"""SQLite database layer.

Implements the *exact* schema from the Step 3 guide (section 7, "Suggested
Database Structure") plus a `projects` table. SQLite is used so the prototype
runs with zero setup; the schema ports directly to PostgreSQL/MySQL later.

Tables (guide → here):
    sources           source_id, project_id, file_name, file_type, source_type, uploaded_at
    raw_units         unit_id, source_id, original_text, row_number, page_number, metadata
    cleaned_units     cleaned_unit_id, unit_id, cleaned_text, status, quality_flags
    cleaning_actions  action_id, unit_id, rule_name, before_value, after_value, ai_suggestion_id
    ai_suggestions    suggestion_id, unit_id, suggestion_type, suggestion_text, confidence
    approval_log      approval_id, user_id, decision, timestamp, note
    quality_reports   report_id, project_id, score, issues_summary, final_status
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    project_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    description  TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    source_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER NOT NULL REFERENCES projects(project_id),
    file_name    TEXT NOT NULL,
    file_type    TEXT,                -- detected extension / kind (pdf, csv, ...)
    source_type  TEXT,                -- Interview / Survey / Review / Experiment / Document
    file_path    TEXT,                -- stored original (evidence trail)
    n_units      INTEGER DEFAULT 0,
    import_status TEXT DEFAULT 'imported',
    notes        TEXT,
    uploaded_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_units (
    unit_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id     INTEGER NOT NULL REFERENCES sources(source_id),
    original_text TEXT,               -- raw extracted text / row content
    row_number    INTEGER,
    page_number   INTEGER,
    metadata      TEXT                 -- JSON: participant, rating, date, segment, ...
);

CREATE TABLE IF NOT EXISTS cleaned_units (
    cleaned_unit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id         INTEGER NOT NULL REFERENCES raw_units(unit_id),
    cleaned_text    TEXT,
    status          TEXT,             -- kept / empty / duplicate / invalid / short
    quality_flags   TEXT              -- JSON list of flags
);

CREATE TABLE IF NOT EXISTS cleaning_actions (
    action_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id          INTEGER REFERENCES raw_units(unit_id),
    rule_name        TEXT,
    before_value     TEXT,
    after_value      TEXT,
    ai_suggestion_id INTEGER REFERENCES ai_suggestions(suggestion_id),
    created_at       TEXT
);

CREATE TABLE IF NOT EXISTS ai_suggestions (
    suggestion_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       INTEGER REFERENCES sources(source_id),
    unit_id         INTEGER REFERENCES raw_units(unit_id),
    suggestion_type TEXT,             -- source_type / column_mapping / cleaning_rule / explanation
    suggestion_text TEXT,
    confidence      REAL,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS approval_log (
    approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER REFERENCES projects(project_id),
    source_id   INTEGER REFERENCES sources(source_id),
    user_id     TEXT,
    decision    TEXT,                 -- approved / rejected / edited
    note        TEXT,
    timestamp   TEXT
);

CREATE TABLE IF NOT EXISTS quality_reports (
    report_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id     INTEGER REFERENCES projects(project_id),
    source_id      INTEGER REFERENCES sources(source_id),
    score          REAL,
    issues_summary TEXT,              -- JSON of metrics
    final_status   TEXT,
    created_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_raw_units_source ON raw_units(source_id);
CREATE INDEX IF NOT EXISTS idx_cleaned_units_unit ON cleaned_units(unit_id);
CREATE INDEX IF NOT EXISTS idx_sources_project ON sources(project_id);


CREATE TABLE IF NOT EXISTS source_domain_assignments (
    assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id      INTEGER NOT NULL UNIQUE REFERENCES sources(source_id),
    domain         TEXT NOT NULL,
    subdomain      TEXT,
    assigned_by    TEXT,
    assigned_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_units (
    evidence_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id     INTEGER NOT NULL REFERENCES projects(project_id),
    source_id      INTEGER NOT NULL REFERENCES sources(source_id),
    unit_id        INTEGER NOT NULL REFERENCES raw_units(unit_id),
    domain         TEXT NOT NULL,
    subdomain      TEXT,
    theme          TEXT NOT NULL,
    stance         TEXT,
    evidence_text  TEXT,
    context_json   TEXT,
    rating         REAL,
    keyword_hits   INTEGER DEFAULT 0,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_findings (
    finding_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL REFERENCES projects(project_id),
    source_id       INTEGER NOT NULL REFERENCES sources(source_id),
    domain          TEXT NOT NULL,
    theme           TEXT NOT NULL,
    total_records   INTEGER,
    theme_mentions  INTEGER,
    prevalence      REAL,
    negative_count  INTEGER,
    positive_count  INTEGER,
    mixed_count     INTEGER,
    finding_stance  TEXT,
    bias_note       TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS triangulation_results (
    result_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id            INTEGER NOT NULL REFERENCES projects(project_id),
    domain                TEXT NOT NULL,
    theme                 TEXT NOT NULL,
    relationship          TEXT NOT NULL,
    confidence            TEXT,
    proposed_claim        TEXT,
    explanation           TEXT,
    source_ids_json       TEXT,
    comparability_status  TEXT,
    status                TEXT DEFAULT 'pending_review',
    created_at             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS triangulation_reviews (
    review_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id     INTEGER NOT NULL REFERENCES triangulation_results(result_id),
    user_id       TEXT,
    decision      TEXT,
    edited_claim  TEXT,
    note          TEXT,
    reviewed_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_project_domain ON evidence_units(project_id, domain, theme);
CREATE INDEX IF NOT EXISTS idx_findings_project_domain ON source_findings(project_id, domain, theme);
CREATE INDEX IF NOT EXISTS idx_tri_results_project ON triangulation_results(project_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def session(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --- small helpers ---------------------------------------------------------
def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def create_project(conn: sqlite3.Connection, name: str, description: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO projects(name, description, created_at) VALUES (?,?,?)",
        (name, description, now()),
    )
    return int(cur.lastrowid)


def get_project(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM projects WHERE project_id=?", (project_id,)
    ).fetchone()


def delete_project(conn: sqlite3.Connection, project_id: int) -> list[str]:
    """Delete a project and everything under it. Returns stored file paths to unlink."""
    file_paths = [
        r["file_path"] for r in conn.execute(
            "SELECT file_path FROM sources WHERE project_id=?", (project_id,)).fetchall()
        if r["file_path"]
    ]
    # child rows first (no ON DELETE CASCADE in schema — do it explicitly)
    conn.execute(
        "DELETE FROM cleaning_actions WHERE unit_id IN "
        "(SELECT unit_id FROM raw_units WHERE source_id IN "
        "(SELECT source_id FROM sources WHERE project_id=?))", (project_id,))
    conn.execute(
        "DELETE FROM cleaned_units WHERE unit_id IN "
        "(SELECT unit_id FROM raw_units WHERE source_id IN "
        "(SELECT source_id FROM sources WHERE project_id=?))", (project_id,))
    conn.execute(
        "DELETE FROM ai_suggestions WHERE source_id IN "
        "(SELECT source_id FROM sources WHERE project_id=?)", (project_id,))
    conn.execute(
        "DELETE FROM raw_units WHERE source_id IN "
        "(SELECT source_id FROM sources WHERE project_id=?)", (project_id,))
    conn.execute("DELETE FROM triangulation_reviews WHERE result_id IN (SELECT result_id FROM triangulation_results WHERE project_id=?)", (project_id,))
    conn.execute("DELETE FROM triangulation_results WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM source_findings WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM evidence_units WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM source_domain_assignments WHERE source_id IN (SELECT source_id FROM sources WHERE project_id=?)", (project_id,))
    conn.execute("DELETE FROM quality_reports WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM approval_log WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM sources WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM projects WHERE project_id=?", (project_id,))
    return file_paths
