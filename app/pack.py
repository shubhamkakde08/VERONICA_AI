"""Report pack: a Power BI-style multi-section report in one go.

  KPI cards  +  several sections (each: optional chart + optional grouped table)
  -> chat text (KPI block + compact tables), chart PNGs, ONE PDF, ONE Excel, ONE HTML.

Grouped tables: rows are grouped by `group_by` columns (e.g. Plant > Item Group) with
header rows and subtotals, like a Power BI matrix. Ratio columns (e.g. Scrap %) are
re-computed for subtotals from hidden helper columns instead of being summed.
"""
from __future__ import annotations

import base64
import html as html_lib
import io
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, filelinks
from .renderers import ReportSpec, chart_png, fmt_value, indian_group, pdf_available

FORMATS = ("table", "chart", "pdf", "excel", "html")


# ---------------------------------------------------------------- data shaping
def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _ratio(rows_vals: list[dict], spec: list) -> float | None:
    num, den, mult = spec[0], spec[1], (spec[2] if len(spec) > 2 else 1)
    n = sum(r.get(num) or 0 for r in rows_vals if _num(r.get(num)))
    d = sum(r.get(den) or 0 for r in rows_vals if _num(r.get(den)))
    return round(n / d * mult, 2) if d else None


class Section:
    def __init__(self, res: dict, sec: dict):
        self.title = sec.get("title", "")
        self.note = sec.get("note", "")
        labels = sec.get("column_labels") or {}
        self.columns = [labels.get(c, c) for c in res["columns"]]
        self.rows = [dict(zip(self.columns, r)) for r in res["rows"]]
        L = lambda xs: [labels.get(x, x) for x in (xs or [])]
        self.group_by = [g for g in L(sec.get("group_by")) if g in self.columns]
        self.hidden = set(L(sec.get("hidden_columns")))
        self.sum_cols = [c for c in L(sec.get("total_columns")) if c in self.columns]
        self.ratio = {labels.get(k, k): [labels.get(x, x) if isinstance(x, str) else x for x in v]
                      for k, v in (sec.get("ratio_columns") or {}).items()}
        self.formats = {labels.get(k, k): v for k, v in (sec.get("column_formats") or {}).items()}
        self.show_table = sec.get("show_table", True)
        self.only_in = set(sec.get("only_in") or [])        # e.g. {"table","excel"}; empty = everywhere
        self.subtotals = sec.get("subtotals", True)
        self.grand_total = sec.get("grand_total", bool(self.sum_cols or self.ratio))
        self.truncated = res.get("truncated", False)
        self.chart = None
        if sec.get("chart") and self.rows:
            ch = dict(sec["chart"])
            ch["x"] = labels.get(ch.get("x"), ch.get("x"))
            ch["y"] = L(ch.get("y"))
            spec = ReportSpec(title=self.title, columns=self.columns,
                              rows=[[r.get(c) for c in self.columns] for r in self.rows], chart=ch)
            self.chart = chart_png(spec)

    @property
    def shown(self) -> list[str]:
        return [c for c in self.columns if c not in self.group_by and c not in self.hidden]

    def total_cells(self, rows: list[dict], label: str) -> dict:
        out = {c: "" for c in self.shown}
        out[self.shown[0]] = label
        for c in self.sum_cols:
            if c in out:
                out[c] = round(sum(r.get(c) or 0 for r in rows if _num(r.get(c))), 2)
        for c, spec in self.ratio.items():
            if c in out:
                out[c] = _ratio(rows, spec)
        return out

    def display_rows(self) -> list[tuple[str, int, dict]]:
        """[(kind, level, cells)] kind = group | data | subtotal | total"""
        out: list[tuple[str, int, dict]] = []
        g = self.group_by

        def walk(rows, level):
            if level == len(g):
                for r in rows:
                    out.append(("data", level, {c: r.get(c) for c in self.shown}))
                return
            col, order, buckets = g[level], [], {}
            for r in rows:
                k = r.get(col)
                if k not in buckets:
                    order.append(k)
                    buckets[k] = []
                buckets[k].append(r)
            for k in order:
                out.append(("group", level, {"label": "" if k is None else str(k)}))
                walk(buckets[k], level + 1)
                child_keys = {r.get(g[level + 1]) for r in buckets[k]} if level + 1 < len(g) else None
                single_child = child_keys is not None and len(child_keys) == 1   # would repeat child total
                if self.subtotals and (self.sum_cols or self.ratio) and len(buckets[k]) > 1 and not single_child:
                    out.append(("subtotal", level, self.total_cells(buckets[k], f"Total {k}")))

        walk(self.rows, 0)
        if self.grand_total and self.rows:
            out.append(("total", 0, self.total_cells(self.rows, "TOTAL")))
        return out

    def fmt(self, c, v):
        kind = self.formats.get(c)
        if kind is None and isinstance(v, float):
            return indian_group(v, 2)          # quantities always with 2 decimals (MT)
        return fmt_value(v, kind)


# ---------------------------------------------------------------- chat
def kpi_delta(k: dict) -> tuple[str, str]:
    """('▲ 12.5% vs Sep', 'good'|'bad'|'') - change against previous, coloured by 'better'."""
    prev, val = k.get("previous"), k.get("value")
    if not isinstance(prev, (int, float)) or not isinstance(val, (int, float)):
        return "", k.get("status", "")
    diff = val - prev
    if k.get("format") == "percent":
        txt = f"{'▲' if diff > 0 else '▼' if diff < 0 else '■'} {abs(diff):.2f} pts"
    else:
        txt = f"{'▲' if diff > 0 else '▼' if diff < 0 else '■'} {abs(diff) / abs(prev) * 100:.1f}%" if prev else "new"
    txt += f" {k.get('previous_label') or 'vs previous'}"
    better = k.get("better")
    status = k.get("status") or ("" if not better or diff == 0 else
                                 "good" if (diff > 0) == (better == "up") else "bad")
    return txt, status


def _kpi_block(kpis: list[dict]) -> str:
    w = max((len(k["label"]) for k in kpis), default=10)
    f = lambda k: (indian_group(k["value"], 2) if k.get("format") is None and isinstance(k["value"], float)
                   else fmt_value(k["value"], k.get("format")))
    lines, grp = [], None
    multi = len({k.get("group") for k in kpis if k.get("group")}) > 1
    for k in kpis:
        if multi and k.get("group") and k["group"] != grp:
            grp = k["group"]
            lines.append(("\n" if lines else "") + f"▸ {grp}")
        d, st = kpi_delta(k)
        mark = {"good": "🟢", "bad": "🔴", "warn": "🟡"}.get(st, "  ")
        unit = f" {k['unit']}" if k.get("unit") else ""
        lines.append(f"{mark} {k['label'].ljust(w)}  {f(k)}{unit}" + (f"  {d}" if d else ""))
    return "\n".join(lines)


def chat_section(sec: Section, max_rows: int = 40, label_max: int = 26, text_max: int = 16) -> str:
    """Monospace table. Column widths follow the content; numbers are NEVER cut."""
    cols = sec.shown
    rows = []          # (kind, level, [cells as text])
    n = 0
    for kind, lvl, cells in sec.display_rows():
        if kind == "group":
            rows.append((kind, lvl, [cells["label"]]))
            continue
        if kind == "data":
            n += 1
            if n > max_rows:
                continue
        vals = [cells.get(c, "") for c in cols]
        first = ("  " * lvl + str(vals[0])) if kind == "data" else str(vals[0])
        rows.append((kind, lvl, [first] + [sec.fmt(c, v) for c, v in zip(cols[1:], vals[1:])]))
    numeric = [i > 0 and any(_num(r.get(c)) for r in sec.rows) for i, c in enumerate(cols)]
    widths = []
    for i, c in enumerate(cols):
        content = max((len(r[2][i]) for r in rows if r[0] != "group" and len(r[2]) > i), default=0)
        if numeric[i]:
            widths.append(max(content, min(len(c), 12)))
        else:
            widths.append(min(max(content, len(c), 4), label_max if i == 0 else text_max))

    def cut(t, w):
        return t if len(t) <= w else t[: w - 1] + "…"

    def line(cells):
        out = []
        for i, (x, w) in enumerate(zip(cells, widths)):
            out.append(x.rjust(w) if numeric[i] else cut(x, w).ljust(w))
        return " ".join(out).rstrip()

    rule = "-" * (sum(widths) + len(widths) - 1)
    out = [line([cut(c, w) for c, w in zip(cols, widths)]), rule]
    for kind, lvl, cells in rows:
        if kind == "group":
            out.append(("  " * lvl) + "▸ " + cells[0])
            continue
        if kind == "total":
            out.append(rule)
        out.append(line(cells))
    if n > max_rows:
        out.append(f"... {n - max_rows} more rows in PDF/Excel")
    return "\n".join(out)


# ---------------------------------------------------------------- html / pdf
def _html(pack: dict, sections: list[Section], for_pdf: bool) -> str:
    e = html_lib.escape
    tz_now = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%d-%b-%Y %I:%M %p")
    filt = "".join(f"<span><b>{e(k)}:</b> {e(str(v))}</span>" for k, v in (pack.get("filters") or {}).items())
    def _card(k):
        d, st = kpi_delta(k)
        unit = f' <small>{e(k["unit"])}</small>' if k.get("unit") else ""
        return (f'<div class="kpi {st}"><div class="l">{e(k["label"])}</div><div class="v">{e(fmt_value(k["value"], k.get("format")))}{unit}</div>'
                + (f'<div class="d {st}">{e(d)}</div>' if d else "") + (f'<div class="n">{e(k["note"])}</div>' if k.get("note") else "") + "</div>")
    kpis = "".join(_card(k) for k in pack.get("kpis") or [])
    body = []
    for s in sections:
        half = bool(s.chart) and not s.group_by and len(s.rows) <= 15
        parts = [f'<section class="{"half" if half else "full"}"><h2>{e(s.title)}</h2>']
        if s.chart:
            parts.append(f'<img class="chart" alt="" src="data:image/png;base64,{base64.b64encode(s.chart).decode()}">')
        if s.show_table and s.rows:
            cols = s.shown
            numeric = {c for c in cols[1:] if any(_num(r.get(c)) for r in s.rows)}
            t = ['<table><thead><tr>' + "".join(f'<th class="{"n" if c in numeric else ""}">{e(c)}</th>' for c in cols)
                 + '</tr></thead><tbody>']
            for kind, lvl, cells in s.display_rows():
                if kind == "group":
                    t.append(f'<tr class="g g{lvl}"><td colspan="{len(cols)}" style="padding-left:{8 + lvl * 16}px">'
                             f'{e(cells["label"])}</td></tr>')
                    continue
                pad = 8 + lvl * 16 if kind == "data" else 8 + max(lvl, 0) * 16
                tds = []
                for i, c in enumerate(cols):
                    v = cells.get(c, "")
                    txt = e(s.fmt(c, v)) if i else e(str(v))
                    style = f' style="padding-left:{pad}px"' if i == 0 else ""
                    tds.append(f'<td class="{"n" if c in numeric else ""}"{style}>{txt}</td>')
                t.append(f'<tr class="{kind}">' + "".join(tds) + "</tr>")
            t.append("</tbody></table>")
            parts.append('<div class="tw">' + "".join(t) + "</div>")
        if s.note:
            parts.append(f'<p class="note">{e(s.note)}</p>')
        if s.truncated:
            parts.append(f'<p class="note">Limited to the first {config.MAX_ROWS} rows.</p>')
        parts.append("</section>")
        body.append("".join(parts))
    summary = e(pack.get("summary", "")).replace("\n", "<br>")
    fonts = "" if for_pdf else '<link href="/vendor/fonts/fonts.css" rel="stylesheet">'   # served by VERONICA, no Google
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(pack['title'])}</title>{fonts}
<style>
:root{{--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--brand:#1f3a8a;--bg:#fff;--card:#f1f5f9;--g0:#dbe4f7;--g1:#eef2fb}}
{"" if for_pdf else "@media (prefers-color-scheme:dark){:root{--ink:#e2e8f0;--muted:#94a3b8;--line:#334155;--brand:#93c5fd;--bg:#0b1120;--card:#111827;--g0:#1e2a4a;--g1:#151d33}}"}
@page{{size:A4 landscape;margin:10mm;@bottom-right{{content:"Page " counter(page) " of " counter(pages);font-size:8pt;color:#64748b}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:"Noto Sans","Noto Sans Devanagari","Noto Sans Gujarati","Nirmala UI","Segoe UI",system-ui,sans-serif;font-size:{'8.5pt' if for_pdf else '14px'}}}
.wrap{{max-width:1200px;margin:0 auto;padding:{'0' if for_pdf else '20px 16px 40px'}}}
header{{border-bottom:3px solid var(--brand);padding-bottom:8px;margin-bottom:12px}}
.co{{color:var(--muted);font-size:.8em;letter-spacing:.08em;text-transform:uppercase}}h1{{margin:2px 0;color:var(--brand);font-size:1.6em}}
.filters{{display:flex;flex-wrap:wrap;gap:4px 16px;color:var(--muted);font-size:.85em}}.filters b{{color:var(--ink)}}
.kpis{{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}}.kpi{{flex:1 1 140px}}
.kpi{{background:var(--card);border-radius:8px;padding:10px 12px;border-left:4px solid var(--brand)}}
.kpi .v{{font-size:1.6em;font-weight:700;font-variant-numeric:tabular-nums}}.kpi .v small{{font-size:.5em;color:var(--muted)}}.kpi .l{{color:var(--muted);font-size:.8em;text-transform:uppercase;letter-spacing:.05em}}
.kpi .d{{font-size:.82em;font-weight:600;margin-top:2px}}.kpi .d.good{{color:#059669}}.kpi .d.bad{{color:#dc2626}}.kpi .n{{font-size:.78em;color:var(--muted)}}
.kpi.good{{border-left-color:#10b981}}.kpi.bad{{border-left-color:#ef4444}}.kpi.warn{{border-left-color:#f59e0b}}
.summary{{background:var(--card);border-radius:8px;padding:10px 14px;margin:8px 0 14px;line-height:1.5}}
.secs{{display:block}}section{{margin:10px 0 14px;display:block}}section.half{{display:inline-block;vertical-align:top;width:48.5%;margin-right:1.5%;break-inside:avoid}}@media (max-width:700px){{section.half{{width:100%}}}}h2{{font-size:1.15em;margin:0 0 8px;color:var(--brand)}}
.chart{{max-width:100%;height:auto;display:block;margin:4px 0 8px}}
.tw{{overflow-x:auto}}table{{border-collapse:collapse;width:100%}}
th{{background:var(--brand);color:#fff;text-align:left;padding:6px 8px;font-weight:600}}th.n,td.n{{text-align:right;font-variant-numeric:tabular-nums}}
td{{padding:4px 8px;border-bottom:1px solid var(--line)}}tr.g td{{font-weight:700}}tr.g0 td{{background:var(--g0)}}tr.g1 td{{background:var(--g1)}}
tr.subtotal td{{font-weight:600;font-style:italic}}tr.total td{{font-weight:700;border-top:2px solid var(--brand)}}
thead{{display:table-header-group}}tr{{page-break-inside:avoid}}.note{{color:var(--muted);font-size:.85em}}
</style></head><body><div class="wrap">
<header><div class="co">{e(config.COMPANY_NAME)}</div><h1>{e(pack['title'])}</h1>
<div class="filters">{filt}<span><b>Generated:</b> {tz_now}</span></div></header>
<div class="kpis">{kpis}</div>
{f'<div class="summary">{summary}</div>' if summary else ''}
<div class="secs">{''.join(body)}</div>
</div></body></html>"""


# ---------------------------------------------------------------- excel
def _excel(pack: dict, sections: list[Section]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    numfmt = {"currency": '[$₹-4009] #,##,##0.00', "number": '#,##,##0.00', "percent": '0.00"%"'}
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = pack["title"]
    ws["A1"].font = Font(bold=True, size=14, color="1F3A8A")
    r = 3
    for k, v in (pack.get("filters") or {}).items():
        ws.cell(r, 1, k).font = Font(bold=True)
        ws.cell(r, 2, str(v))
        r += 1
    r += 1
    for k in pack.get("kpis") or []:
        ws.cell(r, 1, k["label"]).font = Font(bold=True)
        c = ws.cell(r, 2, k["value"])
        c.number_format = numfmt.get(k.get("format"), "#,##,##0.00")
        r += 1
    if pack.get("summary"):
        r += 1
        ws.cell(r, 1, pack["summary"]).alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=r, start_column=1, end_row=r + 5, end_column=6)
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 18
    hdr = PatternFill("solid", fgColor="1F3A8A")
    fills = [PatternFill("solid", fgColor="DBE4F7"), PatternFill("solid", fgColor="EEF2FB")]
    used = {"Summary"}
    for s in sections:
        name = "".join(ch for ch in s.title if ch not in '[]:*?/\\')[:31] or "Section"
        base, i = name, 2
        while name in used:
            name = f"{base[:28]}_{i}"
            i += 1
        used.add(name)
        sh = wb.create_sheet(name)
        sh["A1"] = s.title
        sh["A1"].font = Font(bold=True, size=12, color="1F3A8A")
        cols = s.shown
        for j, c in enumerate(cols, 1):
            cell = sh.cell(3, j, c)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = hdr
        row = 4
        for kind, lvl, cells in s.display_rows() if s.rows else []:
            if kind == "group":
                cell = sh.cell(row, 1, ("   " * lvl) + cells["label"])
                for j in range(1, len(cols) + 1):
                    sh.cell(row, j).fill = fills[min(lvl, 1)]
                cell.font = Font(bold=True)
            else:
                for j, c in enumerate(cols, 1):
                    v = cells.get(c, "")
                    if j == 1 and kind == "data":
                        v = ("   " * lvl) + str(v)
                    cell = sh.cell(row, j, v)
                    if _num(v):
                        cell.number_format = numfmt.get(s.formats.get(c), "#,##,##0.00")
                    if kind in ("subtotal", "total"):
                        cell.font = Font(bold=True, italic=kind == "subtotal")
            row += 1
        sh.column_dimensions["A"].width = 36
        for j in range(2, len(cols) + 1):
            sh.column_dimensions[get_column_letter(j)].width = 15
        sh.freeze_panes = "B4"
        if s.chart:
            img = XLImage(io.BytesIO(s.chart))
            img.width, img.height = 720, 374
            sh.add_image(img, f"{get_column_letter(len(cols) + 2)}3")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- orchestrator
def render_pack(pack: dict, results: dict, formats: list[str]) -> dict:
    formats = [f for f in formats if f in FORMATS] or ["table", "chart"]
    sections, missing = [], []
    for sec in pack.get("sections") or []:
        res = results.get(sec.get("result_id"))
        if res is None:
            missing.append(sec.get("result_id"))
            continue
        sections.append(Section(res, sec))
    folder_id = uuid.uuid4().hex
    folder = config.OUTPUT_DIR / folder_id
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y%m%d_%H%M")
    base = f"{(pack.get('skill_name') or 'report')}_{stamp}"
    files = []

    def put(fmt, name, data):
        p = folder / name
        p.write_bytes(data)
        files.append({"format": fmt, "path": str(p), "filename": p.name,
                      "url": filelinks.url(folder_id, p.name)})

    def for_fmt(fmt):
        return [s for s in sections if not s.only_in or fmt in s.only_in]

    if "chart" in formats:
        for i, s in enumerate(sections, 1):
            if s.chart:
                put("chart", f"{base}_chart{i}.png", s.chart)
    if "pdf" in formats and pdf_available():
        from weasyprint import HTML
        put("pdf", f"{base}.pdf", HTML(string=_html(pack, for_fmt("pdf"), True)).write_pdf())
    if "excel" in formats:
        put("excel", f"{base}.xlsx", _excel(pack, for_fmt("excel")))
    if "html" in formats:
        put("html", f"{base}.html", _html(pack, for_fmt("html"), False).encode("utf-8"))

    chat = None
    if "table" in formats:
        parts = []
        if pack.get("kpis"):
            parts.append(f"{pack['title']}\n\n{_kpi_block(pack['kpis'])}")
        for s in for_fmt("table"):
            if s.show_table and s.rows:
                parts.append(f"{s.title}\n\n{chat_section(s)}")
        chat = parts
    previews = [{"title": s.title, "columns": s.shown,
                 "rows": [[(("  " * lvl + c["label"]) if k == "group" else
                            (("  " * lvl + str(c.get(s.shown[0], ""))) if k == "data" else c.get(s.shown[0], "")))]
                          + ([None] * (len(s.shown) - 1) if k == "group" else [c.get(x) for x in s.shown[1:]])
                          for k, lvl, c in s.display_rows()][:300]}
                for s in for_fmt("table") if s.show_table and s.rows]
    return {"chat_tables": chat, "files": files, "previews": previews, "missing": missing,
            "row_counts": {s.title: len(s.rows) for s in sections},
            "pdf_skipped": "pdf" in formats and not pdf_available()}
