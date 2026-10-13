"""The table, profile, query and relationship endpoints, through real HTTP handling."""

from test_kb_api import err, kbapi, upload  # noqa: F401  (kbapi is a fixture)
from test_kb_research import CSV, csv_of, make_history


def test_profile_query_and_meta_through_the_api(kbapi):
    c = kbapi()
    doc = upload(c, "readings.csv", CSV.encode(), category="dataset", title="NCR readings").json()
    listing = c.get("/api/kb/documents").json()["documents"][0]
    assert listing["status"] == "ready" and listing["meta"]["kind"] == "table" and "pm25" in listing["meta"]["pollutants"]

    prof = c.get(f"/api/kb/documents/{doc['id']}/profile").json()
    assert prof["rows"] == 5 and prof["time_column"] == "date" and prof["zone_column"] == "zone"
    assert c.get("/api/kb/datasets").json()["datasets"][0]["document_id"] == doc["id"]

    q = c.post(f"/api/kb/documents/{doc['id']}/query", json={
        "aggregates": [{"fn": "mean", "column": "pm25"}, {"fn": "count"}], "where": [{"column": "zone", "op": "=", "value": "Delhi"}]})
    assert q.status_code == 200
    body = q.json()
    assert body["rows"] == [[295.25, 2]] and body["document"] == "NCR readings" and body["matched_rows"] == 2

    bad = c.post(f"/api/kb/documents/{doc['id']}/query", json={"aggregates": [{"fn": "mean", "column": "nope"}]})
    assert bad.status_code == 422 and err(bad)["code"] == "unknown_column"
    invalid = c.post(f"/api/kb/documents/{doc['id']}/query", json={"limit": 5000})
    assert invalid.status_code == 422


def test_non_table_documents_are_not_queryable(kbapi):
    c = kbapi()
    doc = upload(c, "note.txt", b"PM2.5 guidance text for Delhi residents and clinics.", category="official_guidance").json()
    assert c.get(f"/api/kb/documents/{doc['id']}/profile").status_code == 422
    r = c.post(f"/api/kb/documents/{doc['id']}/query", json={})
    assert r.status_code == 422 and err(r)["code"] == "not_a_dataset"
    assert c.get(f"/api/kb/documents/{'0' * 32}/profile").status_code == 404
    assert c.get("/api/kb/datasets").json()["datasets"] == []


def test_relationship_endpoint_reports_evidence_and_limits(kbapi, tmp_path):
    db = tmp_path / "history.sqlite"
    driver = make_history(db, days=200, lag=1, with_effect=True)
    c = kbapi(ml_history_db=str(db))
    doc = upload(c, "fires.csv", csv_of(driver).encode(), category="dataset", title="Fire counts").json()
    r = c.get(f"/api/kb/documents/{doc['id']}/relationship", params={"column": "fires", "pollutant": "pm25", "max_lag": 3})
    assert r.status_code == 200
    out = r.json()
    assert out["best_lag_by_abs_pearson"] == 1 and out["heldout_check"]["status"] == "ok" and "not changed" in out["not_applied"]
    assert [x["lag"] for x in out["correlations"]] == [0, 1, 2, 3]

    assert c.get(f"/api/kb/documents/{doc['id']}/relationship", params={"column": "fires", "pollutant": "lead"}).status_code == 422
    assert c.get(f"/api/kb/documents/{doc['id']}/relationship", params={"column": "fires", "max_lag": 99}).status_code == 422
