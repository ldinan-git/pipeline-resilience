"""
Generate a known-GOOD reference dataset — no injected errors.
This is what you'd provide from real verified output data.
Used by learn_from_sample.py to teach the system what valid data looks like.
"""
import pandas as pd
import numpy as np
from pathlib import Path

rng = np.random.default_rng(42)
n   = 300

data = {
    "VendorID":             rng.integers(1, 3, n),
    "tpep_pickup_datetime": pd.date_range("2024-01-01", periods=n, freq="5min").astype(str),
    "tpep_dropoff_datetime":pd.date_range("2024-01-01 00:15", periods=n, freq="5min").astype(str),
    "passenger_count":      rng.integers(1, 7, n).astype(float),
    "trip_distance":        rng.uniform(0.5, 20.0, n).round(2),
    "RatecodeID":           rng.integers(1, 7, n),
    "store_and_fwd_flag":   rng.choice(["N", "Y"], n),
    "PULocationID":         rng.integers(1, 265, n),
    "DOLocationID":         rng.integers(1, 265, n),
    "payment_type":         rng.integers(1, 7, n),          # valid: 1-6
    "fare_amount":          rng.uniform(2.50, 80.0, n).round(2),  # always positive
    "extra":                rng.choice([0.0, 0.5, 1.0], n),
    "mta_tax":              rng.choice([0.0, 0.5], n),
    "tip_amount":           rng.uniform(0, 15.0, n).round(2),
    "tolls_amount":         rng.choice([0.0, 6.12, 12.24], n),
    "improvement_surcharge":rng.choice([0.0, 0.3], n),
    "total_amount":         rng.uniform(3.0, 100.0, n).round(2),
    "congestion_surcharge": rng.choice([0.0, 2.5], n),
    "airport_fee":          rng.choice([0.0, 1.25], n),
    "cbd_congestion_fee":   rng.choice([0.0, 0.75], n),
}

df = pd.DataFrame(data)
Path("data").mkdir(exist_ok=True)
df.to_csv("data/nyc_taxi_good_sample.csv", index=False)
print(f"Generated {len(df)} clean rows -> data/nyc_taxi_good_sample.csv")
print(f"fare_amount range: ${df['fare_amount'].min():.2f} - ${df['fare_amount'].max():.2f}")
print(f"payment_type values: {sorted(df['payment_type'].unique())}")
print(f"passenger_count nulls: {df['passenger_count'].isna().sum()}")
