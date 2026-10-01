"""
Safe, parameterized dataframe operations.
The LLM generates operation specs; this module executes them without eval/exec.

Supported operations:
  filter     — keep rows where column op value
  clamp      — clip column to min/max
  fillna     — fill nulls with a scalar value
  map_values — replace specific values via a mapping dict
"""

import pandas as pd
import logging

log = logging.getLogger("resilience")

_SAFE_OPS = {">=", "<=", ">", "<", "==", "!="}


def apply_operation(df: pd.DataFrame, spec: dict) -> pd.DataFrame:
    op = spec.get("operation")

    if op == "filter":
        col      = spec["column"]
        operator = spec["operator"]
        value    = spec["value"]
        if operator not in _SAFE_OPS:
            raise ValueError(f"Unsafe operator: {operator}")
        before = len(df)
        if operator == ">=": df = df[df[col] >= value]
        elif operator == "<=": df = df[df[col] <= value]
        elif operator == ">":  df = df[df[col] >  value]
        elif operator == "<":  df = df[df[col] <  value]
        elif operator == "==": df = df[df[col] == value]
        elif operator == "!=": df = df[df[col] != value]
        dropped = before - len(df)
        log.info(f"[op:filter] {col} {operator} {value} — kept {len(df)}/{before} rows (dropped {dropped})")
        if len(df) == before:
            log.warning(f"[op:filter] No rows were removed — operator may be inverted")

    elif op == "clamp":
        col = spec["column"]
        lo  = spec.get("min")
        hi  = spec.get("max")
        df = df.copy()
        df[col] = df[col].clip(lower=lo, upper=hi)
        log.info(f"[op:clamp] {col} clipped to [{lo}, {hi}]")

    elif op == "fillna":
        col   = spec["column"]
        value = spec["value"]
        df = df.copy()
        filled = df[col].isna().sum()
        df[col] = df[col].fillna(value)
        log.info(f"[op:fillna] {col} — filled {filled} nulls with {value!r}")

    elif op == "map_values":
        col     = spec["column"]
        mapping = {str(k): v for k, v in spec["mapping"].items()}
        df = df.copy()
        df[col] = df[col].apply(
            lambda x: mapping.get(str(int(x)) if pd.notna(x) else str(x), x)
        )
        log.info(f"[op:map_values] {col} remapped {list(mapping.keys())}")

    elif op == "filter_in":
        col    = spec["column"]
        values = spec["values"]
        before = len(df)
        def _in(x):
            if x in values:
                return True
            try:
                return int(float(x)) in values
            except (ValueError, TypeError):
                return False
        df = df[df[col].apply(_in)]
        dropped = before - len(df)
        log.info(f"[op:filter_in] {col} — kept {len(df)}/{before} rows (dropped {dropped} unknown values)")

    else:
        raise ValueError(f"Unknown operation: {op!r}")

    return df.reset_index(drop=True)
