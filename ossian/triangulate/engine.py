"""Transparent baseline triangulation engine.

This module deliberately keeps extraction deterministic and auditable.  It can
later be replaced by embeddings or an LLM while preserving the same database
contract and review UI.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from typing import Any

from .. import db

DOMAIN_THEMES: dict[str, dict[str, list[str]]] = {
    "software_customer_experience": {
        "reliability": ["crash", "freeze", "bug", "broken", "error", "failed", "data loss", "lost data", "stopped working"],
        "usability": ["confusing", "difficult", "hard to", "interface", "navigation", "unintuitive", "easy to use", "simple", "cannot find", "can't find"],
        "performance": ["slow", "lag", "loading", "takes forever", "fast", "responsive", "sync"],
        "installation_and_setup": ["install", "reinstall", "installation", "activate", "activation", "setup", "license", "registration"],
        "price_and_value": ["price", "expensive", "cost", "worth", "value", "subscription", "refund", "waste"],
        "support_and_service": ["support", "customer service", "help desk", "representative", "reply", "responded"],
        "features_and_functionality": ["feature", "features", "functionality", "missing", "update", "upgrade"],
    },
    "ecommerce_customer_experience": {
        "checkout_usability": ["checkout", "form", "field", "address", "autocomplete", "autofill", "confusing"],
        "discount_code_discoverability": ["discount", "coupon", "promo", "code"],
        "payment_friction": ["payment", "card", "paypal", "apple pay", "google pay", "declined", "billing"],
        "shipping_transparency": ["shipping", "delivery", "fee", "fees", "cost"],
        "account_and_guest_checkout": ["account", "guest", "login", "sign in", "register"],
        "performance_and_errors": ["slow", "loading", "error", "failed", "stuck", "timeout"],
        "cart_and_progress_preservation": ["cart", "saved", "lost", "back button", "start over", "progress"],
    },
    "workplace_experience": {
        "meeting_fatigue": ["meeting", "meetings", "call", "calls", "zoom", "video call"],
        "communication_overload": ["slack", "email", "messages", "notification", "notifications", "unread"],
        "focus_and_distraction": ["focus", "distract", "interruption", "noise", "concentrate"],
        "workload_and_overwork": ["overwhelmed", "workload", "urgent", "deadline", "overtime", "too much"],
        "productivity_and_routine": ["productive", "productivity", "routine", "prioritize", "schedule", "planning"],
        "ergonomics_and_workspace": ["desk", "chair", "back pain", "neck", "workspace", "office"],
        "wellbeing_and_mood": ["stressed", "frustrated", "exhausted", "tired", "anxious", "happy", "calm", "burnout"],
    },
    "customer_service": {
        "service_speed": ["slow service", "long line", "wait", "waiting", "queue", "takes forever", "delay"],
        "staff_behavior": ["friendly", "rude", "helpful", "staff", "cashier", "employee"],
        "service_quality": ["service", "poor service", "great service", "customer care"],
        "cleanliness": ["clean", "dirty", "hygiene", "mess"],
        "price_and_value": ["price", "expensive", "cheap", "value", "worth"],
    },
    "general_customer_experience": {
        "reliability": ["crash", "freeze", "broken", "error", "failed", "unreliable"],
        "usability": ["confusing", "difficult", "easy", "interface", "navigation", "cannot find", "can't find"],
        "speed": ["slow", "fast", "wait", "waiting", "delay"],
        "price_and_value": ["price", "expensive", "cost", "worth", "value", "refund"],
        "support_and_service": ["support", "service", "staff", "helpful", "rude", "friendly"],
    },
}

NEGATIVE = ["bad", "awful", "terrible", "poor", "slow", "confusing", "difficult", "annoying", "frustrating", "crash", "broken", "error", "failed", "lost", "declined", "stuck", "unreliable", "expensive", "never replied", "rude", "dirty"]
POSITIVE = ["good", "great", "excellent", "love", "easy", "helpful", "fast", "reliable", "worth", "recommend", "perfect", "simple", "smooth", "friendly", "clean"]

DOMAIN_LABELS = {
    "software_customer_experience": "Software customer experience",
    "ecommerce_customer_experience": "E-commerce customer experience",
    "workplace_experience": "Workplace experience",
    "customer_service": "Customer service",
    "general_customer_experience": "General customer experience",
}

SOURCE_BIAS = {
    "review": "Self-selection can over-represent unusually positive or negative experiences.",
    "survey": "Question design and nonresponse can shape the result.",
    "interview": "Rich context, but usually a small purposive sample.",
    "diary": "Repeated entries are not independent participants; self-report effects apply.",
    "experiment": "Potentially stronger causal evidence, but scope and design determine validity.",
    "document": "Origin, purpose, and authorship determine evidential strength.",
}


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _rating(metadata: dict[str, Any]) -> float | None:
    for key in ("rating", "star_rating", "score", "stars", "satisfaction", "overall_rating"):
        val = metadata.get(key)
        if val in (None, ""):
            continue
        try:
            return float(str(val).split("/")[0].strip())
        except (TypeError, ValueError):
            continue
    return None


def _stance(text: str, rating: float | None) -> str:
    low = text.lower()
    neg = sum(term in low for term in NEGATIVE)
    pos = sum(term in low for term in POSITIVE)
    if rating is not None:
        if rating <= 2:
            neg += 2
        elif rating >= 4:
            pos += 2
    if neg > pos:
        return "negative"
    if pos > neg:
        return "positive"
    return "mixed_or_neutral"


def _themes(domain: str, text: str) -> list[tuple[str, int]]:
    low = text.lower()
    out: list[tuple[str, int]] = []
    for theme, keywords in DOMAIN_THEMES.get(domain, {}).items():
        hits = sum(keyword in low for keyword in keywords)
        if hits:
            out.append((theme, hits))
    return out or [("unclassified", 0)]


def _bias(source_type: str) -> str:
    st = (source_type or "").lower()
    for key, note in SOURCE_BIAS.items():
        if key in st:
            return note
    return "Source-specific sampling and measurement limitations require human review."


def ensure_default_assignments(conn: sqlite3.Connection, project_id: int) -> None:
    rows = conn.execute("SELECT source_id, source_type, file_name FROM sources WHERE project_id=?", (project_id,)).fetchall()
    for row in rows:
        exists = conn.execute("SELECT 1 FROM source_domain_assignments WHERE source_id=?", (row["source_id"],)).fetchone()
        if exists:
            continue
        hint = f'{row["source_type"] or ""} {row["file_name"] or ""}'.lower()
        if any(x in hint for x in ("app", "software")):
            domain = "software_customer_experience"
        elif any(x in hint for x in ("checkout", "ecommerce", "commerce")):
            domain = "ecommerce_customer_experience"
        elif any(x in hint for x in ("remote", "work", "diary")):
            domain = "workplace_experience"
        elif any(x in hint for x in ("review", "survey", "interview")):
            domain = "general_customer_experience"
        else:
            domain = "general_customer_experience"
        conn.execute(
            "INSERT INTO source_domain_assignments(source_id, domain, subdomain, assigned_by, assigned_at) VALUES (?,?,?,?,?)",
            (row["source_id"], domain, "", "system_suggestion", db.now()),
        )


def run_project(conn: sqlite3.Connection, project_id: int) -> dict[str, Any]:
    """Regenerate evidence, findings, and triangulation results for a project."""
    ensure_default_assignments(conn, project_id)
    conn.execute("DELETE FROM triangulation_reviews WHERE result_id IN (SELECT result_id FROM triangulation_results WHERE project_id=?)", (project_id,))
    conn.execute("DELETE FROM triangulation_results WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM source_findings WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM evidence_units WHERE project_id=?", (project_id,))

    rows = conn.execute(
        """SELECT s.source_id, s.file_name, s.source_type, a.domain, a.subdomain,
                  ru.unit_id, ru.original_text, ru.metadata, cu.cleaned_text
           FROM sources s
           JOIN source_domain_assignments a ON a.source_id=s.source_id
           JOIN raw_units ru ON ru.source_id=s.source_id
           JOIN cleaned_units cu ON cu.unit_id=ru.unit_id
           WHERE s.project_id=? AND cu.status='kept'
           ORDER BY s.source_id, ru.unit_id""",
        (project_id,),
    ).fetchall()

    source_totals: Counter[int] = Counter()
    grouped: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        text = _norm(row["cleaned_text"])
        if not text:
            continue
        metadata = db.loads(row["metadata"]) or {}
        rating = _rating(metadata)
        source_totals[row["source_id"]] += 1
        for theme, hits in _themes(row["domain"], text):
            stance = _stance(text, rating)
            cur = conn.execute(
                """INSERT INTO evidence_units
                   (project_id, source_id, unit_id, domain, subdomain, theme, stance,
                    evidence_text, context_json, rating, keyword_hits, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (project_id, row["source_id"], row["unit_id"], row["domain"], row["subdomain"],
                 theme, stance, text[:2000], db.dumps(metadata), rating, hits, db.now()),
            )
            grouped[(row["source_id"], row["domain"], theme)].append({
                "evidence_id": int(cur.lastrowid), "stance": stance,
            })

    findings: list[dict[str, Any]] = []
    for (source_id, domain, theme), items in grouped.items():
        if theme == "unclassified":
            continue
        counts = Counter(i["stance"] for i in items)
        mentions = len(items)
        neg_share = counts["negative"] / mentions if mentions else 0
        pos_share = counts["positive"] / mentions if mentions else 0
        finding_stance = "concern" if neg_share >= .60 else "strength" if pos_share >= .60 else "mixed"
        src = conn.execute("SELECT source_type FROM sources WHERE source_id=?", (source_id,)).fetchone()
        cur = conn.execute(
            """INSERT INTO source_findings
               (project_id, source_id, domain, theme, total_records, theme_mentions,
                prevalence, negative_count, positive_count, mixed_count, finding_stance,
                bias_note, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (project_id, source_id, domain, theme, source_totals[source_id], mentions,
             mentions / source_totals[source_id] if source_totals[source_id] else 0,
             counts["negative"], counts["positive"], counts["mixed_or_neutral"],
             finding_stance, _bias(src["source_type"] if src else ""), db.now()),
        )
        findings.append({"finding_id": int(cur.lastrowid), "source_id": source_id,
                         "domain": domain, "theme": theme, "stance": finding_stance})

    clusters: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in findings:
        clusters[(item["domain"], item["theme"])].append(item)

    result_count = 0
    for (domain, theme), items in clusters.items():
        source_ids = sorted({i["source_id"] for i in items})
        stances = [i["stance"] for i in items]
        if len(source_ids) < 2:
            relation, confidence = "insufficient_sources", "insufficient"
            claim = f"Not enough independent sources to triangulate {theme.replace('_', ' ')}."
            reason = "Only one source contributes a finding for this domain and theme."
        elif all(s == "concern" for s in stances):
            relation, confidence = "convergent_concern", "moderate"
            claim = f"Multiple sources indicate a concern related to {theme.replace('_', ' ')}."
            reason = "At least two source datasets independently contain predominantly negative evidence."
        elif all(s == "strength" for s in stances):
            relation, confidence = "convergent_strength", "moderate"
            claim = f"Multiple sources indicate a positive experience related to {theme.replace('_', ' ')}."
            reason = "At least two source datasets independently contain predominantly positive evidence."
        elif "concern" in stances and "strength" in stances:
            relation, confidence = "divergent", "low"
            claim = f"Sources disagree about {theme.replace('_', ' ')}."
            reason = "The source findings point in opposite directions; context and population differences require review."
        else:
            relation, confidence = "mixed_or_complementary", "low_to_moderate"
            claim = f"Sources provide mixed or complementary evidence about {theme.replace('_', ' ')}."
            reason = "The sources share the theme but differ in direction or emphasis."
        conn.execute(
            """INSERT INTO triangulation_results
               (project_id, domain, theme, relationship, confidence, proposed_claim,
                explanation, source_ids_json, comparability_status, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (project_id, domain, theme, relation, confidence, claim, reason,
             db.dumps(source_ids), "domain_theme_match" if len(source_ids) >= 2 else "insufficient_sources",
             "pending_review", db.now()),
        )
        result_count += 1

    return {"evidence_units": sum(len(v) for v in grouped.values()),
            "source_findings": len(findings), "triangulation_results": result_count}


def project_snapshot(conn: sqlite3.Connection, project_id: int) -> dict[str, Any]:
    ensure_default_assignments(conn, project_id)
    project = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
    sources = conn.execute(
        """SELECT s.*, a.domain, a.subdomain,
                  (SELECT COUNT(*) FROM cleaned_units cu JOIN raw_units ru ON ru.unit_id=cu.unit_id
                   WHERE ru.source_id=s.source_id AND cu.status='kept') kept
           FROM sources s JOIN source_domain_assignments a ON a.source_id=s.source_id
           WHERE s.project_id=? ORDER BY s.source_id""", (project_id,)).fetchall()
    findings = conn.execute(
        """SELECT sf.*, s.file_name, s.source_type FROM source_findings sf
           JOIN sources s ON s.source_id=sf.source_id WHERE sf.project_id=?
           ORDER BY sf.domain, sf.theme, sf.source_id""", (project_id,)).fetchall()
    results = conn.execute(
        "SELECT * FROM triangulation_results WHERE project_id=? ORDER BY domain, theme", (project_id,)).fetchall()
    domains = sorted({s["domain"] for s in sources})
    return {"project": project, "sources": sources, "findings": findings,
            "results": results, "domains": domains, "domain_labels": DOMAIN_LABELS}
