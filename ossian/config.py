"""Central configuration for the Ossian prototype.

Everything is filesystem-based so the prototype runs with zero external
infrastructure. The tech-stack guide recommends PostgreSQL for later; the DB
layer is written so the schema ports directly.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Paths -----------------------------------------------------------------
# Project root = folder that contains the `ossian` package.
ROOT = Path(__file__).resolve().parent.parent

STORAGE_DIR = Path(os.environ.get("OSSIAN_STORAGE", ROOT / "storage"))
UPLOAD_DIR = STORAGE_DIR / "uploads"          # original files (evidence trail)
DB_PATH = Path(os.environ.get("OSSIAN_DB", STORAGE_DIR / "ossian.db"))
REPORTS_DIR = Path(os.environ.get("OSSIAN_REPORTS", ROOT / "reports"))

for _d in (STORAGE_DIR, UPLOAD_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Step 2: import channel ------------------------------------------------
# MVP formats the guide asks us to focus on first. Anything else is accepted
# but flagged as "future roadmap" (audio / video / images).
MVP_EXTRACTABLE = {"pdf", "docx", "txt", "csv", "xlsx", "tsv", "vtt"}
FUTURE_ROADMAP = {"m4a", "mp3", "wav", "mp4", "mov", "avi", "png", "jpg", "jpeg"}

# Large files (Amazon reviews TSV is ~250 MB) — cap units per source so the
# demo stays fast. The engine handles the full file; this is only a sample cap.
MAX_UNITS_PER_SOURCE = int(os.environ.get("OSSIAN_MAX_UNITS", "4000"))

# --- Step 3: cleaning thresholds ------------------------------------------
SHORT_TEXT_MIN_CHARS = 15      # responses shorter than this are flagged for review
RATING_MIN, RATING_MAX = 1, 5  # default valid rating range (overridable per column)

# Quality-score penalty weights (points deducted from 100).
QUALITY_WEIGHTS = {
    "duplicate_rate": 25,      # weight applied to (duplicate units / raw units)
    "empty_rate": 30,          # weight applied to (empty units / raw units)
    "invalid_rate": 25,        # weight applied to (invalid units / raw units)
    "short_rate": 10,          # weight applied to (very-short units / raw units)
    "missing_meta_rate": 10,   # weight applied to (missing key metadata / raw units)
}

STATUS_THRESHOLDS = [          # (min_score, label)
    (85, "Ready"),
    (70, "Ready with minor issues"),
    (50, "Needs review"),
    (0, "Not ready — major issues"),
]


def status_for_score(score: float) -> str:
    for threshold, label in STATUS_THRESHOLDS:
        if score >= threshold:
            return label
    return "Not ready — major issues"
