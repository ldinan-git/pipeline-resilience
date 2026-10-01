"""
Pipeline resilience wrapper.
Catches failures, loads plain-text context, calls Ollama for a fix suggestion.
"""

import functools
import logging
import traceback
from pathlib import Path

import ollama

CONTEXT_ROOT = Path(__file__).parent.parent / "pipeline-context"
MODEL = "llama3.2"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pipeline.log"),
    ],
)
log = logging.getLogger("resilience")


def _load_context(pipeline_name: str) -> str:
    ctx_dir = CONTEXT_ROOT / pipeline_name
    parts = []
    for fname in ["schema.txt", "known-issues.txt"]:
        fpath = ctx_dir / fname
        if fpath.exists():
            parts.append(f"=== {fname} ===\n{fpath.read_text()}")
    return "\n\n".join(parts)


def _ask_llm(error: Exception, tb: str, context: str) -> str:
    prompt = f"""You are a data engineering assistant. An ETL pipeline failed with the error below.
Using the schema and known issues provided, suggest a specific, actionable fix.

ERROR:
{type(error).__name__}: {error}

TRACEBACK:
{tb}

PIPELINE CONTEXT:
{context}

Respond with:
1. Root cause (one sentence)
2. Suggested fix (specific code change or data correction)
3. Whether this should be a hard stop or can be handled gracefully"""

    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return response["message"]["content"]


def resilient_pipeline(name: str):
    """
    Decorator factory. Wraps a pipeline function with failure interception and LLM-assisted diagnosis.

    Usage:
        @resilient_pipeline(name="nyc-taxi")
        def run(): ...
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            log.info(f"[{name}] Starting: {fn.__name__}")
            try:
                result = fn(*args, **kwargs)
                log.info(f"[{name}] Completed successfully")
                return result
            except Exception as e:
                tb = traceback.format_exc()
                log.error(f"[{name}] FAILURE — {type(e).__name__}: {e}")
                log.error(f"[{name}] Traceback:\n{tb}")

                context = _load_context(name)
                if not context:
                    log.warning(f"[{name}] No context found at pipeline-context/{name}/")

                log.info(f"[{name}] Querying Ollama ({MODEL}) for fix suggestion...")
                try:
                    suggestion = _ask_llm(e, tb, context)
                    log.info(f"[{name}] LLM suggestion:\n{'='*60}\n{suggestion}\n{'='*60}")
                except Exception as llm_err:
                    log.error(f"[{name}] Ollama call failed: {llm_err}")

                raise

        return wrapper
    return decorator
