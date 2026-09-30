# pipeline-resilience

A self-healing ETL wrapper: catches pipeline failures, loads plain-text context, queries a local LLM (Ollama / Llama 3.2) for a fix suggestion, validates the output, and logs everything.

## Structure

```
pipeline/                  # the raw pipeline — no wrapper yet
  nyc_taxi_pipeline.py     # NYC Taxi CSV → Postgres, 4 failure modes injected

pipeline-context/nyc-taxi/ # plain-text context for the LLM
  schema.txt
  known-issues.txt

wrapper/                   # (next) resilience decorator/context manager
```

## Quickstart

```bash
cp .env.example .env       # set DB_URL and CSV_PATH
pip install -r requirements.txt
python pipeline/nyc_taxi_pipeline.py
```

## Failure modes in the pipeline

| # | Failure | Location |
|---|---------|----------|
| 1 | Datetime format variance | `clean()` |
| 2 | Null in NOT NULL columns | `clean()` |
| 3 | Negative `fare_amount` | `clean()` |
| 4 | Unknown `payment_type` codes | `clean()` |
