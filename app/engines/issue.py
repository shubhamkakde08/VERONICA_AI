"""Issue / Costing dashboard - store issues by plant, department, cost centre, equipment, item.

Source: VIEW_ISSUE_ENGINE_PBI (one row per issue line; same columns as the ERP issue export the
'Issue_Dashboard_v3.html' generator reads: VRDATE, VRNO, DEPT_NAME, PLANT_NAME, DIV_CODE, ITEM_GROUP,
COST_NAME, EQPT_NAME, ITEM_CODE, ITEM_NAME, UM, BATCH_NO, QTY_ISSUED, RATE, VAL_ISSUED, VR_MONTH).

Flow: SQL rows of the period -> division lock (U1/U2) and plant lock (user's PLANT_NAME list) applied HERE,
      on the server -> KPI cards / tables -> the generator HTML opened with these rows (start(rows.map(norm))).
Check: VERONICA's total = a separate SQL SUM(VAL_ISSUED) over the same period."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from .. import config, datadb

ENGINE = "issue"
DEFAULT_SOURCE = "VIEW_ISSUE_ENGINE_PBI"
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "dashboards" / "issue_dashboard_v4.html"


class EngineError(Exception):
    pass


# the generator's column names (after its norm(): upper case, spaces/dots -> _) and accepted view names
COLS = {
    "VRDATE": ["VRDATE", "VR_DATE", "ISSUE_DATE", "DOC_DATE"],
    "VR_MONTH": ["VR_MONTH", "MONTH"],
    "VRNO": ["VRNO", "VR_NO", "ISSUE_NO", "DOC_NO"],
    "DEPT_NAME": ["DEPT_NAME", "DEPARTMENT", "DEPT"],
    "PLANT_NAME": ["PLANT_NAME", "PLANT"],
    "DIV_CODE": ["DIV_CODE", "DIVISION", "DIV"],
    "ITEM_GROUP": ["ITEM_GROUP", "ITEM_GROUP_NAME"],
    "COST_NAME": ["COST_NAME", "COST_CENTRE", "COST_CENTER", "COSTCENTRE_NAME"],
    "EQPT_NAME": ["EQPT_NAME", "EQUIPMENT", "EQUIPMENT_NAME"],
    "ITEM_CODE": ["ITEM_CODE"],
    "ITEM_NAME": ["ITEM_NAME"],
    "UM": ["UM", "UOM", "UNIT"],
    "BATCH_NO": ["BATCH_NO", "BATCHNO"],
    "QTY_ISSUED": ["QTY_ISSUED", "ISSUE_QTY", "QTY"],
    "RATE": ["RATE", "ISSUE_RATE"],
    "VAL_ISSUED": ["VAL_ISSUED", "ISSUE_VALUE", "VALUE", "AMOUNT"],
}
REQ = ["VRDATE", "VAL_ISSUED"]
NUMS = ("QTY_ISSUED", "RATE", "VAL_ISSUED")
NOTES: dict = {}


def _k(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def div_of(v) -> str:
    """DIV_CODE -> U1 / U2 ('' when it says neither)."""
    s = str(v or "").upper()
    m = re.search(r"U\s*-?\s*([12])\b|UNIT\s*-?\s*([12])\b", s)
    if m:
        return "U" + (m.group(1) or m.group(2))
    if re.fullmatch(r"\s*[12]\s*", s):
        return "U" + s.strip()
    if "WELD" in s:
        return "U1"
    if "SEAM" in s or "SMLS" in s:
        return "U2"
    return ""


def resolve(source: str, allowed: list[str]) -> dict:
    info = datadb.describe_tables([source], allowed)[0]
    if info.get("error"):
        raise EngineError(f"{source} is not in the ERP replica yet (waiting for the Oracle -> MySQL sync)."
                          if "not found" in info["error"] else f"{source} {info['error']}")
    real = {_k(c["name"]): c for c in info["columns"]}
    NOTES.clear()
    NOTES.update({c["name"]: c["comment"] for c in info["columns"] if c.get("comment")})
    out = {}
    for f, names in COLS.items():
        hit = next((real[_k(n)] for n in names if _k(n) in real), None)
        if hit:
            out[f] = hit
    miss = [f for f in REQ if f not in out]
    if miss:
        raise EngineError(f"{source}: column(s) {', '.join(miss)} not found. Available: "
                          + ", ".join(c["name"] for c in info["columns"]))
    return out


def fetch(source: str, cols: dict, d1: dt.date, d2: dt.date, allowed: list[str]):
    from .scrap_mis import _date_filter, _day
    dcol = cols["VRDATE"]
    where, how = _date_filter(source, dcol["name"], dcol.get("type", ""), d1, d2, allowed)
    names = list(cols)
    sel = ", ".join("`" + cols[f]["name"] + "`" for f in names)
    sql = (f"SELECT {sel} FROM `{source}`"
           + (f" WHERE {where}" if where else ""))
    res = datadb.run_select(sql, allowed, max_rows=1_500_000, timeout=config.ENGINE_QUERY_TIMEOUT_SECONDS)
    if res.get("truncated"):
        raise EngineError("Too many issue lines for one dashboard - choose a shorter period.")
    rows, bad = [], 0
    for r in res["rows"]:
        d = dict(zip(names, r))
        day = _day(d["VRDATE"])
        if day is None:
            bad += 1
            continue
        if not (d1 <= day <= d2):
            continue
        d["VRDATE"] = day.isoformat()
        for n in NUMS:
            if n in d:
                try:
                    d[n] = float(d[n] or 0)
                except (TypeError, ValueError):
                    d[n] = 0.0
        for f in names:
            if f not in NUMS and f != "VRDATE":
                d[f] = "" if d[f] is None else str(d[f]).strip()
        rows.append(d)
    return rows, sql, where, how, bad


def scope(rows: list[dict], division: str, plants: list[str] | None) -> list[dict]:
    """Division lock and plant lock - applied on the server, so other rows never reach the page."""
    one = (division or "").upper()
    if one in ("U1", "U2"):
        rows = [r for r in rows if div_of(r.get("DIV_CODE")) == one]
    if plants:
        P = {p.strip().upper() for p in plants}
        rows = [r for r in rows if (r.get("PLANT_NAME") or "").strip().upper() in P]
    return rows


def plants_list(allowed: list[str], source: str = DEFAULT_SOURCE) -> list[dict]:
    """Distinct PLANT_NAME (+ division) of the view - for the admin's plant picker."""
    cols = resolve(source, allowed)
    if "PLANT_NAME" not in cols:
        return []
    p = f"`{cols['PLANT_NAME']['name']}`"
    dv = f"`{cols['DIV_CODE']['name']}`" if "DIV_CODE" in cols else "''"
    r = datadb.run_select(f"SELECT TRIM({p}) AS plant, GROUP_CONCAT(DISTINCT TRIM({dv})) AS dv, COUNT(*) AS n FROM `{source}` "
                          f"WHERE {p} IS NOT NULL AND TRIM({p}) <> '' GROUP BY TRIM({p}) ORDER BY 1", allowed, max_rows=2000)
    out = []
    for a, b, n in r["rows"]:
        ds = sorted({(div_of(x) or x.strip()) for x in str(b or "").split(",") if x.strip()})
        out.append({"plant": a, "div": " + ".join(ds) if len(ds) <= 2 else "Several divisions", "lines": int(n or 0)})
    return out


def _agg(rows, key):
    m: dict = {}
    for r in rows:
        k = r.get(key) or "(blank)"
        a = m.setdefault(k, [0.0, 0, set()])
        a[0] += r["VAL_ISSUED"]
        a[1] += 1
        a[2].add(r.get("VRNO"))
    return sorted(m.items(), key=lambda kv: -kv[1][0])


def dashboard(rows: list[dict], label: str, note: str = "") -> bytes:
    names = list(COLS)
    data = {"cols": names, "rows": [[r.get(n, "") for n in names] for r in rows]}
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    inj = ("<script id=\"vr-issue-data\">(function(){var D=" + js + ";"
           "function go(){try{var rows=D.rows.map(function(a){var o={};for(var i=0;i<D.cols.length;i++)o[D.cols[i]]=a[i];return norm(o);});"
           "start(rows," + json.dumps(label + (" · " + note if note else "")) + ");}catch(e){console.error(e);}}"
           "if(document.readyState==='complete')go();else window.addEventListener('load',go);})();</script>\n")
    t = TEMPLATE.read_text(encoding="utf-8")
    i = t.rfind("</body>")
    return (t[:i] + inj + t[i:]).encode("utf-8")


def run(skill: dict, from_date: str, to_date: str, allowed: list[str], division: str = "BOTH",
        plants: list[str] | None = None) -> dict:
    from .final_production import period_label, prev_period
    st = json.loads(skill.get("sql_template") or "{}")
    source = st.get("source") or DEFAULT_SOURCE
    d1, d2 = sorted([dt.date.fromisoformat(from_date), dt.date.fromisoformat(to_date)])
    cols = resolve(source, allowed)
    one = (division or "BOTH").upper()
    if one in ("U1", "U2") and "DIV_CODE" not in cols:
        raise EngineError(f"{source} has no DIV_CODE column, so the {one}-only view cannot be applied.")
    if plants and "PLANT_NAME" not in cols:
        raise EngineError(f"{source} has no PLANT_NAME column, so your plant limit cannot be applied.")
    raw, sql, where, how, bad = fetch(source, cols, d1, d2, allowed)
    rows = scope(raw, one, plants)
    label = period_label(d1, d2)
    lock = " · ".join(x for x in ((one + " only") if one in ("U1", "U2") else "",
                                  (f"{len(plants)} plant(s)") if plants else "") if x)
    if not rows:
        raise EngineError(f"No issue lines in {source} for {label}" + (f" ({lock})" if lock else "") + ".")
    p1, p2 = prev_period(d1, d2)
    try:
        prv = scope(fetch(source, cols, p1, p2, allowed)[0], one, plants)
    except Exception:
        prv = []
    tot = sum(r["VAL_ISSUED"] for r in rows)
    ptot = sum(r["VAL_ISSUED"] for r in prv)
    L = lambda v: round(v / 1e5, 2)

    # ---- check: the period total straight from the view (before any lock) = VERONICA's total of the same rows
    checks = [("Every issue line has a readable date", bad == 0)]
    if where:
        try:
            r = datadb.run_select(f"SELECT COUNT(*), SUM(`{cols['VAL_ISSUED']['name']}`) FROM `{source}` WHERE {where}",
                                  allowed, max_rows=2, timeout=config.ENGINE_QUERY_TIMEOUT_SECONDS)
            n_sql, v_sql = int(r["rows"][0][0] or 0), float(r["rows"][0][1] or 0)
            checks.append(("Total value = direct SQL SUM(VAL_ISSUED) of the view",
                           abs(sum(x["VAL_ISSUED"] for x in raw) - v_sql) < 1 and n_sql == len(raw) + bad))
        except Exception:
            pass

    def res(columns, data):
        return {"columns": columns, "rows": data, "row_count": len(data), "truncated": False, "sql": sql}

    results, sections = {}, []
    for rid, key, title, n in (("is_plant", "PLANT_NAME", "Plant-wise issue", 50), ("is_dept", "DEPT_NAME", "Department-wise issue", 50),
                               ("is_grp", "ITEM_GROUP", "Item group-wise issue", 50), ("is_cost", "COST_NAME", "Top cost centres", 20),
                               ("is_eqpt", "EQPT_NAME", "Top equipment", 20)):
        if key not in cols:
            continue
        g = _agg(rows, key)
        results[rid] = res([title.split("-")[0].replace("Top ", "").strip(), "Value (₹ Lakh)", "Share %", "Lines", "Vouchers"],
                           [[k, L(v[0]), round(v[0] / tot * 100, 2) if tot else 0, v[1], len(v[2])] for k, v in g[:n]])
        sections.append({"result_id": rid, "title": f"{title} — {label}" + (f" ({lock})" if lock else ""),
                         "total_columns": ["Value (₹ Lakh)", "Lines"] if n >= 50 else [], "grand_total": n >= 50,
                         "column_formats": {"Share %": "percent"},
                         **({"chart": {"type": "bar", "x": results[rid]["columns"][0], "y": ["Value (₹ Lakh)"], "title": title}}
                            if rid == "is_plant" else {})})
    if "ITEM_NAME" in cols or "ITEM_CODE" in cols:
        m: dict = {}
        for r in rows:
            k = (r.get("ITEM_CODE", ""), r.get("ITEM_NAME", ""), r.get("UM", ""))
            a = m.setdefault(k, [0.0, 0.0, 0])
            a[0] += r["VAL_ISSUED"]; a[1] += r.get("QTY_ISSUED", 0.0); a[2] += 1
        top = sorted(m.items(), key=lambda kv: -kv[1][0])[:25]
        results["is_items"] = res(["Item code", "Item name", "UM", "Qty issued", "Value (₹ Lakh)", "Avg rate (₹)", "Lines"],
                                  [[k[0], k[1], k[2], round(v[1], 3), L(v[0]), round(v[0] / v[1], 2) if v[1] else None, v[2]]
                                   for k, v in top])
        sections.append({"result_id": "is_items", "title": f"Top 25 items by issue value — {label}", "grand_total": False})

    vouchers = len({r.get("VRNO") for r in rows}) if "VRNO" in cols else None
    items = len({r.get("ITEM_CODE") for r in rows}) if "ITEM_CODE" in cols else None
    top_plant = _agg(rows, "PLANT_NAME")[0] if "PLANT_NAME" in cols else None
    top_dept = _agg(rows, "DEPT_NAME")[0] if "DEPT_NAME" in cols else None

    def card(lbl, v, prev=None, unit=None, note="", better=None, fmt="number"):
        c = {"label": lbl, "value": v, "format": fmt, "group": "Issues"}
        if unit:
            c["unit"] = unit
        if prev is not None and prv:
            c["previous"], c["previous_label"] = prev, f"vs {p1:%b %Y}" if p1.day == 1 else "vs previous period"
        if note:
            c["note"] = note
        if better:
            c["better"] = better
        return c

    kp = [card("Issue value", L(tot), L(ptot), "₹ Lakh", better="down"),
          card("Issue lines", len(rows), len(prv)),
          *([card("Vouchers", vouchers)] if vouchers is not None else []),
          *([card("Items issued", items)] if items is not None else []),
          *([card("Top plant", L(top_plant[1][0]), unit="₹ Lakh", note=top_plant[0])] if top_plant else []),
          *([card("Top department", L(top_dept[1][0]), unit="₹ Lakh", note=top_dept[0])] if top_dept else [])]
    summary = {"period": label, "lock": lock or "none", "value_lakh": L(tot), "prev_value_lakh": L(ptot) if prv else None,
               "lines": len(rows), "vouchers": vouchers, "items": items,
               "top_plants": [[k, L(v[0])] for k, v in _agg(rows, "PLANT_NAME")[:5]] if "PLANT_NAME" in cols else [],
               "top_departments": [[k, L(v[0])] for k, v in _agg(rows, "DEPT_NAME")[:5]] if "DEPT_NAME" in cols else [],
               "date_filter": how}
    return {"label": label, "prev_label": f"{p1:%d-%m-%Y} to {p2:%d-%m-%Y}", "unit": "₹ Lakh",
            "columns_used": {f: (c["name"] + (f"  ({NOTES[c['name']]})" if NOTES.get(c["name"]) else "")) for f, c in cols.items()},
            "results": results, "sections": sections, "kpis": kp, "summary": summary,
            "files": {"dashboard": dashboard(rows, label, lock)},
            "checks": [{"check": n, "ok": ok} for n, ok in checks], "sql": sql,
            "row_counts": {k: v["row_count"] for k, v in results.items()}}
