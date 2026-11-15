"""Sales Order MIS - exact port of the company's 'Sales_Order_MIS_Generator.html' (buildD cleaning rules).

Source: VIEW_SALES_ORDER_PBI (one row per sales-order line, same columns as the ERP
"SALES ORDER REPORTS - LD ORDER DETAILS REPORT" export - system names such as SALES_ORDER_NO,
SALE_ORDER_QTY_KG, MATERIAL_VALUE_INR ... are matched after normalising, exactly like the HTML).

Flow:
  view rows -> build_d()  (line-by-line port of MIS_buildD: grade = Parent Grade, MT for KG lines, Nos for
               fittings, value = Material Value, rate = value / net qty, delay = max number after ':', late qty =
               min(delay qty, disp qty), overdue = pending > 0 and delivery date before as-of ...)
           -> D (dictionary-encoded, the HTML's own data format) embedded in <script id="mis-data"> = the
              generator's "Download HTML" snapshot: opens with every tab, slicer, SP Matrix and Excel export.
           -> KPI cards / tables for the requested order-date period computed here from the same D.
"""
from __future__ import annotations

import datetime as dt
import decimal
import json
import math
import logging
import re
import threading
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from .. import config, datadb

ENGINE = "sales_order"
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "dashboards" / "sales_order_mis.html"
DEFAULT_SOURCE = "VIEW_SALES_ORDER_PBI"


class EngineError(Exception):
    pass


NOTES: dict = {}
log = logging.getLogger("veronica.sales_order")

# ------------------------------------------------------------------ the HTML's column aliases (normalised names)
A = {
    "ord": ["salesorderno", "orderno"], "odate": ["salesorderdate", "orderdate"], "ddate": ["deliverydate", "duedate"],
    "month": ["month", "ordermonth"], "grp": ["itemgroupname"], "cust": ["customername"], "quote": ["quotationnumber", "quotationno"],
    "ld": ["ldapplicable", "irfield20"], "itype": ["itemtype"], "od": ["od"], "finish": ["finishtype", "ft"],
    "dly": ["delayduration"], "adate": ["approvaldate", "approveddate"], "sp": ["salespersonname", "employeename"],
    "txn": ["trantype", "transactiontype"], "ctype": ["customertype"], "insp": ["inspectionby", "irfield2"],
    "grade": ["parentgrade", "olditemcode"], "ctry": ["country"], "unit": ["div", "divisioncode", "division"], "status": ["closedflag", "closedstatus"],
    "um": ["um", "unitofmeasure", "uom"], "qty": ["saleorderqtykg"], "canc": ["cancelledqty", "qtycancelled"], "net": ["netorderqtykg", "netorderqty"],
    "exe": ["dispquantitykg", "qtyexecuted", "executedqty", "qtyexecute"], "pend": ["balsalesorderqty", "pendingsoqty", "pendingqty"], "dq": ["delaydeliveryqty", "delayqty"],
    "thk": ["thk", "thickness"], "iname": ["itemname"], "remark": ["itemremark", "remark"],
    "mat": ["materialvalueinr", "materialamount"], "basic": ["basicvalue", "basicamount"],
}
REQ = ["ord", "odate", "sp", "grp", "qty", "net"]
CATS = ["ym", "grp", "cust", "ctype", "sp", "itype", "grade", "mkt", "txn", "ctry", "ld", "um", "ord", "dues", "dd", "unit",
        "status", "insp", "finish", "size", "quote", "odb", "thkb", "fgrade", "sgrade", "otype"]
NUMS = ["qty", "canc", "net", "exe", "pend", "late", "v_qty", "v_canc", "v_net", "v_exe", "v_pend", "v_late", "dly", "odays", "od", "alag",
        "odv", "thk", "dleft"]
MONC = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MON3 = [m.lower() for m in MONC]
EPOCH = dt.date(1970, 1, 1)
TPI = re.compile(r"TPI|TUV|BV|LLOYD|DNV|SGS|IBR|EIL|BVIS|INTERTEK|TATA|CEIL|RINA")


def _um(v) -> str:
    """ERP export says KG / NO; the replica view may say KGS, Kilogram, NOS, Numbers, PCS ..."""
    u = clean(v).upper()
    if not u or u.startswith("KG") or u.startswith("KILO"):
        return "KG"
    if u in ("NO", "NOS", "NO.", "NOS.", "NUMBER", "NUMBERS", "PCS", "PC", "PIECE", "PIECES", "EA", "EACH", "SET", "SETS"):
        return "NO"
    return "NO" if u.startswith(("NO", "NUM", "PC", "PIE")) else u


def _unit(v) -> str:
    u = clean(v).upper()
    m = re.search(r"\bU\s*-?\s*(\d)\b|\bUNIT\s*-?\s*(\d)\b", u)
    if m:
        return "U" + (m.group(1) or m.group(2))
    if re.search(r"\bHO\b|HEAD", u):
        return "HO"
    return u or "NA"


def _status(v) -> str:
    c = clean(v)
    u = c.upper()
    if u in ("", "N", "NO", "OPEN", "O", "0", "FALSE"):
        return "Open"
    if "PARTIAL" in u:
        return "Partially Cancelled"
    if "HOLD" in u or u == "H":
        return "Hold"
    if u in ("Y", "YES", "C", "1", "TRUE", "CLOSED") or "PERMANENT" in u or "CLOSE" in u:
        return "Closed Permanently"
    return c


def norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str("" if s is None else s).strip().lower())


def clean(v) -> str:
    if v is None:
        return ""
    if isinstance(v, decimal.Decimal):
        v = float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        v = v.isoformat()
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v).replace("_x000D_", "").replace(" ", " ")).strip()


def num(v) -> float:
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float, decimal.Decimal)):
        f = float(v)
        return f if math.isfinite(f) else 0.0
    try:
        f = float(str("" if v is None else v).replace(",", "").strip() or "0")
        return f if math.isfinite(f) else 0.0
    except ValueError:
        return 0.0


def jsround(x: float) -> float:          # Math.round: halves go up
    return math.floor(x + 0.5)


def _d(y, m, d) -> int:
    return (dt.date(y, m, d) - EPOCH).days


def pday(v):
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return (v.date() - EPOCH).days
    if isinstance(v, dt.date):
        return (v - EPOCH).days
    if isinstance(v, (int, float, decimal.Decimal)) and not isinstance(v, bool):
        f = float(v)
        return math.floor(f) - 25569 if 20000 < f < 80000 else None
    s = clean(v)
    if not s:
        return None
    try:
        m = re.match(r"^(\d{1,2})[-/ ]([A-Za-z]{3})[A-Za-z]*[-/ ,]+(\d{2,4})", s)
        if m:
            mo = m.group(2).lower()
            if mo not in MON3:
                return None
            y = int(m.group(3)); y = y + 2000 if y < 100 else y
            return _d(y, MON3.index(mo) + 1, int(m.group(1)))
        m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
        if m:
            return _d(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", s)
        if m:
            y = int(m.group(3)); y = y + 2000 if y < 100 else y
            return _d(y, int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    return None


def iso(d: int) -> str:
    return (EPOCH + dt.timedelta(days=d)).isoformat()


def ddstr(d: int) -> str:
    x = EPOCH + dt.timedelta(days=d)
    return f"{x.day:02d}-{MONC[x.month - 1]}-{str(x.year)[2:]}"


def _parse_float(s: str) -> float:      # JS parseFloat
    m = re.match(r"^\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", s)
    return float(m.group(0)) if m else float("nan")


def _fgr(s) -> str:
    s = str(s or "").upper()
    m = re.search(r"TP[- ]?(\d{3}[A-Z]{0,2})(?:\s*/\s*(?:TP)?(\d{3}[A-Z]{0,2}))?", s)
    if m:
        return m.group(1) + ("/" + m.group(2) if m.group(2) else "")
    m = re.search(r"\b(?:WP|F)\s?(\d{3}[A-Z]{0,2})(?:\s*/\s*(\d{3}[A-Z]{0,2}))?\b", s)
    if m:
        return m.group(1) + ("/" + m.group(2) if m.group(2) else "")
    m = re.search(r"UNS\s*([SN]\d{5}(?:\s*/\s*[SN]?\d{5})?)", s)
    if m:
        return "UNS " + re.sub(r"\s", "", m.group(1))
    m = re.search(r"\b(1\.4\d{3})(?:\s*/\s*(1\.4\d{3}))?", s)
    if m:
        return "EN " + m.group(1) + ("/" + m.group(2) if m.group(2) else "")
    for k in ("904L", "SUPER DUPLEX", "DUPLEX", "ALLOY 20", "INCONEL", "MONEL", "HASTELLOY", "2205", "2507", "310S", "317L"):
        if k in s:
            return k
    m = re.search(r"\bA(105|234|106|53|333)\b", s)
    return "CS A" + m.group(1) if m else ""


def _jsnum(v: float) -> str:               # JS Number.toString for short decimals
    v = jsround(v * 100) / 100
    return str(int(v)) if float(v).is_integer() else repr(v)


def _od_band(v: float) -> str:
    if not (v > 0):
        return "NA"
    if v <= 43:
        return "≤ 43"
    ub = 43 + 2 * math.ceil((v - 43) / 2 - 1e-9)
    return _jsnum(ub - 2) + " – " + _jsnum(ub)


def _th_band(v: float) -> str:
    if not (v > 0):
        return "NA"
    if v <= 2:
        return "≤ 2"
    ub = 2 + 0.5 * math.ceil((v - 2) / 0.5 - 1e-9)
    return _jsnum(ub - 0.5) + " – " + _jsnum(ub)


def _band_key(s: str) -> float:
    return 1e9 if s == "NA" else -1 if s.startswith("≤") else _parse_float(s)


def build_d(rows: list[list], asof_day: int, src: str) -> dict:
    """Line-for-line port of MIS_buildD from the HTML generator."""
    h = -1
    for i in range(min(40, len(rows))):
        r = [norm(c) for c in rows[i]]
        if "salesorderno" in r or "orderno" in r:
            h = i
            break
    if h < 0:
        raise EngineError('Header row not found. The view must have a "Sales Order No" (or ORDER_NO) column.')
    H = [norm(c) for c in rows[h]]
    ix = {}
    for k, al in A.items():
        ix[k] = next((H.index(a) for a in al if a in H), -1)
    miss = [k for k in REQ if ix[k] < 0]
    if miss:
        raise EngineError("Missing columns: " + ", ".join(A[k][0] for k in miss))

    def g(r, k):
        j = ix[k]
        return "" if j < 0 or j >= len(r) else r[j]

    out = {k: [] for k in CATS + NUMS}
    skipped = 0
    has_v = ix["mat"] >= 0
    L5 = lambda v: jsround(v / 1e5 * 1e4) / 1e4
    R3 = lambda v: jsround(v * 1000) / 1000
    for r in rows[h + 1:]:
        if not r:
            continue
        ord_ = clean(g(r, "ord"))
        od = pday(g(r, "odate"))
        if not ord_ or od is None:
            skipped += 1
            continue
        x = EPOCH + dt.timedelta(days=od)
        out["ym"].append(f"{x.year}-{x.month:02d}")
        out["od"].append(od)
        out["ord"].append(ord_)
        out["cust"].append(clean(g(r, "cust")).upper())
        out["ctype"].append(clean(g(r, "ctype")) or "UNSPECIFIED")
        out["sp"].append(clean(g(r, "sp")).upper() or "UNASSIGNED")
        out["grp"].append(clean(g(r, "grp")))
        out["itype"].append(clean(g(r, "itype")))
        out["grade"].append(clean(g(r, "grade")).upper() or "OTHER")
        txn = clean(g(r, "txn"))
        out["txn"].append(txn)
        out["mkt"].append("Export" if txn.startswith("Export") else
                          "Domestic" if txn in ("Domestic Sale", "SEZ Supply without Tax Payment") else "Other")
        out["ctry"].append(clean(g(r, "ctry")) or "UNSPECIFIED")
        ld = clean(g(r, "ld")).lower()
        out["ld"].append("Yes" if re.match(r"^\W*yes", ld) else
                         "No" if (re.match(r"^\W*no\b", ld) or re.match(r"^\W*no\.?$", ld)) else "Not Specified")
        um = _um(g(r, "um"))
        out["um"].append(um)
        out["unit"].append(_unit(g(r, "unit")))
        out["status"].append(_status(g(r, "status")))
        out["finish"].append(clean(g(r, "finish")).upper() or "NA")
        ins = clean(g(r, "insp")).upper()
        out["insp"].append("Third Party (TPI)" if TPI.search(ins) else "Client" if re.search(r"CLIENT|CUSTOMER", ins)
                           else "NA" if ins == "" else "Venus")
        odv = _parse_float(clean(g(r, "od")))
        out["size"].append("NA" if math.isnan(odv) else "≤ 60.3 OD (≤2\")" if odv <= 60.4 else
                           "60.3–168.3 OD (2–6\")" if odv <= 168.4 else "168.3–323.9 OD (6–12\")" if odv <= 323.9 else "> 323.9 OD (>12\")")
        out["quote"].append("With quotation" if clean(g(r, "quote")) else "No quotation")
        thv = _parse_float(clean(g(r, "thk")))
        out["odv"].append(-1 if math.isnan(odv) else odv)
        out["thk"].append(-1 if math.isnan(thv) else thv)
        out["odb"].append(_od_band(odv))
        out["thkb"].append(_th_band(thv))
        fg = _fgr(g(r, "iname")) or _fgr(g(r, "remark"))
        out["sgrade"].append(fg or ((clean(g(r, "grade")).upper() or "OTHER") + " (parent)"))
        og = clean(g(r, "grade")).upper()
        out["fgrade"].append("304" if og in ("304", "304H") else "316" if og in ("316", "316MO", "316H") else
                             "DUPLEX" if og in ("DUPLEX", "SUPER DUPLEX") else "316TI" if og == "316TI" else
                             "SUPER 304" if og == "SUPER 304H" else "OTHER GRADE")
        ou = ord_.upper()
        out["otype"].append("Export orders" if ou.startswith("E") else
                            "Market orders" if ou.startswith(("ST", "SR")) else "Domestic orders")
        qty, canc, net, exe = num(g(r, "qty")), num(g(r, "canc")), num(g(r, "net")), num(g(r, "exe"))
        pend = max(0.0, num(g(r, "pend")))
        mat, basic = num(g(r, "mat")), num(g(r, "basic"))
        vals = [int(m) for m in re.findall(r":\s*(-?\d+)", str(g(r, "dly") or ""))]
        dly = max(vals) if vals else 0
        late = max(0.0, min(num(g(r, "dq")), exe)) if dly > 0 else 0.0
        br = basic / qty if qty > 0 else 0.0
        eff = mat / net if net > 0 else (br if (um == "NO" or 20 < br < 20000) else 0.0)
        if not math.isfinite(eff):
            eff = 0.0
        vq = mat + canc * eff if net > 0 else qty * eff
        ve, vp, vl = exe * eff, pend * eff, late * eff
        if um == "KG" and eff > 20000:
            vq, ve, vp, vl = mat, min(ve, mat), min(vp, mat), min(vl, mat)
        vc = max(0.0, vq - mat)
        sc = 1 if um == "NO" else 1 / 1000
        for k, v in (("qty", qty), ("canc", canc), ("net", net), ("exe", exe), ("pend", pend), ("late", late)):
            out[k].append(R3(v * sc))
        for k, v in (("v_net", mat), ("v_qty", vq), ("v_canc", vc), ("v_exe", ve), ("v_pend", vp), ("v_late", vl)):
            out[k].append(L5(v))
        out["dly"].append(dly)
        dd = pday(g(r, "ddate"))
        out["dd"].append("" if dd is None else ddstr(dd))
        pq = pend * sc
        pdue = 0 if dd is None else asof_day - dd
        odays = pdue if (pq > 0 and pdue > 0) else 0
        out["odays"].append(odays)
        out["dleft"].append(dd - asof_day if (pq > 0 and dd is not None) else -99999)
        out["dues"].append("Closed" if pq <= 0 else "Overdue" if odays > 0 else "Open - Not Due")
        ad = pday(g(r, "adate"))
        out["alag"].append(-1 if ad is None else ad - od)
    n = len(out["od"])
    if not n:
        raise EngineError("No order lines found in the view.")
    D = {"n": n, "dict": {}, "c": {}, "asof": iso(asof_day), "src": src, "hasV": has_v, "skipped": skipped}
    for c in CATS:
        cnt: dict = {}
        for v in out[c]:
            cnt[v] = cnt.get(v, 0) + 1
        u = sorted(cnt) if c == "ym" else sorted(cnt, key=_band_key) if c in ("odb", "thkb") else [k for k, _ in sorted(cnt.items(), key=lambda kv: -kv[1])]
        m = {v: i for i, v in enumerate(u)}
        D["dict"][c] = u
        D["c"][c] = [m[v] for v in out[c]]
    for c in NUMS:
        D["c"][c] = [int(v) if isinstance(v, float) and v.is_integer() else v for v in out[c]]
    return D


# ------------------------------------------------------------------ data
def fetch(source: str, allowed: list[str]) -> tuple[list[list], str, dict]:
    info = datadb.describe_tables([source], allowed)[0]
    if info.get("error"):
        raise EngineError(f"{source} {info['error']}")
    want = {a for al in A.values() for a in al}
    cols = [c["name"] for c in info["columns"] if norm(c["name"]) in want]
    for c in info["columns"]:
        if c.get("comment"):
            NOTES[c["name"]] = c["comment"]
    if not any(norm(c) in ("salesorderno", "orderno") for c in cols):
        raise EngineError(f"{source}: no Sales Order No / ORDER_NO column. Available: " + ", ".join(c["name"] for c in info["columns"]))
    sql = f"SELECT {', '.join(f'`{c}`' for c in cols)} FROM `{source}`"
    res = datadb.run_select(sql, allowed, max_rows=2_000_000, timeout=config.ENGINE_QUERY_TIMEOUT_SECONDS)
    if res.get("truncated"):
        raise EngineError(f"{source}: too many rows.")
    used = {k: next((c for c in cols for a in al if norm(c) == a), None) for k, al in A.items()}
    return [list(res["columns"])] + [list(r) for r in res["rows"]], sql, {k: v for k, v in used.items() if v}


# ------------------------------------------------------------------ order book cache (the view is read once, shared)
_CACHE: dict = {}
_CLOCK = threading.Lock()
_BUSY: set = set()


def _load(source: str, allowed: list[str], asof: int) -> dict:
    t0 = time.time()
    rows, sql, used = fetch(source, allowed)
    t1 = time.time()
    D = build_d(rows, asof, source)
    t2 = time.time()
    oi = rows[0].index(used["odate"]) if used.get("odate") in rows[0] else -1
    sample = [r[oi] for r in rows[1:400] if oi >= 0 and r[oi] not in (None, "")]
    ent = {"t": time.time(), "asof": asof, "D": D, "sql": sql, "used": used, "notes": dict(NOTES),
           "rows_read": len(rows) - 1, "date_sample": sample, "page": None,
           "timing": {"fetch_s": round(t1 - t0, 1), "build_s": round(t2 - t1, 1)},
           "loaded_at": dt.datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%d-%m-%Y %H:%M:%S")}
    log.info("sales order book %s: %s rows, fetch %.1fs, build %.1fs", source, ent["rows_read"], t1 - t0, t2 - t1)
    return ent


def order_book(source: str, allowed: list[str], asof: int) -> dict:
    """Rows of the view + D, kept for SO_CACHE_SECONDS; older (same day) copy served while one refresh runs."""
    from ..access import table_ok
    if not table_ok(source, allowed or []):              # same rows for every role -> one shared copy, access checked here
        raise EngineError(f"{source} not found or not allowed")
    key = source.lower()
    allowed = ["*"]
    with _CLOCK:
        hit = _CACHE.get(key)
        age = time.time() - hit["t"] if hit else 1e9
        if hit and hit["asof"] == asof and age < config.SO_CACHE_SECONDS:
            return hit
        if hit and hit["asof"] == asof and age < config.SO_STALE_SECONDS:
            if key not in _BUSY:
                _BUSY.add(key)

                def bg():
                    try:
                        ent = _load(source, allowed, asof)
                        with _CLOCK:
                            _CACHE[key] = ent
                    except Exception:
                        log.warning("background sales order refresh failed", exc_info=True)
                    finally:
                        with _CLOCK:
                            _BUSY.discard(key)
                threading.Thread(target=bg, daemon=True).start()
            return hit
        ent = _load(source, allowed, asof)                 # first load: requests wait for this one read
        _CACHE[key] = ent
        return ent


def warm(allowed: list[str] | None = None):
    """Read the order book in the background at start-up so the first dashboard opens fast."""
    def go():
        try:
            today = dt.datetime.now(ZoneInfo(config.TIMEZONE)).date()
            order_book(DEFAULT_SOURCE, allowed or ["*"], _day(today))
        except Exception:
            log.warning("sales order warm-up failed", exc_info=True)
    threading.Thread(target=go, daemon=True).start()


# ------------------------------------------------------------------ proof: an independent SQL check of the numbers
_MYSQL_FMT = [  # (python regex, MySQL REGEXP, STR_TO_DATE format) - order matters: 4-digit years first
    (r"^\d{4}-\d{1,2}-\d{1,2}", "^[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}", "%Y-%m-%d"),
    (r"^\d{1,2}-[A-Za-z]{3}-\d{4}", "^[0-9]{1,2}-[A-Za-z]{3}-[0-9]{4}", "%d-%b-%Y"),
    (r"^\d{1,2}-[A-Za-z]{3}-\d{2}(?!\d)", "^[0-9]{1,2}-[A-Za-z]{3}-[0-9]{2}([^0-9]|$)", "%d-%b-%y"),
    (r"^\d{1,2}/\d{1,2}/\d{4}", "^[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}", "%d/%m/%Y"),
    (r"^\d{1,2}-\d{1,2}-\d{4}", "^[0-9]{1,2}-[0-9]{1,2}-[0-9]{4}", "%d-%m-%Y"),
    (r"^\d{1,2}\.\d{1,2}\.\d{4}", "^[0-9]{1,2}[.][0-9]{1,2}[.][0-9]{4}", "%d.%m.%Y"),
    (r"^\d{1,2} [A-Za-z]{3} \d{4}", "^[0-9]{1,2} [A-Za-z]{3} [0-9]{4}", "%d %b %Y")]


def _date_sql(col: str, sample: list) -> str | None:
    """SQL expression turning the view's order-date text into a DATE (one format, or a CASE when the view mixes them)."""
    if sample and all(isinstance(v, (dt.date, dt.datetime)) for v in sample[:20]):
        return f"DATE(`{col}`)"
    vals = [clean(v) for v in sample if clean(v)]
    if not vals:
        return None
    seen = [(m, f) for rx, m, f in _MYSQL_FMT if any(re.match(rx, v) for v in vals)]
    covered = sum(1 for v in vals if any(re.match(rx, v) for rx, _, _ in _MYSQL_FMT))
    if not seen or covered < 0.98 * len(vals):
        return None
    if len(seen) == 1:
        return f"STR_TO_DATE(`{col}`, '{seen[0][1]}')"
    return ("CASE " + " ".join(f"WHEN `{col}` REGEXP '{m}' THEN STR_TO_DATE(`{col}`, '{f}')" for m, f in seen) + " END")


def proof(ent: dict, source: str, allowed: list[str], d1: dt.date, d2: dt.date, T: dict, TV: dict) -> dict:
    """Re-count the period straight from the view with plain SUM()s and compare with VERONICA's numbers."""
    u = ent["used"]
    when = dt.datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%d-%m-%Y %H:%M:%S")
    out = {"source": source, "engine_sql": ent["sql"], "rows_read": ent["rows_read"], "loaded_at": ent["loaded_at"],
           "checked_at": when, "columns": u, "verify_sql": "", "rows": [], "ok": None, "error": ""}
    dexpr = _date_sql(u["odate"], ent["date_sample"]) if u.get("odate") else None
    if not dexpr:
        out["error"] = "Order-date format in the view not recognised - SQL cross-check skipped."
        return out
    q = lambda k: f"`{u[k]}`" if u.get(k) else "0"
    where = f"WHERE {dexpr} BETWEEN '{d1.isoformat()}' AND '{d2.isoformat()}' AND {q('ord')} IS NOT NULL AND TRIM({q('ord')}) <> ''"
    um = f"UPPER(TRIM({q('um')}))" if u.get("um") else "'KG'"
    sql = (f"SELECT {um} AS uom, COUNT(*) AS order_lines, SUM({q('qty')}) AS order_qty, SUM({q('canc')}) AS cancelled_qty, "
           f"SUM({q('net')}) AS net_qty, SUM({q('exe')}) AS executed_qty, SUM(GREATEST({q('pend')}, 0)) AS pending_qty, "
           f"SUM({q('mat')}) AS material_value_inr FROM `{source}` {where} GROUP BY {um}")
    sql2 = f"SELECT COUNT(*) AS order_lines, COUNT(DISTINCT TRIM({q('ord')})) AS orders FROM `{source}` {where}"
    out["verify_sql"] = sql + ";\n" + sql2 + ";"
    try:
        r1 = datadb.run_select(sql, allowed, max_rows=100, timeout=config.ENGINE_QUERY_TIMEOUT_SECONDS)
        r2 = datadb.run_select(sql2, allowed, max_rows=5, timeout=config.ENGINE_QUERY_TIMEOUT_SECONDS)
    except Exception as e:
        out["error"] = f"SQL cross-check could not run: {str(e)[:300]}"
        return out
    f = lambda v: float(v or 0)
    kg = {k: 0.0 for k in ("order_qty", "cancelled_qty", "net_qty", "executed_qty", "pending_qty")}
    pcs = {k: 0.0 for k in kg}
    val = 0.0
    out["by_uom"] = []
    for row in r1["rows"]:
        d = dict(zip(r1["columns"], row))
        tgt = pcs if _um(d["uom"]) == "NO" else kg
        for k in kg:
            tgt[k] += f(d[k])
        val += f(d["material_value_inr"])
        out["by_uom"].append({k: (round(f(v), 3) if k != "uom" else v) for k, v in d.items()})
    tot = dict(zip(r2["columns"], r2["rows"][0])) if r2["rows"] else {"order_lines": 0, "orders": 0}
    items = [("Order lines", T["lines"], int(tot["order_lines"] or 0), 0),
             ("Sales orders", len(T["ords"]), int(tot["orders"] or 0), 0),
             ("Order qty (MT, KG lines)", round(T["qty"], 3), round(kg["order_qty"] / 1000, 3), 0.5),
             ("Cancelled (MT)", round(T["canc"], 3), round(kg["cancelled_qty"] / 1000, 3), 0.5),
             ("Net booked (MT)", round(T["net"], 3), round(kg["net_qty"] / 1000, 3), 0.5),
             ("Executed (MT)", round(T["exe"], 3), round(kg["executed_qty"] / 1000, 3), 0.5),
             ("Pending (MT)", round(T["pend"], 3), round(kg["pending_qty"] / 1000, 3), 0.5),
             ("Fittings net (Nos)", round(T["pcsNet"], 3), round(pcs["net_qty"], 3), 0.5),
             ("Net booked value (₹ Cr)", round(TV["net"], 2), round(val / 1e7, 2), 0.02)]
    for name, a, b, tol in items:
        ok = abs(a - b) <= max(tol, abs(b) * 0.0005)
        out["rows"].append([name, a, b, round(a - b, 3), "✅ match" if ok else "❌ differs"])
    out["ok"] = all(r[4].startswith("✅") for r in out["rows"])
    return out


def proof_html(p: dict) -> str:
    """Small 'how this number was made' panel (dashboard ribbon + chat report)."""
    import html as _h
    e = _h.escape
    head = ("✅ All totals re-counted straight from the view and they match." if p.get("ok") else
            "❌ Some totals differ from the direct SQL count - see rows marked ❌." if p.get("ok") is False else
            "⚠️ " + e(p.get("error") or "Not checked."))
    rows = "".join(f"<tr><td>{e(str(r[0]))}</td><td>{r[1]:,}</td><td>{r[2]:,}</td><td>{r[3]:,}</td><td>{e(r[4])}</td></tr>"
                   for r in p.get("rows") or [])
    cols = "".join(f"<tr><td>{e(k)}</td><td><code>{e(str(v))}</code></td></tr>" for k, v in (p.get("columns") or {}).items())
    return (f"<div class='vproof'><b>{head}</b>"
            f"<p>Source <code>{e(p['source'])}</code> · {p['rows_read']:,} rows read at {e(p['loaded_at'])} · checked {e(p['checked_at'])}</p>"
            + (f"<table><tr><th>Figure</th><th>VERONICA</th><th>Direct SQL</th><th>Diff</th><th></th></tr>{rows}</table>" if rows else "")
            + f"<p><b>1. Query VERONICA ran to read the data</b></p><pre>{e(p['engine_sql'])}</pre>"
            + (f"<p><b>2. Independent check query</b> (paste in MySQL / PL-SQL tool to verify yourself)</p><pre>{e(p['verify_sql'])}</pre>" if p.get("verify_sql") else "")
            + f"<details><summary>Column mapping used</summary><table>{cols}</table></details></div>")


def _page(book: dict) -> bytes:
    book["page"] = dashboard(book["D"])
    return book["page"]


def dashboard(D: dict) -> bytes:
    t = TEMPLATE.read_text(encoding="utf-8")
    js = json.dumps(D, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    tag = '<script id="mis-data" type="application/json"></script>'
    if tag not in t:
        raise EngineError("Dashboard template has no empty mis-data slot.")
    return t.replace(tag, '<script id="mis-data" type="application/json">' + js + "</script>", 1).encode("utf-8")


# ------------------------------------------------------------------ aggregation (same as the page: add / total)
def _agg(D, idx, value=False):
    C, NO = D["c"], (D["dict"]["um"].index("NO") if "NO" in D["dict"]["um"] else -1)
    ODUE = D["dict"]["dues"].index("Overdue") if "Overdue" in D["dict"]["dues"] else -2
    a = dict(qty=0.0, canc=0.0, net=0.0, exe=0.0, pend=0.0, late=0.0, od=0.0, lines=0, lateLines=0, dlySum=0,
             pcsNet=0.0, pcsExe=0.0, pcsPend=0.0, ords=set(), custs=set())
    p = "v_" if value else ""
    for i in idx:
        a["lines"] += 1
        if not value and C["um"][i] == NO:
            a["pcsNet"] += C["net"][i]; a["pcsExe"] += C["exe"][i]; a["pcsPend"] += C["pend"][i]
        else:
            for f in ("qty", "canc", "net", "exe", "pend", "late"):
                a[f] += C[p + f][i]
            if C["dues"][i] == ODUE:
                a["od"] += C[p + "pend"][i]
            if C["dly"][i] > 0:
                a["lateLines"] += 1; a["dlySum"] += C["dly"][i]
        a["ords"].add(C["ord"][i]); a["custs"].add(C["cust"][i])
    if value:   # lakh -> crore
        for f in ("qty", "canc", "net", "exe", "pend", "late", "od"):
            a[f] /= 100
    return a


def _ratio(n, d):
    return n / d * 100 if d else None


def _day(d: dt.date) -> int:
    return (d - EPOCH).days


def _shift_year(day: int) -> int:
    x = EPOCH + dt.timedelta(days=day)
    try:
        return _day(x.replace(year=x.year - 1))
    except ValueError:            # 29-Feb
        return _day(x.replace(year=x.year - 1, day=28))


def mx_periods(a: int, wk: int = 0):
    x = EPOCH + dt.timedelta(days=a)
    dow = (x.weekday() + 1) % 7                      # JS getUTCDay: Sun=0
    ws = a - ((dow - wk + 7) % 7)
    ms = _day(dt.date(x.year, x.month, 1))
    lm = dt.date(x.year - 1, 12, 1) if x.month == 1 else dt.date(x.year, x.month - 1, 1)
    lms, lme = _day(lm), ms - 1
    fys = _day(dt.date(x.year if x.month >= 4 else x.year - 1, 4, 1))
    return [("Today", a, a), ("Yesterday", a - 1, a - 1), ("This Week", ws, a), ("Last Week", ws - 7, ws - 1),
            ("This Month", ms, a), ("Last Month", lms, lme), ("FY to Date", fys, a),
            ("LM same days", lms, min(lms + (a - ms), lme))]


def run(skill: dict, from_date: str, to_date: str, allowed: list[str], section: str = "") -> dict:
    st = json.loads(skill.get("sql_template") or "{}")
    source = st.get("source") or DEFAULT_SOURCE
    d1, d2 = sorted([dt.date.fromisoformat(from_date), dt.date.fromisoformat(to_date)])
    NOTES.clear()
    today = dt.datetime.now(ZoneInfo(config.TIMEZONE)).date()
    asof = _day(today)
    book = order_book(source, allowed, asof)
    D, sql, used = book["D"], book["sql"], book["used"]
    NOTES.update(book["notes"])
    C, DI = D["c"], D["dict"]
    a, b = _day(d1), _day(d2)
    cur = [i for i in range(D["n"]) if a <= C["od"][i] <= b]
    pa, pb = _shift_year(a), _shift_year(b)
    prv = [i for i in range(D["n"]) if pa <= C["od"][i] <= pb]
    T, TV = _agg(D, cur), _agg(D, cur, True)
    P, PV = _agg(D, prv), _agg(D, prv, True)
    label = f"{d1:%d-%b-%y} to {d2:%d-%b-%y}"
    plabel = f"{EPOCH + dt.timedelta(days=pa):%d-%b-%y} to {EPOCH + dt.timedelta(days=pb):%d-%b-%y}"
    has_prev = bool(prv)
    r2, r3 = (lambda v: round(v, 2)), (lambda v: round(v, 3))

    def card(lbl, v, prev=None, fmt="number", unit=None, better=None, note="", group="Order book"):
        c = {"label": lbl, "value": v, "format": fmt, "group": group}
        if unit:
            c["unit"] = unit
        if has_prev and prev is not None:
            c["previous"], c["previous_label"] = prev, "same dates LY"
        if better:
            c["better"] = better
        if note:
            c["note"] = note
        return c

    otd = lambda x: (1 - x["late"] / x["exe"]) * 100 if x["exe"] > 0 else None
    kp = [card("Net booked", r2(T["net"]), r2(P["net"]), unit="MT", better="up", note=f"₹ {TV['net']:,.2f} Cr"),
          card("Net booked value", r2(TV["net"]), r2(PV["net"]), unit="₹ Cr", better="up"),
          card("Executed", r2(T["exe"]), r2(P["exe"]), unit="MT", better="up", note=f"₹ {TV['exe']:,.2f} Cr"),
          card("Fulfilment", r2(_ratio(T["exe"], T["net"]) or 0), r2(_ratio(P["exe"], P["net"]) or 0), "percent", better="up",
               note="executed ÷ net booked"),
          card("Pending", r2(T["pend"]), None, unit="MT", note=f"₹ {TV['pend']:,.2f} Cr", group="Delivery"),
          card("Overdue pending", r2(T["od"]), None, unit="MT", better="down",
               note=f"{(_ratio(T['od'], T['pend']) or 0):.1f}% of pending · ₹ {TV['od']:,.2f} Cr", group="Delivery"),
          card("On-time delivery", r2(otd(T) or 0), r2(otd(P) or 0) if otd(P) is not None else None, "percent", better="up",
               note="by executed MT", group="Delivery"),
          card("Cancelled", r2(T["canc"]), r2(P["canc"]), unit="MT", better="down",
               note=f"{(_ratio(T['canc'], T['qty']) or 0):.1f}% of gross orders"),
          card("Orders", len(T["ords"]), len(P["ords"]), note=f"{T['lines']:,} lines · {len(T['custs'])} customers"),
          card("Avg delay (late lines)", r2(T["dlySum"] / T["lateLines"]) if T["lateLines"] else 0, None, unit="days",
               better="down", note=f"{T['lateLines']} late lines", group="Delivery"),
          card("Fittings (Nos)", r3(T["pcsNet"]), r3(P["pcsNet"]), unit="Nos",
               note=f"{T['pcsExe']:,.0f} executed · {T['pcsPend']:,.0f} pending")]

    def res(columns, data):
        return {"columns": columns, "rows": data, "row_count": len(data), "truncated": False, "sql": sql}

    results, sections = {}, []
    # salesperson table (period)
    by: dict = {}
    for i in cur:
        by.setdefault(C["sp"][i], []).append(i)
    sp_rows = []
    for k, idx in by.items():
        q, v = _agg(D, idx), _agg(D, idx, True)
        sp_rows.append([DI["sp"][k], r3(q["net"]), r2(v["net"]), r3(q["exe"]), r3(q["pend"]), r3(q["od"]),
                        r2(otd(q)) if otd(q) is not None else None, len(q["ords"])])
    sp_rows.sort(key=lambda r: -r[2])
    results["so_sp"] = res(["Salesperson", "Net booked (MT)", "Net value (₹ Cr)", "Executed (MT)", "Pending (MT)",
                            "Overdue (MT)", "On-time %", "Orders"], sp_rows)
    sections.append({"result_id": "so_sp", "title": f"Salesperson-wise — {label}",
                     "total_columns": ["Net booked (MT)", "Net value (₹ Cr)", "Executed (MT)", "Pending (MT)", "Overdue (MT)", "Orders"],
                     "column_formats": {"On-time %": "percent"},
                     "chart": {"type": "bar", "x": "Salesperson", "y": ["Net value (₹ Cr)"], "title": "Net booked value by salesperson"}})
    # item group / division
    by = {}
    for i in cur:
        by.setdefault(C["grp"][i], []).append(i)
    g_rows = []
    for k, idx in by.items():
        q, v = _agg(D, idx), _agg(D, idx, True)
        g_rows.append([DI["grp"][k] or "—", r3(q["net"]), r2(v["net"]), r3(q["exe"]), r3(q["pend"]), r3(q["od"])])
    g_rows.sort(key=lambda r: -r[2])
    results["so_grp"] = res(["Item group", "Net booked (MT)", "Net value (₹ Cr)", "Executed (MT)", "Pending (MT)", "Overdue (MT)"], g_rows)
    sections.append({"result_id": "so_grp", "title": "Item group-wise",
                     "total_columns": ["Net booked (MT)", "Net value (₹ Cr)", "Executed (MT)", "Pending (MT)", "Overdue (MT)"]})
    # overdue lines (all open lines, whole book - not only the period)
    ODUE = DI["dues"].index("Overdue") if "Overdue" in DI["dues"] else -2
    NO = DI["um"].index("NO") if "NO" in DI["um"] else -1
    odl = [i for i in range(D["n"]) if C["dues"][i] == ODUE]
    odl.sort(key=lambda i: -C["v_pend"][i])
    results["so_overdue"] = res(["Order No", "Customer", "Salesperson", "Item group", "Delivery date", "Pending", "UM",
                                 "Pending (₹ Lakh)", "Overdue days", "LD"],
                                [[DI["ord"][C["ord"][i]], DI["cust"][C["cust"][i]], DI["sp"][C["sp"][i]], DI["grp"][C["grp"][i]],
                                  DI["dd"][C["dd"][i]], C["pend"][i], "Nos" if C["um"][i] == NO else "MT", C["v_pend"][i],
                                  C["odays"][i], DI["ld"][C["ld"][i]]] for i in odl[:25]])
    tot_od = _agg(D, odl)
    tot_odv = _agg(D, odl, True)
    sections.append({"result_id": "so_overdue", "title": f"Top 25 overdue lines (whole order book as of {today:%d-%b-%y}: "
                                                        f"{len(odl):,} lines, {tot_od['pend']:,.1f} MT, ₹ {tot_odv['pend']:,.2f} Cr)",
                     "grand_total": False})
    # SP matrix (management layout) as on the latest order date - qty = Sale Order Qty (KG), value = Mat. value
    mx_as = max(C["od"])
    per = mx_periods(mx_as)
    divs = ["SMLS", "WELDED", "LSAW", "FITTING", "OTHER"]
    div_of = [0 if re.search("seamless", g_, re.I) else 1 if re.search("welded", g_, re.I) else 2 if re.search("lsaw", g_, re.I)
              else 3 if re.search("fitting", g_, re.I) else 4 for g_ in DI["grp"]]
    dq = [[0.0] * len(per) for _ in divs]
    dvv = [[0.0] * len(per) for _ in divs]
    lo = min(p[1] for p in per)
    for i in range(D["n"]):
        d = C["od"][i]
        if d < lo or d > mx_as or C["um"][i] == NO:
            continue
        k = div_of[C["grp"][i]]
        for j, (_, pa_, pb_) in enumerate(per):
            if pa_ <= d <= pb_:
                dq[k][j] += C["qty"][i]
                dvv[k][j] += C["v_net"][i] / 100
    mrows = [[divs[k]] + [x for j in range(7) for x in (r2(dq[k][j]), r2(dvv[k][j]))] for k in range(len(divs))]
    mrows.append(["Grand Total"] + [x for j in range(7) for x in (r2(sum(dq[k][j] for k in range(5))), r2(sum(dvv[k][j] for k in range(5))))])
    mcols = ["Division"] + [c for p in per[:7] for c in (f"{p[0]} MT", f"{p[0]} ₹ Cr")]
    results["so_mx"] = res(mcols, mrows)
    tm, lm = sum(dq[k][4] for k in range(5)), sum(dq[k][7] for k in range(5))
    sections.append({"result_id": "so_mx", "title": f"SP Matrix — division summary as on {ddstr(mx_as)} (order qty, mat. value)"
                                                  + (f" · MTD vs last month same days {((tm / lm - 1) * 100):+.0f}%" if lm else ""),
                     "grand_total": False})
    if section in ("overdue", "pending", "delivery", "late"):
        order = ["so_overdue", "so_sp", "so_grp", "so_mx"]
        sections.sort(key=lambda s: order.index(s["result_id"]))
    elif section in ("matrix", "sp", "salesperson"):
        order = ["so_mx", "so_sp", "so_grp", "so_overdue"]
        sections.sort(key=lambda s: order.index(s["result_id"]))

    # every order line of the period (e.g. "yesterday's sales orders") - the detail management can tick against ERP
    LIM = 1500
    lines_i = sorted(cur, key=lambda i: (-C["od"][i], DI["ord"][C["ord"][i]]))
    results["so_lines"] = res(["Order date", "Order No", "Customer", "Salesperson", "Item group", "Item type", "Grade", "OD",
                               "UM", "Order qty", "Net qty", "Executed", "Pending", "Value (₹ Lakh)", "Order status"],
                              [[iso(C["od"][i]), DI["ord"][C["ord"][i]], DI["cust"][C["cust"][i]], DI["sp"][C["sp"][i]],
                                DI["grp"][C["grp"][i]], DI["itype"][C["itype"][i]], DI["grade"][C["grade"][i]],
                                C["odv"][i] if C["odv"][i] >= 0 else "", "Nos" if C["um"][i] == NO else "MT",
                                C["qty"][i], C["net"][i], C["exe"][i], C["pend"][i], C["v_net"][i], DI["status"][C["status"][i]]]
                               for i in lines_i[:LIM]])
    results["so_lines"]["truncated"] = len(lines_i) > LIM
    sec_lines = {"result_id": "so_lines", "title": f"Order lines booked {label} ({len(lines_i):,} lines"
                                                  + (f", first {LIM:,} shown - full list in the dashboard Data tab)" if len(lines_i) > LIM else ")"),
                 "total_columns": ["Value (₹ Lakh)"], "grand_total": True, "subtotals": False}
    if (d2 - d1).days <= 7:
        sections.insert(0, sec_lines)
    else:
        sections.append(sec_lines)
    # proof: same totals re-counted by a plain SQL on the view
    pf = proof(book, source, allowed, d1, d2, T, TV)
    if pf["rows"]:
        results["so_proof"] = res(["Figure", "VERONICA", "Direct SQL on view", "Difference", "Result"], pf["rows"])
        sections.append({"result_id": "so_proof", "title": "🔎 Data proof — VERONICA's totals vs a direct SQL count of " + source,
                         "grand_total": False, "subtotals": False,
                         "note": "Run the check query below yourself to confirm."})
    how = [["1", "Source view", source], ["2", "Rows read from view", f"{book['rows_read']:,} (at {book['loaded_at']})"],
           ["3", "Query VERONICA ran", book["sql"]],
           ["4", "Cleaning rules", "Same as Sales_Order_MIS_Generator V8: MT = KG ÷ 1000, fittings (UM NO) counted in Nos, "
                                  "value = Material value, pending below 0 = 0, order date filter on " + str(used.get("odate"))],
           ["5", "Period", f"{d1.isoformat()} to {d2.isoformat()} by order date"],
           ["6", "Check query (independent)", pf["verify_sql"] or pf["error"]],
           ["7", "Check result", "All totals match" if pf["ok"] else ("Differences found" if pf["ok"] is False else pf["error"])],
           ["8", "Checked at", pf["checked_at"]]]
    results["so_how"] = res(["Step", "What", "Detail"], how)
    sections.append({"result_id": "so_how", "title": "How VERONICA got these numbers (audit trail)", "grand_total": False,
                     "subtotals": False})
    checks = [("Every view row read (none skipped without order no / date)", D["skipped"] == 0),
              *([("Totals match a direct SQL count of the view", bool(pf["ok"]))] if pf["ok"] is not None else []),
              ("Value column (Material Value INR) present", D["hasV"]),
              ("Salesperson table = period total", abs(sum(r[1] for r in sp_rows) - T["net"]) < 0.05)]
    summary = {"period": label, "compared_with": plabel, "as_of": today.isoformat(), "lines_in_view": D["n"],
               "net_mt": r2(T["net"]), "net_cr": r2(TV["net"]), "executed_mt": r2(T["exe"]), "pending_mt": r2(T["pend"]),
               "overdue_mt": r2(T["od"]), "on_time_pct": r2(otd(T)) if otd(T) is not None else None,
               "fulfilment_pct": r2(_ratio(T["exe"], T["net"]) or 0), "cancelled_mt": r2(T["canc"]),
               "previous": {"net_mt": r2(P["net"]), "net_cr": r2(PV["net"]), "on_time_pct": r2(otd(P)) if otd(P) is not None else None} if has_prev else None,
               "top_salespersons": sp_rows[:5], "book_overdue_lines": len(odl), "book_overdue_mt": r2(tot_od["pend"]),
               "book_overdue_cr": r2(tot_odv["pend"]), "skipped_rows": D["skipped"]}
    return {"label": label, "prev_label": plabel, "unit": "MT / ₹ Cr", "columns_used": {k: (f"{v}  ({NOTES[v]})" if NOTES.get(v) else v) for k, v in used.items()},
            "results": results, "sections": sections, "kpis": kp, "files": {"dashboard": book["page"] or _page(book)}, "proof": pf,
            "summary": summary, "checks": [{"check": n, "ok": ok} for n, ok in checks], "sql": sql, "_internal": {"D": D}}
