"""
Pre-pipeline validation gate.
Splits a raw dataframe into (clean, quarantine) using ValidationRules.
Auto-fixable violations are corrected in-place before splitting.
"""
from __future__ import annotations
import logging

import pandas as pd

from wrapper.rules import ValidationRule
from wrapper.operations import apply_operation

log = logging.getLogger("resilience")


def validate_and_split(
    df: pd.DataFrame,
    rules: list[ValidationRule],
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Returns (clean_df, quarantine_df, violation_summary).
    Applies auto-fix policies first; rows that still fail go to quarantine.
    """
    df = df.copy()
    violation_summary: dict[str, dict] = {}

    for rule in rules:
        col = rule.column_name
        if col not in df.columns:
            continue

        bad = _detect(df, rule)
        if bad is None or not bad.any():
            continue

        n_bad = int(bad.sum())
        log.info(f"[validator] {col} {rule.rule_type}: {n_bad} violations")
        violation_summary[col] = {
            "rule_type": rule.rule_type,
            "count": n_bad,
            "auto_fixed": False,
        }

        if rule.auto_fix and rule.fix_policy:
            try:
                df = apply_operation(df, rule.fix_policy)
                bad_after = _detect(df, rule)
                remaining = int(bad_after.sum()) if bad_after is not None else 0
                fixed = n_bad - remaining
                log.info(f"[validator] Auto-fixed {fixed}/{n_bad} {col} violations")
                violation_summary[col]["auto_fixed"] = True
                violation_summary[col]["fixed_count"] = fixed
                violation_summary[col]["remaining"] = remaining
            except Exception as e:
                log.warning(f"[validator] Auto-fix failed for {col}: {e}")

    # Final quarantine pass — anything still failing
    quarantine_mask = pd.Series(False, index=df.index)
    for rule in rules:
        col = rule.column_name
        if col not in df.columns:
            continue
        bad = _detect(df, rule)
        if bad is not None and bad.any():
            quarantine_mask |= bad

    clean_df      = df[~quarantine_mask].reset_index(drop=True)
    quarantine_df = df[quarantine_mask].reset_index(drop=True)
    return clean_df, quarantine_df, violation_summary


def _detect(df: pd.DataFrame, rule: ValidationRule) -> pd.Series | None:
    col = rule.column_name
    rt  = rule.rule_type
    p   = rule.params

    if rt == "range":
        bad = pd.Series(False, index=df.index)
        if p.get("min") is not None:
            bad |= df[col].notna() & (df[col] < p["min"])
        if p.get("max") is not None:
            bad |= df[col].notna() & (df[col] > p["max"])
        return bad

    if rt == "enum":
        valid = set(p.get("values", []))
        return df[col].notna() & ~df[col].apply(lambda x: _in_enum(x, valid))

    if rt == "not_null":
        return df[col].isna()

    return None


def _in_enum(x, valid_set: set) -> bool:
    if x in valid_set:
        return True
    try:
        return int(float(x)) in valid_set
    except (ValueError, TypeError):
        return False
