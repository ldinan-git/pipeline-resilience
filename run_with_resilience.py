"""
Entry point: runs the NYC taxi pipeline under the resilience wrapper.
The pipeline itself is unchanged — the wrapper is layered on top.
"""

from wrapper.resilience import resilient_pipeline
import pipeline.nyc_taxi_pipeline as taxi

resilient_run = resilient_pipeline(name="nyc-taxi")(taxi.run)

if __name__ == "__main__":
    resilient_run()
