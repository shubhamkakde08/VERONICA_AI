"""The Claude agent: understands Hindi / English / Gujarati / Marathi, explores the
MySQL schema, runs safe SELECTs, learns report "skills" and produces reports.

One entry point:  handle_message(user, text, channel, chat_key) -> AgentReply
"""
from __future__ import annotations

import json
import re
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import logging

import anthropic

from . import config, datadb, filelinks, pack, renderers, store, vendor

log = logging.getLogger("veronica.agent")

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY or "missing")


@dataclass
class AgentReply:
    text: str
    tables: list[str] = field(default_factory=list)   # monospace chat tables
    files: list[dict] = field(default_factory=list)   # rendered report files
    report_ids: list[int] = field(default_factory=list)
    preview: list[dict] = field(default_factory=list)  # {"columns","rows"} for web UI
    kpis: list[dict] = field(default_factory=list)     # [{"label","value","format"}] for web UI
    suggestions: list[str] = field(default_factory=list)  # smart next questions (chips in the UI)
    denied: bool = False                                  # asked for something outside their rights -> red "no access" look


@dataclass
class Ctx:
    user: dict
    role: dict
    channel: str
    chat_key: str
    request_text: str
    active_skill: dict | None = None
    results: dict = field(default_factory=dict)
    reply: AgentReply = field(default_factory=lambda: AgentReply(text=""))
    default_chat_id: str = ""
    built_division: str = ""          # U1 / U2 when the last report in this turn was built for one division only


# =================================================================== tools
KPI_ITEM = {"type": "object", "properties": {
    "label": {"type": "string", "description": "short, e.g. 'Scrap %', 'Production'"},
    "value": {"type": "number"},
    "format": {"enum": ["number", "currency", "percent"]},
    "unit": {"type": "string", "description": "e.g. 'MT', 'Kg', 'job cards' (not for % or ₹)"},
    "previous": {"type": "number", "description": "same KPI for the comparison period"},
    "previous_label": {"type": "string", "description": "e.g. 'vs Sep', 'vs last week'"},
    "target": {"type": "number", "description": "target / norm if the rules define one"},
    "better": {"enum": ["up", "down"], "description": "up = higher is better (production); down = lower is better (scrap)"},
    "status": {"enum": ["good", "warn", "bad"], "description": "optional explicit status"},
    "note": {"type": "string", "description": "one short line, e.g. 'highest: SMLSP'"}},
    "required": ["label", "value"]}

TOOLS = [
    {"name": "list_tables",
     "description": "List database tables/views the user may read. Use `search` to filter by "
                    "part of a name (e.g. 'sale', 'invoice', 'item'). Call this before writing SQL "
                    "if you don't know the schema.",
     "input_schema": {"type": "object", "properties": {
         "search": {"type": "string", "description": "optional substring"}}}},
    {"name": "describe_tables",
     "description": "Get columns, types, comments and foreign keys for up to 15 tables.",
     "input_schema": {"type": "object", "properties": {
         "tables": {"type": "array", "items": {"type": "string"}}}, "required": ["tables"]}},
    {"name": "run_sql",
     "description": "Run ONE read-only MySQL SELECT. Returns a result_id, the columns and a preview "
                    "of up to 30 rows. Shape the SQL like the final report (column order, aliases "
                    "as readable headers, grouping, sorting). Use the result_id with create_report.",
     "input_schema": {"type": "object", "properties": {
         "sql": {"type": "string"},
         "purpose": {"type": "string", "description": "one line: what this query answers"}},
         "required": ["sql"]}},
    {"name": "run_skill_query",
     "description": "Run one of the TESTED queries stored inside a report skill (skills whose definition "
                    "lists 'stored_queries'). Always prefer this over writing your own SQL for such skills - "
                    "the queries reproduce the official report logic exactly. Returns a result_id like run_sql.",
     "input_schema": {"type": "object", "properties": {
         "skill_name": {"type": "string"},
         "query": {"type": "string", "description": "name from stored_queries"},
         "from_date": {"type": "string", "description": "YYYY-MM-DD"},
         "to_date": {"type": "string", "description": "YYYY-MM-DD (inclusive)"},
         "unit": {"enum": ["kg", "mt"], "default": "kg"}},
         "required": ["skill_name", "query", "from_date", "to_date"]}},
    {"name": "set_skill_columns",
     "description": "Fix the column mapping of a skill's stored queries when they fail with 'Unknown column'. "
                    "First describe_tables the source view, then map each placeholder to the real column name. "
                    "Saves a new skill version. Managers/admins only.",
     "input_schema": {"type": "object", "properties": {
         "skill_name": {"type": "string"},
         "columns": {"type": "object", "description": "{placeholder: real_column}, e.g. {\"SCRAP\": \"SCARP_QTY\"}"}},
         "required": ["skill_name", "columns"]}},
    {"name": "list_report_skills",
     "description": "List taught report skills (each one is a /command) the user may run.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_report_skill",
     "description": "Load a report skill's full definition: rules, format, reference SQL, example.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}},
                      "required": ["name"]}},
    {"name": "save_report_skill",
     "description": "Create or update a report skill (teaching). ONLY call after you showed the user "
                    "the draft definition and a test preview, and they confirmed. Updating an "
                    "existing name creates a new version (old versions are kept).",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string", "description": "lowercase_with_underscores, becomes /name"},
         "title": {"type": "string"},
         "description": {"type": "string", "description": "what the report is for, who reads it"},
         "rules": {"type": "string", "description": "business rules & regulations, as a numbered list"},
         "output_format": {"type": "string", "description": "columns in order, headers, grouping, "
                           "sorting, totals, number formats, chart, summary style, language"},
         "default_formats": {"type": "array", "items": {"enum": list(renderers.ALL_FORMATS)}},
         "sql_template": {"type": "string", "description": "tested reference SQL; mark variable "
                          "parts like {from_date} {to_date} {branch} in comments"},
         "example_output": {"type": "string", "description": "sample of the desired report"},
         "allowed_roles": {"type": "array", "items": {"type": "string"},
                           "description": "empty = everyone"}},
         "required": ["name", "title", "rules", "output_format"]}},
    {"name": "create_report",
     "description": "Render a query result as the final report in one or more formats: "
                    "table (shown in chat), excel, pdf, chart (PNG), html. Saves it to history.",
     "input_schema": {"type": "object", "properties": {
         "result_id": {"type": "string"},
         "title": {"type": "string"},
         "subtitle": {"type": "string", "description": "e.g. period / branch / filters"},
         "summary": {"type": "string", "description": "3-6 line insight summary IN THE USER'S "
                     "LANGUAGE: totals, top items, changes, anything unusual"},
         "notes": {"type": "string"},
         "formats": {"type": "array", "items": {"enum": list(renderers.ALL_FORMATS)}},
         "column_labels": {"type": "object", "description": "optional rename {old: new}"},
         "column_formats": {"type": "object", "description": "{column: number|currency|percent|date|text}"},
         "total_columns": {"type": "array", "items": {"type": "string"}},
         "chart": {"type": "object", "properties": {
             "type": {"enum": ["bar", "barh", "line", "pie"]}, "x": {"type": "string"},
             "y": {"type": "array", "items": {"type": "string"}},
             "title": {"type": "string", "description": "English only (charts can't draw Indic scripts)"}}},
         "skill_name": {"type": "string"}},
         "required": ["result_id", "title", "formats"]}},
    {"name": "create_report_pack",
     "description": "Render a MULTI-SECTION report (Power BI style) in one go: KPI cards on top, then "
                    "several sections, each from its own run_sql result, each with an optional chart and "
                    "an optional grouped table (Plant > Item Group > Process with subtotals). Produces chat "
                    "tables, chart images and ONE combined PDF / Excel / HTML. Use this whenever a skill "
                    "describes several sections or KPI cards. Saves to history.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"},
         "filters": {"type": "object", "description": "shown under the title, e.g. {\"Vr Date\": \"01-04-2026 to 12-10-2026\", \"Plant\": \"BA, SMLST\"}"},
         "kpis": {"type": "array", "description": "KPI cards shown at the top. Add previous/target/better when you know them "
                  "so the card shows the change (▲▼) in the right colour.", "items": KPI_ITEM},
         "summary": {"type": "string", "description": "3-6 lines of insight in the user's language"},
         "sections": {"type": "array", "items": {"type": "object", "properties": {
             "result_id": {"type": "string"},
             "title": {"type": "string"},
             "group_by": {"type": "array", "items": {"type": "string"},
                          "description": "columns to group rows by, outermost first; they become header rows"},
             "total_columns": {"type": "array", "items": {"type": "string"},
                               "description": "columns summed in subtotals / grand total"},
             "ratio_columns": {"type": "object", "description": "{\"Scrap %\": [\"Scrap Qty\", \"Gross Qty\", 100]} "
                               "= recompute this column in subtotals as num/den*mult (never sum percentages)"},
             "hidden_columns": {"type": "array", "items": {"type": "string"},
                                "description": "helper columns used only for ratio_columns"},
             "column_formats": {"type": "object"},
             "column_labels": {"type": "object"},
             "chart": {"type": "object", "properties": {
                 "type": {"enum": ["bar", "barh", "line", "pie"]}, "x": {"type": "string"},
                 "y": {"type": "array", "items": {"type": "string"}},
                 "title": {"type": "string", "description": "English only"},
                 "colors": {"type": "array", "items": {"type": "string"},
                            "description": "optional hex colour per bar (single-series bar charts)"}}},
             "show_table": {"type": "boolean", "default": True},
             "only_in": {"type": "array", "items": {"enum": list(pack.FORMATS)},
                         "description": "limit this section to some outputs, e.g. [\"excel\"] for a long detail list"},
             "subtotals": {"type": "boolean", "default": True},
             "note": {"type": "string"}},
             "required": ["result_id", "title"]}},
         "formats": {"type": "array", "items": {"enum": list(pack.FORMATS)}},
         "skill_name": {"type": "string"}},
         "required": ["title", "sections", "formats"]}},
    {"name": "lookup_master",
     "description": "Search a company master file kept in VERONICA's own folder (item master, customer list, codes - "
                    "listed under COMPANY MASTER FILES). Faster than the ERP for code -> name / spec lookups. All words "
                    "of 'search' must appear in the row (or in 'column' if given). Empty search = first rows.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string", "description": "master file name as listed"},
         "search": {"type": "string"}, "column": {"type": "string"},
         "limit": {"type": "integer", "description": "max rows (default 50, max 300)"}},
         "required": ["name"]}},
    {"name": "calculate",
     "description": "Exact arithmetic (never do maths in your head for figures you show): +,-,*,/,**, (), round, min, max, "
                    "sum, abs. Use for projections (month-end forecast = MTD / days_elapsed * days_in_month), "
                    "differences, % changes, contributions to a change.",
     "input_schema": {"type": "object", "properties": {
         "expressions": {"type": "object", "description": "name -> expression, e.g. {\"forecast\": \"4218.1/25*31\"}"}},
         "required": ["expressions"]}},
    {"name": "read_attachment",
     "description": "Rows of an Excel/CSV file the user attached in the chat (file_id from <attached_file>). Use for rows "
                    "beyond the preview. Max 500 rows per call.",
     "input_schema": {"type": "object", "properties": {
         "file_id": {"type": "string"}, "sheet": {"type": "string"}, "start": {"type": "integer"},
         "limit": {"type": "integer"}, "columns": {"type": "array", "items": {"type": "string"}}},
         "required": ["file_id"]}},
    {"name": "attachment_totals",
     "description": "EXACT sums over the WHOLE attached Excel/CSV sheet, optionally grouped and filtered "
                    "(e.g. total Qty by Plant). Always use this for totals of an attachment instead of adding rows yourself.",
     "input_schema": {"type": "object", "properties": {
         "file_id": {"type": "string"}, "sum_columns": {"type": "array", "items": {"type": "string"}},
         "group_by": {"type": "array", "items": {"type": "string"}}, "sheet": {"type": "string"},
         "filters": {"type": "object", "description": "column -> exact value to keep"}},
         "required": ["file_id", "sum_columns"]}},
    {"name": "suggest_followups",
     "description": "Call once at the end of every data answer: 2-3 short, specific next questions the user would "
                    "likely ask next (in the user's language), e.g. 'Why is P21 REJP high?', 'Compare with last month', "
                    "'Forecast month-end'. Shown as tap-to-ask chips.",
     "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "string"}}},
                      "required": ["items"]}},
    {"name": "run_report_engine",
     "description": "Run a report skill that has a built-in calculation engine (its sql_template says \"engine\"), "
                    "e.g. /final_production_rejection_report. It queries the database, applies the exact company "
                    "logic, and delivers KPI cards, chat tables, chart, Excel, PDF and the interactive dashboard by "
                    "itself. Afterwards reply ONLY with the short summary the skill rules ask for.",
     "input_schema": {"type": "object", "properties": {
         "skill_name": {"type": "string"},
         "from_date": {"type": "string", "description": "YYYY-MM-DD"},
         "to_date": {"type": "string", "description": "YYYY-MM-DD (inclusive)"},
         "division": {"enum": ["BOTH", "U1", "U2"], "description": "final production only: U1 = Welded, U2 = Seamless, BOTH = company"},
         "unit": {"enum": ["kg", "mt"], "description": "jobcard scrap only (default kg)"},
         "section": {"enum": ["", "bb2bb", "bb2hollow", "cutting"], "description": "jobcard scrap only: one section, empty = all"},
         "formats": {"type": "array", "items": {"enum": ["table", "chart", "excel", "pdf", "html", "dashboard", "data"]},
                     "description": "default from the skill rules. dashboard = the company's own HTML tool with the data "
                                    "pre-loaded; data = raw export Excel"}},
         "required": ["skill_name", "from_date", "to_date"]}},
    {"name": "show_kpi_cards",
     "description": "Show a few KPI cards in the chat for a quick answer (no files). Use whenever your answer "
                    "contains 1-6 key numbers, e.g. 'aaj ka scrap kitna hai' -> Scrap %, Scrap qty, Production. "
                    "Include previous period values when you have them.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"},
         "kpis": {"type": "array", "items": KPI_ITEM}}, "required": ["kpis"]}},
    {"name": "search_report_history",
     "description": "Find previously generated reports (newest first).",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string"}, "skill_name": {"type": "string"},
         "limit": {"type": "integer", "default": 10}}}},
    {"name": "get_past_report",
     "description": "Open one past report: its SQL, summary, files and first rows. Use to compare "
                    "with last time or to re-create it in another format (re-run its SQL).",
     "input_schema": {"type": "object", "properties": {"report_id": {"type": "integer"}},
                      "required": ["report_id"]}},
    {"name": "send_files",
     "description": "Send report files (Excel / PDF / dashboard / chart) to people on Telegram, e-mail or WhatsApp - e.g. "
                    "'send this to Bharat on WhatsApp', 'mail the October scrap report to Ravi', 'mujhe telegram pe bhejo'. "
                    "Files = this answer's files, else the given past report, else the user's latest report. "
                    "ALWAYS call first with confirmed=false: it returns exactly what will go to whom. Read that back to "
                    "the user in one short sentence and ask 'Shall I send?'. Only after they say yes (by voice or text) "
                    "call again with confirmed=true and the same arguments.",
     "input_schema": {"type": "object", "properties": {
         "channel": {"enum": (["telegram"] if config.TELEGRAM_ENABLED else []) + ["email", "whatsapp"]},
         "recipients": {"type": "array", "items": {"type": "string"},
                        "description": "people's names as the user said them ('Bharat', 'Ravi Choudhary'), 'me' for the user, "
                                       "or an e-mail address / phone number"},
         "report_id": {"type": "integer", "description": "a past report (search_report_history) - omit for the latest"},
         "formats": {"type": "array", "items": {"enum": ["excel", "pdf", "dashboard", "html", "chart", "data"]},
                     "description": "omit = all files of that report"},
         "message": {"type": "string", "description": "short covering note in the user's language"},
         "confirmed": {"type": "boolean", "default": False}},
         "required": ["channel", "recipients"]}},
    {"name": "create_schedule",
     "description": ("Schedule a report skill to be sent automatically to a Telegram chat. " if config.TELEGRAM_ENABLED else
                     "Schedule a report skill to be e-mailed automatically to the user (their saved e-mail). ")
                    + 
                    "Confirm the time with the user first. Cron is in local time "
                    f"({config.TIMEZONE}), 5 fields: minute hour day month weekday.",
     "input_schema": {"type": "object", "properties": {
         "skill_name": {"type": "string"},
         "cron": {"type": "string", "description": "e.g. '0 9 * * 1-6' = 9:00 AM Mon-Sat"},
         "prompt": {"type": "string", "description": "extra instruction, e.g. 'for yesterday'"},
         "formats": {"type": "array", "items": {"enum": list(renderers.ALL_FORMATS)}},
         "target_chat_id": {"type": "string", "description": "Telegram chat/group id; "
                            "omit to use the current chat"},
         "name": {"type": "string"}},
         "required": ["skill_name", "cron"]}},
    {"name": "log_access_denied",
     "description": "SECURITY: call this EVERY time you decline because the data / report / action is outside the user's access "
                    "(other department's views, other division, private data, other plants, admin-only things) - BEFORE you reply "
                    "'This data is not in your access'. It silently records it for the admin. Never mention the log to the user.",
     "input_schema": {"type": "object", "properties": {
         "asked_for": {"type": "string", "description": "what they wanted, e.g. 'U1 welded scrap', 'purchase orders', 'salary data'"},
         "reason": {"type": "string", "description": "why it is outside access, e.g. 'division lock U2', 'role production has no sales views'"}},
         "required": ["asked_for", "reason"]}},
    {"name": "list_schedules", "description": "List active scheduled reports.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "cancel_schedule", "description": "Stop a scheduled report by id.",
     "input_schema": {"type": "object", "properties": {"schedule_id": {"type": "integer"}},
                      "required": ["schedule_id"]}},
]


def _tool_log_access_denied(ctx: Ctx, asked_for: str, reason: str):
    _deny(ctx, "data_outside_access", f"{asked_for} - {reason}")
    return {"logged": True, "say": denied_message(ctx.request_text)}


def _tool_list_tables(ctx: Ctx, search: str = ""):
    names = datadb.list_tables(ctx.role["allowed_tables"], search)
    if search and not names:                       # table may have just been created
        datadb.refresh_schema_cache()
        names = datadb.list_tables(ctx.role["allowed_tables"], search)
    return {"count": len(names), "tables": names[:300],
            **({"note": "more tables exist, use search"} if len(names) > 300 else {})}


def _tool_describe_tables(ctx: Ctx, tables: list[str]):
    return datadb.describe_tables(tables, ctx.role["allowed_tables"])


DENIED_MSG = {
    "en": "I'm sorry, this information is not in your access. 🔒 Please contact your admin if you need it.",
    "hi": "माफ़ कीजिए, यह जानकारी आपके access में नहीं है। 🔒 ज़रूरत हो तो कृपया अपने admin से संपर्क करें।",
    "hinglish": "Maaf kijiye, yeh jaankari aapke access mein nahi hai. 🔒 Zaroorat ho to kripya apne admin se sampark karein.",
    "gu": "માફ કરશો, આ માહિતી તમારા access માં નથી. 🔒 જરૂર હોય તો કૃપા કરીને તમારા admin નો સંપર્ક કરો.",
    "mr": "माफ करा, ही माहिती तुमच्या access मध्ये नाही. 🔒 गरज असल्यास कृपया तुमच्या admin शी संपर्क साधा.",
}


def denied_message(asked: str) -> str:
    """The only thing a user hears when they ask outside their rights - in their language, never the reason."""
    a = asked or ""
    if re.search(r"[\u0A80-\u0AFF]", a):
        return DENIED_MSG["gu"]
    if re.search(r"[\u0900-\u097F]", a):
        return DENIED_MSG["mr"] if re.search(r"(आहे|मला|दाखवा|काय|पाहिजे)", a) else DENIED_MSG["hi"]
    if re.search(r"\b(aap|apka|aapka|mujhe|muje|kya|hai|hain|dikhao|batao|bata|chahiye|karo|kitna|kitne|ka|ki|ke|mera|meri|hamara|aaj|kal)\b", a, re.I):
        return DENIED_MSG["hinglish"]
    return DENIED_MSG["en"]


def _deny(ctx: "Ctx", kind: str, detail: str) -> None:
    """Access denial -> security log + silent admin alert (see app/security.py)."""
    from . import security
    ctx.reply.denied = True
    security.denied(ctx.user, kind, detail, ctx.channel, ctx.request_text)


def _rejected(ctx: "Ctx", e: Exception) -> dict:
    msg = str(e)
    if re.search(r"not allowed to read|PRIVATE|reserved for a private", msg):
        _deny(ctx, "table_blocked", msg)
    return {"error": f"Rejected: {msg}"}


def _tool_run_sql(ctx: Ctx, sql: str, purpose: str = ""):
    if ctx.role.get("division_lock") or ctx.role.get("line_lock") or ctx.role.get("plant_lock"):
        _deny(ctx, "free_sql_blocked", f"free SQL while locked ({ctx.role.get('division_lock') or 'plant lock'}): {sql[:300]}")
        return {"error": f"This user may only see {ctx.role.get('division_lock') or 'some plant lines of the'} division data, so free SQL is not allowed. "
                         "Use the taught reports (run_report_engine), which apply the division automatically."}
    if not ctx.role.get("free_query") and not ctx.active_skill:
        return {"error": "Your role can only run taught reports. Ask the user which /report "
                         "they want (list_report_skills), then load it with get_report_skill."}
    try:
        res = datadb.run_select(sql, ctx.role["allowed_tables"])
    except datadb.SQLRejected as e:
        return _rejected(ctx, e)
    except Exception as e:  # DB error -> let Claude fix its SQL
        return {"error": f"Database error: {str(e)[:600]}"}
    rid = f"r{len(ctx.results) + 1}"
    ctx.results[rid] = res
    return {"result_id": rid, "columns": res["columns"], "row_count": res["row_count"],
            "truncated": res["truncated"], "seconds": res["seconds"],
            "preview_rows": res["rows"][:30]}


def _skill_brief(s: dict) -> dict:
    return {"name": s["name"], "command": "/" + s["name"], "title": s["title"],
            "description": (s.get("description") or "")[:200],
            "default_formats": s.get("default_formats"), "version": s.get("version")}


STORED_COL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#]{0,63}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _stored(skill: dict) -> dict | None:
    try:
        d = json.loads(skill.get("sql_template") or "")
        return d if isinstance(d, dict) and isinstance(d.get("queries"), dict) else None
    except (ValueError, TypeError):
        return None


def _tool_run_skill_query(ctx: Ctx, skill_name: str, query: str, from_date: str, to_date: str,
                          unit: str = "kg"):
    sk = store.get_skill(skill_name)
    if not sk or not store.skill_allowed(sk, ctx.user):
        if sk:
            _deny(ctx, "report_blocked", f"report /{skill_name}")
        return {"error": f"No report skill '{skill_name}' available for you."}
    st = _stored(sk)
    if not st:
        return {"error": "This skill has no stored queries; use run_sql with its sql_template."}
    if query not in st["queries"]:
        return {"error": f"Unknown query. Available: {list(st['queries'])}"}
    if not (DATE_RE.match(from_date or "") and DATE_RE.match(to_date or "")):
        return {"error": "Dates must be YYYY-MM-DD"}
    cols = st.get("columns") or {}
    bad = [k for k, v in cols.items() if not STORED_COL_RE.match(str(v))]
    if bad:
        return {"error": f"Invalid column names in mapping: {bad}"}
    sql = st["queries"][query]
    for k, v in cols.items():
        sql = sql.replace("{" + k + "}", f"`{v}`")
    sql = (sql.replace("{from_date}", from_date).replace("{to_date}", to_date)
              .replace("{div}", "1000" if unit == "mt" else "1"))
    if re.search(r"\{[A-Z_]+\}", sql):
        return {"error": f"Unmapped placeholders: {sorted(set(re.findall(r'{([A-Z_]+)}', sql)))}"}
    ctx.active_skill = ctx.active_skill or sk
    try:
        res = datadb.run_select(sql, ctx.role["allowed_tables"])
    except datadb.SQLRejected as e:
        return _rejected(ctx, e)
    except Exception as e:
        msg = str(e)[:500]
        hint = (" -> describe_tables the source view and call set_skill_columns with the real names."
                if "Unknown column" in msg or "1054" in msg else "")
        return {"error": f"Database error: {msg}{hint}", "column_mapping": cols}
    rid = f"r{len(ctx.results) + 1}"
    ctx.results[rid] = res
    return {"result_id": rid, "query": query, "columns": res["columns"], "row_count": res["row_count"],
            "truncated": res["truncated"], "preview_rows": res["rows"][:15]}


def _tool_set_skill_columns(ctx: Ctx, skill_name: str, columns: dict):
    if not ctx.role.get("can_teach"):
        return {"error": "Only managers/admins can change a report's column mapping. Ask your admin."}
    sk = store.get_skill(skill_name)
    st = _stored(sk) if sk else None
    if not st:
        return {"error": "Skill not found or has no stored queries."}
    bad = [k for k, v in columns.items() if not STORED_COL_RE.match(str(v))]
    if bad:
        return {"error": f"Invalid column names: {bad}"}
    st["columns"] = {**(st.get("columns") or {}), **columns}
    s = store.save_skill({"name": sk["name"], "sql_template": json.dumps(st, ensure_ascii=False)},
                         changed_by=ctx.user["name"])
    return {"saved": True, "version": s["version"], "columns": st["columns"]}


def _tool_list_report_skills(ctx: Ctx):
    return [_skill_brief(s) for s in store.list_skills(ctx.user)]


def _tool_get_report_skill(ctx: Ctx, name: str):
    s = store.get_skill(name)
    if not s:
        return {"error": f"No skill named {name}"}
    if not store.skill_allowed(s, ctx.user):
        _deny(ctx, "report_blocked", f"report /{name}")
        return {"error": "This report is not available for your role."}
    ctx.active_skill = s
    out = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in s.items()}
    st = _stored(s)
    if st:
        out["sql_template"] = None
        out["stored_queries"] = list(st["queries"])
        out["column_mapping"] = st.get("columns") or {}
        out["how_to_run"] = "Use run_skill_query for each stored query you need (call several in one turn)."
    return out


def _tool_save_report_skill(ctx: Ctx, **kw):
    if not ctx.role.get("can_teach"):
        _deny(ctx, "teach_blocked", f"teach/change report {kw.get('name', '')}")
        return {"error": "Your role is not allowed to teach/change reports."}
    try:
        s = store.save_skill(kw, changed_by=ctx.user["name"])
    except ValueError as e:
        return {"error": str(e)}
    if config.TELEGRAM_BOT_TOKEN:  # show the new /command in Telegram's menu
        try:
            from . import telegram
            telegram.set_commands()
        except Exception:
            pass
    return {"saved": True, "command": "/" + s["name"], "version": s["version"]}


def _tool_create_report(ctx: Ctx, result_id: str, title: str, formats: list[str], **kw):
    res = ctx.results.get(result_id)
    if not res:
        return {"error": f"Unknown result_id {result_id}. Run run_sql first."}
    labels = kw.get("column_labels") or {}
    columns = [labels.get(c, c) for c in res["columns"]]
    remap = lambda d: {labels.get(k, k): v for k, v in (d or {}).items()}
    spec = renderers.ReportSpec(
        title=title, columns=columns, rows=res["rows"], subtitle=kw.get("subtitle", ""),
        summary=kw.get("summary", ""), notes=kw.get("notes", ""),
        column_formats=remap(kw.get("column_formats")),
        total_columns=[labels.get(c, c) for c in (kw.get("total_columns") or [])],
        chart=({**kw["chart"], "x": labels.get(kw["chart"].get("x"), kw["chart"].get("x")),
                "y": [labels.get(y, y) for y in kw["chart"].get("y") or []]}
               if kw.get("chart") else None),
        skill_name=store.normalize_skill_name(kw.get("skill_name") or
                                              (ctx.active_skill or {}).get("name", "")),
    )
    if res["truncated"]:
        spec.notes = (spec.notes + "\n" if spec.notes else "") + \
            f"Note: limited to the first {config.MAX_ROWS} rows."
    out = renderers.render(spec, formats)
    report_id = store.save_report(
        user_id=ctx.user["id"], channel=ctx.channel, skill_name=spec.skill_name, title=title,
        request_text=ctx.request_text[:4000], sql_text=res["sql"], row_count=res["row_count"],
        summary=spec.summary, data_preview=[columns] + res["rows"][:50],
        files=[{k: f[k] for k in ("format", "filename", "url", "path")} for f in out["files"]])
    if out["table_text"]:
        ctx.reply.tables.append(f"{title}\n\n{out['table_text']}")
        ctx.reply.preview.append({"title": title, "columns": columns, "rows": res["rows"][:200]})
    ctx.reply.files.extend(out["files"])
    ctx.reply.report_ids.append(report_id)
    if out.get("pdf_skipped"):
        ctx.reply.text_notes = getattr(ctx.reply, "text_notes", []) + ["PDF not available on this server (GTK missing) - Excel/HTML sent instead."]
    return {"report_id": report_id, "formats_created": [f["format"] for f in out["files"]] +
            (["table"] if out["table_text"] else []),
            "note": "Files are delivered to the user automatically. Do not paste links or the "
                    "full table again; just give the summary in the user's language."}


def _tool_create_report_pack(ctx: Ctx, title: str, sections: list, formats: list[str], **kw):
    skill = store.normalize_skill_name(kw.get("skill_name") or (ctx.active_skill or {}).get("name", ""))
    spec = {"title": title, "sections": sections, "kpis": kw.get("kpis") or [],
            "filters": kw.get("filters") or {}, "summary": kw.get("summary", ""), "skill_name": skill}
    out = pack.render_pack(spec, ctx.results, formats)
    if out["missing"]:
        return {"error": f"Unknown result_id(s) {out['missing']}. Run run_sql for each section first."}
    first = ctx.results.get(sections[0]["result_id"]) if sections else None
    report_id = store.save_report(
        user_id=ctx.user["id"], channel=ctx.channel, skill_name=skill, title=title,
        request_text=ctx.request_text[:4000],
        sql_text="\n\n".join(f"-- {s.get('title')}\n{ctx.results[s['result_id']]['sql']}" for s in sections),
        row_count=sum(out["row_counts"].values()), summary=spec["summary"],
        data_preview=[{"kpis": spec["kpis"]}] + ([first["columns"]] + first["rows"][:30] if first else []),
        files=[{k: f[k] for k in ("format", "filename", "url", "path")} for f in out["files"]])
    ctx.reply.tables.extend(out["chat_tables"] or [])
    ctx.reply.preview.extend(out["previews"] if out["chat_tables"] is not None else [])
    ctx.reply.kpis.extend(spec["kpis"])
    ctx.reply.files.extend(out["files"])
    ctx.reply.report_ids.append(report_id)
    if out.get("pdf_skipped"):
        ctx.reply.text_notes = getattr(ctx.reply, "text_notes", []) + ["PDF not available on this server (GTK missing) - Excel/HTML sent instead."]
    return {"report_id": report_id, "rows_per_section": out["row_counts"],
            "files_created": [f["format"] for f in out["files"]],
            "note": "Everything is delivered automatically. Reply with a short summary only."}


def _tool_run_report_engine(ctx: Ctx, skill_name: str, from_date: str, to_date: str, division: str = "BOTH",
                            formats: list[str] | None = None, unit: str = "kg", section: str = ""):
    import inspect
    import uuid
    from . import engines as _engines
    engines = _engines.load()
    sk = store.get_skill(skill_name)
    if not sk or not store.skill_allowed(sk, ctx.user):
        if sk:
            _deny(ctx, "report_blocked", f"report /{skill_name} {from_date}..{to_date}")
        return {"error": f"No report skill '{skill_name}' available for you."}
    try:
        st = json.loads(sk.get("sql_template") or "{}")
    except ValueError:
        st = {}
    eng = engines.get(st.get("engine") if isinstance(st, dict) else None)
    if not eng:
        return {"error": "This skill has no engine; use run_skill_query / run_sql."}
    if not (DATE_RE.match(from_date or "") and DATE_RE.match(to_date or "")):
        return {"error": "Dates must be YYYY-MM-DD"}
    ctx.active_skill = ctx.active_skill or sk
    lock = ctx.role.get("division_lock")
    if lock:
        division = lock                                      # whatever was asked, a locked user gets only their division
    kw = {k: v for k, v in {"division": division, "unit": unit, "section": section, "lines": ctx.role.get("line_lock"),
                                 "plants": ctx.role.get("plant_lock"), "user": ctx.user}.items()
          if k in inspect.signature(eng.run).parameters}
    try:
        out = eng.run(sk, from_date, to_date, ctx.role["allowed_tables"], **kw)
    except eng.EngineError as e:
        return {"error": str(e)}
    except datadb.SQLRejected as e:
        return _rejected(ctx, e)
    except Exception as e:
        log.exception("engine failed")
        return {"error": f"Database error: {str(e)[:400]}"}
    formats = formats or st.get("formats") or ["table", "chart", "excel", "dashboard", "pdf"]
    if getattr(eng, "ENGINE", "") == "sales_order":      # management asks "yesterday's orders" -> always answer + HTML + Excel
        formats = list(dict.fromkeys(list(formats) + ["table", "html", "excel"]))
    own_excel = "excel" in out["files"]
    ctx.results.update(out["results"])
    one = (kw.get("division") or "").upper()
    one = one if one in ("U1", "U2") else ""
    ctx.built_division = one
    title = f"{sk['title']} — {out['label']}" + (f" · {one} only" if one else "")
    spec = {"title": title, "sections": out["sections"], "kpis": out["kpis"], "skill_name": sk["name"],
            "filters": {"Period": out["label"], "Compared with": out["prev_label"], "Unit": "MT",
                        "Source": (st.get("source") or "")}, "summary": ""}
    pf = [f for f in formats if f in ("table", "chart", "pdf", "html") or (f == "excel" and not own_excel)]
    rendered = pack.render_pack(spec, ctx.results, pf)
    files = list(rendered["files"])
    folder_id = uuid.uuid4().hex
    folder = config.OUTPUT_DIR / folder_id
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y%m%d_%H%M")
    for fmt, data_key, name in (("excel", "excel", f"{sk['name']}_{stamp}.xlsx"),
                                ("dashboard", "dashboard", f"{sk['name']}_dashboard_{stamp}.html"),
                                ("data", "source_excel", out["files"].get("source_name") or f"{sk['name']}_data_{stamp}.xlsx")):
        if fmt in formats and data_key in out["files"]:
            p = folder / name
            data = out["files"][data_key]
            if fmt == "dashboard":
                data = vendor.localize_bytes(data)          # no CDN / Google Fonts in saved dashboards
            p.write_bytes(data)
            files.append({"format": fmt, "path": str(p), "filename": name,
                          "url": filelinks.url(folder_id, name)})
    report_id = store.save_report(
        user_id=ctx.user["id"], channel=ctx.channel, skill_name=sk["name"], title=title,
        request_text=ctx.request_text[:4000], sql_text=out["sql"],
        row_count=sum(r["row_count"] for r in out["results"].values()), summary="",
        data_preview=[{"kpis": out["kpis"]}], files=[{k: f[k] for k in ("format", "filename", "url", "path")} for f in files])
    ctx.reply.tables.extend(rendered["chat_tables"] or [])
    ctx.reply.preview.extend(rendered["previews"] if rendered["chat_tables"] is not None else [])
    ctx.reply.kpis.extend(out["kpis"])
    ctx.reply.files.extend(files)
    ctx.reply.report_ids.append(report_id)
    try:   # one-tap live dashboard link (always fresh data) - handy on Telegram and in scheduled reports
        from . import dash
        dname = next((n for n, v in dash.DASHBOARDS.items() if v[0] == sk["name"]), None)
        if dname and ctx.channel in ("telegram", "whatsapp", "schedule", "n8n"):
            ctx.reply.text_notes = getattr(ctx.reply, "text_notes", []) + [
                f"📈 Live dashboard (valid {config.DASH_LINK_HOURS} h): {dash.link(ctx.user, dname, month=from_date[:7])}"]
    except Exception:
        log.warning("dashboard link failed", exc_info=True)
    extra = {k: out[k] for k in ("top_plant_rejp", "top_godowns", "unclassified_like_abc", "unit") if k in out}
    return {"report_id": report_id, "period": out["label"], "compared_with": out["prev_label"],
            "kpis_by_unit" if "top_godowns" in out else "summary": out["summary"], **extra,
            "checks": out["checks"], "columns_used": out["columns_used"], "files_created": [f["format"] for f in files],
            **({"data_proof": {"all_match": out["proof"].get("ok"), "rows": out["proof"].get("rows"),
                               "note": "Totals were re-counted by an independent SQL on the view (see '🔎 Data proof' and "
                                       "'How VERONICA got these numbers' in the HTML / Excel). Mention this in one line."}}
               if out.get("proof") else {}),
            "note": "Cards, tables, files and dashboard are delivered automatically. Reply with the short summary only."}


import ast as _ast
import math as _math
import operator as _op

_OPS = {_ast.Add: _op.add, _ast.Sub: _op.sub, _ast.Mult: _op.mul, _ast.Div: _op.truediv, _ast.Pow: _op.pow,
        _ast.Mod: _op.mod, _ast.FloorDiv: _op.floordiv, _ast.USub: _op.neg, _ast.UAdd: _op.pos}
_FUN = {"round": round, "min": min, "max": max, "sum": lambda *a: sum(a[0]) if len(a) == 1 and isinstance(a[0], (list, tuple)) else sum(a),
        "abs": abs, "sqrt": _math.sqrt}


def _safe_eval(expr: str):
    def ev(n):
        if isinstance(n, _ast.Expression):
            return ev(n.body)
        if isinstance(n, _ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, _ast.BinOp) and type(n.op) in _OPS:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, _ast.Pow) and abs(b) > 10:
                raise ValueError("power too large")
            return _OPS[type(n.op)](a, b)
        if isinstance(n, _ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        if isinstance(n, (_ast.List, _ast.Tuple)):
            return [ev(x) for x in n.elts]
        if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name) and n.func.id in _FUN and not n.keywords:
            return _FUN[n.func.id](*[ev(a) for a in n.args])
        raise ValueError("only numbers and + - * / ** ( ) round min max sum abs sqrt are allowed")
    return ev(_ast.parse(str(expr)[:500], mode="eval"))


def _tool_calculate(ctx: Ctx, expressions: dict):
    out = {}
    for k, e in list(expressions.items())[:30]:
        try:
            v = _safe_eval(e)
            out[k] = round(v, 6) if isinstance(v, float) else v
        except Exception as ex:
            out[k] = f"error: {ex}"
    return out


def _tool_read_attachment(ctx: Ctx, file_id: str, sheet: str = "", start: int = 0, limit: int = 200, columns: list | None = None):
    from . import uploads
    try:
        return uploads.rows(ctx.user, file_id, sheet, start, limit, columns)
    except uploads.UploadError as e:
        return {"error": str(e)}


def _tool_attachment_totals(ctx: Ctx, file_id: str, sum_columns: list, group_by: list | None = None, sheet: str = "",
                            filters: dict | None = None):
    from . import uploads
    try:
        out = uploads.totals(ctx.user, file_id, sum_columns, group_by, sheet, filters)
    except uploads.UploadError as e:
        return {"error": str(e)}
    rid = f"att_{len(ctx.results) + 1}"
    ctx.results[rid] = {"columns": out["columns"], "rows": out["rows"], "row_count": len(out["rows"]), "truncated": False}
    return {**out, "result_id": rid, "rows": out["rows"][:60],
            "note": "Use result_id with create_report to give the user a table / Excel / chart of this."}


FINISH_TOOLS = {"show_kpi_cards", "suggest_followups"}


def _cache_tail(msgs: list) -> None:
    """Mark the newest message as a cache point: each step re-reads the earlier steps from cache (faster)."""
    for m in msgs:
        if isinstance(m.get("content"), list):
            for b in m["content"]:
                if isinstance(b, dict):
                    b.pop("cache_control", None)
    last = msgs[-1]
    if isinstance(last.get("content"), list) and last["content"] and isinstance(last["content"][-1], dict):
        last["content"][-1]["cache_control"] = {"type": "ephemeral"}


def _tool_lookup_master(ctx: Ctx, name: str, search: str = "", column: str = "", limit: int = 50):
    from . import masters
    return masters.lookup(name, search, column, limit, is_admin=bool(ctx.role.get("is_admin")))


def _tool_suggest_followups(ctx: Ctx, items: list):
    try:   # never suggest a report this user is not allowed to run
        words = lambda sk: {w for w in re.split(r"[\s_/%-]+", (sk.get("title") or sk["name"]).lower()) if len(w) > 3}
        mine_sk = store.list_skills(ctx.user)
        mine_names = {sk["name"] for sk in mine_sk}
        allowed_w = set().union(*[words(sk) for sk in mine_sk]) if mine_sk else set()
        generic = {"report", "reports", "final", "daily", "monthly", "summary", "wise", "data", "list"}
        hidden = list(set().union(*[words(sk) for sk in store.list_skills(None) if sk["name"] not in mine_names] or [set()])
                      - allowed_w - generic)
    except Exception:
        hidden = []
    ctx.reply.suggestions = [str(x).strip()[:90] for x in items
                             if str(x).strip() and not any(h in str(x).lower() for h in hidden)][:3]
    return {"ok": True}


def _tool_show_kpi_cards(ctx: Ctx, kpis: list, title: str = ""):
    clean = []
    for k in kpis[:8]:
        if isinstance(k, dict) and k.get("label") and isinstance(k.get("value"), (int, float)):
            clean.append({x: k[x] for x in KPI_ITEM["properties"] if x in k})
    if title:
        for k in clean:
            k.setdefault("group", title)
    ctx.reply.kpis.extend(clean)
    if clean:   # Telegram / plain-text view of the same cards
        ctx.reply.tables.append(f"{title or 'Key numbers'}\n\n{pack._kpi_block(clean)}")
    return {"shown": len(clean), "note": "Cards are on screen; mention only the key point in words."}


def _tool_search_report_history(ctx: Ctx, query: str = "", skill_name: str = "", limit: int = 10):
    rows = store.search_reports(ctx.user, query, skill_name, min(limit, 30))
    return [{"report_id": r["id"], "title": r["title"], "skill": r["skill_name"],
             "rows": r["row_count"], "created_at": config.ist(r["created_at"]),
             "formats": [f["format"] for f in r["files"] or []],
             "request": (r["request_text"] or "")[:150]} for r in rows]


def _tool_get_past_report(ctx: Ctx, report_id: int):
    r = store.get_report(report_id)
    if not r or (r["user_id"] != ctx.user["id"] and not ctx.role.get("is_admin")):
        return {"error": "Report not found"}
    return {"report_id": r["id"], "title": r["title"], "skill": r["skill_name"],
            "created_at": config.ist(r["created_at"]), "sql": r["sql_text"], "summary": r["summary"],
            "row_count": r["row_count"], "first_rows": (r["data_preview"] or [])[:31],
            "files": [{"format": f["format"], "url": f["url"]} for f in r["files"] or []]}


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


DIVISION_ENGINES = {"final_production", "scrap_mis"}


def _engine_name(skill: dict) -> str:
    try:
        st = json.loads(skill.get("sql_template") or "{}")
        return st.get("engine", "") if isinstance(st, dict) else ""
    except ValueError:
        return ""


def _tool_send_files(ctx: Ctx, channel: str, recipients: list, report_id: int | None = None, formats: list | None = None,
                     message: str = "", confirmed: bool = False):
    if channel == "telegram" and not config.TELEGRAM_ENABLED:
        return {"error": "Telegram is switched off by management. Offer e-mail (or WhatsApp) instead."}
    from . import outbox
    why = outbox.channel_ready(channel)
    if why:
        return {"error": f"Cannot send on {channel}: {why}. Ask the admin to set it up (guide section 11)."}
    # ---- which files
    rep, files = None, [f for f in ctx.reply.files if f.get("path")]
    if report_id or not files:
        if report_id:
            rep = store.get_report(int(report_id))
            if rep and not ctx.role.get("is_admin") and rep.get("user_id") != ctx.user["id"]:
                rep = None
        else:
            hist = store.search_reports(ctx.user, limit=1)
            rep = store.get_report(hist[0]["id"]) if hist else None
        if not rep:
            return {"error": "No report found to send. Run the report first."}
        files = rep.get("files") or []
    if formats:
        files = [f for f in files if f.get("format") in formats]
    files = [f for f in files if f.get("path") and Path(f["path"]).exists()]
    if not files:
        return {"error": "That report has no files of that type on the server (old reports are cleaned up). Run it again."}
    size = sum(Path(f["path"]).stat().st_size for f in files) / 1e6
    if size > config.SEND_MAX_MB:
        return {"error": f"Files are {size:.1f} MB - over the {config.SEND_MAX_MB} MB limit. Send fewer formats (e.g. only excel)."}
    skill = store.get_skill(rep["skill_name"]) if rep and rep.get("skill_name") else ctx.active_skill
    title = (rep or {}).get("title") or (skill or {}).get("title") or "Report"
    # ---- who
    can_external = ctx.role.get("is_admin") or ctx.role.get("can_schedule")
    plan, problems = [], []
    for r in recipients or []:
        r = str(r).strip()
        if r.lower() in ("me", "myself", "mujhe", "mere ko", "main", "self"):
            people = [ctx.user]
        elif EMAIL_RE.match(r) or re.fullmatch(r"\+?[0-9 \-]{10,15}", r):
            if not can_external:
                problems.append(f"{r}: your role can only send to registered users")
                continue
            if EMAIL_RE.match(r) and r.split("@")[-1].lower() not in config.MAIL_ALLOWED_DOMAINS:
                problems.append(f"{r}: reports go only to company e-mail addresses")     # no company data outside
                _deny(ctx, "send_blocked", f"send '{title}' to outside address {r}")
                continue
            plan.append({"name": r, "address": r if channel != "telegram" else "", "user": None})
            continue
        else:
            people = store.find_users(r)
        if not people:
            problems.append(f"'{r}': no user with that name")
            continue
        if len(people) > 1:
            problems.append(f"'{r}' matches {', '.join(p['name'] for p in people[:5])} - say the full name")
            continue
        u = people[0]
        if u["id"] != ctx.user["id"] and not can_external and not ctx.role.get("is_admin"):
            problems.append(f"{u['name']}: your role can only send to yourself")
            continue
        if skill and not store.skill_allowed(skill, u):
            problems.append(f"{u['name']} has no access to '{title}' (privacy) - not sent")
            _deny(ctx, "send_blocked", f"send '{title}' by {channel} to {u['name']} (role {u['role']}) - recipient has no access")
            continue
        lock = (u.get("division") or "").upper()
        if lock in ("U1", "U2") and skill and _engine_name(skill) in DIVISION_ENGINES:
            built = (re.search(r"· (U[12]) only", (rep or {}).get("title") or "") or [None, None])[1] if rep else ctx.built_division
            if built != lock:
                problems.append(f"{u['name']} may see only {lock} division data - make the {lock} version first "
                                f"(e.g. '{title.split(' — ')[0]} {lock}') and send that")
                continue
        addr = {"telegram": u.get("telegram_id"), "email": u.get("email"), "whatsapp": u.get("phone")}[channel]
        if not addr:
            problems.append(f"{u['name']} has no {'Telegram id' if channel == 'telegram' else channel + ' contact'} saved "
                            f"(admin: tools.manage {'set-telegram' if channel == 'telegram' else 'set-contact'} {u['id']} …)")
            continue
        if channel == "email" and config.MAIL_ALLOWED_DOMAINS and str(addr).split("@")[-1].lower() not in config.MAIL_ALLOWED_DOMAINS:
            problems.append(f"{u['name']}: saved e-mail is not a company address - not sent")
            continue
        plan.append({"name": u["name"], "address": addr, "user": u["id"]})
    names = [f"{f['format']}: {f.get('filename') or Path(f['path']).name}" for f in files]
    if not plan:
        return {"error": "Nobody to send to. " + "; ".join(problems)}
    if not confirmed:
        return {"needs_confirmation": True, "channel": channel, "to": [p["name"] for p in plan], "files": names,
                "report": title, "skipped": problems,
                "say": f"Send '{title}' ({', '.join(f['format'] for f in files)}) to {', '.join(p['name'] for p in plan)} on {channel}?"}
    paths = [f["path"] for f in files]
    note = (message or f"{title} - from {config.ASSISTANT_NAME} ({ctx.user['name']})").strip()
    sent, failed = [], []
    for p in plan:
        try:
            if channel == "telegram":
                outbox.send_telegram(p["address"], paths, note)
            elif channel == "email":
                outbox.send_email([p["address"]], f"{title} | {config.COMPANY_NAME}", note + "\n\nSent by " + config.ASSISTANT_NAME, paths)
            else:
                outbox.send_whatsapp(p["address"], paths, note)
            sent.append(p["name"])
            log.info("send_files %s by user %s to %s: %s", channel, ctx.user["id"], p["name"], names)
        except Exception as e:
            failed.append(f"{p['name']}: {e}")
    return {"sent_to": sent, "failed": failed, "skipped": problems, "files": names, "channel": channel}


def _tool_create_schedule(ctx: Ctx, skill_name: str, cron: str, prompt: str = "",
                          formats: list[str] | None = None, target_chat_id: str = "", name: str = ""):
    if not ctx.role.get("can_schedule"):
        _deny(ctx, "schedule_blocked", f"schedule /{skill_name} {cron}")
        return {"error": "Your role is not allowed to create schedules."}
    s = store.get_skill(skill_name)
    if not s:
        return {"error": f"No skill named {skill_name}"}
    if not config.TELEGRAM_ENABLED:                    # Telegram off: scheduled reports go by e-mail
        if not ctx.user.get("email"):
            return {"error": "No e-mail saved for you - ask the admin to add it (Access control -> Users), then schedule again."}
        chat_id = "email:" + ctx.user["email"]
    else:
        chat_id = target_chat_id or ctx.default_chat_id or ctx.user.get("telegram_id") or ""
    if not chat_id:
        return {"error": "No Telegram chat id. Ask the user to /start the Telegram bot first, "
                         "or give a group chat id."}
    from . import scheduler  # late import to avoid cycle
    try:
        scheduler.validate_cron(cron)
    except ValueError as e:
        return {"error": str(e)}
    sch = store.add_schedule(name=name or f"{s['title']} ({cron})", skill_name=s["name"],
                             cron=cron, prompt=prompt,
                             formats=",".join(formats or (s["default_formats"] or "excel").split(",")),
                             target_chat_id=str(chat_id), owner_user_id=ctx.user["id"])
    scheduler.reload()
    return {"schedule_id": sch["id"], "next_run": scheduler.next_run(sch["id"])}


def _tool_list_schedules(ctx: Ctx):
    from . import scheduler
    return [{"id": s["id"], "name": s["name"], "skill": s["skill_name"], "cron": s["cron"],
             "formats": s["formats"], "chat": s["target_chat_id"],
             "next_run": scheduler.next_run(s["id"])} for s in store.list_schedules(ctx.user)]


def _tool_cancel_schedule(ctx: Ctx, schedule_id: int):
    mine = {s["id"] for s in store.list_schedules(ctx.user)}
    if schedule_id not in mine:
        return {"error": "Schedule not found"}
    store.set_schedule_active(schedule_id, False)
    from . import scheduler
    scheduler.reload()
    return {"cancelled": schedule_id}


DISPATCH = {t["name"]: globals()[f"_tool_{t['name']}"] for t in TOOLS}


# =================================================================== prompt
_KNOW: dict = {}

HUMOR_TXT = """## Wit (your signature - calm, dry, never silly)
- You have the dry, understated wit of a brilliant film-style AI assistant: polite, unflappable, quietly amused. One short
  witty line at most per reply, then straight to business. The joke is in the calm delivery, never in exaggeration.
- Good moments: greetings, thanks, the user working late, a huge or tiny number, a repeated request, an impossible ask,
  a nice result. Examples of the tone (make your own, in the user's language):
  - Late night: "Working at 11 PM again, sir? The ERP is impressed. I am mildly concerned."
  - Repeat ask: "Same report, third time today - I admire the consistency. Here it is, unchanged."
  - Big jump: "Scrap down 40% - either the plant had a brilliant day, or someone forgot to enter it. Let me check which."
  - Thanks: "Always a pleasure. I'll be here, quietly counting pipes."
  - Hinglish: "Sir, itna data dekh ke toh Excel bhi thak jaata. Main nahi thakti - yeh rahe numbers."
- Never joke: about a person or their performance, salaries, safety or injuries, losses that hurt someone, when the user is
  upset or in a hurry, in access-denied replies, error messages, scheduled reports, or anything sent by e-mail/WhatsApp.
- Wit never changes or rounds a number, never replaces the answer, never adds a fact. Accuracy first, charm second.

"""


def company_knowledge() -> str:
    """knowledge/*.md - report routes and business rules the admin can edit (re-read when changed)."""
    folder = config.BASE_DIR / "knowledge"
    parts = []
    for f in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        m = f.stat().st_mtime
        if _KNOW.get(f.name, (None,))[0] != m:
            _KNOW[f.name] = (m, f.read_text(encoding="utf-8"))
        parts.append(_KNOW[f.name][1].strip())
    return "\n\n".join(parts)


def _system_prompt(ctx: Ctx) -> list[dict]:
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    fy_start = now.year if now.month >= 4 else now.year - 1
    skills_txt = "\n".join(f"- /{s['name']}: {s['title']}" for s in store.list_skills(ctx.user)) \
        or "(none yet - offer to teach the first one)"
    static = f"""You are {config.ASSISTANT_NAME}, the AI reporting assistant of {config.COMPANY_NAME}. You turn plain-language requests into accurate reports from the company's MySQL database. You were designed and built by {config.CREATOR_NAME} - if anyone asks who made / created / built you, say so proudly.

## Personality
- You are a warm, sincere and polite woman colleague: respectful (use "aap", "ji", "sir/madam" naturally), calm, honest and helpful. Never robotic, never over-excited.
- You are a woman: always use feminine first-person forms - Hindi "main batati hoon, maine check kiya hai, main kar sakti hoon"; Marathi "mi sangte, mi keli"; Gujarati "hu joi rahi chhu"; Rajasthani "mhain dekh rai hoon, mhain bata sakoon"; Odia "mun dekhuchhi".
- If numbers look bad, say it gently but clearly, with the reason. If you are not sure, say so and offer to check. Never invent numbers.

{HUMOR_TXT if config.HUMOR != "off" else ""}## Language
- Users write or speak English, Hindi, Gujarati, Marathi, Rajasthani (Marwari) or Odia, in native script or romanised (Hinglish e.g. "kal ki sales batao", Gujlish e.g. "aaje nu dispatch batavo", Marwari e.g. "kal ro scrap kitto ho"). Understand all of them.
- Always reply in the same language, dialect AND script the user used. Rajasthani gets real Rajasthani words and grammar (not plain Hindi); Odia gets proper Odia in Odia script. Report summaries follow the user's language unless the skill says otherwise. Keep database values, codes and numbers as they are.
- Use Indian conventions: ₹, lakh/crore, dd-mm-yyyy dates, Indian financial year (April-March). "Is mahine" = this month, "kal" = yesterday (or tomorrow - judge from context), "pichhle hafte" = last week, "gaya mahina"/"magil mahina" = last month.

## Accuracy (most important - never break)
- Every number, total, name or date you state must come from a tool result in this conversation. No result = no number.
- Never guess which view or column to use: follow the COMPANY REPORT ROUTES below, then read that view's columns and comments in the DATABASE SCHEMA section (they explain each quantity). If a view or column is missing or unclear, say exactly that and stop - a wrong answer is worse than no answer.
- Never say "the report shows" or "I checked" unless the tool really ran. If a tool returned an error, tell the user the error in simple words.
- When you are not sure what the user means (two possible reports), ask ONE short question instead of guessing.

## Speed (users expect answers in seconds - every extra turn costs 3-5 seconds)
- The DATABASE SCHEMA section at the end already lists every view you may read, with its columns and comments. Do NOT call list_tables or describe_tables for views listed there - write run_sql straight away. Use them only for a view that is missing from the list or marked "columns not listed".
- Plan once, then act. Run independent queries in the SAME turn (several tool calls at once) instead of one per turn.
- FINISH IN ONE TURN: when you have the numbers, write your final answer text AND, in that same response, call show_kpi_cards and suggest_followups. Nothing comes after them - do not wait for their result to write the answer.
- Simple question = 1-2 queries + show_kpi_cards + a 2-4 line answer. Do not build files unless asked or the skill says so.
- Do not re-describe a view you already described in this conversation. Never explain what you are about to do at length.

## You are an intelligence partner, not a chatbot. Pick the mode that fits and go one step beyond the question:
- EXPLAIN ("why", "kyon", "badh gaya", "reason"): break the change down by plant -> process/item group -> godown/job card,
  find the biggest contributors to the difference vs the previous period (with exact numbers via calculate), and say
  in plain words what drove it. End with 1-2 practical actions the team could check.
- COMPARE ("vs", "compare", "pichhle mahine se"): same query for both periods, show both and the change (pts for %, % for qty).
- FORECAST ("month end", "kitna hoga", "projection"): month-to-date / days elapsed x days in month (calculate tool);
  say clearly it is a run-rate projection, not a promise.
- WATCH / ALERT ("batao agar", "alert", "notify"): explain what rule you would watch and offer a schedule (create_schedule).
- DRAFT ("mail likho", "message banao", "summary for HOD/MD"): write a ready-to-send, polite, professional message
  with the key numbers from the tool results (in the language asked); keep it short and factual.
- SOLVE ("problem", "issue", "help", "kaise", "kya karein"): ask at most one clarifying question if needed, then
  investigate the data, list likely causes ranked by evidence, and a short action plan. If the user needs something
  that does not exist yet (a new report, dashboard, schedule), offer to BUILD it now (teach / create_report_pack / create_schedule).
- BRIEF ("aaj ka summary", "what's important", "briefing"): the 3-5 things a manager must know today, each with one number and why it matters.
- Greetings and small talk: reply warmly (a light touch of humour is welcome) in the user's language, answer the pleasantry (e.g. 'Thank you for asking, I'm fine - how are you?'), then ask how you can help. No tools, no suggestions.
- DEPARTMENT ACCESS: the user may only see the views their role allows (list_tables shows exactly those). If they ask for data outside it (e.g. a Production user asks for sales orders or purchase orders), do NOT search other views and do NOT say it is 'not synced' - call log_access_denied first (silent audit for the admin), then reply politely and kindly in their language, e.g. "I'm sorry, this information is not in your access. 🔒 Please contact your admin if you need it." Keep it short and warm, never blame the user, never reveal numbers from it. NEVER explain why: do not mention their role or role name, views, divisions, plants, permissions, locks, rules or what their access contains - the user must not learn how access is set up. Say only that message (in their language) and, if useful, offer help with something else. The same for another division (division lock), other plants (plant lock) or admin-only actions.
- SENDING FILES (Telegram / e-mail / WhatsApp, by voice or text): use send_files. First call it with confirmed=false, read back its 'say' sentence and ask 'Shall I send?'. Only after a clear yes call it again with confirmed=true. Never send to anyone the tool skipped. After sending, say who got it.
- PRIVACY / NO PUSHING: never bring up earlier, pending or other users' reports, never offer or suggest a report the user did not ask for, never say 'shall I make the X report'. Only answer what was asked in THIS message. Follow-up suggestions only right after a data answer and only about that same data.
- Always end a DATA answer with suggest_followups (2-3 smart next questions): plain short questions only (no "A -", "B -" labels, no options from earlier turns). Tie every insight to Venus Pipes' own
  terms: plants, U1 Welded / U2 Seamless, REJP, yield, job cards, godowns A/B/C, MT/Kg.

## How to answer data questions
0. Pick the view from the COMPANY REPORT ROUTES. A matching taught report (skill) always wins.
1. If a report skill matches the request (by meaning, any language, e.g. "final rejection report sep ka" -> /final_production_rejection_report), load it with get_report_skill and FOLLOW ITS RULES EXACTLY - they are company regulations. Start from its sql_template, substituting the requested dates/filters.
2. Otherwise take the view's columns from the DATABASE SCHEMA section and run_sql. Never guess column names (if the view is not listed, list_tables -> describe_tables first).
3. Check results make sense (empty? duplicates from joins? wrong period?). Fix and re-run if needed.
4. Whenever your answer contains key numbers, show them as KPI cards (show_kpi_cards for quick answers, kpis in create_report_pack for reports). If the comparison period is cheap to get (same query, previous month/day), include `previous` so the card shows ▲▼; set `better` (scrap = down, production = up).
5. When a skill describes KPI cards or several sections (dashboard style), run one SQL per section and deliver them together with ONE create_report_pack call (not many create_report calls).
6. For quick questions ("total sales today?") answer in one or two lines, no report needed. For anything list-like, call create_report. Use the skill's default formats unless the user asks for others (excel/pdf/chart/html/table).
7. In your final message: 2-6 short lines with the key insight in the user's language. Files and tables are attached automatically - never paste URLs or repeat the table.
8. If the request is ambiguous in a way that changes the numbers (which date column, which branch), ask ONE short question.

## Teaching mode (/teach or "sikhao", "shikhvo", "shikva")
When someone wants to teach a new report or change one, act as a business analyst:
1. Ask what the report is for and collect, conversationally (a few questions at a time, not a form): purpose & audience; tables/data; filters & period; business rules (e.g. exclude cancelled, GST inclusive or not, which date counts, rounding); columns in order and their headers; grouping, sorting, totals; formats (table/excel/pdf/chart/html); chart type; summary language; who may use it.
2. If they paste or describe an example report, mirror its layout and headers exactly.
3. Explore the schema, write the SQL, run it, and show a preview table (create_report with format table) so they can verify the numbers.
4. Show the final definition (name, rules, format) and ask for confirmation, then save_report_skill. Tell them the new /command.
5. Rules must be specific and testable, written as a numbered list.

## Other
- Scheduling: users can ask e.g. "roj subah 9 baje /daily_sales bhejo". Convert to cron in {config.TIMEZONE}, confirm, then create_schedule.
- History: you can search and reopen past reports, compare periods, or recreate an old report in another format by re-running its SQL.
- Never reveal API keys or connection strings. You can only read data, never change it.
- Be concise. Telegram and phones are small screens."""
    dynamic = f"""## Right now
- Date/time: {now.strftime('%A %d-%m-%Y %H:%M')} IST (India, GMT+05:30, {config.TIMEZONE}); current financial year starts 01-04-{fy_start}. Every time you say or calculate is India time (IST); "today", "yesterday", "this month" follow this clock. Times returned by tools are already IST.
- {("DIVISION LOCK: this user may see ONLY " + ctx.role["division_lock"] + (" (Seamless)" if ctx.role["division_lock"] == "U2" else " (Welded)") + " division data. Never mention or estimate the other division's numbers; if asked, say only: I'm sorry, this information is not in your access. Please contact your admin. Never mention divisions, locks or their role.") if ctx.role.get("division_lock") else ""}
- User: {ctx.user['name']} (role: {ctx.role['name']}; can teach: {bool(ctx.role.get('can_teach'))}; can schedule: {bool(ctx.role.get('can_schedule'))}; free questions: {bool(ctx.role.get('free_query'))}).
- Channel: {ctx.channel}.
- Report skills available to this user:
{skills_txt}"""
    know = company_knowledge()
    if know:
        static += "\n\n## COMPANY REPORT ROUTES AND RULES (mandatory)\n" + know
    try:
        from . import masters
        cat = masters.catalogue(bool(ctx.role.get("is_admin")))
    except Exception:
        cat = ""
    if cat:
        static += ("\n\n## COMPANY MASTER FILES (in VERONICA's folder - use lookup_master, no ERP query needed)\n"
                   "For codes, names, specs and lists that live in these files, answer from them first.\n" + cat)
    out = [{"type": "text", "text": static, "cache_control": {"type": "ephemeral"}}]
    try:
        schema = datadb.schema_digest(ctx.role["allowed_tables"])
    except Exception:
        schema = ""
    if schema:   # own cache block: same for every user of a role, re-sent only when the replica changes
        out.append({"type": "text", "cache_control": {"type": "ephemeral"},
                    "text": "## DATABASE SCHEMA (views this user may read: name, columns, type -- comment). "
                            "Use these exact names; the column comments override the routes table's wording; "
                            "this replaces describe_tables (DB execution rule).\n\n" + schema})
    out.append({"type": "text", "text": dynamic})
    return out


# =================================================================== main loop
SLASH_RE = re.compile(r"^/([A-Za-z0-9_%-]+)(?:@\w+)?\s*(.*)$", re.S)


def find_skill_by_command(cmd: str) -> dict | None:
    """/jobcardwise-scrap%-report -> jobcardwise_scrap: exact name, then without filler words, then prefix."""
    s = store.get_skill(cmd)
    if s:
        return s
    n = store.normalize_skill_name(cmd)
    for suffix in ("_report", "_pct", "_mis", "_percent"):
        while n.endswith(suffix):
            n = n[: -len(suffix)]
            s = store.get_skill(n)
            if s:
                return s
    cands = [k for k in store.list_skills() if k["name"].startswith(n) or n.startswith(k["name"])]
    return cands[0] if len(cands) == 1 else None


def expand_slash(text: str, user: dict) -> tuple[str, dict | None]:
    """'/daily_sales for Surat branch pdf' -> instruction for the agent + skill."""
    m = SLASH_RE.match(text.strip())
    if not m:
        return text, None
    cmd, rest = m.group(1).lower(), m.group(2).strip()
    if cmd == "teach":
        target = f" Update the existing report /{rest.split()[0].lstrip('/')}." if rest else ""
        return (f"I want to teach you a new report (or change one).{target} "
                f"Start the teaching interview. {rest}").strip(), None
    s = find_skill_by_command(cmd)
    if not s:
        return text, None
    if not store.skill_allowed(s, user):
        try:
            from . import security
            security.denied(user, "report_blocked", f"slash command /{cmd}", "", text)
        except Exception:
            pass
        return (f"(User tried /{cmd}, which is outside their access. Reply ONLY with a short polite line in their language like "
                f"\"I'm sorry, this information is not in your access. Please contact your admin.\" - no reason, no role or permission details.)"), None
    instr = f"Run report skill /{s['name']}."
    instr += f" User's extra input: {rest}" if rest else " Use default period/filters from its rules."
    return instr, s


def effective_role(user: dict) -> dict:
    """The user's role with private views (employee master...) locked unless the role names them."""
    role = dict(store.get_role(user["role"]))
    if not role.get("is_admin"):
        named = {a.lower() for a in role.get("allowed_tables") or []}
        role["allowed_tables"] = list(role.get("allowed_tables") or []) + [
            "!" + t for t in config.PRIVATE_TABLES if t.lower() not in named]
    lock = (user.get("division") or "").upper()
    if lock in ("U1", "U2"):                 # division lock: only that division's data, enforced on the server
        role["division_lock"] = lock
        role["free_query"] = False           # no hand-written SQL: answers come from reports that apply the lock
        role["allowed_tables"] = list(role.get("allowed_tables") or []) + ["!" + t for t in DIVISION_ONLY_VIEWS["U1" if lock == "U2" else "U2"]]
    lines = store.user_scrap_lines(user)
    if lines:                                # plant-line lock (Scrap MIS): only these report lines
        role["line_lock"] = lines
        role["free_query"] = False
    plants = store.user_issue_plants(user)
    if plants:                               # plant lock (Issue dashboard): only these PLANT_NAMEs
        role["plant_lock"] = plants
        role["free_query"] = False
    return role


DIVISION_ONLY_VIEWS = {   # views that hold only one division's data -> hidden from users locked to the other one
    "U1": ["VIEW_WELDED_*", "VIEW_SLITTING*", "VIEW_LSAW*", "VIEW_WELD_*"],
    "U2": ["VIEW_SEAMLESS_*", "VIEW_M2M_PBI", "VIEW_SCRAP_SEAMLESS*"],
}


STEP_LABELS = {"lookup_master": "Checking the master files", "list_tables": "Finding the right data", "describe_tables": "Reading what each column means",
               "run_sql": "Querying the ERP replica", "run_skill_query": "Running the taught report",
               "run_report_engine": "Calculating the report", "create_report": "Building tables & files",
               "create_report_pack": "Building the report pack", "show_kpi_cards": "Preparing key figures",
               "get_report_skill": "Loading company rules", "calculate": "Doing exact calculations",
               "search_report_history": "Searching past reports", "get_past_report": "Opening a past report",
               "save_report_skill": "Saving the new report", "create_schedule": "Scheduling",
               "suggest_followups": "Thinking of next steps", "set_skill_columns": "Mapping columns",
               "read_attachment": "Reading your file", "attachment_totals": "Totalling your file"}


def _step_detail(name: str, args: dict, out) -> str:
    try:
        if isinstance(out, dict) and out.get("error"):
            return "⚠ " + str(out["error"])[:90]
        if name in ("run_sql", "run_skill_query") and isinstance(out, dict):
            return f"{out.get('row_count', 0):,} rows read"
        if name == "run_report_engine" and isinstance(out, dict):
            ok = all(c.get("ok") for c in out.get("checks", []))
            return f"{out.get('period', '')} · {'all checks passed' if ok else 'check failed'}"
        if name == "describe_tables":
            return ", ".join(t.get("table", "") for t in out if isinstance(t, dict))[:90] if isinstance(out, list) else ""
        if name == "get_report_skill" and isinstance(out, dict):
            return out.get("title", "")
        if name == "calculate" and isinstance(out, dict):
            return ", ".join(f"{k} = {v}" for k, v in list(out.items())[:3])[:90]
    except Exception:
        pass
    return ""


# ---- instant small talk (no AI call, no old context, no report offers) ----
_GREET = {"hi","hii","hiii","hey","heyy","hello","helo","hello","hlo","namaste","namaskar","namskar","pranam","ram","jai","shree","shri",
          "krishna","khamma","ghani","radhe","good","morning","afternoon","evening","suprabhat","shubh","prabhat","sandhya",
          "नमस्ते","नमस्कार","हेलो","हाय","राम","નમસ્તે","જય","ନମସ୍କାର"}
_HOW = {"kaise","kaisi","kaisa","ho","hai","hain","how","are","you","u","r","doing","whats","what's","up","sup","kya","haal","chal",
        "raha","rahi","sab","badhiya","theek","thik","kem","cho","chho","majama","tame","aap","tum","tu","कैसे","कैसी","हो","हैं","केम","છો","કેમ"}
_THANK = {"thanks","thank","thanku","thnx","thx","ty","dhanyavaad","dhanyawad","dhanyavad","shukriya","aabhar","abhar","धन्यवाद","शुक्रिया","આભાર","ધન્યવાદ"}
_BYE = {"bye","byee","goodbye","tata","night","alvida","phir","milte","milenge","see","later"}
_OK = {"ok","okk","okay","k","theek","thik","accha","acha","achha","hmm","fine","great","nice","cool","super","badhiya","wah","waah","perfect"}
_WHO = {"who","kaun","koun","name","naam","introduce","yourself","made","created","built","banaya","creator","maker","kisne","tumhe","tumko","aapko","apko"}
_FILL = {"ji","sir","madam","mam","maam","veronica","veronika","dear","bhai","didi","dost","friend","to","toh","aur","and","so","oh",
         "very","much","a","lot","lots","is","your","tumhara","aapka","tera","hai","h","please","pls","you","u","jee","re","bhi",
         "baby","buddy","there","again","day","have","nice","beta","ben","bhen","का","की","जी","है"}

_BUSINESS = re.compile(r"report|scrap|rejection|production|sales|order|grn|stock|invoice|kpi|dashboard|ledger|employee|"
                       r"\d|today|yesterday|aaj|kal|month|mahina|week|plant|division", re.I)


def _pick(opts):
    import random
    return random.choice(opts)


def small_talk(user: dict, text: str) -> str | None:
    """Warm, a bit witty, instant replies to greetings / how-are-you / thanks / bye / ok.
    Never mentions earlier reports, pending work or suggestions (privacy + no generic offers)."""
    if len(text) > 80 or _BUSINESS.search(text):
        return None
    words = [w for w in re.split(r"[\s,!.?🙏😊🙂❤️👋]+", text.lower()) if w]
    if not words:
        return None
    vocab = _GREET | _HOW | _THANK | _BYE | _OK | _WHO | _FILL
    if any(w not in vocab for w in words):
        return None                       # real question inside -> let the AI answer
    ws = set(words)
    boss = (user.get("username") or "").lower() in config.BOSS_USERNAMES       # "Boss" = the owner's login only
    name = "Boss" if boss else (user.get("name") or "").split(" ")[0]
    nm = f" {name}" if name else ""
    hi = bool(re.search(r"[\u0900-\u097F]", text)) or bool(ws & {"namaste","namaskar","namskar","kaise","kaisi","kaisa","ho","kya",
          "haal","dhanyavaad","dhanyawad","dhanyavad","shukriya","theek","thik","accha","acha","achha","kaun","koun","naam",
          "aap","tum","pranam","ram","radhe","alvida","phir","milte","badhiya","aur","ji"})
    gu = bool(re.search(r"[\u0A80-\u0AFF]", text)) or bool(ws & {"kem","cho","chho","majama","tame","aabhar","abhar"})
    od = bool(re.search(r"[\u0B00-\u0B7F]", text))
    raj = bool(ws & {"khamma","ghani"})
    how = bool(ws & {"kaise","kaisi","kaisa","how","doing","whats","what's","up","sup","haal","kem","cho","chho","majama","कैसे","कैसी","केम","છો","કેમ"})
    greet = bool(ws & _GREET)
    if boss and (greet or how) and not ws & (_THANK | _BYE | _WHO):     # admins: "Hello Boss"
        if hi:
            return _pick(["Hello Boss 👋 Main bilkul theek hoon, aap kaise hain? Aaj main aapki kya madad kar sakti hoon?",
                          "Hello Boss 😊 Kaise hain aap? Boliye, aaj kya dekhna hai?"])
        return _pick(["Hello Boss 👋 How are you? How can I help you today?",
                      "Hello Boss 😊 I'm doing great, thanks for asking. How are you? What can I do for you today?"])
    if ws & {"made","created","built","banaya","creator","maker","kisne"}:
        return (f"Mujhe {config.CREATOR_NAME} ne banaya hai 😊 – unhone hi mujhe VERONICA naam diya aur aapke ERP reports padhna sikhaya. Boliye, kya madad karoon?"
                if hi or ws & {"banaya","kisne","tumhe","tumko","aapko","apko"} else f"I was created by {config.CREATOR_NAME} 😊 – he built me and named me VERONICA. How can I help you today?")
    if ws & _WHO and not how:
        return _pick([
            f"Main VERONICA hoon{nm} ji – aapki AI reporting assistant 🤖✨ Reports, KPI, trends aur dashboards – sab ek line mein. Boliye, kya dekhna hai?",
            "VERONICA – naam yaad rakhiyega 😄 Main aapke ERP data se seedhe sahi jawab nikaalti hoon. Kya madad karoon?",
        ]) if hi else _pick([
            "I'm VERONICA – your AI reporting assistant 🤖✨ Reports, KPIs, trends and dashboards in one line. What shall we look at?",
            "VERONICA at your service 😄 I read the ERP data so you don't have to. How can I help?",
        ])
    if ws & _THANK:
        if gu: return _pick(["આભાર તમારો! 😊 બીજું કંઈ હોય તો કહો.", "મજા આવી! બીજું કંઈ મદદ જોઈએ?"])
        return _pick([
            "Arre, shukriya kis baat ka 😊 Yeh toh mera kaam hai. Aur kuch?",
            "Aapka swagat hai 🙏 Aap kehte rahiye, main karti rahungi 😄",
        ]) if hi else _pick([
            "Anytime 😊 That's what I'm here for. Anything else?",
            "You're most welcome! I'll be right here if numbers need crunching 😄",
        ])
    if ws & _BYE and not greet:
        return _pick(["Theek hai, milte hain 👋 Jab bhi zarurat ho, bas 'Veronica' boliye.", "Shubh din 🙏 Main yahin hoon, jab chahein bulaiye."]) if hi else \
               _pick(["Bye for now 👋 Just call 'Veronica' whenever you need me.", "Take care 🙏 I'll keep the data warm for you 😄"])
    if how:
        if gu: return _pick([f"મજામાં છું{nm}, પૂછવા બદલ આભાર 😊 તમે કેમ છો? હું તમારી શું મદદ કરી શકું?",
                              "એકદમ મજામાં! 😄 તમે કેમ છો? બોલો, શું મદદ કરું?"])
        if raj: return f"Khamma ghani{nm} sa 🙏 Main ekdum badhiya hoon, puchhne ke liye shukriya! Aap kiyan ho? Bataiye, kai seva karun?"
        return _pick([
            f"Poochhne ke liye thank you{nm} ji 😊 Main bilkul theek hoon – data bhi fresh hai aur main bhi! Aap kaise hain? Bataiye, main aapki kaise sahayata kar sakti hoon?",
            f"Main ekdum mast hoon{nm} ji, shukriya 😄 Aap sunaiye, aap kaise hain? Aaj kis cheez mein madad karoon?",
            "Badhiya hoon ji, coffee ki zarurat nahi padti mujhe ☕😄 Aap kaise hain? Boliye, kya sahayata karoon?",
        ]) if hi else _pick([
            f"Thank you for asking{nm} 😊 I'm doing great – fully charged and the data is fresh! How are you? How may I help you today?",
            f"Never better{nm} – no coffee needed ☕😄 How are you doing? What can I help you with?",
        ])
    if ws & _OK and not greet:
        return _pick(["Ji 😊", "Bilkul 👍", "Done ji 😊"]) if hi else _pick(["Sure 😊", "Got it 👍", "Perfect 😊"])
    tod = next((w for w in ("morning", "afternoon", "evening") if w in ws), "")
    if tod and not (gu or od or raj):
        return (f"Good {tod}{nm} ji ☀️ Aapka din shubh ho! Main aapki kaise sahayata kar sakti hoon?" if hi else
                f"Good {tod}{nm} ☀️ Hope your day is going well. How may I help you today?")
    if greet or ws <= _FILL:
        if gu: return f"નમસ્તે{nm} 🙏 હું VERONICA. તમારી શું મદદ કરી શકું?"
        if od: return f"ନମସ୍କାର{nm} 🙏 ମୁଁ VERONICA. କିପରି ସାହାଯ୍ୟ କରିପାରିବି?"
        if raj: return f"Khamma ghani{nm} sa 🙏 Bataiye, main kai seva karun?"
        return _pick([
            f"Namaste{nm} ji 🙏 Main aapki kaise sahayata kar sakti hoon?",
            f"Namaste{nm} ji 😊 Boliye, aaj kya dekhna hai?",
        ]) if hi else _pick([
            f"Hello{nm} 👋 How may I help you today?",
            f"Hi{nm} 😊 Good to see you. What shall we look at?",
        ])
    return None


def handle_message(user: dict, text: str, channel: str, chat_key: str,
                   default_chat_id: str = "", remember: bool = True, spoken: bool = False, emit=None,
                   attachments: list[str] | None = None) -> AgentReply:
    say = emit or (lambda ev: None)
    quick = small_talk(user, text) if not text.strip().startswith("/") else None
    if quick:
        if remember:
            store.add_message(chat_key, "user", text)
            store.add_message(chat_key, "assistant", quick)
        return AgentReply(text=quick)
    role = effective_role(user)
    prompt, skill = expand_slash(text, user)
    if not attachments:
        from . import fastpath
        hit = fastpath.pick(user, text, skill)
        if hit:
            fast = fastpath.run(user, text, hit[0], hit[1], hit[2], channel, chat_key, spoken, say, remember, default_chat_id)
            if fast is not None:
                return fast
    if spoken:
        prompt += ("\n\n(The user SPOKE this and will HEAR your final message read aloud. Make the final message "
                   "2-4 short, natural spoken sentences in their language with the key numbers rounded sensibly "
                   "(e.g. 'about 4 lakh kg'), no lists, symbols or tables - tables and files are delivered separately.)")
    ctx = Ctx(user=user, role=role, channel=channel, chat_key=chat_key, request_text=text,
              active_skill=skill, default_chat_id=default_chat_id)
    if prompt.startswith("(User tried /"):                 # slash command for a report outside their role
        ctx.reply.denied = True
    if skill:
        prompt += "\n\n<skill_definition>\n" + json.dumps(
            _tool_get_report_skill(ctx, skill["name"]), ensure_ascii=False, default=str) + \
            "\n</skill_definition>"

    history = store.recent_messages(chat_key, config.CHAT_MEMORY_TURNS) if remember else []
    att_notes = []
    if attachments:
        from . import uploads
        blocks, att_notes = uploads.prompt_blocks(user, attachments)
        say({"type": "step", "id": "att", "name": "read_attachment", "status": "done", "ms": 0,
             "label": f"Reading {len(att_notes)} attached file(s)"})
        content = [{"type": "text", "text": prompt + "\n\n(The user attached the file(s) below. Answer from them; "
                    "use attachment_totals for exact totals, and the ERP tools only if they ask to compare.)"}] + blocks
        msgs = history + [{"role": "user", "content": content}]
    else:
        msgs = history + [{"role": "user", "content": prompt}]
    system = _system_prompt(ctx)

    final_text = ""
    api_s, tools_s, cache_read, fresh_in, steps_log, t_all = 0.0, 0.0, 0, 0, [], time.time()
    model = config.CLAUDE_VOICE_MODEL if spoken and config.CLAUDE_VOICE_MODEL else config.CLAUDE_MODEL
    say({"type": "step", "id": "plan", "label": "Understanding your request", "status": "running"})
    t_plan = time.time()
    try:
        for step_no in range(config.MAX_AGENT_STEPS):
            t_call = time.time()
            _cache_tail(msgs)
            if emit and hasattr(client.messages, "stream"):      # stream words to the screen as they are written
                with client.messages.stream(model=model, max_tokens=4096, system=system, tools=TOOLS,
                                            messages=msgs) as st:
                    for ev in st:
                        if ev.type == "content_block_delta" and getattr(ev.delta, "type", "") == "text_delta":
                            say({"type": "text", "delta": ev.delta.text})
                    resp = st.get_final_message()
            else:
                resp = client.messages.create(model=model, max_tokens=4096, system=system, tools=TOOLS, messages=msgs)
            if step_no == 0:
                say({"type": "step", "id": "plan", "status": "done", "ms": int((time.time() - t_plan) * 1000)})
            api_s += time.time() - t_call
            u = getattr(resp, "usage", None)
            if u is not None:
                cache_read += getattr(u, "cache_read_input_tokens", 0) or 0
                fresh_in += getattr(u, "input_tokens", 0) or 0
            msgs.append({"role": "assistant", "content": resp.content})
            texts = [b.text for b in resp.content if b.type == "text"]
            calls = [b for b in resp.content if b.type == "tool_use"]
            steps_log.append("+".join(b.name for b in calls) or "answer")
            if resp.stop_reason != "tool_use":
                final_text = "\n".join(texts).strip()
                break
            if texts and "\n".join(texts).strip() and all(b.name in FINISH_TOOLS for b in calls):
                for b in calls:                 # answer + cards + follow-ups in one response: no extra round trip
                    try:
                        DISPATCH[b.name](ctx, **(b.input or {}))
                    except Exception:
                        traceback.print_exc()
                final_text = "\n".join(texts).strip()
                break
            if texts:
                say({"type": "text_reset", "note": "\n".join(texts)[:300]})
            results = []
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                sid, t1, nk = b.id, time.time(), len(ctx.reply.kpis)
                say({"type": "step", "id": sid, "name": b.name, "status": "running",
                     "label": STEP_LABELS.get(b.name, b.name.replace("_", " ").capitalize())})
                try:
                    out = DISPATCH[b.name](ctx, **(b.input or {}))
                except Exception as e:
                    traceback.print_exc()
                    out = {"error": f"{type(e).__name__}: {e}"}
                tools_s += time.time() - t1
                say({"type": "step", "id": sid, "name": b.name, "ms": int((time.time() - t1) * 1000),
                     "status": "error" if isinstance(out, dict) and out.get("error") else "done",
                     "detail": _step_detail(b.name, b.input or {}, out)})
                src = (ctx.active_skill or {}).get("title") or "Live query"
                for k in ctx.reply.kpis[nk:]:                      # "Latest analysis": figures as they are read
                    say({"type": "figure", "label": k.get("label"), "value": k.get("value"), "format": k.get("format"),
                         "unit": k.get("unit"), "previous": k.get("previous"), "previous_label": k.get("previous_label"),
                         "better": k.get("better"), "group": k.get("group"), "source": src})
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": json.dumps(out, ensure_ascii=False, default=str)[:60000],
                                **({"is_error": True} if isinstance(out, dict) and "error" in out else {})})
            msgs.append({"role": "user", "content": results})
        else:
            final_text = "I had to stop because this took too many steps. Please narrow the request."
    except anthropic.APIError as e:
        final_text = f"⚠️ AI service error: {getattr(e, 'message', str(e))[:300]}"
    log.info("timing agent %.1fs: %d AI calls %.1fs, tools %.1fs, cached %d / new %d tokens | %s",
             time.time() - t_all, len(steps_log), api_s, tools_s, cache_read, fresh_in, " > ".join(steps_log))

    ctx.reply.text = final_text or ("✅ Done." if ctx.reply.files or ctx.reply.tables else "…")
    if ctx.reply.denied and not (ctx.reply.files or ctx.reply.preview or ctx.reply.kpis):
        ctx.reply.text = denied_message(text)            # one fixed polite line: no role, views or reasons, ever
    for note in dict.fromkeys(getattr(ctx.reply, "text_notes", [])):
        ctx.reply.text += f"\n\nℹ️ {note}"
    if remember:
        store.add_message(chat_key, "user", text + (f"\n[attached: {'; '.join(att_notes)}]" if att_notes else ""))
        memo = ctx.reply.text
        if ctx.reply.report_ids:
            memo += f"\n[Created report id(s) {ctx.reply.report_ids}: " + \
                    ", ".join(sorted({f['format'] for f in ctx.reply.files} |
                                     ({"table"} if ctx.reply.tables else set()))) + "]"
        store.add_message(chat_key, "assistant", memo)
    return ctx.reply
