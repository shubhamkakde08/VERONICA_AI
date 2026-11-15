"""Send report files out: Telegram, e-mail (SMTP) and WhatsApp (Meta Cloud API).

Used by the agent tool send_files - always after the user confirmed (by voice or text) and only to people whose role
may see the report. Every send is logged.
"""
from __future__ import annotations

import logging
import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path

import httpx

from .net import TLS

from . import config

log = logging.getLogger("veronica.outbox")


class SendError(Exception):
    pass


def channel_ready(channel: str) -> str | None:
    """None if the channel is configured, else a short reason for the user / admin."""
    if channel == "telegram":
        return None if config.TELEGRAM_BOT_TOKEN else "Telegram bot token is not set in .env"
    if channel == "email":
        return None if config.SMTP_HOST and config.SMTP_FROM else "e-mail is not set up (SMTP_HOST / SMTP_USER / SMTP_PASSWORD in .env)"
    if channel == "whatsapp":
        return None if config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_ID else "WhatsApp is not set up (WHATSAPP_TOKEN / WHATSAPP_PHONE_ID in .env)"
    return f"unknown channel {channel}"


def send_telegram(chat_id: str, paths: list[str], caption: str) -> None:
    from . import telegram
    if caption:
        telegram.send_text(chat_id, caption)
    for p in paths:
        telegram.send_file(chat_id, p, caption=Path(p).name)


def send_email(to: list[str], subject: str, body: str, paths: list[str]) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config.SMTP_FROM, ", ".join(to), subject
    msg.set_content(body)
    for p in paths:
        ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
        main, sub = ctype.split("/", 1)
        msg.add_attachment(Path(p).read_bytes(), maintype=main, subtype=sub, filename=Path(p).name)
    try:
        if config.SMTP_SSL:
            with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=60, local_hostname="veronica.local") as s:
                if config.SMTP_USER:
                    s.login(config.SMTP_USER, config.SMTP_PASSWORD)
                s.send_message(msg)
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=60, local_hostname="veronica.local") as s:
                s.starttls()
                if config.SMTP_USER:
                    s.login(config.SMTP_USER, config.SMTP_PASSWORD)
                s.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise SendError(f"e-mail failed: {e}") from e


def _wa(path: str, **kw):
    r = httpx.post(f"https://graph.facebook.com/v20.0/{config.WHATSAPP_PHONE_ID}/{path}",
                   headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}, timeout=120, verify=TLS, **kw)
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 400:
        err = (j.get("error") or {})
        code = err.get("code")
        if code in (131047, 131026):
            raise SendError("WhatsApp only delivers to people who messaged the business number in the last 24 h - ask them to "
                            "send 'hi' to the VERONICA WhatsApp number first (or set WHATSAPP_TEMPLATE).")
        raise SendError(f"WhatsApp error {code}: {err.get('message', r.text[:200])}")
    return j


def send_whatsapp(phone: str, paths: list[str], caption: str) -> None:
    to = "".join(ch for ch in phone if ch.isdigit())
    if len(to) == 10:
        to = "91" + to                                  # Indian number without country code
    if config.WHATSAPP_TEMPLATE:
        try:
            _wa("messages", json={"messaging_product": "whatsapp", "to": to, "type": "template",
                                  "template": {"name": config.WHATSAPP_TEMPLATE, "language": {"code": "en"}}})
        except SendError as e:
            log.warning("template open failed: %s", e)
    if caption:
        _wa("messages", json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": caption[:4000]}})
    for p in paths:
        ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
        with open(p, "rb") as fh:
            media = _wa("media", data={"messaging_product": "whatsapp", "type": ctype}, files={"file": (Path(p).name, fh, ctype)})
        _wa("messages", json={"messaging_product": "whatsapp", "to": to, "type": "document",
                              "document": {"id": media["id"], "filename": Path(p).name}})
