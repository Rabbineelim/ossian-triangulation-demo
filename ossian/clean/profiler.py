"""Data Profiler (Step 3, module 2).

Counts units, identifies columns, detects text vs numeric fields, checks the
source type, and measures basic quality *before* cleaning. Output feeds the
AI-assistant explanations and gives the reviewer a baseline to compare against.
"""
from __future__ import annotations

import statistics
from typing import Any


def profile_units(raw_units: list[dict[str, Any]], source_type: str) -> dict[str, Any]:
    """raw_units: list of {original_text, metadata}."""
    n = len(raw_units)
    lengths = [len((u.get("original_text") or "")) for u in raw_units]
    empties = sum(1 for L in lengths if L == 0)

    # column inventory (from tabular metadata)
    columns: dict[str, dict[str, Any]] = {}
    for u in raw_units:
        meta = u.get("metadata") or {}
        for k, v in meta.items():
            c = columns.setdefault(k, {"non_null": 0, "numeric": 0, "total": 0})
            c["total"] += 1
            if v not in (None, "", "nan"):
                c["non_null"] += 1
                try:
                    float(str(v))
                    c["numeric"] += 1
                except (ValueError, TypeError):
                    pass

    col_report = []
    for name, c in columns.items():
        total = c["total"] or 1
        col_report.append({
            "column": name,
            "fill_rate": round(c["non_null"] / total, 3),
            "numeric": c["numeric"] / total > 0.8,
            "missing": total - c["non_null"],
        })

    return {
        "source_type": source_type,
        "raw_units": n,
        "empty_units": empties,
        "avg_text_length": round(statistics.mean(lengths), 1) if lengths else 0,
        "median_text_length": round(statistics.median(lengths), 1) if lengths else 0,
        "max_text_length": max(lengths) if lengths else 0,
        "is_tabular": bool(columns),
        "n_columns": len(columns),
        "columns": sorted(col_report, key=lambda x: x["column"]),
    }
