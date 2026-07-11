"""Legacy Microsoft Word `.doc` (Word 97-2003) support.

`.doc` is a binary OLE2 format that python-docx cannot read. We handle it with a
layered, best-effort strategy so it degrades gracefully:

    read:   1) Microsoft Word via COM (best quality, if Word is installed)
            2) RTF text (some .doc files are really RTF)   -> striprtf
            3) crude OLE2 text scrape                        -> olefile
    write:  1) Microsoft Word via COM  (true .doc, wdFormatDocument)
            2) fall back to .docx        (caller is told the format changed)

Every function is fully guarded: a missing library or absent Word never raises
past this module — callers get (result, method) or (None, reason).
"""
from __future__ import annotations

import re
from pathlib import Path

OLE2_MAGIC = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"
RTF_MAGIC = b"{\\rtf"


def is_ole2(head: bytes) -> bool:
    return head.startswith(OLE2_MAGIC)


def is_rtf(head: bytes) -> bool:
    return head.lstrip()[:5] == RTF_MAGIC


def _word_available() -> bool:
    try:
        import win32com.client  # noqa: F401
        return True
    except Exception:
        return False


# --- READ ------------------------------------------------------------------
def _read_via_word(path: Path) -> str | None:
    try:
        import pythoncom
        import win32com.client
    except Exception:
        return None
    word = None
    pythoncom.CoInitialize()
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = False
        doc = word.Documents.Open(str(path.resolve()), ReadOnly=True,
                                  ConfirmConversions=False, AddToRecentFiles=False)
        text = doc.Content.Text
        doc.Close(False)
        return text
    except Exception:
        return None
    finally:
        try:
            if word is not None:
                word.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()


def _read_via_rtf(raw: bytes) -> str | None:
    try:
        from striprtf.striprtf import rtf_to_text
        return rtf_to_text(raw.decode("latin-1", "replace"))
    except Exception:
        return None


def _read_via_olefile(path: Path) -> str | None:
    """Crude last-resort text scrape from the WordDocument stream."""
    try:
        import olefile
        if not olefile.isOleFile(str(path)):
            return None
        ole = olefile.OleFileIO(str(path))
        if not ole.exists("WordDocument"):
            ole.close()
            return None
        data = ole.openstream("WordDocument").read()
        ole.close()
        # Legacy .doc text is largely cp1252; keep printable runs.
        text = data.decode("cp1252", "ignore")
        text = re.sub(r"[^\x09\x0A\x0D\x20-\x7E -ɏ]+", " ", text)
        text = re.sub(r"\s{2,}", " ", text)
        return text if len(text.strip()) > 20 else None
    except Exception:
        return None


def read_doc_text(path: str | Path) -> tuple[str | None, str]:
    """Return (text, method). text is None if every strategy failed."""
    path = Path(path)
    head = path.read_bytes()[:16]

    if is_rtf(head):
        text = _read_via_rtf(path.read_bytes())
        if text:
            return text, "rtf"

    if is_ole2(head):
        text = _read_via_word(path)
        if text:
            return text, "word-com"
        text = _read_via_olefile(path)
        if text:
            return text, "olefile-scrape"

    # not OLE2/RTF, or all failed — try RTF as a final guess
    text = _read_via_rtf(path.read_bytes())
    if text and len(text.strip()) > 20:
        return text, "rtf-fallback"
    return None, "unreadable"


# --- WRITE -----------------------------------------------------------------
def write_doc(paragraphs: list[str], out_path: str | Path) -> bool:
    """Write true .doc (wdFormatDocument) via Word. Returns True on success."""
    try:
        import pythoncom
        import win32com.client
    except Exception:
        return False
    word = None
    pythoncom.CoInitialize()
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = False
        doc = word.Documents.Add()
        rng = doc.Content
        rng.InsertAfter("\r".join(p for p in paragraphs if p is not None))
        doc.SaveAs(str(Path(out_path).resolve()), FileFormat=0)  # 0 = wdFormatDocument (.doc)
        doc.Close(False)
        return True
    except Exception:
        return False
    finally:
        try:
            if word is not None:
                word.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()


def can_write_doc() -> bool:
    return _word_available()
