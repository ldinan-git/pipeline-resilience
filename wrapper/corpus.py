"""
Tier 4: Cross-org corpus.

Architecture:
  Contribution  — when a human resolves an incident, the anonymized error
                  fingerprint + fix policy is embedded and stored.
  Lookup        — incoming error is embedded; cosine similarity finds the
                  closest stored fix above the confidence threshold.

Local dev:  SQLite corpus_entries table, similarity in numpy.
Production: Central hosted API — same interface, pgvector backend.
            Set CORPUS_API_URL + CORPUS_API_KEY to activate.

Anonymization guarantee:
  Only the structural error pattern is embedded — specific values, paths,
  org names, and column values are stripped before embedding.
  No customer data leaves the customer's environment in identifiable form.
"""
from __future__ import annotations
import json
import logging
import os
import re

import requests

from wrapper.embeddings import embed, best_match, normalize_error

log = logging.getLogger("resilience")

CORPUS_API = os.getenv("CORPUS_API_URL", "")
CORPUS_KEY = os.getenv("CORPUS_API_KEY", "")


# ── Fingerprinting ─────────────────────────────────────────────────────────────


def _hash(normalized: str) -> str:
    import hashlib
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


# ── Local corpus (SQLite + numpy) ─────────────────────────────────────────────

def _local_lookup(normalized: str) -> dict | None:
    from backend.database import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM corpus_entries ORDER BY applied_count DESC"
        ).fetchall()

    if not rows:
        return None

    candidates = []
    for row in rows:
        try:
            candidates.append({
                **dict(row),
                "embedding": json.loads(row["embedding"]),
            })
        except Exception:
            continue

    try:
        query_vec = embed(normalized)
    except Exception as e:
        log.warning(f"[corpus] Embedding model unavailable: {e}")
        return None

    match, similarity = best_match(query_vec, candidates)
    if match:
        log.info(
            f"[corpus:tier4] Match — similarity={similarity:.3f}, "
            f"seen {match['applied_count']} times, label='{match['label']}'"
        )
        return {
            "found":       True,
            "operation":   json.loads(match["fix_policy"]),
            "label":       match["label"],
            "match_count": match["applied_count"],
            "similarity":  round(similarity, 3),
        }

    log.debug(f"[corpus] Best similarity {similarity:.3f} below threshold — no match")
    return None


def _local_contribute(normalized: str, fp: str, fix_policy: dict, label: str,
                       vertical: str, error_class: str) -> None:
    from backend.database import get_conn
    try:
        embedding = embed(normalized)
    except Exception as e:
        log.warning(f"[corpus] Cannot embed for contribution: {e}")
        return

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, applied_count FROM corpus_entries WHERE fingerprint = ?", (fp,)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE corpus_entries SET applied_count = applied_count + 1, updated_at = datetime('now') WHERE id = ?",
                (existing["id"],),
            )
            log.info(f"[corpus] Updated entry — now seen {existing['applied_count'] + 1} times")
        else:
            conn.execute(
                """INSERT INTO corpus_entries
                     (fingerprint, fingerprint_text, embedding, fix_policy,
                      label, vertical, error_class)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (fp, normalized, json.dumps(embedding),
                 json.dumps(fix_policy), label, vertical, error_class),
            )
            log.info(f"[corpus] New entry added — '{label}'")


# ── Remote corpus (production API) ────────────────────────────────────────────

def _remote_lookup(normalized: str) -> dict | None:
    try:
        query_vec = embed(normalized)
        resp = requests.post(
            f"{CORPUS_API}/lookup",
            json={"embedding": query_vec, "text": normalized},
            headers={"X-API-Key": CORPUS_KEY},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("found"):
                log.info(f"[corpus:tier4] Remote match — seen {data.get('match_count')} times across orgs")
                return data
    except Exception as e:
        log.debug(f"[corpus:tier4] Remote lookup failed: {e}")
    return None


def _remote_contribute(normalized: str, fix_policy: dict, label: str,
                        vertical: str, error_class: str) -> None:
    try:
        query_vec = embed(normalized)
        requests.post(
            f"{CORPUS_API}/contribute",
            json={
                "embedding":   query_vec,
                "text":        normalized,
                "fix_policy":  fix_policy,
                "label":       label,
                "vertical":    vertical,
                "error_class": error_class,
            },
            headers={"X-API-Key": CORPUS_KEY},
            timeout=5,
        )
        log.info("[corpus] Contributed to remote corpus")
    except Exception as e:
        log.debug(f"[corpus] Remote contribution failed: {e}")


# ── Public API ────────────────────────────────────────────────────────────────

def lookup(error: Exception) -> dict | None:
    normalized = normalize_error(error)
    if CORPUS_API:
        return _remote_lookup(normalized)
    return _local_lookup(normalized)


def contribute(error: Exception, fix_policy: dict, label: str,
               vertical: str = "financial_services") -> None:
    normalized  = normalize_error(error)
    fp          = _hash(normalized)
    error_class = type(error).__name__
    if CORPUS_API:
        _remote_contribute(normalized, fix_policy, label, vertical, error_class)
    else:
        _local_contribute(normalized, fp, fix_policy, label, vertical, error_class)
