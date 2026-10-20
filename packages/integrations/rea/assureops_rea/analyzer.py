"""Source/build analysis for release evidence (integration plan I6).

Two analyzers behind one normalized result:

* `rea`: the pinned upstream REA tool (github.com/morluto/rea) run as a
  separate Node process in a scrubbed, time-limited subprocess. Used only when
  `REA_COMMAND` is configured and its entry file matches the pinned SHA-256 in
  `pin.json`; otherwise it reports `not_installed` as an explicit capability gap.
* `builtin-static`: an AssureOps-owned collector for Python and JavaScript
  snapshots: file hashes, HTTP route literals, model/prompt/policy indicators
  and dependency manifests. Declared language limits are part of the result.

Results carry source/build identity (snapshot hash, per-file hashes) and
coverage gaps. They never execute customer code and never authorize anything;
unknown components they reveal make the release partial so evidence is not
reused.
"""

import hashlib
import io
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

PIN = Path(__file__).with_name("pin.json")
BUILTIN_VERSION = "builtin-static-1.0.0"
MAX_FILES = 2000
MAX_FILE_BYTES = 1_000_000
SUPPORTED = {".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescript"}
CONFIG_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".txt", ".md", ".prompt"}

ROUTE_PATTERNS = [
    (re.compile(r"""@(?:app|router|api)\.(get|post|put|patch|delete)\(\s*['"]([^'"]+)['"]"""), "decorator"),
    (re.compile(r"""\.(get|post|put|patch|delete)\(\s*['"](/[^'"]*)['"]"""), "call"),
    (re.compile(r"""path\s*==\s*['"](/[^'"]*)['"]"""), "comparison"),
    (re.compile(r"""path\.startswith\(\s*['"](/[^'"]*)['"]"""), "prefix"),
    (re.compile(r"""path\s+(?:not\s+)?in\s+\(([^)]*)\)"""), "membership"),
]
MODEL_HINT = re.compile(r"""(?i)\b(model|engine|llm)\b\s*[:=]\s*['"]([A-Za-z0-9_./:-]{3,80})['"]""")
POLICY_HINT = re.compile(r"(?i)\b(def|function)\s+(policy|authorize|permission|guard)\w*")


class AnalysisError(Exception):
    pass


def _safe_members(archive: zipfile.ZipFile):
    for info in archive.infolist():
        name = PurePosixPath(info.filename)
        if info.is_dir() or name.is_absolute() or ".." in name.parts:
            continue
        yield info


def read_snapshot(data: bytes) -> dict[str, bytes]:
    """Zip snapshot -> {relative path: bytes}. Path traversal entries, oversized files and excess files are skipped."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise AnalysisError("snapshot is not a zip archive")
    files = {}
    for info in _safe_members(archive):
        if len(files) >= MAX_FILES:
            break
        if info.file_size > MAX_FILE_BYTES:
            continue
        files[str(PurePosixPath(info.filename))] = archive.read(info)
    return files


def builtin(files: dict[str, bytes]) -> dict:
    observations, skipped, languages = [], [], set()
    file_hashes = {}
    for path, data in sorted(files.items()):
        suffix = PurePosixPath(path).suffix.lower()
        digest = hashlib.sha256(data).hexdigest()
        file_hashes[path] = digest
        name = PurePosixPath(path).name
        if name in ("requirements.txt", "package.json", "pyproject.toml", "package-lock.json"):
            observations.append({"kind": "dependency_manifest", "id": f"deps:{path}", "location": path, "evidence": digest[:16]})
        if suffix not in SUPPORTED:
            if suffix not in CONFIG_SUFFIXES and suffix not in (".html", ".css", ".cmd", ".sh"):
                skipped.append(path)
            if "prompt" in path.lower() or "policy" in path.lower():
                observations.append({"kind": "prompt_or_policy_file", "id": f"file:{path}", "location": path, "evidence": digest[:16]})
            continue
        languages.add(SUPPORTED[suffix])
        observations.append({"kind": "code_file", "id": f"file:{path}", "location": path, "evidence": digest})
        text = data.decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern, how in ROUTE_PATTERNS:
                for m in pattern.finditer(line):
                    if how == "membership":
                        for lit in re.findall(r"""['"](/[^'"]*)['"]""", m.group(1)):
                            observations.append({"kind": "route", "id": f"route:{lit}", "location": f"{path}:{lineno}", "evidence": how})
                        continue
                    route = m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)
                    observations.append({"kind": "route", "id": f"route:{route}", "location": f"{path}:{lineno}", "evidence": how})
            if (m := MODEL_HINT.search(line)):
                observations.append({"kind": "model_reference", "id": f"model:{m.group(2)}", "location": f"{path}:{lineno}", "evidence": "literal"})
            if POLICY_HINT.search(line):
                observations.append({"kind": "policy_logic", "id": f"policy:{path}:{lineno}", "location": f"{path}:{lineno}", "evidence": "definition"})
    seen, unique = set(), []
    for o in observations:
        key = (o["kind"], o["id"], o["location"])
        if key not in seen:
            seen.add(key)
            unique.append(o)
    gaps = []
    if skipped:
        gaps.append(f"{len(skipped)} files in unsupported formats were not analyzed")
    if not languages:
        gaps.append("no supported source language found (Python, JavaScript, TypeScript)")
    gaps.append("static observations only: runtime behaviour is not inferred from source equality")
    return {"analyzer": BUILTIN_VERSION, "observations": unique, "file_hashes": file_hashes,
            "coverage": {"languages": sorted(languages), "files": len(files), "skipped": skipped[:50], "limits": "Python/JS/TS literals only"},
            "gaps": gaps}


def rea_home() -> Path:
    return Path(os.environ.get("REA_HOME", "D:/AssureOpsModels/rea-pkg"))


def rea_status() -> dict:
    """REA is used only when the installed package matches the reviewed pin (npm integrity and entry hash)."""
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    home = rea_home()
    entry = home / pin["entry"]
    if not entry.exists():
        return {"available": False, "reason": f"not_installed: no REA entry at {entry}", "pin": pin}
    try:
        lock = json.loads((home / "package-lock.json").read_text(encoding="utf-8"))
        integrity = lock["packages"]["node_modules/rea-agents"]["integrity"]
    except (OSError, KeyError, ValueError):
        integrity = None
    if integrity != pin["npm_integrity"] or hashlib.sha256(entry.read_bytes()).hexdigest() != pin["entry_sha256"]:
        return {"available": False, "reason": "pin_mismatch: installed REA does not match the reviewed pin", "pin": pin}
    return {"available": True, "reason": "pinned", "pin": pin}


def run_rea(snapshot_dir: Path, timeout: int = 300) -> dict:
    """Run pinned REA on an extracted snapshot directory in a scrubbed, time-limited process; normalize its Evidence."""
    status = rea_status()
    if not status["available"]:
        raise AnalysisError(status["reason"])
    pin = status["pin"]
    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA") if k in os.environ}
    try:
        proc = subprocess.run(["node", str(rea_home() / pin["entry"]), pin["operation"], str(snapshot_dir), "--json"], capture_output=True,
                              timeout=timeout, env=env, cwd=str(snapshot_dir))
    except subprocess.TimeoutExpired:
        raise AnalysisError(f"REA exceeded its {timeout} s limit")
    if proc.returncode != 0:
        raise AnalysisError(f"REA exited with {proc.returncode}")
    try:
        raw = json.loads(proc.stdout)
        graph = raw["normalized_result"]["graph"]
        nodes = graph["nodes"]
    except (ValueError, KeyError, TypeError):
        raise AnalysisError("unsupported REA result schema: quarantined, no parser fallback")
    observations = []
    for node in nodes:
        for obs in node.get("observations", []):
            props = obs.get("properties") or {}
            if node["kind"] == "artifact" and props.get("path"):
                observations.append({"kind": "rea_artifact", "id": f"file:{props['path']}", "location": props["path"],
                                     "evidence": (node.get("identity") or {}).get("sha256")})
            elif node["kind"] != "artifact":
                observations.append({"kind": f"rea_{node['kind']}", "id": obs.get("label"), "location": props.get("path"), "evidence": "structural"})
    stats = raw["normalized_result"].get("statistics", {})
    return {"analyzer": f"rea@{pin['package'].split('@')[1]}+{pin['commit'][:8]}", "evidence_id": raw.get("evidence_id"),
            "subject_sha256": ((raw.get("subject") or {}).get("digest") or {}).get("sha256"),
            "observations": observations, "coverage": {**graph.get("coverage", {}), "statistics": stats},
            "gaps": [f"REA: {limit}" for limit in raw.get("limitations", [])], "file_hashes": {}}


def compare_with_manifest(result: dict, manifest: dict, code_map: dict[str, str]) -> dict:
    """Link observations to manifest components. `code_map` maps component IDs to snapshot paths whose hash the manifest fingerprints."""
    comps = manifest.get("components", {})
    identity = []
    for component, path in code_map.items():
        observed = result["file_hashes"].get(path)
        declared = comps.get(component, {}).get("fingerprint")
        if observed is None:
            identity.append({"component": component, "path": path, "status": "not_in_snapshot"})
        else:
            identity.append({"component": component, "path": path, "status": "matches" if observed == declared else "differs",
                             "observed": observed[:16], "declared": (declared or "")[:16]})
    model_refs = sorted({o["id"] for o in result["observations"] if o["kind"] == "model_reference"})
    declared_models = {c for c in comps if c.startswith("model:")}
    unknown = []
    if model_refs and not declared_models:
        unknown.append("model references found in source but no model component is declared in the manifest")
    mismatched = [i for i in identity if i["status"] != "matches"]
    if mismatched:
        unknown.append("source/build identity uncertain for " + ", ".join(f"{i['component']} ({i['status']})" for i in mismatched))
    return {"identity": identity, "routes": sorted({o["id"][6:] for o in result["observations"] if o["kind"] == "route"}),
            "model_references": model_refs, "unknown_components": unknown}
