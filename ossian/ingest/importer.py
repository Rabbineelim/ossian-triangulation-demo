"""Import orchestrator (Step 2).

Pipeline per file:  detect -> extract -> map source -> store original + units
-> record AI suggestions -> return a preview for human confirmation.

Answers guide question 5 ("preserve the original for the evidence trail") by
copying every uploaded file into storage/uploads and saving its path on the
`sources` row, alongside every extracted raw unit.
"""
from __future__ import annotations

import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

from .. import config, db
from ..models import ExtractionResult
from . import extractors, source_mapping
from .detect import detect_file_type


def _store_original(path: Path) -> Path:
    dest = config.UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{path.name}"
    shutil.copy2(path, dest)
    return dest


def _persist(conn, project_id: int, path: Path, stored: Path,
             res: ExtractionResult) -> dict[str, Any]:
    status = "imported" if res.extractable else "roadmap-stored"
    cur = conn.execute(
        """INSERT INTO sources
           (project_id, file_name, file_type, source_type, file_path,
            n_units, import_status, notes, uploaded_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (project_id, res.file_name, res.file_type, res.source_type,
         str(stored), res.n_units, status, "; ".join(res.warnings), db.now()),
    )
    source_id = int(cur.lastrowid)

    # raw units (batch insert; preserves the original extracted evidence)
    rows = [
        (source_id, u.original_text, u.row_number, u.page_number, db.dumps(u.metadata))
        for u in res.units
    ]
    if rows:
        conn.executemany(
            """INSERT INTO raw_units
               (source_id, original_text, row_number, page_number, metadata)
               VALUES (?,?,?,?,?)""",
            rows,
        )

    # AI-layer suggestions produced at import time (source_type + column mapping)
    conn.execute(
        """INSERT INTO ai_suggestions
           (source_id, suggestion_type, suggestion_text, confidence, created_at)
           VALUES (?,?,?,?,?)""",
        (source_id, "source_type",
         f"Looks like a {res.source_type} source.",
         res.source_type_confidence, db.now()),
    )
    for s in source_mapping.suggest_column_mapping(res.columns):
        conn.execute(
            """INSERT INTO ai_suggestions
               (source_id, suggestion_type, suggestion_text, confidence, created_at)
               VALUES (?,?,?,?,?)""",
            (source_id, "column_mapping",
             f"{s['incoming']} -> {s['standard']}", s["confidence"], db.now()),
        )

    return {
        "source_id": source_id,
        "file_name": res.file_name,
        "file_type": res.file_type,
        "detected_by": res.detected_by,
        "source_type": res.source_type,
        "source_type_confidence": round(res.source_type_confidence, 2),
        "n_units": res.n_units,
        "columns": res.columns,
        "column_mapping_suggestions": source_mapping.suggest_column_mapping(res.columns),
        "truncated": res.truncated,
        "warnings": res.warnings,
        "extractable": res.extractable,
        "preview_units": [
            {"original_text": u.original_text[:400], "metadata": u.metadata}
            for u in res.units[:5]
        ],
    }


def import_file(conn, project_id: int, path: str | Path,
                source_type_override: str | None = None) -> list[dict[str, Any]]:
    """Import one file. Returns a list of previews (>1 when the file is a ZIP)."""
    path = Path(path)
    kind, detected_by = detect_file_type(path)

    # ZIP that is not docx/xlsx -> expand and import members (e.g. Music Taste).
    if kind == "zip":
        previews: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(path) as zf:
                zf.extractall(tmp)
            for member in sorted(Path(tmp).rglob("*")):
                if member.is_file():
                    previews.extend(import_file(conn, project_id, member,
                                                source_type_override))
        return previews or [{"file_name": path.name, "n_units": 0,
                             "warnings": ["Empty or unreadable ZIP."],
                             "extractable": False}]

    res = extractors.extract(path, kind)
    res.detected_by = detected_by

    if source_type_override:
        res.source_type, res.source_type_confidence = source_type_override, 1.0
    else:
        stype, conf, _reason = source_mapping.infer_source_type(res, path.stem)
        res.source_type, res.source_type_confidence = stype, conf

    stored = _store_original(path)
    return [_persist(conn, project_id, path, stored, res)]


def import_paths(project_id: int, paths: list[str | Path],
                 db_path: str | None = None) -> list[dict[str, Any]]:
    """Import many files into a project in one transaction."""
    out: list[dict[str, Any]] = []
    with db.session(db_path) as conn:
        for p in paths:
            out.extend(import_file(conn, project_id, p))
    return out
