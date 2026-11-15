"""WhatsApp as a chat channel (Meta Cloud API webhook): users talk to VERONICA on WhatsApp like on Telegram.

GET  /whatsapp/webhook  - Meta's one-time verification (hub.verify_token must equal WHATSAPP_VERIFY_TOKEN)
POST /whatsapp/webhook  - incoming messages (text or voice notes) -> same agent -> reply + report files
Users are recognised by the mobile saved with `tools.manage set-contact <id> <mobile>`.
Every incoming message also opens WhatsApp's 24-hour window, so "send it on WhatsApp" works right after.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re

import httpx

from .net import TLS

from . import config, outbox, store

log = logging.getLogger("veronica.whatsapp")
GRAPH = "https://graph.facebook.com/v20.0"


def verify_signature(body: bytes, header: str) -> bool:
    if not config.WHATSAPP_APP_SECRET:     # no app secret = cannot prove it is Meta: refuse (anyone could fake a sender)
        return False
    want = "sha256=" + hmac.new(config.WHATSAPP_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header or "")


def send_text(to: str, text: str) -> None:
    for i in range(0, len(text), 3900):
        outbox._wa("messages", json={"messaging_product": "whatsapp", "to": to, "type": "text",
                                     "text": {"body": text[i:i + 3900], "preview_url": True}})


def _wa_markup(t: str) -> str:
    t = re.sub(r"\*\*(.+?)\*\*", r"*\1*", t)          # markdown bold -> WhatsApp bold
    return re.sub(r"`([^`\n]+)`", r"```\1```", t)


def _media(media_id: str) -> tuple[bytes, str]:
    h = {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}
    meta = httpx.get(f"{GRAPH}/{media_id}", headers=h, timeout=30, verify=TLS).json()
    r = httpx.get(meta["url"], headers=h, timeout=60, verify=TLS)
    return r.content, meta.get("mime_type", "audio/ogg")


def _send_reply(to: str, reply) -> None:
    parts = [_wa_markup(reply.text or "")]
    for tbl in reply.tables[:3]:
        parts.append("```" + tbl[:3000] + "```")
    send_text(to, "\n\n".join(p for p in parts if p.strip()) or "✅ Done.")
    paths = [f["path"] for f in reply.files if f.get("path")]
    if paths:
        try:
            outbox.send_whatsapp(to, paths, "")
        except Exception as e:
            send_text(to, f"⚠️ Files could not be sent here: {e}")


def process(payload: dict) -> None:
    from . import agent, voice
    try:   # keep the last event's shape (no message text) to debug sender fields
        import json as _json
        from . import config as _cfg
        def _shape(o):
            if isinstance(o, dict):
                return {k: ("…" if k in ("body", "text", "caption") and not isinstance(v, dict) else _shape(v)) for k, v in o.items()}
            if isinstance(o, list):
                return [_shape(x) for x in o[:3]]
            return o
        (_cfg.BASE_DIR / "logs" / "whatsapp_last_event.json").write_text(_json.dumps(_shape(payload), indent=1), encoding="utf-8")
    except Exception:
        pass
    for entry in payload.get("entry", []):
        for ch in entry.get("changes", []):
            val = ch.get("value") or {}
            contacts = val.get("contacts") or [{}]
            for msg in val.get("messages", []) or []:
                frm = (msg.get("from") or contacts[0].get("wa_id") or "")
                if not frm:                       # Meta's "Test" button sends sample data without a sender
                    log.info("whatsapp test event received (no sender) - webhook works")
                    continue
                try:
                    user = store.get_user_by_phone(frm)
                    if not user:
                        send_text(frm, f"🙏 You are not registered with VERONICA yet.\nSend this number to your admin: {frm}\n"
                                       f"(Admin: tools.manage set-contact <id> {frm})")
                        continue
                    kind = msg.get("type")
                    if kind == "text":
                        text = (msg.get("text") or {}).get("body", "").strip()
                        if not text:
                            continue
                        reply = agent.handle_message(user, text, channel="whatsapp", chat_key=f"wa:{frm}")
                        _send_reply(frm, reply)
                    elif kind in ("audio", "voice"):
                        data, mime = _media((msg.get(kind) or {}).get("id"))
                        heard = voice.transcribe(data, mime)
                        if not heard:
                            send_text(frm, "🎙️ I could not hear any words. Please try again.")
                            continue
                        send_text(frm, f"🎙️ _{heard}_")
                        reply = agent.handle_message(user, heard, channel="whatsapp", chat_key=f"wa:{frm}", spoken=True)
                        _send_reply(frm, reply)
                    else:
                        send_text(frm, "Please send text or a voice note.")
                except Exception as e:
                    log.exception("whatsapp message failed")
                    try:
                        send_text(frm, f"⚠️ Sorry, something went wrong: {str(e)[:150]}")
                    except Exception:
                        pass
