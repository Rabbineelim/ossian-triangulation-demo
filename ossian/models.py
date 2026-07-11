"""Shared in-memory data structures passed between the pipeline modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractedUnit:
    """One analyzable piece of content produced by Step 2 extraction.

    Guide rule: one review = one unit; one interview turn/paragraph = one unit;
    one survey response row = one unit; one transcript cue = one unit.
    """
    original_text: str
    row_number: int | None = None
    page_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    """Output of the Step 2 extraction + standardization stage for one file."""
    file_name: str
    file_type: str                      # detected kind: pdf/docx/txt/csv/xlsx/tsv/vtt/...
    detected_by: str                    # "extension" or "magic-bytes:<sig>"
    source_type: str                    # Interview / Survey / Review / Experiment / Document
    source_type_confidence: float
    units: list[ExtractedUnit] = field(default_factory=list)
    columns: list[str] | None = None    # for tabular sources
    column_mapping: dict[str, str] = field(default_factory=dict)  # incoming -> standard
    warnings: list[str] = field(default_factory=list)
    extractable: bool = True            # False => future-roadmap format (audio/video/image)
    truncated: bool = False             # True if capped at MAX_UNITS_PER_SOURCE

    @property
    def n_units(self) -> int:
        return len(self.units)


@dataclass
class CleanedUnit:
    """Result of Step 3 rule-based cleaning for one raw unit."""
    unit_id: int
    original_text: str
    cleaned_text: str
    status: str                          # kept / empty / duplicate / invalid / short
    quality_flags: list[str] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)  # rule_name/before/after

    @property
    def usable(self) -> bool:
        return self.status == "kept"
