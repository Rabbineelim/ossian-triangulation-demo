"""Ossian web app (Step 2 import + Step 3 human-review UI).

Run:  python -m ossian.web   (or)   uvicorn ossian.web.app:app --reload

Implements the guide's Step 2/Step 3 demonstrable flow:
  create project -> upload mixed files -> auto-detect file & source type ->
  extract into units -> preview -> clean (rule engine) -> human review with
  before/after + AI explanations -> approve -> quality report -> export.
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import config, db, exporters
from ..clean import ai_assistant, pipeline
from ..ingest import import_file
from ..triangulate import engine as triangulation_engine

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

app = FastAPI(title="Ossian", docs_url="/api-docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

DATA_DIR = config.ROOT / "data"
SAMPLE_GLOBS = [
    "Complete Interview Transcript/**/*.txt",
    "Surveys/Mixed/*.csv", "Surveys/Mixed/*.xlsx",
    "Surveys/Multiple Choice/*.csv", "Surveys/Multiple Choice/Music Taste Survey Dataset_",
    "Surveys/Open Ended/*.tsv",
    "Video Data Usability Study/*.vtt", "Video Data Usability Study/*.pdf",
]


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# --------------------------------------------------------------------------
# dashboard + projects
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with db.session() as conn:
        projects = conn.execute(
            """SELECT p.*,
                      (SELECT COUNT(*) FROM sources s WHERE s.project_id=p.project_id) n_sources,
                      (SELECT score FROM quality_reports q WHERE q.project_id=p.project_id
                       ORDER BY report_id DESC LIMIT 1) score
               FROM projects p ORDER BY p.project_id DESC"""
        ).fetchall()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"projects": projects, "has_samples": DATA_DIR.exists()},
    )


@app.post("/projects")
def create_project(name: str = Form(...), description: str = Form("")):
    with db.session() as conn:
        pid = db.create_project(conn, name.strip() or "Untitled project", description)
    return RedirectResponse(f"/projects/{pid}", status_code=303)


@app.get("/projects/{pid}", response_class=HTMLResponse)
def project_view(request: Request, pid: int):
    with db.session() as conn:
        project = db.get_project(conn, pid)
        sources = conn.execute(
            """SELECT s.*,
                      (SELECT COUNT(*) FROM cleaned_units cu JOIN raw_units ru
                       ON ru.unit_id=cu.unit_id WHERE ru.source_id=s.source_id
                       AND cu.status='kept') kept,
                      (SELECT COUNT(*) FROM cleaned_units cu JOIN raw_units ru
                       ON ru.unit_id=cu.unit_id WHERE ru.source_id=s.source_id
                       AND cu.status='duplicate') dup,
                      (SELECT COUNT(*) FROM cleaned_units cu JOIN raw_units ru
                       ON ru.unit_id=cu.unit_id WHERE ru.source_id=s.source_id
                       AND cu.status='empty') empty
               FROM sources s WHERE s.project_id=? ORDER BY s.source_id""", (pid,)
        ).fetchall()
        report_row = conn.execute(
            "SELECT issues_summary FROM quality_reports WHERE project_id=? "
            "ORDER BY report_id DESC LIMIT 1", (pid,)).fetchone()
    report = db.loads(report_row["issues_summary"]) if report_row else None
    any_cleaned = any(s["import_status"] == "cleaned" for s in sources)
    return templates.TemplateResponse(
        request=request,
        name="project.html",
        context={
            "project": project,
            "sources": sources,
            "report": report,
            "any_cleaned": any_cleaned,
            "has_samples": DATA_DIR.exists(),
        },
    )


# --------------------------------------------------------------------------
# Step 2 — import
# --------------------------------------------------------------------------
def _gather_samples() -> list[Path]:
    out: list[Path] = []
    for pat in SAMPLE_GLOBS:
        out += [Path(p) for p in DATA_DIR.glob(pat)]
    return [p for p in out if p.is_file()]


@app.post("/projects/{pid}/load-samples")
def load_samples(pid: int):
    with db.session() as conn:
        for p in _gather_samples():
            import_file(conn, pid, p)
    return RedirectResponse(f"/projects/{pid}", status_code=303)


@app.post("/projects/{pid}/upload")
async def upload(pid: int, files: list[UploadFile], source_type: str = Form("")):
    override = source_type or None
    with tempfile.TemporaryDirectory() as tmp:
        saved: list[Path] = []
        for f in files:
            dest = Path(tmp) / f.filename
            with open(dest, "wb") as out:
                shutil.copyfileobj(f.file, out)
            saved.append(dest)
        with db.session() as conn:
            for p in saved:
                import_file(conn, pid, p, source_type_override=override)
    return RedirectResponse(f"/projects/{pid}", status_code=303)


@app.get("/sources/{sid}/preview", response_class=HTMLResponse)
def source_preview(request: Request, sid: int):
    from ..ingest.source_mapping import STANDARD_FIELDS
    with db.session() as conn:
        src = conn.execute("SELECT * FROM sources WHERE source_id=?", (sid,)).fetchone()
        units = conn.execute(
            "SELECT unit_id, original_text, metadata, row_number, page_number "
            "FROM raw_units WHERE source_id=? ORDER BY unit_id LIMIT 25", (sid,)).fetchall()
        suggestions = conn.execute(
            "SELECT suggestion_type, suggestion_text, confidence FROM ai_suggestions "
            "WHERE source_id=? AND unit_id IS NULL ORDER BY suggestion_id", (sid,)).fetchall()
        # columns (for the interactive mapping tool) + current mapping
        first = conn.execute("SELECT metadata FROM raw_units WHERE source_id=? LIMIT 1",
                            (sid,)).fetchone()
        cols = [c for c in ((db.loads(first["metadata"]) or {}).keys() if first else [])
                if c != "index"]
        current_map = {}
        for r in conn.execute("SELECT suggestion_text FROM ai_suggestions WHERE source_id=? "
                              "AND suggestion_type='column_mapping'", (sid,)).fetchall():
            if "->" in (r["suggestion_text"] or ""):
                inc, std = (p.strip() for p in r["suggestion_text"].split("->", 1))
                current_map[inc] = std
    # file size (file identification module: "detect file type and size")
    size = None
    if src and src["file_path"] and Path(src["file_path"]).exists():
        size = Path(src["file_path"]).stat().st_size
    return templates.TemplateResponse(
        request=request,
        name="preview.html",
        context={
            "src": src,
            "units": units,
            "suggestions": suggestions,
            "loads": db.loads,
            "columns": cols,
            "current_map": current_map,
            "standard_fields": STANDARD_FIELDS,
            "file_size": size,
        },
    )


@app.post("/sources/{sid}/mapping")
async def save_mapping(sid: int, request: Request):
    """Human confirms/edits the column mapping (Step 2 UI), then re-clean the source."""
    form = await request.form()
    with db.session() as conn:
        src = conn.execute("SELECT project_id FROM sources WHERE source_id=?", (sid,)).fetchone()
        conn.execute("DELETE FROM ai_suggestions WHERE source_id=? AND "
                     "suggestion_type='column_mapping'", (sid,))
        for key, std in form.items():
            if key.startswith("map__") and std and std != "ignore":
                inc = key[5:]
                conn.execute(
                    "INSERT INTO ai_suggestions (source_id, suggestion_type, suggestion_text, "
                    "confidence, created_at) VALUES (?,?,?,?,?)",
                    (sid, "column_mapping", f"{inc} -> {std}", 1.0, db.now()))
        conn.execute(
            "INSERT INTO approval_log (project_id, source_id, user_id, decision, note, "
            "timestamp) VALUES (?,?,?,?,?,?)",
            (src["project_id"], sid, "reviewer", "edited", "column mapping updated", db.now()))
        # re-clean this source with the confirmed mapping
        if conn.execute("SELECT import_status FROM sources WHERE source_id=?",
                        (sid,)).fetchone()["import_status"] == "cleaned":
            pipeline.clean_source(conn, sid)
    return RedirectResponse(f"/sources/{sid}/preview", status_code=303)


# --------------------------------------------------------------------------
# Step 3 — clean, review, approve, report, export
# --------------------------------------------------------------------------
@app.post("/projects/{pid}/clean")
def clean(pid: int):
    with db.session() as conn:
        pipeline.clean_project(conn, pid)
    return RedirectResponse(f"/projects/{pid}/report", status_code=303)


@app.get("/projects/{pid}/report", response_class=HTMLResponse)
def report_view(request: Request, pid: int):
    with db.session() as conn:
        project = db.get_project(conn, pid)
        row = conn.execute(
            "SELECT issues_summary FROM quality_reports WHERE project_id=? "
            "ORDER BY report_id DESC LIMIT 1", (pid,)).fetchone()
        approvals = conn.execute(
            "SELECT * FROM approval_log WHERE project_id=? ORDER BY approval_id DESC",
            (pid,)).fetchall()
        n_sources = conn.execute(
            "SELECT COUNT(*) c FROM sources WHERE project_id=? AND n_units>0",
            (pid,)).fetchone()["c"]
        n_approved = conn.execute(
            "SELECT COUNT(DISTINCT source_id) c FROM approval_log WHERE project_id=? "
            "AND decision='approved' AND source_id IS NOT NULL", (pid,)).fetchone()["c"]
        approved_ids = {r["source_id"] for r in conn.execute(
            "SELECT DISTINCT source_id FROM approval_log WHERE project_id=? "
            "AND decision='approved'", (pid,)).fetchall()}
        review_sources = [dict(r, approved=(r["source_id"] in approved_ids)) for r in conn.execute(
            "SELECT source_id, file_name, source_type, file_type FROM sources "
            "WHERE project_id=? AND import_status='cleaned' AND n_units>0 ORDER BY source_id",
            (pid,)).fetchall()]
    report = db.loads(row["issues_summary"]) if row else None
    if report:  # user approval rate — computed live
        report["performance"]["user_approval_rate"] = round(n_approved / max(1, n_sources), 3)
    return templates.TemplateResponse(
        request=request,
        name="report.html",
        context={
            "project": project,
            "report": report,
            "approvals": approvals,
            "review_sources": review_sources,
        },
    )


@app.get("/sources/{sid}/review", response_class=HTMLResponse)
def review_view(request: Request, sid: int, show: str = "changed"):
    with db.session() as conn:
        src = conn.execute("SELECT * FROM sources WHERE source_id=?", (sid,)).fetchone()
        rows = conn.execute(
            """SELECT ru.unit_id, ru.original_text, cu.cleaned_text, cu.status,
                      cu.quality_flags
               FROM cleaned_units cu JOIN raw_units ru ON ru.unit_id=cu.unit_id
               WHERE ru.source_id=? ORDER BY ru.unit_id""", (sid,)).fetchall()
        # AI explanations keyed by unit
        expl = {r["unit_id"]: r["suggestion_text"] for r in conn.execute(
            "SELECT unit_id, suggestion_text FROM ai_suggestions "
            "WHERE source_id=? AND suggestion_type='explanation'", (sid,)).fetchall()}
        actions = {}
        for a in conn.execute(
            """SELECT ca.unit_id, ca.rule_name, ca.before_value, ca.after_value
               FROM cleaning_actions ca JOIN raw_units ru ON ru.unit_id=ca.unit_id
               WHERE ru.source_id=?""", (sid,)).fetchall():
            actions.setdefault(a["unit_id"], []).append(a)
        # source-level AI suggestions (source_type / column_mapping / cleaning_rule)
        src_suggestions = conn.execute(
            "SELECT suggestion_type, suggestion_text, confidence FROM ai_suggestions "
            "WHERE source_id=? AND unit_id IS NULL ORDER BY suggestion_id", (sid,)).fetchall()
        # per-source dataset summary (Human Approval Screen: "Dataset summary")
        summary = {k: conn.execute(
            "SELECT COUNT(*) c FROM cleaned_units cu JOIN raw_units ru "
            "ON ru.unit_id=cu.unit_id WHERE ru.source_id=? AND cu.status=?",
            (sid, k)).fetchone()["c"] for k in ("kept", "duplicate", "empty", "removed")}
        summary["raw"] = sum(summary.values())
        flag_counts = {"invalid": 0, "short": 0, "missing": 0}
        for r in conn.execute(
            "SELECT cu.quality_flags FROM cleaned_units cu JOIN raw_units ru "
            "ON ru.unit_id=cu.unit_id WHERE ru.source_id=? AND cu.status='kept'",
            (sid,)).fetchall():
            fl = db.loads(r["quality_flags"]) or []
            if {"invalid_rating", "invalid_date", "broken_extraction",
                "invalid_numeric"} & set(fl):
                flag_counts["invalid"] += 1
            if "short" in fl:
                flag_counts["short"] += 1
            if "missing_participant_meta" in fl:
                flag_counts["missing"] += 1
        summary["flagged"] = flag_counts["invalid"] + flag_counts["short"]
        # per-source quality score (Human Approval Screen: "Quality score")
        from ..clean import quality as _q
        src_score = _q.compute_score({
            "raw_units": summary["raw"], "duplicate_units": summary["duplicate"],
            "empty_units": summary["empty"], "invalid_units": flag_counts["invalid"],
            "short_units": flag_counts["short"], "missing_meta_units": flag_counts["missing"]})
        src_status = config.status_for_score(src_score)

    from ..clean.ai_assistant import SOURCE_LEVEL_FLAGS
    units = []
    for r in rows:
        flags = db.loads(r["quality_flags"]) or []
        # a unit is worth showing if its text changed, it was removed, OR it
        # carries a per-unit flag for review (source-level flags don't count)
        review_flags = [f for f in flags
                        if not f.startswith("duplicate_of") and f not in SOURCE_LEVEL_FLAGS]
        changed = ((r["original_text"] or "") != (r["cleaned_text"] or "")
                   or r["status"] != "kept" or bool(review_flags))
        if show == "changed" and not changed:
            continue
        units.append({
            "unit_id": r["unit_id"], "original": r["original_text"],
            "cleaned": r["cleaned_text"], "status": r["status"], "flags": flags,
            "explanation": expl.get(r["unit_id"], ""),
            "actions": actions.get(r["unit_id"], []),
        })
    return templates.TemplateResponse(
        request=request,
        name="review.html",
        context={
            "src": src,
            "units": units[:300],
            "show": show,
            "boundary": ai_assistant.AGENT_BOUNDARY,
            "summary": summary,
            "src_suggestions": src_suggestions,
            "src_score": src_score,
            "src_status": src_status,
        },
    )


@app.post("/projects/{pid}/approve")
def approve(pid: int, decision: str = Form("approved"), note: str = Form(""),
            user_id: str = Form("reviewer"), source_id: str = Form("")):
    sid = int(source_id) if source_id.strip().isdigit() else None
    with db.session() as conn:
        conn.execute(
            "INSERT INTO approval_log (project_id, source_id, user_id, decision, note, "
            "timestamp) VALUES (?,?,?,?,?,?)",
            (pid, sid, user_id, decision, note, db.now()))
    return RedirectResponse(f"/projects/{pid}/report", status_code=303)


# --- Edit manually (inline, dynamic) --------------------------------------
@app.post("/sources/{sid}/units/{uid}/edit")
async def edit_unit(sid: int, uid: int, request: Request):
    """Human edit of one cleaned unit (op: save | remove | restore). Returns JSON."""
    payload = await request.json()
    op = payload.get("op", "save")
    new_text = payload.get("cleaned_text")
    with db.session() as conn:
        row = conn.execute(
            "SELECT cu.cleaned_text, cu.status FROM cleaned_units cu WHERE cu.unit_id=?",
            (uid,)).fetchone()
        if row is None:
            return JSONResponse({"ok": False, "error": "unit not found"}, status_code=404)
        before, status = row["cleaned_text"], row["status"]

        if op == "remove":
            conn.execute("UPDATE cleaned_units SET status='removed' WHERE unit_id=?", (uid,))
            _log_action(conn, uid, "manual_remove", before, "(removed by reviewer)")
            new_status = "removed"
        elif op == "restore":
            conn.execute("UPDATE cleaned_units SET status='kept' WHERE unit_id=?", (uid,))
            _log_action(conn, uid, "manual_restore", f"(was {status})", "kept")
            new_status = "kept"
        else:  # save edited text
            conn.execute("UPDATE cleaned_units SET cleaned_text=? WHERE unit_id=?",
                         (new_text, uid))
            _log_action(conn, uid, "manual_edit", before, new_text)
            new_status = status
        # record that a human touched this source
        proj = conn.execute("SELECT project_id FROM sources WHERE source_id=?",
                            (sid,)).fetchone()
        conn.execute(
            "INSERT INTO approval_log (project_id, source_id, user_id, decision, note, "
            "timestamp) VALUES (?,?,?,?,?,?)",
            (proj["project_id"], sid, "reviewer", "edited", f"unit {uid}: {op}", db.now()))
    return JSONResponse({"ok": True, "status": new_status})


def _log_action(conn, uid, rule, before, after):
    conn.execute(
        "INSERT INTO cleaning_actions (unit_id, rule_name, before_value, after_value, "
        "created_at) VALUES (?,?,?,?,?)",
        (uid, rule, (before or "")[:400], (after or "")[:400], db.now()))



# --------------------------------------------------------------------------
# Step 4 — domain-filtered data triangulation
# --------------------------------------------------------------------------
@app.get("/projects/{pid}/triangulate", response_class=HTMLResponse)
def triangulation_view(request: Request, pid: int, domain: str = ""):
    with db.session() as conn:
        snapshot = triangulation_engine.project_snapshot(conn, pid)
        selected_domain = domain or (snapshot["domains"][0] if snapshot["domains"] else "")
        selected_results = [r for r in snapshot["results"] if r["domain"] == selected_domain]
        selected_findings = [f for f in snapshot["findings"] if f["domain"] == selected_domain]
        evidence_by_result = {}
        for result in selected_results:
            evidence_by_result[result["result_id"]] = conn.execute(
                """SELECT eu.*, s.file_name, s.source_type
                   FROM evidence_units eu JOIN sources s ON s.source_id=eu.source_id
                   WHERE eu.project_id=? AND eu.domain=? AND eu.theme=?
                   ORDER BY eu.source_id, eu.evidence_id LIMIT 80""",
                (pid, result["domain"], result["theme"]),
            ).fetchall()
        last_run = conn.execute(
            "SELECT created_at FROM triangulation_results WHERE project_id=? ORDER BY result_id DESC LIMIT 1",
            (pid,),
        ).fetchone()
    return templates.TemplateResponse(
        request=request,
        name="triangulate.html",
        context={
            **snapshot,
            "selected_domain": selected_domain,
            "selected_results": selected_results,
            "selected_findings": selected_findings,
            "evidence_by_result": evidence_by_result,
            "available_domains": triangulation_engine.DOMAIN_LABELS,
            "last_run": last_run["created_at"] if last_run else None,
            "loads": db.loads,
        },
    )


@app.post("/projects/{pid}/triangulate/configure")
async def triangulation_configure(pid: int, request: Request):
    form = await request.form()
    with db.session() as conn:
        for key, value in form.items():
            if key.startswith("domain__"):
                sid_text = key.split("__", 1)[1]
                if not sid_text.isdigit():
                    continue
                sid = int(sid_text)
                subdomain = str(form.get(f"subdomain__{sid}", "")).strip()
                conn.execute(
                    """INSERT INTO source_domain_assignments
                       (source_id, domain, subdomain, assigned_by, assigned_at)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(source_id) DO UPDATE SET
                         domain=excluded.domain, subdomain=excluded.subdomain,
                         assigned_by=excluded.assigned_by, assigned_at=excluded.assigned_at""",
                    (sid, str(value), subdomain, "human", db.now()),
                )
        conn.execute(
            "INSERT INTO approval_log(project_id, user_id, decision, note, timestamp) VALUES (?,?,?,?,?)",
            (pid, "reviewer", "edited", "triangulation domain assignments updated", db.now()),
        )
    return RedirectResponse(f"/projects/{pid}/triangulate", status_code=303)


@app.post("/projects/{pid}/triangulate/run")
def triangulation_run(pid: int):
    with db.session() as conn:
        triangulation_engine.run_project(conn, pid)
    return RedirectResponse(f"/projects/{pid}/triangulate", status_code=303)


@app.post("/projects/{pid}/triangulate/results/{rid}/review")
def triangulation_review(pid: int, rid: int, decision: str = Form("approved"),
                         edited_claim: str = Form(""), note: str = Form(""),
                         user_id: str = Form("reviewer")):
    with db.session() as conn:
        result = conn.execute(
            "SELECT result_id FROM triangulation_results WHERE result_id=? AND project_id=?",
            (rid, pid),
        ).fetchone()
        if not result:
            return JSONResponse({"error": "result not found"}, status_code=404)
        conn.execute(
            "INSERT INTO triangulation_reviews(result_id,user_id,decision,edited_claim,note,reviewed_at) VALUES (?,?,?,?,?,?)",
            (rid, user_id, decision, edited_claim.strip(), note.strip(), db.now()),
        )
        conn.execute("UPDATE triangulation_results SET status=? WHERE result_id=?", (decision, rid))
    return RedirectResponse(f"/projects/{pid}/triangulate", status_code=303)


@app.get("/projects/{pid}/triangulation.json")
def triangulation_export_json(pid: int):
    with db.session() as conn:
        snapshot = triangulation_engine.project_snapshot(conn, pid)
        payload = {
            "project": dict(snapshot["project"]) if snapshot["project"] else None,
            "sources": [dict(r) for r in snapshot["sources"]],
            "source_findings": [dict(r) for r in snapshot["findings"]],
            "triangulation_results": [dict(r) for r in snapshot["results"]],
        }
    data = json.dumps(payload, indent=2, default=str).encode("utf-8")
    return StreamingResponse(iter([data]), media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="ossian_triangulation_project{pid}.json"'})


@app.get("/projects/{pid}/triangulation.csv")
def triangulation_export_csv(pid: int):
    import csv
    with db.session() as conn:
        rows = conn.execute(
            "SELECT domain,theme,relationship,confidence,proposed_claim,explanation,comparability_status,status FROM triangulation_results WHERE project_id=? ORDER BY domain,theme",
            (pid,),
        ).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["domain","theme","relationship","confidence","proposed_claim","explanation","comparability_status","review_status"])
    for row in rows:
        writer.writerow(list(row))
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="ossian_triangulation_project{pid}.csv"'})

# --- delete project --------------------------------------------------------
@app.post("/projects/{pid}/delete")
def delete_project(pid: int):
    with db.session() as conn:
        paths = db.delete_project(conn, pid)
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass
    return RedirectResponse("/", status_code=303)


# --- downloads: cleaned (per-source & bundle), original, report -----------
@app.get("/sources/{sid}/download")
def download_cleaned_source(sid: int):
    """Download one source's cleaned data in its original format."""
    with db.session() as conn:
        data, filename, media_type = exporters.build_cleaned_file(conn, sid)
    return StreamingResponse(
        iter([data]), media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/sources/{sid}/original")
def download_original(sid: int):
    """Download the untouched original upload (evidence trail — old data kept)."""
    with db.session() as conn:
        src = conn.execute("SELECT file_name, file_path FROM sources WHERE source_id=?",
                          (sid,)).fetchone()
    if not src or not src["file_path"] or not Path(src["file_path"]).exists():
        return JSONResponse({"error": "original not found"}, status_code=404)
    return FileResponse(src["file_path"], filename=src["file_name"],
                        media_type="application/octet-stream")


@app.get("/projects/{pid}/export.zip")
def export_zip(pid: int):
    """Every cleaned source, each in its own original format, bundled as a ZIP."""
    with db.session() as conn:
        data = exporters.build_project_zip(conn, pid)
    return StreamingResponse(
        iter([data]), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="ossian_clean_project{pid}.zip"'})


@app.get("/projects/{pid}/report.json")
def export_report(pid: int):
    with db.session() as conn:
        row = conn.execute("SELECT issues_summary FROM quality_reports WHERE project_id=? "
                           "ORDER BY report_id DESC LIMIT 1", (pid,)).fetchone()
    report = db.loads(row["issues_summary"]) if row else {"error": "no report yet"}
    data = json.dumps(report, indent=2, default=str).encode("utf-8")
    return StreamingResponse(
        iter([data]), media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="ossian_report_project{pid}.json"'})


@app.get("/projects/{pid}/export.csv")
def export_csv(pid: int):
    import csv
    with db.session() as conn:
        units = pipeline.export_clean_units(conn, pid)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["source_file", "source_type", "unit_id", "content_clean"])
    for u in units:
        w.writerow([u["source_file"], u["source_type"], u["unit_id"],
                    (u["content_clean"] or "")[:2000]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="ossian_clean_project{pid}.csv"'})
