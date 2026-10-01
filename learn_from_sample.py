"""
Learn validation rules from a known-good data sample.
Run this once before your first pipeline run to bootstrap the rule set.

Usage:
  python learn_from_sample.py
  python learn_from_sample.py --csv data/nyc_taxi_good_sample.csv --pipeline nyc-taxi
"""
import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from backend.database import init_db
from wrapper.learn import learn_from_sample

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv",      default="data/nyc_taxi_good_sample.csv")
    parser.add_argument("--pipeline", default="nyc-taxi")
    parser.add_argument("--org",      default="default")
    args = parser.parse_args()

    init_db()
    rules = learn_from_sample(args.csv, args.pipeline, org_id=args.org)

    if not rules:
        print("\nNo rules generated — check that Ollama is running and the CSV path is correct.")
        sys.exit(1)

    print(f"\nGenerated {len(rules)} validation rules for pipeline '{args.pipeline}':")
    for r in rules:
        print(f"  [{r.rule_type:8s}] {r.column_name:25s} confidence={r.confidence} auto_fix={r.auto_fix}")
        if r.params:
            print(f"           params: {r.params}")
        if r.fix_policy:
            print(f"           fix:    {r.fix_policy}")
    print("\nRun 'python run_with_resilience.py' — the pipeline will now validate data before running.")
