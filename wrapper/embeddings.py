"""
Embedding generation and similarity search.

Local dev: nomic-embed-text via Ollama, cosine similarity in numpy.
Production: same embedding model, similarity search via pgvector:
  SELECT *, 1 - (embedding <=> $query) AS similarity
  FROM corpus_entries
  WHERE vertical = $vertical
  ORDER BY embedding <=> $query
  LIMIT 5;

The embedding model must be consistent between contribution and lookup —
switching models requires re-embedding the entire corpus.
"""
from __future__ import annotations
import logging

import numpy as np
import ollama

log = logging.getLogger("resilience")

EMBED_MODEL          = "nomic-embed-text"
SIMILARITY_THRESHOLD = 0.82   # tunable: lower = more matches, higher = stricter


def embed(text: str) -> list[float]:
    """Return a float vector for the given text."""
    response = ollama.embeddings(model=EMBED_MODEL, prompt=text)
    return response["embedding"]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def best_match(
    query_embedding: list[float],
    candidates: list[dict],          # each must have "embedding" key (list[float])
    threshold: float = SIMILARITY_THRESHOLD,
) -> tuple[dict | None, float]:
    """
    Find the closest candidate above threshold.
    Returns (best_candidate, similarity) or (None, 0.0).
    """
    best_sim  = 0.0
    best_item = None
    for item in candidates:
        sim = cosine_similarity(query_embedding, item["embedding"])
        if sim > best_sim:
            best_sim  = sim
            best_item = item
    if best_sim >= threshold:
        return best_item, best_sim
    return None, best_sim
