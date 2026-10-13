"""Renders a Document to one self-contained HTML file and to a PDF. Both read the same blocks, so they cannot disagree."""

from __future__ import annotations

import io
import re
from html import escape

from fpdf import FPDF

from app.reports.doc import (
    Block, Bullets, Callout, Code, Document, Figure, Heading, PageBreak, Paragraph, Quote, Table, inline_parts, plain,
)

_LATIN = str.maketrans({
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5", "≥": ">=", "≤": "<=", "—": "-", "–": "-", "−": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...", "•": "-", "×": "x", "→": "->", "←": "<-", "µ": "u", "³": "3", "²": "2", "·": "-", "≈": "~",
    " ": " ", " ": " ", "\n": " ", "✓": "yes", "✗": "no", "≠": "!=", "±": "+/-",
})


def latin(text: object) -> str:
    return str(text).translate(_LATIN).encode("latin-1", "replace").decode("latin-1")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"


# ================================================================================ HTML
_CSS = """
:root{--ink:#17202f;--muted:#566377;--line:#d8dee9;--accent:#0e7490;--bg:#ffffff;--soft:#f3f6fa;--warn:#9a5b00;--warnbg:#fff7e6}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.7 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:62rem;margin:0 auto;padding:2rem 1.25rem 5rem}
header.cover{border-bottom:3px solid var(--accent);padding:2.5rem 0 1.5rem;margin-bottom:1.5rem}
.kicker{font-size:.8rem;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);font-weight:600}
h1{font-size:2.3rem;line-height:1.2;margin:.4rem 0 .5rem;letter-spacing:-.01em}
.sub{font-size:1.15rem;color:var(--muted);margin:0 0 1.2rem}
dl.meta{display:grid;grid-template-columns:max-content 1fr;gap:.25rem 1.2rem;margin:0;font-size:.92rem}
dl.meta dt{color:var(--muted)} dl.meta dd{margin:0}
nav.toc{background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:1rem 1.25rem;margin:1.5rem 0 2rem}
nav.toc h2{margin:0 0 .4rem;font-size:.85rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);border:0;padding:0}
nav.toc ol{margin:0;padding-left:1.2rem;columns:2;column-gap:2rem} nav.toc a{color:var(--ink);text-decoration:none} nav.toc a:hover{color:var(--accent)}
h2{font-size:1.55rem;margin:3rem 0 .6rem;padding-top:1.4rem;border-top:1px solid var(--line);letter-spacing:-.005em}
h3{font-size:1.2rem;margin:2rem 0 .3rem} h4{font-size:1.02rem;margin:1.4rem 0 .2rem}
p{margin:.7rem 0} p.muted{color:var(--muted);font-size:.92rem}
a{color:var(--accent)} code{background:var(--soft);padding:.05rem .3rem;border-radius:4px;font-size:.88em}
blockquote{margin:1rem 0;padding:.6rem 1rem;border-left:3px solid var(--accent);background:var(--soft);color:var(--muted);border-radius:0 8px 8px 0}
ul,ol{margin:.6rem 0;padding-left:1.4rem} li{margin:.25rem 0}
.tablewrap{overflow-x:auto;margin:1rem 0;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:.9rem;min-width:30rem}
th,td{padding:.45rem .7rem;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
th{background:var(--soft);font-size:.78rem;letter-spacing:.05em;text-transform:uppercase;color:var(--muted)}
tr:last-child td{border-bottom:0}
figure{margin:1.4rem 0;border:1px solid var(--line);border-radius:10px;padding:.8rem;background:#fff;break-inside:avoid}
figure svg{width:100%;height:auto;display:block}
figcaption{font-size:.88rem;color:var(--muted);margin-top:.5rem}
.callout{margin:1rem 0;padding:.7rem 1rem;border:1px solid #f0d9a8;background:var(--warnbg);border-radius:8px;font-size:.92rem;color:#5b3b00}
.callout b{display:block;font-size:.75rem;letter-spacing:.1em;text-transform:uppercase;color:var(--warn);margin-bottom:.15rem}
pre{background:#0f1726;color:#e8edf5;padding:1rem;border-radius:8px;overflow-x:auto;font-size:.85rem;line-height:1.5}
footer{margin-top:4rem;padding-top:1rem;border-top:1px solid var(--line);color:var(--muted);font-size:.85rem}
@media print{
  .wrap{max-width:none;padding:0} nav.toc ol{columns:2} h2{break-before:auto;break-after:avoid} h3,h4{break-after:avoid}
  figure,table,blockquote,.callout{break-inside:avoid} .tablewrap{overflow:visible;border:0} a{color:inherit;text-decoration:none}
  @page{size:A4;margin:14mm}
}
"""


def _inline_html(text: str) -> str:
    out = []
    for kind, t, href in inline_parts(text):
        e = escape(t)
        if kind == "bold":
            out.append(f"<strong>{e}</strong>")
        elif kind == "italic":
            out.append(f"<em>{e}</em>")
        elif kind == "code":
            out.append(f"<code>{e}</code>")
        elif kind == "link":
            ok = href and re.match(r"https?://", href)
            out.append(f'<a href="{escape(href or "", quote=True)}" rel="noopener noreferrer">{e}</a>' if ok else e)
        else:
            out.append(e)
    return "".join(out)


def _block_html(b: Block, ids: dict[int, str]) -> str:
    if isinstance(b, Heading):
        lvl = min(4, max(2, b.level))
        return f'<h{lvl} id="{ids.get(id(b), "")}">{_inline_html(b.text)}</h{lvl}>'
    if isinstance(b, Paragraph):
        return f'<p class="{"muted" if b.muted else ""}">{_inline_html(b.text)}</p>'
    if isinstance(b, Quote):
        return f"<blockquote>{_inline_html(b.text)}</blockquote>"
    if isinstance(b, Bullets):
        tag = "ol" if b.ordered else "ul"
        return f"<{tag}>" + "".join(f"<li>{_inline_html(i)}</li>" for i in b.items) + f"</{tag}>"
    if isinstance(b, Table):
        head = "".join(f"<th scope='col'>{_inline_html(h)}</th>" for h in b.header)
        rows = "".join("<tr>" + "".join(f"<td>{_inline_html(c)}</td>" for c in r) + "</tr>" for r in b.rows)
        cap = f"<p class='muted'>{_inline_html(b.caption)}</p>" if b.caption else ""
        return f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>{cap}'
    if isinstance(b, Figure):
        label = escape(b.alt or b.caption, quote=True)
        svg = b.svg.replace("<svg ", f'<svg role="img" aria-label="{label}" ', 1)
        return f"<figure>{svg}<figcaption>{_inline_html(b.caption)}</figcaption></figure>"
    if isinstance(b, Code):
        return f"<pre><code>{escape(b.text)}</code></pre>"
    if isinstance(b, Callout):
        return f'<div class="callout"><b>{escape(b.label)}</b>{_inline_html(b.text)}</div>'
    return ""


def render_html(doc: Document) -> str:
    ids: dict[int, str] = {}
    used: set[str] = set()
    toc: list[tuple[str, str]] = []
    for b in doc.blocks:
        if isinstance(b, Heading) and b.level == 2:
            base = s = slug(b.text)
            k = 2
            while s in used:
                s, k = f"{base}-{k}", k + 1
            used.add(s)
            ids[id(b)] = s
            toc.append((s, b.text))
        elif isinstance(b, Heading):
            ids[id(b)] = ""
    meta = "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in doc.meta)
    toc_html = "".join(f'<li><a href="#{i}">{escape(plain(t))}</a></li>' for i, t in toc)
    body = "\n".join(_block_html(b, ids) for b in doc.blocks if not isinstance(b, PageBreak))
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(doc.title)}</title><style>{_CSS}</style></head><body><div class=\"wrap\">"
        f'<header class="cover"><div class="kicker">AEROCAST NCR</div><h1>{escape(doc.title)}</h1><p class="sub">{escape(doc.subtitle)}</p>'
        f"<dl class=\"meta\">{meta}</dl></header>"
        f'<nav class="toc" aria-label="Contents"><h2>Contents</h2><ol>{toc_html}</ol></nav>'
        f"{body}<footer>Generated by AEROCAST NCR. Every figure and number in this file was drawn from the sources listed in it at the time shown; "
        "nothing was estimated to fill a gap. This file is self-contained and works offline.</footer></div></body></html>"
    )


# ================================================================================ PDF
ACCENT = (14, 116, 144)
INK = (23, 32, 47)
MUTED = (86, 99, 119)
LINE = (216, 222, 233)


class _Pdf(FPDF):
    title_text = "AEROCAST NCR"

    def footer(self) -> None:  # noqa: D401
        self.set_y(-11)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, latin(f"{self.title_text} - values as retrieved; see Sources"), align="L")
        self.cell(0, 5, f"Page {self.page_no()} of {{nb}}", align="R")


def _svg_for_pdf(svg: str) -> bytes:
    # non-ASCII characters become numeric references so the XML parser needs no encoding declaration
    return str(svg).translate(_LATIN).encode("ascii", "xmlcharrefreplace")


def render_pdf(doc: Document) -> bytes:
    pdf = _Pdf(format="A4")
    pdf.title_text = latin(f"AEROCAST NCR - {doc.title}")[:90]
    pdf.set_margins(16, 14, 16)
    pdf.set_auto_page_break(True, 16)
    pdf.alias_nb_pages()
    pdf.set_title(latin(doc.title))
    pdf.set_author("AEROCAST NCR")
    pdf.set_creator("AEROCAST NCR")
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 5, "AEROCAST NCR", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 9, latin(doc.title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 5.6, latin(doc.subtitle), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    for k, v in doc.meta:
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(*MUTED)
        pdf.cell(34, 4.6, latin(k))
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*INK)
        pdf.multi_cell(0, 4.6, latin(v), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.8)
    pdf.line(pdf.l_margin, pdf.get_y() + 2, pdf.w - pdf.r_margin, pdf.get_y() + 2)
    pdf.set_line_width(0.2)
    pdf.ln(5)

    def need(h: float) -> None:
        if pdf.get_y() + h > pdf.h - 18:
            pdf.add_page()

    for b in doc.blocks:
        if isinstance(b, PageBreak):
            pdf.add_page()
        elif isinstance(b, Heading):
            lvl = min(4, max(2, b.level))
            size, gap = {2: (14, 6), 3: (11.5, 4), 4: (10, 3)}[lvl]
            need(22)
            pdf.ln(gap)
            if lvl == 2:
                pdf.start_section(latin(plain(b.text)), level=0)
            pdf.set_font("Helvetica", "B", size)
            pdf.set_text_color(*(ACCENT if lvl == 2 else INK))
            pdf.multi_cell(0, size * 0.55, latin(plain(b.text)), new_x="LMARGIN", new_y="NEXT")
            if lvl == 2:
                pdf.set_draw_color(*LINE)
                pdf.line(pdf.l_margin, pdf.get_y() + 0.5, pdf.w - pdf.r_margin, pdf.get_y() + 0.5)
            pdf.ln(2)
        elif isinstance(b, Paragraph):
            pdf.set_font("Helvetica", "I" if b.muted else "", 8.5 if b.muted else 9.5)
            pdf.set_text_color(*(MUTED if b.muted else INK))
            pdf.multi_cell(0, 4.7, latin(plain(b.text)), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1.5)
        elif isinstance(b, Quote):
            need(14)
            y0 = pdf.get_y()
            pdf.set_x(pdf.l_margin + 4)
            pdf.set_font("Helvetica", "I", 9.5)
            pdf.set_text_color(*MUTED)
            pdf.multi_cell(width - 4, 4.7, latin(plain(b.text)), new_x="LMARGIN", new_y="NEXT")
            pdf.set_draw_color(*ACCENT)
            pdf.set_line_width(0.7)
            pdf.line(pdf.l_margin + 1, y0, pdf.l_margin + 1, pdf.get_y())
            pdf.set_line_width(0.2)
            pdf.ln(2)
        elif isinstance(b, Callout):
            need(16)
            pdf.set_font("Helvetica", "B", 7.5)
            pdf.set_text_color(154, 91, 0)
            pdf.cell(0, 4, latin(b.label.upper()), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(91, 59, 0)
            pdf.multi_cell(0, 4.5, latin(plain(b.text)), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif isinstance(b, Bullets):
            for k, it in enumerate(b.items, start=1):
                need(8)
                pdf.set_font("Helvetica", "", 9.5)
                pdf.set_text_color(*INK)
                pdf.set_x(pdf.l_margin + 3)
                mark = f"{k}. " if b.ordered else "- "
                pdf.multi_cell(width - 3, 4.7, latin(mark + plain(it)), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1.5)
        elif isinstance(b, Code):
            pdf.set_font("Courier", "", 8)
            pdf.set_text_color(*INK)
            pdf.multi_cell(0, 4, latin(b.text), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif isinstance(b, Table):
            ncol = len(b.header)
            w = b.widths or [1.0] * ncol
            tot = sum(w)
            widths = tuple(width * x / tot for x in w)
            need(20)
            pdf.set_font("Helvetica", "", 8.2)
            pdf.set_text_color(*INK)
            with pdf.table(col_widths=widths, line_height=4.4, first_row_as_headings=True, text_align="LEFT", borders_layout="HORIZONTAL_LINES") as t:
                r = t.row()
                for c in b.header:
                    r.cell(latin(plain(c)))
                for row in b.rows:
                    r = t.row()
                    for c in row:
                        r.cell(latin(plain(c)))
            if b.caption:
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(*MUTED)
                pdf.multi_cell(0, 4, latin(plain(b.caption)), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif isinstance(b, Figure):
            m = re.search(r'viewBox="0 0 (\d+) (\d+)"', b.svg)
            ratio = (int(m.group(2)) / int(m.group(1))) if m else 0.35
            w_mm = min(width, b.width_mm)
            h_mm = w_mm * ratio
            need(h_mm + 12)
            y = pdf.get_y()
            pdf.set_draw_color(*LINE)
            pdf.rect(pdf.l_margin, y, w_mm, h_mm)
            pdf.image(io.BytesIO(_svg_for_pdf(b.svg)), x=pdf.l_margin, y=y, w=w_mm, h=h_mm)
            pdf.set_y(y + h_mm + 1.5)
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(*MUTED)
            pdf.multi_cell(0, 4, latin(plain(b.caption)), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)
    return bytes(pdf.output())
