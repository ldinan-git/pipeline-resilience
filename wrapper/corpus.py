"""
Tier 4: Cross-org corpus.

In production this hits a central hosted API — anonymized error fingerprints
and fix policies contributed by all customers, queryable by any customer.
No raw data, no column values, no org identity — only structural error patterns
and the fix policies that resolved them.

Today this is a stub. The interface is fixed; the implementation fills in
as the corpus grows. Every resolved incident from any customer is a candidate
for contribution (with consent).
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import re

import requests

log = logging.getLogger("resilience")

CORPUS_API = os.getenv("CORPUS_API_URL", "")  # empty = corpus not yet connected
CORPUS_KEY = os.getenv("CORPUS_API_KEY", "")


def fingerprint(error: Exception) -> str:
    """
    Structural fingerprint of an error — vendor + error class + pattern.
    Strips org-specific values (numbers, paths, IDs) so errors from different
    orgs hitting the same root cause share the same fingerprint.
    """
    msg = str(error)
    # Remove specific values, keep structure
    msg = re.sub(r"\b\d+(\.\d+)?\b", "<N>", msg)        # numbers
    msg = re.sub(r"'[^']{1,80}'", "<VAL>", msg)          # quoted strings
    msg = re.sub(r'"[^"]{1,80}"', "<VAL>", msg)
    msg = re.sub(r"[\\/][^\s,]+", "<PATH>", msg)         # file paths
    error_class = type(error).__name__
    raw = f"{error_class}::{msg}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def lookup(error: Exception) -> dict | None:
    """
    Query the cross-org corpus for a known fix.
    Returns {"operation": ..., "label": ..., "match_count": N} or None.
    """
    if not CORPUS_API:
        return None  # corpus not connected yet
    try:
        fp = fingerprint(error)
        resp = requests.get(
            f"{CORPUS_API}/lookup",
            params={"fingerprint": fp},
            headers={"X-API-Key": CORPUS_KEY},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("found"):
                log.info(f"[corpus:tier4] Match found — seen {data['match_count']} times across orgs")
                return data
    except Exception as e:
        log.debug(f"[corpus:tier4] Unavailable: {e}")
    return None


def contribute(error: Exception, fix_policy: dict, label: str, vertical: str = "financial_services") -> None:
    """
    Anonymously contribute a resolved incident to the corpus.
    Only the error fingerprint + fix policy + industry vertical are sent.
    No org identity, no data values, no column names.
    """
    if not CORPUS_API:
        return
    try:
        payload = {
            "fingerprint": fingerprint(error),
            "error_class": type(error).__name__,
            "fix_policy":  fix_policy,
            "label":       label,
            "vertical":    vertical,
        }
        requests.post(
            f"{CORPUS_API}/contribute",
            json=payload,
            headers={"X-API-Key": CORPUS_KEY},
            timeout=5,
        )
        log.info("[corpus:tier4] Contributed resolved incident to cross-org corpus")
    except Exception as e:
        log.debug(f"[corpus:tier4] Contribution failed: {e}")
