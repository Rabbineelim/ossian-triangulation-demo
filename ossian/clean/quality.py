"""Quality scoring + report (Step 3, "Recommended quality report output" and
"Performance checking").

Two outputs:
  * a report matching the guide's example (raw units, duplicates removed,
    empty/invalid removed, final clean units, quality score /100, status)
  * performance metrics (import success, duplicate detection count, missing-value
    detection rate, final usable unit rate, cleaning time per source).
"""
from __future__ import annotations

from typing import Any

from .. import config


def compute_score(counts: dict[str, int]) -> float:
    """Score out of 100. Deterministic: penalties scale with problem rates."""
    raw = max(1, counts.get("raw_units", 0))
    w = config.QUALITY_WEIGHTS
    penalty = (
        w["duplicate_rate"] * counts.get("duplicate_units", 0) / raw
        + w["empty_rate"] * counts.get("empty_units", 0) / raw
        + w["invalid_rate"] * counts.get("invalid_units", 0) / raw
        + w["short_rate"] * counts.get("short_units", 0) / raw
        + w["missing_meta_rate"] * counts.get("missing_meta_units", 0) / raw
    )
    return round(max(0.0, 100.0 - penalty), 1)


def build_report(
    project_name: str,
    sources_imported: int,
    counts: dict[str, int],
    seconds: float,
    files_attempted: int,
    files_succeeded: int,
) -> dict[str, Any]:
    raw = counts.get("raw_units", 0)
    duplicates = counts.get("duplicate_units", 0)
    empty = counts.get("empty_units", 0)
    invalid = counts.get("invalid_units", 0)
    short = counts.get("short_units", 0)
    missing_meta = counts.get("missing_meta_units", 0)

    # Rule engine removes only the safe classes (empty + exact duplicates).
    removed = empty + duplicates
    final_clean = max(0, raw - removed)

    score = compute_score(counts)
    status = config.status_for_score(score)

    return {
        # --- guide's headline report ---
        "project": project_name,
        "sources_imported": sources_imported,
        "raw_units": raw,
        "duplicate_units_removed": duplicates,
        "empty_units_removed": empty,
        "invalid_units_flagged": invalid,
        "short_units_flagged": short,
        "final_clean_units": final_clean,
        "quality_score": score,
        "status": status,
        # --- performance metrics (Step 3 performance table) ---
        "performance": {
            "import_success_rate": round(files_succeeded / max(1, files_attempted), 3),
            "duplicate_detection_count": duplicates,
            "missing_value_detection_rate": round((empty + missing_meta) / max(1, raw), 3),
            "final_usable_unit_rate": round(final_clean / max(1, raw), 3),
            "cleaning_seconds_total": round(seconds, 2),
            "cleaning_seconds_per_source": round(seconds / max(1, sources_imported), 3),
        },
    }
