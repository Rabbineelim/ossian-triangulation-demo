"""AI / Agent Assistant (Step 3, module 5).

The assistant SUGGESTS and EXPLAINS. It never finalises a change. Per the
design doc's governance table it may:
    * suggest source type / column mapping
    * explain why a row was flagged
    * recommend a cleaning rule
    * summarise the cleaning report in plain language
...and it must NOT auto-delete data, auto-change research meaning, merge
participants, remove outliers, finalise the dataset, or hide actions.

This MVP implementation is a deterministic, offline heuristic assistant (same
input -> same explanation, no external API, fully auditable). `AGENT_BOUNDARY`
documents the hard limits and is enforced by the pipeline: this module only ever
produces `ai_suggestions` rows — it has no path that writes `cleaned_units`.
"""
from __future__ import annotations

from typing import Any

# Hard governance limits — the pipeline asserts the assistant never crosses these.
AGENT_BOUNDARY = {
    "can": [
        "suggest source type",
        "suggest column mapping",
        "explain why a unit is flagged",
        "recommend a cleaning rule",
        "summarise the cleaning report in plain language",
        "ask the user to clarify uncertain mappings",
    ],
    "must_not": [
        "auto-delete important data without approval",
        "auto-change research meaning",
        "merge participants automatically",
        "remove outliers without permission",
        "finalise the clean dataset alone",
        "hide cleaning actions from the audit trail",
    ],
}

_FLAG_EXPLANATIONS = {
    "empty": "No text content after extraction — safe to remove as an empty unit.",
    "short": "Very short response (below the minimum length). Kept, but flagged so "
             "you can decide whether it carries real signal.",
    "duplicate": "Identical to an earlier unit. Removing the copy prevents "
                 "double-counting the same evidence.",
    "invalid_rating": "Rating value falls outside the expected range. Flagged for "
                      "review — not removed, because it may be a real edge value.",
    "invalid_date": "Date could not be parsed into a standard format. Flagged so "
                    "you can correct or confirm it.",
    "invalid_numeric": "A numeric experiment field holds a non-numeric value. "
                       "Flagged for review — check the measurement/outcome column.",
    "broken_extraction": "Undecodable characters survived extraction — the source "
                         "encoding may be wrong. Flagged for a spot-check.",
    "missing_participant_meta": "No participant/respondent identifier found. Fine "
                                "for anonymous data; flagged in case it was lost in import.",
}


# Flags that describe the whole SOURCE (a missing column, etc.) rather than one
# unit. These are explained once at source level, not repeated on every row.
SOURCE_LEVEL_FLAGS = {"missing_participant_meta"}


def explain_flags(flags: list[str]) -> str:
    """Plain-language explanation for a unit's flags (suggestion only)."""
    parts = [_FLAG_EXPLANATIONS[f] for f in flags if f in _FLAG_EXPLANATIONS]
    return " ".join(parts)


def explain_unit(flags: list[str], status: str | None = None,
                 rating_value: str | None = None) -> str:
    """Per-unit explanation. Skips source-level flags and references the actual
    offending value where possible, so two flagged rows don't read identically."""
    parts: list[str] = []
    for f in flags:
        if f in SOURCE_LEVEL_FLAGS:
            continue
        if f == "invalid_rating" and rating_value not in (None, ""):
            parts.append(f"Rating '{rating_value}' is outside the expected 1-5 range. "
                         "Flagged for review, not removed.")
        elif f in _FLAG_EXPLANATIONS:
            parts.append(_FLAG_EXPLANATIONS[f])
    if status == "duplicate":
        parts.append(_FLAG_EXPLANATIONS["duplicate"])
    return " ".join(parts)


def explain_source_flags(counts: dict) -> list[dict]:
    """One suggestion per source-level issue (shown once, not per row)."""
    out: list[dict] = []
    n = counts.get("missing_meta_units", 0)
    if n:
        out.append({"suggestion_type": "note", "confidence": 0.6,
                    "suggestion_text": f"No participant/respondent column found — "
                    f"{n} units flagged. Fine for anonymous or non-survey data (e.g. "
                    f"a jobs or product table); add an ID column if you need to trace "
                    f"responses to people."})
    return out


def suggest_cleaning_rule(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Recommend (never apply) cleaning rules based on the profile."""
    recs: list[dict[str, Any]] = []
    if profile.get("empty_units", 0) > 0:
        recs.append({"suggestion_type": "cleaning_rule",
                     "suggestion_text": f"Remove {profile['empty_units']} empty units.",
                     "confidence": 0.95})
    if profile.get("is_tabular") and profile.get("n_columns", 0):
        low_fill = [c["column"] for c in profile.get("columns", []) if c["fill_rate"] < 0.5]
        if low_fill:
            recs.append({"suggestion_type": "cleaning_rule",
                         "suggestion_text": "Columns with heavy missing data: "
                                            + ", ".join(low_fill[:6])
                                            + ". Consider confirming they are optional.",
                         "confidence": 0.6})
    return recs


def summarise_report(report: dict[str, Any]) -> str:
    """One-paragraph plain-language summary of the cleaning report (suggestion)."""
    return (
        f"Imported {report['sources_imported']} source(s) totalling "
        f"{report['raw_units']:,} raw units. The rule engine removed "
        f"{report['duplicate_units_removed']:,} duplicate and "
        f"{report['empty_units_removed']:,} empty units, and flagged "
        f"{report['invalid_units_flagged']:,} invalid and "
        f"{report['short_units_flagged']:,} very-short units for your review. "
        f"That leaves {report['final_clean_units']:,} clean units. "
        f"Quality score {report['quality_score']}/100 — {report['status']}. "
        f"Nothing was finalised: approve, edit, or reject before this becomes "
        f"the analysis-ready dataset."
    )
