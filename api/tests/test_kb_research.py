"""Queryable tables, exact-word fusion, research metadata and the dataset/pollution relationship test."""

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from kbfakes import FakeEmbedder
from test_kb import ingest, settings
from test_kb_assistant import executor

from app.kb import research
from app.kb.lexical import LexicalIndex, tokens
from app.kb.meta import text_meta
from app.kb.service import KnowledgeBaseService
from app.kb.tables import DatasetStore, QuerySpec, parse_aggregate, parse_condition, parse_time, tz_minutes
from app.kb.types import KbError, Table

CSV = (
    "date,station,zone,pm25,pm10,remarks\n"
    "2024-11-01,Anand Vihar,Delhi,310.5,420,smog\n"
    "2024-11-02,Anand Vihar,Delhi,280.0,390,\n"
    "2024-11-02,Sector 62,Noida,150.2,260,construction dust\n"
    "2024-12-01,Sector 62,Noida,NA,200,\n"
    "01-12-2024,Vikas Sadan,Gurugram,95.0,180,calm\n"
)


def table_from(text: str) -> Table:
    lines = [ln.split(",") for ln in text.strip().splitlines()]
    return Table(lines[0], lines[1:], [])


@pytest.fixture
def store(tmp_path):
    return DatasetStore(tmp_path / "tables.sqlite")


# ---------------------------------------------------------------------------------------------- tables
def test_profile_types_nulls_time_zone_and_pollutant_columns(store):
    p = store.load("d" * 32, table_from(CSV), "Asia/Kolkata")
    cols = {c["name"]: c for c in p["columns"]}
    assert cols["date"]["type"] == "datetime" and cols["pm25"]["type"] == "real" and cols["pm10"]["type"] == "integer"
    assert cols["station"]["type"] == "text" and cols["pm25"]["nulls"] == 1  # "NA" is a null, not text
    assert p["rows"] == 5 and p["time_column"] == "date"
    # offset-free dates are read as IST and stored as UTC: IST midnight is 18:30 UTC the day before
    assert p["time_start"] == "2024-10-31T18:30:00Z" and "UTC+05:30" in p["timezone_assumed"]
    assert p["pollutant_columns"] == {"pm25": "pm25", "pm10": "pm10"}
    assert p["station_column"] == "station" and p["zone_column"] == "zone"
    assert any("read as Asia/Kolkata" in w for w in p["warnings"])


def test_a_mixed_column_stays_text_rather_than_being_guessed(store):
    p = store.load("e" * 32, table_from("id,v\n1,10\n2,ten\n3,30\n"), "UTC")
    assert {c["name"]: c["type"] for c in p["columns"]} == {"id": "integer", "v": "text"}
    p2 = store.load("f" * 32, table_from("code,v\n007,1\n010,2\n"), "UTC")
    assert p2["columns"][0]["type"] == "text"  # leading zeros: an identifier, not a number


def test_aggregates_filters_groups_and_the_definition(store):
    store.load("a" * 32, table_from(CSV), "Asia/Kolkata")
    res = store.query("a" * 32, QuerySpec(aggregates=[parse_aggregate("mean:pm25"), parse_aggregate("count")],
                                          where=[parse_condition("zone=Delhi")]))
    assert res["rows"] == [[295.25, 2]] and res["matched_rows"] == 2 and res["dataset_rows"] == 5
    assert "mean(pm25)" in res["definition"] and "over 2 of 5 rows" in res["definition"]

    by_zone = store.query("a" * 32, QuerySpec(aggregates=[parse_aggregate("max:pm25")], group_by=["zone"], order_by="max(pm25)", descending=True))
    assert by_zone["rows"][0] == ["Delhi", 310.5] and [r[0] for r in by_zone["rows"]][:2] == ["Delhi", "Noida"]

    monthly = store.query("a" * 32, QuerySpec(aggregates=[parse_aggregate("mean:pm10")], group_by=["date:month"]))
    assert [r[0] for r in monthly["rows"]] == ["2024-11", "2024-12"]  # months in the dataset's own time zone
    assert monthly["columns"][0].startswith("date (month, UTC+05:30)")


def test_date_filters_and_row_selection_use_the_assumed_time_zone(store):
    store.load("b" * 32, table_from(CSV), "Asia/Kolkata")
    res = store.query("b" * 32, QuerySpec(select=["date", "station"], where=[parse_condition("date>=2024-11-02"), parse_condition("pm25>100")]))
    assert res["matched_rows"] == 2 and res["rows"][0][0] == "2024-11-02T00:00:00+05:30"
    contains = store.query("b" * 32, QuerySpec(select=["station"], where=[parse_condition("station contains Vihar")]))
    assert contains["matched_rows"] == 2


def test_invalid_queries_are_refused_with_a_reason(store):
    store.load("c" * 32, table_from(CSV), "UTC")
    for spec, code in [
        (QuerySpec(aggregates=[parse_aggregate("mean:nosuch")]), "unknown_column"),
        (QuerySpec(aggregates=[parse_aggregate("mean:station")]), "invalid_aggregate"),
        (QuerySpec(select=["pm25"], where=[parse_condition("station>5")]), "invalid_filter"),
        (QuerySpec(group_by=["zone"]), "invalid_group"),
        (QuerySpec(aggregates=[parse_aggregate("count")], group_by=["station:day"]), "invalid_group"),
    ]:
        with pytest.raises(KbError) as e:
            store.query("c" * 32, spec)
        assert e.value.code == code, (spec, e.value.message)
    with pytest.raises(KbError):
        parse_condition("no operator here")
    with pytest.raises(KbError):
        parse_aggregate("median:pm25")
    # a hostile column name or value is only ever a parameter or a validated identifier, never SQL
    with pytest.raises(KbError):
        store.query("c" * 32, QuerySpec(select=['pm25"; drop table datasets; --']))
    assert store.profile("c" * 32) is not None


def test_time_helpers():
    assert tz_minutes("Asia/Kolkata") == 330 and tz_minutes("+05:30") == 330 and tz_minutes("-03:00") == -180
    assert parse_time("2024-11-02", 330).isoformat() == "2024-11-01T18:30:00+00:00"
    assert parse_time("02-11-2024", 0).isoformat() == "2024-11-02T00:00:00+00:00"
    assert parse_time("20241102", 0) is None  # a bare number is not a date
    with pytest.raises(KbError):
        tz_minutes("Mars/Olympus")


# ---------------------------------------------------------------------------------------------- exact words
def test_exact_word_index_finds_names_and_numbers():
    idx = LexicalIndex([
        ("a:0", "a", "Anand Vihar station reported PM2.5 of 312 on the evening"),
        ("b:0", "b", "General guidance on particulate matter and health effects"),
        ("c:0", "c", "Mandir Marg station in Delhi, PM2.5 of 90"),
    ])
    hits = idx.search("Which station is Mandir Marg?", {"a", "b", "c"}, 5)
    assert hits[0].key == "c:0" and hits[0].coverage >= 0.6
    assert tokens("PM 2.5 and NO2") == ["pm25", "no2"]
    assert [h.key for h in idx.search("312", {"a", "b", "c"}, 5)] == ["a:0"]
    assert idx.search("Mandir", {"a"}, 5) == []  # a document filter is respected


async def test_a_passage_with_the_exact_words_is_admitted_below_the_similarity_threshold(tmp_path):
    filler = " ".join(f"filler{i}" for i in range(20))
    text = f"Mandir Marg {filler}"
    strict = KnowledgeBaseService(settings(tmp_path / "s", kb_min_score=0.45, kb_lexical_relax=0.0), embedder=FakeEmbedder())
    await ingest(strict, "n.txt", text, "project_documentation", title="Station note")
    assert (await strict.search("Mandir Marg")).status == "no_relevant_passages"

    hybrid = KnowledgeBaseService(settings(tmp_path / "h", kb_min_score=0.45, kb_lexical_relax=0.2), embedder=FakeEmbedder())
    rec = await ingest(hybrid, "n.txt", text, "project_documentation", title="Station note")
    res = await hybrid.search("Mandir Marg")
    assert res.status == "ok" and res.passages[0].document_id == rec.id and res.passages[0].score < 0.45  # displayed score is the cosine
    assert (await hybrid.search("Anand Vihar")).status == "no_relevant_passages"  # nothing matches: still refused


# ---------------------------------------------------------------------------------------------- metadata
def test_research_tags_for_text():
    m = text_meta("PM2.5 and ozone in Gurgaon and Delhi NCR during stubble burning; crop residue burning raises PM10. CO too.")
    assert {"pm25", "pm10", "o3", "co"} <= set(m["pollutants"])
    assert {"Gurugram", "Delhi", "NCR"} <= set(m["places"]) and "stubble burning" in m["topics"]
    assert text_meta("A cooking recipe about bread")["pollutants"] == []


async def test_documents_get_tags_and_tables_get_a_profile(tmp_path):
    kb = KnowledgeBaseService(settings(tmp_path), embedder=FakeEmbedder())
    note = await ingest(kb, "n.txt", "PM2.5 levels in Delhi rise with stubble burning and temperature inversion in November. " * 3,
                        "scientific_publication", title="Paper")
    table = await ingest(kb, "t.csv", CSV, "dataset", title="Readings")
    nm, tm = kb.document_meta(note.id), kb.document_meta(table.id)
    assert nm["kind"] == "document" and "pm25" in nm["pollutants"] and "Delhi" in nm["places"]
    assert tm["kind"] == "table" and tm["rows"] == 5 and tm["period_start"] == "2024-10-31T18:30:00Z"
    assert {"pm25", "pm10"} <= set(tm["pollutants"]) and tm["columns"][:2] == ["date", "station"]
    assert [d["title"] for d in kb.datasets()] == ["Readings"] and kb.dataset_profile(table.id)["rows"] == 5
    with pytest.raises(KbError):
        kb.dataset_profile(note.id)
    await kb.delete(table.id)
    assert kb.datasets() == [] and kb.document_meta(table.id) is None  # nothing left behind


# ---------------------------------------------------------------------------------------------- relationship
def lcg(seed):
    state = seed
    while True:
        state = (state * 1103515245 + 12345) % (2 ** 31)
        yield state / 2 ** 31


def make_history(path: Path, days: int, lag: int, with_effect: bool) -> list[tuple[date, float]]:
    """Hourly PM2.5 for 3 stations: mostly a base level plus (optionally) 0.9 * driver(t - lag), with noise."""
    rnd = lcg(7)
    start = date(2024, 1, 1)
    driver = [20 + 80 * next(rnd) for _ in range(days)]
    db = sqlite3.connect(path)
    db.execute("create table clean_air (station_id integer, pollutant text, label_utc text, value_std real, usable integer)")
    db.execute("create table stations (station_id integer primary key, zone text)")
    for sid, zone in [(1, "Delhi"), (2, "Delhi"), (3, "Noida")]:
        db.execute("insert into stations values (?, ?)", (sid, zone))
    prev = 100.0
    for d in range(days):
        eff = 0.9 * driver[d - lag] if with_effect and d >= lag else 0.0
        level = 0.35 * prev + 0.65 * (60 + eff) + 6 * (next(rnd) - 0.5)
        prev = level
        # One value per IST day, spread over 24 hourly UTC labels: IST day d starts at 18:30 UTC the day before.
        t0 = datetime(start.year, start.month, start.day, tzinfo=timezone.utc) + timedelta(days=d) - timedelta(hours=5, minutes=30)
        for h in range(24):
            label = (t0 + timedelta(hours=h)).strftime("%Y-%m-%dT%H:00:00Z")
            for sid in (1, 2, 3):
                db.execute("insert into clean_air values (?, 'pm25', ?, ?, 1)", (sid, label, level + (sid - 2) * 2))
    db.commit()
    db.close()
    return [(start + timedelta(days=d), driver[d]) for d in range(days)]


def csv_of(series: list[tuple[date, float]], name: str = "fires") -> str:
    return "date," + name + "\n" + "\n".join(f"{d.isoformat()},{v:.3f}" for d, v in series)


async def test_a_real_driver_is_detected_and_a_random_series_is_not(tmp_path):
    db = tmp_path / "history.sqlite"
    driver = make_history(db, days=240, lag=1, with_effect=True)
    kb = KnowledgeBaseService(settings(tmp_path, ml_history_db=str(db)), embedder=FakeEmbedder())
    real = await ingest(kb, "fires.csv", csv_of(driver), "dataset", title="Fire counts")
    out = await kb.relationship(real.id, "fires", "pm25")
    by_lag = {c["lag"]: c for c in out["correlations"]}
    assert out["resolution"] == "daily" and out["observations"]["days_used"] >= 238
    assert by_lag[1]["pearson"] > 0.6 and out["best_lag_by_abs_pearson"] == 1
    hc = out["heldout_check"]
    assert hc["status"] == "ok" and hc["chosen_lag_steps"] == 1 and hc["chosen_on"] == "training part only"
    assert hc["relative_change_vs_yesterday_only"] > 0.02 and "candidate feature" in hc["verdict"]
    assert "not changed" in out["not_applied"] and any("Correlation is not causation" in c for c in out["caveats"])

    rnd = lcg(99)
    noise = [(d, 100 * next(rnd)) for d, _ in driver]
    junk = await ingest(kb, "noise.csv", csv_of(noise, "noise"), "dataset", title="Unrelated numbers")
    out2 = await kb.relationship(junk.id, "noise", "pm25")
    assert abs(out2["correlations"][1]["pearson"]) < 0.3
    assert out2["heldout_check"]["status"] == "ok" and out2["heldout_check"]["relative_change_vs_yesterday_only"] < 0.02
    assert "no evidence" in out2["heldout_check"]["verdict"] or "worse" in out2["heldout_check"]["verdict"]


async def test_relationship_refuses_what_it_cannot_do_honestly(tmp_path):
    db = tmp_path / "history.sqlite"
    driver = make_history(db, days=40, lag=1, with_effect=True)
    kb = KnowledgeBaseService(settings(tmp_path, ml_history_db=str(db)), embedder=FakeEmbedder())
    t = await ingest(kb, "fires.csv", csv_of(driver), "dataset", title="Fire counts")
    for column, pollutant, code in [("fires", "benzene", "invalid_pollutant"), ("nosuch", "pm25", "unknown_column")]:
        with pytest.raises(KbError) as e:
            await kb.relationship(t.id, column, pollutant)
        assert e.value.code == code
    notime = await ingest(kb, "plain.csv", "a,b\n1,2\n3,4\n5,6\n7,8\n", "dataset", title="No dates")
    with pytest.raises(KbError) as e:
        await kb.relationship(notime.id, "a", "pm25")
    assert e.value.code == "no_time_column"
    missing = KnowledgeBaseService(settings(tmp_path / "x", ml_history_db=str(tmp_path / "none.sqlite")), embedder=FakeEmbedder())
    t2 = await ingest(missing, "fires.csv", csv_of(driver), "dataset", title="Fire counts")
    with pytest.raises(KbError) as e:
        await missing.relationship(t2.id, "fires", "pm25")
    assert e.value.code == "no_observations"


def test_statistics_helpers():
    x = [1.0, 2, 3, 4, 5, 6]
    assert research.pearson(x, [2 * v for v in x]) == pytest.approx(1.0)
    assert research.spearman(x, [v ** 3 for v in x]) == pytest.approx(1.0)
    assert research.pearson([1, 1, 1], [1, 2, 3]) is None  # a constant series has no correlation
    beta = research.ols([[v] for v in x], [3 + 2 * v for v in x])
    assert beta == pytest.approx([3.0, 2.0])
    lo, hi = research.conf_interval(0.5, 50)
    assert lo < 0.5 < hi


# ---------------------------------------------------------------------------------------------- assistant tool
async def test_query_dataset_tool_lists_then_computes_with_a_real_source(tmp_path):
    kb = KnowledgeBaseService(settings(tmp_path), embedder=FakeEmbedder())
    t = await ingest(kb, "stations.csv", CSV, "dataset", title="NCR readings")
    ex = executor(kb)

    listing = await ex.run("query_dataset", {})
    assert listing.ok and listing.data["status"] == "datasets" and listing.data["datasets"][0]["document"] == "NCR readings"
    assert listing.data["untrusted_text"] is True

    out = await ex.run("query_dataset", {"document": "readings", "aggregates": ["mean:pm25", "max:pm25"], "where": ["zone=Delhi"]})
    assert out.ok and out.data["status"] == "ok" and out.data["rows"] == [[295.25, 310.5]] and out.data["matched_rows"] == 2
    assert out.sources[0].id == "K1" and out.sources[0].category == "Dataset (table)" and out.sources[0].document_id == t.id
    assert "computed from the whole uploaded table" in out.data["notes"][0]

    grouped = await ex.run("query_dataset", {"document": "readings", "aggregates": ["count"], "group_by": ["zone"], "order_by": "count", "descending": True})
    assert grouped.ok and grouped.data["rows"][0][1] >= grouped.data["rows"][-1][1] and grouped.data["untrusted_text"] is True

    bad = await ex.run("query_dataset", {"document": "readings", "aggregates": ["mean:nosuch"]})
    assert not bad.ok and bad.arg_error and "no column" in bad.error.lower()
    missing = await ex.run("query_dataset", {"document": "weather balloon"})
    assert missing.data["status"] == "document_not_found"


async def test_query_dataset_without_any_table_says_so(tmp_path):
    kb = KnowledgeBaseService(settings(tmp_path), embedder=FakeEmbedder())
    out = await executor(kb).run("query_dataset", {})
    assert out.ok and out.data["status"] == "no_datasets"


async def test_a_same_time_series_counts_only_when_marked_known_in_advance(tmp_path):
    db = tmp_path / "history.sqlite"
    driver = make_history(db, days=240, lag=0, with_effect=True)  # pollution responds to the SAME day's driver
    kb = KnowledgeBaseService(settings(tmp_path, ml_history_db=str(db)), embedder=FakeEmbedder())
    t = await ingest(kb, "wx.csv", csv_of(driver, "forecast_ventilation"), "dataset", title="Forecast ventilation")
    earlier_only = await kb.relationship(t.id, "forecast_ventilation", "pm25")
    assert earlier_only["known_in_advance"] is False and earlier_only["heldout_check"]["chosen_lag_steps"] >= 1
    assert "earlier steps only" in earlier_only["heldout_check"]["assumption"]
    ahead = await kb.relationship(t.id, "forecast_ventilation", "pm25", known_in_advance=True)
    hc = ahead["heldout_check"]
    assert ahead["known_in_advance"] is True and hc["chosen_lag_steps"] == 0
    assert hc["relative_change_vs_yesterday_only"] > 0.02 and "known when the forecast is made" in hc["assumption"]
    assert hc["relative_change_vs_yesterday_only"] > earlier_only["heldout_check"]["relative_change_vs_yesterday_only"]
