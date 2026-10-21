"""Phase R enablement decision: choose the retrieval method on the development split, report it on the held-out split.

    python scripts/retrieval_decision.py

Methods: BM25 (lexical baseline), dense (BGE-small), and reciprocal-rank fusion with dense
weights 1, 2 and 3. Selection uses only phase-R-dev-v2.json; the held-out result of the chosen
method is reported once. Output: var/benchmarks/retrieval-decision.json.
"""

import json
from pathlib import Path

from assureops_ai import retrieval, router

ROOT = Path(__file__).resolve().parent.parent
Q = ROOT / "profiles" / "qualification"
METHODS = ["bm25", "dense", "rrf_w1", "rrf_w2", "rrf_w3"]


def evaluate(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    corpus, queries = data["corpus"], data["queries"]
    route = router.resolve("R", False)
    client = router.encoder_client(route)
    docs = client.embed([f"{d['title']}. {d['text']}" for d in corpus], route.model).parsed["result"]
    qvec = client.embed([f"Represent this sentence for searching relevant passages: {q['q']}" for q in queries], route.model).parsed["result"]
    index = retrieval.index([{"id": d["id"], "title": d["title"], "text": d["text"]} for d in corpus])
    hits = {m: 0 for m in METHODS}
    for q, v in zip(queries, qvec):
        lex = [c.source_id for _, c in index.search(q["q"], k=10)]
        dense = [d["id"] for _, d in sorted(((sum(a * b for a, b in zip(v, dv)), d) for dv, d in zip(docs, corpus)), key=lambda x: -x[0])]
        ranked = {"bm25": lex[:3], "dense": dense[:3]}
        for w in (1, 2, 3):
            fused = {}
            for rank, i in enumerate(lex):
                fused[i] = fused.get(i, 0) + 1 / (60 + rank)
            for rank, i in enumerate(dense):
                fused[i] = fused.get(i, 0) + w / (60 + rank)
            ranked[f"rrf_w{w}"] = [i for i, _ in sorted(fused.items(), key=lambda x: -x[1])[:3]]
        for m in METHODS:
            hits[m] += bool(set(ranked[m]) & set(q["relevant"]))
    return {m: round(hits[m] / len(queries), 3) for m in METHODS} | {"queries": len(queries), "model": route.model}


def main():
    dev = evaluate(Q / "phase-R-dev-v2.json")
    chosen = max(METHODS, key=lambda m: (dev[m], m != "bm25"))  # ties go to the method using the qualified encoder
    held = evaluate(Q / "phase-R-holdout-v2.json")
    out = {"selected_on": "development split only", "development": dev, "chosen": chosen, "held_out_recall_at_3": held[chosen],
           "held_out_all_methods": held, "note": "Held-out numbers for the other methods are reported for transparency, not used for selection."}
    target = ROOT / "var" / "benchmarks" / "retrieval-decision.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
