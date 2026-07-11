"""Audit Logger (Step 3, module 7).

Records every cleaning change: original value, cleaned value, rule used, the AI
suggestion (if any), and later the user's decision + reviewer + time. This is
what makes a finding defensible — every unit can be traced back to what changed
and why. Nothing is hidden from this trail.
"""
from __future__ import annotations

from typing import Any

from .. import db


def log_actions(conn, unit_id: int, actions: list[dict[str, Any]],
                ai_suggestion_id: int | None = None) -> None:
    if not actions:
        return
    conn.executemany(
        """INSERT INTO cleaning_actions
           (unit_id, rule_name, before_value, after_value, ai_suggestion_id, created_at)
           VALUES (?,?,?,?,?,?)""",
        [(unit_id, a.get("rule_name"), a.get("before_value"), a.get("after_value"),
          ai_suggestion_id, db.now()) for a in actions],
    )


def log_suggestion(conn, source_id: int, unit_id: int | None,
                   suggestion_type: str, suggestion_text: str,
                   confidence: float) -> int:
    cur = conn.execute(
        """INSERT INTO ai_suggestions
           (source_id, unit_id, suggestion_type, suggestion_text, confidence, created_at)
           VALUES (?,?,?,?,?,?)""",
        (source_id, unit_id, suggestion_type, suggestion_text, confidence, db.now()),
    )
    return int(cur.lastrowid)


def log_approval(conn, project_id: int, source_id: int | None,
                 user_id: str, decision: str, note: str = "") -> None:
    conn.execute(
        """INSERT INTO approval_log
           (project_id, source_id, user_id, decision, note, timestamp)
           VALUES (?,?,?,?,?,?)""",
        (project_id, source_id, user_id, decision, note, db.now()),
    )
