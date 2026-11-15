"""Master files the admin drops in knowledge/masters (Excel .xlsx or .csv) - item master, customer list, plant codes...

VERONICA reads them directly (no ERP query): the prompt lists each file with its columns, and lookup_master searches
the rows. Files in knowledge/masters/private are for admins only. Re-read automatically when a file changes.
"""
from __future__ import annotations

import csv
import io
import logging
from pathlib import Path

from . import config

log = logging.getLogger("veronica.masters")
_CACHE: dict = {}          # path -> (mtime, header, rows)
MAX_ROWS = 200_000


def folder() -> Path:
    return config.BASE_DIR / "knowledge" / "masters"


def _files(is_admin: bool) -> list[Path]:
    base = folder()
    if not base.is_dir():
        return []
    out = [f for f in sorted(base.iterdir()) if f.is_file() and f.suffix.lower() in (".csv", ".xlsx", ".xlsm")
           and not f.name.startswith(("~$", "."))]
    priv = base / "private"
    if is_admin and priv.is_dir():
        out += [f for f in sorted(priv.iterdir()) if f.is_file() and f.suffix.lower() in (".csv", ".xlsx", ".xlsm")
                and not f.name.startswith(("~$", "."))]
    return out


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _load(f: Path) -> tuple[list[str], list[list[str]]]:
    m = f.stat().st_mtime
    hit = _CACHE.get(str(f))
    if hit and hit[0] == m:
        return hit[1], hit[2]
    rows: list[list[str]] = []
    if f.suffix.lower() == ".csv":
        raw = f.read_bytes()
        txt = None
        for enc in ("utf-8-sig", "cp1252"):
            try:
                txt = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if txt is None:                       # odd bytes: latin-1 never fails, so the file still opens
            txt = raw.decode("latin-1")
        rows = [[_cell(c) for c in r] for r in csv.reader(io.StringIO(txt))]
    else:
        from openpyxl import load_workbook
        wb = load_workbook(f, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        for r in ws.iter_rows(values_only=True):
            rows.append([_cell(c) for c in r])
            if len(rows) > MAX_ROWS:
                break
        wb.close()
    rows = [r for r in rows if any(r)]
    header = rows[0] if rows else []
    body = rows[1:]
    _CACHE[str(f)] = (m, header, body)
    log.info("master %s loaded: %d rows", f.name, len(body))
    return header, body


def catalogue(is_admin: bool) -> str:
    """One line per master file for the system prompt: name, rows, columns."""
    lines = []
    for f in _files(is_admin):
        try:
            h, b = _load(f)
            lines.append(f"- {f.stem}: {len(b)} rows; columns: {', '.join(c for c in h if c)[:600]}")
        except Exception as e:
            lines.append(f"- {f.stem}: could not be read ({type(e).__name__})")
    return "\n".join(lines)


def lookup(name: str, search: str = "", column: str = "", limit: int = 50, is_admin: bool = False) -> dict:
    files = {f.stem.lower(): f for f in _files(is_admin)}
    f = files.get((name or "").lower().strip())
    if not f:
        return {"error": f"master '{name}' not found", "available": sorted(files)}
    h, b = _load(f)
    words = [w for w in (search or "").lower().split() if w]
    col_i = next((i for i, c in enumerate(h) if c.lower() == column.lower()), None) if column else None
    hits = []
    for r in b:
        hay = (r[col_i] if col_i is not None and col_i < len(r) else " | ".join(r)).lower()
        if all(w in hay for w in words):
            hits.append(dict(zip(h, r)))
    limit = max(1, min(int(limit or 50), 300))
    return {"master": f.stem, "columns": h, "total_rows": len(b), "matches": len(hits), "rows": hits[:limit],
            **({"note": f"showing first {limit} of {len(hits)} - narrow the search"} if len(hits) > limit else {})}
