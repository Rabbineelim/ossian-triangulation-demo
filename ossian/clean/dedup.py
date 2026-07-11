"""Duplicate detection (part of Step 3 rule-based cleaning).

Guide's four duplicate types, applied where each is actually correct:

    tabular source (survey / review / experiment rows)
        -> "duplicate row": two units match only when ALL data columns match
           (the synthetic row-index column is ignored). This is the safe,
           defensible definition: it will not flag two distinct survey
           respondents just because they share one categorical answer, and it
           preserves prevalence (e.g. the same joke reposted with a different id
           is a separate data point, not a duplicate).

    free-text source (interview / transcript / document / post)
        -> "exact / lowercase duplicate" of the normalized text, and
           "same participant + same response" when a speaker/participant is known.

Only these exact matches are auto-removed (fully safe). The first occurrence is
always kept; later copies point back to the original for the evidence trail.
"""
from __future__ import annotations

import re
from typing import Any

_WS = re.compile(r"\s+")
DEFAULT_IGNORE_COLS = ("index",)  # synthetic pandas index created during extraction


def _norm(text: str) -> str:
    return _WS.sub(" ", (text or "").strip().lower())


def _row_key(row_values: dict[str, Any], ignore_cols: tuple[str, ...]) -> str | None:
    cells = {k: v for k, v in (row_values or {}).items() if k not in ignore_cols}
    if not any(str(v).strip() for v in cells.values() if v not in (None, "")):
        return None  # entirely empty row -> handled as empty, not duplicate
    return "||".join(f"{k}={_norm(str(v))}" for k, v in sorted(cells.items())
                     if v not in (None, ""))


def find_duplicates(
    units: list[dict[str, Any]],
    tabular: bool = False,
    ignore_cols: tuple[str, ...] = DEFAULT_IGNORE_COLS,
) -> dict[int, dict[str, Any]]:
    """units: list of {unit_id, cleaned_text, participant, row_values}.

    Returns {unit_id: {"duplicate_of": first_unit_id, "kind": str}} for each
    duplicate. Originals are not included.
    """
    seen: dict[str, int] = {}
    result: dict[int, dict[str, Any]] = {}

    for u in units:
        uid = u["unit_id"]

        if tabular and u.get("row_values"):
            key = _row_key(u["row_values"], ignore_cols)
            kind = "duplicate row"
        else:
            text = u.get("cleaned_text") or ""
            if not text.strip():
                continue
            participant = str(u.get("participant") or "").strip().lower()
            if participant:
                key = f"participant::{participant}::{_norm(text)}"
                kind = "same participant + same response"
            else:
                key = f"text::{_norm(text)}"
                kind = "exact/lowercase"

        if key is None:
            continue
        if key in seen:
            result[uid] = {"duplicate_of": seen[key], "kind": kind}
        else:
            seen[key] = uid

    return result
