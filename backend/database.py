import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "pipeline_resilience.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
            -- Learned validation rules (generated from known-good sample data)
            CREATE TABLE IF NOT EXISTS rules (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id        TEXT NOT NULL DEFAULT 'default',
                pipeline_name TEXT NOT NULL,
                column_name   TEXT NOT NULL,
                rule_type     TEXT NOT NULL CHECK(rule_type IN ('range','enum','not_null')),
                params        TEXT NOT NULL DEFAULT '{}',
                fix_policy    TEXT NOT NULL DEFAULT '{}',
                auto_fix      INTEGER NOT NULL DEFAULT 1,
                confidence    TEXT NOT NULL DEFAULT 'high',
                source        TEXT NOT NULL DEFAULT 'learned',
                created_at    TEXT DEFAULT (datetime('now'))
            );

            -- Quarantine batches: groups of rows that failed validation
            CREATE TABLE IF NOT EXISTS quarantine_batches (
                id            TEXT PRIMARY KEY,
                org_id        TEXT NOT NULL DEFAULT 'default',
                pipeline_name TEXT NOT NULL,
                row_count     INTEGER NOT NULL,
                violations    TEXT NOT NULL DEFAULT '{}',
                sample_rows   TEXT NOT NULL DEFAULT '[]',
                status        TEXT NOT NULL DEFAULT 'pending'
                                  CHECK(status IN ('pending','reviewing','resolved','skipped')),
                fix_summary   TEXT,
                created_at    TEXT DEFAULT (datetime('now')),
                resolved_at   TEXT
            );

            -- Legacy: kept for backwards compat, no longer the primary flow
            CREATE TABLE IF NOT EXISTS resolutions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id         TEXT NOT NULL DEFAULT 'default',
                error_type     TEXT NOT NULL,
                error_fragment TEXT NOT NULL,
                pipeline_name  TEXT,
                operation      TEXT NOT NULL,
                label          TEXT NOT NULL,
                scope          TEXT NOT NULL CHECK(scope IN ('this_error', 'org', 'global')),
                applied_count  INTEGER DEFAULT 0,
                created_at     TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS events (
                id             TEXT PRIMARY KEY,
                org_id         TEXT NOT NULL DEFAULT 'default',
                pipeline_name  TEXT,
                error_type     TEXT NOT NULL,
                error_message  TEXT NOT NULL,
                traceback      TEXT,
                analysis       TEXT,
                suggestions    TEXT,
                failing_rows   TEXT,
                status         TEXT DEFAULT 'pending'
                                   CHECK(status IN ('pending', 'resolved', 'dismissed')),
                operation      TEXT,
                scope          TEXT,
                created_at     TEXT DEFAULT (datetime('now')),
                resolved_at    TEXT
            );
        """)
