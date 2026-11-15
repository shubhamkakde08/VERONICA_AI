"""Final Production / Final Rejection report - exact port of Venus_Final_Production_Dashboard_V5.html.

Source: VIEW_REJECTION_PBI (Tnature PROD + REJP, Division U1 Welded / U2 Seamless).
REJP rows are split into Rejection / Rework / A / B / C from godown code + name (same regexes as the dashboard).

Outputs (one call):
  * KPI cards + chat tables + PDF/HTML via the normal report pack
  * Excel in the dashboard's own layout (title, KPI row, plant x item-group pivot, % rows) + KPI Summary + Data
  * the interactive dashboard itself (the user's HTML) with the period's data pre-loaded - no upload needed
"""
from __future__ import annotations

import calendar
import datetime as dt
import io
import json
import re
from pathlib import Path

from .. import config, datadb

ENGINE = "final_production"
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "dashboards" / "final_production_v13.html"
UNIT = {"U1": "Welded (U1)", "U2": "Seamless (U2)", "ALL": "Company (U1 + U2)"}
CATS = ["Rejection", "Rework", "A", "B", "C"]

# placeholder -> accepted column names in the view (compared without spaces/underscores, upper case)
ALIASES = {
    "DIV": ["DIVISION", "DIV_CODE", "DIV"],
    "TNATURE": ["TNATURE", "T_NATURE", "TRAN_NATURE"],
    "PDATE": ["PRODUCTION_DATE", "PROD_DATE", "VRDATE", "VR_DATE", "PRODUCTIONDATE"],
    "PLANT": ["PLANT_CODE", "PLANT", "PLANTCODE"],
    "IG": ["ITEM_GROUP_NAME", "ITEM_GROUP", "ITEMGROUP_NAME", "ITEM_GROUP_NM"],
    "GCODE": ["GODOWN_CODE", "GODOWNCODE", "GDN_CODE"],
    "GNAME": ["GODOWN_NAME", "GODOWNNAME", "GDN_NAME"],
    "MT": ["PROD_WT_MT", "PRODWTMT", "PROD_WT", "PROD_WEIGHT_MT", "Production Qty (MT)", "PRODUCTION_QTY_MT", "WT_MT"],
}
OPT_ALIASES = {   # optional measures (v13 dashboard: MT / Nos / Meter switch) - used when the view has them
    "NOS": ["PROD_NOS", "PRODNOS", "PROD_NO_S", "PRODUCTION_NOS", "PRODUCTION_NUMBERS", "PROD_QTY_NOS", "NOS"],
    "MTR": ["PROD_MTR", "PRODMTR", "PROD_METER", "PRODUCTION_METER", "PRODUCTION_METERS", "PRODUCTION_MTR", "PROD_QTY_MTR", "MTR", "METER"],
}
KG_ALIASES = ["Production Qty (KG)", "PRODUCTION_QTY_KG", "PROD_WT_KG", "PROD_WT KG"]   # used /1000 when no MT column
MEANING = {"DIV": "Division (U1/U2)", "TNATURE": "Tnature (PROD/REJP)", "PDATE": "Production Date",
           "PLANT": "Plant Code", "IG": "Item Group name", "GCODE": "Godown Code", "GNAME": "Godown Name",
           "MT": "Prod WT MT"}


NOTES: dict = {}      # column comments from the database (what each quantity means), filled per run


class EngineError(Exception):
    pass


# ------------------------------------------------------------------ same rules as the dashboard JS
def classify_rejp(code: str, name: str) -> str:
    c, n = (code or "").upper(), (name or "").upper()
    if re.search(r"-A\b", c) or c.endswith("-A") or re.search(r"PRIME\s*-\s*A", n) or re.search(r"\s-\s*A$", n):
        return "A"
    if (re.search(r"-B\b", c) or c.endswith("-B") or c.endswith("F-B") or re.search(r"SEMI\s*REJECT\s*-\s*B", n)
            or re.search(r"\s-\s*B$", n)):
        return "B"
    if (re.search(r"-C\b", c) or c.endswith("-C") or c.endswith("F-C") or c.endswith("3-C")
            or re.search(r"FINAL\s*REJECT\s*-\s*C", n) or re.search(r"\s-\s*C$", n)):
        return "C"
    if "REW" in c or "REWORK" in n or "PIC" in c or re.search(r"PICKEL|PICKLE", n):
        return "Rework"
    return "Rejection"


def normalize_item_group(ig) -> str:
    s = str(ig or "").strip()
    if not s:
        return "Unknown"
    return "FG Seamless" if re.search(r"seamless\s*u[-\s]?tube", s, re.I) else s


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
    for ph, names in ALIASES.items():
        cand = [preset.get(ph)] if preset.get(ph) else []
        hit = next((real[_key(n)] for n in cand + names if n and _key(n) in real), None)
        if hit:
            out[ph] = hit
        elif ph == "MT" and any(_key(n) in real for n in KG_ALIASES):
            out["KG"] = next(real[_key(n)] for n in KG_ALIASES if _key(n) in real)
        else:
            missing.append(f"{ph} = {MEANING[ph]}")
    for ph, names in OPT_ALIASES.items():
        hit = next((real[_key(n)] for n in ([preset.get(ph)] if preset.get(ph) else []) + names if n and _key(n) in real), None)
        if hit:
            out[ph] = hit
    if missing:
        raise EngineError("Column(s) not found in " + source + ": " + "; ".join(missing)
                          + ". Available: " + ", ".join(c["name"] for c in info["columns"])
                          + ". Ask an admin to map them with set_skill_columns.")
    return out


def _date_where(source: str, dcol: str, d1: dt.date, d2: dt.date, allowed: list[str]) -> str:
    """The view's date may be a real DATE or Oracle text like '09-OCT-2026' / '09-OCT-26' (same formats the V10 HTML reads)."""
    from .scrap_mis import _date_filter
    info = datadb.describe_tables([source], allowed)[0]
    ctype = next((c["type"] for c in info["columns"] if c["name"] == dcol), "")
    where, how = _date_filter(source, dcol, ctype, d1, d2, allowed)
    DIAG["date"] = how
    return where


DIAG: dict = {}


def fetch(source: str, cols: dict, d1: dt.date, d2: dt.date, allowed: list[str]) -> list[dict]:
    from .scrap_mis import _day
    q = {k: f"`{v}`" for k, v in cols.items()}
    qty = f"SUM(COALESCE({q['MT']}, 0))" if "MT" in q else f"SUM(COALESCE({q['KG']}, 0)) / 1000"
    dw = _date_where(source, cols["PDATE"], d1, d2, allowed)
    sql = f"""SELECT TRIM({q['DIV']}) AS division, UPPER(TRIM({q['TNATURE']})) AS tnature,
       {q['PDATE']} AS pdate, TRIM({q['PLANT']}) AS plant, TRIM({q['IG']}) AS ig,
       TRIM(COALESCE({q['GCODE']}, '')) AS gcode, TRIM(COALESCE({q['GNAME']}, '')) AS gname,
       {qty} AS mt, COUNT(*) AS n,
       {f"SUM(COALESCE({q['NOS']}, 0))" if "NOS" in q else "0"} AS nos, {f"SUM(COALESCE({q['MTR']}, 0))" if "MTR" in q else "0"} AS mtr
FROM `{source}`
WHERE UPPER(TRIM({q['TNATURE']})) IN ('PROD', 'REJP') AND UPPER(TRIM({q['DIV']})) IN ('U1', 'U2')""" \
        + (f"\n  AND {dw}" if dw else "") + "\nGROUP BY 1, 2, 3, 4, 5, 6, 7"
    res = datadb.run_select(sql, allowed, max_rows=500000)
    if res.get("truncated"):
        raise EngineError("Too many rows for one report - choose a shorter period.")
    out = []
    for r in res["rows"]:
        division, tn, pdate, plant, ig, gcode, gname, mt, n, nos, mtr = r
        pdate = _day(pdate)
        if pdate is None or not (d1 <= pdate <= d2):
            continue
        division = (division or "").upper()
        out.append({"div": division, "tn": tn, "date": pdate, "plant": plant or "", "ig_raw": ig or "",
                    "ig": normalize_item_group(ig), "gcode": gcode or "", "gname": gname or "",
                    "mt": float(mt or 0), "n": int(n or 0), "nos": float(nos or 0), "mtr": float(mtr or 0),
                    "cat": classify_rejp(gcode, gname) if tn == "REJP" else "PROD"})
    return out, sql


# ------------------------------------------------------------------ maths
def kpis(rows: list[dict]) -> dict:
    s = {c: 0.0 for c in ["PROD"] + CATS}
    for r in rows:
        s[r["cat"]] += r["mt"]
    abc = s["A"] + s["B"] + s["C"]
    rejp = s["Rejection"] + s["Rework"] + abc
    tot = s["PROD"] + rejp
    pct = lambda x: (x / tot * 100) if tot else 0.0
    return {"prod": s["PROD"], "rej": s["Rejection"], "rew": s["Rework"], "A": s["A"], "B": s["B"], "C": s["C"],
            "abc": abc, "rejp": rejp, "tot": tot, "yield_pct": pct(s["PROD"]), "rej_pct": pct(s["Rejection"]),
            "rew_pct": pct(s["Rework"]), "abc_pct": pct(abc), "rejp_pct": pct(rejp),
            "records": sum(r["n"] for r in rows), "days": len({r["date"] for r in rows})}


def pivot(rows: list[dict]):
    plants = sorted({r["plant"] for r in rows})
    igs = sorted({r["ig"] for r in rows})
    p: dict = {}
    for r in rows:
        k = (r["cat"], r["plant"], r["ig"])
        p[k] = p.get(k, 0.0) + r["mt"]
    return plants, igs, p


ROWS = [("Tnature PROD — Inspection Qty", ["PROD"], "prod"), ("Rejection", ["Rejection"], "rej"),
        ("Rework", ["Rework"], "rew"), ("A + B + C", ["A", "B", "C"], "abc"),
        ("Subtotal (Tnature REJP)", CATS, "sub"), ("TOTAL INSPECTION (Grand Total)", ["PROD"] + CATS, "tot"),
        ("Godown A", ["A"], "ga"), ("Godown B", ["B"], "gb"), ("Godown C", ["C"], "gc")]
PCT_ROWS = [("% Rejection", ["Rejection"]), ("% Rework", ["Rework"]), ("% A + B + C", ["A", "B", "C"])]


EXPAND = {"prod": ["PROD"], "rej": ["Rejection"], "rew": ["Rework"], "abc": ["A", "B", "C"]}   # V9: rows with godown children


def matrix(rows: list[dict], godowns: bool = False):
    """The dashboard's table: [(label, style, [values per plant/ig..., plant total..., grand])].
    godowns=True adds V9's Godown Code child rows (style 'child') under PROD, Rejection, Rework and A + B + C."""
    plants, igs, p = pivot(rows)
    cell = lambda cats, pl, ig: sum(p.get((c, pl, ig), 0.0) for c in cats)
    gp: dict = {}
    names: dict = {}
    for r in rows:
        gd = r["gcode"] or "(blank)"
        if r["gname"]:
            names[gd] = r["gname"]
        k = (r["cat"], gd, r["plant"], r["ig"])
        gp[k] = gp.get(k, 0.0) + r["mt"]

    def line(get):
        vals, g = [], 0.0
        for pl in plants:
            t = 0.0
            for ig in igs:
                v = get(pl, ig); t += v; vals.append(v)
            vals.append(t); g += t
        vals.append(g)
        return vals

    out = []
    for lab, cats, sty in ROWS:
        out.append((lab, sty, line(lambda pl, ig: cell(cats, pl, ig))))
        if godowns and sty in EXPAND:
            gds = sorted({gd for (c, gd, _, _) in gp if c in EXPAND[sty]})
            for gd in gds:
                cat_of = next((c for c in EXPAND[sty] if any(k[0] == c and k[1] == gd for k in gp)), "")
                tag = f" [{cat_of}]" if sty == "abc" else ""
                out.append((f"   ↳ {gd}" + (f" · {names[gd]}" if names.get(gd) else "") + tag, "child",
                            line(lambda pl, ig, gd=gd: sum(gp.get((c, gd, pl, ig), 0.0) for c in EXPAND[sty]))))
    for lab, cats in PCT_ROWS:
        vals, gn, gd = [], 0.0, 0.0
        for pl in plants:
            pn = pdn = 0.0
            for ig in igs:
                n = cell(cats, pl, ig); d = cell(["PROD"] + CATS, pl, ig)
                pn += n; pdn += d
                vals.append(n / d * 100 if d else None)
            vals.append(pn / pdn * 100 if pdn else None); gn += pn; gd += pdn
        vals.append(gn / gd * 100 if gd else None)
        out.append((lab, "pct", vals))
    return plants, igs, out


def prev_period(d1: dt.date, d2: dt.date) -> tuple[dt.date, dt.date]:
    def back(d):
        y, m = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
        return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))
    p1, p2 = back(d1), back(d2)
    if d2.day == calendar.monthrange(d2.year, d2.month)[1]:          # full month -> full previous month
        p2 = dt.date(p2.year, p2.month, calendar.monthrange(p2.year, p2.month)[1])
    return p1, p2


def period_label(d1: dt.date, d2: dt.date) -> str:
    if d1.day == 1 and d1.month == d2.month and d1.year == d2.year:
        full = d2.day == calendar.monthrange(d2.year, d2.month)[1]
        return d1.strftime("%b %Y").upper() + ("" if full else f" (MTD to {d2:%d-%m})")
    return f"{d1:%d-%m-%Y} to {d2:%d-%m-%Y}"


# ------------------------------------------------------------------ Excel (dashboard export layout)
def excel(rows: list[dict], units: dict, label: str, divisions: list[str]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    side = Side(style="thin", color="CBD5E1")
    bd = Border(left=side, right=side, top=side, bottom=side)

    def sty(cell, fill, bold=False, color="1E293B", align="right"):
        cell.fill = PatternFill("solid", fgColor=fill)
        cell.font = Font(bold=bold, color=color, size=10, name="Calibri")
        cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=True)
        cell.border = bd

    ROWSTY = {"prod": ("D1FAE5", True, "064E3B"), "rej": ("FEE2E2", False, "991B1B"),
              "rew": ("FFEDD5", False, "9A3412"), "abc": ("FCE7F3", True, "9D174D"), "sub": ("FEF3C7", True, "854D0E"),
              "tot": ("BFDBFE", True, "1E3A8A"), "ga": ("E0E7FF", False, "3730A3"), "gb": ("EDE9FE", False, "5B21B6"),
              "gc": ("FAE8FF", False, "86198F"), "pct": ("F5F3FF", True, "5B21B6"), "rejph": ("FECACA", True, "7F1D1D")}
    wb = Workbook()
    ws = wb.active
    ws.title = "KPI Summary"
    ws.append([f"VENUS PIPES AND TUBES LTD. — Final Production / Rejection — {label}"])
    hdr = ["Unit", "Total Inspection MT", "PROD MT", "Yield %", "Rejection MT", "Rejection %", "Rework MT",
           "Rework %", "Godown A", "Godown B", "Godown C", "A+B+C MT", "A+B+C %", "Total REJP MT", "REJP %",
           "Records", "Prod days"]
    ws.append(hdr)
    for u in ["U1", "U2", "ALL"]:
        k = units.get(u)
        if not k:
            continue
        ws.append([UNIT[u], k["tot"], k["prod"], k["yield_pct"] / 100, k["rej"], k["rej_pct"] / 100, k["rew"],
                   k["rew_pct"] / 100, k["A"], k["B"], k["C"], k["abc"], k["abc_pct"] / 100, k["rejp"],
                   k["rejp_pct"] / 100, k["records"], k["days"]])
    sty(ws["A1"], "0B3D5C", True, "FFFFFF", "left")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(hdr))
    for c in ws[2]:
        sty(c, "0B3D5C", True, "FFFFFF", "center")
    for row in ws.iter_rows(min_row=3):
        last = row[0].value == UNIT["ALL"]
        for c in row:
            sty(c, "BFDBFE" if last else "FFFFFF", last, "1E3A8A" if last else "1E293B", "left" if c.column == 1 else "right")
            if c.column > 1:
                h = hdr[c.column - 1]
                c.number_format = "0.00%" if h.endswith("%") else ("#,##0" if h in ("Records", "Prod days") else "#,##0.000")
    ws.column_dimensions["A"].width = 22
    for i in range(2, len(hdr) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 14
    ws.row_dimensions[1].height = 26
    ws.freeze_panes = "B3"

    for div in divisions:
        d = [r for r in rows if r["div"] == div]
        if not d:
            continue
        k = units[div]
        plants, igs, mat = matrix(d)
        ncol = 1 + len(plants) * (len(igs) + 1) + 1
        ws = wb.create_sheet(UNIT[div].replace("(", "").replace(")", "").strip()[:31])
        ws.append([f"{UNIT[div]} — Final Production Report — {label}"])
        ws.append([f"Inspection Qty: {k['prod']:.3f}", f"Rejection: {k['rej']:.3f}", f"Rework: {k['rew']:.3f}",
                   f"A+B+C: {k['abc']:.3f}", f"Subtotal REJP: {k['rejp']:.3f}", f"Total Inspection: {k['tot']:.3f}"])
        ws.append([])
        h1 = ["Particulars"]
        for pl in plants:
            h1 += [pl] + [""] * len(igs)
        ws.append(h1 + ["Grand Total"])
        h2 = [""]
        for _ in plants:
            h2 += igs + ["Total"]
        ws.append(h2 + [""])
        for lab, s, vals in mat:
            if s == "rej":
                ws.append(["Tnature REJP — Further Bifurcation"])
            ws.append([lab] + [None if v is None or abs(v) < 1e-12 else round(v, 2 if s == "pct" else 6) for v in vals])
        # merges + styles
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
        col = 2
        for _ in plants:
            ws.merge_cells(start_row=4, start_column=col, end_row=4, end_column=col + len(igs))
            col += len(igs) + 1
        ws.merge_cells(start_row=4, start_column=ncol, end_row=5, end_column=ncol)
        ws.merge_cells(start_row=4, start_column=1, end_row=5, end_column=1)
        tot_cols = set()
        cc = 1
        for _ in plants:
            cc += len(igs) + 1
            tot_cols.add(cc)
        for r_i, row in enumerate(ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=ncol), start=1):
            label_ = str(ws.cell(r_i, 1).value or "")
            for c in row:
                if r_i == 1:
                    sty(c, "0B3D5C", True, "FFFFFF", "left")
                elif r_i == 2:
                    sty(c, "EFF6FF", True, "1E3A8A", "center")
                elif r_i == 3:
                    continue
                elif r_i in (4, 5):
                    fill = "062536" if c.column == ncol else ("0A334D" if (r_i == 5 and c.column in tot_cols)
                                                              else ("164E6F" if r_i == 5 and c.column > 1 else "0B3D5C"))
                    sty(c, fill, True, "FFFFFF", "left" if c.column == 1 else "center")
                else:
                    key = next((s for lab, s, _ in mat if lab == label_), "rejph" if "Bifurcation" in label_ else "pct")
                    f, b, colr = ROWSTY[key]
                    sty(c, f, b or c.column in tot_cols or c.column == ncol, colr, "left" if c.column == 1 else "right")
                    if c.column > 1 and isinstance(c.value, (int, float)):
                        c.number_format = '0.00"%"' if key == "pct" else "#,##0.000"
        ws.column_dimensions["A"].width = 36
        for i in range(2, ncol + 1):
            ws.column_dimensions[get_column_letter(i)].width = 13
        ws.row_dimensions[1].height = 28
        ws.row_dimensions[2].height = 22
        ws.row_dimensions[3].height = 8
        ws.freeze_panes = "B6"

    ws = wb.create_sheet("Data")
    ws.append(["Division", "Tnature", "Production Date", "Plant Code", "Item Group name", "Godown Code",
               "Godown Name", "Prod WT MT", "REJP Category", "Records"])
    for r in sorted(rows, key=lambda r: (r["div"], r["date"], r["plant"], r["tn"])):
        ws.append([r["div"], r["tn"], r["date"], r["plant"], r["ig"], r["gcode"], r["gname"], round(r["mt"], 6),
                   "" if r["cat"] == "PROD" else r["cat"], r["n"]])
    for c in ws[1]:
        sty(c, "0B3D5C", True, "FFFFFF", "center")
    for row in ws.iter_rows(min_row=2):
        row[2].number_format = "dd-mmm-yyyy"
        row[7].number_format = "#,##0.000"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, w in enumerate([9, 9, 14, 12, 22, 16, 30, 13, 14, 9], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ interactive dashboard (user's HTML + data)
def dashboard(rows: list[dict], label: str, only: str = "") -> bytes:
    data = [{"Division": r["div"], "Tnature": r["tn"], "Production Date": r["date"].isoformat(),
             "Plant Code": r["plant"], "Item Group name": r["ig_raw"] or r["ig"], "Godown Code": r["gcode"],
             "Godown Name": r["gname"], "Prod WT MT": round(r["mt"], 6), "Month": r["date"].strftime("%b").upper(),
             **({"Prod Nos": round(r.get("nos", 0), 3)} if r.get("nos") else {}),
             **({"Prod MTR": round(r.get("mtr", 0), 3)} if r.get("mtr") else {})}
            for r in rows]
    js = lambda o: json.dumps(o, ensure_ascii=False).replace("</", "<\\/")      # safe inside <script>
    inj = ("<script>window.addEventListener('load',function(){try{processRawRows(" + js(data) + ");"
           "document.getElementById('upload-section').classList.add('hidden');"
           "document.getElementById('dashboard').classList.remove('hidden');"
           "document.getElementById('print-date').textContent=" + js(f"{label} · prepared by {config.ASSISTANT_NAME} · ")
           + "+new Date().toLocaleString();"
           + (("var o=" + js(only) + ",t=document.querySelector('.div-tab[data-div=\"'+o+'\"]');if(t)t.click();"   # one division:
               "document.querySelectorAll('.div-tab').forEach(function(x){if(x.getAttribute('data-div')!==o)x.style.display='none';});")
              if only in ("U1", "U2") else "")                                                      # open on it, hide the rest
           + "}catch(e){console.error(e);}});</script>\n")
    t = TEMPLATE.read_text(encoding="utf-8")
    i = t.rfind("</body>")
    return (t[:i] + inj + t[i:]).encode("utf-8")


def _why_empty(source: str, cols: dict, allowed: list[str]) -> str:
    """Tell the admin what the view really holds, so a wrong value or an old sync is obvious."""
    try:
        q = {k: f"`{v}`" for k, v in cols.items()}
        r = datadb.run_select(f"SELECT {q['DIV']}, {q['TNATURE']}, COUNT(*), MIN({q['PDATE']}), MAX({q['PDATE']}) "
                              f"FROM `{source}` GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 8", allowed, max_rows=8)
        parts = [f"{a}/{b}: {n:,} rows" for a, b, n, *_ in r["rows"]]
        dates = [d for row in r["rows"] for d in row[3:5] if d]
        return (f"The view holds {', '.join(parts) or 'no rows'}; date column {cols['PDATE']} "
                f"({DIAG.get('date', '?')}) looks like '{dates[0] if dates else '-'}'. "
                "If the latest dates are old, run the Oracle sync.")
    except Exception as e:   # diagnostics must never hide the real message
        return f"(could not inspect the view: {str(e)[:120]})"


# ------------------------------------------------------------------ main entry used by the agent tool
def run(skill: dict, from_date: str, to_date: str, allowed: list[str], division: str = "BOTH") -> dict:
    st = json.loads(skill.get("sql_template") or "{}")
    source = st.get("source") or "VIEW_REJECTION_PBI"
    d1, d2 = dt.date.fromisoformat(from_date), dt.date.fromisoformat(to_date)
    if d2 < d1:
        d1, d2 = d2, d1
    cols = resolve_columns(source, st.get("columns") or {}, allowed)
    rows, sql = fetch(source, cols, d1, d2, allowed)
    one = (division or "BOTH").upper()
    if one in ("U1", "U2"):                              # a single division: the other one never leaves the server
        rows = [r for r in rows if r["div"] == one]
    if not rows:
        raise EngineError(f"No PROD/REJP rows in {source} between {d1} and {d2}. " + _why_empty(source, cols, allowed))
    p1, p2 = prev_period(d1, d2)
    prev_rows, _ = fetch(source, cols, p1, p2, allowed)
    if one in ("U1", "U2"):
        prev_rows = [r for r in prev_rows if r["div"] == one]
    division = (division or "BOTH").upper()
    divisions = ["U1", "U2"] if division not in ("U1", "U2") else [division]
    label, plabel = period_label(d1, d2), p1.strftime("%b")

    units = {}
    for u in divisions + (["ALL"] if len(divisions) == 2 else []):
        cur = rows if u == "ALL" else [r for r in rows if r["div"] == u]
        prv = prev_rows if u == "ALL" else [r for r in prev_rows if r["div"] == u]
        if cur:
            units[u] = kpis(cur)
            units[u]["prev"] = kpis(prv) if prv else None
    scope = [r for r in rows if r["div"] in divisions]

    # ---- cross-checks (same as the dashboard's numbers must tie up)
    checks = []
    raw_total = sum(r["mt"] for r in scope)
    main = units.get("ALL") or units[divisions[0]]
    checks.append(("Sum of Prod WT MT = Total Inspection", abs(raw_total - main["tot"]) < 0.001))
    if "ALL" in units and "U1" in units and "U2" in units:
        checks.append(("U1 + U2 = Company", abs(units["U1"]["tot"] + units["U2"]["tot"] - units["ALL"]["tot"]) < 0.001))
    for u in divisions:
        if u in units:
            _, _, mat = matrix([r for r in scope if r["div"] == u])
            grand = dict((lab, v[-1]) for lab, _, v in mat)
            checks.append((f"{u} pivot grand total = KPI", abs(grand["TOTAL INSPECTION (Grand Total)"] - units[u]["tot"]) < 0.001))
    suspicious = sorted({(r["gcode"], r["gname"]) for r in scope if r["cat"] == "Rejection"
                         and re.search(r"PRIME|SEMI|FINAL\s*REJ|REWORK|PICK|[-\s][ABC]$", (r["gcode"] + " " + r["gname"]).upper())})

    # ---- tables for the report pack
    def res(columns, data, note_sql=sql):
        return {"columns": columns, "rows": data, "row_count": len(data), "truncated": False, "sql": note_sql}

    usum = []
    for u in divisions:
        k = units.get(u)
        if k:
            usum.append([UNIT[u], round(k["tot"], 3), round(k["prod"], 3), round(k["rej"], 3), round(k["rew"], 3),
                         round(k["abc"], 3), round(k["rejp"], 3), k["yield_pct"], k["rejp_pct"]])
    results = {"fp_units": res(["Unit", "Total Inspection", "PROD", "Rejection", "Rework", "A+B+C", "Total REJP",
                                "Yield %", "REJP %"], usum)}
    sections = [{"result_id": "fp_units", "title": "Unit summary (MT)",
                 "total_columns": ["Total Inspection", "PROD", "Rejection", "Rework", "A+B+C", "Total REJP"],
                 "ratio_columns": {"Yield %": ["PROD", "Total Inspection", 100], "REJP %": ["Total REJP", "Total Inspection", 100]},
                 "column_formats": {"Yield %": "percent", "REJP %": "percent"}, "grand_total": len(usum) > 1}]
    # the dashboard's own table per unit: Particulars x (plant -> item groups + Total) + Grand Total
    for u in divisions:
        d = [r for r in scope if r["div"] == u]
        if not d:
            continue
        plants, igs, mat = matrix(d, godowns=True)
        mcols = ["Particulars"] + [c for pl in plants for c in [f"{pl} | {ig}" for ig in igs] + [f"{pl} | Total"]] + ["Grand Total"]
        mrows = []
        for lab, sty_, vals in mat:
            if sty_ == "pct":
                mrows.append([lab] + [(f"{v:.2f}%" if v is not None else None) for v in vals])
            else:
                mrows.append([lab] + [(round(v, 3) if abs(v) > 1e-12 else None) for v in vals])
        results[f"fp_{u}_matrix"] = res(mcols, mrows)
        sections.append({"result_id": f"fp_{u}_matrix", "title": f"{UNIT[u]} — {len(d):,} records (MT)",
                         "grand_total": False, "only_in": ["table", "pdf", "html"]})
    sections[0]["only_in"] = ["pdf", "html"]          # unit summary: not in chat (dashboard has none)
    chart_rows = []
    for u in divisions:
        d = [r for r in scope if r["div"] == u]
        if not d:
            continue
        plants, igs, p = pivot(d)
        full, short = [], []
        for pl in plants:
            for ig in igs:
                v = {c: p.get((c, pl, ig), 0.0) for c in ["PROD"] + CATS}
                tot = sum(v.values())
                if tot < 1e-9:
                    continue
                abc = v["A"] + v["B"] + v["C"]
                rejp = tot - v["PROD"]
                full.append([pl, ig, round(v["PROD"], 3), round(v["Rejection"], 3), round(v["Rework"], 3),
                             round(abc, 3), round(v["A"], 3), round(v["B"], 3), round(v["C"], 3), round(rejp, 3),
                             round(tot, 3), None, None, None])
                short.append([pl, ig, round(tot, 3), round(v["PROD"], 3), round(rejp, 3), None])
            ptot = sum(sum(p.get((c, pl, ig), 0.0) for c in ["PROD"] + CATS) for ig in igs)
            prejp = sum(sum(p.get((c, pl, ig), 0.0) for c in CATS) for ig in igs)
            chart_rows.append([f"{u} {pl}", round(prejp / ptot * 100, 2) if ptot else 0.0])
        ratio_full = {"% Rejection": ["Rejection", "Total Inspection", 100], "% Rework": ["Rework", "Total Inspection", 100],
                      "% A+B+C": ["A+B+C", "Total Inspection", 100]}
        # per-row % filled from the same ratio rule
        for r in full:
            r[11] = r[3] / r[10] * 100 if r[10] else None
            r[12] = r[4] / r[10] * 100 if r[10] else None
            r[13] = r[5] / r[10] * 100 if r[10] else None
        for r in short:
            r[5] = r[4] / r[2] * 100 if r[2] else None
        results[f"fp_{u}_full"] = res(["Plant", "Item Group", "PROD", "Rejection", "Rework", "A+B+C", "Godown A",
                                       "Godown B", "Godown C", "Total REJP", "Total Inspection", "% Rejection",
                                       "% Rework", "% A+B+C"], full)
        results[f"fp_{u}_short"] = res(["Plant", "Item Group", "Total Insp", "PROD", "REJP", "REJP %"], short)
        sections.append({"result_id": f"fp_{u}_short", "title": f"{UNIT[u]} — plant / item group (MT)",
                         "group_by": ["Plant"], "total_columns": ["Total Insp", "PROD", "REJP"],
                         "ratio_columns": {"REJP %": ["REJP", "Total Insp", 100]},
                         "column_formats": {"REJP %": "percent"}, "only_in": ["pdf"]})
        sections.append({"result_id": f"fp_{u}_full", "title": f"{UNIT[u]} — PROD / REJP bifurcation (MT)",
                         "group_by": ["Plant"],
                         "total_columns": ["PROD", "Rejection", "Rework", "A+B+C", "Godown A", "Godown B", "Godown C",
                                           "Total REJP", "Total Inspection"],
                         "ratio_columns": ratio_full,
                         "column_formats": {"% Rejection": "percent", "% Rework": "percent", "% A+B+C": "percent"},
                         "only_in": ["pdf", "html"]})
    gd: dict = {}
    for r in scope:
        if r["cat"] != "PROD":
            k = (r["div"], r["gcode"], r["gname"], r["cat"])
            gd[k] = gd.get(k, 0.0) + r["mt"]
    top_g = sorted(gd.items(), key=lambda x: -x[1])[:10]
    results["fp_godowns"] = res(["Unit", "Godown Code", "Godown Name", "Category", "MT", "% of Insp"],
                                [[k[0], k[1], k[2], k[3], round(v, 3), v / units[k[0]]["tot"] * 100] for k, v in top_g])
    sections.append({"result_id": "fp_godowns", "title": "Top REJP godowns", "column_formats": {"% of Insp": "percent"},
                     "grand_total": False, "only_in": ["pdf", "html"]})
    results["fp_plant_chart"] = res(["Plant", "REJP %"], chart_rows)
    sections.append({"result_id": "fp_plant_chart", "title": "REJP % by plant", "show_table": False,
                     "column_formats": {"REJP %": "percent"}, "grand_total": False, "only_in": ["pdf", "html"],
                     "chart": {"type": "bar", "x": "Plant", "y": ["REJP %"], "title": "REJP % by plant"}})

    # ---- KPI cards
    def card(label_, key, fmt="number", better=None, unit_="MT", group=None, k=None, note=""):
        k = k or main
        c = {"label": label_, "value": round(k[key], 3 if fmt == "number" else 2), "format": fmt}
        if fmt == "number":
            c["unit"] = unit_
        if k.get("prev"):
            c["previous"] = round(k["prev"][key], 3 if fmt == "number" else 2)
            c["previous_label"] = f"vs {plabel}"
        if better:
            c["better"] = better
        if group:
            c["group"] = group
        if note:
            c["note"] = note
        return c

    top_plant = max(chart_rows, key=lambda x: x[1]) if chart_rows else None
    kp = []
    for u in divisions:
        k = units.get(u)
        if not k:
            continue
        g = UNIT[u]
        kp += [card("Inspection Qty (PROD)", "prod", better="up", group=g, k=k),
               card("Rejection", "rej", better="down", group=g, k=k),
               card("Rework", "rew", better="down", group=g, k=k),
               card("A + B + C", "abc", better="down", group=g, k=k),
               card("Subtotal REJP", "rejp", better="down", group=g, k=k),
               card("Total Inspection", "tot", group=g, k=k)]
    files = {"excel": excel(scope, units, label, divisions), "dashboard": dashboard(scope, label, division if division in ("U1", "U2") else "")}
    summary = {u: {x: round(v, 3) for x, v in k.items() if isinstance(v, (int, float))} |
               ({"prev": {x: round(v, 3) for x, v in k["prev"].items() if isinstance(v, (int, float))}} if k.get("prev") else {})
               for u, k in units.items()}
    return {"label": label, "prev_label": f"{p1:%d-%m-%Y} to {p2:%d-%m-%Y}", "columns_used": {k: (f"{v}  ({NOTES[v]})" if NOTES.get(v) else v) for k, v in cols.items()},
            "results": results, "sections": sections, "kpis": kp, "files": files, "summary": summary,
            "checks": [{"check": n, "ok": ok} for n, ok in checks],
            "unclassified_like_abc": [f"{c} {n}".strip() for c, n in suspicious][:15], "sql": sql,
            "top_plant_rejp": top_plant, "top_godowns": [[*k, round(v, 3)] for k, v in top_g[:5]]}
