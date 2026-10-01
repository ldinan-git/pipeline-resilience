"""
Pipeline resilience wrapper — quarantine model.

Flow:
  1. Load raw data from CSV
  2. Validate against learned rules → split into clean + quarantine
  3. Auto-fix rows where rules carry a fix_policy (applied by validator)
  4. Run pipeline immediately on clean data — no retries, no crashes
  5. Submit quarantined rows asynchronously for AI triage + human review
  6. If no rules exist yet, warn and run pipeline on all data (unsafe mode)
"""

import functools
import json
import logging
import os
from pathlib import Path

import pandas as pd
import requests

from wrapper.rules import load_rules
from wrapper.validator import validate_and_split

BACKEND_URL   = os.getenv("RESILIENCE_BACKEND", "http://localhost:8000")
ORG_ID        = os.getenv("ORG_ID", "default")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pipeline.log"),
    ],
)
log = logging.getLogger("resilience")


def _submit_quarantine(pipeline_name: str, quarantine_df: pd.DataFrame, violations: dict) -> None:
    """Post quarantined rows to backend for AI triage + human review (non-blocking)."""
    try:
        payload = {
            "pipeline_name": pipeline_name,
            "row_count":     len(quarantine_df),
            "violations":    violations,
            "sample_rows":   quarantine_df.head(20).to_dict(orient="records"),
        }
        resp = requests.post(f"{BACKEND_URL}/api/quarantine", json=payload, timeout=10)
        resp.raise_for_status()
        batch_id = resp.json().get("batch_id", "?")
        log.info(f"[{pipeline_name}] Quarantine batch submitted — {len(quarantine_df)} rows (batch {batch_id[:8]})")
    except Exception as e:
        log.warning(f"[{pipeline_name}] Backend unreachable, saving quarantine locally: {e}")
        Path("data").mkdir(exist_ok=True)
        quarantine_df.to_csv("data/quarantine.csv", index=False)


def resilient_pipeline(name: str):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            csv_path = os.getenv("CSV_PATH", "data/nyc_taxi_sample.csv")
            log.info(f"[{name}] Starting: {fn.__name__}")

            # 1. Load raw data
            raw_df = pd.read_csv(csv_path)
            log.info(f"[{name}] Loaded {len(raw_df)} raw rows")

            # 2. Validate + split
            rules = load_rules(name, org_id=ORG_ID)
            if not rules:
                log.warning(
                    f"[{name}] No validation rules found. "
                    "Run learn_from_sample.py first to generate rules from known-good data."
                )
            else:
                log.info(f"[{name}] Validating with {len(rules)} rules")
                clean_df, quarantine_df, violations = validate_and_split(raw_df, rules)

                auto_fixed   = sum(1 for v in violations.values() if v.get("auto_fixed"))
                n_quarantine = len(quarantine_df)
                log.info(
                    f"[{name}] {len(clean_df)} rows clean, "
                    f"{auto_fixed} columns auto-fixed, "
                    f"{n_quarantine} rows quarantined"
                )

                # 3. Write clean data back so the pipeline reads it
                clean_df.to_csv(csv_path, index=False)

                # 4. Submit quarantine batch (non-blocking)
                if n_quarantine > 0:
                    _submit_quarantine(name, quarantine_df, violations)

            # 5. Run pipeline on clean data — should succeed
            try:
                result = fn(*args, **kwargs)
                n = len(clean_df) if rules else len(raw_df)
                log.info(f"[{name}] Pipeline succeeded on {n} rows")
                return result
            except Exception as e:
                # Unexpected failure: data passed validation but pipeline still broke.
                # This means either a rule is missing or the pipeline has a bug.
                log.error(
                    f"[{name}] Unexpected failure — no rule caught this. "
                    f"Consider adding a rule. {type(e).__name__}: {e}"
                )
                raise

        return wrapper
    return decorator
