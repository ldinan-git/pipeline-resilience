"""
Resolution store — tiered lookup and persistence.

Lookup order:
  Tier 1 — pipeline-scoped:  org_id + pipeline_name match
  Tier 3 — org-scoped:       org_id match, any pipeline (scope='org')
  future  — global:          no org/pipeline restriction (scope='global')
"""

import json
from typing import Optional
from backend.database import get_conn


def _fragment(error_message: str) -> str:
    return error_message[:80]


def find_auto_resolution(
    error_type: str,
    error_message: str,
    pipeline_name: str,
    org_id: str,
) -> Optional[dict]:
    with get_conn() as conn:

        # Tier 1 — pipeline-scoped
        row = conn.execute(
            """
            SELECT id, operation, label, scope FROM resolutions
            WHERE error_type = ?
              AND ? LIKE '%' || error_fragment || '%'
              AND pipeline_name = ?
              AND org_id = ?
              AND scope = 'this_error'
              AND operation IS NOT NULL
            ORDER BY applied_count DESC LIMIT 1
            """,
            (error_type, error_message, pipeline_name, org_id),
        ).fetchone()

        # Tier 3 — org-scoped (any pipeline in the same org)
        if not row:
            row = conn.execute(
                """
                SELECT id, operation, label, scope FROM resolutions
                WHERE error_type = ?
                  AND ? LIKE '%' || error_fragment || '%'
                  AND org_id = ?
                  AND scope = 'org'
                  AND operation IS NOT NULL
                ORDER BY applied_count DESC LIMIT 1
                """,
                (error_type, error_message, org_id),
            ).fetchone()

        # Global fallback
        if not row:
            row = conn.execute(
                """
                SELECT id, operation, label, scope FROM resolutions
                WHERE error_type = ?
                  AND ? LIKE '%' || error_fragment || '%'
                  AND scope = 'global'
                  AND operation IS NOT NULL
                ORDER BY applied_count DESC LIMIT 1
                """,
                (error_type, error_message),
            ).fetchone()

        if row and row["operation"]:
            return {
                "resolution_id": row["id"],
                "operation":     json.loads(row["operation"]),
                "label":         row["label"] or "",
                "matched_scope": row["scope"],
            }

    return None


def save_resolution(
    org_id: str,
    error_type: str,
    error_message: str,
    pipeline_name: Optional[str],
    operation: dict,
    label: str,
    scope: str,
) -> int:
    frag        = _fragment(error_message)
    scoped_name = pipeline_name if scope == "this_error" else None
    scoped_org  = org_id        if scope != "global"     else None

    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO resolutions
              (org_id, error_type, error_fragment, pipeline_name, operation, label, scope)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (scoped_org or "global", error_type, frag, scoped_name,
             json.dumps(operation), label, scope),
        )
        return cur.lastrowid


def increment_applied(resolution_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE resolutions SET applied_count = applied_count + 1 WHERE id = ?",
            (resolution_id,),
        )


def list_resolutions() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM resolutions ORDER BY created_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["operation"] = json.loads(d["operation"]) if d["operation"] else None
        except Exception:
            d["operation"] = None
        result.append(d)
    return result
