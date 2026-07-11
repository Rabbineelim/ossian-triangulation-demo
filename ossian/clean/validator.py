"""Validation Checker (Step 3, module 3).

Finds missing values, empty text, invalid dates, impossible ratings, and broken
extraction. Produces `validation_flags` per unit. Flags are advisory: hard-empty
content is removable by rule, but suspicious values (bad ratings, weird dates)
are *flagged for human review*, never silently dropped (governance rule).
"""
from __future__ import annotations

import re
from typing import Any

from .. import config
from . import rules

_RATING_COL = re.compile(r"(rating|stars?)", re.I)
_BROKEN_RE = re.compile(r"�")               # replacement char from bad decode


def _invert(mapping: dict[str, str]) -> dict[str, str]:
    """incoming->standard  =>  standard->incoming (first wins)."""
    out: dict[str, str] = {}
    for incoming, standard in (mapping or {}).items():
        out.setdefault(standard, incoming)
    return out


def validate_unit(
    cleaned_text: str,
    metadata: dict[str, Any] | None,
    column_mapping: dict[str, str] | None,
    source_type: str,
) -> dict[str, Any]:
    """Return {flags, actions, meta_updates, hard_empty}.

    hard_empty=True marks a unit the rule engine may remove (no content at all).
    Everything else is a flag for the reviewer.
    """
    metadata = metadata or {}
    flags: list[str] = []
    actions: list[rules.Action] = []
    meta_updates: dict[str, Any] = {}

    text = (cleaned_text or "").strip()

    # 1. empty / missing content
    hard_empty = len(text) == 0
    if hard_empty:
        flags.append("empty")

    # 2. very short response (flag for review, keep)
    elif len(text) < config.SHORT_TEXT_MIN_CHARS:
        flags.append("short")

    # 3. broken extraction (undecodable characters survived)
    if _BROKEN_RE.search(cleaned_text or ""):
        flags.append("broken_extraction")

    std_map = _invert(column_mapping or {})

    # 4. impossible rating (only for genuine rating columns, not vote counts)
    rating_col = None
    for incoming in (metadata or {}):
        if _RATING_COL.search(str(incoming)):
            rating_col = incoming
            break
    if rating_col is None and "score" in std_map and _RATING_COL.search(std_map["score"]):
        rating_col = std_map["score"]
    if rating_col and metadata.get(rating_col) not in (None, ""):
        try:
            val = float(str(metadata[rating_col]).strip())
            if not (config.RATING_MIN <= val <= config.RATING_MAX):
                flags.append("invalid_rating")
        except (ValueError, TypeError):
            flags.append("invalid_rating")

    # 5. date standardisation + invalid-date flag
    date_col = std_map.get("date")
    if date_col is None:
        for incoming in metadata:
            if re.search(r"(date|timestamp|time)", str(incoming), re.I):
                date_col = incoming
                break
    if date_col and metadata.get(date_col) not in (None, ""):
        iso, action, ok = rules.standardize_date(metadata[date_col])
        if not ok:
            flags.append("invalid_date")
        elif iso and action:
            meta_updates[date_col] = iso
            actions.append(action)

    # 5b. experiment data: numeric outcome fields must be numeric
    if source_type == "Experiment":
        for col in metadata:
            if re.search(r"(outcome|result|measure|value|score|metric|n_|sample)",
                         str(col), re.I) and metadata.get(col) not in (None, ""):
                try:
                    float(str(metadata[col]).strip())
                except (ValueError, TypeError):
                    flags.append("invalid_numeric")
                    break

    # 6. missing key metadata (participant/date) — advisory
    if source_type in ("Survey", "Review", "Experiment"):
        has_pid = any(re.search(r"(participant|user|customer|reviewer|author)", str(k), re.I)
                      for k in metadata)
        if not has_pid:
            flags.append("missing_participant_meta")

    return {"flags": flags, "actions": actions,
            "meta_updates": meta_updates, "hard_empty": hard_empty}
