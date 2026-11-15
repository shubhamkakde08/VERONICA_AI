"""Live dashboards: the company's own HTML dashboards, filled from the database on every open.

HODs get a link (web button or Telegram). No Excel download, no upload: the server runs the report engine
for the chosen period and returns the HTML tool with the data already loaded.

Links are signed: /dash?k=<user.expiry.signature>  - valid DASH_LINK_HOURS, tied to one user, so the
same role rules (taught-report access, private views) apply as in chat.
"""
from __future__ import annotations

import base64
import calendar
import datetime as dt
import hashlib
import hmac
import html
import json
import logging
import secrets
import threading
import time
from zoneinfo import ZoneInfo

from . import config, store, vendor

log = logging.getLogger("veronica.dash")

# name in URL -> (skill name, engine module, title, extra options)
DASHBOARDS = {
    "final-production": ("final_production_rejection_report", "final_production", "Final Production / Rejection",
                         "QC final inspection · PROD + REJP · Welded U1 / Seamless U2"),
    "jobcard-scrap": ("jobcardwise_scrap", "jobcard_scrap", "Job Cardwise Scrap %",
                      "Black Bar → Bright Bar · Bright Bar → Hollow · Hollow → Seamless"),
    "scrap-mis": ("scrap_mis_report", "scrap_mis", "Scrap MIS",
                  "Welded · L-Saw · Seamless · Slitting · Final cutting · M2M"),
    "sales-order": ("sale_order_dashboard", "sales_order", "Sales Order MIS",
                    "Order book · pending · late delivery · SP Matrix · customers · grades"),
    "issue": ("issue_dashboard", "issue", "Issue / Costing",
              "Store issues · plant · department · cost centre · equipment · items"),
    "sales-dispatch": ("sales_dispatch_dashboard", "sale_dispatch", "Monthwise Sales Dispatch",
                       "Sale invoices · MT · ₹ Cr · realisation · month · customer · grade · product (admin / manager)"),
    "director-mis": ("director_mis", "director_mis", "Director MIS",
                     "All reports analysed together · health by area · cross-department ratios · biggest changes (directors / admin)"),
}
FY_DEFAULT = {"sales-dispatch"}       # month-wise reports: the plain link opens the financial year to date
SUMMARY_ONLY = {"director-mis"}       # built from the other dashboards - left out of the home-screen briefing


# ------------------------------------------------------------------ signed links
def _secret() -> bytes:
    p = config.OUTPUT_DIR / ".dash_secret"
    if not p.exists():
        p.write_text(secrets.token_hex(32))
    return p.read_text().strip().encode()


def make_token(user_id: int, hours: int | None = None) -> str:
    exp = int(time.time()) + 3600 * (hours or config.DASH_LINK_HOURS)
    msg = f"{user_id}.{exp}"
    sig = hmac.new(_secret(), msg.encode(), hashlib.sha256).digest()[:18]
    return msg + "." + base64.urlsafe_b64encode(sig).decode().rstrip("=")


def check_token(k: str) -> dict | None:
    try:
        uid, exp, sig = k.split(".")
        good = base64.urlsafe_b64encode(hmac.new(_secret(), f"{uid}.{exp}".encode(), hashlib.sha256).digest()[:18]).decode().rstrip("=")
        if not hmac.compare_digest(sig, good) or int(exp) < time.time():
            return None
        u = store.get_user(int(uid))
        return u if u and u.get("active", True) else None
    except Exception:
        return None


def link(user: dict, name: str = "", **params) -> str:
    q = "&".join(f"{a}={b}" for a, b in params.items() if b)
    return f"{config.PUBLIC_BASE_URL}/dash{('/' + name) if name else ''}?k={make_token(user['id'])}" + (f"&{q}" if q else "")


# ------------------------------------------------------------------ periods
def month_range(ym: str | None) -> tuple[dt.date, dt.date, str]:
    today = dt.datetime.now(ZoneInfo(config.TIMEZONE)).date()
    if ym:
        y, m = map(int, ym.split("-"))
    else:
        y, m = today.year, today.month
    d1 = dt.date(y, m, 1)
    last = dt.date(y, m, calendar.monthrange(y, m)[1])
    d2 = min(last, today) if (y, m) == (today.year, today.month) else last
    return d1, d2, f"{y:04d}-{m:02d}"


def custom_range(d1: str | None, d2: str | None) -> tuple[dt.date, dt.date, str] | None:
    """User-typed period (From / To). Accepts 2026-10-01 or 01-10-2026; max one year; never past today."""
    def parse(v):
        v = (v or "").strip()
        for f in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
            try:
                return dt.datetime.strptime(v, f).date()
            except ValueError:
                pass
        return None
    a, b = parse(d1), parse(d2)
    if not a or not b:
        return None
    today = dt.datetime.now(ZoneInfo(config.TIMEZONE)).date()
    if a > b:
        a, b = b, a
    b = min(b, today)
    if a > b:
        raise ValueError("That period is in the future.")
    if (b - a).days > 366 * 5 + 2:
        raise ValueError("Please pick a period of five years or less.")
    return a, b, f"{a.year:04d}-{a.month:02d}"


def months_back(n: int = 6) -> list[str]:
    today = dt.datetime.now(ZoneInfo(config.TIMEZONE)).date()
    out, y, m = [], today.year, today.month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out


# ------------------------------------------------------------------ data ready? (a new view appears only after the ERP sync copies it)
def missing_views(sk: dict) -> list[str]:
    """Views this dashboard needs that are not in the MySQL replica yet ([] = ready)."""
    from . import datadb
    try:
        st = json.loads(sk.get("sql_template") or "{}")
        need = [st["source"]] if isinstance(st, dict) and isinstance(st.get("source"), str) and st["source"].strip() else []
        if not need:                               # multi-view engines (Scrap MIS) handle missing views themselves
            return []
        have = {t.lower() for t in datadb._all_tables()}
        miss = [v for v in need if v.lower() not in have]
        if miss:                                   # maybe the sync just created it - look again once
            datadb.refresh_schema_cache()
            have = {t.lower() for t in datadb._all_tables()}
            miss = [v for v in need if v.lower() not in have]
        return miss
    except Exception:
        return []


class NotReady(PermissionError):
    pass


# ------------------------------------------------------------------ build (cached a few minutes)
_cache: dict = {}
_lock = threading.Lock()


def briefing(user: dict) -> dict:
    """Today's pulse for the home screen: this month's key numbers per taught engine + the biggest changes."""
    cards, notes = [], []
    for name, (skill, _, title, _sub) in DASHBOARDS.items():
        if name in SUMMARY_ONLY:
            continue
        sk = store.get_skill(skill)
        if not sk or not store.skill_allowed(sk, user) or missing_views(sk):
            continue
        try:
            _, meta = build(user, name, None)
        except Exception as e:
            log.warning("briefing %s failed: %s", name, e)
            continue
        first = meta["kpis"][0].get("group") if meta["kpis"] else None
        main = [k for k in meta["kpis"] if k.get("group") == first][:4] or meta["kpis"][:4]
        cards.append({"name": name, "title": title, "period": meta["label"], "kpis": main,
                      "skill": skill, "checks_ok": all(c["ok"] for c in meta["checks"])})
        for k in meta["kpis"]:
            if not isinstance(k.get("previous"), (int, float)) or not k.get("better"):
                continue
            d = k["value"] - k["previous"]
            if not d:
                continue
            worse = (d > 0) != (k["better"] == "up")
            size = abs(d) if k.get("format") == "percent" else (abs(d) / abs(k["previous"]) * 100 if k["previous"] else 0)
            unit = "pts" if k.get("format") == "percent" else "%"
            g = k.get("group") or ""
            where = (f" {g.split(' by ')[0].lower()}" if " by " in g else f" · {g}") if g and g != "Overall" and not g.startswith("Company") else ""
            notes.append({"worse": worse, "size": size, "title": title,
                          "text": f"{k['label']}{where} {'up' if d > 0 else 'down'} {size:.2f} {unit} {k.get('previous_label', 'vs last month')}",
                          "note": k.get("note", ""),
                          "ask": f"Why did {k['label']}{where} go {'up' if d > 0 else 'down'} this month? Explain the biggest contributors."})
    notes.sort(key=lambda n: (not n["worse"], -n["size"]))
    return {"cards": cards, "noticed": notes[:4],
            "at": dt.datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%H:%M")}


def build(user: dict, name: str, ym: str | None, unit: str = "kg", division: str = "BOTH",
          d_from: str | None = None, d_to: str | None = None) -> tuple[bytes, dict]:
    from . import agent
    import inspect
    from . import engines as _engines
    engines = _engines.load()
    skill_name, eng_name, title, _ = DASHBOARDS[name]
    sk = store.get_skill(skill_name)
    if not sk:
        raise PermissionError(f"The report /{skill_name} is not loaded yet (run seed-skills).")
    if not store.skill_allowed(sk, user):
        from . import security
        security.denied(user, "dashboard_blocked", f"dashboard {title}", "web")
        raise PermissionError("This dashboard is not in your access. Please contact your admin.")
    miss = missing_views(sk)
    if miss:
        raise NotReady(f"The {title} dashboard is waiting for its first ERP data sync ({', '.join(miss)}). "
                       f"It will open automatically as soon as the data arrives.")
    if name in FY_DEFAULT and not ym and not (d_from and d_to):
        t = dt.datetime.now(ZoneInfo(config.TIMEZONE)).date()
        d_from, d_to = dt.date(t.year if t.month >= 4 else t.year - 1, 4, 1).isoformat(), t.isoformat()
    d1, d2, ym = custom_range(d_from, d_to) or month_range(ym)
    role = agent.effective_role(user)
    division = role.get("division_lock") or division                  # locked users: their division only
    lines = role.get("line_lock") or []
    plants = role.get("plant_lock") or []
    key = (name, d1, d2, unit, division, tuple(lines), tuple(plants), tuple(sorted(role["allowed_tables"] or [])))
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < config.DASH_CACHE_SECONDS:
            return hit[1], hit[2]
    eng = engines.get(eng_name)
    if not eng:
        raise PermissionError(f"The {title} engine is not installed on this server.")
    kw = {k: v for k, v in {"division": division, "unit": unit, "lines": lines, "plants": plants, "user": user}.items()
          if k in inspect.signature(eng.run).parameters}
    t0 = time.time()
    out = eng.run(sk, d1.isoformat(), d2.isoformat(), role["allowed_tables"], **kw)
    page = out["files"]["dashboard"]
    meta = {"label": out["label"], "kpis": out["kpis"], "checks": out["checks"], "ym": ym,
            "d1": d1.isoformat(), "d2": d2.isoformat(), "today": dt.datetime.now(ZoneInfo(config.TIMEZONE)).date().isoformat(),
            "built": dt.datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%d-%m-%Y %H:%M"),
            "seconds": round(time.time() - t0, 1)}
    if out.get("proof") and hasattr(eng, "proof_html"):
        meta["proof_html"] = eng.proof_html(out["proof"])
        meta["data_read"] = out["proof"].get("loaded_at", "")
    page = _stamp(page, title, meta)
    with _lock:
        _cache[key] = (time.time(), page, meta)
        for k in [k for k, v in _cache.items() if time.time() - v[0] > 3600]:
            _cache.pop(k, None)
    log.info("dashboard %s %s..%s (%s) built in %.1fs for %s", name, d1, d2, division, meta["seconds"], user["name"])
    return page, meta


_IN = "background:#06213d;color:#e8f6ff;border:1px solid #1e5a8a;border-radius:6px;padding:3px 6px;font:600 12px Segoe UI,system-ui,sans-serif;color-scheme:dark"


def _stamp(page: bytes, title: str, meta: dict) -> bytes:
    """Small 'live' ribbon on top of the user's dashboard: period, refreshed time, back to all dashboards."""
    ok = all(c["ok"] for c in meta["checks"])
    bar = (f'<div style="position:sticky;top:0;z-index:99999;display:flex;gap:14px;align-items:center;flex-wrap:wrap;'
           f'padding:7px 14px;font:600 12px Segoe UI,system-ui,sans-serif;color:#e8f6ff;'
           f'background:linear-gradient(90deg,#071a33,#0b2c52);border-bottom:1px solid #1e5a8a">'
           f'<span style="color:#7fd6ff;letter-spacing:.14em">● LIVE</span><span>{html.escape(title)} · {html.escape(meta["label"])}</span>'
           f'<span style="opacity:.75;font-weight:500">refreshed {meta["built"]}{(" · data read " + meta["data_read"][-8:-3]) if meta.get("data_read") else ""} · {"✅ totals checked" if ok else "⚠️ check totals"}</span>'
           f'<form onsubmit="var u=new URL(location.href);u.searchParams.delete(\'month\');u.searchParams.delete(\'go\');'
           f'u.searchParams.set(\'from\',this.f.value);u.searchParams.set(\'to\',this.t.value);location.href=u.toString();return false" '
           f'style="margin-left:auto;display:flex;gap:6px;align-items:center;font-weight:500">'
           f'<span style="opacity:.8">Period</span>'
           f'<input name="f" type="date" required value="{meta["d1"]}" max="{meta["today"]}" style="{_IN}">'
           f'<span style="opacity:.6">to</span>'
           f'<input name="t" type="date" required value="{meta["d2"]}" max="{meta["today"]}" style="{_IN}">'
           f'<button type="submit" style="{_IN};cursor:pointer;background:#1b6fd1;border-color:#3b8cff;color:#fff;font-weight:700">Go</button></form>'
           + (f'<button type="button" onclick="var p=document.getElementById(\'vproofp\');p.style.display=p.style.display==\'block\'?\'none\':\'block\'" '
              f'style="{_IN};cursor:pointer;background:#0f3d24;border-color:#2fbf71;color:#bff5d6;font-weight:700">🔎 Proof</button>'
              if meta.get("proof_html") else "")
           + f'<a href="javascript:history.back()" style="color:#9fe3ff;text-decoration:none">← All dashboards</a></div>'
           + (f'<div id="vproofp" style="display:none;position:fixed;top:44px;right:12px;left:12px;max-width:980px;margin:auto;max-height:80vh;'
              f'overflow:auto;z-index:99999;background:#06182e;color:#e8f6ff;border:1px solid #2fbf71;border-radius:10px;padding:14px 16px;'
              f'font:13px Segoe UI,system-ui,sans-serif;box-shadow:0 12px 40px #000a">'
              f'<style>#vproofp table{{border-collapse:collapse;width:100%;margin:8px 0}}#vproofp td,#vproofp th{{border:1px solid #1e5a8a;padding:4px 8px;text-align:left}}'
              f'#vproofp pre{{white-space:pre-wrap;word-break:break-word;background:#020c18;padding:8px;border-radius:6px;font:12px Consolas,monospace;color:#9fe3ff}}'
              f'#vproofp code{{color:#9fe3ff}}</style>'
              f'<div style="float:right;cursor:pointer" onclick="this.parentNode.style.display=\'none\'">✕</div>'
              f'{meta["proof_html"]}</div>' if meta.get("proof_html") else ""))
    t = vendor.localize(page.decode("utf-8"))               # charts / fonts from VERONICA herself, not the internet
    i = t.find(">", t.lower().find("<body")) + 1
    return (t[:i] + bar + t[i:]).encode("utf-8")


# ------------------------------------------------------------------ index page
DIV_SUBS = {"U2": {"scrap-mis": "Seamless · Final cutting · M2M  (Seamless U2 only)", "final-production": "QC final inspection · PROD + REJP · Seamless U2 only"},
            "U1": {"scrap-mis": "Welded · L-Saw · Slitting · Final cutting  (Welded U1 only)", "final-production": "QC final inspection · PROD + REJP · Welded U1 only"}}


def notice_page(title: str, msg: str) -> str:
    """Calm, branded message instead of a raw error (what management sees if something is not ready)."""
    body = "".join(f"<p>{html.escape(p)}</p>" for p in msg.split("\n\n"))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(config.ASSISTANT_NAME)}</title><style>body{{margin:0;min-height:100vh;display:grid;place-items:center;font:15px/1.6 Inter,Segoe UI,system-ui,sans-serif;
color:#e8edf5;background:radial-gradient(700px 400px at 50% 0,rgba(52,140,220,.22),transparent 70%),#04070e;padding:24px}}
.c{{max-width:520px;border:1px solid rgba(120,200,255,.22);background:rgba(255,255,255,.03);border-radius:18px;padding:26px 28px}}
h1{{margin:0 0 6px;font-size:18px;letter-spacing:.06em}}p{{color:#a9b8cc;margin:8px 0}}
a{{display:inline-block;margin-top:12px;padding:9px 16px;border-radius:12px;background:linear-gradient(135deg,#7fd6ff,#3b8cff);color:#04111f;font-weight:700;text-decoration:none}}
</style></head><body><div class="c"><h1>{html.escape(title)}</h1>{body}<a href="javascript:location.reload()">Try again</a> &nbsp; <a href="javascript:history.back()" style="background:none;border:1px solid rgba(120,200,255,.35);color:#cfe7ff">← Back</a></div></body></html>"""


def index_page(user: dict, k: str) -> str:
    from . import agent
    lock = agent.effective_role(user).get("division_lock") or ""
    rows = []
    for name, (skill, _, title, sub) in DASHBOARDS.items():
        sub = DIV_SUBS.get(lock, {}).get(name, sub)
        sk = store.get_skill(skill)
        if not sk or not store.skill_allowed(sk, user):
            continue
        miss = missing_views(sk)
        if miss:                                   # not synced yet: hidden from everyone except admins
            if store.get_role(user["role"]).get("is_admin"):
                rows.append(f'<section style="opacity:.55"><div class="t"><h2>{html.escape(title)} <small style="color:#d7b36a">· admin only · waiting for data</small></h2>'
                            f'<p>{html.escape(", ".join(miss))} is not in the ERP replica yet. Other users do not see this card until the sync copies it '
                            f'(run SYNC_ISSUE_NOW.bat or wait for the daily sync).</p></div></section>')
            continue
        months = "".join(f'<a class="m" href="/dash/{name}?k={k}&month={ym}">{dt.date(int(ym[:4]), int(ym[5:]), 1):%b %Y}</a>'
                         for ym in months_back(6))
        extra = ("" if name != "jobcard-scrap" else
                 f'<a class="m alt" href="/dash/{name}?k={k}&unit=mt">This month in MT</a>')
        today = dt.datetime.now(ZoneInfo(config.TIMEZONE)).date()
        custom = (f'<form class="cr" method="get" action="/dash/{name}"><input type="hidden" name="k" value="{html.escape(k)}">'
                  + f'<label>From <input type="date" name="from" required value="{today.replace(day=1).isoformat()}" max="{today.isoformat()}"></label>'
                  f'<label>To <input type="date" name="to" required value="{today.isoformat()}" max="{today.isoformat()}"></label>'
                  f'<button type="submit">Open this period →</button></form>')
        rows.append(f'<section><div class="t"><h2>{html.escape(title)}</h2><p>{html.escape(sub)}</p></div>'
                    f'<a class="go" href="/dash/{name}?k={k}">{"Open financial year to date" if name in FY_DEFAULT else "Open this month"} →</a><div class="ms">{months}{extra}</div>{custom}</section>')
    body = "".join(rows) or "<p class='e'>No dashboards are available for your role yet.</p>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(config.ASSISTANT_NAME)} · Live dashboards</title><style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;font:14px/1.5 Inter,Segoe UI,system-ui,sans-serif;color:#e8edf5;
background:radial-gradient(800px 500px at 50% 0,rgba(52,140,220,.18),transparent 70%),#04070e;padding:28px 16px}}
.w{{max-width:880px;margin:0 auto}}h1{{font-weight:600;letter-spacing:.24em;font-size:18px;margin:0}}h1 b{{color:#d7b36a;font-weight:500}}
.sub{{color:#7c889c;margin:6px 0 24px}}section{{border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.03);border-radius:16px;padding:18px;margin-bottom:14px}}
h2{{margin:0;font-size:16px;font-weight:600}}.t p{{margin:2px 0 12px;color:#7c889c;font-size:12.5px}}
.go{{display:inline-block;padding:10px 16px;border-radius:12px;background:linear-gradient(135deg,#7fd6ff,#3b8cff);color:#04111f;font-weight:700;text-decoration:none}}
.ms{{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}}.m{{padding:6px 11px;border-radius:999px;border:1px solid rgba(120,200,255,.25);color:#cfe7ff;text-decoration:none;font-size:12.5px}}
.m.alt{{border-color:rgba(215,179,106,.4);color:#f0d394}}
.cr{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-top:14px;padding-top:12px;border-top:1px dashed rgba(120,200,255,.18)}}
.cr label{{display:flex;gap:6px;align-items:center;color:#9fb3cc;font-size:12.5px}}
.cr input{{background:#0a1424;color:#e8edf5;border:1px solid rgba(120,200,255,.3);border-radius:10px;padding:7px 9px;font:inherit;color-scheme:dark}}
.cr button{{padding:8px 14px;border-radius:10px;border:1px solid rgba(120,200,255,.45);background:rgba(59,140,255,.15);color:#cfe7ff;font-weight:600;cursor:pointer}}
.cr button:hover{{background:rgba(59,140,255,.3)}}.e{{color:#7c889c}}.f{{color:#55607a;font-size:12px;margin-top:20px}}
</style></head><body><div class="w"><h1>{html.escape(config.ASSISTANT_NAME)} <b>AI</b></h1>
<div class="sub">Live dashboards for {html.escape(user['name'])} · data straight from the ERP replica, refreshed when you open them.</div>
{body}<div class="f">This link is personal and expires automatically. Do not forward it.</div></div></body></html>"""


def loading_page(target: str) -> str:
    """Shown instantly while the report is calculated (a few seconds), then swaps to the dashboard."""
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Preparing dashboard…</title>
<style>body{{margin:0;height:100vh;display:grid;place-items:center;background:#04070e;color:#cfe7ff;font:14px Inter,Segoe UI,sans-serif}}
.r{{width:64px;height:64px;border-radius:50%;border:2px solid rgba(98,200,255,.2);border-top-color:#62c8ff;animation:s 1s linear infinite;margin:0 auto 16px;box-shadow:0 0 24px rgba(98,200,255,.35)}}
@keyframes s{{to{{transform:rotate(360deg)}}}}</style></head><body><div style="text-align:center"><div class="r"></div>Preparing your live dashboard…<br><small style="color:#7c889c">reading the latest ERP data</small></div>
<script>location.replace({json.dumps(target)});</script></body></html>"""
