"""Reliability tests for the Ossian Step 2/Step 3 engine.

Run:  python tests/test_pipeline.py        (no pytest needed)
      python -m pytest tests/               (if pytest is installed)

Locks in the behaviours that matter for defensibility:
  * magic-byte file detection (extension can lie)
  * duplicate detection: no false positives on wide surveys; catches exact rows
  * invalid-rating + empty flagging
  * deterministic text cleaning (same input -> same output)
  * governance: the AI layer never writes cleaned_units
"""
from __future__ import annotations

import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ossian import db  # noqa: E402
from ossian.clean import dedup, rules, validator  # noqa: E402
from ossian.clean import pipeline  # noqa: E402
from ossian.ingest import import_file  # noqa: E402
from ossian.ingest.detect import detect_file_type  # noqa: E402


def _tmpdb():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db.init_db(path)
    return path


def test_detect_zip_without_extension():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "mystery_no_ext"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("columns.csv", "a,b\n1,2\n")
        kind, how = detect_file_type(p)
        assert kind == "zip", f"expected zip, got {kind}"
        assert "magic-bytes" in how
    print("ok  detect_zip_without_extension")


def test_detect_pdf_and_text():
    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / "x.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%rest")
        assert detect_file_type(pdf)[0] == "pdf"
        txt = Path(d) / "x.txt"
        txt.write_text("hello world\nthis is text", encoding="utf-8")
        assert detect_file_type(txt)[0] == "txt"
    print("ok  detect_pdf_and_text")


def test_clean_text_deterministic_and_normalizes():
    messy = "  “Smart”  quotes –  and   extra   spaces\n\n\n\nand exam-\nple break "
    out1, actions = rules.clean_text(messy)
    out2, _ = rules.clean_text(messy)
    assert out1 == out2, "cleaning must be deterministic"
    assert '"' in out1 and "“" not in out1, "smart quotes normalized"
    assert "example" in out1, "hyphenation across line break fixed"
    assert "   " not in out1, "extra spaces collapsed"
    assert actions, "changes should be recorded as auditable actions"
    print("ok  clean_text_deterministic_and_normalizes")


def test_epoch_date_standardization():
    iso, action, ok = rules.standardize_date("1455676933.0")
    assert ok and iso == "2016-02-17", iso
    assert action["rule_name"] == "standardize_date_epoch"
    _, _, ok2 = rules.standardize_date("not a date")
    assert ok2 is False
    print("ok  epoch_date_standardization")


def test_dedup_no_false_positive_on_wide_survey():
    # two DISTINCT respondents that share one categorical answer must NOT be dupes
    units = [
        {"unit_id": 1, "cleaned_text": "often early", "participant": None,
         "row_values": {"index": "0", "punctuality": "often early", "pop": "5", "rock": "1"}},
        {"unit_id": 2, "cleaned_text": "often early", "participant": None,
         "row_values": {"index": "1", "punctuality": "often early", "pop": "3", "rock": "4"}},
    ]
    res = dedup.find_duplicates(units, tabular=True)
    assert res == {}, f"wide-survey false positive: {res}"
    print("ok  dedup_no_false_positive_on_wide_survey")


def test_dedup_catches_exact_duplicate_row():
    units = [
        {"unit_id": 1, "cleaned_text": "great", "participant": None,
         "row_values": {"index": "0", "id": "abc", "text": "great", "rating": "5"}},
        {"unit_id": 2, "cleaned_text": "great", "participant": None,
         "row_values": {"index": "1", "id": "abc", "text": "great", "rating": "5"}},
    ]
    res = dedup.find_duplicates(units, tabular=True)
    assert 2 in res and res[2]["duplicate_of"] == 1, res
    print("ok  dedup_catches_exact_duplicate_row")


def test_validator_flags_invalid_rating_and_empty():
    v = validator.validate_unit("good product overall", {"rating": "9"}, {}, "Review")
    assert "invalid_rating" in v["flags"], v["flags"]
    v2 = validator.validate_unit("", {}, {}, "Review")
    assert v2["hard_empty"] and "empty" in v2["flags"]
    print("ok  validator_flags_invalid_rating_and_empty")


def test_end_to_end_import_clean_and_governance():
    path = _tmpdb()
    with tempfile.TemporaryDirectory() as d:
        csv = Path(d) / "reviews.csv"
        csv.write_text(
            "review_id,rating,review_text,date\n"
            "1,5,Great app really love it,2024-03-01\n"
            "2,9,Impossible rating value here,2024-03-02\n"
            "1,5,Great app really love it,2024-03-01\n",   # exact duplicate row
            encoding="utf-8")
        with db.session(path) as conn:
            pid = db.create_project(conn, "t")
            import_file(conn, pid, csv)
        with db.session(path) as conn:
            out = pipeline.clean_project(conn, pid)
            clean = pipeline.export_clean_units(conn, pid)
            # governance: the AI layer only ever writes ai_suggestions, never cleaned_units.
            n_sugg = conn.execute("SELECT COUNT(*) c FROM ai_suggestions").fetchone()["c"]
            n_clean = conn.execute("SELECT COUNT(*) c FROM cleaned_units").fetchone()["c"]
        rep = out["report"]
        assert rep["duplicate_units_removed"] == 1, rep
        assert rep["invalid_units_flagged"] >= 1, rep
        assert rep["final_clean_units"] == 2, rep
        assert len(clean) == 2
        assert n_sugg > 0 and n_clean == 3   # 3 raw units cleaned, suggestions exist
    os.unlink(path)
    print("ok  end_to_end_import_clean_and_governance")


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\nAll {len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
