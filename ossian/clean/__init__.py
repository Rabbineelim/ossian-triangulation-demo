"""Step 3 — Hybrid Data Cleaning Tool.

Governance model (from the Step 3 design doc):
    Rule-based engine  = actual cleaning   (rules.py, validator.py, dedup.py)
    AI / agent layer   = suggestion only    (ai_assistant.py)
    Human approval     = final decision      (web UI + audit.py)

Eight internal modules the doc specifies:
    1. Data Receiver          -> reads raw_units from Step 2
    2. Data Profiler          -> profiler.py     (profile_report)
    3. Validation Checker     -> validator.py    (validation_flags)
    4. Rule-based Cleaner     -> rules.py        (cleaned_units draft)
    5. AI/Agent Assistant     -> ai_assistant.py (suggestions)
    6. Human Review UI        -> web/            (approval decision)
    7. Audit Logger           -> audit.py        (audit_log)
    8. Export/Analysis Handoff-> pipeline.export (clean_dataset)
"""
from .pipeline import clean_source, clean_project  # noqa: F401
