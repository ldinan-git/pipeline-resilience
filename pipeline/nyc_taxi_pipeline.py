"""
NYC Taxi CSV → Postgres pipeline.
Intentionally brittle — 4 failure modes injected for the resilience wrapper to catch.
"""

import pandas as pd
from sqlalchemy import create_engine, text
import os

DB_URL = os.getenv("DB_URL", "postgresql://postgres:postgres@localhost:5432/taxi_db")
CSV_PATH = os.getenv("CSV_PATH", "data/nyc_taxi_sample.csv")
TABLE_NAME = "taxi_trips"


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    # Failure 1: datetime parsing — format varies in real files
    df["tpep_pickup_datetime"] = pd.to_datetime(df["tpep_pickup_datetime"])
    df["tpep_dropoff_datetime"] = pd.to_datetime(df["tpep_dropoff_datetime"])

    # Failure 2: nulls in NOT NULL columns — real taxi data has them
    df = df.dropna(subset=["passenger_count", "trip_distance"])

    # Failure 3: out-of-range fares — corrupt rows slip through
    if (df["fare_amount"] < 0).any():
        raise ValueError(
            f"Negative fare_amount in {(df['fare_amount'] < 0).sum()} rows"
        )

    # Failure 4: unexpected payment_type codes beyond {1,2,3,4,5,6}
    valid_codes = {1, 2, 3, 4, 5, 6}
    bad = set(df["payment_type"].dropna().unique()) - valid_codes
    if bad:
        raise ValueError(f"Unknown payment_type codes: {bad}")

    return df


def write_to_postgres(df: pd.DataFrame, engine) -> None:
    df.to_sql(TABLE_NAME, engine, if_exists="append", index=False)


def run():
    print(f"[pipeline] Loading {CSV_PATH}")
    df = load_csv(CSV_PATH)
    print(f"[pipeline] {len(df)} rows loaded")

    print("[pipeline] Cleaning...")
    df = clean(df)
    print(f"[pipeline] {len(df)} rows after cleaning")

    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))  # smoke-test connection

    print("[pipeline] Writing to Postgres...")
    write_to_postgres(df, engine)
    print(f"[pipeline] Done — {len(df)} rows written to {TABLE_NAME}")


if __name__ == "__main__":
    run()
