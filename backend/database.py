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

            -- Tier 3: org-wide incident history (resolved quarantine batches with embeddings)
            -- Searched via embedding similarity across ALL pipelines in the org.
            -- "Pipeline B gets fixed by knowledge from pipeline A."
            CREATE TABLE IF NOT EXISTS org_incidents (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id          TEXT NOT NULL,
                pipeline_name   TEXT NOT NULL,
                incident_text   TEXT NOT NULL,   -- normalized fingerprint for embedding
                embedding       TEXT NOT NULL,   -- JSON float array (768-dim nomic-embed-text)
                fix_policy      TEXT NOT NULL,   -- JSON operation spec actually applied
                label           TEXT NOT NULL,
                violations      TEXT,            -- JSON violation summary for display
                resolved_count  INTEGER NOT NULL DEFAULT 1,
                created_at      TEXT DEFAULT (datetime('now'))
            );

            -- Tier 4 corpus: anonymized cross-org error patterns + fix policies
            -- Embeddings stored as JSON float arrays (local dev).
            -- Production: swap this table for a pgvector column:
            --   ALTER TABLE corpus_entries ADD COLUMN embedding vector(768);
            --   CREATE INDEX ON corpus_entries USING ivfflat (embedding vector_cosine_ops);
            CREATE TABLE IF NOT EXISTS corpus_entries (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint      TEXT NOT NULL UNIQUE,
                fingerprint_text TEXT NOT NULL,
                embedding        TEXT NOT NULL,
                fix_policy       TEXT NOT NULL,
                label            TEXT NOT NULL,
                vertical         TEXT NOT NULL DEFAULT 'general',
                error_class      TEXT,
                applied_count    INTEGER NOT NULL DEFAULT 1,
                confidence       REAL NOT NULL DEFAULT 1.0,
                created_at       TEXT DEFAULT (datetime('now')),
                updated_at       TEXT DEFAULT (datetime('now'))
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
