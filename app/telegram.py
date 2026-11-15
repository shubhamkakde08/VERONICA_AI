"""Telegram Bot API: receive updates (webhook) and deliver replies, tables and files."""
from __future__ import annotations

import html
import io
import logging
from pathlib import Path

import httpx

from .net import TLS

from . import config, store

log = logging.getLogger("veronica.telegram")
API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
_http = httpx.Client(timeout=60, verify=TLS)
_bot_username: str | None = None

HELP = """🤖 <b>VERONICA AI</b> — ask in English, हिंदी, ગુજરાતી or मराठी.

<b>Examples</b>
• aaj ki total sales kitni hai?
• ગઈકાલનું dispatch report excel માં આપો
• /daily_sales Surat branch pdf
• roj subah 9 baje /daily_sales group me bhejo

<b>Commands</b>
/dashboard – live dashboards (tap to open)
/skills – reports I know
/teach – teach me a new report
/history – your recent reports
/schedules – scheduled reports
/new – start a fresh conversation
/myid – your Telegram id"""


# ------------------------------------------------------------------ sending
def _call(method: str, **kw) -> dict:
    r = _http.post(f"{API}/{method}", **kw)
    data = r.json()
    if not data.get("ok"):
        log.error("telegram %s failed: %s", method, data)
    return data


def send_text(chat_id, text: str, parse_mode: str | None = None) -> None:
    for i in range(0, max(len(text), 1), 3900):
        payload = {"chat_id": chat_id, "text": text[i:i + 3900] or "…",
                   "disable_web_page_preview": True}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        res = _call("sendMessage", json=payload)
        if parse_mode and not res.get("ok"):  # fall back to plain text on markup errors
            _call("sendMessage", json={"chat_id": chat_id, "text": text[i:i + 3900]})


def send_buttons(chat_id, text: str, rows: list[list[tuple[str, str]]]) -> None:
    """Message with tap-to-open link buttons: rows = [[(label, url), ...], ...]"""
    kb = {"inline_keyboard": [[{"text": t, "url": u} for t, u in r] for r in rows]}
    res = _call("sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                     "disable_web_page_preview": True, "reply_markup": kb})
    if not res.get("ok"):   # e.g. PUBLIC_BASE_URL is not https -> Telegram refuses buttons; send plain links
        send_text(chat_id, text + "\n\n" + "\n".join(f"{t}: {u}" for r in rows for t, u in r))


def send_dashboards(chat_id, user: dict) -> None:
    from . import dash
    rows, lines = [], []
    for name, (skill, _, title, _sub) in dash.DASHBOARDS.items():
        sk = store.get_skill(skill)
        if sk and store.skill_allowed(sk, user):
            this_m, prev_m = dash.months_back(2)
            rows.append([(f"📊 {title} · this month", dash.link(user, name)),
                         ("last month", dash.link(user, name, month=prev_m))])
    if not rows:
        send_text(chat_id, "No dashboards are available for your role yet. Please contact your admin.")
        return
    rows.append([("🗂 All dashboards & months", dash.link(user))])
    send_buttons(chat_id, f"<b>📈 Live dashboards</b>\nTap to open – fresh data from the ERP every time.\n"
                          f"<i>Links are personal and valid {config.DASH_LINK_HOURS} h.</i>", rows)


def send_typing(chat_id, action: str = "typing") -> None:
    try:
        _call("sendChatAction", json={"chat_id": chat_id, "action": action})
    except Exception:
        pass


def send_voice(chat_id, text: str, lang: str | None = None) -> None:
    """Spoken reply as a Telegram voice note (Gemini TTS, OGG/Opus)."""
    from . import voice
    if not voice.enabled() or not text:
        return
    try:
        audio = voice.speak(text, lang, "audio/ogg_opus")
        _call("sendVoice", data={"chat_id": chat_id}, files={"voice": ("veronica.ogg", io.BytesIO(audio), "audio/ogg")})
    except Exception as e:
        log.warning("voice reply failed: %s", e)


def send_file(chat_id, path: str, caption: str = "", as_photo: bool = False) -> None:
    p = Path(path)
    with p.open("rb") as fh:
        if as_photo:
            _call("sendPhoto", data={"chat_id": chat_id, "caption": caption[:1000]},
                  files={"photo": (p.name, fh)})
        else:
            _call("sendDocument", data={"chat_id": chat_id, "caption": caption[:1000]},
                  files={"document": (p.name, fh)})


def _md_to_tg_html(text: str) -> str:
    """Very small markdown -> Telegram HTML (bold, code)."""
    import re
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)
    t = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", t, flags=re.M)
    return t


def send_reply(chat_id, reply, header: str = "") -> None:
    if header:
        send_text(chat_id, f"<b>{html.escape(header)}</b>", "HTML")
    for tbl in reply.tables:
        title, _, body = tbl.partition("\n\n")
        # wide tables are unreadable on phones -> send as .txt file instead
        if max((len(l) for l in body.splitlines()), default=0) > 60 or len(body) > 3500:
            buf = io.BytesIO(tbl.encode("utf-8"))
            _call("sendDocument", data={"chat_id": chat_id, "caption": title[:1000]},
                  files={"document": ("table.txt", buf)})
        else:
            send_text(chat_id, f"<b>{html.escape(title)}</b>\n<pre>{html.escape(body)}</pre>", "HTML")
    for f in reply.files:
        send_typing(chat_id, "upload_document")
        send_file(chat_id, f["path"], caption=f["filename"], as_photo=(f["format"] == "chart"))
    if reply.text:
        send_text(chat_id, _md_to_tg_html(reply.text), "HTML")


# ------------------------------------------------------------------ attachments
def _download(file_id: str) -> tuple[str, bytes]:
    info = _call("getFile", json={"file_id": file_id})["result"]
    r = _http.get(f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}/{info['file_path']}")
    return info["file_path"], r.content


def attachment_text(filename: str, data: bytes, max_chars: int = 12000) -> str:
    """Turns an example report (xlsx / csv / txt / pdf) into text the agent can read."""
    name = filename.lower()
    try:
        if name.endswith((".xlsx", ".xlsm")):
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            parts = []
            for ws in wb.worksheets[:3]:
                parts.append(f"--- sheet: {ws.title}")
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= 40:
                        parts.append("...")
                        break
                    parts.append(" | ".join("" if v is None else str(v) for v in row))
            return "\n".join(parts)[:max_chars]
        if name.endswith(".pdf"):
            try:
                from pypdf import PdfReader
                return "\n".join((p.extract_text() or "") for p in
                                 PdfReader(io.BytesIO(data)).pages[:5])[:max_chars]
            except ImportError:
                return "(PDF received; install pypdf to read PDF examples)"
        return data.decode("utf-8", errors="replace")[:max_chars]
    except Exception as e:
        return f"(could not read {filename}: {e})"


# ------------------------------------------------------------------ incoming
def _bot_name() -> str:
    global _bot_username
    if _bot_username is None:
        _bot_username = (_call("getMe", json={}).get("result") or {}).get("username", "")
    return _bot_username


def _builtin_command(cmd: str, args: str, user: dict, chat_id) -> bool:
    """Handles commands that don't need the AI. Returns True if handled."""
    role = store.get_role(user["role"])
    if cmd in ("start", "help"):
        send_text(chat_id, f"Namaste {html.escape(user['name'])} 🙏\n\n" + HELP, "HTML")
        return True
    if cmd == "myid":
        send_text(chat_id, f"Your Telegram id: <code>{user['telegram_id']}</code>\n"
                           f"This chat id: <code>{chat_id}</code>", "HTML")
        return True
    if cmd == "new":
        store.clear_chat(f"tg:{chat_id}")
        send_text(chat_id, "🧹 New conversation started.")
        return True
    if cmd in ("dashboard", "dashboards", "dash"):
        send_dashboards(chat_id, user)
        return True
    if cmd == "skills":
        sk = store.list_skills(user)
        txt = "\n".join(f"/{s['name']} – {html.escape(s['title'])}" for s in sk) or \
            "No reports taught yet. Use /teach to create the first one."
        send_text(chat_id, "<b>📋 Reports</b>\n" + txt, "HTML")
        return True
    if cmd == "history":
        rows = store.search_reports(user, limit=10)
        txt = "\n".join(f"#{r['id']} · {config.local_dt(r['created_at']):%d-%m %H:%M} · {html.escape(r['title'])}"
                        for r in rows) or "No reports yet."
        send_text(chat_id, "<b>🗂 Recent reports</b>\n" + txt +
                  "\n\nAsk e.g. “report #12 ko pdf me bhejo” or “compare with #12”.", "HTML")
        return True
    if cmd == "schedules":
        from . import scheduler
        rows = store.list_schedules(user)
        txt = "\n".join(f"#{s['id']} · /{s['skill_name']} · <code>{s['cron']}</code> · next "
                        f"{scheduler.next_run(s['id']) or '-'}" for s in rows) or "No schedules."
        send_text(chat_id, "<b>⏰ Schedules</b>\n" + txt, "HTML")
        return True
    if cmd == "adduser":
        if not role.get("is_admin"):
            send_text(chat_id, "Only admins can add users.")
            return True
        parts = args.split(maxsplit=2)
        if len(parts) < 3:
            send_text(chat_id, "Usage: /adduser <telegram_id> <admin|manager|viewer> <Name>")
            return True
        try:
            nu = store.add_user(parts[2], parts[1], telegram_id=parts[0])
            web = (f"Web login: set a username/password with\n<code>python -m tools.manage set-login "
                   f"{nu['id']} &lt;username&gt; &lt;password&gt;</code>" if config.WEB_REQUIRE_PASSWORD
                   else f"Web link: {config.PUBLIC_BASE_URL}/?token={nu['web_token']}")
            send_text(chat_id, f"✅ Added {html.escape(nu['name'])} as {nu['role']} (id {nu['id']}).\n{web}", "HTML")
        except Exception as e:
            send_text(chat_id, f"Could not add user: {e}")
        return True
    return False


def process_update(update: dict) -> None:
    from . import agent  # late import
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    chat_type = msg["chat"].get("type", "private")
    tg_user = msg.get("from") or {}
    text = (msg.get("text") or msg.get("caption") or "").strip()

    user = store.get_user_by_telegram(tg_user.get("id"))
    if not user:
        if chat_type == "private":
            send_text(chat_id, f"🙏 You are not registered yet.\nSend this id to your admin: "
                               f"<code>{tg_user.get('id')}</code>\n"
                               f"(Admin: /adduser {tg_user.get('id')} viewer {html.escape(tg_user.get('first_name', 'Name'))})",
                      "HTML")
        return

    # In groups only react to commands, mentions or replies to the bot
    if chat_type != "private":
        bot = _bot_name()
        replied_to_bot = (msg.get("reply_to_message") or {}).get("from", {}).get("username") == bot
        if not (text.startswith("/") or (bot and f"@{bot}" in text) or replied_to_bot):
            return
        if bot:
            text = text.replace(f"@{bot}", "").strip()

    if text.startswith("/"):
        cmd, _, args = text[1:].partition(" ")
        cmd = cmd.split("@")[0].lower()
        if _builtin_command(cmd, args.strip(), user, chat_id):
            return

    # Voice notes -> text (Gemini), and VERONICA answers with her voice too
    spoken = msg.get("voice") or msg.get("audio")
    if spoken:
        from . import voice
        if not voice.enabled():
            send_text(chat_id, "🎙️ Voice messages are not switched on yet. Please type your question.")
            return
        send_typing(chat_id, "typing")
        try:
            _, data = _download(spoken["file_id"])
            heard = voice.transcribe(data, spoken.get("mime_type") or "audio/ogg")
        except Exception as e:
            send_text(chat_id, f"🎙️ Sorry, I could not hear that clearly ({str(e)[:80]}). Please try again or type.")
            return
        if not heard:
            send_text(chat_id, "🎙️ I could not hear any words. Please try again.")
            return
        send_text(chat_id, f"🎙️ <i>{html.escape(heard)}</i>", "HTML")
        reply = agent.handle_message(user, heard, channel="telegram", chat_key=f"tg:{chat_id}",
                                     default_chat_id=str(chat_id), spoken=True)
        send_reply(chat_id, reply)
        send_voice(chat_id, reply.text, voice.detect_lang(heard))
        return

    # Example report files for teaching (xlsx / csv / txt / pdf)
    doc = msg.get("document")
    if doc:
        _, data = _download(doc["file_id"])
        extracted = attachment_text(doc.get("file_name", "file"), data)
        text = (text or "Here is an example report.") + \
            f"\n\n<attached_file name=\"{doc.get('file_name')}\">\n{extracted}\n</attached_file>"
    if not text:
        send_text(chat_id, "Please send text (or an example report file).")
        return

    send_typing(chat_id)
    reply = agent.handle_message(user, text, channel="telegram", chat_key=f"tg:{chat_id}",
                                 default_chat_id=str(chat_id))
    send_reply(chat_id, reply)


def set_webhook() -> dict:
    return _call("setWebhook", json={
        "url": f"{config.PUBLIC_BASE_URL}/telegram/webhook",
        "secret_token": config.TELEGRAM_WEBHOOK_SECRET or None,
        "allowed_updates": ["message", "edited_message"],
    })


def delete_webhook() -> dict:
    """Telegram switched off: stop Telegram from delivering messages here (pending ones are dropped)."""
    return _call("deleteWebhook", json={"drop_pending_updates": True})


def set_commands() -> None:
    cmds = [("dashboard", "Live dashboards"), ("skills", "Reports I know"), ("teach", "Teach me a new report"),
            ("history", "Your recent reports"), ("schedules", "Scheduled reports"),
            ("new", "Fresh conversation"), ("help", "Help")]
    import re as _re
    cmds += [(s["name"], s["title"][:60]) for s in store.list_skills()
             if len(s["name"]) <= 32 and _re.fullmatch(r"[a-z0-9_]+", s["name"])][:90]   # Telegram: max 32 chars
    _call("setMyCommands", json={"commands": [{"command": c, "description": d} for c, d in cmds]})
