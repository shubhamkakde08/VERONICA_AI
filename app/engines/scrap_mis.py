"""Scrap MIS report - exact port of the company's 'Scrap_MIS_Dashboard_Generator_v10_NoCharts.html'.

Sources (one view per ERP export the tool expects):
  Welded (R959)              -> Welded.csv        : VIEW_WELDED_SCRAP_MIS_PBI
  Seamless (R960)            -> Seamless.csv      : VIEW_SEAMLESS_SCRAP_MIS_PBI
  Slitting (R961)            -> Slitting.csv      : VIEW_SLITTING_MIS_PBI
  Final cutting (R950)       -> Final_Cutting.csv : VIEW_FINAL_CUTTING_SCRAP_PBI
  M2M seamless scrap (R984)  -> M2M.csv           : VIEW_M2M_PBI
(If the welded view is not synced yet, welded-plant rows of the seamless view are used as the Welded file.)

Each view is exported in the SAME column layout as the ERP file the HTML recognises, then:
  * the HTML tool gets those files auto-uploaded (all its tabs / Excel / PDF work),
  * the same numbers are computed here (calc / dv / combined) for KPI cards and chat tables.
"""
from __future__ import annotations

import base64
import calendar
import csv
import datetime as dt
import io
import json
import re
from pathlib import Path

from .. import datadb

ENGINE = "scrap_mis"
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "dashboards" / "scrap_mis_v10.html"

DEFAULT_SOURCES = {"seamless": "VIEW_SEAMLESS_SCRAP_MIS_PBI", "slitting": "VIEW_SLITTING_MIS_PBI",
                   "cutting": "VIEW_FINAL_CUTTING_SCRAP_PBI", "m2m": "VIEW_M2M_PBI", "welded": "VIEW_WELDED_SCRAP_MIS_PBI"}


class EngineError(Exception):
    pass


NOTES: dict = {}

# ------------------------------------------------------------------ column mapping (view -> ERP export header)
# field: (ERP header the HTML expects, [view column aliases, normalised: letters+digits only, lower case], required)
FIELDS = {
    "process": {
        "machine": ("Machine Name", ["machinename", "machine", "machinecode", "machineno"], False),
        "plant": ("Plant", ["plantcode", "plant", "plantname", "plantid"], True),
        "vrno": ("Production VRNO", ["productionvrno", "prodvrno", "vrno", "productionno", "prodno"], False),
        "date": ("Production Date", ["productiondate", "proddate", "vrdate", "trandate", "transactiondate", "date"], True),
        "prod": ("Prod Qty", ["prodqty", "productionqty", "prodqtykg", "productionquantity"], True),
        "rl": ("RL Qty", ["rlqty", "randomqty", "randomlengthqty", "rl"], False),
        "scrap": ("Scrap Qty", ["scrapqty", "scarpqty", "scrapquantity", "scarpquantity"], False),
        "bl": ("BL Qty", ["blqty", "bl"], False),
        "total": ("Total Qty", ["totalqty", "totalquantity"], False),
    },
    "cutting": {
        "proc": ("Process Name", ["processname", "process"], False),
        "name": ("Plant Name", ["plantname"], True),
        "code": ("Plant Code", ["plantcode", "plant"], True),
        "vrno": ("Prod VRNO", ["prodvrno", "productionvrno", "vrno"], False),
        "date": ("Prod Date", ["proddate", "productiondate", "vrdate", "date"], True),
        "machine": ("Machine Name", ["machinename", "machine"], False),
        "prod": ("Prod Qty Kg", ["prodqtykg", "prodqty", "productionqty"], True),
        "scrap": ("Scarp Qty", ["scarpqty", "scrapqty", "scrapqtykg", "scarpqtykg"], True),
        "total": ("Prod Qty With Scrap", ["prodqtywithscrap", "prodqtywithscarp", "prodqtywscrap"], False),
    },
    "slitting": {
        "date": ("Production Date", ["productiondate", "proddate", "vrdate", "date"], True),
        "group": ("Item Group Name", ["itemgroupname", "itemgroup"], True),
        "godown": ("Godown Name", ["godownname", "godown"], False),
        "issue": ("Issue Quantity (Kg)", ["issuequantitykg", "issuequantity", "issueqty", "issueqtykg"], False),
        "recv": ("Received Quantity (Kg)", ["receivedquantitykg", "receivedquantity", "receivedqty", "receivedqtykg", "recqty"], False),
    },
    "m2m": {
        "vrno": ("Production No", ["productionno", "prodvrno", "vrno", "productionvrno"], False),
        "date": ("Transaction Date", ["productiondate", "transactiondate", "trandate", "vrdate", "date"], True),
        "group": ("Item Name", ["itemgroupname", "itemname", "itemgroup"], False),
        "godown": ("Godown Name", ["godownname", "godown"], False),
        "issue": ("Issue Quantity (Kg)", ["issuequantitykg", "issuequantity", "issueqty"], False),
        "recv": ("Received Quantity (Kg)", ["receivedquantitykg", "receivedquantity", "receivedqty", "recqty"], True),
    },
}
KIND_OF = {"seamless": "process", "welded": "process", "slitting": "slitting", "cutting": "cutting", "m2m": "m2m"}
FILE_NAME = {"welded": "Welded.csv", "seamless": "Seamless.csv", "slitting": "Slitting.csv",
             "cutting": "Final_Cutting.csv", "m2m": "M2M.csv"}
SLOT_NAME = {"welded": "Welded", "seamless": "Seamless", "slitting": "Slitting", "cutting": "Final cutting", "m2m": "M2M"}

WPL = {"WELDE", "CONDT", "L_SAW"}
SPL = {"BA", "SMLSP", "SMLP2", "SMLST", "PIERC", "PIER2"}


def _n(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def resolve(source: str, kind: str, allowed: list[str]) -> tuple[dict, dict]:
    info = datadb.describe_tables([source], allowed)[0]
    if info.get("error"):
        raise EngineError(f"{source} {info['error']}")
    real = {}
    for c in info["columns"]:
        real.setdefault(_n(c["name"]), c["name"])
        if c.get("comment"):
            NOTES[f"{source}.{c['name']}"] = c["comment"]
    out, cands, missing = {}, {}, []
    for f, (hdr, aliases, req) in FIELDS[kind].items():
        hits = [real[a] for a in aliases if a in real]
        hits = list(dict.fromkeys(hits))
        if hits:
            out[f], cands[f] = hits[0], hits
        elif req:
            missing.append(f"{hdr}")
    if missing:
        raise EngineError(f"Column(s) not found in {source}: {', '.join(missing)}. Available: "
                          + ", ".join(c["name"] for c in info["columns"]))
    return out, cands


def _day(v):
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    t = str(v).strip()
    try:
        return dt.date.fromisoformat(t[:10])
    except ValueError:
        pass
    for f in ("%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d-%b-%y", "%d/%m/%y", "%d.%m.%Y", "%Y%m%d", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(t.split(" ")[0], f).date()
        except ValueError:
            continue
    return None


def _num(v) -> float:
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return 0.0


def _s(v) -> str:
    return "" if v is None else str(v).strip()


DIAG: dict = {}     # per view: date column, its type / format, rows fetched -> shown in checks + check-scrap-mis

_SQL_FMT = [  # (python strptime, MySQL STR_TO_DATE, regex)
    ("%Y-%m-%d", "%Y-%m-%d", r"^\d{4}-\d{1,2}-\d{1,2}"),
    ("%d-%b-%Y", "%d-%b-%Y", r"^\d{1,2}-[A-Za-z]{3}-\d{4}"),
    ("%d-%b-%y", "%d-%b-%y", r"^\d{1,2}-[A-Za-z]{3}-\d{2}(\D|$)"),
    ("%d-%m-%Y", "%d-%m-%Y", r"^\d{1,2}-\d{1,2}-\d{4}"),
    ("%d/%m/%Y", "%d/%m/%Y", r"^\d{1,2}/\d{1,2}/\d{4}"),
    ("%d.%m.%Y", "%d.%m.%Y", r"^\d{1,2}\.\d{1,2}\.\d{4}"),
    ("%d/%m/%y", "%d/%m/%y", r"^\d{1,2}/\d{1,2}/\d{2}(\D|$)"),
    ("%Y%m%d", "%Y%m%d", r"^\d{8}$"),
]


def _date_filter(source: str, dcol: str, ctype: str, d1, d2, allowed) -> tuple[str, str]:
    """WHERE clause that works whether the view's date column is a real DATE/DATETIME or text like '01-OCT-2026'."""
    t = (ctype or "").upper()
    if any(k in t for k in ("DATE", "TIME")):
        return f"`{dcol}` >= '{d1.isoformat()}' AND `{dcol}` <= '{d2.isoformat()} 23:59:59'", "date"
    smp = datadb.run_select(f"SELECT `{dcol}` FROM `{source}` WHERE `{dcol}` IS NOT NULL LIMIT 200", allowed, max_rows=200)
    vals = [str(r[0]).strip() for r in smp["rows"] if r[0] not in (None, "")]
    DIAG.setdefault(source, {})["sample"] = vals[:3]
    for py, my, rx in _SQL_FMT:
        if vals and sum(1 for v in vals if re.match(rx, v)) >= max(1, len(vals) * 0.8):
            if datadb.DIALECT == "mysql":
                e = f"STR_TO_DATE(SUBSTRING_INDEX(TRIM(`{dcol}`), ' ', 1), '{my}')"
                return f"{e} >= '{d1.isoformat()}' AND {e} <= '{d2.isoformat()}'", f"text {py}"
            return "", f"text {py} (filtered in Python)"
    return "", "text, unknown format (filtered in Python)"


def fetch(source: str, kind: str, d1: dt.date, d2: dt.date, allowed: list[str]):
    cols, cands = resolve(source, kind, allowed)
    sel = list(dict.fromkeys([c for v in cands.values() for c in v]))
    dcol = cols["date"]
    info = datadb.describe_tables([source], allowed)[0]
    ctype = next((c["type"] for c in info["columns"] if c["name"] == dcol), "")
    where, how = _date_filter(source, dcol, ctype, d1, d2, allowed)
    sql = f"SELECT {', '.join(f'`{c}`' for c in sel)} FROM `{source}`" + (f" WHERE {where}" if where else "")
    res = datadb.run_select(sql, allowed, max_rows=1_000_000)
    if res.get("truncated"):
        raise EngineError(f"{source}: too many rows for one report - pick a shorter period.")
    raw = [dict(zip(res["columns"], r)) for r in res["rows"]]
    if not where:   # text dates in an unknown format / non-MySQL: filter here with the same parser
        raw = [r for r in raw if (lambda d: d is not None and d1 <= d <= d2)(_day(r.get(dcol)))]
    DIAG.setdefault(source, {}).update(date_column=dcol, date_type=ctype, date_filter=how, rows=len(raw),
                                        columns={f: c for f, c in cols.items()})
    if kind == "process" and len(cands.get("plant", [])) > 1:
        # pick the plant column that really holds the plant codes the tool maps (WELDE, SMLSP, BA ...)
        score = lambda c: sum(1 for r in raw[:5000] if _s(r.get(c)).upper() in WPL | SPL)
        cols["plant"] = max(cands["plant"], key=score)
    if kind == "cutting" and cols.get("code") == cols.get("name"):
        raise EngineError(f"{source}: needs both a Plant Name and a Plant Code column.")
    return raw, cols, sql


# ------------------------------------------------------------------ rows in the tool's record format
def to_records(kind: str, raw: list[dict], cols: dict) -> list[dict]:
    g = lambda r, f: r.get(cols[f]) if f in cols else None
    out = []
    for r in raw:
        day = _day(g(r, "date"))
        if day is None:
            continue
        if kind == "process":
            plant = _s(g(r, "plant")).upper()
            if not plant:
                continue
            v = [_num(g(r, "prod")), _num(g(r, "rl")), _num(g(r, "scrap")), _num(g(r, "bl")), 0.0]
            v[4] = v[0] + v[1] + v[2] + v[3]
            out.append({"plant": plant, "machine": _s(g(r, "machine")).upper(), "day": day, "v": v, "_r": r})
        elif kind == "cutting":
            nm = _s(g(r, "name"))
            if not nm:
                continue
            pr, sc = _num(g(r, "prod")), _num(g(r, "scrap"))
            t = _num(g(r, "total")) if "total" in cols else pr + sc
            out.append({"name": nm, "code": _s(g(r, "code")), "mach": _s(g(r, "machine")), "proc": _s(g(r, "proc")),
                        "day": day, "v": [pr, sc, t - (pr + sc)], "_r": r})
        elif kind == "slitting":
            grp = _s(g(r, "group"))
            if not grp:
                continue
            out.append({"group": grp, "godown": _s(g(r, "godown")), "day": day, "issue": _num(g(r, "issue")),
                        "recv": _num(g(r, "recv")), "isScrap": bool(re.search(r"ss\s*scrap|scrap", grp, re.I)), "_r": r})
        else:  # m2m
            recv, issue = _num(g(r, "recv")), _num(g(r, "issue"))
            if not recv and not issue:
                continue
            out.append({"group": _s(g(r, "group")), "godown": _s(g(r, "godown")), "day": day, "issue": issue,
                        "recv": recv, "_r": r})
    return out


def erp_csv(kind: str, recs: list[dict], cols: dict) -> bytes:
    """Write the records back in the exact ERP export layout the HTML recognises."""
    # always write the columns the tool reads (blank when the view lacks them) so its row-length checks pass
    keep = {"process": ("machine", "plant", "vrno", "date", "prod", "rl", "scrap", "bl"),
            "cutting": ("proc", "name", "code", "vrno", "date", "machine", "prod", "scrap"),
            "slitting": ("date", "group", "godown", "issue", "recv"),
            "m2m": ("vrno", "date", "group", "godown", "recv")}[kind]   # m2m: no Issue / Item Group Name (would look like slitting)
    flds = [f for f in FIELDS[kind] if f in keep or (f in cols and kind != "m2m")]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([FIELDS[kind][f][0] for f in flds])
    for rec in recs:
        r = rec["_r"]
        row = []
        for f in flds:
            if f == "date":
                row.append(rec["day"].isoformat())
            elif kind == "process" and f == "plant":
                row.append(rec["plant"])
            elif f in cols:
                v = r.get(cols[f])
                row.append("" if v is None else (repr(float(v)) if isinstance(v, float) else str(v)))
            else:
                row.append("")
        w.writerow(row)
    return ("﻿" + buf.getvalue()).encode("utf-8")


# ------------------------------------------------------------------ the tool's classification (exact)
LAYOUT = [
    {"id": "welded", "title": "Welded production", "items": [
        {"k": "W_WELDED", "label": "Welded", "cut": "map"},
        {"k": "W_TM10", "label": "TM10", "cut": "zero"},
        {"k": "W_COND", "label": "Cond", "cut": "map"},
        {"k": "W_SLIT", "label": "Slitting", "cut": "zero"},
        {"k": "T_WELDED", "label": "Welded Total", "total": True, "of": ["W_WELDED", "W_TM10", "W_COND", "W_SLIT"],
         "cutOf": ["W_WELDED", "W_COND"]},
        {"band": "L-Saw section"},
        {"k": "L_LSAW", "label": "L-Saw (PLB1)", "cut": "map"},
        {"k": "T_LSAW", "label": "L-Saw Total", "total": True, "of": ["L_LSAW"], "cutOf": ["L_LSAW"]},
    ]},
    {"id": "seamless", "title": "Seamless production", "items": [
        {"k": "S_BA", "label": "BA", "cut": "map"},
        {"k": "S_PIPE1_EXP1", "label": "SMLS Pipe (EXP1)", "cut": "zero"},
        {"k": "S_PIPE1_PEEL", "label": "SMLS Pipe (PEEL)", "cut": "map"},
        {"k": "S_PIPE1_PIL", "label": "SMLS Pipe (ALL PILGER)", "cut": "map"},
        {"k": "S_PIPE2_PEEL3", "label": "SMLS Pipe-2 (PEEL3)", "cut": "map"},
        {"k": "S_PIPE2_PIL", "label": "SMLS Pipe-2 (ALL PILGER)", "cut": "map"},
        {"k": "S_TUBE", "label": "SMLS Tube", "cut": "map"},
        {"k": "S_PIERC", "label": "Piercing 1", "cut": "map"},
        {"k": "S_PIER2", "label": "Piercing 2", "cut": "map"},
        {"k": "S_OTH", "label": "M2M", "cut": "map"},
        {"k": "T_SEAM", "label": "Seamless Total", "total": True,
         "of": ["S_BA", "S_PIPE1_EXP1", "S_PIPE1_PEEL", "S_PIPE1_PIL", "S_PIPE2_PEEL3", "S_PIPE2_PIL", "S_TUBE", "S_PIERC", "S_PIER2", "S_OTH"],
         "cutOf": ["S_BA", "S_PIPE1_PEEL", "S_PIPE1_PIL", "S_PIPE2_PEEL3", "S_PIPE2_PIL", "S_TUBE", "S_PIERC", "S_PIER2", "S_OTH"]},
    ]},
]


def classW(r):
    if r["machine"] == "TM10":
        return ["W_TM10"]
    if r["machine"] == "PLB1" and r["plant"] == "L_SAW":
        return ["L_LSAW"]
    if r["plant"] == "WELDE":
        return ["W_WELDED"]
    if r["plant"] == "CONDT":
        return ["W_COND"]
    return []


def classS(r):
    plant, m = r["plant"], (r["machine"] or "").upper()
    if plant == "BA":
        return "S_BA"
    if plant == "SMLSP":
        if m == "EXP1":
            return "S_PIPE1_EXP1"
        return "S_PIPE1_PEEL" if m.startswith("PEEL") else "S_PIPE1_PIL"
    if plant == "SMLP2":
        return "S_PIPE2_PEEL3" if m.startswith("PEEL") else "S_PIPE2_PIL"
    return {"SMLST": "S_TUBE", "PIERC": "S_PIERC", "PIER2": "S_PIER2"}.get(plant)


CUT_NAME = {"welded": "W_WELDED", "condenser": "W_COND", "lsaw": "L_LSAW", "ba": "S_BA", "seamlesspipe-1": "S_PIPE1_PIL",
            "seamlesspipe-2": "S_PIPE2_PIL", "seamlesstube": "S_TUBE"}
CUT_CODE = {"WELDE": "W_WELDED", "CONDT": "W_COND", "L_SAW": "L_LSAW", "BA": "S_BA", "SMLSP": "S_PIPE1_PIL",
            "SMLP2": "S_PIPE2_PIL", "SMLST": "S_TUBE"}


def classC(r):
    code = (r["code"] or "").upper()
    proc = re.sub(r"\s+", " ", (r["proc"] or "").upper())
    if re.search(r"MH\s*CUTT|MOTHE", proc):
        if code == "SMLSP":
            return "S_PIERC"
        if code == "SMLP2":
            return "S_PIER2"
    if re.search(r"RB\s*CUTT|ROUND", proc):
        if code == "SMLSP":
            return "S_PIPE1_PEEL"
        if code == "SMLP2":
            return "S_PIPE2_PEEL3"
    n = re.sub(r"\s+", "", (r["name"] or "").lower())
    return CUT_NAME.get(n) or CUT_CODE.get(code)


WO_RE = re.compile(r"\bw\s*/?\s*o\b[\s\-_.]*process|without\s*process|\bwoprocess", re.I)
WO_MH_RE = re.compile(r"process[\s\-_]*mh", re.I)


def build(slots: dict) -> dict:
    proc, cut, excl = {}, {}, {}

    def addP(i, day, v):
        a = proc.setdefault((i, day), [0.0] * 5)
        for j in range(5):
            a[j] += v[j]

    def addX(kind, label, day, prod, scrap):
        e = excl.setdefault((kind, label, day), {"kind": kind, "label": label, "day": day, "prod": 0.0, "scrap": 0.0})
        e["prod"] += prod
        e["scrap"] += scrap

    def addCut(i, day, v):
        a = cut.setdefault((i, day), [0.0] * 3)
        for j in range(3):
            a[j] += v[j]

    for r in slots.get("welded", []):
        ids = classW(r)
        if not ids:
            addX("proc", f"{r['machine']} ({r['plant']})", r["day"], r["v"][0], r["v"][2])
        for i in ids:
            addP(i, r["day"], r["v"])
    for r in slots.get("seamless", []):
        i = classS(r)
        if not i:
            addX("proc", f"{r['machine']} ({r['plant']})", r["day"], r["v"][0], r["v"][2])
        else:
            addP(i, r["day"], r["v"])
    for r in slots.get("slitting", []):
        if r["isScrap"]:
            scr = r["recv"] or r["issue"] or 0
            addP("W_SLIT", r["day"], [0, 0, scr, 0, scr])
            continue
        if re.search(r"coil|plate", r["group"] or "", re.I):
            prod = r["recv"] or 0
            addP("W_SLIT", r["day"], [prod, 0, 0, 0, prod])
        else:
            addX("proc", "Slitting " + r["group"] + (f" ({r['godown']})" if r["godown"] else ""), r["day"],
                 r["issue"] or r["recv"] or 0, 0)
    for r in slots.get("cutting", []):
        wo = f"{r['mach']} | {r['proc']} | {r['name']}"
        if WO_RE.search(wo):
            addX("cut", "Cutting WO Process-MH" if WO_MH_RE.search(wo) else "Cutting WO Process", r["day"], r["v"][0], r["v"][1])
            continue
        i = classC(r)
        if not i:
            addX("cut", r["name"] + (f" [{r['proc']}]" if r["proc"] else ""), r["day"], r["v"][0], r["v"][1])
            continue
        addCut(i, r["day"], r["v"])
    for r in slots.get("m2m", []):
        rv = r["recv"] or 0
        addCut("S_OTH", r["day"], [0, rv, rv])
    return {"proc": proc, "cut": cut, "excl": excl}


def calc(D: dict, pred=lambda d: True) -> dict:
    P, C = {}, {}
    for (i, day), v in D["proc"].items():
        if pred(day):
            a = P.setdefault(i, [0.0] * 5)
            for j in range(5):
                a[j] += v[j]
    for (i, day), v in D["cut"].items():
        if pred(day):
            a = C.setdefault(i, [0.0] * 3)
            for j in range(3):
                a[j] += v[j]
    out = {}
    for sec in LAYOUT:
        for it in sec["items"]:
            if it.get("band"):
                continue
            if it.get("total"):
                p = [sum(out[k]["p"][j] for k in it["of"]) for j in range(5)]
                c = [sum((out[k]["c"] or [0, 0, 0])[j] for k in it["cutOf"]) for j in range(3)]
                out[it["k"]] = {"p": p, "c": c}
            else:
                out[it["k"]] = {"p": P.get(it["k"], [0.0] * 5),
                                "c": C.get(it["k"], [0.0] * 3) if it["cut"] == "map" else [0.0] * 3 if it["cut"] == "zero" else None}
    return out


def dv(o):
    p, c, T = o["p"], o["c"], o["p"][4]
    rl = p[1] / T * 100 if T else 0.0
    pr = (p[2] + p[3]) / T * 100 if T else 0.0
    cTot = (c[0] + c[1]) if c else 0.0
    fc = c[1] / cTot * 100 if (c and cTot > 0) else (0.0 if c and c[1] == 0 else None)
    return {"rl": rl, "pr": pr, "fc": fc, "cTot": cTot, "tot": rl + pr + (fc or 0)}


def combined(out):
    W, L, Sm = out["T_WELDED"], out["T_LSAW"], out["T_SEAM"]
    p = [W["p"][i] + Sm["p"][i] for i in range(5)]
    cP, cS = W["c"][0] + L["c"][0] + Sm["c"][0], W["c"][1] + L["c"][1] + Sm["c"][1]
    cTot, T = cP + cS, p[4]
    rl = p[1] / T * 100 if T else 0.0
    pr = (p[2] + p[3]) / T * 100 if T else 0.0
    fc = cS / cTot * 100 if cTot else 0.0
    return {"p": p, "cP": cP, "cS": cS, "cTot": cTot, "rl": rl, "pr": pr, "fc": fc, "tot": rl + pr + fc}


def exclusions(D):
    m = {}
    for e in D["excl"].values():
        a = m.setdefault((e["kind"], e["label"]), {"kind": e["kind"], "label": e["label"], "prod": 0.0, "scrap": 0.0})
        a["prod"] += e["prod"]
        a["scrap"] += e["scrap"]
    return sorted([a for a in m.values() if a["prod"] or a["scrap"]], key=lambda a: -a["prod"])


# ------------------------------------------------------------------ dashboard = the user's HTML with the files auto-uploaded
def dashboard(files: dict[str, bytes], division: str = "", lines=None) -> bytes:
    js_files = ",".join("[" + json.dumps(n) + ",'" + base64.b64encode(b).decode() + "']" for n, b in files.items())
    inj = ("<script>window.addEventListener('load',function(){try{"
           "var L=[" + js_files + "],dt=new DataTransfer();"
           "L.forEach(function(x){var s=atob(x[1]),u=new Uint8Array(s.length);for(var i=0;i<s.length;i++)u[i]=s.charCodeAt(i);"
           "dt.items.add(new File([u],x[0],{type:'text/csv'}));});"
           "var inp=document.getElementById('fileIn');inp.files=dt.files;inp.dispatchEvent(new Event('change',{bubbles:true}));"
           "}catch(e){console.error('auto-load failed',e);}});</script>\n")
    t = TEMPLATE.read_text(encoding="utf-8")
    if division in ("U1", "U2") or lines:        # locked user: the page shows only their division / lines (no empty blocks)
        j = t.lower().find("<head>") + len("<head>")
        t = t[:j] + f'<script>window.VPT_DIV={json.dumps(division)};window.VPT_LINES={json.dumps(list(lines or []))};</script>' + t[j:]
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


U1_SLOTS, U2_SLOTS = {"welded", "slitting"}, {"m2m"}


def scope_records(slot: str, recs: list, division: str) -> list:
    """U2 = Seamless division (seamless plants, seamless final-cutting lines, M2M);
    U1 = Welded division (welded, L-Saw, slitting, welded final-cutting lines). '' = everything."""
    division = (division or "").upper()
    if division not in ("U1", "U2"):
        return recs
    mine = U2_SLOTS if division == "U2" else U1_SLOTS
    other = U1_SLOTS if division == "U2" else U2_SLOTS
    if slot in other:
        return []
    if slot in mine:
        return recs
    if slot in ("seamless", "welded"):
        return [r for r in recs if (r["plant"] in WPL) == (division == "U1")]
    if slot == "cutting":
        keep = []
        for r in recs:
            cid = classC(r) or ""
            if (cid.startswith("S_") and division == "U2") or ((cid.startswith("W_") or cid.startswith("L_")) and division == "U1"):
                keep.append(r)
        return keep
    return recs


def line_of(r) -> str | None:
    """Report line of one production row (welded or seamless view)."""
    return (classW(r) or [None])[0] or classS(r)


def scope_lines(slot: str, recs: list, lines) -> list:
    """Plant-line lock: keep only rows of the user's lines (e.g. Bharat: SMLS Pipe/Pipe-2, Piercing, M2M)."""
    if not lines:
        return recs
    L = set(lines)
    if slot == "slitting":
        return recs if "W_SLIT" in L else []
    if slot == "m2m":
        return recs if "S_OTH" in L else []
    if slot == "cutting":
        return [r for r in recs if (classC(r) or "") in L]
    return [r for r in recs if line_of(r) in L]


def load(sources: dict, d1, d2, allowed, want_files=False, division: str = "", lines=None):
    sources = dict(sources)
    division = (division or "").upper()
    if lines and not division:                            # all lines in one division -> never read the other one's views
        if all(k.startswith("S_") for k in lines):
            division = "U2"
        elif not any(k.startswith("S_") for k in lines):
            division = "U1"
    if division in ("U1", "U2"):                          # never read the other division's own views
        for slot in (U1_SLOTS if division == "U2" else U2_SLOTS):
            sources[slot] = ""
        # the seamless view holds BOTH divisions (welded plants too) -> a locked user may read it here;
        # scope_records / scope_lines below drop every row outside their division / plants
        import fnmatch
        both = (sources.get("seamless") or "").lower()
        allowed = [x for x in (allowed or []) if not (x.startswith("!") and both and fnmatch.fnmatchcase(both, x[1:].lower()))]
    if sources.get("welded"):
        have = {t.lower() for t in datadb.list_tables(allowed)}
        if sources["welded"].lower() not in have:
            NOTES["_welded_fallback"] = (f"{sources['welded']} is not in the replica yet - welded plant rows "
                                         f"(WELDE, CONDT, L_SAW) of {sources.get('seamless')} were used as the Welded file.")
            sources["welded"] = ""
    slots, files, sqls, cols_used, counts = {k: [] for k in SLOT_NAME}, {}, [], {}, {}
    for slot in ("seamless", "welded", "slitting", "cutting", "m2m"):
        src = sources.get(slot)
        if not src:
            continue
        kind = KIND_OF[slot]
        raw, cols, sql = fetch(src, kind, d1, d2, allowed)
        sqls.append(sql)
        cols_used[slot] = {f: (f"{c}  ({NOTES[src + '.' + c]})" if NOTES.get(src + "." + c) else c) for f, c in cols.items()}
        recs = to_records(kind, raw, cols)
        DIAG.setdefault(src, {})["records"] = len(recs)
        if kind == "process":
            if slot == "seamless" and not sources.get("welded"):
                # one view for both ERP reports -> split like two files (welded plants vs the rest)
                w = scope_lines("welded", scope_records("welded", [r for r in recs if r["plant"] in WPL], division), lines)
                s = scope_lines("seamless", scope_records("seamless", [r for r in recs if r["plant"] not in WPL], division), lines)
                slots["welded"] += w
                slots["seamless"] += s
                if want_files and w:
                    files[FILE_NAME["welded"]] = erp_csv(kind, w, cols)
                if want_files and s:
                    files[FILE_NAME["seamless"]] = erp_csv(kind, s, cols)
                counts["welded"], counts["seamless"] = counts.get("welded", 0) + len(w), counts.get("seamless", 0) + len(s)
                continue
        recs = scope_lines(slot, scope_records(slot, recs, division), lines)
        slots[slot] += recs
        counts[slot] = counts.get(slot, 0) + len(recs)
        if want_files and recs:
            files[FILE_NAME[slot]] = erp_csv(kind, recs, cols)
    return slots, files, sqls, cols_used, counts


def run(skill: dict, from_date: str, to_date: str, allowed: list[str], section: str = "", division: str = "",
        lines=None) -> dict:
    division = (division or "").upper() if (division or "").upper() in ("U1", "U2") else ""
    lines = [k for k in (lines or []) if any(it.get("k") == k for sec in LAYOUT for it in sec["items"])]
    if lines and not division:
        division = "U2" if all(k.startswith("S_") for k in lines) else ("U1" if not any(k.startswith("S_") for k in lines) else "")
    st = json.loads(skill.get("sql_template") or "{}")
    sources = {**DEFAULT_SOURCES, **(st.get("sources") or {})}
    d1, d2 = sorted([dt.date.fromisoformat(from_date), dt.date.fromisoformat(to_date)])
    NOTES.clear()
    DIAG.clear()
    slots, files, sqls, cols_used, counts = load(sources, d1, d2, allowed, want_files=True, division=division, lines=lines)
    diag = {k: dict(v) for k, v in DIAG.items()}
    if not any(slots.values()):
        if lines:
            names = [it["label"] for sec in LAYOUT for it in sec["items"] if it.get("k") in lines and not it.get("total")]
            raise EngineError(f"No Scrap MIS data for your plants ({', '.join(names)}) between {d1:%d-%m-%Y} and {d2:%d-%m-%Y}.")
        raise EngineError(f"No Scrap MIS rows in the views between {d1} and {d2}.")
    D = build(slots)
    out = calc(D)
    cb = combined(out)
    p1, p2 = prev_period(d1, d2)
    try:
        ps, _, _, _, _ = load(sources, p1, p2, allowed, division=division, lines=lines)
        pout = calc(build(ps)) if any(ps.values()) else None
    except EngineError:
        pout = None
    pcb = combined(pout) if pout else None
    label, plabel = period_label(d1, d2), p1.strftime("%b")
    mt = lambda kg: round(kg / 1000.0, 2)
    sql = ";\n".join(sqls)

    # ---- checks (same rules the tool's notes describe)
    checks = []
    for sec in LAYOUT:
        for it in sec["items"]:
            if it.get("total"):
                s = sum(out[k]["p"][0] for k in it["of"])
                checks.append((f"{it['label']} = sum of its lines", abs(out[it["k"]]["p"][0] - s) < 0.01))
    for k, o in out.items():
        if abs(o["p"][4] - sum(o["p"][:4])) > 0.01:
            checks.append((f"{k}: Total Issue = Prod + RL + Scrap + BL", False))
    checks.append(("Total Issue = Prod + RL + Scrap + BL on every line", all(abs(o["p"][4] - sum(o["p"][:4])) < 0.01 for o in out.values())))
    for slot in ("welded", "seamless", "slitting", "cutting", "m2m"):
        src = sources.get(slot)
        g = diag.get(src) if src else None
        if not g:
            continue
        ok = g.get("records", 0) > 0
        checks.append((f"{src}: {g.get('records', 0)} rows used" + ("" if ok else
                       f" - NO DATA for the period (date column {g.get('date_column')}, {g.get('date_filter')}, "
                       f"rows fetched {g.get('rows', 0)}, sample {g.get('sample', [])})"), ok))
    cut_diff = sum(v[2] for v in D["cut"].values())
    excl = exclusions(D)

    # ---- tables (MT, exactly the tool's summary table)
    cols_t = ["Plant", "Prod Qty", "Random (RL)", "Scrap", "BL", "Total Issue Qty", "Random %", "Prod 1st process scrap %",
              "Cut Prod Qty", "Cut Scrap Qty", "Cut Total Prod Qty", "Cut Scrap %", "Total scrap %"]
    results, sections = {}, []

    def res(columns, data):
        return {"columns": columns, "rows": data, "row_count": len(data), "truncated": False, "sql": sql}

    sec_ok = {"U2": {"seamless"}, "U1": {"welded", "lsaw", "lsaw_pipe", "l_saw"}}.get(division)
    for sec in LAYOUT:
        if section and sec["id"] != section:
            continue
        if sec_ok is not None and ((division == "U2" and sec["id"] not in sec_ok) or (division == "U1" and sec["id"] == "seamless")):
            continue
        rows = []
        for it in sec["items"]:
            if it.get("band"):
                continue
            if lines and not it.get("total") and it["k"] not in lines:
                continue
            o = out[it["k"]]
            d = dv(o)
            showc = o["c"] is not None and (it.get("total") or it.get("cut") == "map") and (o["c"][0] or o["c"][1])
            rows.append([it["label"], mt(o["p"][0]), mt(o["p"][1]), mt(o["p"][2]), mt(o["p"][3]), mt(o["p"][4]),
                         round(d["rl"], 2), round(d["pr"], 2),
                         mt(o["c"][0]) if showc else None, mt(o["c"][1]) if showc else None,
                         mt(o["c"][0] + o["c"][1]) if showc else None, round(d["fc"], 2) if showc and d["fc"] is not None else None,
                         round(d["tot"], 2)])
        results[sec["id"]] = res(cols_t, rows)
        tot_lbl = next(it["label"] for it in sec["items"] if it.get("total"))
        tot_k = next(it["k"] for it in sec["items"] if it.get("total"))
        sections.append({"result_id": sec["id"], "title": f"{sec['title']} (MT) — {tot_lbl} scrap {dv(out[tot_k])['tot']:.2f}%",
                         "grand_total": False,
                         "column_formats": {c: "percent" for c in cols_t if c.endswith("%")},
                         "chart": {"type": "bar", "x": "Plant", "y": ["Total scrap %"], "title": f"{sec['title']} — total scrap % by line"}})
    if excl:
        results["excl"] = res(["Left out (no report line)", "Type", "Prod (MT)", "Scrap (MT)"],
                              [[e["label"], "Final cutting" if e["kind"] == "cut" else "Process", mt(e["prod"]), mt(e["scrap"])] for e in excl])
        sections.append({"result_id": "excl", "title": "Left out and data checks (same as the tool's notes)", "grand_total": False})

    # ---- KPI cards = the tool's 5 cards (+ previous month)
    W, L, Sm = out["T_WELDED"], out["T_LSAW"], out["T_SEAM"]

    def card(label_, value, fmt="number", unit_=None, prevv=None, better=None, note="", group="Scrap MIS"):
        c = {"label": label_, "value": value, "format": fmt, "group": group}
        if unit_:
            c["unit"] = unit_
        if prevv is not None:
            c["previous"], c["previous_label"] = prevv, f"vs {plabel}"
        if better:
            c["better"] = better
        if note:
            c["note"] = note
        return c

    sub = lambda o: f"Total scrap {dv(o)['tot']:.2f}% · scrap + BL {mt(o['p'][2] + o['p'][3])} MT"
    pv = lambda f: f(pout) if pout else None
    kp = [card("Welded production", mt(W["p"][0]), unit_="MT", prevv=pv(lambda o: mt(o["T_WELDED"]["p"][0])), better="up", note=sub(W)),
          card("L-Saw (PLB1)", mt(L["p"][0]), unit_="MT", prevv=pv(lambda o: mt(o["T_LSAW"]["p"][0])), better="up", note=sub(L)),
          card("Seamless production", mt(Sm["p"][0]), unit_="MT", prevv=pv(lambda o: mt(o["T_SEAM"]["p"][0])), better="up", note=sub(Sm)),
          card("Final cutting output", mt(cb["cP"]), unit_="MT", prevv=mt(pcb["cP"]) if pcb else None, better="up",
               note=f"Scrap {mt(cb['cS'])} MT · {cb['fc']:.2f}%"),
          card("Total scrap % (Welded + Seamless)", round(cb["tot"], 2), "percent", prevv=round(pcb["tot"], 2) if pcb else None,
               better="down", note=f"Random {cb['rl']:.2f} + process {cb['pr']:.2f} + cutting {cb['fc']:.2f}"),
          card("Welded total scrap %", round(dv(W)["tot"], 2), "percent", prevv=pv(lambda o: round(dv(o["T_WELDED"])["tot"], 2)),
               better="down", group="Scrap % by section"),
          card("L-Saw total scrap %", round(dv(L)["tot"], 2), "percent", prevv=pv(lambda o: round(dv(o["T_LSAW"])["tot"], 2)),
               better="down", group="Scrap % by section"),
          card("Seamless total scrap %", round(dv(Sm)["tot"], 2), "percent", prevv=pv(lambda o: round(dv(o["T_SEAM"])["tot"], 2)),
               better="down", group="Scrap % by section")]

    if division == "U2":
        kp = [k for k in kp if not re.search(r"welded|l-saw", k["label"], re.I) or "Welded + Seamless" in k["label"]]
        for k in kp:
            k["label"] = k["label"].replace("Total scrap % (Welded + Seamless)", "Total scrap % (Seamless U2)")
    elif division == "U1":
        kp = [k for k in kp if not re.search(r"seamless", k["label"], re.I) or "Welded + Seamless" in k["label"]]
        for k in kp:
            k["label"] = k["label"].replace("Total scrap % (Welded + Seamless)", "Total scrap % (Welded U1)")

    # insights like the tool's "What stands out"
    ins_lines = [it for sec in LAYOUT if not division or (sec["id"] == "seamless") == (division == "U2")
             for it in sec["items"] if not it.get("band") and not it.get("total") and (not lines or it["k"] in lines)]
    best = max((it for it in ins_lines if out[it["k"]]["p"][4] > 20000), key=lambda it: dv(out[it["k"]])["tot"], default=None)
    bc = max((it for it in ins_lines if it.get("cut") == "map" and out[it["k"]]["c"] and sum(out[it["k"]]["c"][:2]) > 5000),
             key=lambda it: out[it["k"]]["c"][1] / sum(out[it["k"]]["c"][:2]), default=None)
    summary = {"period": label, **({"division_only": division} if division else {}),
               **({} if division == "U2" else {"welded_mt": mt(W["p"][0]), "lsaw_mt": mt(L["p"][0])}),
               **({} if division == "U1" else {"seamless_mt": mt(Sm["p"][0])}),
               "final_cutting_mt": mt(cb["cP"]), "final_cutting_scrap_mt": mt(cb["cS"]), "final_cutting_scrap_pct": round(cb["fc"], 2),
               "total_scrap_pct": round(cb["tot"], 2), "random_pct": round(cb["rl"], 2), "process_pct": round(cb["pr"], 2),
               "previous_total_scrap_pct": round(pcb["tot"], 2) if pcb else None,
               "highest_total_scrap_line": ({"line": best["label"], "pct": round(dv(out[best["k"]])["tot"], 2)} if best else None),
               "highest_cutting_scrap_line": ({"line": bc["label"], "pct": round(out[bc["k"]]["c"][1] / sum(out[bc["k"]]["c"][:2]) * 100, 2),
                                               "scrap_mt": mt(out[bc["k"]]["c"][1])} if bc else None),
               "rows_used": counts, "left_out": [{"label": e["label"], "prod_mt": mt(e["prod"]), "scrap_mt": mt(e["scrap"])} for e in excl[:6]]}
    summary["views"] = diag
    if NOTES.get("_welded_fallback"):
        summary["welded_source_note"] = NOTES["_welded_fallback"]
    if abs(cut_diff) > 0.5:
        summary["note"] = (f"Final Cutting: ERP 'Prod Qty with Scrap' differs from Prod + Scrap by {cut_diff / 1000:.2f} MT; "
                           "the report uses Prod Qty and Scarp Qty only (same as the tool).")

    return {"label": label, "prev_label": f"{p1:%d-%m-%Y} to {p2:%d-%m-%Y}", "unit": "MT",
            "columns_used": cols_used, "results": results, "sections": sections, "kpis": kp,
            "files": {"dashboard": dashboard(files, division, lines), "source_excel": _zip(files), "source_name": f"SCRAP_MIS_{d1:%d%m%Y}_{d2:%d%m%Y}.zip"},
            "summary": summary, "checks": [{"check": n, "ok": ok} for n, ok in checks], "sql": sql,
            "_internal": {"out": out, "combined": cb}}


def _zip(files: dict[str, bytes]) -> bytes:
    import zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in files.items():
            z.writestr(n, d)
    return b.getvalue()
