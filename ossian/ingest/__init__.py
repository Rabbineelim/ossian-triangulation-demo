"""Step 2 — Compatible Data Import Channel.

Answers the five questions the guide requires for every upload:
    1. What type of file is this?           -> detect.py
    2. What type of research source is it?   -> source_mapping.py
    3. How can the content be extracted?     -> extractors.py
    4. How is it standardized into units?    -> unitizer / extractors
    5. How is the original preserved?        -> importer.py (stores file + rows)
"""
from .importer import import_file, import_paths  # noqa: F401
