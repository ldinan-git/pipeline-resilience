"""
Rule generation from known-good sample data.
The LLM analyzes column statistics (not raw rows) and generates ValidationRules
covering: valid ranges, valid enum sets, and required (non-null) columns.
"""
from __future__ import annotations
import json
import logging
import re

import ollama
import pandas as pd

from wrapper.rules import ValidationRule, save_rule, clear_rules

log  = logging.getLogger("resilience")
MODEL = "llama3.2"


def _column_stats(df: pd.DataFrame) -> dict:
    stats = {}
    for col in df.columns:
        s = df[col]
        entry: dict = {
            "dtype":      str(s.dtype),
            "null_count": int(s.isna().sum()),
            "null_pct":   round(s.isna().mean() * 100, 1),
            "total":      len(s),
        }
        if pd.api.types.is_numeric_dtype(s):
            nz = s.dropna()
            entry.update({
                "min":          float(nz.min())  if len(nz) else None,
                "max":          float(nz.max())  if len(nz) else None,
                "mean":         round(float(nz.mean()), 2) if len(nz) else None,
                "unique_count": int(nz.nunique()),
            })
            if nz.nunique() <= 20:
                entry["unique_values"] = sorted([int(v) if float(v) == int(v) else float(v) for v in nz.unique()])
        else:
            entry["unique_count"] = int(s.nunique())
            if s.nunique() <= 30:
                entry["top_values"] = s.value_counts().head(20).index.tolist()
        stats[col] = entry
    return stats


def learn_from_sample(
    csv_path: str,
    pipeline_name: str,
    org_id: str = "default",
    replace: bool = True,
) -> list[ValidationRule]:
    """
    Analyze a known-good CSV and ask the LLM to generate validation rules.
    Stores rules in the DB and returns them.
    """
    df = pd.read_csv(csv_path)
    log.info(f"[learn] Analyzing {len(df)} rows, {len(df.columns)} columns")
    stats = _column_stats(df)

    prompt = f"""You are a data quality expert. The following statistics describe a known-GOOD dataset.
Your job: generate validation rules that would catch bad data before it enters the pipeline.

Column statistics (from {len(df)} rows of clean, correct data):
{json.dumps(stats, indent=2)}

For each column that needs validation, output one JSON object with this exact shape:
{{
  "column": "<column name>",
  "rule_type": "range" | "enum" | "not_null",
  "params": {{
    // range:    {{"min": <number or null>, "max": <number or null>}}
    // enum:     {{"values": [list of ALL valid values as integers]}}
    // not_null: {{}}
  }},
  "fix_policy": {{
    // How to auto-fix violations.  Choose ONE:
    // Remove out-of-range rows:  {{"operation": "filter", "column": "col", "operator": ">=", "value": 0}}
    // Clip to range (keep rows): {{"operation": "clamp",  "column": "col", "min": 0, "max": null}}
    // Fill nulls:                {{"operation": "fillna", "column": "col", "value": 1}}
    // Remove unknown enum vals:  {{"operation": "filter_in", "column": "col", "values": [1,2,3,4,5,6]}}
  }},
  "auto_fix": true,   // true = apply without asking a human
  "confidence": "high" | "medium" | "low"
}}

Return ONLY a valid JSON array [ ... ] of these objects.
Rules to generate:
- Numeric columns with a clear valid range (e.g. fare > 0, passenger_count 1-6)
- Categorical columns with a known set of valid codes
- Columns that must never be null
Skip: free-text, raw IDs, timestamps."""

    response = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt}])
    content  = response["message"]["content"]

    match = re.search(r"\[.*\]", content, re.DOTALL)
    if not match:
        log.error("[learn] LLM did not return a JSON array")
        return []

    try:
        rules_data = json.loads(match.group())
    except json.JSONDecodeError as e:
        log.error(f"[learn] JSON parse error: {e}")
        return []

    if replace:
        clear_rules(pipeline_name, org_id=org_id)
        log.info(f"[learn] Cleared existing rules for {pipeline_name}")

    saved: list[ValidationRule] = []
    for rd in rules_data:
        try:
            rule = ValidationRule(
                pipeline_name=pipeline_name,
                column_name=rd["column"],
                rule_type=rd["rule_type"],
                params=rd.get("params", {}),
                fix_policy=rd.get("fix_policy", {}),
                auto_fix=rd.get("auto_fix", True),
                confidence=rd.get("confidence", "high"),
                source="learned",
            )
            rule.id = save_rule(rule, org_id=org_id)
            saved.append(rule)
            log.info(f"[learn]  + {rule.column_name} [{rule.rule_type}] confidence={rule.confidence}")
        except Exception as e:
            log.warning(f"[learn] Skipped rule {rd.get('column')}: {e}")

    log.info(f"[learn] {len(saved)} rules saved for pipeline '{pipeline_name}'")
    return saved
