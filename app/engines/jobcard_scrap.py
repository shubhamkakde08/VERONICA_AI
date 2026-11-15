"""Job Cardwise Scrap MIS - exact port of 'Job_Cardwise_Scrap_Generator_v4.html'.

Source: VIEW_JOB_CARD_SCRAP_PBI. Processes containing MACHINING are excluded (company rule).
Three sections, one row per Job Card No (split by plant when a job card spans plants):
  bb2bb     Black Bar -> Bright Bar   Peeling + Round Bar Cutting
  bb2hollow Bright Bar -> Hollow      Piercing + Mother Hollow Cutting + Final Inspection (BA excluded on FI),
                                      job cards with Item Group Mother Hollow
  cutting   Hollow -> Seamless        Pilger + Sinking + Final Cutting & Deburring, plants BA / Seamless Pipe-1/2 / Tube
Per job card: Scrap = SUM(scrap) over its processes, Prod = MAX(prod w/ scrap) over processes, Scrap % = Scrap / Prod.

Outputs: KPI cards, chat tables, bucket charts, Excel/PDF (report pack) and the user's own HTML tool with
the period's data auto-uploaded (an Excel in the JOBCARD export format is embedded and fed to its upload box).
"""
from __future__ import annotations

import base64
import calendar
import datetime as dt
import io
import json
import math
import re
from pathlib import Path

from .. import config, datadb

ENGINE = "jobcard_scrap"
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "dashboards" / "jobcard_scrap_v4.html"
INF = math.inf

SECTIONS = [
    {"id": "bb2bb", "title": "Black Bar → Bright Bar", "processes": ["PEELING", "ROUND BAR CUTTING"],
     "labels": ["Peeling", "Round Bar Cutting"], "plants": None,
     "buckets": [("Above 10%", 10, INF, "b-bad"), ("8% - 10%", 8, 10, "b-warn"), ("5% - 8%", 5, 8, "b-ok"),
                 ("3% - 5%", 3, 5, "b-ok"), ("Upto 3%", -INF, 3, "b-good")]},
    {"id": "bb2hollow", "title": "Bright Bar → Hollow", "processes": ["PIERCING", "MOTHER HOLLOW CUTTING", "FINAL INSPECTION"],
     "labels": ["Piercing", "Mother Hollow Cutting", "Final Inspection"], "plants": None,
     "exclude_plant_for_process": {"FINAL INSPECTION": ["BA"]}, "item_group_filter": ["MOTHER HOLLOW", "MOTHERHOLLOW"],
     "buckets": [("Above 10%", 10, INF, "b-bad"), ("5% - 10%", 5, 10, "b-warn"), ("3% - 5%", 3, 5, "b-ok"),
                 ("Upto 3%", -INF, 3, "b-good")]},
    {"id": "cutting", "title": "Hollow → Seamless", "processes": ["PILGER", "SINKING", "FINAL CUTTING & DEBURRING"],
     "labels": ["Pilger", "Sinking", "Final Cutting & Deburring"],
     "plants": ["BA", "SEAMLESS PIPE- 1", "SEAMLESS PIPE- 2", "SEAMLESS TUBE", "SEAMLESS PIPE-1", "SEAMLESS PIPE-2"],
     "buckets": [("Above 20%", 20, INF, "b-bad"), ("15% - 20%", 15, 20, "b-bad"), ("10% - 15%", 10, 15, "b-warn"),
                 ("5% - 10%", 5, 10, "b-warn"), ("3% - 5%", 3, 5, "b-ok"), ("Upto 3%", -INF, 3, "b-good")]},
]
TONE = {"b-good": "#22c58e", "b-ok": "#f5a524", "b-warn": "#f2495c", "b-bad": "#c81e3a"}

ALIASES = {
    "JOB": ["JOB_CARD_NO", "JOBCARD_NO", "JOB_CARD", "JOB_NO"],
    "PROCESS": ["PROCESS_NAME", "PROCESS"],
    "PLANT": ["PLANT_NAME", "PLANT"],
    "PROD_DATE": ["PROD_DATE", "PRODUCTION_DATE", "VRDATE"],
    "SCRAP": ["SCRAP_QTY", "SCARP_QTY", "SCRAP_QUANTITY", "SCARP_QUANTITY"],
    "PRODWS": ["PROD_QTY_WITH_SCRAP", "PROD_QTY_W_SCRAP", "PRODUCTION_QTY_WITH_SCRAP", "PROD_QTY_WITH_SCARP"],
}
OPTIONAL = {"MACHINE": ["MACHINE_NAME", "MACHINE"], "PROD_QTY": ["PROD_QTY", "PROD_QTY_KG", "PRODUCTION_QTY"],
            "ITEM_GROUP": ["ITEM_GROUP", "ITEM_GROUP_NAME", "ITEMGROUP", "ITEM_CATEGORY", "PRODUCT_GROUP"]}
MEANING = {"JOB": "Job Card No", "PROCESS": "Process Name", "PLANT": "Plant Name", "PROD_DATE": "Prod Date",
           "SCRAP": "Scrap Qty", "PRODWS": "Prod Qty with Scrap"}


NOTES: dict = {}      # column comments from the database (what each quantity means), filled per run


class EngineError(Exception):
    pass


# ------------------------------------------------------------------ same helpers as the HTML tool
def norm_process(p) -> str:
    p = str(p or "").strip()
    parts = [s.strip() for s in p.split("-") if s.strip()]
    n = re.sub(r"\s+", " ", " ".join(parts[1:]) if len(parts) > 1 else p).strip().upper()
    n = re.sub(r"\s+AND\s+", " & ", n)
    if n in ("MH CUTTING", "M H CUTTING", "MOTHER HOLLOW CUTTING") or "MH CUTTING" in n:
        n = "MOTHER HOLLOW CUTTING"
    if n in ("RB CUTTING", "R B CUTTING", "ROUND CUTTING", "ROUND BAR CUTTING"):
        n = "ROUND BAR CUTTING"
    if n in ("PILGERING", "PILGER", "COLD PILGER", "COLD PILGERING"):
        n = "PILGER"
    if n in ("CUTTING & DEBURRING", "CUTTING AND DEBURRING") or ("CUTTING" in n and "DEBURR" in n):
        n = "FINAL CUTTING & DEBURRING"
    if n == "FINAL INSPECTION" or n.endswith("FINAL INSPECTION"):
        n = "FINAL INSPECTION"
    if n == "PEELING" or n.startswith("PEEL"):
        n = "PEELING"
    if n == "PIERCING" or n.startswith("PIERC"):
        n = "PIERCING"
    if n in ("SINK", "SINKING", "SINKING MILL"):
        n = "SINKING"
    return n


def _ws(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def plant_matches(plant_upper: str, plant_set: set) -> bool:
    pu = _ws(plant_upper)
    if pu in plant_set:
        return True
    k = re.sub(r"[\s-]+", "", pu)
    return any(k == re.sub(r"[\s-]+", "", p) for p in plant_set)


def ig_matches(row: dict, flt: list) -> bool:
    if not flt:
        return True
    if not row["ig"]:
        return True                                   # no item group on the row -> keep (same as the tool)
    ig = re.sub(r"\s+", "", row["ig"]).upper()
    return any((ff := re.sub(r"\s+", "", f).upper()) == ig or ff in ig or ig in ff for f in flt)


def bucket_for(sec, pct):
    for b in sec["buckets"]:
        if b[1] <= pct < b[2] or (b[2] == INF and pct >= b[1]):
            return b
    return sec["buckets"][-1]


def aggregate(sec: dict, rows: list[dict]) -> dict:
    sr = [r for r in rows if r["process"] in sec["processes"]]
    excl = sec.get("exclude_plant_for_process")
    if excl:
        sr = [r for r in sr if not (excl.get(r["process"]) and
                                     plant_matches(r["plant_u"], {_ws(p).upper() for p in excl[r["process"]]}))]
    flt = sec.get("item_group_filter")
    if flt and any(r["ig"] for r in sr):
        jobs = {r["job"] for r in sr if ig_matches(r, flt)}
        sr = [r for r in sr if r["job"] in jobs]
    if sec.get("plants"):
        ps = {_ws(p).upper() for p in sec["plants"]}
        sr = [r for r in sr if plant_matches(r["plant_u"], ps)]

    # jobs spanning more than one plant are split by plant
    jp: dict = {}
    for r in sr:
        jp.setdefault(r["job"], {}).setdefault(r["process"], set()).add(r["plant"] or "—")
    multi = set()
    for job, procs in jp.items():
        allp = set().union(*procs.values())
        if any(len(s) > 1 for s in procs.values()) or len(allp) > 1:
            multi.add(job)

    groups: dict = {}
    order = []
    for r in sr:
        key = (r["job"], r["plant"] or "—") if r["job"] in multi else (r["job"],)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"job": r["job"], "procs": {}, "plant": r["plant"], "machine": r["machine"],
                               "date": r["date"], "ig": r["ig"] or "", "rep": -1, "multi": r["job"] in multi}
            order.append(key)
        pr = g["procs"].setdefault(r["process"], {"scrap": 0.0, "prod": 0.0, "plant": r["plant"] or "", "rep": -1})
        pr["scrap"] += r["scrap"]
        pr["prod"] += r["prodws"]
        if r["prodws"] > pr["rep"]:
            pr["rep"], pr["plant"] = r["prodws"], r["plant"] or ""
        if r["ig"] and not g["ig"]:
            g["ig"] = r["ig"]
        if r["prodws"] > g["rep"]:
            g["rep"], g["plant"], g["machine"], g["date"] = r["prodws"], r["plant"], r["machine"], r["date"]
            if r["ig"]:
                g["ig"] = r["ig"]

    jobs = []
    for key in order:
        g = groups[key]
        scrap = sum(v["scrap"] for v in g["procs"].values())
        prod = max([v["prod"] for v in g["procs"].values()] + [0.0])
        pct = scrap / prod * 100 if prod else 0.0
        b = bucket_for(sec, pct)
        jobs.append({**g, "scrap": scrap, "prod": prod, "pct": pct, "bucket": b[0], "tone": b[3]})
    jobs.sort(key=lambda j: (-j["pct"], j["job"], j["plant"] or ""))

    buckets = [{"label": b[0], "tone": b[3], "count": 0, "scrap": 0.0, "prod": 0.0} for b in sec["buckets"]]
    bi = {b["label"]: b for b in buckets}
    plants: dict = {}
    for j in jobs:
        b = bi[j["bucket"]]
        b["count"] += 1; b["scrap"] += j["scrap"]; b["prod"] += j["prod"]
        p = plants.setdefault(j["plant"] or "—", {"plant": j["plant"] or "—", "count": 0, "scrap": 0.0, "prod": 0.0})
        p["count"] += 1; p["scrap"] += j["scrap"]; p["prod"] += j["prod"]
    plant_list = sorted(plants.values(), key=lambda p: -p["scrap"])
    grand = {"count": len(jobs), "scrap": sum(j["scrap"] for j in jobs), "prod": sum(j["prod"] for j in jobs)}
    grand["pct"] = grand["scrap"] / grand["prod"] * 100 if grand["prod"] else 0.0
    return {"jobs": jobs, "buckets": buckets, "plants": plant_list, "grand": grand}


def compute(rows: list[dict]) -> dict:
    data = {s["id"]: aggregate(s, rows) for s in SECTIONS}
    tp = sum(d["grand"]["prod"] for d in data.values())
    ts = sum(d["grand"]["scrap"] for d in data.values())
    summary: dict = {}
    for s in SECTIONS:
        for j in data[s["id"]]["jobs"]:
            p = summary.setdefault(j["plant"] or "—", {"plant": j["plant"] or "—", "jobs": set(), "scrap": 0.0,
                                                       "prod": 0.0, "by": {}})
            p["jobs"].add(j["job"]); p["scrap"] += j["scrap"]; p["prod"] += j["prod"]
            b = p["by"].setdefault(s["id"], {"scrap": 0.0, "prod": 0.0, "jobs": 0})
            b["scrap"] += j["scrap"]; b["prod"] += j["prod"]; b["jobs"] += 1
    return {"sections": data, "kpi": {"jobs": len({r["job"] for r in rows}), "prod": tp, "scrap": ts,
                                      "pct": ts / tp * 100 if tp else 0.0, "rows": len(rows)},
            "plant_summary": sorted(summary.values(), key=lambda p: -p["scrap"])}


# ------------------------------------------------------------------ data
def _key(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def resolve_columns(source: str, preset: dict, allowed: list[str]) -> dict:
    info = datadb.describe_tables([source], allowed)[0]
    if info.get("error"):
        raise EngineError(f"{source} {info['error']}")
    real = {_key(c["name"]): c["name"] for c in info["columns"]}
    NOTES.clear()
    NOTES.update({c["name"]: c["comment"] for c in info["columns"] if c.get("comment")})
    out, missing = {}, []
    for ph, names in {**ALIASES, **OPTIONAL}.items():
        cand = ([preset[ph]] if preset.get(ph) else []) + names
        hit = next((real[_key(n)] for n in cand if _key(n) in real), None)
        if hit:
            out[ph] = hit
        elif ph in ALIASES:
            missing.append(f"{ph} = {MEANING[ph]}")
    if missing:
        raise EngineError("Column(s) not found in " + source + ": " + "; ".join(missing) + ". Available: "
                          + ", ".join(c["name"] for c in info["columns"]))
    return out


def fetch(source: str, cols: dict, d1: dt.date, d2: dt.date, allowed: list[str]):
    q = {k: f"`{v}`" for k, v in cols.items()}
    opt = lambda k: q[k] if k in q else "''"
    num = lambda k: f"COALESCE({q[k]}, 0)" if k in q else "0"
    sql = f"""SELECT {q['JOB']} AS job, {q['PROCESS']} AS process, {q['PLANT']} AS plant, {q['PROD_DATE']} AS pdate,
       {opt('MACHINE')} AS machine, {num('SCRAP')} AS scrap, {num('PRODWS')} AS prodws, {num('PROD_QTY')} AS prodqty,
       {opt('ITEM_GROUP')} AS ig
FROM `{source}`
WHERE {q['PROD_DATE']} >= '{d1.isoformat()}' AND {q['PROD_DATE']} <= '{d2.isoformat()} 23:59:59'
  AND {q['JOB']} IS NOT NULL AND TRIM({q['JOB']}) <> ''
  AND UPPER(COALESCE({q['PROCESS']}, '')) NOT LIKE '%MACHINING%'"""
    res = datadb.run_select(sql, allowed, max_rows=400000)
    if res.get("truncated"):
        raise EngineError("Too many rows for one report - choose a shorter period.")
    rows = []
    for job, proc, plant, pdate, machine, scrap, prodws, prodqty, ig in res["rows"]:
        if isinstance(pdate, str):
            try:
                pdate = dt.date.fromisoformat(pdate[:10])
            except ValueError:
                pdate = None
        elif isinstance(pdate, dt.datetime):
            pdate = pdate.date()
        plant_ = _ws(plant)
        ig_ = _ws(ig)
        f = lambda v: float(str(v).replace(",", "")) if v not in (None, "") else 0.0
        rows.append({"job": str(job).strip(), "process_raw": str(proc or "").strip(), "process": norm_process(proc),
                     "plant": plant_, "plant_u": plant_.upper(), "date": pdate, "machine": str(machine or "").strip(),
                     "scrap": f(scrap), "prodws": f(prodws), "prodqty": f(prodqty), "ig": ig_})
    return rows, sql


# ------------------------------------------------------------------ the user's HTML tool, data auto-uploaded
def source_excel(rows: list[dict]) -> bytes:
    """Same columns as the ERP 'Job Cardwise Production Report' export the tool expects."""
    from openpyxl import Workbook
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("JOBCARD")
    ws.append(["Job Card No", "Process Name", "Plant Name", "Item Group", "Prod Date", "Machine Name",
               "Scarp Qty", "Prod Qty with Scrap", "Prod Qty"])
    for r in rows:
        ws.append([r["job"], r["process_raw"], r["plant"], r["ig"], r["date"].strftime("%d-%m-%Y") if r["date"] else "",
                   r["machine"], r["scrap"], r["prodws"], r["prodqty"]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def dashboard(xlsx: bytes, filename: str, unit: str) -> bytes:
    b64 = base64.b64encode(xlsx).decode()
    inj = ("<script>window.addEventListener('load',function(){try{"
           "var s=atob('" + b64 + "'),u=new Uint8Array(s.length);for(var i=0;i<s.length;i++)u[i]=s.charCodeAt(i);"
           "var f=new File([u]," + json.dumps(filename) + ",{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});"
           "var dt=new DataTransfer();dt.items.add(f);var inp=document.getElementById('fileInput');inp.files=dt.files;"
           "inp.dispatchEvent(new Event('change',{bubbles:true}));"
           + ("setTimeout(function(){var b=document.querySelector('#unitToggle button[data-unit=\"MT\"]');if(b)b.click();},900);"
              if unit == "mt" else "")
           + "}catch(e){console.error('auto-load failed',e);}});</script>\n")
    t = TEMPLATE.read_text(encoding="utf-8")
    i = t.rfind("</body>")
    return (t[:i] + inj + t[i:]).encode("utf-8")


# ------------------------------------------------------------------ main entry
def prev_period(d1: dt.date, d2: dt.date):
    def back(d):
        y, m = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
        return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))
    p1, p2 = back(d1), back(d2)
    if d2.day == calendar.monthrange(d2.year, d2.month)[1]:
        p2 = dt.date(p2.year, p2.month, calendar.monthrange(p2.year, p2.month)[1])
    return p1, p2


def period_label(d1, d2):
    if d1.day == 1 and (d1.year, d1.month) == (d2.year, d2.month):
        full = d2.day == calendar.monthrange(d2.year, d2.month)[1]
        return d1.strftime("%b %Y").upper() + ("" if full else f" (MTD to {d2:%d-%m})")
    return f"{d1:%d-%m-%Y} to {d2:%d-%m-%Y}"


def run(skill: dict, from_date: str, to_date: str, allowed: list[str], division: str = "", unit: str = "kg",
        section: str = "") -> dict:
    st = json.loads(skill.get("sql_template") or "{}")
    source = st.get("source") or "VIEW_JOB_CARD_SCRAP_PBI"
    d1, d2 = sorted([dt.date.fromisoformat(from_date), dt.date.fromisoformat(to_date)])
    unit = "mt" if str(unit).lower() in ("mt", "ton", "tonne") else "kg"
    div, U, dp = (1000.0, "MT", 2) if unit == "mt" else (1.0, "Kg", 0)
    cols = resolve_columns(source, st.get("columns") or {}, allowed)
    rows, sql = fetch(source, cols, d1, d2, allowed)
    if not rows:
        raise EngineError(f"No job card rows in {source} between {d1} and {d2}.")
    cur = compute(rows)
    p1, p2 = prev_period(d1, d2)
    prev_rows, _ = fetch(source, cols, p1, p2, allowed)
    prev = compute(prev_rows) if prev_rows else None
    label, plabel = period_label(d1, d2), p1.strftime("%b")
    secs = [s for s in SECTIONS if not section or s["id"] == section] or SECTIONS
    q = lambda v: round(v / div, dp)

    # ---- checks
    checks = []
    for s in SECTIONS:
        d = cur["sections"][s["id"]]
        checks.append((f"{s['title']}: bucket job cards = job list",
                       sum(b["count"] for b in d["buckets"]) == len(d["jobs"])))
    checks.append(("KPI scrap = sum of sections", abs(cur["kpi"]["scrap"] -
                                                     sum(cur["sections"][s["id"]]["grand"]["scrap"] for s in SECTIONS)) < 0.01))
    checks.append(("Plant summary scrap = KPI scrap", abs(sum(p["scrap"] for p in cur["plant_summary"]) - cur["kpi"]["scrap"]) < 0.01))

    # ---- tables for the report pack
    results, sections = {}, []

    def res(columns, data):
        return {"columns": columns, "rows": data, "row_count": len(data), "truncated": False, "sql": sql}

    for s in secs:
        d = cur["sections"][s["id"]]
        k = s["id"]
        results[f"{k}_b"] = res(["Bucket", "Job cards", f"Scrap Qty ({U})", f"Prod Qty w/ Scrap ({U})", "Scrap %"],
                                [[b["label"], b["count"], q(b["scrap"]), q(b["prod"]),
                                  b["scrap"] / b["prod"] * 100 if b["prod"] else 0.0] for b in d["buckets"]])
        sections.append({"result_id": f"{k}_b", "title": f"{s['title']} — bucket summary ({d['grand']['pct']:.2f}%)",
                         "total_columns": ["Job cards", f"Scrap Qty ({U})", f"Prod Qty w/ Scrap ({U})"],
                         "ratio_columns": {"Scrap %": [f"Scrap Qty ({U})", f"Prod Qty w/ Scrap ({U})", 100]},
                         "column_formats": {"Scrap %": "percent", "Job cards": "number"},
                         "chart": {"type": "bar", "x": "Bucket", "y": ["Job cards"], "title": f"{s['title']} — job cards by scrap %",
                                   "colors": [TONE[b[3]] for b in s["buckets"]]}})
        results[f"{k}_p"] = res(["Plant", "Job cards", f"Scrap Qty ({U})", f"Prod Qty w/ Scrap ({U})", "Scrap %"],
                                [[p["plant"], p["count"], q(p["scrap"]), q(p["prod"]),
                                  p["scrap"] / p["prod"] * 100 if p["prod"] else 0.0] for p in d["plants"]])
        sections.append({"result_id": f"{k}_p", "title": f"{s['title']} — plant-wise",
                         "total_columns": ["Job cards", f"Scrap Qty ({U})", f"Prod Qty w/ Scrap ({U})"],
                         "ratio_columns": {"Scrap %": [f"Scrap Qty ({U})", f"Prod Qty w/ Scrap ({U})", 100]},
                         "column_formats": {"Scrap %": "percent", "Job cards": "number"}})
        cols_j = ["Job Card No", "Plant"]
        for lab in s["labels"]:
            cols_j += [f"{lab} Scrap", f"{lab} Prod"]
        cols_j += [f"Total Scrap ({U})", f"Max Prod w/ Scrap ({U})", "Scrap %", "Bucket"]
        jl = []
        for j in d["jobs"]:
            row = [j["job"], j["plant"] or "—"]
            for p in s["processes"]:
                v = j["procs"].get(p) or {"scrap": 0.0, "prod": 0.0}
                row += [q(v["scrap"]), q(v["prod"])]
            row += [q(j["scrap"]), q(j["prod"]), j["pct"], j["bucket"]]
            jl.append(row)
        results[f"{k}_jtop"] = res(["Job Card No", "Plant", f"Scrap ({U})", f"Prod ({U})", "Scrap %", "Bucket"],
                                   [[r[0], r[1], r[-4], r[-3], r[-2], r[-1]] for r in jl[:10]])
        sections.append({"result_id": f"{k}_jtop", "title": f"{s['title']} — 10 worst job cards",
                         "column_formats": {"Scrap %": "percent"}, "grand_total": False, "only_in": ["table"]})
        results[f"{k}_j"] = res(cols_j, jl)
        sections.append({"result_id": f"{k}_j", "title": f"{s['title']} — job-card detail ({len(jl)} job cards)",
                         "total_columns": [c for c in cols_j if c.endswith(("Scrap", "Prod")) or c.startswith(("Total Scrap", "Max Prod"))],
                         "ratio_columns": {"Scrap %": [f"Total Scrap ({U})", f"Max Prod w/ Scrap ({U})", 100]},
                         "column_formats": {"Scrap %": "percent"}, "only_in": ["excel", "html"]})
    ps_cols = ["Plant", "Job cards"] + sum([[f"{s['title']} Scrap", f"{s['title']} Prod"] for s in SECTIONS], []) \
        + [f"Total Scrap ({U})", f"Total Prod ({U})", "Scrap %"]
    ps = []
    for p in cur["plant_summary"]:
        row = [p["plant"], len(p["jobs"])]
        for s in SECTIONS:
            v = p["by"].get(s["id"]) or {"scrap": 0.0, "prod": 0.0}
            row += [q(v["scrap"]), q(v["prod"])]
        ps.append(row + [q(p["scrap"]), q(p["prod"]), p["scrap"] / p["prod"] * 100 if p["prod"] else 0.0])
    results["plant_summary"] = res(ps_cols, ps)
    sections.append({"result_id": "plant_summary", "title": "Plant-wise summary — all sections",
                     "total_columns": [c for c in ps_cols if c.endswith(("Scrap", "Prod", f"({U})"))],
                     "ratio_columns": {"Scrap %": [f"Total Scrap ({U})", f"Total Prod ({U})", 100]},
                     "column_formats": {"Scrap %": "percent"}, "only_in": ["excel", "pdf", "html"]})

    # ---- KPI cards (same four as the tool + each section's scrap %)
    pk = prev["kpi"] if prev else None

    def card(label_, value, fmt="number", unit_=None, prevv=None, better=None, note="", group=None):
        c = {"label": label_, "value": value, "format": fmt}
        if unit_:
            c["unit"] = unit_
        if prevv is not None:
            c["previous"], c["previous_label"] = prevv, f"vs {plabel}"
        if better:
            c["better"] = better
        if note:
            c["note"] = note
        if group:
            c["group"] = group
        return c

    worst_plant = max(cur["plant_summary"], key=lambda p: p["scrap"] / p["prod"] if p["prod"] else 0, default=None)
    g0 = "Overall"
    kp = [card("Job cards in view", cur["kpi"]["jobs"], prevv=pk["jobs"] if pk else None, group=g0),
          card("Production qty", q(cur["kpi"]["prod"]), unit_=U, prevv=q(pk["prod"]) if pk else None, better="up", group=g0),
          card("Scrap qty", q(cur["kpi"]["scrap"]), unit_=U, prevv=q(pk["scrap"]) if pk else None, better="down", group=g0),
          card("Overall scrap %", round(cur["kpi"]["pct"], 2), "percent", prevv=round(pk["pct"], 2) if pk else None,
               better="down", group=g0,
               note=(f"Worst plant: {worst_plant['plant']} {worst_plant['scrap'] / worst_plant['prod'] * 100:.2f}%"
                     if worst_plant and worst_plant["prod"] else ""))]
    for s in SECTIONS:
        d = cur["sections"][s["id"]]["grand"]
        pv = prev["sections"][s["id"]]["grand"] if prev else None
        top = cur["sections"][s["id"]]["buckets"][0]
        kp.append(card(s["title"], round(d["pct"], 2), "percent", prevv=round(pv["pct"], 2) if pv else None,
                       better="down", group="Scrap % by section",
                       note=f"{d['count']} job cards · {top['count']} in '{top['label']}'"))

    xlsx = source_excel(rows)
    fname = f"JOBCARD_{d1:%d%m%Y}_{d2:%d%m%Y}.xlsx"
    worst = {s["id"]: [[j["job"], j["plant"], round(j["pct"], 2)] for j in cur["sections"][s["id"]]["jobs"][:3]] for s in SECTIONS}
    return {"label": label, "prev_label": f"{p1:%d-%m-%Y} to {p2:%d-%m-%Y}", "unit": U, "columns_used": {k: (f"{v}  ({NOTES[v]})" if NOTES.get(v) else v) for k, v in cols.items()},
            "results": results, "sections": sections, "kpis": kp,
            "files": {"dashboard": dashboard(xlsx, fname, unit), "source_excel": xlsx, "source_name": fname},
            "summary": {"overall": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in cur["kpi"].items()},
                        "previous": ({k: (round(v, 3) if isinstance(v, float) else v) for k, v in pk.items()} if pk else None),
                        "sections": {s["id"]: {"title": s["title"], "scrap_pct": round(cur["sections"][s["id"]]["grand"]["pct"], 2),
                                               "job_cards": cur["sections"][s["id"]]["grand"]["count"],
                                               "buckets": {b["label"]: b["count"] for b in cur["sections"][s["id"]]["buckets"]},
                                               "worst_job_cards": worst[s["id"]],
                                               "top_plant": (cur["sections"][s["id"]]["plants"][0]["plant"]
                                                             if cur["sections"][s["id"]]["plants"] else None)}
                                     for s in SECTIONS}},
            "checks": [{"check": n, "ok": ok} for n, ok in checks], "sql": sql,
            "_internal": cur}
