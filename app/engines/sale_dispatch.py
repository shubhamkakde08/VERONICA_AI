"""Monthwise Sales Dispatch (Sale Invoice MIS) - the company's 'Monthwise_Sales_Dispatch_v1.html' fed from the replica.

Source: VIEW_SALE_INVOICE_PBI (one row per invoice line). The view's rows go to the page's own ingest()
(same column detection, Kg->MT and Rs->Cr rules as when an ERP export is uploaded), so the dashboard is
exactly the HTML's logic. Here we only read the period and compute the cards / tables for chat and Excel.
Default period: financial year to date (it is a month-wise report)."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from .. import config, datadb

ENGINE = "sale_dispatch"
DEFAULT_SOURCE = "VIEW_SALE_INVOICE_PBI"
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "dashboards" / "sales_dispatch_v1.html"
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class EngineError(Exception):
    pass


def norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str("" if s is None else s).lower())


def _col(H: list[str], cands: list[str], avoid: str | None = None, used: set | None = None) -> int:
    """Same rule as the page: exact normalised name first, then 'contains' (skipping the avoid pattern)."""
    used = used if used is not None else set()
    HN = [norm(h) for h in H]
    for c in cands:
        c = norm(c)
        for j, h in enumerate(HN):
            if j not in used and h == c:
                used.add(j)
                return j
    for c in cands:
        c = norm(c)
        for j, h in enumerate(HN):
            if j not in used and h and c in h and not (avoid and re.search(avoid, h)):
                used.add(j)
                return j
    return -1


def columns(H: list[str]) -> dict:
    used: set = set()
    return {
        "date": _col(H, ["Sale Bill Date", "Bill Date", "Invoice Date", "Inv Date", "Sale Date", "Date"],
                     r"due|podate|order|lrdate|lcdate|ewb|eway|delivery", used),
        "month": _col(H, ["Month"], None, used),
        "qty": _col(H, ["Dispatch Qty (MT)", "Disp Qty (MT)", "Dispatch Qty(MT)", "Disp Qty(MT)", "Dispatch Qty (Kg)", "Disp Qty(Kg)",
                        "Disp Qty (Kg)", "Dispatch Qty", "Disp Qty", "Invoice Qty", "Qty (MT)", "Qty"],
                    r"nos|pcs|mtr|meter|order|pend|rate|bal", used),
        "amt": _col(H, ["Material Value in Cr", "Material Value (Cr)", "Material Amt", "Material Amount", "Material Value", "Basic Amount",
                        "Basic Amt", "Taxable Value", "Taxable Amount", "Amount", "Value"],
                    r"rate|gst|igst|cgst|sgst|freight|grand|tcs|insurance", used),
        "div": _col(H, ["Division", "Unit", "Plant"], r"code|price|rate", used),
        "cust": _col(H, ["Customer Name", "Party Name", "Customer", "Party"], r"code|pono|po$|group|type|country|state|city|ref", used),
    }


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        s = re.sub(r"[,\s₹]", "", str(v or ""))
        try:
            return float(s)
        except ValueError:
            return 0.0


def _units(H, rows, C):
    qh, ah = norm(H[C["qty"]]), norm(H[C["amt"]])
    def med(ci):
        v = sorted(x for x in (_num(r[ci]) for r in rows[:3000]) if x > 0)
        return v[len(v) // 2] if v else 0
    q = 1000 if "kg" in qh else 1 if re.search(r"mt|ton", qh) else (1000 if med(C["qty"]) > 50 else 1)
    a = 1 if re.search(r"crore|cr$|incr", ah) else 100 if re.search(r"lakh|lac", ah) else (1e7 if med(C["amt"]) > 1000 else 1)
    return q, a


def fy_start(d: dt.date) -> dt.date:
    return dt.date(d.year if d.month >= 4 else d.year - 1, 4, 1)


def fetch(source: str, allowed: list[str], d1: dt.date, d2: dt.date):
    from .scrap_mis import _date_filter, _day
    info = datadb.describe_tables([source], allowed)[0]
    if info.get("error"):
        raise EngineError(f"{source} is not in the ERP replica yet (waiting for the Oracle -> MySQL sync)."
                          if "not found" in info["error"] else f"{source} {info['error']}")
    H = [c["name"] for c in info["columns"]]
    C = columns(H)
    if C["date"] < 0:
        raise EngineError(f"{source}: no bill / invoice date column. Columns: " + ", ".join(H))
    if C["qty"] < 0 or C["amt"] < 0:
        raise EngineError(f"{source}: dispatch qty or material value column not found. Columns: " + ", ".join(H))
    dcol = info["columns"][C["date"]]
    where, how = _date_filter(source, dcol["name"], dcol.get("type", ""), d1, d2, allowed)
    sql = f"SELECT * FROM `{source}`" + (f" WHERE {where}" if where else "")
    res = datadb.run_select(sql, allowed, max_rows=1_500_000, timeout=config.ENGINE_QUERY_TIMEOUT_SECONDS)
    if res.get("truncated"):
        raise EngineError("Too many invoice lines for one dashboard - choose a shorter period.")
    H = list(res["columns"])
    C = columns(H)
    rows = []
    for r in res["rows"]:
        d = _day(r[C["date"]])
        if d is None or not (d1 <= d <= d2):
            continue
        r = list(r)
        r[C["date"]] = d.isoformat()
        rows.append(r)
    return H, rows, C, sql, where


def dashboard(H, rows, label: str) -> bytes:
    data = [H] + rows
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str).replace("</", "<\\/")
    inj = ("<script id=\"vr-sale-data\">(function(){var A=" + js + ";"
           "var al=window.alert;window.alert=function(m){console.warn(m);var z=document.getElementById('uploadZone');"
           "if(z){z.style.display='block';z.insertAdjacentHTML('afterbegin','<p style=\"color:#c0392b;font-weight:600\">'+String(m)+'</p>');}};"
           "try{ingest(A," + json.dumps(label) + ");}catch(e){console.error(e);}finally{window.alert=al;}})();</script>\n")
    t = TEMPLATE.read_text(encoding="utf-8")
    i = t.rfind("</body>")
    return (t[:i] + inj + t[i:]).encode("utf-8")


def run(skill: dict, from_date: str, to_date: str, allowed: list[str], division: str = "BOTH") -> dict:
    st = json.loads(skill.get("sql_template") or "{}")
    source = st.get("source") or DEFAULT_SOURCE
    d1, d2 = sorted([dt.date.fromisoformat(from_date), dt.date.fromisoformat(to_date)])
    H, rows, C, sql, where = fetch(source, allowed, d1, d2)
    one = (division or "").upper()
    if one in ("U1", "U2") and C["div"] >= 0:            # division lock: keep only that unit's invoices
        rows = [r for r in rows if re.search(rf"\b{one}\b", str(r[C['div']] or "").upper())]
    label = f"{d1:%d-%b-%y} to {d2:%d-%b-%y}"
    if not rows:
        raise EngineError(f"No sale invoice lines in {source} for {label}.")
    qd, ad = _units(H, rows, C)
    by_m: dict = {}
    by_c: dict = {}
    tq = ta = 0.0
    for r in rows:
        d = dt.date.fromisoformat(r[C["date"]])
        q, a = _num(r[C["qty"]]) / qd, _num(r[C["amt"]]) / ad
        k = (d.year, d.month)
        m = by_m.setdefault(k, [0.0, 0.0, 0])
        m[0] += q; m[1] += a; m[2] += 1
        if C["cust"] >= 0:
            c = by_c.setdefault(str(r[C["cust"]] or "(Blank)").strip(), [0.0, 0.0])
            c[0] += q; c[1] += a
        tq += q; ta += a
    rk = lambda a, q: round(a * 1e4 / q, 0) if q > 0.0005 else None          # Cr / MT -> Rs per kg
    res = lambda cols, data: {"columns": cols, "rows": data, "row_count": len(data), "truncated": False, "sql": sql}
    mrows = [[f"{MON[m - 1]}-{str(y)[2:]}", round(v[0], 3), round(v[1], 4), rk(v[1], v[0]), v[2]] for (y, m), v in sorted(by_m.items())]
    results = {"sd_month": res(["Month", "Dispatch (MT)", "Value (₹ Cr)", "Realisation (₹/kg)", "Lines"], mrows)}
    sections = [{"result_id": "sd_month", "title": f"Monthwise sales dispatch — {label}",
                 "total_columns": ["Dispatch (MT)", "Value (₹ Cr)", "Lines"],
                 "chart": {"type": "bar", "x": "Month", "y": ["Dispatch (MT)"], "title": "Dispatch MT by month"}}]
    if by_c:
        top = sorted(by_c.items(), key=lambda kv: -kv[1][1])[:20]
        results["sd_cust"] = res(["Customer", "Dispatch (MT)", "Value (₹ Cr)", "Share %"],
                                 [[k, round(v[0], 3), round(v[1], 4), round(v[1] / ta * 100, 2) if ta else 0] for k, v in top])
        sections.append({"result_id": "sd_cust", "title": "Top 20 customers by value", "grand_total": False,
                         "column_formats": {"Share %": "percent"}})
    checks = [("Monthly table = period total", abs(sum(r[1] for r in mrows) - tq) < 0.01)]
    if where:
        try:
            r = datadb.run_select(f"SELECT COUNT(*) FROM `{source}` WHERE {where}", allowed, max_rows=2,
                                  timeout=config.ENGINE_QUERY_TIMEOUT_SECONDS)
            checks.append(("Every invoice line of the period read (direct SQL COUNT)", int(r["rows"][0][0] or 0) >= len(rows)))
        except Exception:
            pass
    kp = [{"label": "Dispatch", "value": round(tq, 2), "unit": "MT", "format": "number", "group": "Sales dispatch"},
          {"label": "Sale value", "value": round(ta, 2), "unit": "₹ Cr", "format": "number", "group": "Sales dispatch"},
          {"label": "Realisation", "value": rk(ta, tq) or 0, "unit": "₹/kg", "format": "number", "group": "Sales dispatch"},
          {"label": "Invoice lines", "value": len(rows), "format": "number", "group": "Sales dispatch"}]
    summary = {"period": label, "dispatch_mt": round(tq, 2), "value_cr": round(ta, 2), "realisation_rs_kg": rk(ta, tq),
               "months": [[m[0], m[1], m[2]] for m in mrows], "top_customers": results.get("sd_cust", {}).get("rows", [])[:5]}
    return {"label": label, "prev_label": "", "unit": "MT / ₹ Cr",
            "columns_used": {k: (H[v] if v >= 0 else "— not found —") for k, v in C.items()},
            "results": results, "sections": sections, "kpis": kp, "summary": summary,
            "files": {"dashboard": dashboard(H, rows, f"{source} · {label}")},
            "checks": [{"check": n, "ok": ok} for n, ok in checks], "sql": sql,
            "row_counts": {k: v["row_count"] for k, v in results.items()}}
