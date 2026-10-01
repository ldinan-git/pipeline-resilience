"""
FastAPI backend for the pipeline resilience UI.

New endpoints (quarantine model):
  POST /api/learn               — trigger rule learning from a good-data CSV
  GET  /api/rules               — list all rules for a pipeline
  PUT  /api/rules/{id}          — update rule (toggle auto_fix, edit params)
  DELETE /api/rules/{id}        — delete a rule
  POST /api/quarantine          — receive a quarantine batch from the wrapper
  GET  /api/quarantine          — list quarantine batches
  POST /api/quarantine/{id}/resolve — apply a fix to a batch + update its rule
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import ollama
import re

ORG_ID = os.getenv("ORG_ID", "default")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from backend.database import init_db, get_conn
from backend import store
from wrapper.rules import ValidationRule, save_rule, delete_rule, load_rules
from wrapper.learn import learn_from_sample
from wrapper import corpus
from wrapper.diagnosis import diagnose, TIER_LABELS

app = FastAPI(title="Pipeline Resilience API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/")
def serve_ui():
    return FileResponse(FRONTEND / "index.html")


@app.on_event("startup")
def startup():
    init_db()


# ── Rules ─────────────────────────────────────────────────────────────────────

class RuleUpdate(BaseModel):
    auto_fix:    Optional[bool] = None
    fix_policy:  Optional[dict] = None
    params:      Optional[dict] = None
    confidence:  Optional[str]  = None


@app.get("/api/rules")
def list_rules(pipeline_name: Optional[str] = None):
    with get_conn() as conn:
        if pipeline_name:
            rows = conn.execute(
                "SELECT * FROM rules WHERE pipeline_name = ? AND org_id = ? ORDER BY created_at DESC",
                (pipeline_name, ORG_ID),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM rules WHERE org_id = ? ORDER BY pipeline_name, created_at DESC",
                (ORG_ID,),
            ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["params"]     = json.loads(d["params"]     or "{}")
        d["fix_policy"] = json.loads(d["fix_policy"] or "{}")
        result.append(d)
    return result


@app.put("/api/rules/{rule_id}")
def update_rule(rule_id: int, update: RuleUpdate):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    fields, vals = [], []
    if update.auto_fix is not None:
        fields.append("auto_fix = ?");    vals.append(1 if update.auto_fix else 0)
    if update.fix_policy is not None:
        fields.append("fix_policy = ?"); vals.append(json.dumps(update.fix_policy))
    if update.params is not None:
        fields.append("params = ?");     vals.append(json.dumps(update.params))
    if update.confidence is not None:
        fields.append("confidence = ?"); vals.append(update.confidence)
    if not fields:
        return dict(row)
    vals.append(rule_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE rules SET {', '.join(fields)} WHERE id = ?", vals)
    return {"updated": rule_id}


@app.delete("/api/rules/{rule_id}")
def delete_rule_endpoint(rule_id: int):
    delete_rule(rule_id)
    return {"deleted": rule_id}


# ── Learning ──────────────────────────────────────────────────────────────────

class LearnRequest(BaseModel):
    pipeline_name: str
    csv_path:      str   # path to known-good CSV on the server


@app.post("/api/learn")
def trigger_learning(req: LearnRequest):
    csv_path = Path(req.csv_path)
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {req.csv_path}")
    rules = learn_from_sample(str(csv_path), req.pipeline_name, org_id=ORG_ID)
    return {"rules_generated": len(rules), "pipeline": req.pipeline_name}


# ── Quarantine ────────────────────────────────────────────────────────────────

class QuarantineIn(BaseModel):
    pipeline_name: str
    row_count:     int
    violations:    dict
    sample_rows:   list[dict]


class QuarantineResolveIn(BaseModel):
    fix_policy:    dict   # operation spec to apply to ALL rows in this batch
    update_rule:   bool = False  # if True, persist this fix_policy back to the rule
    column_name:   Optional[str] = None  # which rule to update (if update_rule=True)


def _triage_quarantine(pipeline_name: str, violations: dict, sample_rows: list[dict]) -> dict:
    """
    Run the tiered diagnosis engine against the quarantine batch.
    Returns a triage dict with tier, analysis, and suggestions.
    """
    # Synthesize a representative error from the violations summary
    # so the diagnosis engine can fingerprint and cascade tiers
    col_names = list(violations.keys())
    error_msg = f"Quarantine violations in columns: {col_names} — {violations}"
    synthetic_error = ValueError(error_msg)

    result = diagnose(
        error=synthetic_error,
        pipeline_name=pipeline_name,
        org_id=ORG_ID,
        failing_rows=sample_rows,
    )

    # Normalise into the suggestion format the frontend expects
    suggestions = result.get("suggestions", [])
    if not suggestions and result.get("operation"):
        suggestions = [{
            "column":      result.get("operation", {}).get("column", col_names[0] if col_names else ""),
            "label":       result.get("label", "Apply fix"),
            "description": result.get("analysis", ""),
            "operation":   result["operation"],
        }]

    return {
        "analysis":   result.get("analysis", ""),
        "suggestions": suggestions,
        "tier":        result.get("tier", 5),
        "tier_label":  result.get("tier_label", TIER_LABELS[5]),
        "auto_fix":    result.get("auto_fix", False),
    }


@app.post("/api/quarantine")
def receive_quarantine(batch: QuarantineIn):
    batch_id = str(uuid4())
    triage   = _triage_quarantine(batch.pipeline_name, batch.violations, batch.sample_rows)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO quarantine_batches
              (id, org_id, pipeline_name, row_count, violations, sample_rows, fix_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id, ORG_ID, batch.pipeline_name,
                batch.row_count,
                json.dumps(batch.violations),
                json.dumps(batch.sample_rows),
                json.dumps(triage),
            ),
        )
    return {"batch_id": batch_id, "triage": triage}


@app.get("/api/quarantine")
def list_quarantine(pipeline_name: Optional[str] = None):
    with get_conn() as conn:
        if pipeline_name:
            rows = conn.execute(
                "SELECT * FROM quarantine_batches WHERE pipeline_name = ? AND org_id = ? ORDER BY created_at DESC",
                (pipeline_name, ORG_ID),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM quarantine_batches WHERE org_id = ? ORDER BY created_at DESC LIMIT 50",
                (ORG_ID,),
            ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["violations"]  = json.loads(d["violations"]  or "{}")
        d["sample_rows"] = json.loads(d["sample_rows"] or "[]")
        d["fix_summary"] = json.loads(d["fix_summary"] or "{}")
        result.append(d)
    return result


@app.post("/api/quarantine/{batch_id}/resolve")
def resolve_quarantine(batch_id: str, resolution: QuarantineResolveIn):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM quarantine_batches WHERE id = ?", (batch_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Batch not found")

    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE quarantine_batches SET status='resolved', resolved_at=? WHERE id=?",
            (now, batch_id),
        )

    if resolution.update_rule and resolution.column_name:
        with get_conn() as conn:
            conn.execute(
                """UPDATE rules SET fix_policy = ?, auto_fix = 1
                   WHERE pipeline_name = ? AND column_name = ? AND org_id = ?""",
                (
                    json.dumps(resolution.fix_policy),
                    row["pipeline_name"], resolution.column_name, ORG_ID,
                ),
            )

    # Contribute anonymised pattern to cross-org corpus (Tier 4)
    label = resolution.column_name or "fix"
    synthetic_error = ValueError(json.loads(row["violations"] or "{}"))
    corpus.contribute(synthetic_error, resolution.fix_policy, label)

    return {"status": "resolved", "batch_id": batch_id}


@app.post("/api/quarantine/{batch_id}/skip")
def skip_quarantine(batch_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE quarantine_batches SET status='skipped' WHERE id=?", (batch_id,)
        )
    return {"status": "skipped", "batch_id": batch_id}


# ── Legacy event endpoints (kept for compatibility) ───────────────────────────

@app.get("/api/resolutions")
def list_resolutions():
    return store.list_resolutions()


@app.delete("/api/resolutions/{resolution_id}")
def delete_resolution(resolution_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM resolutions WHERE id = ?", (resolution_id,))
    return {"deleted": resolution_id}
