import io
from pathlib import Path

import httpx
import pytest
from kbfakes import BAKING, INVERSION, PM25, FakeEmbedder, make_pdf
from pypdf import PdfReader, PdfWriter

from app.core.config import Settings, get_settings
from app.kb.chunking import chunk_document
from app.kb.embeddings import (
    EmbeddingBadResponse, EmbeddingModelMissing, EmbeddingUnavailable, OllamaEmbedder,
)
from app.kb.extract import extract, safe_filename, unwrap_lines
from app.kb.service import KnowledgeBaseService, matches_document
from app.kb.types import Extracted, KbError, PageText


def settings(tmp_path, **over):
    return Settings(**{**get_settings().model_dump(), "kb_dir": str(tmp_path / "kb"), "kb_min_score": 0.15,
                       "kb_chunk_chars": 300, "kb_chunk_overlap": 50, **over})


@pytest.fixture
def emb():
    return FakeEmbedder()


@pytest.fixture
def kb(tmp_path, emb):
    return KnowledgeBaseService(settings(tmp_path), embedder=emb)


async def ingest(kb, name, data, category="project_documentation", **kw):
    rec = await kb.add_document(name, data if isinstance(data, bytes) else data.encode(), category, **kw)
    await kb.index(rec.id)
    return kb.get(rec.id)


async def codes(coro):
    with pytest.raises(KbError) as e:
        await coro
    return e.value.code, e.value.status


# ---------------------------------------------------------------------------------------------- extraction
def test_text_and_markdown_are_extracted_without_pages():
    s = get_settings()
    t = extract("notes.txt", "Hello\r\n\r\n\r\n\r\nWorld\x07".encode(), s)
    assert t.kind == "txt" and t.page_count is None and t.pages[0].number is None
    assert t.pages[0].text == "Hello\n\nWorld"  # CRLF normalised, blank runs collapsed, control characters removed
    assert extract("a.md", b"# T\n\ntext here", s).kind == "md" and extract("a.markdown", b"x y z", s).kind == "md"


def test_pdf_text_keeps_page_numbers_and_skips_blank_pages():
    out = extract("g.pdf", make_pdf(["Page one about PM2.5.", "", "Page three (with) parentheses."]), get_settings())
    assert [(p.number, p.text) for p in out.pages] == [(1, "Page one about PM2.5."), (3, "Page three (with) parentheses.")]
    assert out.page_count == 3 and any("no extractable text" in w for w in out.warnings)


def test_filenames_are_sanitised_for_display():
    assert safe_filename("../../etc/passwd.txt") == "passwd.txt"
    assert safe_filename("C:\\Users\\me\\report.pdf") == "report.pdf"
    assert safe_filename("bad\x00name\x1f.md") == "badname.md"
    assert safe_filename("   ...  ") == "document" and len(safe_filename("a" * 500 + ".txt")) <= 120


def encrypted_pdf():
    w = PdfWriter()
    w.append(PdfReader(io.BytesIO(make_pdf(["secret"]))))
    w.encrypt("pw", algorithm="RC4-128")
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()


@pytest.mark.parametrize("name,data,code,status", [
    ("evil.exe", b"MZ\x90\x00", "unsupported_type", 415),
    ("paper.docx", b"PK\x03\x04", "unsupported_type", 415),
    ("noext", b"hello", "unsupported_type", 415),
    ("empty.txt", b"", "empty_file", 422),
    ("fake.pdf", b"This is not a PDF at all", "not_a_pdf", 422),
    ("broken.pdf", b"%PDF-1.4\nthis is garbage, not objects\n", "unreadable_pdf", 422),
    ("binary.txt", b"abc\x00\x01\x02def", "not_text", 422),
    ("latin.txt", "caf\xe9 cr\xe8me".encode("latin-1"), "unsupported_encoding", 422),
    ("blank.txt", b"   \n\n\t ", "no_extractable_text", 422),
    ("scan.pdf", make_pdf(["", ""]), "no_extractable_text", 422),
    ("locked.pdf", None, "encrypted_pdf", 422),
])
def test_invalid_files_are_rejected_with_a_specific_reason(name, data, code, status):
    with pytest.raises(KbError) as e:
        extract(name, data if data is not None else encrypted_pdf(), get_settings())
    assert (e.value.code, e.value.status) == (code, status) and e.value.message


def test_limits_on_size_pages_and_text(tmp_path):
    s1 = settings(tmp_path, kb_max_upload_mb=1)
    with pytest.raises(KbError) as e:
        extract("big.txt", b"a " * (600 * 1024), s1)
    assert (e.value.code, e.value.status) == ("file_too_large", 413)
    with pytest.raises(KbError) as e:
        extract("many.pdf", make_pdf(["a b c"] * 3), settings(tmp_path, kb_max_pdf_pages=2))
    assert e.value.code == "too_many_pages"
    with pytest.raises(KbError) as e:
        extract("long.txt", b"word " * 100, settings(tmp_path, kb_max_text_chars=100))
    assert e.value.code == "too_much_text"


# ---------------------------------------------------------------------------------------------- chunking
def doc(*pages, kind="pdf"):
    return Extracted(kind, [PageText(i + 1 if kind == "pdf" else None, t) for i, t in enumerate(pages)], len(pages) if kind == "pdf" else None)


def test_chunks_respect_size_and_keep_the_page_they_came_from():
    words = lambda tag, n: " ".join(f"{tag}{i}" for i in range(n)) + "."  # noqa: E731
    chunks = chunk_document(doc(words("alpha", 200), words("beta", 200)), 300, 50, 100)
    assert all(len(c.text) <= 300 for c in chunks)
    assert {c.page_start for c in chunks} == {1, 2} and all(c.page_start == c.page_end for c in chunks)
    assert all(c.text.startswith("alpha") or "alpha" not in c.text for c in chunks if c.page_start == 2) and [c.index for c in chunks] == list(range(len(chunks)))


def test_adjacent_chunks_overlap_so_sentences_are_not_cut_off_from_context():
    chunks = chunk_document(doc(" ".join(f"w{i}" for i in range(300)) + "."), 300, 60, 100)
    assert len(chunks) > 2
    for a, b in zip(chunks, chunks[1:]):
        assert set(a.text.split()[-4:]) & set(b.text.split()[:20])  # the tail of one reappears at the head of the next


def test_markdown_chunks_carry_their_section_and_do_not_overlap_across_headings():
    md = "# Guide\n\nIntro text about the guide and what it covers.\n\n## Methods\n\n" + " ".join(f"m{i}" for i in range(120)) + "\n\n## Results\n\nResults paragraph long enough to keep."
    chunks = chunk_document(doc(md, kind="md"), 300, 50, 100)
    assert [c.section for c in chunks][0] == "Guide" and chunks[-1].section == "Results"
    assert chunks[-1].text.startswith("## Results")  # a new section starts clean, with no carried-over text


def test_chunking_rejects_oversized_documents_and_bad_parameters():
    with pytest.raises(KbError) as e:
        chunk_document(doc(" ".join(f"w{i}" for i in range(5000))), 100, 10, 5)
    assert e.value.code == "too_many_chunks"
    with pytest.raises(ValueError):
        chunk_document(doc("text " * 50), 50, 10, 10)
    with pytest.raises(KbError):
        chunk_document(doc("   "), 300, 50, 10)


# ---------------------------------------------------------------------------------------------- ingestion
async def test_a_pdf_is_ingested_indexed_and_marked_ready(kb):
    rec = await kb.add_document("who.pdf", make_pdf([PM25, INVERSION]), "official_guidance", publisher="WHO", licence="CC BY-NC-SA", source_url="https://who.int/x")
    assert rec.status == "indexing" and rec.pages == 2 and rec.chunk_count == 0
    assert (Path(kb._files) / f"{rec.id}.pdf").exists()
    await kb.index(rec.id)
    done = kb.get(rec.id)
    assert done.status == "ready" and done.error is None and done.chunk_count > 1 and done.embedding_model == "fake-embed" and done.indexed_at
    assert kb.store.count_chunks(rec.id) == done.chunk_count
    pages = {h.page_start for h in await kb.chunks(rec.id, 100)}
    assert pages == {1, 2}


async def test_invalid_uploads_are_rejected_before_anything_is_stored(kb, tmp_path):
    assert await codes(kb.add_document("a.txt", b"hello world text", "nonsense")) == ("invalid_category", 422)
    assert await codes(kb.add_document("a.txt", b"hello world text", "official_guidance", source_url="javascript:alert(1)")) == ("invalid_url", 422)
    assert await codes(kb.add_document("a.exe", b"x", "official_guidance")) == ("unsupported_type", 415)
    assert await codes(kb.add_document("a.pdf", b"nope", "official_guidance")) == ("not_a_pdf", 422)
    assert kb.list_documents() == [] and list(kb._files.iterdir()) == []


async def test_metadata_is_trimmed_and_defaults_come_from_the_filename(kb):
    rec = await kb.add_document("WHO Guidelines 2021.txt", PM25.encode(), "official_guidance", title="  ", publisher="x" * 500)
    assert rec.title == "WHO Guidelines 2021" and len(rec.publisher) == 120


async def test_duplicates_are_detected_by_content_even_under_a_new_name(kb):
    first = await ingest(kb, "a.txt", PM25)
    with pytest.raises(KbError) as e:
        await kb.add_document("renamed copy.txt", PM25.encode(), "official_guidance")
    assert (e.value.code, e.value.status, e.value.existing_id) == ("duplicate", 409, first.id)
    await kb.add_document("different.txt", INVERSION.encode(), "official_guidance")  # different content is fine
    assert len(kb.list_documents()) == 2


# ---------------------------------------------------------------------------------------------- failures are visible
async def test_an_embedding_failure_is_recorded_on_the_document_and_leaves_no_chunks(kb, emb):
    emb.fail_with = EmbeddingUnavailable("The embedding service (Ollama) is not reachable.")
    rec = await ingest(kb, "a.txt", PM25)
    assert rec.status == "failed" and "not reachable" in rec.error and rec.chunk_count == 0
    assert kb.store.count_chunks(rec.id) == 0
    emb.fail_with = None  # the service recovers; Re-index fixes it
    kb.start_reindex(rec.id)
    await kb.index(rec.id)
    assert kb.get(rec.id).status == "ready" and kb.get(rec.id).error is None


async def test_unexpected_errors_are_recorded_without_leaking_internals(kb, emb):
    async def boom(texts):
        raise RuntimeError("/secret/internal/path exploded")

    emb.embed_documents = boom
    rec = await ingest(kb, "a.txt", PM25)
    assert rec.status == "failed" and "secret" not in rec.error and "unexpectedly" in rec.error


async def test_a_missing_stored_file_is_reported(kb):
    rec = await kb.add_document("a.txt", PM25.encode(), "official_guidance")
    (kb._files / f"{rec.id}.txt").unlink()
    await kb.index(rec.id)
    assert kb.get(rec.id).status == "failed" and "missing" in kb.get(rec.id).error


async def test_indexing_interrupted_by_a_restart_shows_as_failed(tmp_path, emb):
    s = settings(tmp_path)
    first = KnowledgeBaseService(s, embedder=emb)
    rec = await first.add_document("a.txt", PM25.encode(), "official_guidance")  # left in 'indexing'
    first.registry.close()
    second = KnowledgeBaseService(s, embedder=emb)  # a new process
    got = second.get(rec.id)
    assert got.status == "failed" and "interrupted" in got.error


# ---------------------------------------------------------------------------------------------- re-indexing
async def test_reindex_replaces_chunks_instead_of_duplicating_them(kb):
    rec = await ingest(kb, "a.pdf", make_pdf([PM25, INVERSION]))
    before = rec.chunk_count
    kb.start_reindex(rec.id)
    assert kb.get(rec.id).status == "indexing"
    await kb.index(rec.id)
    after = kb.get(rec.id)
    assert after.status == "ready" and after.chunk_count == before == kb.store.count_chunks(rec.id)


async def test_reindex_guards(kb):
    assert await codes(_async(kb.start_reindex, "nope")) == ("not_found", 404)
    rec = await kb.add_document("a.txt", PM25.encode(), "official_guidance")  # still 'indexing'
    assert await codes(_async(kb.start_reindex, rec.id)) == ("already_indexing", 409)


async def _async(fn, *a):
    return fn(*a)


async def test_changing_the_embedding_model_requires_reindexing_and_hides_stale_vectors(tmp_path):
    s = settings(tmp_path)
    old = KnowledgeBaseService(s, embedder=FakeEmbedder("model-a"))
    rec = await ingest(old, "a.txt", PM25)
    old.registry.close()
    new = KnowledgeBaseService(s, embedder=FakeEmbedder("model-b"))
    assert new.needs_reindex(new.get(rec.id)) and not new.ready
    assert (await new.search("WHO PM2.5 guideline")).status == "empty"  # nothing searchable under the new model
    new.start_reindex(rec.id)
    await new.index(rec.id)
    assert not new.needs_reindex(new.get(rec.id)) and (await new.search("WHO PM2.5 guideline")).status == "ok"
    # the old model's chunks were purged, not left behind
    assert new.store._client.get_collection("kb_model-a").get(where={"doc_id": rec.id})["ids"] == []


# ---------------------------------------------------------------------------------------------- deletion
async def test_deleting_a_document_removes_its_row_file_and_every_chunk(kb):
    rec = await ingest(kb, "a.txt", PM25)
    other = await ingest(kb, "b.txt", INVERSION)
    path = kb._files / f"{rec.id}.txt"
    assert path.exists()
    await kb.delete(rec.id)
    assert not path.exists() and kb.store.count_chunks(rec.id) == 0
    with pytest.raises(KbError):
        kb.get(rec.id)
    res = await kb.search("WHO guideline PM2.5 particulate")
    assert all(p.document_id != rec.id for p in res.passages)
    assert kb.store.count_chunks(other.id) > 0  # other documents are untouched
    assert await codes(kb.delete(rec.id)) == ("not_found", 404)


async def test_deleting_while_indexing_leaves_no_orphaned_chunks(kb, emb):
    rec = await kb.add_document("a.txt", PM25.encode(), "official_guidance")
    emb.on_embed = lambda: kb.registry.delete(rec.id)  # the user deletes it mid-embedding
    await kb.index(rec.id)
    assert kb.registry.get(rec.id) is None and kb.store.count_chunks(rec.id) == 0


# ---------------------------------------------------------------------------------------------- retrieval
async def corpus(kb):
    who = await ingest(kb, "who.pdf", make_pdf([PM25, INVERSION]), "official_guidance", title="WHO Air Quality Guidelines", publisher="WHO", licence="CC BY-NC-SA 3.0 IGO", source_url="https://who.int/g")
    paper = await ingest(kb, "inv.md", "# Inversions\n\n" + INVERSION, "scientific_publication", title="Winter inversions in the plains", publisher="Journal X")
    notes = await ingest(kb, "readme.txt", "AEROCAST computes the ventilation index from boundary layer height and wind speed. " * 4, "project_documentation", title="AEROCAST README")
    return who, paper, notes


async def test_a_relevant_question_finds_the_right_passage_with_page_and_provenance(kb):
    who, *_ = await corpus(kb)
    res = await kb.search("What is the WHO guideline for annual PM2.5?", top_k=3)
    assert res.status == "ok"
    top = res.passages[0]
    assert top.document == "WHO Air Quality Guidelines" and top.document_id == who.id
    assert top.category == "official_guidance" and top.category_label == "Official guidance"
    assert top.publisher == "WHO" and top.licence.startswith("CC BY") and top.url == "https://who.int/g" and top.location == "p. 1"
    assert "5 micrograms" in top.text and top.score > 0.3
    assert [p.score for p in res.passages] == sorted((p.score for p in res.passages), reverse=True)


async def test_passages_from_a_markdown_file_cite_their_section(kb):
    await corpus(kb)
    res = await kb.search("temperature inversion traps pollutants", document="winter inversions")
    assert res.passages and res.passages[0].location == "section 'Inversions'"


async def test_unrelated_questions_return_no_relevant_passages_instead_of_the_least_bad_match(kb):
    await corpus(kb)
    res = await kb.search("quantum chromodynamics gluon confinement lattice")
    assert res.status == "no_relevant_passages" and res.passages == [] and "best similarity" in res.reason


async def test_top_k_is_respected_and_capped(kb):
    await corpus(kb)
    assert len((await kb.search("pollutants inversion temperature", top_k=1)).passages) == 1
    assert len((await kb.search("pollutants inversion temperature", top_k=999, min_score=0.0)).passages) <= kb._s.kb_top_k_max


async def test_filters_by_category_and_by_document_title(kb):
    who, paper, notes = await corpus(kb)
    only_notes = await kb.search("ventilation index boundary layer wind speed", categories=["project_documentation"])
    assert {p.document_id for p in only_notes.passages} == {notes.id}
    assert (await kb.search("inversion", categories=["official_guidance"], min_score=0.0)).passages[0].document_id == who.id
    missing = await kb.search("anything at all", document="no such doc")
    assert missing.status == "document_not_found" and "WHO Air Quality Guidelines" in missing.available_documents


async def test_an_empty_knowledge_base_says_so(kb):
    assert (await kb.search("anything")).status == "empty"
    assert not kb.ready and "no documents" in kb.note.lower()


async def test_failed_and_unfinished_documents_are_never_searched(kb, emb):
    good = await ingest(kb, "good.txt", PM25)
    emb.fail_with = EmbeddingUnavailable("down")
    bad = await ingest(kb, "bad.txt", INVERSION)
    pending = await kb.add_document("pending.txt", BAKING.encode(), "official_guidance")
    emb.fail_with = None
    res = await kb.search("temperature inversion traps pollutants baking sourdough PM2.5", min_score=0.0)
    ids = {p.document_id for p in res.passages}
    assert ids <= {good.id} and bad.id not in ids and pending.id not in ids


async def test_search_degrades_gracefully_when_embeddings_are_unavailable(kb, emb):
    await ingest(kb, "a.txt", PM25)
    emb.fail_with = EmbeddingUnavailable("The embedding service (Ollama) is not reachable.")
    res = await kb.search("PM2.5 guideline")
    assert res.status == "unavailable" and "not reachable" in res.reason and res.passages == []


# ---------------------------------------------------------------------------------------------- Ollama embedder
def ollama(handler, **over):
    s = settings(Path("."), **{"kb_embed_batch": 2, "embedding_doc_prefix": "D:", "embedding_query_prefix": "Q:", **over})
    return OllamaEmbedder(s, transport=httpx.MockTransport(handler))


async def test_ollama_embedder_batches_requests_and_applies_task_prefixes():
    seen = []

    def handler(req):
        body = __import__("json").loads(req.content)
        seen.append(body)
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]] * len(body["input"])})

    e = ollama(handler)
    out = await e.embed_documents(["a", "b", "c", "d", "e"])
    assert len(out) == 5 and [len(b["input"]) for b in seen] == [2, 2, 1]
    assert seen[0]["input"] == ["D:a", "D:b"] and seen[0]["model"] == get_settings().ollama_embed_model
    assert (await e.embed_query("why")) == [0.1, 0.2, 0.3] and seen[-1]["input"] == ["Q:why"]


@pytest.mark.parametrize("resp,exc", [
    (httpx.Response(404, json={"error": "model not found"}), EmbeddingModelMissing),
    (httpx.Response(500, json={"error": "model not found, try pulling it"}), EmbeddingModelMissing),
    (httpx.Response(500, json={"error": "out of memory"}), EmbeddingBadResponse),
    (httpx.Response(200, json={"embeddings": [[0.1]]}), EmbeddingBadResponse),  # wrong count for 2 inputs
    (httpx.Response(200, json={"embeddings": [[0.1], [0.1, 0.2]]}), EmbeddingBadResponse),  # inconsistent dimensions
    (httpx.Response(200, content=b'{"embeddings": [[0.1], [NaN]]}'), EmbeddingBadResponse),  # a server can send NaN as raw text
    (httpx.Response(200, json={"nope": 1}), EmbeddingBadResponse),
])
async def test_ollama_embedder_failures_are_typed(resp, exc):
    with pytest.raises(exc) as info:
        await ollama(lambda req: resp).embed_documents(["x", "y"])
    assert info.value.message
    if exc is EmbeddingModelMissing:
        assert "ollama pull" in info.value.message


async def test_ollama_embedder_reports_an_unreachable_host_and_missing_model():
    def down(req):
        raise httpx.ConnectError("refused")

    for call in (lambda e: e.embed_query("x"), lambda e: e.check()):
        with pytest.raises(EmbeddingUnavailable) as info:
            await call(ollama(down))
        assert "not reachable" in info.value.message and "ollama.test" not in info.value.message
    with pytest.raises(EmbeddingModelMissing) as info:
        await ollama(lambda req: httpx.Response(200, json={"models": [{"name": "other:latest"}]})).check()
    assert "ollama pull" in info.value.message
    await ollama(lambda req: httpx.Response(200, json={"models": [{"name": f"{get_settings().ollama_embed_model}:latest"}]})).check()


# ---------------------------------------------------------------------------------------------- loose document names
@pytest.mark.parametrize("needle,title,filename,expected", [
    ("who guidelines", "WHO Air Quality Guidelines", "who.pdf", True),
    ("the CPCB document", "CPCB: How is AQI calculated", "how_aqi.pdf", True),
    ("CPCB document title", "CPCB: How is AQI calculated", "how_aqi.pdf", True),
    ("how_aqi", "CPCB: How is AQI calculated", "how_aqi.pdf", True),
    ("AEROCAST README", "AEROCAST README", "readme.txt", True),
    ("who paper", "WHO Air Quality Guidelines", "who.pdf", True),
    ("nasa report", "WHO Air Quality Guidelines", "who.pdf", False),
    ("document", "WHO Air Quality Guidelines", "who.pdf", False),  # only generic words: names nothing
    ("who unicorn", "WHO Air Quality Guidelines", "who.pdf", False),  # every meaningful word must match
    ("", "WHO Air Quality Guidelines", "who.pdf", False),
])
def test_document_names_match_loosely_but_not_carelessly(needle, title, filename, expected):
    assert matches_document(needle, title, filename) is expected


def test_pdf_layout_line_breaks_are_joined_but_paragraph_breaks_stay():
    assert unwrap_lines("A minimum of 16 hours\nis necessary for\ncalculating.\n\nNew paragraph\nhere.") == (
        "A minimum of 16 hours is necessary for calculating.\n\nNew paragraph here.")


async def test_a_loosely_named_document_filter_still_finds_the_document(kb):
    who = await ingest(kb, "who.pdf", make_pdf([PM25]), "official_guidance", title="WHO Air Quality Guidelines")
    res = await kb.search("annual PM2.5 guideline", document="the WHO guidelines document")
    assert res.status == "ok" and res.passages[0].document_id == who.id


async def test_naming_a_document_relaxes_the_relevance_threshold_for_that_search(tmp_path):
    kb = KnowledgeBaseService(settings(tmp_path, kb_min_score=0.8, kb_named_document_relax=0.1, kb_lexical_relax=0.0), embedder=FakeEmbedder())
    await ingest(kb, "nato.txt", "alpha bravo charlie delta echo foxtrot golf hotel india juliet", "project_documentation", title="Phonetic alphabet")
    query = "alpha bravo charlie delta"  # shares 4 of the document's words: cosine about 0.72, between 0.7 and 0.8
    assert (await kb.search(query)).status == "no_relevant_passages"
    named = await kb.search(query, document="phonetic alphabet")
    assert named.status == "ok" and 0.7 <= named.passages[0].score < 0.8
    assert (await kb.search(query, document="phonetic alphabet", min_score=0.8)).status == "no_relevant_passages"  # an explicit threshold wins


# ---------------------------------------------------------------------------------------------- CSV support
STATIONS_CSV = (
    "station,zone,pm25,note\n"
    "Anand Vihar,Delhi,312.5,heavy smog episode\n"
    "Okhla Phase 2,Delhi,188.0,\n"
    "Sector 62,Noida,141.2,construction dust\n"
)


def test_csv_rows_repeat_the_column_header_and_skip_empty_cells():
    out = extract("stations.csv", STATIONS_CSV.encode(), settings(Path(".")))
    assert out.kind == "csv" and out.page_count is None
    text = out.pages[0].text
    assert text.splitlines()[0] == "Columns: station, zone, pm25, note"
    assert "row 1: station=Anand Vihar; zone=Delhi; pm25=312.5; note=heavy smog episode" in text
    assert "row 2: station=Okhla Phase 2; zone=Delhi; pm25=188.0" in text and "note=;" not in text  # empty cell left out
    assert out.pages[0].section == "rows 1-3"


def test_csv_semicolon_delimiter_and_headerless_files():
    semi = extract("a.csv", b"station;pm25\nAnand Vihar;312\nSector 62;141\n", settings(Path(".")))
    assert "station=Anand Vihar; pm25=312" in semi.pages[0].text and any("delimiter ';'" in w for w in semi.warnings)
    bare = extract("b.csv", b"1,2.5\n3,4.5\n", settings(Path(".")))
    assert bare.pages[0].text.startswith("Columns: column_1, column_2") and "row 1: column_1=1; column_2=2.5" in bare.pages[0].text
    assert any("columns were named" in w for w in bare.warnings)


def test_csv_blocks_stay_within_the_chunk_size_and_are_kept_whole():
    s = settings(Path("."), kb_chunk_chars=300)
    body = "station,pm25\n" + "".join(f"Station number {i},{100 + i}\n" for i in range(60))
    out = extract("big.csv", body.encode(), s)
    assert len(out.pages) > 1 and all(len(p.text) <= 300 + 40 for p in out.pages)
    chunks = chunk_document(out, 300, 50, 100)
    assert [c.text for c in chunks] == [p.text for p in out.pages]  # not re-split
    assert chunks[0].section == "rows 1-" + chunks[0].section.split("-")[1] and chunks[0].page_start is None
    assert all(c.text.startswith("Columns: station, pm25") for c in chunks)  # every chunk is self-describing


def test_csv_limits_and_bad_input():
    s = settings(Path("."), kb_csv_max_rows=3, kb_csv_max_columns=4)
    rows = "a,b\n" + "1,x\n" * 4
    with pytest.raises(KbError) as e:
        extract("r.csv", rows.encode(), s)
    assert e.value.code == "too_many_rows"
    with pytest.raises(KbError) as e:
        extract("c.csv", b"a,b,c,d,e\n1,2,3,4,5\n", s)
    assert e.value.code == "too_many_columns"
    with pytest.raises(KbError) as e:
        extract("h.csv", b"only,a,header\n", s)
    assert e.value.code == "no_extractable_text"
    with pytest.raises(KbError) as e:
        extract("bin.csv", b"a,b\n\x00\x01,2\n", s)
    assert e.value.code == "not_text"


async def test_csv_and_pdf_form_one_searchable_knowledge_base(kb):
    who = await ingest(kb, "who.pdf", make_pdf([PM25, INVERSION]), "official_guidance", title="WHO Air Quality Guidelines")
    data = await ingest(kb, "stations.csv", STATIONS_CSV, "dataset", title="NCR station readings")
    assert data.kind == "csv" and data.status == "ready" and data.chunk_count >= 1 and data.pages is None

    table = await kb.search("Anand Vihar heavy smog episode pm25", categories=["dataset"], min_score=0.0)
    assert table.status == "ok"
    top = table.passages[0]
    assert top.document_id == data.id and top.category_label == "Dataset (table)"
    assert "Anand Vihar" in top.text and top.location.startswith("section 'rows ")

    everything = await kb.search("fine particulate matter annual guideline value", min_score=0.0)
    assert {p.document_id for p in everything.passages} == {who.id, data.id} or everything.passages[0].document_id == who.id
    assert {d.id for d in kb.list_documents()} == {who.id, data.id}  # one registry, one collection


async def test_assistant_is_told_table_rows_are_a_sample(kb):
    # The tool-level note is covered through the service category; here we only pin the label the tool keys on.
    data = await ingest(kb, "stations.csv", STATIONS_CSV, "dataset")
    res = await kb.search("Sector 62 construction dust", min_score=0.0)
    assert res.passages and res.passages[0].category == "dataset"
