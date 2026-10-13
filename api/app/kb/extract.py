"""Validation and text extraction for uploaded files.

Files are untrusted. Nothing here executes content: PDFs are parsed with pypdf (pure Python, no JavaScript or embedded
file handling), text files are decoded as UTF-8, and every limit (size, pages, characters) is enforced up front.
The result is plain text per page; anything that cannot be read cleanly is rejected with a specific reason.
"""

import csv
import io
import os
import re
import unicodedata

from pypdf import PdfReader

from app.core.config import Settings
from app.kb.types import Extracted, KbError, PageText, Table

ALLOWED = {".pdf": "pdf", ".txt": "txt", ".md": "md", ".markdown": "md", ".csv": "csv"}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def safe_filename(name: str | None) -> str:
    """The name is only ever shown to people (the stored file gets a generated name), but still strip path parts and
    control characters so it cannot confuse a UI, a log line or a file system."""
    base = os.path.basename((name or "").replace("\\", "/"))
    base = _CONTROL.sub("", unicodedata.normalize("NFKC", base)).strip(" .")
    return base[:120] or "document"


def file_kind(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED:
        raise KbError("unsupported_type", f"Unsupported file type '{ext or filename}'. Allowed: PDF, TXT, Markdown and CSV (.pdf, .txt, .md, .csv).", 415)
    return ALLOWED[ext]


def clean_text(text: str) -> str:
    text = _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def unwrap_lines(text: str) -> str:
    """PDF text comes with a line break wherever the page layout wrapped. Those are not paragraph breaks, so join them
    (blank lines are kept) to give readable passages and cleaner embeddings."""
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"(?<!\n)\n(?!\n)", " ", text))


def extract(filename: str, data: bytes, s: Settings) -> Extracted:
    """Validate `data` and return its text. Raises KbError with a user-presentable message on any problem."""
    kind = file_kind(filename)
    limit = s.kb_max_upload_mb * 1024 * 1024
    if len(data) == 0:
        raise KbError("empty_file", "The file is empty.", 422)
    if len(data) > limit:
        raise KbError("file_too_large", f"The file is larger than the {s.kb_max_upload_mb} MB limit.", 413)
    if kind == "pdf":
        return _pdf(data, s)
    return _csv(data, s) if kind == "csv" else _text(kind, data, s)


def _text(kind: str, data: bytes, s: Settings) -> Extracted:
    if b"\x00" in data[:8192]:
        raise KbError("not_text", "This does not look like a text file (it contains binary data).", 422)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise KbError("unsupported_encoding", "The file is not valid UTF-8 text. Re-save it as UTF-8 and try again.", 422) from None
    text = clean_text(text)
    if not text:
        raise KbError("no_extractable_text", "The file contains no text.", 422)
    if len(text) > s.kb_max_text_chars:
        raise KbError("too_much_text", f"The file has more than {s.kb_max_text_chars:,} characters of text.", 422)
    return Extracted(kind, [PageText(None, text)], None)


def _pdf(data: bytes, s: Settings) -> Extracted:
    if not data.lstrip()[:5] == b"%PDF-":
        raise KbError("not_a_pdf", "The file is named .pdf but is not a PDF document.", 422)
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise KbError("encrypted_pdf", "The PDF is password-protected. Remove the protection and upload it again.", 422)
        n_pages = len(reader.pages)
    except KbError:
        raise
    except Exception:
        raise KbError("unreadable_pdf", "The PDF is damaged or could not be read.", 422) from None
    if n_pages == 0:
        raise KbError("empty_file", "The PDF has no pages.", 422)
    if n_pages > s.kb_max_pdf_pages:
        raise KbError("too_many_pages", f"The PDF has {n_pages} pages; the limit is {s.kb_max_pdf_pages}.", 422)

    pages: list[PageText] = []
    warnings: list[str] = []
    total = 0
    for i in range(n_pages):
        try:
            text = unwrap_lines(clean_text(reader.pages[i].extract_text() or ""))
        except Exception:
            warnings.append(f"Page {i + 1} could not be read and was skipped.")
            continue
        total += len(text)
        if total > s.kb_max_text_chars:
            raise KbError("too_much_text", f"The PDF has more than {s.kb_max_text_chars:,} characters of text.", 422)
        if text:
            pages.append(PageText(i + 1, text))
    if not pages:
        raise KbError(
            "no_extractable_text",
            "No text could be extracted. The PDF may be a scan of images; OCR is not supported.", 422,
        )
    empty = n_pages - len(pages) - sum("could not be read" in w for w in warnings)
    if empty:
        warnings.append(f"{empty} page(s) had no extractable text.")
    return Extracted("pdf", pages, n_pages, warnings)


_CELL_MAX = 300
_ROW_MAX = 700


def _is_number(cell: str) -> bool:
    try:
        float(cell.replace(",", ""))
        return True
    except ValueError:
        return False


def _csv(data: bytes, s: Settings) -> Extracted:
    """A CSV becomes blocks of rows, each block starting with the column names so a row is meaningful on its own
    ("pm25=45.2; station=Anand Vihar"). The first row is the header unless every cell in it is a number, in which case
    columns are named column_1, column_2 and so on. Empty cells are left out of a row, not written as blanks."""
    if b"\x00" in data[:8192]:
        raise KbError("not_text", "This does not look like a CSV file (it contains binary data).", 422)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise KbError("unsupported_encoding", "The file is not valid UTF-8 text. Re-save it as UTF-8 and try again.", 422) from None
    text = _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    if not text.strip():
        raise KbError("no_extractable_text", "The file contains no text.", 422)
    try:
        delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    try:
        rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter) if any(c.strip() for c in r)]
    except csv.Error:
        raise KbError("unreadable_csv", "The CSV could not be parsed. Check for unbalanced quotes.", 422) from None
    if len(rows) < 2:
        raise KbError("no_extractable_text", "The CSV needs a header row and at least one data row.", 422)
    width = max(len(r) for r in rows)
    if width > s.kb_csv_max_columns:
        raise KbError("too_many_columns", f"The CSV has {width} columns; the limit is {s.kb_csv_max_columns}.", 422)
    warnings: list[str] = []
    first = [c.strip() for c in rows[0]]
    if all(_is_number(c) for c in first if c):
        header = [f"column_{i + 1}" for i in range(width)]
        warnings.append("The first row is all numbers, so it was treated as data and columns were named column_1, column_2, ...")
    else:
        header = [(first[i] if i < len(first) and first[i] else f"column_{i + 1}")[:80] for i in range(width)]
        rows = rows[1:]
    if len(rows) > s.kb_csv_max_rows:
        raise KbError("too_many_rows", f"The CSV has {len(rows):,} data rows; the limit is {s.kb_csv_max_rows:,}. Split it into smaller files.", 422)

    head = ("Columns: " + ", ".join(header))[:_ROW_MAX]
    size = max(s.kb_chunk_chars, 200)
    blocks: list[PageText] = []
    lines: list[str] = []
    used = len(head)
    first_row = 1
    total = 0
    ragged = 0

    def flush(last_row: int) -> None:
        nonlocal lines, used, first_row
        if lines:
            label = f"rows {first_row}-{last_row}" if last_row > first_row else f"row {first_row}"
            blocks.append(PageText(None, head + "\n" + "\n".join(lines), label))
        lines, used, first_row = [], len(head), last_row + 1

    for n, row in enumerate(rows, start=1):
        if len(row) != width:
            ragged += 1
        cells = [f"{header[i]}={row[i].strip()[:_CELL_MAX]}" for i in range(min(len(row), width)) if row[i].strip()]
        if not cells:
            continue
        line = (f"row {n}: " + "; ".join(cells))[:_ROW_MAX]
        if lines and used + len(line) + 1 > size:
            flush(n - 1)
        lines.append(line)
        used += len(line) + 1
        total += len(line)
        if total > s.kb_max_text_chars:
            raise KbError("too_much_text", f"The CSV has more than {s.kb_max_text_chars:,} characters of text.", 422)
    flush(len(rows))
    if not blocks:
        raise KbError("no_extractable_text", "The CSV has no non-empty data rows.", 422)
    if ragged:
        warnings.append(f"{ragged:,} row(s) had a different number of cells than the header; missing cells were left out and extras ignored.")
    shown = "tab" if delimiter == "\t" else delimiter
    warnings.append(f"{len(rows):,} data row(s), {width} column(s), delimiter '{shown}'.")
    return Extracted("csv", blocks, None, warnings, Table(header, [[c.strip() for c in r] for r in rows], []))
