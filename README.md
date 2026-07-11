# Ossian — Steps 2 & 3 (Data Import Channel + Hybrid Cleaning Tool)

> Step 2 brings the evidence into the system. Step 3 makes the evidence
> trustworthy enough to analyze.

This repository implements **Step 2 (Compatible Data Import Channel)** and
**Step 3 (Hybrid Data Cleaning Tool)** of the Ossian 10-step roadmap, exactly to
the specifications in `Ossian_Step2_Step3_Presentation_Guide.pdf` and
`Ossian Data Cleaning tool (step 3).docx`.

Step 1 (data collection) was already done — the sample datasets live in the
three ZIPs and are extracted into `data/`.

---

## Quick start

```bash
# 1. install dependencies (Python 3.10+)
pip install -r requirements.txt

# 2a. run the web app  (import → clean → review → approve → report → export)
python -m ossian.web
#     then open  http://127.0.0.1:8000
#     → create a project → "Load sample datasets" → "Run cleaning" → review → export

# 2b. or run the whole thing headless over the real sample datasets
python run_demo.py
#     writes reports/quality_report.json and reports/clean_dataset.csv

# 3. run the reliability tests
python tests/test_pipeline.py
```

`OSSIAN_MAX_UNITS` caps units per source for fast demos (default 4000); the
engine handles full files — the big Amazon reviews TSV is ~250 MB.

---

## What it does

### Step 2 — Compatible Data Import Channel
Answers the five questions the guide requires on every upload:

| Question | Where |
|---|---|
| What type of file is this? | `ingest/detect.py` — **magic bytes first**, extension second (one sample file, `Music Taste Survey Dataset_`, has *no extension* but is really a ZIP; extension-trust would corrupt it) |
| What research source is it? | `ingest/source_mapping.py` — Interview / Survey / Review / Experiment / Document |
| How is content extracted? | `ingest/extractors.py` — PDF, DOCX, **DOC** (Word 97-2003 via Word/olefile/RTF), TXT, CSV, TSV, XLSX, VTT, ZIP |
| How is it standardized? | one review / survey row / interview paragraph / transcript cue = **one unit** |
| How is the original preserved? | `ingest/importer.py` — copies the file to `storage/uploads/` and keeps every raw unit |

MVP formats: **PDF, DOCX, TXT, CSV, XLSX** (+ TSV, VTT). Audio / video / images
are accepted and stored as *roadmap* items but not yet extracted — per the guide.

### Format-preserving download
Whatever format a source was uploaded in, its cleaned version downloads
**individually in the same format** (`ossian/exporters.py`, route
`/sources/{id}/download`): CSV→CSV, TSV→TSV, XLSX→XLSX, TXT→TXT, VTT→VTT (cues
kept), DOCX→DOCX, PDF→PDF. Removed rows are dropped, the content column is
cleaned, and dates are standardized — the original upload stays untouched in
`storage/`.

### Step 3 — Hybrid Data Cleaning Tool
Governance model from the design doc — **rules clean, AI suggests, humans approve**:

| Module (doc) | File | Output |
|---|---|---|
| 1. Data Receiver | `pipeline._load_raw_units` | raw units |
| 2. Data Profiler | `clean/profiler.py` | profile report |
| 3. Validation Checker | `clean/validator.py` | validation flags |
| 4. Rule-based Cleaner | `clean/rules.py` + `clean/dedup.py` | cleaned units draft |
| 5. AI/Agent Assistant | `clean/ai_assistant.py` | suggestions (never finalizes) |
| 6. Human Review UI | `web/` | approval decision |
| 7. Audit Logger | `clean/audit.py` | audit log |
| 8. Export / Analysis Handoff | `pipeline.export_clean_units` | clean dataset |

Duplicate detection follows the doc's taxonomy precisely:
* **tabular** sources → *"duplicate row"* (whole-row match, ignoring the synthetic
  index) — so two distinct survey respondents are never merged just because they
  share one answer, and repeated posts keep their prevalence signal;
* **free-text** sources → exact / lowercase text duplicate, plus
  *"same participant + same response"*.

Only fully safe classes (empty + exact duplicates) are auto-removed. Suspicious
values (bad ratings, unparseable dates, very short responses) are **flagged for
human review, never silently dropped**.

---

## Output — the quality report
Produced per the guide's "Recommended quality report output" + "Performance
checking" tables: sources imported, raw units, duplicates removed, empty/invalid,
final clean units, **quality score /100**, status, and performance metrics
(import success rate, duplicate detection count, missing-value rate, final usable
unit rate, cleaning time per source). See `reports/quality_report.json`.

---

## Project layout
```
ossian/
  config.py            paths, MVP formats, quality weights/thresholds
  db.py                SQLite — the doc's exact 7-table schema (+ projects)
  models.py            shared dataclasses (units, results)
  ingest/              STEP 2: detect, extractors, source_mapping, importer
  clean/               STEP 3: profiler, validator, rules, dedup, quality,
                                ai_assistant, audit, pipeline
  web/                 FastAPI app + Jinja2 templates (dashboard, import,
                                preview, review, report)
run_demo.py            headless end-to-end over data/
tests/test_pipeline.py reliability tests (no pytest required)
storage/               SQLite DB + stored original files (evidence trail)
reports/               generated quality report + clean dataset
data/                  extracted sample datasets (from the 3 ZIPs)
```

## Tech stack
Python · FastAPI + Uvicorn · Jinja2 · SQLite (ports to PostgreSQL later) ·
pandas · openpyxl · python-docx · pdfplumber · python-dateutil — matches the
guide's recommended stack.
