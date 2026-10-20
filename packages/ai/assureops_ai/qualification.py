"""Per-phase qualification against synthetic holdouts (integration plan §2).

A phase/provider/model is qualified only with zero critical false-support cases
and the phase's quality floor; every count, abstention and failure is kept in
the record. Generation phases call the model through the same provider and
validation the production path uses.
"""

import json
import re
import time
from pathlib import Path

from . import prompts, retrieval, router, validation
from .registry import PHASES, constrained

HOLDOUTS = Path(__file__).resolve().parents[3] / "profiles" / "qualification"
READY_CLAIM = re.compile(r"\b(is|are|now) (fully )?ready\b|\bready for (release|deployment|production)\b|\bno blocking\b", re.I)
SUPPORT_WORDS = re.compile(r"\b(supported|passed|passes|satisfied|meets|is met)\b", re.I)
EXCEPTION = re.compile(r"\b(not|fail|failed|failing|failure|except|other than|apart from|besides|unverified|blocked)\b", re.I)
RESOLVED_CLAIM = re.compile(r"\b(has been|was|is now) (resolved|closed|fixed)\b|\bno longer (open|occurring)\b", re.I)


def load(phase: str) -> dict:
    return json.loads((HOLDOUTS / f"phase-{phase}-holdout.json").read_text(encoding="utf-8"))


def holdout_digest(phase: str) -> str:
    import hashlib

    return hashlib.sha256((HOLDOUTS / f"phase-{phase}-holdout.json").read_bytes()).hexdigest()[:16]


def _generate(client, model, phase, data, ctx, budget=None):
    from .service import BUDGET

    return client.generate(model=model, system=prompts.SYSTEM[phase], user=validation.minimize(prompts.user_message(phase, data)),
                           max_tokens=budget or BUDGET.get(phase, 1500),
                           json_mode=client.json_mode(model) if hasattr(client, "json_mode") else "json_object", schema=constrained(phase, ctx))


def critical_false_support_f(case: dict, output: dict) -> list[str]:
    problems = []
    text = " ".join(s["text"] for s in output.get("sections", []))
    if case["gate"] != "ready" and READY_CLAIM.search(text):
        problems.append(f"describes a {case['gate']} release as ready")
    sentences = re.split(r"(?<=[.;!?])\s+", text)
    for cid in case["failed_controls"]:
        for sentence in sentences:
            if re.search(rf"\b{cid}\b", sentence) and SUPPORT_WORDS.search(sentence) and not EXCEPTION.search(sentence):
                problems.append(f"describes failed control {cid} as supported: {sentence[:100]!r}")
    return problems


def run_generation(phase: str, route: router.Route, log=print) -> dict:
    client = router.generation_client(route)
    suite = load(phase)["cases"]
    c = {"cases": len(suite), "schema_valid": 0, "valid": 0, "unsupported_claims": 0, "invalid_output": 0, "provider_errors": 0,
         "critical_false_support": 0, "abstentions": 0}
    quality, details, latencies, tokens = [], [], [], 0
    for case in suite:
        if phase == "A":
            from assureops_domain.profile import control_catalog

            data = {"application_purpose": case["purpose"],
                    "controls": {k: f"{v['name']}: {v['description']}" for k, v in control_catalog()["controls"].items()},
                    "sources": case["sources"]}
            ctx = {"sources": {s["source_id"]: s["text"] for s in case["sources"]}}
        elif phase == "B":
            data = {"tests": case["tests"], "components": case["components"], "requirements": []}
            ctx = {"test_ids": [t["id"] for t in case["tests"]], "component_ids": [x["id"] for x in case["components"]]}
        elif phase == "C":
            from assureops_connectors import templates

            data = {"requirements": case["requirements"], "templates": templates.catalogue(), "actors": case["actors"],
                    "allowed_paths": case["allowed_paths"]}
            ctx = {"actors": case["actors"], "templates": [t["id"] for t in templates.catalogue()]}
        elif phase == "E":
            data = {"incident": case["incident"], "events": case["events"], "tests": case["tests"]}
            ctx = {"sources": {e["source_id"]: e["text"] for e in case["events"]}, "test_ids": [t["id"] for t in case["tests"]]}
        elif phase == "F":
            data = {"facts": case["facts"]}
            ctx = {"facts": {f["id"]: f["text"] for f in case["facts"]}}
        else:
            raise ValueError(phase)
        result = _generate(client, route.model, phase, data, ctx)
        tokens += (result.usage or {}).get("total_tokens") or 0
        if result.latency_ms:
            latencies.append(result.latency_ms)
        if not result.ok:
            key = "invalid_output" if result.status == "invalid_output" else "provider_errors"
            c[key] += 1
            details.append({"case": case["id"], "status": result.status, "error": result.error})
            log(f"  {case['id']}: {result.status} {result.error or ''}")
            continue
        out = result.parsed
        check = validation.validate(phase, out, ctx)
        if check["status"] != "invalid_output":
            c["schema_valid"] += 1
        c[check["status"] if check["status"] != "valid" else "valid"] += 1
        if out.get("unknowns") or out.get("gaps"):
            c["abstentions"] += 1
        critical, score = [], None
        if check["status"] != "invalid_output":
            if phase == "A":
                got = {r["control"] for r in out["requirements"]}
                score = len(got & set(case["expected_controls"])) / len(case["expected_controls"])
            elif phase == "B":
                got = {(link["test_id"], link["component_id"]) for link in out["links"]}
                exp = {tuple(x) for x in case["expected"]}
                score = len(got & exp) / len(exp)
            elif phase == "C":
                got = {t["control"] for t in out["tests"]}
                score = len(got & set(case["expected_controls"])) / len(case["expected_controls"])
            elif phase == "E":
                got = set(out["retest_suggestions"])
                score = len(got & set(case["expected_retests"])) / len(case["expected_retests"])
                if RESOLVED_CLAIM.search(out["summary"]):
                    critical.append("summary claims an open incident is resolved")
            elif phase == "F":
                critical = critical_false_support_f(case, out)
        if score is not None:
            quality.append(score)
        c["critical_false_support"] += bool(critical)
        details.append({"case": case["id"], "status": check["status"], "problems": check["problems"][:3], "critical": critical, "score": score})
        log(f"  {case['id']}: {check['status']} score={score} {critical or ''} {check['problems'][:2] or ''}")
    answered = c["cases"] - c["provider_errors"]
    c["schema_valid_rate"] = round(c["schema_valid"] / answered, 3) if answered else 0
    c["valid_rate"] = round(c["valid"] / answered, 3) if answered else 0
    c["mean_ground_truth_recall"] = round(sum(quality) / len(quality), 3) if quality else None
    c["median_latency_ms"] = sorted(latencies)[len(latencies) // 2] if latencies else None
    c["total_tokens"] = tokens
    floor = {"A": 0.5, "B": 0.4, "C": 0.5, "E": 0.5}.get(phase)
    qualified = (answered == c["cases"] and c["critical_false_support"] == 0 and c["schema_valid_rate"] >= 0.75
                 and c["valid_rate"] >= (0.75 if phase == "F" else 0.5)
                 and (floor is None or (c["mean_ground_truth_recall"] or 0) >= floor))
    return {"metrics": c, "details": details, "qualified": qualified}


def run_classifier_d(route: router.Route, log=print) -> dict:
    suite = load("D")["cases"]
    client = router.encoder_client(route)
    result = client.classify_pairs([(x["premise"], x["hypothesis"]) for x in suite], route.model)
    if not result.ok:
        return {"metrics": {"cases": len(suite), "provider_errors": len(suite), "error": result.error}, "details": [], "qualified": False}
    correct = critical = 0
    details = []
    for case, scores in zip(suite, result.parsed["result"]):
        label = max(scores, key=lambda s: s["score"])["label"]
        ok = label == case["label"]
        crit = case["label"] == "contradiction" and label == "entailment"  # false support: a contradiction read as support
        correct += ok
        critical += crit
        details.append({"case": case["id"], "gold": case["label"], "predicted": label, "critical": crit})
        log(f"  {case['id']}: gold={case['label']} predicted={label}{' CRITICAL' if crit else ''}")
    acc = correct / len(suite)
    return {"metrics": {"cases": len(suite), "accuracy": round(acc, 3), "critical_false_support": critical, "latency_ms": result.latency_ms},
            "details": details, "qualified": critical == 0 and acc >= 0.7}


def run_screening_g(route: router.Route, log=print) -> dict:
    suite = load("G")["cases"]
    client = router.encoder_client(route)
    correct, details = 0, []
    for case in suite:
        status, score = client.screen(case["text"], route.model)
        if status != "succeeded":
            details.append({"case": case["id"], "status": status})
            log(f"  {case['id']}: {status}")
            continue
        flagged = score >= 0.5
        correct += flagged == case["malicious"]
        details.append({"case": case["id"], "malicious": case["malicious"], "score": round(score, 4), "flagged": flagged})
        log(f"  {case['id']}: malicious={case['malicious']} score={score:.4f}")
        time.sleep(0.3)
    answered = sum(1 for d in details if "score" in d)
    acc = correct / answered if answered else 0
    return {"metrics": {"cases": len(suite), "answered": answered, "accuracy": round(acc, 3), "critical_false_support": 0,
                        "note": "screening is advisory and never authorizes an action"},
            "details": details, "qualified": answered == len(suite) and acc >= 0.8}


def run_retrieval_r(route: router.Route, log=print) -> dict:
    data = load("R")
    corpus, queries = data["corpus"], data["queries"]
    bm25 = retrieval.index([{"id": d["id"], "title": d["title"], "text": d["text"]} for d in corpus])
    client = router.encoder_client(route)
    doc_vec = client.embed([f"{d['title']}. {d['text']}" for d in corpus], route.model)
    if not doc_vec.ok:
        return {"metrics": {"error": doc_vec.error}, "details": [], "qualified": False}
    q_vec = client.embed([f"Represent this sentence for searching relevant passages: {q['q']}" for q in queries], route.model)
    docs = doc_vec.parsed["result"]
    hits = {"bm25": 0, "dense": 0, "hybrid": 0}
    details = []
    for q, qv in zip(queries, q_vec.parsed["result"]):
        lex = [c.source_id for _, c in bm25.search(q["q"], k=3)]
        sims = sorted(((sum(a * b for a, b in zip(qv, dv)), d["id"]) for dv, d in zip(docs, corpus)), reverse=True)
        dense = [i for _, i in sims[:3]]
        fused = {}
        for rank, i in enumerate(lex):
            fused[i] = fused.get(i, 0) + 1 / (60 + rank)
        for rank, (_, i) in enumerate(sims):
            fused[i] = fused.get(i, 0) + 1 / (60 + rank)
        hybrid = [i for i, _ in sorted(fused.items(), key=lambda x: -x[1])[:3]]
        for name, got in (("bm25", lex), ("dense", dense), ("hybrid", hybrid)):
            hits[name] += bool(set(got) & set(q["relevant"]))
        details.append({"q": q["q"], "bm25": lex, "dense": dense, "hybrid": hybrid, "relevant": q["relevant"]})
        log(f"  {q['q'][:50]!r}: bm25={lex[:1]} dense={dense[:1]} hybrid={hybrid[:1]} relevant={q['relevant']}")
    n = len(queries)
    recall = {k: round(v / n, 3) for k, v in hits.items()}
    return {"metrics": {"queries": n, "recall_at_3": recall, "critical_false_support": 0},
            "details": details, "qualified": recall["hybrid"] >= recall["bm25"] and recall["hybrid"] >= 0.8}


def run(phase: str, route: router.Route, log=print) -> dict:
    if PHASES[phase].kind == "generate":
        return run_generation(phase, route, log)
    if phase == "D":
        return run_classifier_d(route, log)
    if phase == "G":
        return run_screening_g(route, log)
    if phase == "R":
        return run_retrieval_r(route, log)
    raise ValueError(phase)
