"""A report as an ordered list of blocks. The full export is assembled once into blocks and then rendered to HTML and to PDF,
so both formats always show the same text, numbers and figures.

Inline text may use a small subset of Markdown (**bold**, *italic*, `code`, [text](url)); renderers decide how to show it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Heading:
    level: int
    text: str


@dataclass
class Paragraph:
    text: str
    muted: bool = False


@dataclass
class Quote:
    text: str


@dataclass
class Bullets:
    items: list[str]
    ordered: bool = False


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]
    widths: list[float] | None = None  # relative column widths for the PDF
    caption: str | None = None


@dataclass
class Figure:
    svg: str
    caption: str
    alt: str = ""
    width_mm: float = 174.0  # width in the PDF; the HTML scales to the page


@dataclass
class Code:
    text: str


@dataclass
class PageBreak:
    pass


@dataclass
class Callout:
    """A short labelled note, for example the 'not a measurement' warnings next to a figure."""

    label: str
    text: str


Block = Heading | Paragraph | Quote | Bullets | Table | Figure | Code | PageBreak | Callout


@dataclass
class Document:
    title: str
    subtitle: str
    meta: list[tuple[str, str]] = field(default_factory=list)  # label, value pairs shown on the cover
    blocks: list[Block] = field(default_factory=list)


# ---- inline helpers -------------------------------------------------------------------------------------------------
_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|\*[^*\s][^*]*\*)")


def inline_parts(text: str) -> list[tuple[str, str, str | None]]:
    """Split inline Markdown into (kind, text, href) parts. kind is text, bold, italic, code or link."""
    out: list[tuple[str, str, str | None]] = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            out.append(("text", text[pos:m.start()], None))
        tok = m.group(0)
        if tok.startswith("**"):
            out.append(("bold", tok[2:-2], None))
        elif tok.startswith("`"):
            out.append(("code", tok[1:-1], None))
        elif tok.startswith("["):
            label, href = re.match(r"\[([^\]]+)\]\(([^)]+)\)", tok).groups()  # type: ignore[union-attr]
            out.append(("link", label, href))
        else:
            out.append(("italic", tok[1:-1], None))
        pos = m.end()
    if pos < len(text):
        out.append(("text", text[pos:], None))
    return out


def plain(text: str) -> str:
    """Inline Markdown as plain text; a link keeps its address in brackets so a printed report is still traceable."""
    parts = []
    for kind, t, href in inline_parts(text):
        parts.append(f"{t} ({href})" if kind == "link" and href and href.startswith("http") else t)
    return "".join(parts)


# ---- Markdown -> blocks ---------------------------------------------------------------------------------------------
def _row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_markdown(md: str, *, skip_title: bool = True, demote: int = 0) -> list[Block]:
    """Headings, paragraphs, lists, tables, block quotes and fenced code: the subset the project's articles use.
    `skip_title` drops the first level-1 heading (the caller shows the article title itself); `demote` shifts heading levels."""
    lines = md.replace("\r\n", "\n").split("\n")
    blocks: list[Block] = []
    i, n = 0, len(lines)
    seen_title = False
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            j = i + 1
            while j < n and not lines[j].startswith("```"):
                j += 1
            blocks.append(Code("\n".join(lines[i + 1:j])))
            i = j + 1
            continue
        m = re.match(r"(#{1,6})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            if level == 1 and skip_title and not seen_title:
                seen_title = True
            else:
                blocks.append(Heading(min(6, level + demote), m.group(2).strip()))
            i += 1
            continue
        if re.match(r"\s*([-*_])(\s*\1){2,}\s*$", line):
            i += 1
            continue
        if line.lstrip().startswith(">"):
            buf = []
            while i < n and lines[i].lstrip().startswith(">"):
                buf.append(lines[i].lstrip()[1:].strip())
                i += 1
            blocks.append(Quote(" ".join(buf)))
            continue
        if "|" in line and i + 1 < n and re.match(r"\s*\|?\s*:?-{2,}", lines[i + 1]):
            header = _row(line)
            i += 2
            rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_row(lines[i]))
                i += 1
            blocks.append(Table(header, [r + [""] * (len(header) - len(r)) for r in rows]))
            continue
        bm = re.match(r"\s*([-*]|\d+\.)\s+(.*)", line)
        if bm:
            ordered = bm.group(1)[0].isdigit()
            items: list[str] = []
            while i < n:
                mm = re.match(r"\s*([-*]|\d+\.)\s+(.*)", lines[i])
                if mm:
                    items.append(mm.group(2).strip())
                    i += 1
                elif lines[i].startswith("  ") and lines[i].strip() and items:
                    items[-1] += " " + lines[i].strip()
                    i += 1
                else:
                    break
            blocks.append(Bullets(items, ordered))
            continue
        buf = [line.strip()]
        i += 1
        while i < n and lines[i].strip() and not re.match(r"(#{1,6}\s|```|\s*>|\s*([-*]|\d+\.)\s)", lines[i]) and "|" not in lines[i][:1]:
            buf.append(lines[i].strip())
            i += 1
        blocks.append(Paragraph(" ".join(buf)))
    return blocks
