"""Splits extracted text into overlapping chunks that remember where they came from (page range, markdown section).

Chunks are built page by page, so a PDF chunk always cites the page it was read from. Paragraph boundaries are
respected where possible; overlong paragraphs fall back to sentences, then to hard cuts at word boundaries.
"""

import re

from app.kb.types import Chunk, Extracted, KbError

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
MIN_CHUNK_CHARS = 20


def _pieces(paragraph: str, size: int) -> list[str]:
    """Break a paragraph larger than `size` into sentence-sized, then word-boundary-sized, pieces."""
    if len(paragraph) <= size:
        return [paragraph]
    out: list[str] = []
    for sentence in _SENTENCE.split(paragraph):
        while len(sentence) > size:
            cut = sentence.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            out.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            out.append(sentence)
    return out


def _tail(text: str, overlap: int) -> str:
    """The last ~`overlap` characters, starting at a word boundary, to carry into the next chunk."""
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 and len(text) <= overlap else ""
    cut = text.find(" ", len(text) - overlap)
    return text[cut + 1:] if cut != -1 else ""


def chunk_document(doc: Extracted, size: int, overlap: int, max_chunks: int) -> list[Chunk]:
    if size < 100 or not 0 <= overlap < size // 2:
        raise ValueError("chunk size must be at least 100 and overlap under half of it")
    chunks: list[Chunk] = []
    section: str | None = None

    if doc.kind == "csv":
        # The extractor already grouped rows into chunk-sized blocks that each repeat the column header; do not re-split them.
        if len(doc.pages) > max_chunks:
            raise KbError("too_many_chunks", f"The document produces more than {max_chunks} chunks; split it into smaller files.", 422)
        return [Chunk(i, p.text, None, None, p.section) for i, p in enumerate(doc.pages) if p.text.strip()]

    for page in doc.pages:
        buf = ""
        buf_section = section
        carried = ""

        def flush():
            nonlocal buf, carried, buf_section
            body = buf.strip()
            if len(body) >= MIN_CHUNK_CHARS:
                chunks.append(Chunk(len(chunks), body, page.number, page.number, buf_section))
                carried = _tail(body, overlap)
            buf = carried
            buf_section = section

        for paragraph in re.split(r"\n\s*\n", page.text):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            if doc.kind == "md":
                m = _HEADING.match(paragraph.splitlines()[0])
                if m:
                    if buf.strip() and buf.strip() != carried.strip():
                        flush()  # finish the previous section's text first
                    section = m.group(1).strip()[:120]
                    carried, buf, buf_section = "", "", section  # no overlap across a heading
            for piece in _pieces(paragraph, size - overlap):
                if buf and len(buf) + len(piece) + 2 > size:
                    flush()
                buf = f"{buf}\n\n{piece}" if buf else piece
                if len(chunks) > max_chunks:
                    raise KbError("too_many_chunks", f"The document produces more than {max_chunks} chunks; split it into smaller files.", 422)
        if buf.strip() and buf.strip() != carried.strip():
            flush()
        elif not chunks and buf.strip():
            chunks.append(Chunk(len(chunks), buf.strip(), page.number, page.number, buf_section))

    if not chunks:
        raise KbError("no_extractable_text", "No usable text was found in the document.", 422)
    if len(chunks) > max_chunks:
        raise KbError("too_many_chunks", f"The document produces more than {max_chunks} chunks; split it into smaller files.", 422)
    return chunks
