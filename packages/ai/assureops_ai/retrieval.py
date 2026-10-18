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
