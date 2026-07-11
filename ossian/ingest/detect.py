"""File identification module (Step 2, question 1: "What type of file is this?").

Detection uses *magic bytes first*, extension second. This matters: one of the
real sample files (`Music Taste Survey Dataset_`) has no extension yet is
actually a ZIP archive. Trusting the extension alone would corrupt the import.
"""
from __future__ import annotations

from pathlib import Path

# Magic-byte signatures -> logical kind.
_SIGNATURES: list[tuple[bytes, str]] = [
    (b"%PDF-", "pdf"),
    (b"PK\x03\x04", "zip"),      # zip; also the container for docx/xlsx (disambiguated below)
    (b"PK\x05\x06", "zip"),      # empty zip
    (b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1", "ole2"),  # legacy .doc/.xls/.ppt (OLE2)
    (b"{\\rtf", "rtf"),          # Rich Text (sometimes saved as .doc)
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"ID3", "mp3"),
    (b"RIFF", "wav"),
    (b"\x1a\x45\xdf\xa3", "mkv"),
]

# Extensions we recognise directly.
_EXT_KINDS = {
    "pdf": "pdf", "docx": "docx", "doc": "doc", "txt": "txt", "text": "txt",
    "md": "txt", "log": "txt", "csv": "csv", "tsv": "tsv", "xlsx": "xlsx",
    "xls": "xlsx", "rtf": "doc", "vtt": "vtt", "srt": "vtt", "json": "json",
    "m4a": "m4a", "mp3": "mp3", "wav": "wav", "mp4": "mp4", "mov": "mov",
    "avi": "avi", "mkv": "mkv", "png": "png", "jpg": "jpg", "jpeg": "jpg",
    "zip": "zip",
}


def _sniff_signature(head: bytes) -> str | None:
    for sig, kind in _SIGNATURES:
        if head.startswith(sig):
            return kind
    return None


def _looks_textual(head: bytes) -> bool:
    """Heuristic: mostly-printable bytes with no NUL => treat as text/csv/tsv."""
    if not head:
        return False
    if b"\x00" in head:
        return False
    sample = head[:4096]
    printable = sum(1 for b in sample if b in (9, 10, 13) or 32 <= b <= 126 or b >= 128)
    return printable / len(sample) > 0.90


def detect_file_type(path: str | Path) -> tuple[str, str]:
    """Return (kind, detected_by).

    kind is a logical type: pdf/docx/xlsx/csv/tsv/txt/vtt/zip/json/audio/video/image.
    detected_by is "extension" or "magic-bytes:<sig>" for the evidence trail.
    """
    path = Path(path)
    ext = path.suffix.lower().lstrip(".")

    with open(path, "rb") as fh:
        head = fh.read(8192)

    sig_kind = _sniff_signature(head)

    # ZIP container may actually be a docx/xlsx — disambiguate by inner names + ext.
    if sig_kind == "zip":
        inner = head[:2048]
        if b"word/" in inner or ext in ("docx", "doc"):
            return "docx", f"magic-bytes:zip(ext={ext or 'none'})"
        if b"xl/" in inner or ext in ("xlsx", "xls"):
            return "xlsx", f"magic-bytes:zip(ext={ext or 'none'})"
        # Generic zip — needs the ZIP handler (may hold csv/txt, like Music Taste).
        return "zip", "magic-bytes:zip"

    if sig_kind == "ole2":
        # Legacy OLE2 container: .doc / .xls / .ppt. We support .doc; a real
        # legacy .xls goes to the tabular path.
        if ext in ("xls",):
            return "xlsx", "magic-bytes:ole2(xls)"
        return "doc", f"magic-bytes:ole2(ext={ext or 'none'})"
    if sig_kind == "rtf":
        return "doc", "magic-bytes:rtf"

    if sig_kind:
        # Trust extension for the flavour of a signature when useful.
        if sig_kind == "pdf":
            return "pdf", "magic-bytes:%PDF"
        if sig_kind in ("jpg", "png"):
            return "image", f"magic-bytes:{sig_kind}"
        if sig_kind in ("mp3", "wav", "mkv"):
            return "audio" if sig_kind in ("mp3", "wav") else "video", f"magic-bytes:{sig_kind}"

    # No decisive signature -> use extension.
    if ext in _EXT_KINDS:
        kind = _EXT_KINDS[ext]
        # Collapse to broad media categories for roadmap formats.
        if kind in ("m4a", "mp3", "wav"):
            return "audio", "extension"
        if kind in ("mp4", "mov", "avi", "mkv"):
            return "video", "extension"
        if kind in ("png", "jpg"):
            return "image", "extension"
        return kind, "extension"

    # Last resort: content sniff.
    if _looks_textual(head):
        if b"\t" in head and head.count(b"\t") > head.count(b","):
            return "tsv", "content-sniff"
        if b"," in head:
            return "csv", "content-sniff"
        return "txt", "content-sniff"

    return "unknown", "unknown"
