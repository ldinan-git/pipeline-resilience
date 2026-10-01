"""
Pre-written, vetted fix functions keyed by error signature.
The LLM diagnoses; these functions apply the actual data correction.
"""

import logging
import pandas as pd

log = logging.getLogger("resilience")


def fix_negative_fares(df: pd.DataFrame) -> pd.DataFrame:
    bad = (df["fare_amount"] < 0).sum()
    df = df[df["fare_amount"] >= 0].copy()
    log.warning(f"[fix] Dropped {bad} rows with negative fare_amount")
    return df


def fix_unknown_payment_type(df: pd.DataFrame) -> pd.DataFrame:
    valid = {1, 2, 3, 4, 5, 6}
    mask = ~df["payment_type"].isin(valid)
    df = df.copy()
    df.loc[mask, "payment_type"] = 5  # coerce to Unknown
    log.warning(f"[fix] Coerced {mask.sum()} unknown payment_type values to 5 (Unknown)")
    return df


def fix_null_required_columns(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)
    # impute passenger_count=1 where trip_distance > 0, else drop
    null_pax = df["passenger_count"].isna()
    df.loc[null_pax & (df["trip_distance"] > 0), "passenger_count"] = 1
    df = df.dropna(subset=["passenger_count", "trip_distance"])
    log.warning(f"[fix] Null handling: {before} → {len(df)} rows")
    return df


# Maps error message fragments to fix functions
FIX_REGISTRY: list[tuple[str, callable]] = [
    ("Negative fare_amount", fix_negative_fares),
    ("Unknown payment_type codes", fix_unknown_payment_type),
    ("passenger_count",  fix_null_required_columns),
]


def find_fix(error: Exception):
    msg = str(error)
    for fragment, fn in FIX_REGISTRY:
        if fragment in msg:
            return fn
    return None


def get_fix_by_key(key: str):
    for _, fn in FIX_REGISTRY:
        if fn.__name__ == key:
            return fn
    return None
