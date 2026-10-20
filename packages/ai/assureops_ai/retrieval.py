"""Lexical retrieval (BM25) over approved, authorized sources.

The baseline every model-assisted phase uses. Hybrid retrieval with BGE
embeddings (phase R) is enabled only after it is measured against this
baseline on the same queries; until then results come from here alone.
"""

import math
import re
from dataclasses import dataclass

TOKEN = re.compile(r"[a-z0-9]+")
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "be", "for", "on", "with", "by", "that", "this", "it", "as", "at"}


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP]


@dataclass
class Chunk:
    source_id: str
    title: str
    start: int
    text: str


def chunk(source_id: str, title: str, text: str, size: int = 600) -> list[Chunk]:
    """Paragraph-aligned chunks with character offsets into the original text."""
    out, start, buf = [], 0, ""
    pos = 0
    for para in re.split(r"(\n\s*\n)", text):
        if not buf:
            start = pos
        if len(buf) + len(para) > size and buf.strip():
            out.append(Chunk(source_id, title, start, buf))
            buf, start = "", pos
        buf += para
        pos += len(para)
    if buf.strip():
        out.append(Chunk(source_id, title, start, buf))
    return out


class BM25:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.docs = [tokens(c.text + " " + c.title) for c in chunks]
        self.avg = sum(map(len, self.docs)) / len(self.docs) if self.docs else 0
        df: dict[str, int] = {}
        for doc in self.docs:
            for term in set(doc):
                df[term] = df.get(term, 0) + 1
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 5) -> list[tuple[float, Chunk]]:
        q = tokens(query)
        scored = []
        for doc, ch in zip(self.docs, self.chunks):
            if not doc:
                continue
            tf: dict[str, int] = {}
            for term in doc:
                tf[term] = tf.get(term, 0) + 1
            score = 0.0
            for term in q:
                if term in tf:
                    f = tf[term]
                    score += self.idf.get(term, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(doc) / (self.avg or 1)))
            if score > 0:
                scored.append((round(score, 4), ch))
        scored.sort(key=lambda x: (-x[0], x[1].source_id, x[1].start))
        return scored[:k]


def index(sources: list[dict]) -> BM25:
    chunks = [c for s in sources for c in chunk(s["id"], s["title"], s["text"])]
    return BM25(chunks)


def hybrid_search(sources: list[dict], query: str, k: int = 5) -> tuple[str, list[tuple[float, Chunk]]]:
    """BM25 plus BGE dense retrieval fused by reciprocal rank, used only while phase R is qualified; otherwise BM25 alone."""
    idx = index(sources)
    lexical = idx.search(query, k=max(k, 10))
    try:
        from . import router

        route = router.resolve("R", external_allowed=False)
    except Exception:  # registry or database unavailable: stay with the lexical baseline
        route = None
    if route is None or not route.available or not idx.chunks:
        return "bm25", lexical[:k]
    client = router.encoder_client(route)
    texts = [f"{c.title}. {c.text}"[:2000] for c in idx.chunks]
    vectors = []
    for start in range(0, len(texts), 32):  # the encoder accepts bounded batches
        batch = client.embed(texts[start:start + 32], route.model)
        if not batch.ok:
            return "bm25 (embedding service unavailable)", lexical[:k]
        vectors += batch.parsed["result"]
    qv = client.embed([f"Represent this sentence for searching relevant passages: {query}"], route.model)
    if not qv.ok:
        return "bm25 (embedding service unavailable)", lexical[:k]
    q = qv.parsed["result"][0]
    dense = sorted(((sum(a * b for a, b in zip(q, d)), i) for i, d in enumerate(vectors)), reverse=True)
    fused: dict[int, float] = {}
    positions = {id(c): i for i, c in enumerate(idx.chunks)}
    for rank, (_, chunk) in enumerate(lexical):
        fused[positions[id(chunk)]] = fused.get(positions[id(chunk)], 0) + 1 / (60 + rank)
    for rank, (_, i) in enumerate(dense):
        fused[i] = fused.get(i, 0) + 1 / (60 + rank)
    ranked = sorted(fused.items(), key=lambda x: -x[1])[:k]
    return f"hybrid bm25+{route.model}", [(round(score, 5), idx.chunks[i]) for i, score in ranked]
