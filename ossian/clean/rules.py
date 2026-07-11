"""Rule-based Cleaner (Step 3, module 4).

Deterministic, repeatable text/field cleaning: the same input always produces
the same output. Every transformation returns an auditable action so the
change can be shown before/after and logged (nothing is hidden from the trail).

Implements the guide's cleaning rules:
    text  -> trim spaces, fix broken PDF line breaks, drop blank lines,
             normalize quotes/dashes/encoding
    dates -> convert to one consistent (ISO) format, incl. epoch timestamps
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

Action = dict  # {"rule_name": str, "before_value": str, "after_value": str}


def _clip(s: str, n: int = 120) -> str:
    s = s.replace("\n", "\\n")
    return s if len(s) <= n else s[:n] + "…"


# --- text cleaning ---------------------------------------------------------
_QUOTE_MAP = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", " ": " ",
    "﻿": "", "​": "",
}
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")        # "exam-\nple" -> "example"
_INTRA_NEWLINE = re.compile(r"(?<![.\n])\n(?!\n)")  # single newline inside a sentence
_MULTISPACE = re.compile(r"[ \t ]{2,}")
_MULTINEWLINE = re.compile(r"\n{3,}")


def clean_text(text: str | None) -> tuple[str, list[Action]]:
    if text is None:
        return "", []
    original = text
    actions: list[Action] = []
    out = text

    # 1. unicode / encoding normalisation
    norm = unicodedata.normalize("NFKC", out)
    for bad, good in _QUOTE_MAP.items():
        norm = norm.replace(bad, good)
    if norm != out:
        actions.append({"rule_name": "normalize_encoding",
                        "before_value": _clip(out), "after_value": _clip(norm)})
        out = norm

    # 2. fix broken PDF hyphenation across line breaks
    fixed = _HYPHEN_BREAK.sub(r"\1\2", out)
    if fixed != out:
        actions.append({"rule_name": "fix_pdf_hyphenation",
                        "before_value": _clip(out), "after_value": _clip(fixed)})
        out = fixed

    # 3. join broken single line breaks inside a paragraph
    joined = _INTRA_NEWLINE.sub(" ", out)
    if joined != out:
        actions.append({"rule_name": "join_broken_linebreaks",
                        "before_value": _clip(out), "after_value": _clip(joined)})
        out = joined

    # 4. collapse whitespace / blank lines and trim
    collapsed = _MULTISPACE.sub(" ", out)
    collapsed = _MULTINEWLINE.sub("\n\n", collapsed)
    collapsed = "\n".join(ln.strip() for ln in collapsed.splitlines())
    collapsed = collapsed.strip()
    if collapsed != out:
        actions.append({"rule_name": "trim_whitespace",
                        "before_value": _clip(out), "after_value": _clip(collapsed)})
        out = collapsed

    if out == original:
        return out, []  # nothing changed -> no noise in the audit log
    return out, actions


# --- date standardisation --------------------------------------------------
_EPOCH_RE = re.compile(r"^\d{9,13}(\.\d+)?$")


def standardize_date(value: str | None) -> tuple[str | None, Action | None, bool]:
    """Return (iso_date_or_None, action_or_None, ok).

    ok=False means the value looked like a date but could not be parsed
    (flagged as 'invalid date' by the validator).
    """
    if value is None or str(value).strip() == "":
        return None, None, True
    raw = str(value).strip()

    # epoch seconds / millis
    if _EPOCH_RE.match(raw):
        try:
            num = float(raw)
            if num > 1e12:      # milliseconds
                num /= 1000.0
            iso = datetime.fromtimestamp(num, tz=timezone.utc).date().isoformat()
            if iso != raw:
                return iso, {"rule_name": "standardize_date_epoch",
                             "before_value": raw, "after_value": iso}, True
            return iso, None, True
        except (ValueError, OSError, OverflowError):
            return None, None, False

    try:
        from dateutil import parser as dateparser
        dt = dateparser.parse(raw, fuzzy=False)
        iso = dt.date().isoformat()
        if iso != raw:
            return iso, {"rule_name": "standardize_date",
                         "before_value": raw, "after_value": iso}, True
        return iso, None, True
    except (ValueError, OverflowError, TypeError):
        return None, None, False


# --- column-name standardisation ------------------------------------------
def standardize_column_name(name: str) -> str:
    n = unicodedata.normalize("NFKC", str(name)).strip().lower()
    n = re.sub(r"[^\w]+", "_", n)
    n = re.sub(r"_+", "_", n).strip("_")
    return n or "column"
