"""Fast answers: a report request with a clear period runs its engine straight away - no AI round-trips.

    "/final-production-rejection-report oct"      "scrap mis report september"
    "sales order last month"                       "show only seamless for oct 26"

Questions that need thinking ("why…", "compare…", "send to…", "kyu…") still go to the agent. The reply carries
the same cards, tables, files and dashboard as before, plus a short summary and 3 follow-ups built from the numbers.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import logging
import re
import time
from zoneinfo import ZoneInfo

from . import config, store

log = logging.getLogger("veronica.fast")

ENGINE_WORDS = {
    "final_production": ("final rejection", "rejection", "final production", "final prod", "rejp"),
    "scrap_mis": ("scrap mis", "scrap report", "scrap"),
    "jobcard_scrap": ("job card", "jobcard", "job-card", "jobcardwise"),
    "sales_order": ("sales order", "sale order", "order book", "pending order", "late delivery", "so mis"),
    "sale_dispatch": ("sales dispatch", "sale dispatch", "dispatch report", "sale invoice", "sales invoice", "monthwise sales",
                      "monthwise dispatch", "dispatch", "realisation"),
    "issue": ("issue report", "issue dashboard", "store issue", "material issue", "issue value", "costing", "issues"),
}
THINK = re.compile(r"\?|\b(why|kyu|kyun|kyon|how|kaise|explain|samjha|compare|comparison|vs|versus|difference|trend|reason|"
                   r"analy\w*|send|bhej\w*|mail|email|whatsapp|telegram|schedule|roz|roj|daily|every|har|teach|which|kaun|"
                   r"kitna|kitne|what|kya|insight|summary|top|lowest|highest|best|worst|plant\s*wise|godown|customer|"
                   r"salesperson|grade|item)\b", re.I)
MON = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
MON.update({m.lower(): i for i, m in enumerate(calendar.month_name) if m})
MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


def _today() -> dt.date:
    return dt.datetime.now(ZoneInfo(config.TIMEZONE)).date()


def _mon(word: str) -> int:
    w = word.lower()[:3]
    return MON.get(w, 0)


def _month(m: int, y: int | None, today: dt.date) -> tuple[dt.date, dt.date]:
    y = y or (today.year if m <= today.month else today.year - 1)
    last = dt.date(y, m, calendar.monthrange(y, m)[1])
    return dt.date(y, m, 1), min(last, today)


def parse_period(text: str, today: dt.date | None = None) -> tuple[dt.date, dt.date] | None:
    t, today = " " + text.lower() + " ", today or _today()
    yr = lambda s: (int(s) + (2000 if int(s) < 100 else 0)) if s else None
    # 1 oct to 15 oct / 01-10-2026 to 15-10-2026
    m = re.search(rf"(\d{{1,2}})\s*{MON_RE}\s*(\d{{2,4}})?\s*(?:to|-|till|se|tak)\s*(\d{{1,2}})\s*{MON_RE}\s*(\d{{2,4}})?", t)
    if m:
        y2 = yr(m.group(6)) or today.year
        a = dt.date(yr(m.group(3)) or y2, _mon(m.group(2)), int(m.group(1)))
        return a, dt.date(y2, _mon(m.group(5)), int(m.group(4)))
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})\s*(?:to|-|till)\s*(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        g = list(map(int, m.groups()))
        return dt.date(*g[:3]), dt.date(*g[3:])
    # oct 26 / 26 oct (a single day)
    m = re.search(rf"\b{MON_RE}\s+(\d{{1,2}})(?!\d)(?:\s*,?\s*(\d{{4}}))?\b", t) or None
    if m and int(m.group(2)) <= 31:
        d = dt.date(yr(m.group(3)) or today.year, _mon(m.group(1)), int(m.group(2)))
        return d, d
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{MON_RE}\b(?:\s*(\d{{4}}))?", t)
    if m and int(m.group(1)) <= 31:
        d = dt.date(yr(m.group(3)) or today.year, _mon(m.group(2)), int(m.group(1)))
        return d, d
    if re.search(r"\b(today|aaj|aj)\b", t):
        return today, today
    if re.search(r"\b(yesterday|kal)\b", t):
        d = today - dt.timedelta(days=1)
        return d, d
    if re.search(r"\b(last|previous|pichle|pichhle|pichla)\s+(month|mahine|mahina)\b", t):
        p = today.replace(day=1) - dt.timedelta(days=1)
        return _month(p.month, p.year, today)
    if re.search(r"\b(this|current|is)\s+(month|mahine|mahina)\b|\bmtd\b", t):
        return today.replace(day=1), today
    m = re.search(rf"\b{MON_RE}\b(?:\s*['-]?\s*(\d{{2,4}}))?", t)
    if m:
        return _month(_mon(m.group(1)), yr(m.group(2)), today)
    return None


def _division(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(seamless|u2|smls)\b", t):
        return "U2"
    if re.search(r"\b(welded|u1|erw)\b", t):
        return "U1"
    return "BOTH"


def _engine_of(skill: dict) -> str:
    try:
        st = json.loads(skill.get("sql_template") or "{}")
        return st.get("engine", "") if isinstance(st, dict) else ""
    except ValueError:
        return ""


def pick(user: dict, text: str, skill: dict | None) -> tuple[dict, tuple, str] | None:
    """Returns (skill, (d1, d2), division) when this message can be answered without the AI."""
    if not config.FAST_REPORTS:
        return None
    raw = text.strip()
    body = re.sub(r"^/\S+", "", raw).strip() if skill else raw
    if THINK.search(body) or len(body.split()) > 9:
        return None
    if skill is None:
        low = " " + raw.lower() + " "
        hits = []
        for sk in store.list_skills(user):
            eng = _engine_of(sk)
            words = ENGINE_WORDS.get(eng, ())
            hit = next((w for w in words if f" {w} " in low or f" {w}s " in low), None)
            if hit:
                hits.append((len(hit), sk))
        if not hits:
            return None
        skill = max(hits, key=lambda h: h[0])[1]
    elif not _engine_of(skill):
        return None
    period = parse_period(body)
    if period is None:
        if skill is not None and raw.startswith("/") and not body:
            today = _today()
            period = (today.replace(day=1), today)          # bare slash command = this month so far
        else:
            return None
    d1, d2 = sorted(period)
    if d2 > _today():
        return None
    return skill, (d1, d2), _division(body)


def _pct(k: dict) -> float | None:
    p, v = k.get("previous"), k.get("value")
    if not isinstance(p, (int, float)) or not isinstance(v, (int, float)):
        return None
    if k.get("format") == "percent":
        return v - p
    return (v - p) / abs(p) * 100 if p else None


def _fmt(k: dict) -> str:
    v = k["value"]
    s = f"{v:.2f}%" if k.get("format") == "percent" else f"{v:,.2f}".rstrip("0").rstrip(".")
    return s + (f" {k['unit']}" if k.get("unit") and k.get("format") != "percent" else "")


def nice_period(label: str) -> str:
    """'01-08-2026 to 31-08-2026' -> 'Aug 2026' ; '01-09-2026 to 15-09-2026' -> '1–15 Sep 2026'."""
    m = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4}) to (\d{2})-(\d{2})-(\d{4})", (label or "").strip())
    if not m:
        return label
    a = dt.date(int(m[3]), int(m[2]), int(m[1]))
    b = dt.date(int(m[6]), int(m[5]), int(m[4]))
    if a.day == 1 and (b + dt.timedelta(days=1)).day == 1 and a.month == b.month:
        return a.strftime("%b %Y")
    if a.month == b.month:
        return f"{a.day}–{b.day} {a.strftime('%b %Y')}"
    return f"{a.day} {a:%b} – {b.day} {b:%b %Y}"


def summarise(title: str, period: str, prev: str, kpis: list[dict], spoken: bool) -> tuple[str, list[str], dict | None]:
    period, prev = nice_period(period), nice_period(prev)
    groups: dict[str, list[dict]] = {}
    for k in kpis:
        if isinstance(k.get("value"), (int, float)):
            groups.setdefault(k.get("group") or "", []).append(k)
    worst, wscore = None, 0.0
    for ks in groups.values():
        for k in ks:
            d = _pct(k)
            if d is None or not k.get("better"):
                continue
            bad = d if k["better"] == "down" else -d
            if bad > wscore:
                worst, wscore = k, bad
    if spoken:
        bits = []
        for g, ks in list(groups.items())[:2]:
            bits.append((f"{g}: " if g else "") + ", ".join(f"{k['label']} {_fmt(k)}" for k in ks[:3]))
        text = f"{title} for {period}. " + ". ".join(bits) + "."
    else:
        lines = [f"**{title} — {period}**" + (f" (compared with {prev})" if prev else "")]
        for g, ks in list(groups.items())[:3]:
            parts = []
            for k in ([k for k in ks if k["value"]] or ks)[:4]:
                d = _pct(k)
                arrow = ""
                if d:
                    arrow = (" ▲" if d > 0 else " ▼") + (f"{abs(d):.2f} pts" if k.get("format") == "percent" else f"{abs(d):.1f}%")
                parts.append(f"{k['label']} **{_fmt(k)}**{arrow}")
            lines.append(("• " + (f"{g}: " if g else "")) + " · ".join(parts))
        if worst:
            lines.append(f"⚠️ Watch: {worst['label']}" + (f" ({worst['group']})" if worst.get("group") else "")
                         + f" moved the wrong way vs {prev or 'last period'}.")
        text = "\n".join(lines)
    short = re.sub(r"\s*\(.*?\)", "", period or "").strip() or "this period"
    mon = short.split()[0].title() if short else "this period"
    sugg = []
    if worst:
        sugg.append(f"Why is {worst['label']}" + (f" in {worst['group']}" if worst.get("group") else "") + f" high in {mon}?")
    if len(groups) > 1:
        other = [g for g in groups if g][-1:] or []
        if other:
            sugg.append(f"Show only {other[0]} for {short.title()}")
    if prev:
        sugg.append(f"Compare {short.title()} with {prev}")
    return text, sugg[:3], worst


def run(user: dict, text: str, skill: dict, period: tuple, division: str, channel: str, chat_key: str,
        spoken: bool, say, remember: bool, default_chat_id: str = ""):
    """Runs the engine directly. Returns an AgentReply, or None to let the agent handle it."""
    from . import agent
    t0 = time.time()
    ctx = agent.Ctx(user=user, role=agent.effective_role(user), channel=channel, chat_key=chat_key,
                    request_text=text, active_skill=skill, default_chat_id=default_chat_id)
    d1, d2 = period
    say({"type": "step", "id": "plan", "label": f"Fast path · {skill['title']}", "status": "done", "ms": 5})
    say({"type": "step", "id": "fast", "name": "run_report_engine", "status": "running", "label": "Calculating the report"})
    st = json.loads(skill.get("sql_template") or "{}")
    formats = [f for f in (st.get("formats") or ["table", "chart", "excel", "dashboard"]) if f != "pdf"]
    if re.search(r"\bpdf\b", text, re.I):
        formats.append("pdf")
    try:
        out = agent._tool_run_report_engine(ctx, skill["name"], d1.isoformat(), d2.isoformat(),
                                            division=division, formats=formats)
    except Exception:
        log.exception("fast path failed - handing over to the agent")
        return None
    ms = int((time.time() - t0) * 1000)
    err = out.get("error") if isinstance(out, dict) else None
    say({"type": "step", "id": "fast", "name": "run_report_engine", "ms": ms, "status": "error" if err else "done",
         "detail": f"{skill['name']} {d1}..{d2}"})
    if err:
        if "No " in err and "rows" in err or "not found" in err.lower():
            ctx.reply.text = f"⚠️ {err}"
        else:
            return None                                     # unusual problem: let the agent try other ways
    else:
        for k in ctx.reply.kpis:
            say({"type": "figure", **{x: k.get(x) for x in ("label", "value", "format", "unit", "previous",
                                                             "previous_label", "better", "group")},
                 "source": skill["title"]})
        txt, sugg, _ = summarise(skill["title"], out.get("period", ""), out.get("compared_with", ""), ctx.reply.kpis, spoken)
        ctx.reply.text = txt + "".join(f"\n\nℹ️ {n}" for n in dict.fromkeys(getattr(ctx.reply, "text_notes", [])))
        ctx.reply.suggestions = sugg
        say({"type": "text", "delta": txt})
    if remember:
        store.add_message(chat_key, "user", text)
        memo = ctx.reply.text + (f"\n[Created report id(s) {ctx.reply.report_ids} for {d1}..{d2}]" if ctx.reply.report_ids else "")
        store.add_message(chat_key, "assistant", memo)
    log.info("fast path %s %s..%s in %.1fs", skill["name"], d1, d2, time.time() - t0)
    return ctx.reply
