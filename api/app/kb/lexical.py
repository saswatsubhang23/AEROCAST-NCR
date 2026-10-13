"""Exact-word retrieval (BM25) to complement the embedding search.

Embeddings are good at meaning and weak at names and numbers: "Mandir Marg" and "Anand Vihar" are just two place-like
strings to them. BM25 over the same chunks finds the passages that literally contain the words asked for. The two rankings
are fused in `KnowledgeBaseService.search`, which keeps the cosine similarity as the displayed relevance.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "by", "for", "from", "with", "is", "are", "was", "were", "be", "been",
    "what", "which", "who", "whom", "when", "where", "why", "how", "does", "do", "did", "this", "that", "these", "those", "about",
    "me", "my", "show", "tell", "give", "please", "can", "could", "would", "should", "it", "its", "as", "than", "then", "there",
    "has", "have", "had", "any", "all", "some", "into", "per", "row", "rows", "columns", "document", "file", "table",
}


def normalise(text: str) -> str:
    t = text.lower()
    t = re.sub(r"pm\s?2\.?5|pm[₂]\.?[₅]", "pm25", t)
    t = re.sub(r"pm\s?10|pm[₁][₀]", "pm10", t)
    t = re.sub(r"\bno\s?2\b|no[₂]", "no2", t)
    t = re.sub(r"\bso\s?2\b|so[₂]", "so2", t)
    t = re.sub(r"\bo\s?3\b|o[₃]", "o3", t)
    return t


def tokens(text: str, drop_stop: bool = True) -> list[str]:
    out = _WORD.findall(normalise(text))
    return [t for t in out if len(t) >= 2 and not (drop_stop and t in STOP)]


@dataclass
class LexicalHit:
    key: str  # chunk id
    score: float
    matched: int  # distinct query terms found in the chunk
    total: int  # distinct query terms
    coverage: float  # matched / total


class LexicalIndex:
    K1, B = 1.4, 0.75

    def __init__(self, items: list[tuple[str, str, str]]):
        """items: (chunk id, document id, text)."""
        self._ids: list[str] = []
        self._docs: list[str] = []
        self._tf: list[Counter] = []
        self._len: list[int] = []
        df: Counter = Counter()
        for cid, did, text in items:
            toks = tokens(text, drop_stop=False)
            tf = Counter(toks)
            self._ids.append(cid)
            self._docs.append(did)
            self._tf.append(tf)
            self._len.append(len(toks))
            df.update(tf.keys())
        self._n = len(self._ids)
        self._avg = (sum(self._len) / self._n) if self._n else 0.0
        self._df = df

    def __len__(self) -> int:
        return self._n

    def search(self, query: str, doc_ids: set[str], n: int) -> list[LexicalHit]:
        terms = sorted(set(tokens(query)))
        if not terms or not self._n:
            return []
        idf = {t: math.log(1 + (self._n - self._df.get(t, 0) + 0.5) / (self._df.get(t, 0) + 0.5)) for t in terms}
        hits: list[LexicalHit] = []
        for i, tf in enumerate(self._tf):
            if self._docs[i] not in doc_ids:
                continue
            matched = [t for t in terms if t in tf]
            if not matched:
                continue
            norm = self.K1 * (1 - self.B + self.B * self._len[i] / (self._avg or 1.0))
            score = sum(idf[t] * tf[t] * (self.K1 + 1) / (tf[t] + norm) for t in matched)
            hits.append(LexicalHit(self._ids[i], score, len(matched), len(terms), len(matched) / len(terms)))
        hits.sort(key=lambda h: -h.score)
        return hits[:n]
