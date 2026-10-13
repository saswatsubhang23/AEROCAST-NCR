"""The written reports (docs/articles/*.md) served to the Report page.

Only files in that one folder, with a plain slug name, are ever read: there is no path from the request to anywhere else on disk.
The first `# heading` is the title; the first block quote is the summary shown on the index.
"""

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/docs", tags=["articles"])

ARTICLES_DIR = Path(__file__).resolve().parents[3] / "docs" / "articles"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")


def _meta(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), path.stem.replace("-", " ").title())
    summary = next((ln.lstrip("> ").strip() for ln in text.splitlines() if ln.startswith("> ")), "")
    words = len(re.findall(r"\w+", text))
    return {"slug": path.stem, "title": title, "summary": summary, "minutes": max(1, round(words / 200)), "updated": path.stat().st_mtime}


def _files() -> list[Path]:
    if not ARTICLES_DIR.is_dir():
        return []
    # an index file may list the reading order; otherwise alphabetical
    order = ARTICLES_DIR / "_order.txt"
    names = [ln.strip() for ln in order.read_text(encoding="utf-8").splitlines() if ln.strip()] if order.is_file() else []
    files = {p.stem: p for p in ARTICLES_DIR.glob("*.md") if SLUG.match(p.stem)}
    return [files[n] for n in names if n in files] + [p for k, p in sorted(files.items()) if k not in names]


@router.get("/articles", summary="The written reports, in reading order")
def list_articles():
    return {"articles": [_meta(p) for p in _files()]}


@router.get("/articles/{slug}", summary="One report as markdown")
def get_article(slug: str):
    if not SLUG.match(slug):
        raise HTTPException(404, {"code": "not_found", "message": "No such article."})
    path = ARTICLES_DIR / f"{slug}.md"
    if not path.is_file():
        raise HTTPException(404, {"code": "not_found", "message": "No such article."})
    return {**_meta(path), "markdown": path.read_text(encoding="utf-8")}
