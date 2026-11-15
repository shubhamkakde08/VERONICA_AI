"""Report file links that expire: /files/<folder>/<name>?e=<unix expiry>&s=<signature>.
Without a valid, unexpired signature the file is not served - a forwarded or leaked link stops working."""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

from . import config


def _sig(folder: str, name: str, exp: int) -> str:
    from .dash import _secret
    d = hmac.new(_secret(), f"file|{folder}|{name}|{exp}".encode(), hashlib.sha256).digest()[:18]
    return base64.urlsafe_b64encode(d).decode().rstrip("=")


def url(folder: str, name: str) -> str:
    exp = int(time.time()) + 86400 * config.FILE_LINK_DAYS
    return f"{config.PUBLIC_BASE_URL}/files/{folder}/{name}?e={exp}&s={_sig(folder, name, exp)}"


def ok(folder: str, name: str, e: str, s: str) -> bool:
    try:
        exp = int(e)
    except (TypeError, ValueError):
        return False
    return exp >= time.time() and hmac.compare_digest(s or "", _sig(folder, name, exp))
