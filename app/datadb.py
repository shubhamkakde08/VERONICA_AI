"""Access to YOUR business MySQL database — strictly read-only.

Three layers of protection:
  1. Connect with a MySQL user that only has SELECT grants (see .env.example).
  2. Every query is parsed with sqlglot: one statement, SELECT only, no
     INTO OUTFILE / LOAD_FILE / SLEEP etc., and only tables the user's role allows.
  3. The session is set READ ONLY with a max execution time.
"""
from __future__ import annotations

import datetime as dt
import decimal
import re
import time

import sqlglot
from sqlalchemy import create_engine, inspect, text
from sqlglot import exp

from . import config
from .access import table_ok

engine = create_engine(config.DATA_DB_URL, pool_pre_ping=True, pool_recycle=1800, future=True)
DIALECT = "mysql" if engine.dialect.name in ("mysql", "mariadb") else engine.dialect.name

BLOCKED_FUNCTIONS = {"load_file", "sleep", "benchmark", "get_lock", "release_lock",
                     "sys_exec", "sys_eval", "pg_sleep"}
BLOCKED_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
                 exp.Command, exp.Merge, exp.TruncateTable, exp.Grant, exp.Into)


class SQLRejected(Exception):
    pass


# ------------------------------------------------------------------ schema
# The table list and column details are cached, but only for SCHEMA_CACHE_SECONDS, so tables
# created or re-created by the Oracle sync show up without restarting the bot.
SCHEMA_CACHE_SECONDS = 300
_cache: dict = {"tables": None, "at": 0.0, "describe": {}}


def _all_tables() -> tuple[str, ...]:
    now = time.time()
    if _cache["tables"] is None or now - _cache["at"] > SCHEMA_CACHE_SECONDS:
        insp = inspect(engine)
        names = insp.get_table_names() + insp.get_view_names()
        # hide the sync script's temporary copies
        names = [n for n in names if not n.lower().endswith(("__new", "__old"))]
        _cache.update(tables=tuple(sorted(names)), at=now, describe={})
    return _cache["tables"]


def refresh_schema_cache() -> None:
    _cache.update(tables=None, at=0.0, describe={})


def _denied(allowed: list[str]) -> set[str]:
    """'!TABLE' entries = never allowed for this role (private views such as employee master)."""
    return {a[1:].lower() for a in allowed if a.startswith("!")}


def _visible(allowed: list[str]) -> list[str]:
    return [t for t in _all_tables() if table_ok(t, allowed)]


def list_tables(allowed: list[str], search: str = "") -> list[str]:
    names = _visible(allowed)
    if search:
        s = search.lower()
        names = [n for n in names if s in n.lower()]
    return names


def _describe(table: str) -> dict:
    hit = _cache["describe"].get(table)
    if hit:
        return hit
    insp = inspect(engine)
    cols = [{"name": c["name"], "type": str(c["type"]),
             **({"comment": c["comment"]} if c.get("comment") else {})}
            for c in insp.get_columns(table)]
    try:
        fks = [{"columns": f["constrained_columns"], "ref_table": f["referred_table"],
                "ref_columns": f["referred_columns"]} for f in insp.get_foreign_keys(table)]
    except Exception:
        fks = []
    try:
        comment = (insp.get_table_comment(table) or {}).get("text") or ""
    except Exception:
        comment = ""
    out = {"table": table, "comment": comment, "columns": cols, "foreign_keys": fks}
    _cache["describe"][table] = out
    return out


def describe_tables(names: list[str], allowed: list[str]) -> list[dict]:
    visible = {t.lower(): t for t in _visible(allowed)}
    if any(n.lower() not in visible for n in names):      # maybe just created by the sync
        refresh_schema_cache()
        visible = {t.lower(): t for t in _visible(allowed)}
    out = []
    for n in names[:15]:
        real = visible.get(n.lower())
        out.append(_describe(real) if real else {"table": n, "error": "not found or not allowed"})
    return out


def last_sync():
    """Newest table creation time in the replica (the sync re-creates tables) - shown as 'ERP synced HH:MM'."""
    if DIALECT != "mysql":
        return None
    try:
        with engine.connect() as c:
            return c.execute(text("SELECT MAX(CREATE_TIME) FROM information_schema.tables WHERE table_schema = DATABASE()")).scalar()
    except Exception:
        return None


# ------------------------------------------------------------------ validation
def validate_select(sql: str, allowed: list[str]) -> str:
    sql = sql.strip().rstrip(";").strip()
    try:
        statements = sqlglot.parse(sql, read=DIALECT)
    except sqlglot.errors.ParseError as e:
        raise SQLRejected(f"SQL could not be parsed: {e}") from e
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise SQLRejected("Exactly one SQL statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise SQLRejected("Only SELECT queries are allowed (read-only bot).")
    for node in tree.walk():
        if isinstance(node, BLOCKED_NODES):
            raise SQLRejected(f"{type(node).__name__} is not allowed.")
        if isinstance(node, exp.Func):
            fname = (node.sql_name() if not isinstance(node, exp.Anonymous) else node.name).lower()
            if fname in BLOCKED_FUNCTIONS:
                raise SQLRejected(f"Function {fname} is not allowed.")
    low = sql.lower()
    if "outfile" in low or "dumpfile" in low:
        raise SQLRejected("INTO OUTFILE is not allowed.")

    deny = _denied(allowed)
    if deny:   # checked on every table reference, even one hidden behind a CTE of the same name
        for t in tree.find_all(exp.Table):
            if t.name and not table_ok(t.name, ["*"] + ["!" + d for d in deny]):
                raise SQLRejected(f"PRIVATE: '{t.name}' contains private data your role cannot see.")
        cte_l = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
        if any(not table_ok(c, ["*"] + ["!" + d for d in deny]) for c in cte_l):
            raise SQLRejected("PRIVATE: that name is reserved for a private view.")
    if "*" not in allowed:
        cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
        real = {t.lower() for t in _all_tables()}
        if any(not table_ok(c, allowed) for c in cte_names & real):      # WITH secret AS (SELECT * FROM secret) must not hide the real table
            raise SQLRejected("A WITH name may not reuse the name of a table your role cannot read.")
        for t in tree.find_all(exp.Table):
            name = t.name.lower()
            if name and name not in cte_names and not table_ok(name, allowed):
                raise SQLRejected(f"Your role is not allowed to read table '{t.name}'.")
    return sql


# ------------------------------------------------------------------ execution
def _jsonable(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace")
    return v


def run_select(sql: str, allowed: list[str], max_rows: int | None = None, timeout: int | None = None) -> dict:
    sql = validate_select(sql, allowed)
    max_rows = max_rows or config.MAX_ROWS
    tmo = int(timeout or config.QUERY_TIMEOUT_SECONDS)
    start = time.time()
    with engine.connect() as conn:
        if DIALECT == "mysql":
            conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
            try:   # MySQL; MariaDB uses max_statement_time instead
                conn.execute(text(f"SET SESSION MAX_EXECUTION_TIME={tmo * 1000}"))
            except Exception:
                conn.rollback()
                conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
                try:
                    conn.execute(text(f"SET SESSION max_statement_time={tmo}"))
                except Exception:
                    conn.rollback()
        result = conn.execute(text(sql))
        columns = list(result.keys())
        raw = result.fetchmany(max_rows + 1)
        conn.rollback()
    truncated = len(raw) > max_rows
    rows = [[_jsonable(v) for v in r] for r in raw[:max_rows]]
    return {"columns": columns, "rows": rows, "row_count": len(rows),
            "truncated": truncated, "seconds": round(time.time() - start, 2), "sql": sql}


# ------------------------------------------------------------------ schema digest for the prompt
_digest: dict = {}
DIGEST_MAX_CHARS = 45000


def schema_digest(allowed: list[str]) -> str:
    """Every view this role may read, with its columns and comments - put in the (cached) system prompt so the
    model can write SQL straight away instead of spending round trips on list_tables / describe_tables."""
    key = ("|".join(sorted(allowed)), _cache["at"])
    if key in _digest:
        return _digest[key]
    try:
        names = list(_visible(allowed))
    except Exception:
        return ""
    names.sort(key=lambda n: (not n.upper().startswith("VIEW_"), n.upper()))
    parts, size = [], 0
    for n in names[:60]:
        try:
            d = _describe(n)
        except Exception:
            continue
        cols = []
        for c in d["columns"]:
            t = re.sub(r"\(.*", "", c["type"]).lower()
            cm = (c.get("comment") or "").replace("\n", " ").strip()
            cols.append(f"{c['name']} {t}" + (f" -- {cm[:90]}" if cm else ""))
        block = f"### {n}" + (f" ({d['comment'][:120]})" if d.get("comment") else "") + "\n" + "\n".join(cols)
        if size + len(block) > DIGEST_MAX_CHARS:
            parts.append(f"### {n}\n(columns not listed - use describe_tables)")
            continue
        parts.append(block)
        size += len(block)
    out = "\n\n".join(parts)
    for k in [k for k in _digest if k[1] != key[1]]:
        _digest.pop(k, None)
    _digest[key] = out
    return out
