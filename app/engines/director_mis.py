"""Director MIS - one page that reads ALL taught report engines for a period and analyses them together.

Runs the existing engines (sales order book, sales dispatch, final production / QC, scrap MIS, job-card scrap,
issues / costing) for the same period - each with its own verified logic and data checks - then adds the
cross-department view a director needs: health per area, what got better / worse vs the previous period,
book-to-bill, production vs dispatch, issue cost per MT produced, realisation, and the financial-year
dispatch trend. Nothing here is estimated: every number is a card from one of the engines, or a ratio of two
such cards (the formula is printed next to it). Areas whose view is not synced yet are listed, not guessed."""
from __future__ import annotations

import datetime as dt
import html
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

from .. import config, store

ENGINE = "director_mis"
log = logging.getLogger("veronica.director_mis")

# (taught report, engine, area title, live dashboard name, icon)
SUBS = [
    ("sale_order_dashboard", "sales_order", "Order book", "sales-order", "📑"),
    ("sales_dispatch_dashboard", "sale_dispatch", "Sales dispatch", "sales-dispatch", "🚚"),
    ("final_production_rejection_report", "final_production", "Production & QC", "final-production", "🏭"),
    ("scrap_mis_report", "scrap_mis", "Scrap MIS", "scrap-mis", "♻️"),
    ("jobcardwise_scrap", "jobcard_scrap", "Job-card scrap", "jobcard-scrap", "🧾"),
    ("issue_dashboard", "issue", "Issues & costing", "issue", "📦"),
]


class EngineError(Exception):
    pass


# ------------------------------------------------------------------ helpers
def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def change(k: dict) -> dict | None:
    """Change of a card vs its previous value: size, unit (% or pts), and whether it is good or bad."""
    v, p = _num(k.get("value")), _num(k.get("previous"))
    if v is None or p is None or v == p:
        return None
    d = v - p
    if k.get("format") == "percent":
        size, unit = abs(d), "pts"
    elif p:
        size, unit = abs(d) / abs(p) * 100, "%"
    else:
        return None
    better = k.get("better")
    good = None if not better else ((d > 0) == (better == "up"))
    return {"up": d > 0, "size": round(size, 2), "cu": unit, "good": good}


def find(kpis: list[dict], pattern: str, group: str | None = None) -> dict | None:
    """First card whose label matches; prefer the company-level / overall group when there are several."""
    hits = [k for k in kpis if re.search(pattern, k.get("label", ""), re.I) and _num(k.get("value")) is not None]
    if group:
        g = [k for k in hits if re.search(group, k.get("group") or "", re.I)]
        hits = g or hits
    return hits[0] if hits else None


def fmt(v, unit: str = "", fmt_: str = "number") -> str:
    if v is None:
        return "–"
    if fmt_ == "percent":
        return f"{v:,.2f}%"
    s = f"{v:,.2f}" if abs(v) < 1000 else f"{v:,.0f}"
    return html.escape(f"{s} {unit or ''}".strip())


# ------------------------------------------------------------------ run every area
def _run_one(spec, d1: str, d2: str, allowed: list[str], user: dict | None, division: str,
             lines: list | None = None, plants: list | None = None) -> dict:
    import inspect
    from . import load
    skill_name, eng_name, title, dash_name, icon = spec
    base = {"title": title, "dash": dash_name, "icon": icon, "skill": skill_name}
    sk = store.get_skill(skill_name)
    if not sk:
        return {**base, "error": "report not taught on this server"}
    if user is not None and not store.skill_allowed(sk, user):
        return {**base, "error": "not in this user's access", "hidden": True}
    eng = load().get(eng_name)
    if not eng:
        return {**base, "error": "engine not installed"}
    params = inspect.signature(eng.run).parameters
    one = (division or "").upper() if (division or "").upper() in ("U1", "U2") else ""
    locks = {"division": one, "lines": lines or None, "plants": plants or None}
    missing = [k for k, v in locks.items() if v and k not in params]
    if missing:                                   # this area cannot be cut to the user's division / lines / plants
        return {**base, "error": "not available for your access (cannot be limited to your " + ", ".join(missing) + ")",
                "hidden": True}
    kw = {k: v for k, v in {"division": division, "lines": lines, "plants": plants}.items() if k in params and (v or k == "division")}
    t0 = time.time()
    try:
        out = eng.run(sk, d1, d2, allowed, **kw)
    except Exception as e:                                    # missing view, no rows, DB error: shown, never guessed
        log.warning("director MIS: %s failed: %s", title, e)
        return {**base, "error": str(e)[:240]}
    return {**base, "label": out.get("label"), "prev_label": out.get("prev_label"), "kpis": out.get("kpis") or [],
            "checks": out.get("checks") or [], "summary": out.get("summary") or {}, "sql": out.get("sql") or "",
            "rows": sum((r or {}).get("row_count", 0) for r in (out.get("results") or {}).values()),
            "seconds": round(time.time() - t0, 1)}


def fy_months(allowed: list[str], user: dict | None, upto: dt.date, division: str = "BOTH",
              lines: list | None = None, plants: list | None = None) -> list:
    """Financial-year dispatch by month (from the sales dispatch engine) - the trend line of the page."""
    fy = dt.date(upto.year if upto.month >= 4 else upto.year - 1, 4, 1)
    r = _run_one(SUBS[1], fy.isoformat(), upto.isoformat(), allowed, user, division, lines, plants)
    return [] if r.get("error") else (r["summary"].get("months") or [])


# ------------------------------------------------------------------ analysis
def analyse(areas: list[dict]) -> dict:
    by = {a["title"]: a for a in areas if not a.get("error")}
    K = lambda area, pat, grp=None: find(by[area]["kpis"], pat, grp) if area in by else None
    booked, disp = K("Order book", r"^net booked$"), K("Sales dispatch", r"^dispatch$")
    value, real = K("Sales dispatch", r"^sale value$"), K("Sales dispatch", r"^realisation$")
    prod = [K("Scrap MIS", r"^welded production$"), K("Scrap MIS", r"^l-saw"), K("Scrap MIS", r"^seamless production$")]
    prod_mt = sum(p["value"] for p in prod if p) if any(prod) else None
    issue = K("Issues & costing", r"^issue value$")
    qc_prod, qc_tot, qc_rejp = (K("Production & QC", r"^inspection qty", "compan|overall|total"),
                                K("Production & QC", r"^total inspection", "compan|overall|total"),
                                K("Production & QC", r"subtotal rejp", "compan|overall|total"))
    ratios = []

    def ratio(name, val, unit, how, good_when=""):
        if val is not None:
            ratios.append({"name": name, "value": round(val, 2), "unit": unit, "how": how, "hint": good_when})
    if booked and disp and disp["value"]:
        ratio("Book-to-bill", booked["value"] / disp["value"], "×",
              f"Net booked {fmt(booked['value'], 'MT')} ÷ dispatch {fmt(disp['value'], 'MT')}",
              "above 1 = order book growing faster than we ship")
    if prod_mt and disp and disp["value"]:
        ratio("Production vs dispatch", prod_mt / disp["value"], "×",
              f"Welded + L-Saw + Seamless production {fmt(prod_mt, 'MT')} ÷ dispatch {fmt(disp['value'], 'MT')}",
              "above 1 = stock building up; below 1 = shipping from stock")
    if issue and prod_mt:
        ratio("Issue cost per MT produced", issue["value"] * 1e5 / prod_mt, "₹/MT",
              f"Issue value {fmt(issue['value'], '₹ Lakh')} ÷ production {fmt(prod_mt, 'MT')}", "lower is better")
    if real:
        ratio("Realisation", real["value"], "₹/kg", f"Sale value {fmt(value['value'] if value else None, '₹ Cr')} ÷ dispatch", "")
    if qc_rejp and qc_tot and qc_tot["value"]:
        ratio("QC REJP share", qc_rejp["value"] / qc_tot["value"] * 100, "%",
              f"Subtotal REJP {fmt(qc_rejp['value'])} ÷ total inspection {fmt(qc_tot['value'])}", "lower is better")

    moves = []
    for a in areas:
        if a.get("error"):
            continue
        good = bad = 0
        for k in a["kpis"]:
            c = change(k)
            if not c or c["good"] is None or c["size"] < 0.5:
                continue
            good += c["good"]
            bad += not c["good"]
            g = k.get("group") or ""
            moves.append({"area": a["title"], "icon": a["icon"], "label": k["label"] + (f" · {g}" if g and g not in (a["title"],) and not g.startswith("Company") else ""),
                          "value": k["value"], "previous": k["previous"], "unit": k.get("unit", ""), "format": k.get("format", "number"),
                          **c})
        a["health"] = "red" if bad >= good + 2 else ("amber" if bad > good else "green")
        a["good"], a["bad"] = good, bad
    moves.sort(key=lambda m: -m["size"])
    worse = [m for m in moves if not m["good"]][:6]
    better = [m for m in moves if m["good"]][:6]
    return {"ratios": ratios, "worse": worse, "better": better, "prod_mt": prod_mt}


# ------------------------------------------------------------------ page
CSS = """
:root{--bg:#050b16;--card:#0b1628;--card2:#0e1d33;--line:#1d3557;--tx:#e8f1fb;--mut:#8aa0bd;--ac:#4fb6ff;--good:#3fd29b;--bad:#ff6b7f;--warn:#f5b84a;--bar:#2f8fe0}
[data-theme=light]{--bg:#f4f7fb;--card:#ffffff;--card2:#f0f4fa;--line:#d6e0ee;--tx:#11223a;--mut:#5d708b;--ac:#0b6fd1;--good:#13955f;--bad:#cf2f48;--warn:#b7791f;--bar:#2f7fd0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.45 "Segoe UI",system-ui,sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:22px 18px 40px}
h1{margin:0;font-size:22px;letter-spacing:.02em}h2{font-size:15px;margin:26px 0 10px;letter-spacing:.08em;text-transform:uppercase;color:var(--mut)}
.top{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap}.top .sub{color:var(--mut)}.top .sp{flex:1}
.tbtn{background:var(--card);color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:6px 12px;cursor:pointer;font:inherit}
.lead{margin-top:14px;padding:14px 16px;border:1px solid var(--line);border-left:4px solid var(--ac);border-radius:10px;background:var(--card);font-size:15px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.area{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;position:relative}
.area .h{display:flex;align-items:center;gap:8px;font-weight:700}.area .dot{width:10px;height:10px;border-radius:50%;margin-left:auto}
.dot.green{background:var(--good)}.dot.amber{background:var(--warn)}.dot.red{background:var(--bad)}
.area .k{display:flex;justify-content:space-between;gap:8px;margin-top:8px;font-size:13px}.area .k b{font-size:15px}
.area .k span{color:var(--mut)}.area a{color:var(--ac);font-size:12px;text-decoration:none;display:inline-block;margin-top:10px}
.area.err{opacity:.75}.area.err .msg{color:var(--mut);font-size:12.5px;margin-top:8px}
.ch{font-size:12px;font-weight:600;white-space:nowrap}.ch.g{color:var(--good)}.ch.b{color:var(--bad)}.ch.n{color:var(--mut)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:820px){.two{grid-template-columns:1fr}}
.list{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:6px 14px}
.list .row{display:flex;gap:10px;align-items:center;padding:9px 0;border-bottom:1px solid var(--line)}.list .row:last-child{border:0}
.list .row .t{flex:1}.list .row .t small{display:block;color:var(--mut)}.list .empty{color:var(--mut);padding:12px 0}
.ratios{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}
.ratio{background:var(--card2);border:1px solid var(--line);border-radius:12px;padding:14px}.ratio .v{font-size:24px;font-weight:700;color:var(--ac)}
.ratio .n{font-weight:600}.ratio .how{color:var(--mut);font-size:12px;margin-top:6px}.ratio .hint{font-size:12px;margin-top:4px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:13px}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:right}th{color:var(--mut);font-weight:600;background:var(--card2)}
td:first-child,th:first-child{text-align:left}tr.grp td{background:var(--card2);font-weight:700;text-align:left}
.trend{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}.trend svg{width:100%;height:auto;display:block}
.trend text{fill:var(--mut);font-size:11px}.trend .val{fill:var(--tx);font-weight:600}.trend rect{fill:var(--bar)}
.foot{color:var(--mut);font-size:12px;margin-top:24px}.ok{color:var(--good)}.no{color:var(--bad)}
@media print{.tbtn{display:none}body{background:#fff}}
"""


def _ch(c: dict | None) -> str:
    if not c:
        return '<span class="ch n">–</span>'
    cls = "n" if c["good"] is None else ("g" if c["good"] else "b")
    return f'<span class="ch {cls}">{"▲" if c["up"] else "▼"} {c["size"]:.2f} {c["cu"]}</span>'


def page(areas: list[dict], ana: dict, months: list, label: str, prev_label: str) -> bytes:
    e = html.escape
    ok_areas = [a for a in areas if not a.get("error")]
    reds = [a["title"] for a in ok_areas if a.get("health") == "red"]
    greens = [a["title"] for a in ok_areas if a.get("health") == "green"]
    lead = (f"{len(ok_areas)} of {len([a for a in areas if not a.get('hidden')])} areas read for <b>{e(label)}</b>. "
            + (f"Needs attention: <b>{e(', '.join(reds))}</b>. " if reds else "No area is clearly worse than last period. ")
            + (f"Doing well: {e(', '.join(greens))}." if greens else ""))
    cards = []
    for a in areas:
        if a.get("hidden"):
            continue
        if a.get("error"):
            cards.append(f'<div class="area err"><div class="h">{a["icon"]} {e(a["title"])}</div>'
                         f'<div class="msg">Not available: {e(a["error"][:150] + ("…" if len(a["error"]) > 150 else ""))}</div></div>')
            continue
        main = [k for k in a["kpis"] if _num(k.get("value")) is not None][:4]
        rows = "".join(f'<div class="k"><span>{e(k["label"])}</span><b>{fmt(k["value"], k.get("unit", ""), k.get("format", "number"))}</b>{_ch(change(k))}</div>'
                       for k in main)
        cards.append(f'<div class="area"><div class="h">{a["icon"]} {e(a["title"])}<span class="dot {a.get("health", "green")}" '
                     f'title="{a.get("good", 0)} better · {a.get("bad", 0)} worse"></span></div>{rows}'
                     f'<a class="dl" data-dash="{a["dash"]}" href="#">Open full {e(a["title"])} dashboard →</a></div>')

    def mlist(ms, empty):
        if not ms:
            return f'<div class="list"><div class="empty">{empty}</div></div>'
        return '<div class="list">' + "".join(
            f'<div class="row"><span>{m["icon"]}</span><div class="t">{e(m["label"])}<small>{e(m["area"])} · now '
            f'{fmt(m["value"], m["unit"], m["format"])} vs {fmt(m["previous"], m["unit"], m["format"])}</small></div>{_ch(m)}</div>'
            for m in ms) + "</div>"
    ratios = "".join(f'<div class="ratio"><div class="n">{e(r["name"])}</div><div class="v">{r["value"]:,.2f} <small>{e(r["unit"])}</small></div>'
                     f'<div class="how">= {e(r["how"])}</div>' + (f'<div class="hint">{e(r["hint"])}</div>' if r["hint"] else "") + "</div>"
                     for r in ana["ratios"]) or '<div class="list"><div class="empty">Needs at least two areas with data.</div></div>'
    trend = ""
    if months:
        W, H, pad = 900, 230, 34
        mx = max((m[1] or 0) for m in months) or 1
        bw = (W - 2 * pad) / len(months)
        bars = []
        for i, m in enumerate(months):
            h = (m[1] or 0) / mx * (H - 2 * pad)
            x = pad + i * bw
            bars.append(f'<rect x="{x + bw * .18:.1f}" y="{H - pad - h:.1f}" width="{bw * .64:.1f}" height="{h:.1f}" rx="4"/>'
                        f'<text class="val" x="{x + bw / 2:.1f}" y="{H - pad - h - 6:.1f}" text-anchor="middle">{m[1]:,.0f}</text>'
                        f'<text x="{x + bw / 2:.1f}" y="{H - pad + 16:.1f}" text-anchor="middle">{e(str(m[0]))}</text>'
                        f'<text x="{x + bw / 2:.1f}" y="{H - 6:.1f}" text-anchor="middle">₹{(m[2] or 0):,.1f} Cr</text>')
        trend = (f'<h2>Dispatch this financial year (MT by month, ₹ Cr below)</h2><div class="trend">'
                 f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Dispatch MT by month">{"".join(bars)}</svg></div>')
    det = []
    for a in ok_areas:
        det.append(f'<tr class="grp"><td colspan="4">{a["icon"]} {e(a["title"])} · {e(a.get("label") or "")}'
                   + (f' <span style="font-weight:400;color:var(--mut)">vs {e(a["prev_label"])}</span>' if a.get("prev_label") else "") + "</td></tr>")
        for k in a["kpis"]:
            if _num(k.get("value")) is None:
                continue
            g = k.get("group") or ""
            det.append(f'<tr><td>{e(k["label"])}{(" <small style=color:var(--mut)>· " + e(g) + "</small>") if g and g != a["title"] else ""}</td>'
                       f'<td>{fmt(k["value"], k.get("unit", ""), k.get("format", "number"))}</td>'
                       f'<td>{fmt(_num(k.get("previous")), k.get("unit", ""), k.get("format", "number"))}</td><td>{_ch(change(k))}</td></tr>')
    checks = "".join(f'<div>{a["icon"]} {e(a["title"])}: '
                     + (f'<span class="ok">✔ {len(a["checks"])} data checks passed</span>' if all(c.get("ok") for c in a["checks"])
                        else f'<span class="no">⚠ {sum(not c.get("ok") for c in a["checks"])} check(s) failed</span>')
                     + f' · {a["rows"]:,} rows · {a["seconds"]} s</div>' for a in ok_areas)
    built = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).strftime("%d-%m-%Y %H:%M IST")
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Director MIS · {e(label)}</title><style>{CSS}</style></head><body><div class="wrap">
<div class="top"><div><h1>Director MIS</h1><div class="sub">{e(label)}{(" · compared with " + e(prev_label)) if prev_label else ""} · built {built}</div></div>
<div class="sp"></div><button class="tbtn" id="thm" type="button">☀ Light</button><button class="tbtn" type="button" onclick="print()">⎙ Print / PDF</button></div>
<div class="lead">{lead}</div>
<h2>Health by area</h2><div class="grid">{"".join(cards)}</div>
<h2>Cross-department view</h2><div class="ratios">{ratios}</div>
<div class="two"><div><h2>Got worse</h2>{mlist(ana["worse"], "Nothing got worse by 0.5 or more.")}</div>
<div><h2>Got better</h2>{mlist(ana["better"], "No clear improvement yet.")}</div></div>
{trend}
<h2>All figures</h2><table><thead><tr><th>Figure</th><th>Now</th><th>Previous</th><th>Change</th></tr></thead><tbody>{"".join(det)}</tbody></table>
<div class="foot"><b>How these numbers were made.</b> Each area is the company's own taught report, run for this period with its own data checks;
the cross-department figures are ratios of those cards (formula under each). ▲▼ colours follow what is good for that figure (scrap down = green).
<div style="margin-top:8px">{checks}</div></div></div>
<script>
(function(){{var r=document.documentElement,b=document.getElementById('thm');
function set(t){{r.dataset.theme=t;b.textContent=t==='light'?'🌙 Dark':'☀ Light';try{{localStorage.setItem('dm_theme',t)}}catch(e){{}}}}
var s='dark';try{{s=localStorage.getItem('dm_theme')||'dark'}}catch(e){{}}set(s);b.onclick=function(){{set(r.dataset.theme==='light'?'dark':'light')}};
var q=new URLSearchParams(location.search),k=q.get('k');
document.querySelectorAll('a.dl').forEach(function(a){{if(!k){{a.style.display='none';return}}
var u='/dash/'+a.dataset.dash+'?k='+encodeURIComponent(k);['from','to','month'].forEach(function(p){{if(q.get(p))u+='&'+p+'='+encodeURIComponent(q.get(p))}});a.href=u;a.target='_blank'}});}})();
</script></body></html>"""
    return doc.encode("utf-8")


# ------------------------------------------------------------------ engine entry
def run(skill: dict, from_date: str, to_date: str, allowed: list[str], division: str = "BOTH", user: dict | None = None,
        lines: list | None = None, plants: list | None = None) -> dict:
    d1, d2 = sorted([dt.date.fromisoformat(from_date), dt.date.fromisoformat(to_date)])
    label = f"{d1:%d-%b-%y} to {d2:%d-%b-%y}"
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(_run_one, s, d1.isoformat(), d2.isoformat(), allowed, user, division, lines, plants) for s in SUBS]
        fy = pool.submit(fy_months, allowed, user, d2, division, lines, plants)
        areas = [f.result() for f in futs]
        months = fy.result()
    if all(a.get("error") for a in areas):
        raise EngineError("No report area could be read for " + label + ": "
                          + "; ".join(f"{a['title']} - {a['error']}" for a in areas if not a.get("hidden")))
    ana = analyse(areas)
    prev = next((a.get("prev_label") for a in areas if not a.get("error") and a.get("prev_label")), "")
    sql = "\n\n".join(f"-- {a['title']}\n{a['sql'][:3000]}" for a in areas if not a.get("error") and a.get("sql"))
    res = lambda cols, rows: {"columns": cols, "rows": rows, "row_count": len(rows), "truncated": False, "sql": sql[:2000]}
    results = {
        "dm_health": res(["Area", "Health", "Better", "Worse", "Status"],
                         [[a["title"], a.get("health", "-") if not a.get("error") else "-", a.get("good", 0), a.get("bad", 0),
                           "read" if not a.get("error") else "not available: " + a["error"][:80]] for a in areas if not a.get("hidden")]),
        "dm_ratios": res(["Figure", "Value", "Unit", "How"], [[r["name"], r["value"], r["unit"], r["how"]] for r in ana["ratios"]]),
        "dm_moves": res(["Area", "Figure", "Now", "Previous", "Change", "Good?"],
                        [[m["area"], m["label"], m["value"], m["previous"], f"{'+' if m['up'] else '-'}{m['size']} {m['cu']}",
                          "better" if m["good"] else "worse"] for m in ana["worse"] + ana["better"]]),
    }
    sections = [{"result_id": "dm_health", "title": f"Health by area — {label}", "grand_total": False},
                {"result_id": "dm_ratios", "title": "Cross-department view", "grand_total": False},
                {"result_id": "dm_moves", "title": "Biggest changes vs previous period", "grand_total": False}]
    kp = []
    for a in areas:
        if a.get("error"):
            continue
        for k in [k for k in a["kpis"] if _num(k.get("value")) is not None][:2]:
            kp.append({**k, "group": a["title"]})
    for r in ana["ratios"]:
        kp.append({"label": r["name"], "value": r["value"], "unit": r["unit"], "format": "number", "group": "Cross-department"})
    checks = [{"check": f"{a['title']}: its own data checks", "ok": all(c.get("ok") for c in a["checks"])}
              for a in areas if not a.get("error")]
    summary = {"period": label, "compared_with": prev,
               "areas": {a["title"]: ({"not_available": a["error"]} if a.get("error") else
                                      {"health": a.get("health"), "kpis": [{x: k.get(x) for x in ("label", "value", "unit", "previous", "group")}
                                                                            for k in a["kpis"][:8]]})
                         for a in areas if not a.get("hidden")},
               "cross_department": ana["ratios"], "got_worse": ana["worse"], "got_better": ana["better"],
               "dispatch_fy_months": months}
    return {"label": label, "prev_label": prev, "unit": "mixed", "columns_used": {}, "results": results,
            "sections": sections, "kpis": kp, "summary": summary,
            "files": {"dashboard": page(areas, ana, months, label, prev)},
            "checks": checks, "sql": sql, "row_counts": {k: v["row_count"] for k, v in results.items()}}
