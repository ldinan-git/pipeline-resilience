"""
Generates data/nyc_taxi_sample.csv with all 4 failure modes injected.
Run once: python generate_sample_data.py
"""

import pandas as pd
import numpy as np
from pathlib import Path

Path("data").mkdir(exist_ok=True)

rng = np.random.default_rng(42)
n = 200

df = pd.DataFrame({
    "VendorID": rng.choice([1, 2], n),
    "tpep_pickup_datetime": pd.date_range("2024-01-01", periods=n, freq="10min").astype(str),
    "tpep_dropoff_datetime": pd.date_range("2024-01-01 00:15", periods=n, freq="10min").astype(str),
    "passenger_count": rng.choice([1.0, 2.0, np.nan], n, p=[0.7, 0.2, 0.1]),  # Failure 2: nulls
    "trip_distance": rng.uniform(0.5, 20.0, n),
    "RatecodeID": rng.choice([1, 2, 3], n),
    "store_and_fwd_flag": rng.choice(["Y", "N"], n),
    "PULocationID": rng.integers(1, 265, n),
    "DOLocationID": rng.integers(1, 265, n),
    "payment_type": rng.choice([1.0, 2.0, 3.0, 99.0], n, p=[0.6, 0.2, 0.15, 0.05]),  # Failure 4: code 99
    "fare_amount": rng.uniform(3.0, 80.0, n),
    "extra": rng.uniform(0, 2, n),
    "mta_tax": 0.5,
    "tip_amount": rng.uniform(0, 15, n),
    "tolls_amount": rng.uniform(0, 5, n),
    "improvement_surcharge": 0.3,
    "total_amount": rng.uniform(5, 100, n),
    "congestion_surcharge": 2.5,
    "airport_fee": rng.choice([0.0, 1.25], n),
})

# Failure 3: inject negative fares
df.loc[rng.choice(df.index, 5, replace=False), "fare_amount"] = -5.0

df.to_csv("data/nyc_taxi_sample.csv", index=False)
print(f"Written {len(df)} rows to data/nyc_taxi_sample.csv")
print(f"  Nulls in passenger_count: {df['passenger_count'].isna().sum()}")
print(f"  Negative fare_amount: {(df['fare_amount'] < 0).sum()}")
print(f"  Unknown payment_type (99): {(df['payment_type'] == 99).sum()}")
