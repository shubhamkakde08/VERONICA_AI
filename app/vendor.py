"""Everything a page needs is served by VERONICA herself - no CDN, no Google Fonts, works without internet.
localize(html) swaps the known internet links for /vendor/... files kept in app/static/vendor."""
from __future__ import annotations

import re

from . import config

_SCRIPTS = [  # (pattern of the internet URL, local file)
    (r"https://cdn\.tailwindcss\.com[^\"']*", None),                       # replaced by a compiled stylesheet
    (r"https://(?:cdnjs\.cloudflare\.com/ajax/libs/Chart\.js/[\d.]+/|cdn\.jsdelivr\.net/npm/chart\.js@[\d.]+/dist/)chart\.umd(?:\.min)?\.js", "chart.umd.min.js"),
    (r"https://cdn\.jsdelivr\.net/npm/tom-select@[\d.]+/dist/js/tom-select\.complete\.min\.js", "tom-select.complete.min.js"),
    (r"https://cdn\.jsdelivr\.net/npm/tom-select@[\d.]+/dist/css/tom-select\.bootstrap5\.min\.css", "tom-select.bootstrap5.min.css"),
    (r"https://cdn\.jsdelivr\.net/npm/xlsx-js-style@[\d.]+/dist/xlsx\.bundle\.js", "xlsx-js-style.bundle.js"),
    (r"https://cdn\.jsdelivr\.net/npm/xlsx-js-style@[\d.]+/dist/xlsx\.min\.js", "xlsx-js-style.min.js"),
    (r"https://cdnjs\.cloudflare\.com/ajax/libs/exceljs/[\d.]+/exceljs\.min\.js", "exceljs.min.js"),
    (r"https://cdnjs\.cloudflare\.com/ajax/libs/html2canvas/[\d.]+/html2canvas\.min\.js", "html2canvas.min.js"),
    (r"https://cdnjs\.cloudflare\.com/ajax/libs/jspdf/[\d.]+/jspdf\.umd\.min\.js", "jspdf.umd.min.js"),
    (r"https://cdnjs\.cloudflare\.com/ajax/libs/xlsx/[\d.]+/xlsx\.full\.min\.js", "xlsx.full.min.js"),
]
_TW = re.compile(r"<script[^>]*src=[\"']https://cdn\.tailwindcss\.com[^\"']*[\"'][^>]*>\s*</script>", re.I)
_PRECONNECT = re.compile(r"<link[^>]*rel=[\"']preconnect[\"'][^>]*fonts\.(?:googleapis|gstatic)\.com[^>]*>|"
                         r"<link[^>]*fonts\.(?:googleapis|gstatic)\.com[^>]*rel=[\"']preconnect[\"'][^>]*>", re.I)
_GFONTS = re.compile(r"https://fonts\.googleapis\.com/css2?\?[^\"']*", re.I)


def localize(html: str, absolute: bool = False) -> str:
    """absolute=True for files that may be opened away from the page (e-mailed / downloaded reports)."""
    base = (config.PUBLIC_BASE_URL if absolute else "") + "/vendor/"
    html = _TW.sub(f'<link rel="stylesheet" href="{base}tailwind.css">', html)
    for pat, local in _SCRIPTS:
        if local:
            html = re.sub(pat, base + local, html)
    html = _PRECONNECT.sub("", html)
    html = _GFONTS.sub(base + "fonts/fonts.css", html)
    return html


def localize_bytes(b: bytes, absolute: bool = False) -> bytes:
    return localize(b.decode("utf-8"), absolute).encode("utf-8")


def leftovers(html: str) -> list[str]:
    """Internet links still in a page (for tests / the offline check)."""
    return sorted(set(re.findall(r"(?:src|href)=[\"'](https?://[^\"']+)", html)))
