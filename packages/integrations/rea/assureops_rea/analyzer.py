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


def rea_status() -> dict:
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    command = os.environ.get("REA_COMMAND", "")
    if not command or not pin.get("commit") or not pin.get("entry_sha256"):
        return {"available": False, "reason": "not_installed: REA is not pinned and installed on this host", "pin": pin}
    entry = Path(command.split()[-1])
    if not entry.exists() or hashlib.sha256(entry.read_bytes()).hexdigest() != pin["entry_sha256"]:
        return {"available": False, "reason": "pin_mismatch: installed REA entry does not match the reviewed pin", "pin": pin}
    return {"available": True, "reason": "pinned", "pin": pin}


def run_rea(snapshot_dir: Path, timeout: int = 120) -> dict:
    status = rea_status()
    if not status["available"]:
        raise AnalysisError(status["reason"])
    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if k in os.environ}
    proc = subprocess.run([*os.environ["REA_COMMAND"].split(), "analyze", "--json", str(snapshot_dir)], capture_output=True, timeout=timeout,
                          env=env, cwd=snapshot_dir)
    if proc.returncode != 0:
        raise AnalysisError(f"REA exited with {proc.returncode}")
    try:
        raw = json.loads(proc.stdout)
    except ValueError:
        raise AnalysisError("REA result schema unreadable: quarantined, no parser fallback")
    if not isinstance(raw, dict) or "evidence" not in raw:
        raise AnalysisError("unsupported REA result schema: quarantined")
    return {"analyzer": f"rea@{status['pin']['commit'][:12]}", "observations": raw["evidence"], "coverage": raw.get("coverage", {}),
            "gaps": raw.get("gaps", []), "file_hashes": {}}


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
