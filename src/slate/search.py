"""Pure-Python BM25 over expertise records (mulch parity: k1=1.5, b=0.75).

Computed on the fly — no index cache in v0.1; ms-scale at realistic corpus
sizes. The tokenizer mirrors mulch's JS exactly (ASCII \\w, hyphens kept).
"""

from __future__ import annotations

import math
import re
from collections import Counter

from slate import schema

BM25_K1 = 1.5
BM25_B = 0.75

_PUNCT_RE = re.compile(r"[^\w\s-]", re.ASCII)


def tokenize(text: str) -> list[str]:
    return _PUNCT_RE.sub(" ", text.lower()).split()


def extract_text(record: dict) -> str:
    """Concatenate a record's searchable fields (type fields + tags)."""
    parts: list[str] = []

    def add(value) -> None:
        if isinstance(value, str) and value.strip():
            parts.append(value)
        elif isinstance(value, list):
            joined = " ".join(v for v in value if isinstance(v, str))
            if joined.strip():
                parts.append(joined)

    type_def = schema.TYPES.get(record.get("type", ""))
    if type_def is not None:
        for key in (*type_def.required, *type_def.optional):
            add(record.get(key))
    else:
        # Unknown type (tolerant reader): search every string-ish field.
        for key, value in record.items():
            if key in ("id", "type", "classification", "recorded_at", "status"):
                continue
            add(value)
    add(record.get("tags"))
    return " ".join(parts)


def search_records(
    records: list[dict], query: str, *, boost_factor: float = 0.0
) -> list[tuple[dict, float]]:
    """BM25-rank records against query; only positive scores, best first.

    boost_factor > 0 applies mulch's confirmation boost:
    score * (1 + boost_factor * len(outcomes)).
    """
    if not records or not query.strip():
        return []
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    docs = [(record, tokenize(extract_text(record))) for record in records]
    total_len = sum(len(tokens) for _, tokens in docs)
    avg_len = total_len / len(docs) if docs else 0.0
    if avg_len == 0.0:
        return []  # nothing tokenizable anywhere — no match is possible

    doc_freq: Counter[str] = Counter()
    for _, tokens in docs:
        doc_freq.update(set(tokens))
    n_docs = len(docs)
    idf = {
        term: math.log((n_docs - df + 0.5) / (df + 0.5) + 1) for term, df in doc_freq.items()
    }

    results: list[tuple[dict, float]] = []
    for record, tokens in docs:
        tf = Counter(tokens)
        score = 0.0
        for term in query_tokens:
            freq = tf.get(term, 0)
            term_idf = idf.get(term, 0.0)
            numerator = freq * (BM25_K1 + 1)
            denominator = freq + BM25_K1 * (1 - BM25_B + BM25_B * (len(tokens) / avg_len))
            score += term_idf * (numerator / denominator)
        if score > 0:
            if boost_factor > 0:
                score *= 1 + boost_factor * len(record.get("outcomes") or [])
            results.append((record, score))

    results.sort(key=lambda item: -item[1])  # stable: ties keep insertion order
    return results
