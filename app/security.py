"""Access-denied audit: every time someone asks for data or an action outside their rights, VERONICA
  1. saves it in the database (rb_security_events) - admins see it under Menu -> Security log,
  2. writes one line to logs/security.log (separate from the server log),
  3. alerts the admins on Telegram / e-mail (at most once per user + kind every SECURITY_ALERT_MINUTES).
The user still only gets the polite "not in your access" answer - the alert is silent for them."""
from __future__ import annotations

import logging
import threading
import time
from logging.handlers import RotatingFileHandler

from . import config, store

log = logging.getLogger("veronica.security")
_setup = False
_last: dict = {}
_lock = threading.Lock()

KIND_TEXT = {
    "report_blocked": "asked for a report outside their access",
    "dashboard_blocked": "opened a dashboard outside their access",
    "table_blocked": "tried to read a view outside their access",
    "free_sql_blocked": "tried a free data question while limited to their division / plants",
    "data_outside_access": "asked for data outside their access",
    "send_blocked": "tried to send a report to someone not allowed to see it",
    "teach_blocked": "tried to teach / change a report without the right",
    "schedule_blocked": "tried to create a schedule without the right",
    "admin_blocked": "tried an admin-only action",
    "login_locked": "was locked out after repeated wrong passwords",
    "rbac_change": "changed access rights",
    "link_not_yours": "opened a dashboard / report link made for someone else",
    "link_without_login": "opened a dashboard / report link without signing in",
}


def _file_log():
    global _setup
    if _setup:
        return
    _setup = True
    try:
        d = config.BASE_DIR / "logs"
        d.mkdir(exist_ok=True)
        h = RotatingFileHandler(d / "security.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    except Exception:
        pass


def denied(user: dict | None, kind: str, detail: str, channel: str = "", request_text: str = "", ip: str = "",
           notify: bool = True) -> None:
    """Record an access denial. Never raises - security logging must not break the answer."""
    _file_log()
    u = user or {}
    try:
        store.add_security_event(u, kind, detail, channel, request_text, ip)
    except Exception:
        log.exception("could not save security event")
    log.warning("DENIED %s | user #%s %s (%s) | %s | %s | asked: %s", kind, u.get("id"), u.get("name") or u.get("username"),
                u.get("role"), channel, detail[:300], (request_text or "")[:300].replace("\n", " "))
    if not notify or not config.SECURITY_ALERTS:
        return
    try:
        if u.get("role") and store.get_role(u["role"]).get("is_admin"):
            return                                       # admins are not alerted about themselves
    except Exception:
        pass
    key = (u.get("id") or u.get("username") or ip, kind)
    with _lock:
        if time.time() - _last.get(key, 0) < 60 * config.SECURITY_ALERT_MINUTES:
            return
        _last[key] = time.time()
    threading.Thread(target=_alert, args=(u, kind, detail, channel, request_text), daemon=True).start()


def _alert(u: dict, kind: str, detail: str, channel: str, request_text: str) -> None:
    who = f"{u.get('name') or u.get('username') or 'Unknown'} (role {u.get('role') or '-'})"
    text = (f"🛡️ VERONICA security alert\n{who} {KIND_TEXT.get(kind, kind)}.\n"
            f"Detail: {detail[:300]}\n" + (f"Asked: \"{request_text[:300]}\"\n" if request_text else "")
            + f"Channel: {channel or '-'} · Nothing was shown to them.")
    try:                          # who gets the alert is set per person in the Admin Console (e.g. director on/off)
        admins = [a for a in store.list_users() if a.get("active", True) and store.gets_security_alerts(a)]
    except Exception:
        return
    if config.SECURITY_ALERT_USERS:
        admins = [a for a in admins if a["id"] in config.SECURITY_ALERT_USERS]
    for a in admins:
        try:
            if "telegram" in config.SECURITY_ALERTS and config.TELEGRAM_ENABLED and a.get("telegram_id"):
                from . import telegram
                telegram.send_text(a["telegram_id"], text)
            if "email" in config.SECURITY_ALERTS and a.get("email"):
                from . import outbox
                outbox.send_email([a["email"]], f"Security alert: {who}", text, [])
        except Exception:
            log.exception("security alert to %s failed", a.get("name"))
