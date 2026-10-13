"""Uploaded CSV files as real, queryable tables (`KB_DIR/tables.sqlite`), plus per-document research metadata.

Why: semantic search over table rows can find *which rows look like the question* but cannot compute: a mean, a count or a
maximum needs every row. Each CSV is therefore also loaded into SQLite with typed columns, and the assistant and the API
query it with a small, validated specification (never raw SQL from the model or the user).

Everything is conservative about time and units:
* a column is typed `integer`, `real`, `datetime` or `text` only if EVERY non-empty value parses as that type;
* timestamps without an offset are read in `KB_DATASET_TIMEZONE` (default Asia/Kolkata) and stored as UTC; the assumption is
  written into the profile and into every query result, because a wrong time zone silently shifts a series by hours;
* units are never inferred or converted. A column's name is all the app knows about it.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.kb.types import KbError, Table

NULL_TOKENS = {"", "na", "n/a", "nan", "null", "none", "-", "--", "?", "nil"}
_TZ_NAMES = {"asia/kolkata": 330, "asia/calcutta": 330, "ist": 330, "utc": 0, "gmt": 0, "z": 0}
_OFFSET = re.compile(r"^([+-])(\d{1,2}):?(\d{2})$")
_DMY = re.compile(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
_TIME_CHARS = re.compile(r"[-/:]")
_SQL_NAME = re.compile(r"^[A-Za-z0-9_]{1,64}$")
MAX_QUERY_ROWS = 200
BUCKETS = ("hour", "day", "month", "year")

POLLUTANT_COLUMNS = {
    "pm25": re.compile(r"pm\s*2[._]?5|pm25|fine\s*particulate", re.I),
    "pm10": re.compile(r"pm\s*10|pm10", re.I),
    "no2": re.compile(r"(?<![a-z0-9])no\s*2(?![a-z0-9])|nitrogen\s*dioxide", re.I),
    "so2": re.compile(r"(?<![a-z0-9])so\s*2(?![a-z0-9])|sulphur\s*dioxide|sulfur\s*dioxide", re.I),
    "o3": re.compile(r"(?<![a-z0-9])o\s*3(?![a-z0-9])|ozone", re.I),
    "co": re.compile(r"(?<![a-z0-9])co(?![a-z0-9])|carbon\s*monoxide", re.I),
}
_STATION_NAME = re.compile(r"station|site|monitor|location|city|place", re.I)
_ZONE_NAME = re.compile(r"zone|region|district|area|state", re.I)


# ---------------------------------------------------------------------------------------------- time
def tz_minutes(name: str | None) -> int:
    key = (name or "Asia/Kolkata").strip()
    if key.lower() in _TZ_NAMES:
        return _TZ_NAMES[key.lower()]
    m = _OFFSET.match(key)
    if m:
        total = int(m.group(2)) * 60 + int(m.group(3))
        return total if m.group(1) == "+" else -total
    raise KbError("invalid_timezone", f"Unknown time zone '{key}'. Use Asia/Kolkata, UTC or an offset such as +05:30.", 422)


def tz_label(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    return f"UTC{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def parse_time(value: str, tz_min: int) -> datetime | None:
    """A timestamp as aware UTC, or None. Offset-free values are read in the dataset's assumed time zone."""
    s = value.strip()
    if not s or not _TIME_CHARS.search(s):  # a bare number such as 20240105 is not treated as a date
        return None
    m = _DMY.match(s)
    try:
        if m:
            d, mo, y, h, mi, se = m.groups()
            dt = datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(se or 0))
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(minutes=tz_min)))
    return dt.astimezone(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_iso(utc_iso: str, tz_min: int) -> str:
    dt = datetime.strptime(utc_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(minutes=tz_min))).isoformat()


# ---------------------------------------------------------------------------------------------- typing
def _is_int(s: str) -> bool:
    if not re.fullmatch(r"[+-]?\d{1,18}", s):
        return False
    digits = s.lstrip("+-")
    return not (len(digits) > 1 and digits.startswith("0"))  # "007" is an identifier, not a number


def _is_float(s: str) -> bool:
    if not re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", s):
        return False
    digits = s.lstrip("+-")
    return not (len(digits) > 1 and digits.startswith("0") and not digits.startswith("0."))


def infer_type(values: list[str], tz_min: int) -> str:
    vals = [v for v in values if v.strip().lower() not in NULL_TOKENS]
    if not vals:
        return "text"
    vals = [v.strip() for v in vals]
    if all(_is_int(v) for v in vals):
        return "integer"
    if all(_is_float(v) or _is_int(v) for v in vals):
        return "real"
    if all(parse_time(v, tz_min) is not None for v in vals):
        return "datetime"
    return "text"


def _round(x: float | None) -> float | None:
    return None if x is None else round(float(x), 4)


def _resolution(times: list[datetime]) -> str | None:
    uniq = sorted(set(times))
    if len(uniq) < 3:
        return None
    gap = median((b - a).total_seconds() for a, b in zip(uniq, uniq[1:]))
    if gap <= 5400:
        return "hourly"
    if 72000 <= gap <= 100800:
        return "daily"
    return "irregular"


# ---------------------------------------------------------------------------------------------- query spec
class Cond(BaseModel):
    column: str
    op: Literal["=", "!=", ">", ">=", "<", "<=", "contains", "in"]
    value: Any


class Agg(BaseModel):
    fn: Literal["count", "count_distinct", "mean", "sum", "min", "max"]
    column: str | None = None


class QuerySpec(BaseModel):
    select: list[str] = Field(default_factory=list, max_length=20)
    aggregates: list[Agg] = Field(default_factory=list, max_length=8)
    where: list[Cond] = Field(default_factory=list, max_length=10)
    group_by: list[str] = Field(default_factory=list, max_length=3)  # "col" or "datetime_col:day|month|year|hour"
    order_by: str | None = None
    descending: bool = False
    limit: int = Field(50, ge=1, le=MAX_QUERY_ROWS)


def parse_condition(text: str) -> Cond:
    """'pm25>=100', 'zone=Delhi', 'name contains Vihar', 'date>=2024-11-01' -> Cond. Used by the assistant tool."""
    m = re.match(r"^\s*(.+?)\s*(>=|<=|!=|=|>|<)\s*(.+?)\s*$", text)
    if m:
        return Cond(column=m.group(1).strip().strip("\"'"), op=m.group(2), value=m.group(3).strip().strip("\"'"))  # type: ignore[arg-type]
    m = re.match(r"^\s*(.+?)\s+contains\s+(.+?)\s*$", text, re.I)
    if m:
        return Cond(column=m.group(1).strip().strip("\"'"), op="contains", value=m.group(2).strip().strip("\"'"))
    raise KbError("invalid_filter", f"Cannot read the filter '{text[:60]}'. Use the form column>=value, column=value or column contains value.", 422)


def parse_aggregate(text: str) -> Agg:
    """'mean:pm25', 'max:pm25', 'count' -> Agg."""
    t = text.strip()
    if ":" not in t:
        fn, col = t.lower(), None
    else:
        fn, col = (p.strip() for p in t.split(":", 1))
        fn = fn.lower()
    fn = {"avg": "mean", "average": "mean", "maximum": "max", "minimum": "min", "distinct": "count_distinct"}.get(fn, fn)
    try:
        return Agg(fn=fn, column=col or None)  # type: ignore[arg-type]
    except ValidationError:
        raise KbError("invalid_aggregate", f"Unknown aggregate '{text[:40]}'. Use count, count_distinct, mean, sum, min or max, "
                                           "for example mean:pm25.", 422) from None


# ---------------------------------------------------------------------------------------------- store
SCHEMA = """
create table if not exists datasets (doc_id text primary key, profile text not null, loaded_at text not null);
create table if not exists doc_meta (doc_id text primary key, meta text not null);
"""


class DatasetStore:
    def __init__(self, path: Path | str):
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    # ---- meta ----
    def set_meta(self, doc_id: str, meta: dict) -> None:
        with self._lock:
            self._db.execute("insert or replace into doc_meta (doc_id, meta) values (?, ?)", (doc_id, json.dumps(meta)))
            self._db.commit()

    def get_meta(self, doc_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("select meta from doc_meta where doc_id = ?", (doc_id,)).fetchone()
        return json.loads(row["meta"]) if row else None

    # ---- tables ----
    @staticmethod
    def _table(doc_id: str) -> str:
        if not _SQL_NAME.match(doc_id):
            raise KbError("invalid_document", "Invalid document id.", 422)
        return f"t_{doc_id}"

    def load(self, doc_id: str, table: Table, tz_name: str) -> dict:
        """Create (or replace) the typed table for a document and return its profile."""
        tz_min = tz_minutes(tz_name)
        name = self._table(doc_id)
        n_cols = len(table.header)
        raw_cols = [[(r[i] if i < len(r) else "") for r in table.rows] for i in range(n_cols)]
        types = [infer_type(col, tz_min) for col in raw_cols]
        sql_names = [f"c{i + 1}" for i in range(n_cols)]
        profiles: list[dict] = []
        converted: list[list[Any]] = []
        times_by_col: dict[int, list[datetime]] = {}
        for i, (col, typ) in enumerate(zip(raw_cols, types)):
            vals: list[Any] = []
            for v in col:
                s = v.strip()
                if s.lower() in NULL_TOKENS:
                    vals.append(None)
                elif typ == "integer":
                    vals.append(int(s))
                elif typ == "real":
                    vals.append(float(s))
                elif typ == "datetime":
                    dt = parse_time(s, tz_min)
                    vals.append(to_iso(dt))  # type: ignore[arg-type]
                    times_by_col.setdefault(i, []).append(dt)  # type: ignore[arg-type]
                else:
                    vals.append(s[:300])
            converted.append(vals)
            present = [x for x in vals if x is not None]
            p: dict = {"name": table.header[i], "sql": sql_names[i], "type": typ, "nulls": len(vals) - len(present)}
            if typ in ("integer", "real") and present:
                p.update(min=_round(min(present)), max=_round(max(present)), mean=_round(sum(present) / len(present)))
            elif typ == "datetime" and present:
                p.update(min=min(present), max=max(present))
            elif typ == "text" and present:
                distinct = sorted(set(present))
                p["distinct"] = len(distinct)
                p["examples"] = distinct[:8]
            profiles.append(p)

        with self._lock:
            self._db.execute(f'drop table if exists "{name}"')
            sql_type = {"integer": "INTEGER", "real": "REAL", "datetime": "TEXT", "text": "TEXT"}
            self._db.execute(f'create table "{name}" ({", ".join(f"{c} {sql_type[t]}" for c, t in zip(sql_names, types))})')
            rows = list(zip(*converted)) if converted else []
            self._db.executemany(f'insert into "{name}" values ({", ".join("?" * n_cols)})', rows)
            self._db.commit()

        warnings: list[str] = list(table.warnings)
        time_idx = next((i for i, t in enumerate(types) if t == "datetime"), None)
        profile: dict = {
            "rows": len(table.rows), "columns": profiles, "time_column": None, "time_start": None, "time_end": None,
            "resolution": None, "timezone_assumed": f"{tz_name} ({tz_label(tz_min)})", "station_column": None, "zone_column": None,
            "pollutant_columns": {}, "warnings": warnings,
        }
        if time_idx is not None:
            ts = times_by_col[time_idx]
            profile.update(time_column=table.header[time_idx], time_start=to_iso(min(ts)), time_end=to_iso(max(ts)), resolution=_resolution(ts))
            warnings.append(f"Timestamps without an offset were read as {tz_name} ({tz_label(tz_min)}). Set KB_DATASET_TIMEZONE if that is wrong.")
        else:
            warnings.append("No column could be read as a date or time, so this table cannot be aligned with observations.")
        for key, rx in POLLUTANT_COLUMNS.items():
            hit = next((p["name"] for p in profiles if p["type"] in ("integer", "real") and rx.search(p["name"])), None)
            if hit:
                profile["pollutant_columns"][key] = hit
        profile["station_column"] = next((p["name"] for p in profiles if p["type"] == "text" and _STATION_NAME.search(p["name"])), None)
        profile["zone_column"] = next((p["name"] for p in profiles if p["type"] == "text" and _ZONE_NAME.search(p["name"])), None)
        with self._lock:
            self._db.execute("insert or replace into datasets (doc_id, profile, loaded_at) values (?, ?, ?)",
                             (doc_id, json.dumps(profile), to_iso(datetime.now(timezone.utc))))
            self._db.commit()
        return profile

    def profile(self, doc_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("select profile from datasets where doc_id = ?", (doc_id,)).fetchone()
        return json.loads(row["profile"]) if row else None

    def drop(self, doc_id: str) -> None:
        name = self._table(doc_id)
        with self._lock:
            self._db.execute(f'drop table if exists "{name}"')
            self._db.execute("delete from datasets where doc_id = ?", (doc_id,))
            self._db.execute("delete from doc_meta where doc_id = ?", (doc_id,))
            self._db.commit()

    def dataset_ids(self) -> list[str]:
        with self._lock:
            return [r["doc_id"] for r in self._db.execute("select doc_id from datasets").fetchall()]

    # ---- querying ----
    @staticmethod
    def _col(profile: dict, name: str) -> dict:
        wanted = name.strip().lower()
        for c in profile["columns"]:
            if c["name"].lower() == wanted:
                return c
        available = ", ".join(c["name"] for c in profile["columns"][:30])
        raise KbError("unknown_column", f"There is no column '{name[:60]}'. Columns: {available}.", 422)

    def query(self, doc_id: str, spec: QuerySpec) -> dict:
        profile = self.profile(doc_id)
        if profile is None:
            raise KbError("not_a_dataset", "This document is not a table, so it cannot be queried.", 422)
        tz_min = tz_minutes(profile["timezone_assumed"].split(" (")[0])
        table = self._table(doc_id)
        params: list[Any] = []

        # WHERE
        clauses: list[str] = []
        for cond in spec.where:
            col = self._col(profile, cond.column)
            sql = col["sql"]
            op = cond.op
            if op == "in":
                values = cond.value if isinstance(cond.value, list) else [v.strip() for v in str(cond.value).split(",")]
                if not values or len(values) > 50:
                    raise KbError("invalid_filter", "'in' needs between 1 and 50 values.", 422)
                coerced = [self._coerce(col, v, tz_min) for v in values]
                clauses.append(f"{sql} in ({', '.join('?' * len(coerced))})")
                params.extend(coerced)
            elif op == "contains":
                if col["type"] != "text":
                    raise KbError("invalid_filter", f"'contains' works on text columns; '{col['name']}' is {col['type']}.", 422)
                esc = str(cond.value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                clauses.append(f"{sql} like ? escape '\\'")
                params.append(f"%{esc}%")
            else:
                if col["type"] == "text" and op not in ("=", "!="):
                    raise KbError("invalid_filter", f"'{op}' works on numbers and dates; '{col['name']}' is text.", 422)
                clauses.append(f"{sql} {op} ?")
                params.append(self._coerce(col, cond.value, tz_min))
        where = f" where {' and '.join(clauses)}" if clauses else ""

        # SELECT / GROUP BY
        out_cols: list[str] = []
        exprs: list[str] = []
        out_kinds: list[str] = []  # how to present each output column: "datetime" -> local time
        group_exprs: list[str] = []
        for g in spec.group_by:
            name, _, bucket = g.partition(":")
            col = self._col(profile, name)
            if bucket:
                if col["type"] != "datetime" or bucket not in BUCKETS:
                    raise KbError("invalid_group", f"'{g}': bucketing works on a date column with one of {', '.join(BUCKETS)}.", 422)
                width = {"hour": 13, "day": 10, "month": 7, "year": 4}[bucket]
                expr = f"substr(datetime({col['sql']}, '{tz_min:+d} minutes'), 1, {width})"
                label = f"{col['name']} ({bucket}, {tz_label(tz_min)})"
            else:
                expr, label = col["sql"], col["name"]
            group_exprs.append(expr)
            exprs.append(expr)
            out_cols.append(label)
            out_kinds.append("datetime" if col["type"] == "datetime" and not bucket else "plain")

        if spec.aggregates:
            for c in spec.select:
                if c.lower() not in {g.partition(":")[0].lower() for g in spec.group_by}:
                    raise KbError("invalid_select", f"'{c}' must be in group_by when aggregates are used.", 422)
            for a in spec.aggregates:
                label, expr, kind = self._aggregate(profile, a)
                exprs.append(expr)
                out_cols.append(label)
                out_kinds.append(kind)
            sql = f'select {", ".join(exprs)} from "{table}"{where}'
            if group_exprs:
                sql += f" group by {', '.join(group_exprs)}"
        else:
            if spec.group_by:
                raise KbError("invalid_group", "group_by needs at least one aggregate (for example count or mean:pm25).", 422)
            cols = spec.select or [c["name"] for c in profile["columns"][:20]]
            exprs, out_cols, out_kinds = [], [], []
            for c in cols:
                col = self._col(profile, c)
                exprs.append(col["sql"])
                out_cols.append(col["name"])
                out_kinds.append("datetime" if col["type"] == "datetime" else "plain")
            sql = f'select {", ".join(exprs)} from "{table}"{where}'

        # ORDER BY: an output column by name or position; grouped output defaults to the group keys.
        if spec.order_by:
            key = spec.order_by.strip().lower()
            idx = next((i for i, c in enumerate(out_cols) if c.lower() == key or c.lower().startswith(key + " ")), None)
            if idx is None:
                raise KbError("invalid_order", f"order_by must be one of the output columns: {', '.join(out_cols)}.", 422)
            sql += f" order by {idx + 1} {'desc' if spec.descending else 'asc'}"
        elif group_exprs:
            sql += " order by " + ", ".join(str(i + 1) for i in range(len(group_exprs)))
        sql += f" limit {spec.limit + 1}"

        with self._lock:
            matched = self._db.execute(f'select count(*) from "{table}"{where}', params).fetchone()[0]
            fetched = self._db.execute(sql, params).fetchall()
        truncated = len(fetched) > spec.limit
        rows = []
        for r in fetched[: spec.limit]:
            row = []
            for v, kind in zip(r, out_kinds):
                if kind == "datetime" and isinstance(v, str) and v.endswith("Z"):
                    v = local_iso(v, tz_min)
                row.append(_round(v) if isinstance(v, float) else v)
            rows.append(row)
        return {
            "columns": out_cols, "rows": rows, "matched_rows": matched, "returned_rows": len(rows), "truncated": truncated,
            "dataset_rows": profile["rows"], "timezone": f"{profile['timezone_assumed']}",
            "definition": self._describe(spec, matched, profile["rows"]),
        }

    @staticmethod
    def _coerce(col: dict, value: Any, tz_min: int) -> Any:
        s = str(value).strip()
        try:
            if col["type"] == "integer":
                return int(float(s)) if re.fullmatch(r"[+-]?\d+(\.0+)?", s) else float(s)
            if col["type"] == "real":
                return float(s)
        except ValueError:
            raise KbError("invalid_filter", f"'{s[:40]}' is not a number, but '{col['name']}' is numeric.", 422) from None
        if col["type"] == "datetime":
            dt = parse_time(s, tz_min)
            if dt is None:
                raise KbError("invalid_filter", f"'{s[:40]}' is not a date or time (use YYYY-MM-DD or YYYY-MM-DDTHH:MM).", 422)
            return to_iso(dt)
        return s

    def _aggregate(self, profile: dict, a: Agg) -> tuple[str, str, str]:
        if a.fn == "count" and not a.column:
            return "count", "count(*)", "plain"
        if not a.column:
            raise KbError("invalid_aggregate", f"'{a.fn}' needs a column, for example {a.fn}:pm25.", 422)
        col = self._col(profile, a.column)
        label = f"{a.fn}({col['name']})"
        if a.fn == "count":
            return label, f"count({col['sql']})", "plain"
        if a.fn == "count_distinct":
            return label, f"count(distinct {col['sql']})", "plain"
        if a.fn in ("mean", "sum"):
            if col["type"] not in ("integer", "real"):
                raise KbError("invalid_aggregate", f"'{a.fn}' needs a numeric column; '{col['name']}' is {col['type']}.", 422)
            return label, f"{'avg' if a.fn == 'mean' else 'sum'}({col['sql']})", "plain"
        return label, f"{a.fn}({col['sql']})", "datetime" if col["type"] == "datetime" else "plain"

    @staticmethod
    def _describe(spec: QuerySpec, matched: int, total: int) -> str:
        parts = []
        if spec.aggregates:
            parts.append(", ".join(f"{a.fn}({a.column})" if a.column else a.fn for a in spec.aggregates))
        else:
            parts.append("rows" + (f" [{', '.join(spec.select)}]" if spec.select else ""))
        if spec.where:
            parts.append("where " + " and ".join(f"{c.column} {c.op} {c.value}" for c in spec.where))
        if spec.group_by:
            parts.append("grouped by " + ", ".join(spec.group_by))
        parts.append(f"over {matched:,} of {total:,} rows")
        return " ".join(parts)

    # ---- series for research ----
    def series(self, doc_id: str, time_column: str, value_column: str) -> list[tuple[datetime, float]]:
        profile = self.profile(doc_id)
        if profile is None:
            raise KbError("not_a_dataset", "This document is not a table.", 422)
        tcol, vcol = self._col(profile, time_column), self._col(profile, value_column)
        if tcol["type"] != "datetime":
            raise KbError("no_time_column", f"'{tcol['name']}' is not a date or time column.", 422)
        if vcol["type"] not in ("integer", "real"):
            raise KbError("invalid_column", f"'{vcol['name']}' is not numeric.", 422)
        with self._lock:
            rows = self._db.execute(
                f'select {tcol["sql"]} t, {vcol["sql"]} v from "{self._table(doc_id)}" where t is not null and v is not null order by t'
            ).fetchall()
        return [(datetime.strptime(r["t"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc), float(r["v"])) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._db.close()
