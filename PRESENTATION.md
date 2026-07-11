# Ossian — Steps 2 & 3: What to present

**One line:** *Step 2 brings the evidence into the system; Step 3 makes it
trustworthy enough to analyze — and every change is logged, so the final dataset
is defensible.*

We built the "engine room" of Ossian: a working import channel and a hybrid
cleaning tool, tested on the real interview, survey, review, and video-study
samples.

---

## Live demo (5 clicks)
1. `python -m ossian.web` → open http://127.0.0.1:8000
2. **Create a project** → *"Mid-market churn analysis"*.
3. **Load sample datasets** — 17 mixed files import in one click; Ossian
   auto-detects each file type and research source and splits them into units.
4. **Run cleaning** → the quality report appears (score /100).
5. Open any source's **Review** screen → before/after, flags, AI explanations,
   and the **Approve** button. Then **Export clean CSV**.

---

## Real results on the sample data (3,000-unit sample cap)
| | |
|---|---|
| Sources imported | **17** (interviews, surveys, reviews, transcript, PDF, +audio stored) |
| Raw units | **16,555** |
| Duplicate rows removed | **5,611** |
| Empty units removed | **905** |
| Invalid units flagged (kept for review) | **74** |
| Very-short units flagged | **780** |
| **Final clean units** | **10,039** |
| **Quality score** | **85 / 100 — Ready** |

Three moments worth showing:
- **`Music Taste Survey Dataset_` has no file extension but is actually a ZIP.**
  Ossian detects it by *magic bytes*, opens it, and imports the CSVs inside.
  Trusting the extension would have corrupted the import.
- **The reddit/joke datasets contain the same records duplicated** (identical
  post-ids). Ossian removes them as *duplicate rows* — and the audit log points
  each removed copy back to its original, so the removal is defensible.
- **A 145-column survey (`responses.csv`) is NOT over-cleaned.** An early version
  wrongly flagged 1,005 respondents as duplicates because they shared one answer;
  the whole-row rule fixed it. Good research evidence is preserved.

---

## Acceptance criteria — Step 2 (all met)
- [x] Import multiple files in one project
- [x] Detect & process PDF, DOCX, TXT, CSV, XLSX (+ TSV, VTT)
- [x] Break imported content into units and count them
- [x] Store the original file **and** the extracted structure (evidence trail)
- [x] Preview & confirm the import before it flows on
- [x] Imported data passes directly into the cleaning pipeline

## Acceptance criteria — Step 3 (all met)
- [x] Preserves both original **and** cleaned versions of the content
- [x] Detects empty, invalid, and duplicate units
- [x] Standardizes text and structured fields consistently (dates → ISO, encoding, spacing)
- [x] Produces a quality summary report (+ performance metrics)
- [x] Clean output moves directly into framework building / analysis (Export CSV)

---

## The governance story (the important slide)
The cleaning tool is a **hybrid**, exactly as the design doc specifies:

| Rule-based engine | AI / agent layer | Human |
|---|---|---|
| **does the actual cleaning** — deterministic, repeatable | **only suggests & explains** — source type, column mapping, why a unit is flagged | **approves, edits, or rejects** before anything is final |

The AI layer is boxed in: it can suggest and explain, but the code has **no path
that lets it write the cleaned dataset** — a test (`test_pipeline.py`) enforces
that it only ever writes `ai_suggestions`. This is what makes Ossian's findings
defensible: nothing changes the evidence without a logged human decision.

---

## Why this is the right foundation
The later roadmap steps (methods, triangulation, qual+quant framework, launch)
all read from the clean, unit-structured, fully-audited dataset this produces. If
the import channel were weak, Ossian couldn't support mixed-method data; if the
cleaning were weak, the findings wouldn't be defensible. Steps 2 & 3 are the
engine room — and the engine runs.

**Next (Step 4+):** gather methodological data for research analysis & methods,
then build the triangulation + framework layer on top of `export_clean_units()`.
