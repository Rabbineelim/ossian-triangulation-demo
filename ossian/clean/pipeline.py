"""Cleaning pipeline orchestrator (Step 3).

Runs the 8 modules in order for a source, then aggregates a project report:

    Receiver -> Profiler -> (Rule Cleaner + Validator per unit) -> Dedup
             -> write cleaned_units + audit actions + AI explanations
             -> Quality report -> (Human approval, via web UI) -> Export
"""
from __future__ import annotations

import re
import time
from typing import Any

from .. import db
from . import ai_assistant, audit, dedup, profiler, quality, rules, validator

_PARTICIPANT_RE = re.compile(r"(participant|respondent|user|customer|reviewer|author|username)", re.I)


def _participant_of(metadata: dict[str, Any]) -> str | None:
    for k, v in (metadata or {}).items():
        if _PARTICIPANT_RE.search(str(k)) and v:
            return str(v)
    return None


_RATING_RE = re.compile(r"(rating|stars?)", re.I)


def _rating_value(metadata: dict[str, Any]) -> str | None:
    for k, v in (metadata or {}).items():
        if _RATING_RE.search(str(k)) and v not in (None, ""):
            return str(v)
    return None


def _load_raw_units(conn, source_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT unit_id, original_text, row_number, page_number, metadata "
        "FROM raw_units WHERE source_id=? ORDER BY unit_id", (source_id,),
    ).fetchall()
    return [
        {"unit_id": r["unit_id"], "original_text": r["original_text"] or "",
         "row_number": r["row_number"], "page_number": r["page_number"],
         "metadata": db.loads(r["metadata"]) or {}}
        for r in rows
    ]


def clean_source(conn, source_id: int) -> dict[str, Any]:
    """Clean one source. Writes cleaned_units, cleaning_actions, ai_suggestions.

    Returns the per-source counts + profile for aggregation.
    """
    src = conn.execute("SELECT * FROM sources WHERE source_id=?", (source_id,)).fetchone()
    if src is None:
        raise ValueError(f"source {source_id} not found")

    source_type = src["source_type"] or "Document"
    column_mapping = _load_column_mapping(conn, source_id)
    raw_units = _load_raw_units(conn, source_id)

    profile = profiler.profile_units(raw_units, source_type)

    # --- clean + validate each unit (rule engine) --------------------------
    processed: list[dict[str, Any]] = []
    for u in raw_units:
        cleaned_text, text_actions = rules.clean_text(u["original_text"])
        vres = validator.validate_unit(cleaned_text, u["metadata"], column_mapping, source_type)
        actions = text_actions + vres["actions"]
        processed.append({
            "unit_id": u["unit_id"],
            "original_text": u["original_text"],
            "cleaned_text": cleaned_text,
            "flags": list(vres["flags"]),
            "actions": actions,
            "hard_empty": vres["hard_empty"],
            "participant": _participant_of(u["metadata"]),
            "row_values": u["metadata"],
        })

    # --- duplicate detection (within source, first occurrence kept) --------
    # Tabular sources dedup on the whole row ("duplicate row"); free-text
    # sources dedup on normalized text / same-participant-same-response.
    is_tabular = bool(profile.get("is_tabular")) and profile.get("n_columns", 0) >= 2
    dup_map = dedup.find_duplicates(
        [{"unit_id": p["unit_id"], "cleaned_text": p["cleaned_text"],
          "participant": p["participant"], "row_values": p["row_values"]}
         for p in processed],
        tabular=is_tabular,
    )

    # --- assign final status + persist -------------------------------------
    counts = {k: 0 for k in ("raw_units", "empty_units", "duplicate_units",
                             "invalid_units", "short_units", "missing_meta_units")}
    counts["raw_units"] = len(processed)

    # clear any previous clean run for idempotency (keep import-time suggestions
    # like source_type / column_mapping; only clear ones this stage regenerates)
    conn.execute(
        "DELETE FROM cleaned_units WHERE unit_id IN "
        "(SELECT unit_id FROM raw_units WHERE source_id=?)", (source_id,))
    conn.execute(
        "DELETE FROM cleaning_actions WHERE unit_id IN "
        "(SELECT unit_id FROM raw_units WHERE source_id=?)", (source_id,))
    conn.execute(
        "DELETE FROM ai_suggestions WHERE source_id=? AND suggestion_type IN "
        "('explanation','cleaning_rule','note')", (source_id,))

    for p in processed:
        uid = p["unit_id"]
        flags = p["flags"]
        if p["hard_empty"]:
            status = "empty"
            counts["empty_units"] += 1
        elif uid in dup_map:
            status = "duplicate"
            flags = flags + [f"duplicate_of:{dup_map[uid]['duplicate_of']}"]
            counts["duplicate_units"] += 1
        else:
            status = "kept"
            if {"invalid_rating", "invalid_date", "broken_extraction",
                "invalid_numeric"} & set(flags):
                counts["invalid_units"] += 1
            if "short" in flags:
                counts["short_units"] += 1
            if "missing_participant_meta" in flags:
                counts["missing_meta_units"] += 1

        conn.execute(
            "INSERT INTO cleaned_units (unit_id, cleaned_text, status, quality_flags) "
            "VALUES (?,?,?,?)",
            (uid, p["cleaned_text"], status, db.dumps(flags)),
        )

        # Per-unit explanation (suggestion only). Source-level facts are handled
        # once below, not repeated on every row; the offending value is included
        # so two flagged rows don't read identically.
        suggestion_id = None
        human_flags = [f for f in flags if not f.startswith("duplicate_of")]
        explanation = ai_assistant.explain_unit(
            human_flags, status=status, rating_value=_rating_value(p["row_values"]))
        if explanation:
            suggestion_id = audit.log_suggestion(
                conn, source_id, uid, "explanation", explanation, 0.7)
        audit.log_actions(conn, uid, p["actions"], suggestion_id)

    # source-level suggestions (shown once): cleaning-rule recs + source-level flags
    src_profile = dict(profile, **counts)
    for rec in (ai_assistant.suggest_cleaning_rule(src_profile)
                + ai_assistant.explain_source_flags(counts)):
        audit.log_suggestion(conn, source_id, None,
                             rec["suggestion_type"], rec["suggestion_text"],
                             rec["confidence"])

    final_clean = counts["raw_units"] - counts["empty_units"] - counts["duplicate_units"]
    conn.execute("UPDATE sources SET import_status='cleaned' WHERE source_id=?", (source_id,))

    return {"source_id": source_id, "file_name": src["file_name"],
            "source_type": source_type, "profile": profile,
            "counts": counts, "final_clean_units": max(0, final_clean)}


def _load_column_mapping(conn, source_id: int) -> dict[str, str]:
    """Rebuild incoming->standard mapping from the AI suggestions saved at import."""
    rows = conn.execute(
        "SELECT suggestion_text FROM ai_suggestions "
        "WHERE source_id=? AND suggestion_type='column_mapping'", (source_id,),
    ).fetchall()
    mapping: dict[str, str] = {}
    for r in rows:
        if "->" in (r["suggestion_text"] or ""):
            inc, std = r["suggestion_text"].split("->", 1)
            mapping[inc.strip()] = std.strip()
    return mapping


def clean_project(conn, project_id: int) -> dict[str, Any]:
    """Clean every source in a project and write the aggregate quality report."""
    project = db.get_project(conn, project_id)
    if project is None:
        raise ValueError(f"project {project_id} not found")

    sources = conn.execute(
        "SELECT * FROM sources WHERE project_id=?", (project_id,)).fetchall()

    total = {k: 0 for k in ("raw_units", "empty_units", "duplicate_units",
                            "invalid_units", "short_units", "missing_meta_units")}
    per_source: list[dict[str, Any]] = []
    files_attempted = len(sources)
    files_succeeded = 0

    start = time.perf_counter()
    for s in sources:
        if not s["n_units"]:  # roadmap/media source — nothing to clean
            per_source.append({"source_id": s["source_id"], "file_name": s["file_name"],
                               "source_type": s["source_type"], "skipped": True,
                               "counts": {k: 0 for k in total}})
            continue
        res = clean_source(conn, s["source_id"])
        files_succeeded += 1
        for k in total:
            total[k] += res["counts"][k]
        per_source.append(res)
    seconds = time.perf_counter() - start

    report = quality.build_report(
        project_name=project["name"],
        sources_imported=sum(1 for s in sources if s["n_units"]),
        counts=total, seconds=seconds,
        files_attempted=files_attempted, files_succeeded=files_succeeded,
    )
    report["ai_summary"] = ai_assistant.summarise_report(report)

    conn.execute(
        "INSERT INTO quality_reports (project_id, source_id, score, issues_summary, "
        "final_status, created_at) VALUES (?,?,?,?,?,?)",
        (project_id, None, report["quality_score"], db.dumps(report),
         report["status"], db.now()),
    )

    return {"report": report, "per_source": per_source}


# --- Export / Analysis Handoff (module 8) ---------------------------------
def export_clean_units(conn, project_id: int) -> list[dict[str, Any]]:
    """Return approved clean units (status='kept') ready for framework building.

    This is the hand-off surface to Steps 4-7 (methods, triangulation, analysis).
    """
    rows = conn.execute(
        """SELECT s.source_id, s.file_name, s.source_type,
                  ru.unit_id, cu.cleaned_text, ru.metadata, ru.row_number, ru.page_number
           FROM cleaned_units cu
           JOIN raw_units ru ON ru.unit_id = cu.unit_id
           JOIN sources s ON s.source_id = ru.source_id
           WHERE s.project_id=? AND cu.status='kept'
           ORDER BY s.source_id, ru.unit_id""", (project_id,),
    ).fetchall()
    return [
        {"source_id": r["source_id"], "source_file": r["file_name"],
         "source_type": r["source_type"], "unit_id": r["unit_id"],
         "content_clean": r["cleaned_text"], "row_number": r["row_number"],
         "page_number": r["page_number"], "metadata": db.loads(r["metadata"])}
        for r in rows
    ]
