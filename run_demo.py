"""End-to-end demo: run Steps 2 and 3 over the real Ossian sample datasets.

    python run_demo.py

Creates a fresh project, imports every sample file (Step 2), cleans the whole
project (Step 3), prints the quality report, and writes:
    reports/quality_report.json    the full report + per-source breakdown
    reports/clean_dataset.csv       the analysis-ready clean units (hand-off)
"""
from __future__ import annotations

import csv
import glob
import json
from pathlib import Path

from ossian import config, db
from ossian.clean import pipeline
from ossian.ingest import import_paths

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

SAMPLE_GLOBS = [
    "Complete Interview Transcript/**/*.txt",
    "Surveys/**/*.csv",
    "Surveys/**/*.xlsx",
    "Surveys/Multiple Choice/Music Taste Survey Dataset_",
    "Surveys/Open Ended/*.tsv",
    "Video Data Usability Study/*.vtt",
    "Video Data Usability Study/*.pdf",
    "Video Data Usability Study/*.m4a",
]


def gather_files() -> list[str]:
    files: list[str] = []
    for pat in SAMPLE_GLOBS:
        files += glob.glob(str(DATA / pat), recursive=True)
    # de-dupe while preserving order
    seen, out = set(), []
    for f in files:
        if f not in seen and Path(f).is_file():
            seen.add(f)
            out.append(f)
    return out


def main() -> None:
    # fresh database for a clean demo
    for p in (config.DB_PATH, Path(str(config.DB_PATH) + "-wal"),
              Path(str(config.DB_PATH) + "-shm")):
        if p.exists():
            p.unlink()
    db.init_db()

    with db.session() as conn:
        pid = db.create_project(conn, "Ossian foundation demo — Steps 2 & 3",
                                "Import + hybrid cleaning over interview, survey, "
                                "review, and transcript samples.")

    files = gather_files()
    print(f"\n=== STEP 2 · IMPORT ({len(files)} files) ===")
    previews = import_paths(pid, files)
    for p in previews:
        flag = "" if p.get("extractable", True) else "  [roadmap-stored]"
        trunc = "  (sampled)" if p.get("truncated") else ""
        print(f"  {p.get('file_name','?')[:46]:46} {str(p.get('source_type')):10} "
              f"{p.get('n_units',0):>6} units{flag}{trunc}")

    print(f"\n=== STEP 3 · CLEAN ===")
    with db.session() as conn:
        result = pipeline.clean_project(conn, pid)
        clean_units = pipeline.export_clean_units(conn, pid)

    rep = result["report"]
    print(f"\n  {'QUALITY REPORT':-<60}")
    for label, key in [
        ("Project", "project"), ("Sources imported", "sources_imported"),
        ("Raw units", "raw_units"), ("Duplicate units removed", "duplicate_units_removed"),
        ("Empty units removed", "empty_units_removed"),
        ("Invalid units flagged", "invalid_units_flagged"),
        ("Short units flagged", "short_units_flagged"),
        ("Final clean units", "final_clean_units"),
        ("Quality score", "quality_score"), ("Status", "status"),
    ]:
        val = rep[key]
        val = f"{val:,}" if isinstance(val, int) else val
        print(f"  {label:.<32} {val}")

    print(f"\n  {'PERFORMANCE METRICS':-<60}")
    for k, v in rep["performance"].items():
        print(f"  {k:.<32} {v}")

    print(f"\n  AI summary: {rep['ai_summary']}")

    # write outputs
    (config.REPORTS_DIR / "quality_report.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8")

    out_csv = config.REPORTS_DIR / "clean_dataset.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["source_file", "source_type", "unit_id", "content_clean"])
        for u in clean_units:
            w.writerow([u["source_file"], u["source_type"], u["unit_id"],
                        (u["content_clean"] or "")[:2000]])

    print(f"\n  Wrote {config.REPORTS_DIR / 'quality_report.json'}")
    print(f"  Wrote {out_csv}  ({len(clean_units):,} clean units)\n")


if __name__ == "__main__":
    main()
