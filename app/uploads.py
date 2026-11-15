"""Files people attach in the chat window: Excel / CSV / PDF / images / text.

Each upload is kept per user (output/uploads/<user id>/<file id>/), read once into a small summary
(sheets, columns, first rows, numeric totals) and handed to the agent:
  tables -> CSV text of the first rows + totals; the read_attachment / attachment_totals tools reach the rest
  PDF    -> the PDF itself (Claude reads it) ; images -> the image itself ; text -> the text
"""
from __future__ import annotations

import base64
import csv
import io
import json
import re
import uuid
from pathlib import Path

from . import config

TABLE = (".xlsx", ".xlsm", ".csv", ".tsv")
IMAGE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
TEXT = (".txt", ".md", ".json", ".sql", ".log")
OK = TABLE + tuple(IMAGE) + TEXT + (".pdf",)
ID_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_ROWS = 200_000


class UploadError(ValueError):
    pass


def _root(user: dict) -> Path:
    p = config.OUTPUT_DIR / "uploads" / str(int(user["id"]))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _clean_name(name: str) -> str:
    base = Path(name or "file").name
    return re.sub(r"[^\w.\- ()]+", "_", base)[:120] or "file"


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        t = v.strip().replace(",", "")
        if re.fullmatch(r"-?\d+(\.\d+)?", t):
            return float(t)
    return None


def _header_index(rows: list[list]) -> int:
    for i, r in enumerate(rows[:15]):
        texts = [c for c in r if isinstance(c, str) and c.strip() and _num(c) is None]
        if len(texts) >= max(2, int(len([c for c in r if c not in (None, "")]) * .6)):
            return i
    return 0


def _sheet(name: str, raw: list[list]) -> dict:
    raw = [list(r) for r in raw if any(c not in (None, "") for c in r)]
    if not raw:
        return {"name": name, "columns": [], "rows": []}
    h = _header_index(raw)
    width = max(len(r) for r in raw)
    cols, seen = [], {}
    for j, c in enumerate((raw[h] + [None] * width)[:width]):
        c = str(c).strip() if c not in (None, "") else f"Column {j + 1}"
        seen[c] = seen.get(c, 0) + 1
        cols.append(c if seen[c] == 1 else f"{c} ({seen[c]})")
    rows = [(r + [None] * width)[:width] for r in raw[h + 1:]]
    return {"name": name, "columns": cols, "rows": rows}


def read_table(path: Path) -> list[dict]:
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets[:8]:
            rows = []
            for i, r in enumerate(ws.iter_rows(values_only=True)):
                if i > MAX_ROWS:
                    break
                rows.append(list(r))
            out.append(_sheet(ws.title, rows))
        return out
    txt = path.read_bytes().decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(txt[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if ext == ".tsv" else csv.excel
    rows = [r for _, r in zip(range(MAX_ROWS), csv.reader(io.StringIO(txt), dialect))]
    return [_sheet(path.stem, rows)]


def _stats(sheet: dict) -> dict:
    out = {}
    for j, c in enumerate(sheet["columns"]):
        vals = [_num(r[j]) for r in sheet["rows"]]
        nums = [v for v in vals if v is not None]
        if nums and len(nums) >= max(1, len([1 for r in sheet["rows"] if r[j] not in (None, "")]) * .8):
            out[c] = {"sum": round(sum(nums), 4), "min": min(nums), "max": max(nums), "count": len(nums)}
    return out


def _cell(v):
    if v is None:
        return ""
    if hasattr(v, "isoformat"):
        return v.isoformat()[:19]
    return v


def save(user: dict, filename: str, data: bytes) -> dict:
    name = _clean_name(filename)
    ext = Path(name).suffix.lower()
    if ext == ".xls":
        raise UploadError("Old .xls files can't be read here - please save it as .xlsx and attach again.")
    if ext not in OK:
        raise UploadError(f"{ext or 'This file type'} is not supported. Attach Excel (.xlsx), CSV, PDF, an image or a text file.")
    if len(data) > config.UPLOAD_MAX_MB * 1024 * 1024:
        raise UploadError(f"The file is larger than {config.UPLOAD_MAX_MB} MB.")
    fid = uuid.uuid4().hex
    folder = _root(user) / fid
    folder.mkdir(parents=True)
    path = folder / name
    path.write_bytes(data)
    meta = {"id": fid, "name": name, "size": len(data), "ext": ext}
    if ext in TABLE:
        try:
            sheets = read_table(path)
        except Exception as e:
            raise UploadError(f"Could not read {name}: {e}") from e
        meta["kind"] = "table"
        meta["sheets"] = [{"name": s["name"], "rows": len(s["rows"]), "cols": len(s["columns"]), "columns": s["columns"][:60],
                           "preview": [[_cell(v) for v in r[:12]] for r in s["rows"][:8]], "totals": _stats(s)}
                          for s in sheets]
    elif ext == ".pdf":
        meta["kind"] = "pdf"
        try:
            from pypdf import PdfReader
            rd = PdfReader(io.BytesIO(data))
            meta["pages"] = len(rd.pages)
            meta["excerpt"] = " ".join((rd.pages[0].extract_text() or "").split())[:400] if rd.pages else ""
        except Exception:
            meta["pages"] = None
    elif ext in IMAGE:
        meta["kind"] = "image"
    else:
        meta["kind"] = "text"
        meta["excerpt"] = data.decode("utf-8", errors="replace")[:400]
    (folder / "meta.json").write_text(json.dumps(meta, default=str), encoding="utf-8")
    return meta


def load(user: dict, fid: str) -> tuple[dict, Path]:
    if not ID_RE.match(fid or ""):
        raise UploadError("Unknown file.")
    folder = _root(user) / fid
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    except OSError:
        raise UploadError("That file is no longer available - please attach it again.") from None
    return meta, folder / meta["name"]


def _pick_sheet(sheets: list[dict], sheet: str) -> dict:
    if not sheet:
        return max(sheets, key=lambda s: len(s["rows"]))
    for s in sheets:
        if s["name"].lower() == sheet.lower():
            return s
    raise UploadError(f"No sheet '{sheet}'. Sheets: {', '.join(s['name'] for s in sheets)}")


def rows(user: dict, fid: str, sheet: str = "", start: int = 0, limit: int = 200, columns: list | None = None) -> dict:
    meta, path = load(user, fid)
    if meta.get("kind") != "table":
        raise UploadError("Only Excel / CSV attachments have rows.")
    s = _pick_sheet(read_table(path), sheet)
    idx = [s["columns"].index(c) for c in columns or [] if c in s["columns"]] or list(range(len(s["columns"])))
    limit = max(1, min(int(limit or 200), 500))
    part = s["rows"][int(start or 0):int(start or 0) + limit]
    return {"file": meta["name"], "sheet": s["name"], "total_rows": len(s["rows"]), "start": start,
            "columns": [s["columns"][i] for i in idx], "rows": [[_cell(r[i]) for i in idx] for r in part]}


def totals(user: dict, fid: str, sum_columns: list, group_by: list | None = None, sheet: str = "",
           filters: dict | None = None) -> dict:
    """Exact group-by sums over the whole sheet (no row limit)."""
    meta, path = load(user, fid)
    if meta.get("kind") != "table":
        raise UploadError("Only Excel / CSV attachments can be totalled.")
    s = _pick_sheet(read_table(path), sheet)
    cols = s["columns"]
    missing = [c for c in list(sum_columns or []) + list(group_by or []) + list((filters or {}).keys()) if c not in cols]
    if missing:
        raise UploadError(f"Column(s) not in the file: {', '.join(missing)}. Columns: {', '.join(cols[:60])}")
    gi = [cols.index(c) for c in group_by or []]
    si = [cols.index(c) for c in sum_columns]
    fi = [(cols.index(k), str(v).strip().lower()) for k, v in (filters or {}).items()]
    acc: dict[tuple, list] = {}
    for r in s["rows"]:
        if any(str(r[i] if r[i] is not None else "").strip().lower() != v for i, v in fi):
            continue
        key = tuple(_cell(r[i]) for i in gi)
        a = acc.setdefault(key, [0.0] * len(si) + [0])
        for n, i in enumerate(si):
            a[n] += _num(r[i]) or 0.0
        a[-1] += 1
    out = sorted(acc.items(), key=lambda kv: -abs(kv[1][0]) if si else 0)
    return {"file": meta["name"], "sheet": s["name"], "columns": list(group_by or []) + list(sum_columns) + ["Rows"],
            "rows": [list(k) + [round(x, 4) for x in v[:-1]] + [v[-1]] for k, v in out[:300]],
            "groups": len(out), "grand_total": {c: round(sum(v[n] for v in acc.values()), 4) for n, c in enumerate(sum_columns)}}


def prompt_blocks(user: dict, ids: list[str]) -> tuple[list[dict], list[str]]:
    """Content blocks for Claude + short notes for chat history."""
    blocks, notes = [], []
    for fid in ids[:5]:
        try:
            meta, path = load(user, fid)
        except UploadError as e:
            blocks.append({"type": "text", "text": f"(attachment {fid}: {e})"})
            continue
        notes.append(f"{meta['name']} (file_id {fid})")
        head = f'<attached_file file_id="{fid}" name="{meta["name"]}" kind="{meta["kind"]}">'
        if meta["kind"] == "table":
            parts = [head]
            for s in read_table(path)[:4]:
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(s["columns"])
                for r in s["rows"][:120]:
                    w.writerow([_cell(v) for v in r])
                txt = buf.getvalue()[:20000]
                parts.append(f"--- sheet '{s['name']}': {len(s['rows'])} data rows x {len(s['columns'])} columns"
                             + (" (first 120 rows below; use read_attachment / attachment_totals for the rest)" if len(s["rows"]) > 120 else "")
                             + f"\n{txt}\nColumn totals: {json.dumps(_stats(s), default=str)[:3000]}")
            blocks.append({"type": "text", "text": "\n".join(parts) + "\n</attached_file>"})
        elif meta["kind"] == "pdf":
            blocks.append({"type": "text", "text": head + " (the PDF follows) </attached_file>"})
            blocks.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                          "data": base64.b64encode(path.read_bytes()).decode()}})
        elif meta["kind"] == "image":
            blocks.append({"type": "text", "text": head + " (the image follows) </attached_file>"})
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": IMAGE[meta["ext"]],
                                                       "data": base64.b64encode(path.read_bytes()).decode()}})
        else:
            blocks.append({"type": "text", "text": head + "\n" + path.read_text(encoding="utf-8", errors="replace")[:30000]
                           + "\n</attached_file>"})
    return blocks, notes
