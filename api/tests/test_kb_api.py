import pytest
from kbfakes import INVERSION, PM25, FakeEmbedder, make_pdf
from test_kb import encrypted_pdf, settings

from app.api.knowledge import get_kb_service
from app.core.config import get_settings
from app.kb.embeddings import EmbeddingModelMissing
from app.kb.service import KnowledgeBaseService


@pytest.fixture
def kbapi(client, tmp_path):
    def make(**over):
        s = settings(tmp_path, **over)
        emb = FakeEmbedder()
        svc = KnowledgeBaseService(s, embedder=emb)
        client.app.dependency_overrides[get_kb_service] = lambda: svc
        client.app.dependency_overrides[get_settings] = lambda: s
        client.svc, client.emb = svc, emb
        return client

    return make


def upload(c, name, data, category="official_guidance", **form):
    return c.post("/api/kb/documents", files={"file": (name, data, "application/octet-stream")}, data={"category": category, **form})


def err(r):
    return r.json()["error"]


def test_full_lifecycle_upload_index_search_reindex_delete(kbapi):
    c = kbapi()
    r = upload(c, "who.pdf", make_pdf([PM25, INVERSION]), title="WHO Guidelines", publisher="WHO", licence="CC BY", source_url="https://who.int/a")
    assert r.status_code == 202
    doc = r.json()
    assert doc["status"] == "indexing" and doc["category_label"] == "Official guidance" and doc["pages"] == 2 and doc["kind"] == "pdf"

    listing = c.get("/api/kb/documents").json()  # indexing runs as a background task, finished by now
    assert listing["limits"]["max_upload_mb"] == 10 and listing["limits"]["categories"]["official_guidance"] == "Official guidance"
    got = listing["documents"][0]
    assert got["id"] == doc["id"] and got["status"] == "ready" and got["chunk_count"] > 1 and got["needs_reindex"] is False
    assert got["indexed_at"] and got["error"] is None and len(got["content_hash"]) == 64

    chunks = c.get(f"/api/kb/documents/{doc['id']}/chunks", params={"limit": 3}).json()
    assert len(chunks) == 3 and chunks[0]["page_start"] == 1 and chunks[0]["index"] == 0

    res = c.get("/api/kb/search", params={"q": "WHO guideline for annual PM2.5", "top_k": 2}).json()
    assert res["status"] == "ok" and res["passages"][0]["title"] == "WHO Guidelines" and res["passages"][0]["location"] == "p. 1"
    assert res["passages"][0]["category_label"] == "Official guidance" and res["min_score"] == 0.15

    assert c.post(f"/api/kb/documents/{doc['id']}/reindex").status_code == 202
    assert c.get(f"/api/kb/documents/{doc['id']}").json()["status"] == "ready"

    assert c.delete(f"/api/kb/documents/{doc['id']}").status_code == 204
    assert c.get(f"/api/kb/documents/{doc['id']}").status_code == 404
    assert c.get("/api/kb/documents").json()["documents"] == []
    assert c.get("/api/kb/search", params={"q": "WHO guideline PM2.5"}).json()["status"] == "empty"


@pytest.mark.parametrize("name,data,form,status,code", [
    ("tool.exe", b"MZ", {}, 415, "unsupported_type"),
    ("fake.pdf", b"plain text pretending", {}, 422, "not_a_pdf"),
    ("empty.txt", b"", {}, 422, "empty_file"),
    ("notes.txt", b"valid text content here", {"category": "bogus"}, 422, "invalid_category"),
    ("notes.txt", b"valid text content here", {"source_url": "javascript:alert(1)"}, 422, "invalid_url"),
    ("bin.txt", b"abc\x00def", {}, 422, "not_text"),
])
def test_invalid_uploads_are_rejected_with_codes_and_nothing_is_stored(kbapi, name, data, form, status, code):
    c = kbapi()
    r = upload(c, name, data, **form)
    assert r.status_code == status and err(r)["code"] == code and err(r)["message"] and err(r)["request_id"]
    assert c.get("/api/kb/documents").json()["documents"] == []


def test_encrypted_pdfs_are_rejected(kbapi):
    r = upload(kbapi(), "locked.pdf", encrypted_pdf())
    assert r.status_code == 422 and err(r)["code"] == "encrypted_pdf"


def test_a_missing_file_is_a_validation_error(kbapi):
    r = kbapi().post("/api/kb/documents", data={"category": "official_guidance"})
    assert r.status_code == 422 and err(r)["code"] == "validation_error"


def test_oversized_uploads_are_refused_before_the_file_is_read(kbapi):
    c = kbapi(kb_max_upload_mb=1)
    r = upload(c, "big.txt", b"word " * (400 * 1024))  # ~2 MB against a 1 MB limit
    assert r.status_code == 413 and err(r)["code"] == "file_too_large" and "1 MB" in err(r)["message"]
    assert c.get("/api/kb/documents").json()["documents"] == []
    just_under = upload(c, "ok.txt", b"word " * 1000)
    assert just_under.status_code == 202


def test_duplicates_return_409_with_the_existing_document(kbapi):
    c = kbapi()
    first = upload(c, "a.txt", PM25).json()
    r = upload(c, "same-content-new-name.txt", PM25)
    assert r.status_code == 409 and err(r)["code"] == "duplicate"
    assert err(r)["details"]["existing_document_id"] == first["id"]
    assert len(c.get("/api/kb/documents").json()["documents"]) == 1


def test_a_failed_indexing_run_is_visible_in_the_list_and_can_be_retried(kbapi):
    c = kbapi()
    c.emb.fail_with = EmbeddingModelMissing("The embedding model 'x' is not installed on the Ollama host. Run: ollama pull x")
    doc = upload(c, "a.txt", PM25).json()
    shown = c.get("/api/kb/documents").json()["documents"][0]
    assert shown["status"] == "failed" and "ollama pull" in shown["error"] and shown["chunk_count"] == 0
    c.emb.fail_with = None
    assert c.post(f"/api/kb/documents/{doc['id']}/reindex").status_code == 202
    assert c.get(f"/api/kb/documents/{doc['id']}").json()["status"] == "ready"


def test_unknown_documents_return_404_everywhere(kbapi):
    c = kbapi()
    for call in (lambda: c.get("/api/kb/documents/nope"), lambda: c.get("/api/kb/documents/nope/chunks"),
                 lambda: c.post("/api/kb/documents/nope/reindex"), lambda: c.delete("/api/kb/documents/nope")):
        r = call()
        assert r.status_code == 404 and err(r)["code"] == "not_found"


def test_search_validates_its_parameters_and_supports_filters(kbapi):
    c = kbapi()
    upload(c, "g.txt", PM25, category="official_guidance", title="Guidance")
    upload(c, "p.txt", INVERSION, category="scientific_publication", title="Paper")
    assert c.get("/api/kb/search", params={"q": "x"}).status_code == 422
    assert c.get("/api/kb/search", params={"q": "valid query", "top_k": 0}).status_code == 422
    r = c.get("/api/kb/search", params={"q": "valid query", "category": "nonsense"})
    assert r.status_code == 422 and err(r)["code"] == "invalid_category"
    only_paper = c.get("/api/kb/search", params={"q": "inversion traps pollutants", "category": "scientific_publication"}).json()
    assert {p["title"] for p in only_paper["passages"]} == {"Paper"}
    missing = c.get("/api/kb/search", params={"q": "anything here", "document": "zzz"}).json()
    assert missing["status"] == "document_not_found" and set(missing["available_documents"]) == {"Guidance", "Paper"}


def test_status_reports_embedding_availability_and_counts(kbapi):
    c = kbapi()
    upload(c, "a.txt", PM25)
    ok = c.get("/api/kb/status").json()
    assert ok["embedding"]["available"] is True and ok["documents_ready"] == 1 and ok["documents_total"] == 1
    c.emb.fail_with = EmbeddingModelMissing("missing model")
    down = c.get("/api/kb/status").json()
    assert down["embedding"]["available"] is False and down["embedding"]["code"] == "embedding_model_missing"


def test_cors_allows_delete_from_the_frontend(client):
    r = client.options("/api/kb/documents/x", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "DELETE"})
    assert r.status_code == 200 and "DELETE" in r.headers["access-control-allow-methods"]


def test_openapi_lists_the_knowledge_base_endpoints(client):
    paths = set(client.get("/openapi.json").json()["paths"])
    assert {"/api/kb/documents", "/api/kb/documents/{doc_id}", "/api/kb/documents/{doc_id}/chunks",
            "/api/kb/documents/{doc_id}/reindex", "/api/kb/search", "/api/kb/status"} <= paths


def test_csv_upload_is_listed_searched_and_combined_with_a_pdf(kbapi):
    c = kbapi()
    csv_body = b"station,zone,pm25,note\nAnand Vihar,Delhi,312.5,heavy smog episode\nSector 62,Noida,141.2,construction dust\n"
    pdf = upload(c, "who.pdf", make_pdf([PM25, INVERSION]), title="WHO Guidelines")
    table = upload(c, "stations.csv", csv_body, category="dataset", title="NCR station readings")
    assert pdf.status_code == 202 and table.status_code == 202
    assert table.json()["kind"] == "csv" and table.json()["category_label"] == "Dataset (table)" and table.json()["pages"] is None

    listing = c.get("/api/kb/documents").json()
    assert ".csv" in listing["limits"]["extensions"] and listing["limits"]["categories"]["dataset"] == "Dataset (table)"
    assert {d["kind"] for d in listing["documents"]} == {"pdf", "csv"} and all(d["status"] == "ready" for d in listing["documents"])

    res = c.get("/api/kb/search", params={"q": "Anand Vihar heavy smog episode pm25", "top_k": 3}).json()
    assert res["status"] == "ok" and res["passages"][0]["title"] == "NCR station readings"
    assert res["passages"][0]["category_label"] == "Dataset (table)" and "Anand Vihar" in res["passages"][0]["text"]


def test_bad_csv_is_rejected_with_a_specific_code(kbapi):
    c = kbapi()
    r = upload(c, "empty.csv", b"only,a,header\n", category="dataset")
    assert r.status_code == 422 and err(r)["code"] == "no_extractable_text"
