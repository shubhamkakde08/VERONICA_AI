"""Turns query results into reports: chat table, Excel, PDF, chart image, HTML.

PDF is made from the same HTML (WeasyPrint), so Hindi / Gujarati / Marathi
text renders correctly when Noto fonts are installed (the Dockerfile does this).
"""
from __future__ import annotations

import base64
import html as html_lib
import io
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config, filelinks

ALL_FORMATS = ("table", "excel", "pdf", "chart", "html")
TEMPLATES = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                        autoescape=select_autoescape(["html"]))


@dataclass
class ReportSpec:
    title: str
    columns: list[str]
    rows: list[list]
    subtitle: str = ""
    summary: str = ""                    # short narrative in the user's language
    notes: str = ""
    column_formats: dict = field(default_factory=dict)  # col -> number|currency|percent|date|text
    total_columns: list[str] = field(default_factory=list)
    chart: dict | None = None            # {"type":"bar|line|pie|barh","x":"col","y":["col"],"title":""}
    skill_name: str = ""

    def now_str(self) -> str:
        return datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%d-%b-%Y %I:%M %p")


# ---------------------------------------------------------------- number formatting
def indian_group(n: float, decimals: int = 2) -> str:
    """12345678.5 -> 1,23,45,678.50 (lakh / crore grouping)."""
    neg = n < 0
    s = f"{abs(n):.{decimals}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if neg else "") + whole + (("." + frac) if frac else "")


def fmt_value(v, kind: str | None) -> str:
    if v is None:
        return ""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if kind == "currency":
            return "₹" + indian_group(v, 2)
        if kind == "percent":
            return f"{v:.2f}%"
        if kind == "number" or isinstance(v, float):
            return indian_group(v, 0 if float(v).is_integer() else 2)
        return str(v)
    return str(v)


def totals_row(spec: ReportSpec) -> list | None:
    if not spec.total_columns:
        return None
    out = []
    for i, c in enumerate(spec.columns):
        if c in spec.total_columns:
            out.append(sum(r[i] for r in spec.rows if isinstance(r[i], (int, float))))
        else:
            out.append("TOTAL" if i == 0 else "")
    return out


# ---------------------------------------------------------------- chat table
def chat_table(spec: ReportSpec, max_rows: int = 25, max_width: int = 18) -> str:
    """Monospace table for Telegram (<pre>) or plain text."""
    head = [str(c)[:max_width] for c in spec.columns]
    body = [[fmt_value(v, spec.column_formats.get(c))[:max_width]
             for c, v in zip(spec.columns, r)] for r in spec.rows[:max_rows]]
    tot = totals_row(spec)
    if tot:
        body.append([fmt_value(v, spec.column_formats.get(c))[:max_width]
                     for c, v in zip(spec.columns, tot)])
    widths = [max(len(x) for x in col) for col in zip(head, *body)] if body else [len(h) for h in head]
    line = lambda cells: " | ".join(c.ljust(w) for c, w in zip(cells, widths))
    out = [line(head), "-+-".join("-" * w for w in widths)]
    out += [line(r) for r in body[:-1]] if tot else [line(r) for r in body]
    if tot:
        out.append("-+-".join("-" * w for w in widths))
        out.append(line(body[-1]))
    if len(spec.rows) > max_rows:
        out.append(f"... {len(spec.rows) - max_rows} more rows (see Excel/PDF)")
    return "\n".join(out)


# ---------------------------------------------------------------- chart
def chart_png(spec: ReportSpec) -> bytes | None:
    ch = spec.chart
    if not ch or not spec.rows:
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.family"] = ["Noto Sans", "Noto Sans Devanagari", "Noto Sans Gujarati",
                                   "Nirmala UI", "Segoe UI", "DejaVu Sans"]
    idx = {c: i for i, c in enumerate(spec.columns)}
    x_col = ch.get("x") or spec.columns[0]
    y_cols = [y for y in (ch.get("y") or []) if y in idx] or \
             [c for c in spec.columns[1:] if isinstance(spec.rows[0][idx[c]], (int, float))][:3]
    if x_col not in idx or not y_cols:
        return None
    rows = spec.rows[:40]
    xs = [str(r[idx[x_col]]) for r in rows]
    palette = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4"]

    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=130)
    kind = ch.get("type", "bar")
    if kind == "pie":
        vals = [r[idx[y_cols[0]]] or 0 for r in rows]
        ax.pie(vals, labels=xs, autopct="%1.1f%%", colors=palette * 8, startangle=90,
               wedgeprops={"linewidth": 1, "edgecolor": "white"})
        ax.axis("equal")
    else:
        n = len(y_cols)
        for k, y in enumerate(y_cols):
            vals = [r[idx[y]] or 0 for r in rows]
            if kind == "line":
                ax.plot(xs, vals, marker="o", linewidth=2, color=palette[k % 6], label=y)
            elif kind == "barh":
                pos = [i + (k - (n - 1) / 2) * 0.8 / n for i in range(len(xs))]
                ax.barh(pos, vals, height=0.8 / n, color=palette[k % 6], label=y)
                ax.set_yticks(range(len(xs)), xs)
            else:
                pos = [i + (k - (n - 1) / 2) * 0.8 / n for i in range(len(xs))]
                bar_colors = (ch.get("colors") or [])[:len(vals)] if n == 1 else []
                ax.bar(pos, vals, width=0.8 / n, label=y,
                       color=bar_colors if len(bar_colors) == len(vals) else palette[k % 6])
                ax.set_xticks(range(len(xs)), xs, rotation=35 if len(xs) > 6 else 0, ha="right"
                              if len(xs) > 6 else "center")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="x" if kind == "barh" else "y", alpha=0.25)
        axis = ax.xaxis if kind == "barh" else ax.yaxis
        all_vals = [abs(r[idx[y]] or 0) for y in y_cols for r in rows if isinstance(r[idx[y]], (int, float))]
        dec = 0 if (max(all_vals, default=0) >= 100) else 2   # small values (e.g. Scrap %) keep decimals
        axis.set_major_formatter(matplotlib.ticker.FuncFormatter(
            lambda v, _: indian_group(v, dec)))
        if n > 1:
            ax.legend(frameon=False)
    # matplotlib cannot shape Indic scripts (conjuncts break), so only draw Latin titles;
    # the PDF/HTML header already shows the full title in the user's language.
    title = next((t for t in (ch.get("title"), spec.title) if t and t.isascii()), "")
    if title:
        ax.set_title(title, fontsize=13, fontweight="bold", loc="left")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------- excel
def excel_bytes(spec: ReportSpec, chart: bytes | None = None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = (spec.skill_name or "Report")[:31]
    ncol = max(len(spec.columns), 1)
    ws.cell(1, 1, spec.title).font = Font(bold=True, size=14, color="1F3A8A")
    ws.cell(2, 1, f"{config.COMPANY_NAME} · {spec.subtitle or ''} · Generated {spec.now_str()}"
            ).font = Font(italic=True, size=9, color="64748B")
    hdr_row = 4
    fill = PatternFill("solid", fgColor="1F3A8A")
    thin = Side(style="thin", color="CBD5E1")
    for j, c in enumerate(spec.columns, 1):
        cell = ws.cell(hdr_row, j, c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    numfmt = {"currency": '[$₹-4009] #,##,##0.00', "number": '#,##,##0.##',
              "percent": '0.0"%"', "date": "dd-mmm-yyyy"}
    for i, r in enumerate(spec.rows, hdr_row + 1):
        for j, (c, v) in enumerate(zip(spec.columns, r), 1):
            cell = ws.cell(i, j, v)
            cell.border = Border(bottom=thin)
            f = spec.column_formats.get(c)
            if f in numfmt and isinstance(v, (int, float)):
                cell.number_format = numfmt[f]
        if (i - hdr_row) % 2 == 0:
            for j in range(1, ncol + 1):
                ws.cell(i, j).fill = PatternFill("solid", fgColor="F1F5F9")
    last = hdr_row + len(spec.rows)
    if spec.total_columns and spec.rows:
        tr = last + 1
        ws.cell(tr, 1, "TOTAL").font = Font(bold=True)
        for j, c in enumerate(spec.columns, 1):
            if c in spec.total_columns:
                L = get_column_letter(j)
                cell = ws.cell(tr, j, f"=SUM({L}{hdr_row + 1}:{L}{last})")
                cell.font = Font(bold=True)
                cell.number_format = numfmt.get(spec.column_formats.get(c), "#,##,##0.##")
            ws.cell(tr, j).border = Border(top=Side(style="medium", color="1F3A8A"))
    for j, c in enumerate(spec.columns, 1):
        width = max([len(str(c))] + [len(str(r[j - 1])) for r in spec.rows[:200]]) + 3
        ws.column_dimensions[get_column_letter(j)].width = min(max(width, 10), 45)
    ws.freeze_panes = ws.cell(hdr_row + 1, 1)
    if spec.rows:
        ws.auto_filter.ref = f"A{hdr_row}:{get_column_letter(ncol)}{last}"
    if spec.summary or spec.notes:
        ns = wb.create_sheet("Summary")
        ns.column_dimensions["A"].width = 110
        for k, para in enumerate([spec.title, "", spec.summary, "", spec.notes], 1):
            ns.cell(k, 1, para).alignment = Alignment(wrap_text=True, vertical="top")
        ns.cell(1, 1).font = Font(bold=True, size=13)
    if chart:
        cs = wb.create_sheet("Chart")
        img = XLImage(io.BytesIO(chart))
        img.width, img.height = 900, 468
        cs.add_image(img, "B2")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- html / pdf
def html_doc(spec: ReportSpec, chart: bytes | None = None, for_pdf: bool = False) -> str:
    tot = totals_row(spec)
    numeric = {c for i, c in enumerate(spec.columns)
               if spec.rows and all(isinstance(r[i], (int, float)) or r[i] is None
                                    for r in spec.rows[:50])}
    return TEMPLATES.get_template("report.html").render(
        spec=spec, company=config.COMPANY_NAME, generated=spec.now_str(),
        fmt=lambda v, c: fmt_value(v, spec.column_formats.get(c)),
        totals=tot, numeric=numeric, for_pdf=for_pdf,
        chart_b64=base64.b64encode(chart).decode() if chart else None,
        summary_html=html_lib.escape(spec.summary).replace("\n", "<br>"),
        notes_html=html_lib.escape(spec.notes).replace("\n", "<br>"),
    )


_PDF_OK: bool | None = None


def pdf_available() -> bool:
    """WeasyPrint needs the GTK/Pango libraries. On Windows without them, skip PDF instead of crashing."""
    global _PDF_OK
    if _PDF_OK is None:
        try:
            import weasyprint  # noqa: F401
            _PDF_OK = True
        except (OSError, ImportError) as e:
            import logging
            logging.getLogger("veronica").warning("PDF disabled (WeasyPrint/GTK not available): %s", e)
            _PDF_OK = False
    return _PDF_OK


def pdf_bytes(spec: ReportSpec, chart: bytes | None = None) -> bytes:
    from weasyprint import HTML
    return HTML(string=html_doc(spec, chart, for_pdf=True)).write_pdf()


# ---------------------------------------------------------------- orchestrator
def render(spec: ReportSpec, formats: list[str]) -> dict:
    """Returns {"table_text": str|None, "files": [{"format","path","url","filename"}]}"""
    formats = [f for f in formats if f in ALL_FORMATS] or ["table"]
    folder_id = uuid.uuid4().hex
    folder = config.OUTPUT_DIR / folder_id
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y%m%d_%H%M")
    base = f"{(spec.skill_name or 'report')}_{stamp}"
    chart = chart_png(spec) if ("chart" in formats or spec.chart) else None

    files = []

    def put(fmt: str, ext: str, data: bytes):
        p = folder / f"{base}.{ext}"
        p.write_bytes(data)
        files.append({"format": fmt, "path": str(p), "filename": p.name,
                      "url": filelinks.url(folder_id, p.name)})

    if "excel" in formats:
        put("excel", "xlsx", excel_bytes(spec, chart))
    if "pdf" in formats and pdf_available():
        put("pdf", "pdf", pdf_bytes(spec, chart))
    if "html" in formats:
        put("html", "html", html_doc(spec, chart).encode("utf-8"))
    if "chart" in formats and chart:
        put("chart", "png", chart)
    return {"table_text": chat_table(spec) if "table" in formats else None, "files": files,
            "pdf_skipped": "pdf" in formats and not pdf_available()}
