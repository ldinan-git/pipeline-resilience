"""
Tiered diagnosis engine.

When a quarantine batch arrives, diagnosis cascades through 5 tiers,
stopping at the first confident match. The tier that resolved it is
recorded — this is both an audit trail and a product signal.

Tier 1 — Pipeline history:    has THIS pipeline seen this error before?
Tier 2 — Data analysis:       what do the failing rows tell us?
Tier 3 — Org knowledge:       has any pipeline in this org seen this?
Tier 4 — Cross-org corpus:    have other orgs (anonymized) seen this?
Tier 5 — General LLM:         best guess from model knowledge alone.

The business value concentrates at Tier 4: a fix that came from the
cross-org corpus means another organization already paid the cost of
figuring this out, and you didn't have to.
"""
from __future__ import annotations
import json
import logging
import os
import re

import ollama

from wrapper import corpus

log   = logging.getLogger("resilience")
MODEL = os.getenv("RESILIENCE_MODEL", "llama3.2")


# ── Tier 1: pipeline-scoped rule history ──────────────────────────────────────

def _tier1(error: Exception, pipeline_name: str, org_id: str) -> dict | None:
    from wrapper.rules import load_rules
    rules = load_rules(pipeline_name, org_id=org_id)
    if not rules:
        return None
    msg = str(error).lower()
    for rule in rules:
        if rule.column_name.lower() in msg and rule.fix_policy:
            log.info(f"[tier1] Matched rule for column '{rule.column_name}'")
            return {
                "operation": rule.fix_policy,
                "label":     f"{rule.rule_type} rule on {rule.column_name}",
                "tier":      1,
                "auto_fix":  rule.auto_fix,
            }
    return None


# ── Tier 2: data pattern analysis ────────────────────────────────────────────

def _tier2(error: Exception, failing_rows: list[dict], pipeline_name: str) -> dict | None:
    if not failing_rows:
        return None
    log.info("[tier2] Analyzing failing row patterns...")
    prompt = f"""A pipeline quarantined {len(failing_rows)} rows. Analyze the data pattern and suggest the best fix.

Error: {type(error).__name__}: {error}

Sample rows (showing the problem data):
{json.dumps(failing_rows[:6], indent=2)}

Return ONLY a JSON object:
{{
  "analysis": "one sentence describing the data pattern you see",
  "confidence": "high" | "medium" | "low",
  "operation": {{
    // ONE of these:
    // {{"operation": "filter",    "column": "col", "operator": ">=", "value": 0}}
    // {{"operation": "clamp",     "column": "col", "min": 0, "max": null}}
    // {{"operation": "fillna",    "column": "col", "value": 1}}
    // {{"operation": "filter_in", "column": "col", "values": [1,2,3,4,5,6]}}
    // {{"operation": "map_values","column": "col", "mapping": {{"99": 5}}}}
  }},
  "label": "short action name"
}}"""

    try:
        resp    = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt}])
        content = resp["message"]["content"]
        match   = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            data = json.loads(match.group())
            if data.get("confidence") in ("high", "medium") and data.get("operation"):
                log.info(f"[tier2] Analysis: {data.get('analysis')}")
                return {**data, "tier": 2, "auto_fix": data.get("confidence") == "high"}
    except Exception as e:
        log.warning(f"[tier2] Failed: {e}")
    return None


# ── Tier 3: org-wide cross-pipeline lookup ────────────────────────────────────

def _tier3(error: Exception, org_id: str) -> dict | None:
    from backend.database import get_conn
    msg = str(error)
    # Find rules from ANY pipeline in this org that match this error pattern
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM rules WHERE org_id = ? AND fix_policy != '{}'
               ORDER BY created_at DESC""",
            (org_id,),
        ).fetchall()

    if not rows:
        return None

    msg_lower = msg.lower()
    for row in rows:
        if row["column_name"].lower() in msg_lower:
            fix = json.loads(row["fix_policy"])
            log.info(f"[tier3] Org-wide match: column '{row['column_name']}' from pipeline '{row['pipeline_name']}'")
            return {
                "operation":    fix,
                "label":        f"Org rule: {row['rule_type']} on {row['column_name']}",
                "tier":         3,
                "auto_fix":     bool(row["auto_fix"]),
                "source_pipeline": row["pipeline_name"],
            }
    return None


# ── Tier 4: cross-org corpus ──────────────────────────────────────────────────

def _tier4(error: Exception) -> dict | None:
    result = corpus.lookup(error)
    if result and result.get("found"):
        return {
            "operation":   result["operation"],
            "label":       result.get("label", "Cross-org fix"),
            "tier":        4,
            "auto_fix":    True,
            "match_count": result.get("match_count", 0),
        }
    return None


# ── Tier 5: general LLM ───────────────────────────────────────────────────────

def _tier5(error: Exception, context: str, failing_rows: list[dict]) -> dict:
    log.info("[tier5] Falling back to general LLM...")
    rows_section = f"\nSample failing rows:\n{json.dumps(failing_rows[:5], indent=2)}" if failing_rows else ""
    prompt = f"""A data pipeline failed. Suggest 2-3 fixes.

Error: {type(error).__name__}: {error}
{rows_section}

Pipeline context:
{context}

Return ONLY JSON:
{{
  "analysis": "one sentence describing the issue",
  "suggestions": [
    {{
      "label": "Short action",
      "description": "what this does",
      "operation": {{
        // filter / clamp / fillna / filter_in / map_values
      }}
    }}
  ]
}}"""

    try:
        resp    = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt}])
        content = resp["message"]["content"]
        match   = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return {**data, "tier": 5, "auto_fix": False}
    except Exception as e:
        log.error(f"[tier5] LLM failed: {e}")

    return {"analysis": "Could not diagnose automatically.", "suggestions": [], "tier": 5, "auto_fix": False}


# ── Public API ────────────────────────────────────────────────────────────────

TIER_LABELS = {
    1: "Pipeline history",
    2: "Data pattern analysis",
    3: "Org-wide knowledge",
    4: "Cross-org corpus",
    5: "General LLM",
}


def diagnose(
    error:         Exception,
    pipeline_name: str,
    org_id:        str,
    failing_rows:  list[dict] = None,
    context:       str = "",
) -> dict:
    """
    Cascade through all 5 tiers. Returns a diagnosis dict that always includes:
      tier        — which tier resolved it (1-5)
      tier_label  — human-readable tier name
      auto_fix    — whether this can be applied without human confirmation
      analysis    — what's wrong
      operation   — fix to apply (may be None at tier 5 if only suggestions returned)
      suggestions — list of alternatives (tier 5)
    """
    failing_rows = failing_rows or []

    for fn, args in [
        (_tier1, (error, pipeline_name, org_id)),
        (_tier2, (error, failing_rows, pipeline_name)),
        (_tier3, (error, org_id)),
        (_tier4, (error,)),
    ]:
        try:
            result = fn(*args)
            if result:
                tier = result["tier"]
                log.info(f"[diagnosis] Resolved at Tier {tier}: {TIER_LABELS[tier]}")
                result["tier_label"] = TIER_LABELS[tier]
                result.setdefault("analysis",    "")
                result.setdefault("suggestions", [])
                return result
        except Exception as e:
            log.warning(f"[diagnosis] Tier error: {e}")

    result = _tier5(error, context, failing_rows)
    result["tier_label"] = TIER_LABELS[5]
    return result
