"""Source mapping module (Step 2, question 2: "What type of research source?").

Two jobs:
  1. Suggest the research source_type (Interview / Survey / Review /
     Experiment / Document) from the filename, file type, columns, and content.
  2. Suggest a column mapping for tabular sources, following the guide's
     practical example (Customer_ID -> participant_id, Review_Text -> content...).

These are *suggestions*: the human confirms them during import (Step 2) and the
AI/agent layer echoes them during cleaning (Step 3). Nothing here is destructive.
"""
from __future__ import annotations

import re
from ..models import ExtractionResult

# --- source_type inference -------------------------------------------------
_FILENAME_HINTS = [
    ("Interview", re.compile(r"interview|transcript|think.?aloud|usability", re.I)),
    ("Interview", re.compile(r"chatbot|conversation|call|session", re.I)),
    ("Review", re.compile(r"review|rating|app.?store|g2|amazon", re.I)),
    ("Survey", re.compile(r"survey|questionnaire|diary|feedback|poll|taste", re.I)),
    ("Experiment", re.compile(r"experiment|a.?b.?test|control|treatment|trial", re.I)),
    ("Document", re.compile(r"post|reddit|community|forum|thread|log", re.I)),
]

_CONTENT_EXPERIMENT = re.compile(
    r"\b(control group|treatment group|hypothesis|p\s*[<=]|p-value|A/B|"
    r"randomi[sz]ed|sample size|effect size)\b", re.I)
_CONTENT_REVIEW = re.compile(r"\b(star rating|stars?|verified purchase|helpful votes?)\b", re.I)

_COL_RATING = re.compile(r"(rating|stars?|score)", re.I)
_COL_SURVEYISH = re.compile(r"(q\d+|question|answer|option|choice|likert|response)", re.I)
_COL_REVIEWISH = re.compile(r"(review|verified|helpful|vine|product)", re.I)


def infer_source_type(res: ExtractionResult, file_stem: str) -> tuple[str, float, str]:
    """Return (source_type, confidence, reason)."""
    # 1. filename signal (strong)
    for stype, rx in _FILENAME_HINTS:
        if rx.search(file_stem):
            return stype, 0.85, f"filename matches /{rx.pattern[:30]}.../"

    cols = " ".join(res.columns or [])
    sample = " ".join(u.original_text for u in res.units[:40])[:5000]

    # 2. structured-column signals
    if res.columns:
        if _COL_REVIEWISH.search(cols) and _COL_RATING.search(cols):
            return "Review", 0.8, "columns include review + rating fields"
        if _CONTENT_EXPERIMENT.search(cols) or _CONTENT_EXPERIMENT.search(sample):
            return "Experiment", 0.7, "experiment terms present (control/treatment/p-value)"
        if _COL_RATING.search(cols):
            return "Review", 0.6, "rating/score column present"
        if _COL_SURVEYISH.search(cols):
            return "Survey", 0.65, "survey-style question/answer columns"
        return "Survey", 0.5, "tabular data with no strong review/experiment signal"

    # 3. free-text signals
    speakers = sum(1 for u in res.units if u.metadata.get("speaker"))
    if res.units and speakers / len(res.units) > 0.3:
        return "Interview", 0.75, "many units carry speaker labels (dialogue)"
    if _CONTENT_EXPERIMENT.search(sample):
        return "Experiment", 0.6, "experiment terminology in text"
    if _CONTENT_REVIEW.search(sample):
        return "Review", 0.6, "review terminology in text"
    if res.file_type in ("pdf", "docx"):
        return "Document", 0.6, "document format without dialogue structure"
    return "Document", 0.4, "defaulted — no strong signal"


# --- column mapping suggestions -------------------------------------------
# incoming-name pattern -> standard field (guide's internal structure)
_MAP_RULES: list[tuple[str, re.Pattern]] = [
    ("participant_id", re.compile(r"(customer|user|reviewer|participant|respondent|author|username)([ _-]?(id|name))?$", re.I)),
    ("content",        re.compile(r"(review[_ ]?text|review[_ ]?body|comment|entry[_ ]?text|response[_ ]?text|text|body|message|content|joke|post|answer)", re.I)),
    ("score",          re.compile(r"(rating|stars?|score|star[_ ]?rating|helpful[_ ]?votes?)", re.I)),
    ("date",           re.compile(r"(date|timestamp|created|time|updated)", re.I)),
    ("customer_segment", re.compile(r"(segment|tier|plan|cohort|group|category|subreddit)", re.I)),
    ("title",          re.compile(r"(title|headline|subject)", re.I)),
]


# The standard fields a column can be mapped to (used by the interactive
# column-mapping tool). "ignore" = keep as plain metadata.
STANDARD_FIELDS = ["ignore", "content", "participant_id", "score", "date",
                   "customer_segment", "title"]


def suggest_column_mapping(columns: list[str] | None) -> list[dict]:
    """Return a list of {incoming, standard, confidence} suggestions."""
    if not columns:
        return []
    suggestions: list[dict] = []
    used_standard: set[str] = set()
    for col in columns:
        for standard, rx in _MAP_RULES:
            if standard in used_standard and standard != "customer_segment":
                continue
            if rx.search(str(col)):
                suggestions.append({"incoming": col, "standard": standard,
                                    "confidence": 0.8})
                used_standard.add(standard)
                break
    return suggestions
