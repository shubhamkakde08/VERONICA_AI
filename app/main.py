"""FastAPI app: web chat (URL chatbot), REST API for n8n, Telegram webhook, file downloads.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import hmac
import json
import html
import re
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from . import agent, config, datadb, live, scheduler, store, telegram, vendor, voice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("veronica")
for _noisy in ("httpx", "httpcore"):          # these log full URLs - the Telegram URL contains the bot token
    logging.getLogger(_noisy).setLevel(logging.WARNING)
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    store.init_db()
    scheduler.start()
    try:
        from . import local_tts
        local_tts.warm()                                   # free offline voice: load it now, not on the first answer
    except Exception as e:
        log.warning("free voice not started: %s", e)
    try:                                                   # new report skills shipped with an update: load once if missing
        for f in ("issue_dashboard.json", "sales_dispatch_dashboard.json", "director_mis.json"):
            p = Path(__file__).resolve().parent.parent / "examples" / "skills" / f
            if p.exists() and not store.get_skill(p.stem):
                store.save_skill(json.loads(p.read_text(encoding="utf-8")), changed_by="seed")
                log.info("report skill %s loaded", p.stem)
    except Exception as e:
        log.warning("skill seed failed: %s", e)
    try:
        from .engines import sales_order
        sales_order.warm()                                 # read the sales order book now -> first dashboard opens fast
    except Exception as e:
        log.warning("sales order warm-up not started: %s", e)
    try:                                                   # column list for the prompt: build now, not on the first question
        import threading
        from . import datadb
        threading.Thread(target=lambda: datadb.schema_digest(["*"]), daemon=True).start()
    except Exception as e:
        log.warning("schema warm-up not started: %s", e)
    if config.TELEGRAM_BOT_TOKEN and not config.TELEGRAM_ENABLED:
        try:                                               # Telegram switched off: no messages delivered here any more
            log.info("telegram disabled - webhook removed: %s", telegram.delete_webhook())
        except Exception as e:
            log.warning("could not remove telegram webhook: %s", e)
    elif config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_MODE == "direct" \
            and config.PUBLIC_BASE_URL.startswith("https://"):
        try:
            log.info("telegram webhook: %s", telegram.set_webhook())
            telegram.set_commands()
        except Exception as e:
            log.error("could not register telegram webhook: %s", e)
    yield


app = FastAPI(title="VERONICA AI", lifespan=lifespan)


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",                         # no framing by other sites (clickjacking)
    "Referrer-Policy": "no-referrer",                        # signed ?k= links never leak in a Referer header
    "Permissions-Policy": "camera=(self), microphone=(self), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        resp.headers.setdefault("Strict-Transport-Security", "max-age=15552000")
    if request.url.path.startswith(("/api/", "/dash", "/files/")):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


# ------------------------------------------------------------------ auth
TRUSTED_PROXIES = {"127.0.0.1", "::1"}       # cloudflared / a local reverse proxy run on this server itself


def client_ip(request: Request) -> str:
    """The caller's real IP. A proxy header is believed only when the connection itself comes from this server
    (the tunnel / reverse proxy) - on the LAN anyone could type a fake CF-Connecting-IP to dodge the login lock."""
    peer = request.client.host if request.client else ""
    if peer in TRUSTED_PROXIES:
        fwd = request.headers.get("cf-connecting-ip") or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if fwd:
            return fwd[:64]
    return peer or "?"


def current_user(authorization: str = Header(default=""), x_api_key: str = Header(default=""),
                 x_telegram_id: str = Header(default="")) -> dict:
    """Web users: 'Authorization: Bearer <session token from /api/login>'
    (or a personal web_token when WEB_REQUIRE_PASSWORD=false).
    n8n / other systems: 'X-API-Key: <SERVICE_API_KEY>' + 'X-Telegram-Id: <acting user>'."""
    if authorization.lower().startswith("bearer "):
        tok = authorization[7:].strip()
        u = store.get_user_by_session(tok)
        if not u and not config.WEB_REQUIRE_PASSWORD:
            u = store.get_user_by_token(tok)
        if u:
            u["_session"] = tok
            return u
    # service key + X-Telegram-Id = act as any linked user: only while the chat bridge is switched on
    if x_api_key and config.SERVICE_API_KEY and config.TELEGRAM_ENABLED and hmac.compare_digest(x_api_key, config.SERVICE_API_KEY):
        u = store.get_user_by_telegram(x_telegram_id) if x_telegram_id else None
        if u:
            return u
        raise HTTPException(403, "Unknown X-Telegram-Id user")
    raise HTTPException(401, "Not logged in")


def _admin_denied(user: dict, what: str):
    """Non-admin hit an admin-only API -> security log + admin alert, then 403."""
    from . import security
    security.denied(user, "admin_blocked", f"admin API {what}", "web")
    raise HTTPException(403)


def _reply_json(r: agent.AgentReply) -> dict:
    return {"text": r.text, "report_ids": r.report_ids, "tables": r.tables, "preview": r.preview,
            "kpis": r.kpis, "suggestions": getattr(r, "suggestions", []), "denied": bool(getattr(r, "denied", False)),
            "files": [{k: f[k] for k in ("format", "filename", "url")} for f in r.files]}


# ------------------------------------------------------------------ login
_fails: dict[str, list[float]] = {}  # key -> timestamps of failed attempts


def _locked(key: str) -> bool:
    now = time.time()
    window = config.LOGIN_LOCK_MINUTES * 60
    _fails[key] = [t for t in _fails.get(key, []) if now - t < window]
    return len(_fails[key]) >= config.LOGIN_MAX_FAILS


class LoginIn(BaseModel):
    username: str
    password: str


@app.get("/api/auth-mode")
def auth_mode():
    return {"password_required": config.WEB_REQUIRE_PASSWORD}


SESS_COOKIE = "rb_sess"


def _set_sess_cookie(response: Response, request: Request, token: str) -> None:
    """Browser cookie with the session, so dashboard and file links opened in this browser prove who is looking.
    HttpOnly (page scripts can't read it), SameSite=Lax, Secure on https."""
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"
    response.set_cookie(SESS_COOKIE, token, max_age=config.SESSION_HOURS * 3600, httponly=True, samesite="lax",
                        secure=https, path="/")


def link_viewer(request: Request) -> dict | None:
    """The signed-in VERONICA user of this browser (from the session cookie), or None."""
    tok = request.cookies.get(SESS_COOKIE, "")
    return store.get_user_by_session(tok) if tok else None


@app.post("/api/login")
def login(body: LoginIn, request: Request, response: Response):
    ip = client_ip(request)
    keys = [f"u:{body.username.strip().lower()}", f"ip:{ip}"]
    if any(_locked(k) for k in keys):
        raise HTTPException(429, f"Too many wrong attempts. Try again in {config.LOGIN_LOCK_MINUTES} minutes.")
    u = store.authenticate(body.username, body.password)
    if not u:
        for k in keys:
            _fails.setdefault(k, []).append(time.time())
        log.warning("failed login for %s from %s", body.username, ip)
        if any(_locked(k) for k in keys):                 # this wrong password just caused the lock-out
            from . import security
            nm = body.username.strip()[:60]
            security.denied({"username": nm, "name": nm}, "login_locked",
                            f"{config.LOGIN_MAX_FAILS} wrong passwords for login '{nm}' - locked {config.LOGIN_LOCK_MINUTES} min", "web", ip=ip)
        raise HTTPException(401, "Wrong username or password")
    for k in keys:
        _fails.pop(k, None)
    log.info("login ok: %s from %s", u["username"], ip)
    tok = store.create_session(u["id"], config.SESSION_HOURS)
    _set_sess_cookie(response, request, tok)
    return {"token": tok, "name": u["name"]}


@app.post("/api/session-cookie")
def session_cookie(request: Request, response: Response, user: dict = Depends(current_user)):
    """Browsers signed in before the cookie existed: give them the cookie for their current session."""
    if user.get("_session") and store.get_user_by_session(user["_session"]):
        _set_sess_cookie(response, request, user["_session"])
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response, user: dict = Depends(current_user)):
    if user.get("_session"):
        store.end_session(user["_session"])
    response.delete_cookie(SESS_COOKIE, path="/")
    return {"ok": True}


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


@app.post("/api/change-password")
def change_password(body: PasswordIn, user: dict = Depends(current_user)):
    try:
        store.change_password(user["id"], body.old_password, body.new_password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "note": "Password changed. Please log in again."}


# ------------------------------------------------------------------ web chat
@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(vendor.localize((STATIC / "index.html").read_text(encoding="utf-8")), headers={"Cache-Control": "no-cache"})


# ------------------------------------------------------------------ installable app (PWA): phone -> "Add to Home screen"
@app.get("/manifest.webmanifest")
def pwa_manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def pwa_sw():
    return FileResponse(STATIC / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/intro.mp3")
def intro_music(lang: str = "en"):
    """Admin sign-in intro: music + VERONICA's own (Sulafat) voice in one track - English or Hindi."""
    f = STATIC / ("intro_hi.mp3" if lang.lower().startswith("hi") else "intro_en.mp3")
    if not f.is_file():
        f = STATIC / "veronica_intro.mp3"
    return FileResponse(f, media_type="audio/mpeg", headers={"Cache-Control": "no-cache"})


@app.get("/boss-hello.mp3")
def boss_hello(i: int = -1):
    """Admin sign-in greeting in VERONICA's own voice: a pre-recorded 'Hello Boss' line (random),
    or her voice sample until those are recorded. Never calls Gemini, so it always plays."""
    import random
    lines = sorted((STATIC / "boss").glob("hello_*.mp3"))
    if lines:
        p = lines[i % len(lines)] if i >= 0 else random.choice(lines)
        return FileResponse(p, media_type="audio/mpeg", headers={"Cache-Control": "no-cache", "X-Boss-Line": p.stem})
    sample = STATIC / "veronica_voice.mp3"
    if not sample.is_file():
        raise HTTPException(404)
    return FileResponse(sample, media_type="audio/mpeg", headers={"Cache-Control": "no-cache", "X-Boss-Line": "sample"})


@app.get("/bgm.mp3")
def bgm_music():
    """Background music for the hologram themes (plays while VERONICA is idle)."""
    return FileResponse(STATIC / "veronica_bgm.mp3", media_type="audio/mpeg", headers={"Cache-Control": "max-age=86400"})


HANDS = STATIC / "hands"
HANDS_TYPES = {".js": "application/javascript", ".wasm": "application/wasm", ".data": "application/octet-stream",
               ".tflite": "application/octet-stream", ".binarypb": "application/octet-stream"}


@app.get("/hands/{name}")
def hands_file(name: str):
    """Self-hosted MediaPipe Hands (Apache-2.0) for the laptop-only gesture mode - works offline, no CDN."""
    p = HANDS / name
    if "/" in name or "\\" in name or p.suffix not in HANDS_TYPES or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type=HANDS_TYPES[p.suffix], headers={"Cache-Control": "max-age=604800"})


VENDOR = STATIC / "vendor"
VENDOR_TYPES = {".js": "application/javascript", ".css": "text/css", ".woff2": "font/woff2"}


@app.get("/vendor/{path:path}")
def vendor_file(path: str):
    """Chart / Excel / PDF libraries and fonts kept on this server - dashboards never call the internet."""
    p = (VENDOR / path).resolve()
    if VENDOR.resolve() not in p.parents or p.suffix not in VENDOR_TYPES or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type=VENDOR_TYPES[p.suffix], headers={"Cache-Control": "max-age=2592000"})


@app.get("/icon-{size}.png")
def pwa_icon(size: int):
    if size not in (192, 512):
        raise HTTPException(404)
    return FileResponse(STATIC / f"icon-{size}.png", media_type="image/png")


@app.get("/chat", response_class=HTMLResponse)
def chat_full():
    """Direct link to the full-window chat (same page, opens maximised)."""
    return HTMLResponse(vendor.localize((STATIC / "index.html").read_text(encoding="utf-8")), headers={"Cache-Control": "no-cache"})


WIDGET_JS = r"""(function(){
  if (window.__veronica) return; window.__veronica = 1;
  var base = (document.currentScript && document.currentScript.src || '').replace(/\/widget\.js.*$/, '') || '%BASE%';
  var css = '.vr-fab{position:fixed;right:22px;bottom:22px;z-index:2147483000;width:66px;height:66px;border-radius:50%;border:1.5px solid rgba(56,189,248,.9);'
    + 'background:radial-gradient(circle at 35% 30%,rgba(29,109,255,.55),#020817 72%);box-shadow:0 0 28px rgba(56,189,248,.6);cursor:pointer;padding:0}'
    + '.vr-fab:before{content:"";position:absolute;inset:-7px;border-radius:50%;border:1px solid rgba(56,189,248,.5);animation:vrp 2.4s ease-out infinite}'
    + '.vr-fab i{position:absolute;inset:14px;border-radius:50%;border:2px solid #38bdf8;box-shadow:0 0 14px #38bdf8,inset 0 0 10px #38bdf8}'
    + '.vr-fab b{position:absolute;inset:26px;border-radius:50%;background:#9bdcff;box-shadow:0 0 16px #38bdf8}'
    + '@keyframes vrp{0%{transform:scale(.9);opacity:.9}100%{transform:scale(1.45);opacity:0}}'
    + '.vr-frame{position:fixed;z-index:2147483001;right:22px;bottom:100px;width:min(440px,calc(100vw - 24px));height:min(720px,calc(100vh - 124px));'
    + 'border:1px solid rgba(56,189,248,.6);border-radius:22px;box-shadow:0 30px 80px rgba(0,0,0,.5);background:#020817;display:none}'
    + '.vr-frame.full{inset:0;width:100vw;height:100vh;border-radius:0;border:0}'
    + '@media(max-width:560px){.vr-frame{inset:0;width:100vw;height:100vh;border-radius:0}}';
  var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
  var fab = document.createElement('button'); fab.className = 'vr-fab'; fab.title = 'Chat with VERONICA'; fab.innerHTML = '<i></i><b></b>';
  var fr = document.createElement('iframe'); fr.className = 'vr-frame'; fr.allow = 'microphone; autoplay; clipboard-write'; fr.title = 'VERONICA';
  var loaded = false;
  function open(){ if (!loaded) { fr.src = base + '/?view=dock&embed=1'; loaded = true; } fr.style.display = 'block'; fab.style.display = window.innerWidth < 560 ? 'none' : ''; }
  function close(){ fr.style.display = 'none'; fr.classList.remove('full'); fab.style.display = ''; }
  fab.onclick = function(){ fr.style.display === 'block' ? close() : open(); };
  window.addEventListener('message', function(e){
    if (!e.data || !e.data.veronica || e.source !== fr.contentWindow) return;
    var m = e.data.veronica;
    if (m === 'home') close(); else if (m === 'full') { fr.classList.add('full'); fab.style.display = 'none'; } else { fr.classList.remove('full'); open(); }
  });
  document.body.appendChild(fr); document.body.appendChild(fab);
})();"""


# ------------------------------------------------------------------ live dashboards (HODs: open a link, no upload)
@app.post("/api/dash-link")
def dash_link(user: dict = Depends(current_user)):
    from . import dash
    return {"url": dash.link(user).replace(config.PUBLIC_BASE_URL, ""), "hours": config.DASH_LINK_HOURS}


def _link_guard(request: Request, owner: dict, what: str) -> HTMLResponse | None:
    """A dashboard / file link is not enough on its own: the browser must also be signed in to VERONICA
    as the person the link was made for (admins may open anyone's). Otherwise -> sign-in page."""
    if not config.LINKS_REQUIRE_LOGIN:
        return None
    viewer = link_viewer(request)
    if viewer and (viewer["id"] == owner["id"] or store.get_role(viewer["role"]).get("is_admin")):
        return None
    from . import security
    ip = client_ip(request)
    if viewer:                                     # signed in, but as someone else: a forwarded link
        security.denied(viewer, "link_not_yours", f"opened {what} made for {owner.get('name')}", "web", ip=ip)
        return HTMLResponse(_dash_login_page(request, other=True), status_code=403)
    security.denied({"name": f"(not signed in) link of {owner.get('name')}", "role": "-"}, "link_without_login",
                    f"{what} opened without signing in", "web", ip=ip, notify=False)
    return HTMLResponse(_dash_login_page(request), status_code=401)


def _dash_login_page(request: Request, other: bool = False) -> str:
    from urllib.parse import quote
    from . import dash
    nxt = quote(request.url.path + ("?" + request.url.query if request.url.query else ""), safe="")
    msg = ("This link was made for another person. Sign in with your own login and open Dashboards from VERONICA."
           if other else "Please sign in to VERONICA to open this. Links work only for the person they were made for.")
    page = dash.notice_page("🔒 Sign in required", msg)
    return page.replace('<a href="javascript:location.reload()">Try again</a>', f'<a href="/?next={nxt}">Sign in</a>')


@app.get("/dash", response_class=HTMLResponse)
def dash_index(request: Request, k: str = ""):
    from . import dash
    user = dash.check_token(k)
    if not user:
        return HTMLResponse(_dash_expired(), status_code=401)
    blocked = _link_guard(request, user, "the dashboards page")
    if blocked:
        return blocked
    return dash.index_page(user, k)


@app.get("/dash/{name}", response_class=HTMLResponse)
async def dash_open(name: str, request: Request, k: str = "", month: str = "", unit: str = "kg", div: str = "BOTH", go: str = "",
                    d_from: str = Query("", alias="from"), d_to: str = Query("", alias="to")):
    from . import dash
    user = dash.check_token(k)
    if not user:
        return HTMLResponse(_dash_expired(), status_code=401)
    blocked = _link_guard(request, user, f"dashboard '{name}'")
    if blocked:
        return blocked
    if name not in dash.DASHBOARDS:
        raise HTTPException(404)
    if month and not re.match(r"^\d{4}-\d{2}$", month):
        raise HTTPException(400, "month must be YYYY-MM")
    if not go:            # show a spinner at once, the real page follows
        return dash.loading_page(str(request.url) + "&go=1")
    try:
        page, _ = await run_in_threadpool(dash.build, user, name, month or None, unit, div, d_from or None, d_to or None)
    except dash.NotReady as e:
        return HTMLResponse(dash.notice_page("⏳ Data is on its way", str(e)), status_code=503)
    except PermissionError as e:
        return HTMLResponse(f"<p style='font:16px sans-serif;padding:30px'>🔒 {html.escape(str(e))}</p>", status_code=403)
    except ValueError as e:                     # bad period typed in the From / To boxes
        return HTMLResponse(f"<p style='font:16px sans-serif;padding:30px'>📅 {html.escape(str(e))} "
                            f"<a href='javascript:history.back()'>Go back</a></p>", status_code=400)
    except Exception as e:
        log.exception("dashboard failed")
        admin = store.get_role(user["role"]).get("is_admin")
        return HTMLResponse(dash.notice_page("This dashboard needs a moment",
                                             "The data could not be prepared just now. Please try again in a minute — "
                                             "if it keeps happening, the IT team has been notified in the log."
                                             + (f"\n\nAdmin detail: {str(e)[:300]}" if admin else "")), status_code=500)
    return HTMLResponse(page.decode("utf-8"), headers={"Cache-Control": "no-store"})


def _dash_expired() -> str:
    return ("<p style='font:16px sans-serif;padding:30px;max-width:520px'>⏳ This dashboard link has expired or is not valid. "
            "Open VERONICA and tap <b>Dashboards</b>, or send <b>/dashboard</b> to the Telegram bot for a fresh link.</p>")


@app.get("/widget.js")
def widget_js():
    """Put VERONICA on any company page:  <script src="https://your-link/widget.js" async></script>"""
    return Response(WIDGET_JS.replace("%BASE%", config.PUBLIC_BASE_URL), media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=600"})


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    role = store.get_role(user["role"])
    return {"id": user["id"], "name": user["name"], "role": user["role"], "assistant": config.ASSISTANT_NAME,
            "tagline": config.ASSISTANT_TAGLINE, "company": config.COMPANY_NAME, "voice": voice.enabled(),
            "voice_input": config.VOICE_INPUT, "live": live.enabled(), "boss": (user.get("username") or "").lower() in config.BOSS_USERNAMES,
            "power": store.is_power(user), "gesture_local_only": config.GESTURE_LOCAL_ONLY, "voice_strict": config.VOICE_STRICT, "voice_one_clip": config.VOICE_ONE_CLIP,
            "can_teach": bool(role.get("can_teach")), "is_admin": bool(role.get("is_admin")), "can_schedule": bool(role.get("can_schedule")),
            "data_synced_at": str(datadb.last_sync() or ""), "themes": store.user_themes(user),
            "channels": {"telegram": bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_ENABLED), "whatsapp": bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_ID),
                         "mail": bool(config.SMTP_HOST and config.SMTP_USER)},
            "skills": [{"name": s["name"], "title": s["title"]} for s in store.list_skills(user)]}


class ChatIn(BaseModel):
    message: str
    voice: bool = False
    attachments: list[str] = []


class TtsIn(BaseModel):
    text: str
    lang: str | None = None


@app.post("/api/tts")
async def tts(body: TtsIn, user: dict = Depends(current_user)):
    """VERONICA's voice (Gemini TTS) -> MP3."""
    t0 = time.time()
    try:
        audio = await run_in_threadpool(voice.speak, body.text[:4000], body.lang, "audio/mp3")
        log.info("timing tts %.1fs (%d chars)", time.time() - t0, len(body.text))
    except voice.VoiceError as e:
        msg = str(e)
        raise HTTPException(429 if re.search(r"rate limit|quota|429|per day", msg, re.I) else 503, msg)
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=86400",
                                                             "X-Voice": "backup" if voice.gemini_paused() else "main"})


@app.websocket("/api/live")
async def live_voice(ws: WebSocket, token: str = "", lang: str = "en-IN"):
    """Real-time voice conversation (Gemini Live). Browsers can't send headers on WebSockets,
    so the session token comes as ?token=."""
    user = store.get_user_by_session(token) or (None if config.WEB_REQUIRE_PASSWORD else store.get_user_by_token(token))
    await ws.accept()
    if not user:
        await ws.send_json({"type": "error", "message": "Please sign in again."})
        await ws.close(code=4401)
        return
    if not live.enabled():
        await ws.send_json({"type": "error", "message": "Live voice is not switched on (GEMINI_API_KEY / LIVE_ENABLED)."})
        await ws.close()
        return
    log.info("live voice start: %s (%s)", user["name"], lang)
    await live.bridge(ws, user, lang)
    log.info("live voice end: %s", user["name"])


@app.post("/api/stt")
async def stt(audio: UploadFile = File(...), user: dict = Depends(current_user)):
    """Speech -> text (Gemini), for browsers without speech recognition and for better Hinglish."""
    data = await audio.read()
    if not data:
        raise HTTPException(400, "Empty recording")
    t0 = time.time()
    try:
        text = await run_in_threadpool(voice.transcribe, data, audio.content_type or "audio/webm")
        log.info("timing stt %.1fs (%d KB)", time.time() - t0, len(data) // 1024)
    except voice.VoiceError as e:
        raise HTTPException(503, str(e))
    return {"text": text}


@app.get("/api/dashboard")
def dashboard(user: dict = Depends(current_user)):
    """Latest KPI cards per report (real numbers from saved reports) + recent history."""
    panels, seen = [], set()
    for r in store.search_reports(user, limit=40, include_preview=True):
        dp = r.get("data_preview") or []
        kpis = dp[0].get("kpis") if dp and isinstance(dp[0], dict) else None
        key = r.get("skill_name") or r.get("title")
        if kpis and key not in seen:
            seen.add(key)
            panels.append({"title": r["title"], "skill": r.get("skill_name") or "", "kpis": kpis[:5],
                           "created_at": config.iso_local(r["created_at"]), "report_id": r["id"],
                           "summary": (r.get("summary") or "")[:220]})
        if len(panels) >= 3:
            break
    recent = [{"id": r["id"], "title": r["title"], "created_at": config.iso_local(r["created_at"]),
               "skill": r.get("skill_name") or "",
               "files": [{k: f[k] for k in ("format", "url")} for f in r.get("files") or []]}
              for r in store.search_reports(user, limit=6)]
    return {"panels": panels, "recent": recent}


@app.post("/api/chat")
async def chat(body: ChatIn, user: dict = Depends(current_user)):
    t0 = time.time()
    reply = await run_in_threadpool(lambda: agent.handle_message(user, body.message, "web", f"web:{user['id']}",
                                                                 user.get("telegram_id") or "", True, body.voice,
                                                                 attachments=body.attachments))
    log.info("timing chat %.1fs (voice=%s, files=%d)", time.time() - t0, body.voice, len(reply.files))
    return _reply_json(reply)


# ------------------------------------------------------------------ arc keyboard remote (phone -> big screen)
class RemoteKeyIn(BaseModel):
    k: str
    src: str = ""


_remote: dict = {}            # user id -> set of asyncio.Queue (one per open screen of that user)


@app.post("/api/remote/key")
async def remote_key(body: RemoteKeyIn, user: dict = Depends(current_user)):
    """A key tapped on the phone's arc keyboard -> every other open VERONICA screen of the SAME user."""
    k = body.k[:16]
    if not k:
        raise HTTPException(400, "empty key")
    qs = list(_remote.get(user["id"], ()))
    for q in qs:
        if q.qsize() < 300:
            q.put_nowait({"k": k, "src": body.src[:40]})
    return {"screens": len(qs)}


@app.get("/api/remote/stream")
async def remote_stream(user: dict = Depends(current_user)):
    """Open screens listen here for keys from the user's phone (server-sent events, own account only)."""
    import asyncio
    import json as _json
    from fastapi.responses import StreamingResponse
    q: asyncio.Queue = asyncio.Queue()
    _remote.setdefault(user["id"], set()).add(q)

    async def gen():
        try:
            yield ": open\n\n"
            ends = time.time() + 300                           # recycle every 5 min: no connection lives forever
            while time.time() < ends:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=20)
                    yield "data: " + _json.dumps(ev, ensure_ascii=False) + "\n\n"
                except asyncio.TimeoutError:
                    if not store.get_user_by_session(user.get("_session", "")) and user.get("_session"):
                        break                                  # signed out / disabled -> stop listening
                    yield ": ping\n\n"
        finally:
            _remote.get(user["id"], set()).discard(q)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/chat/stream")
async def chat_stream(body: ChatIn, user: dict = Depends(current_user)):
    """Same as /api/chat, but streams: steps (Activity), figures (Latest analysis), answer words, then the reply."""
    import asyncio
    import json as _json
    from fastapi.responses import StreamingResponse
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    emit = lambda ev: loop.call_soon_threadsafe(q.put_nowait, ev)
    t0 = time.time()

    def work():
        try:
            r = agent.handle_message(user, body.message, "web", f"web:{user['id']}", user.get("telegram_id") or "",
                                     True, body.voice, emit=emit, attachments=body.attachments)
            emit({"type": "reply", **_reply_json(r), "seconds": round(time.time() - t0, 1)})
            log.info("timing chat-stream %.1fs (voice=%s)", time.time() - t0, body.voice)
        except Exception as e:
            log.exception("chat stream failed")
            emit({"type": "error", "message": str(e)[:300]})
        finally:
            emit(None)
    loop.run_in_executor(None, work)

    async def gen():
        yield ": open\n\n"
        while True:
            ev = await q.get()
            if ev is None:
                break
            yield "data: " + _json.dumps(ev, ensure_ascii=False, default=str) + "\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), user: dict = Depends(current_user)):
    """A file attached in the chat window -> kept for this user, summarised, ready for the next question."""
    from . import uploads
    data = await file.read()
    try:
        return await run_in_threadpool(uploads.save, user, file.filename or "file", data)
    except uploads.UploadError as e:
        raise HTTPException(400, str(e)) from None


@app.get("/api/briefing")
async def briefing(user: dict = Depends(current_user)):
    """Today's pulse: key numbers of this month from the taught engines + what changed most (no AI call, fast)."""
    from . import dash
    return await run_in_threadpool(dash.briefing, user)


@app.post("/api/chat/reset")
def chat_reset(user: dict = Depends(current_user)):
    store.clear_chat(f"web:{user['id']}")
    return {"ok": True}


# ------------------------------------------------------------------ skills (teach node API)
class SkillIn(BaseModel):
    name: str
    title: str
    description: str = ""
    rules: str = ""
    output_format: str = ""
    default_formats: list[str] | str = "table"
    sql_template: str = ""
    example_output: str = ""
    allowed_roles: list[str] = []


@app.get("/api/skills")
def skills_list(user: dict = Depends(current_user)):
    return store.list_skills(user)


@app.get("/api/skills/{name}")
def skill_get(name: str, user: dict = Depends(current_user)):
    s = store.get_skill(name)
    if not s or not store.skill_allowed(s, user):
        raise HTTPException(404, "not found")
    return s


@app.post("/api/skills")
def skill_save(body: SkillIn, user: dict = Depends(current_user)):
    """Direct teaching (used by the n8n 'Teach Report' form). If no SQL is given, the agent
    will work it out the first time the report runs and you can save it back via chat."""
    if not store.get_role(user["role"]).get("can_teach"):
        raise HTTPException(403, "Your role cannot teach reports")
    try:
        s = store.save_skill(body.model_dump(), changed_by=user["name"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    if config.TELEGRAM_BOT_TOKEN:
        try:
            telegram.set_commands()
        except Exception:
            pass
    return {"saved": True, "command": "/" + s["name"], "version": s["version"]}


@app.delete("/api/skills/{name}")
def skill_delete(name: str, user: dict = Depends(current_user)):
    if not store.get_role(user["role"]).get("can_teach"):
        raise HTTPException(403, "Your role cannot change reports")
    return {"deleted": store.delete_skill(name)}


class RunIn(BaseModel):
    prompt: str = ""
    formats: list[str] = []
    deliver_to_chat_id: str = ""   # send the result to this Telegram chat as well


@app.post("/api/skills/{name}/run")
async def skill_run(name: str, body: RunIn, user: dict = Depends(current_user)):
    text = f"/{name} {body.prompt}".strip()
    if body.formats:
        text += f"\n(Output formats: {','.join(body.formats)}. Do not ask questions.)"
    reply = await run_in_threadpool(agent.handle_message, user, text, "n8n",
                                    f"api:{user['id']}:{name}", body.deliver_to_chat_id, False)
    if body.deliver_to_chat_id and config.TELEGRAM_BOT_TOKEN:
        await run_in_threadpool(telegram.send_reply, body.deliver_to_chat_id, reply)
    return _reply_json(reply)


# ------------------------------------------------------------------ history & schedules
@app.get("/api/history")
def history(q: str = "", skill: str = "", limit: int = 20, user: dict = Depends(current_user)):
    rows = store.search_reports(user, q, skill, min(limit, 100))
    from . import filelinks
    for r in rows:      # fresh signed links (old saved links expire; the logged-in owner gets a new one)
        r["created_at"] = config.iso_local(r.get("created_at"))       # stored UTC -> India time with +05:30
        r["files"] = [{"format": f["format"], "filename": f["filename"],
                       "url": (filelinks.url(*f["url"].split("/files/", 1)[1].split("?")[0].split("/", 1))
                               if "/files/" in (f.get("url") or "") else f.get("url"))} for f in r["files"] or []]
    return rows


@app.get("/api/schedules")
def schedules_list(user: dict = Depends(current_user)):
    return [{**s, "next_run": scheduler.next_run(s["id"])} for s in store.list_schedules(user)]


@app.post("/api/schedules/{schedule_id}/run")
async def schedule_run_now(schedule_id: int, user: dict = Depends(current_user)):
    if schedule_id not in {s["id"] for s in store.list_schedules(user)}:
        raise HTTPException(404, "not found")
    return await run_in_threadpool(scheduler.run_schedule, schedule_id)


# ------------------------------------------------------------------ users (admin)
class UserIn(BaseModel):
    name: str
    role: str = "viewer"
    telegram_id: str | None = None
    username: str | None = None
    password: str | None = None


@app.get("/api/users")
def users_list(user: dict = Depends(current_user)):
    if not store.get_role(user["role"]).get("is_admin"):
        _admin_denied(user, "/api/users")
    return [{k: v for k, v in u.items() if k != "password_hash"} for u in store.list_users()]


@app.post("/api/users")
def users_add(body: UserIn, user: dict = Depends(current_user)):
    if not store.get_role(user["role"]).get("is_admin"):
        _admin_denied(user, "/api/users")
    nu = store.add_user(body.name, body.role, body.telegram_id)
    if body.username and body.password:
        try:
            store.set_login(nu["id"], body.username, body.password)
        except ValueError as e:
            raise HTTPException(400, str(e))
    nu = store.get_user(nu["id"])
    nu.pop("password_hash", None)
    return {**nu, "web_link": f"{config.PUBLIC_BASE_URL}/"}


class ThemesIn(BaseModel):
    user_id: int
    themes: list[str]


@app.get("/api/admin/themes")
def admin_themes(user: dict = Depends(current_user)):
    """Admin: which looks each user may use."""
    if not store.get_role(user["role"]).get("is_admin"):
        _admin_denied(user, "/api/admin/themes")
    return {"themes": store.THEMES,
            "users": [{"id": u["id"], "name": u["name"], "username": (u.get("username") or "").upper(), "role": u["role"], "active": bool(u.get("active", True)),
                       "themes": store.user_themes(u), "division": (u.get("division") or "ALL"),
                       "scrap_lines": store.user_scrap_lines(u), "issue_plants": store.user_issue_plants(u)} for u in store.list_users()],
            "scrap_lines": [{"k": k, "label": v} for k, v in store.SCRAP_LINES.items()]}


class LinesIn(BaseModel):
    user_id: int
    lines: list[str]


@app.post("/api/admin/scrap-lines")
def admin_set_scrap_lines(body: LinesIn, user: dict = Depends(current_user)):
    """Admin: Scrap MIS plant lines a user may see (empty / all ticked = no limit)."""
    if not store.get_role(user["role"]).get("is_admin"):
        _admin_denied(user, "/api/admin/scrap-lines")
    if not store.get_user(body.user_id):
        raise HTTPException(404, "No such user")
    got = store.set_user_scrap_lines(body.user_id, body.lines)
    log.info("scrap lines of user #%s set to %s by %s", body.user_id, got or "ALL", user["name"])
    return {"user_id": body.user_id, "lines": got}


_ISSUE_PLANTS: dict = {}


@app.get("/api/admin/issue-plants")
def admin_issue_plants(user: dict = Depends(current_user)):
    """Admin: plant names in the issue view (for the per-user plant picker), cached 30 min."""
    if not store.get_role(user["role"]).get("is_admin"):
        _admin_denied(user, "/api/admin/issue-plants")
    from .engines import issue
    hit = _ISSUE_PLANTS.get("v")
    if not hit or time.time() - hit[0] > 1800:
        try:
            hit = (time.time(), issue.plants_list(["*"]))
        except Exception as e:
            raise HTTPException(400, f"Could not read plants from {issue.DEFAULT_SOURCE}: {e}")
        _ISSUE_PLANTS["v"] = hit
    return {"plants": hit[1]}


class PlantsIn(BaseModel):
    user_id: int
    plants: list[str]


@app.post("/api/admin/issue-plants")
def admin_set_issue_plants(body: PlantsIn, user: dict = Depends(current_user)):
    """Admin: plants a user may see in the Issue dashboard (empty = all plants of their division)."""
    if not store.get_role(user["role"]).get("is_admin"):
        _admin_denied(user, "/api/admin/issue-plants")
    if not store.get_user(body.user_id):
        raise HTTPException(404, "No such user")
    got = store.set_user_issue_plants(body.user_id, body.plants)
    log.info("issue plants of user #%s set to %s by %s", body.user_id, got or "ALL", user["name"])
    return {"user_id": body.user_id, "plants": got}


@app.get("/api/admin/security")
def admin_security(days: int = 30, user: dict = Depends(current_user)):
    """Admin: access-denied audit trail (who asked for what outside their rights)."""
    if not store.get_role(user["role"]).get("is_admin"):
        _admin_denied(user, "/api/admin/security")
    rows = store.list_security_events(max(1, min(days, 365)))
    from datetime import timezone
    from zoneinfo import ZoneInfo as _Z
    for r in rows:
        if r.get("at"):
            r["at"] = config.local_dt(r["at"]).strftime("%d-%m-%Y %H:%M")
    return {"events": rows, "days": days}


# ------------------------------------------------------------------ Access control console (admin role only)
def _need_admin(user: dict, what: str) -> None:
    if not store.get_role(user["role"]).get("is_admin"):
        _admin_denied(user, what)


def _audit(user: dict, detail: str) -> None:
    """Every rights change is written to the security log (kind rbac_change), no alert."""
    from . import security
    security.denied(user, "rbac_change", detail, "web", notify=False)


def _active_admins(excluding: int | None = None) -> list[dict]:
    return [u for u in store.list_users() if u.get("active", True) and u["id"] != excluding
            and store.get_role(u["role"]).get("is_admin")]


@app.get("/api/admin/rbac")
def rbac_all(user: dict = Depends(current_user)):
    """Everything the Access control screen needs: users, roles, reports and the views a role can be given."""
    _need_admin(user, "/api/admin/rbac")
    import json as _j
    users = [{"id": u["id"], "name": u["name"], "username": (u.get("username") or "").upper(), "role": u["role"],
              "active": bool(u.get("active", True)), "email": u.get("email") or "", "phone": u.get("phone") or "",
              "division": u.get("division") or "ALL", "has_login": bool(u.get("password_hash")),
              "alerts": store.gets_security_alerts(u)} for u in store.list_users()]
    roles = [{k: r.get(k) for k in ("name", "description", "allowed_tables", "can_teach", "can_schedule", "free_query", "is_admin")}
             | {"users": sum(1 for u in users if u["role"] == r["name"])} for r in store.list_roles()]
    from .access import skill_tables
    skills = []
    for sk in store.list_skills():
        try:
            st = _j.loads(sk.get("sql_template") or "{}")
            src = st.get("source") if isinstance(st, dict) else None
        except ValueError:
            src = None
        skills.append({"name": sk["name"], "title": sk["title"], "allowed_roles": sk.get("allowed_roles") or [],
                       "views": sorted(skill_tables(sk)) if not src else [src]})
    try:
        views = list(datadb._all_tables())
    except Exception:
        views = []
    return {"users": users, "roles": roles, "skills": skills, "views": views, "private": config.PRIVATE_TABLES, "me": user["id"]}


class RbacUserIn(BaseModel):
    name: str | None = None
    role: str | None = None
    active: bool | None = None
    alerts: bool | None = None
    email: str | None = None
    phone: str | None = None


@app.post("/api/admin/rbac/users/{uid}")
def rbac_user_update(uid: int, body: RbacUserIn, user: dict = Depends(current_user)):
    _need_admin(user, f"/api/admin/rbac/users/{uid}")
    u = store.get_user(uid)
    if not u:
        raise HTTPException(404, "No such user")
    was_admin = store.get_role(u["role"]).get("is_admin")
    if body.role is not None and body.role != u["role"]:
        if was_admin and not store.get_role(body.role).get("is_admin") and not _active_admins(excluding=uid):
            raise HTTPException(400, "This is the last active admin - make someone else admin first.")
        if uid == user["id"] and not store.get_role(body.role).get("is_admin"):
            raise HTTPException(400, "You cannot remove your own admin rights.")
        try:
            store.set_user_role(uid, body.role)
        except ValueError as e:
            raise HTTPException(400, str(e))
        store.end_all_sessions(uid)                     # new rights from their next sign-in
        _audit(user, f"{u['name']}: role {u['role']} -> {body.role}")
    if body.active is not None and body.active != bool(u.get("active", True)):
        if not body.active and uid == user["id"]:
            raise HTTPException(400, "You cannot disable yourself.")
        if not body.active and was_admin and not _active_admins(excluding=uid):
            raise HTTPException(400, "This is the last active admin.")
        store.set_active(uid, body.active)
        _audit(user, f"{u['name']}: {'enabled' if body.active else 'DISABLED (signed out everywhere)'}")
    if body.alerts is not None and body.alerts != store.gets_security_alerts(u):
        store.set_security_alerts(uid, body.alerts)
        _audit(user, f"{u['name']}: security alert mails {'ON' if body.alerts else 'OFF'}")
    if body.name is not None and body.name.strip() and body.name.strip() != u["name"]:
        store.rename_user(uid, body.name)
        _audit(user, f"{u['name']}: renamed to {body.name.strip()}")
    if body.email is not None or body.phone is not None:
        em = (body.email or "").strip()
        if em and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", em):
            raise HTTPException(400, "E-mail looks wrong.")
        store.set_user_contact(uid, email=em if body.email is not None else None,
                               phone=(body.phone or "").strip() if body.phone is not None else None)
        _audit(user, f"{u['name']}: contact updated")
    return {"ok": True}


class RbacLoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/admin/rbac/users/{uid}/login")
def rbac_user_login(uid: int, body: RbacLoginIn, user: dict = Depends(current_user)):
    """Admin sets / resets a user's login (signs them out everywhere)."""
    _need_admin(user, f"/api/admin/rbac/users/{uid}/login")
    u = store.get_user(uid)
    if not u:
        raise HTTPException(404, "No such user")
    try:
        store.set_login(uid, body.username, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _audit(user, f"{u['name']}: login set / password reset (login {body.username.strip().upper()})")
    return {"ok": True}


@app.delete("/api/admin/rbac/users/{uid}")
def rbac_user_delete(uid: int, user: dict = Depends(current_user)):
    _need_admin(user, f"/api/admin/rbac/users/{uid} DELETE")
    if uid == user["id"]:
        raise HTTPException(400, "You cannot delete yourself.")
    try:
        u = store.delete_user(uid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _audit(user, f"user {u['name']} (#{uid}, role {u['role']}) DELETED")
    return {"ok": True}


class RbacNewUserIn(BaseModel):
    name: str
    role: str
    username: str
    password: str
    email: str = ""


@app.post("/api/admin/rbac/users")
def rbac_user_add(body: RbacNewUserIn, user: dict = Depends(current_user)):
    _need_admin(user, "/api/admin/rbac/users")
    if not any(r["name"] == body.role for r in store.list_roles()):
        raise HTTPException(400, f"Role '{body.role}' does not exist.")
    if not body.name.strip():
        raise HTTPException(400, "Name is empty.")
    nu = store.add_user(" ".join(body.name.split()), body.role, None)
    try:
        store.set_login(nu["id"], body.username, body.password)
    except ValueError as e:
        store.delete_user(nu["id"])
        raise HTTPException(400, str(e))
    if body.email.strip():
        store.set_user_contact(nu["id"], email=body.email.strip())
    _audit(user, f"user {nu['name']} created (role {body.role}, login {body.username.strip().upper()})")
    return {"ok": True, "id": nu["id"]}


class RbacRoleIn(BaseModel):
    name: str
    description: str = ""
    allowed_tables: list[str] = []
    can_teach: bool = False
    can_schedule: bool = False
    free_query: bool = True
    is_admin: bool = False


@app.post("/api/admin/rbac/roles")
def rbac_role_save(body: RbacRoleIn, user: dict = Depends(current_user)):
    """Create or change a role: which views it may read and what it may do."""
    _need_admin(user, "/api/admin/rbac/roles")
    name = body.name.strip().lower()
    old = next((r for r in store.list_roles() if r["name"] == name), None)
    if old and old.get("is_admin") and not body.is_admin:
        holders = [u for u in store.list_users() if u["role"] == name and u.get("active", True)]
        others = [u for u in _active_admins() if u["role"] != name]
        if holders and not others:
            raise HTTPException(400, "Taking admin away from this role would leave nobody as admin.")
        if user["role"] == name:
            raise HTTPException(400, "You cannot remove admin from your own role.")
    tabs = []
    for t in body.allowed_tables:
        t = t.strip()
        if t and re.match(r"^!?[A-Za-z0-9_*.\-]+$", t) and t not in tabs:
            tabs.append(t)
    if body.is_admin:
        tabs = ["*"]
    try:
        r = store.save_role(name, tabs, body.description.strip()[:250], body.can_teach, body.can_schedule,
                            body.free_query, body.is_admin)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if old:
        added = sorted(set(tabs) - set(old.get("allowed_tables") or []))
        removed = sorted(set(old.get("allowed_tables") or []) - set(tabs))
        flags = [f"{k}={getattr(body, k)}" for k in ("can_teach", "can_schedule", "free_query", "is_admin") if bool(old.get(k)) != getattr(body, k)]
        _audit(user, f"role {name} changed: " + "; ".join(x for x in (
            ("+views " + ", ".join(added)) if added else "", ("-views " + ", ".join(removed)) if removed else "",
            ", ".join(flags)) if x) or f"role {name} saved (no change)")
    else:
        _audit(user, f"role {name} created with {len(tabs)} view rule(s)")
    from . import dash
    dash._cache.clear()
    return {"ok": True, "role": r}


@app.delete("/api/admin/rbac/roles/{name}")
def rbac_role_delete(name: str, user: dict = Depends(current_user)):
    _need_admin(user, f"/api/admin/rbac/roles/{name} DELETE")
    if name in ("admin",):
        raise HTTPException(400, "The admin role cannot be deleted.")
    n = sum(1 for u in store.list_users() if u["role"] == name)
    if n:
        raise HTTPException(400, f"{n} user(s) still have this role - move them first.")
    if not store.delete_role(name):
        raise HTTPException(404, "No such role")
    _audit(user, f"role {name} deleted")
    return {"ok": True}


class RbacSkillIn(BaseModel):
    roles: list[str] = []


@app.post("/api/admin/rbac/skills/{name}")
def rbac_skill_roles(name: str, body: RbacSkillIn, user: dict = Depends(current_user)):
    """Which roles may run a report / open its dashboard ([] = every role that can read its views)."""
    _need_admin(user, f"/api/admin/rbac/skills/{name}")
    sk = store.get_skill(name)
    if not sk:
        raise HTTPException(404, "No such report")
    known = {r["name"] for r in store.list_roles()}
    roles = [r for r in dict.fromkeys(body.roles) if r in known]
    store.save_skill({"name": sk["name"], "allowed_roles": roles}, user["name"])
    from . import dash
    dash._cache.clear()
    _audit(user, f"report /{name}: roles {', '.join(sk.get('allowed_roles') or []) or 'everyone'} -> {', '.join(roles) or 'everyone'}")
    return {"ok": True, "allowed_roles": roles}


class DivisionIn(BaseModel):
    user_id: int
    division: str


@app.post("/api/admin/division")
def admin_set_division(body: DivisionIn, user: dict = Depends(current_user)):
    """Admin: U1 = Welded only, U2 = Seamless only, ALL = both (applies to every report, dashboard and chat answer)."""
    if not store.get_role(user["role"]).get("is_admin"):
        _admin_denied(user, "/api/admin/division")
    if not store.get_user(body.user_id):
        raise HTTPException(404, "No such user")
    d = body.division.strip().upper()
    if d not in ("U1", "U2", "ALL"):
        raise HTTPException(400, "Division must be U1, U2 or ALL")
    store.set_user_division(body.user_id, "" if d == "ALL" else d)
    log.info("division of user #%s set to %s by %s", body.user_id, d, user["name"])
    return {"user_id": body.user_id, "division": d}


@app.post("/api/admin/themes")
def admin_set_themes(body: ThemesIn, user: dict = Depends(current_user)):
    if not store.get_role(user["role"]).get("is_admin"):
        _admin_denied(user, "/api/admin/themes")
    if not store.get_user(body.user_id):
        raise HTTPException(404, "No such user")
    if not [x for x in body.themes if x in store.THEMES]:
        raise HTTPException(400, "Pick at least one look")
    return {"user_id": body.user_id, "themes": store.set_user_themes(body.user_id, body.themes)}


@app.post("/api/admin/refresh-schema")
def refresh_schema(user: dict = Depends(current_user)):
    if not store.get_role(user["role"]).get("is_admin"):
        _admin_denied(user, "/api/admin/refresh-schema")
    datadb.refresh_schema_cache()
    return {"ok": True}


# ------------------------------------------------------------------ n8n
class N8nChatIn(BaseModel):
    telegram_id: str
    chat_id: str
    text: str
    deliver: bool = False  # True = this server sends the reply to Telegram itself


@app.post("/api/n8n/chat")
async def n8n_chat(body: N8nChatIn, x_api_key: str = Header(default="")):
    if not (config.SERVICE_API_KEY and hmac.compare_digest(x_api_key, config.SERVICE_API_KEY)):
        raise HTTPException(401, "bad api key")
    if not config.TELEGRAM_ENABLED:
        raise HTTPException(404, "Telegram is switched off")
    user = store.get_user_by_telegram(body.telegram_id)
    if not user:
        return {"registered": False, "text": f"🙏 Not registered. Send this id to your admin: "
                                             f"{body.telegram_id}", "files": [], "tables": []}
    if body.text.startswith("/"):
        cmd = body.text[1:].split()[0].split("@")[0].lower()
        if cmd in {"start", "help", "myid", "new", "skills", "history", "schedules", "adduser", "dashboard", "dashboards", "dash"}:
            await run_in_threadpool(telegram.process_update, {"message": {
                "chat": {"id": body.chat_id, "type": "private"},
                "from": {"id": body.telegram_id}, "text": body.text}})
            return {"registered": True, "handled": True, "text": "", "files": [], "tables": []}
    reply = await run_in_threadpool(agent.handle_message, user, body.text, "telegram",
                                    f"tg:{body.chat_id}", body.chat_id)
    if body.deliver:
        await run_in_threadpool(telegram.send_reply, body.chat_id, reply)
    return {"registered": True, **_reply_json(reply)}


# ------------------------------------------------------------------ telegram (direct mode)
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request, background: BackgroundTasks,
                           x_telegram_bot_api_secret_token: str = Header(default="")):
    if not config.TELEGRAM_ENABLED:
        raise HTTPException(404)
    if config.TELEGRAM_WEBHOOK_SECRET and not hmac.compare_digest(
            x_telegram_bot_api_secret_token, config.TELEGRAM_WEBHOOK_SECRET):
        raise HTTPException(401)
    update = await request.json()
    background.add_task(telegram.process_update, update)  # reply fast, work in background
    return {"ok": True}


# ------------------------------------------------------------------ WhatsApp (Meta Cloud API webhook)
@app.get("/whatsapp/webhook")
def whatsapp_verify(request: Request):
    q = request.query_params
    if (q.get("hub.mode") == "subscribe" and config.WHATSAPP_VERIFY_TOKEN
            and hmac.compare_digest(q.get("hub.verify_token", ""), config.WHATSAPP_VERIFY_TOKEN)):
        return Response(q.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(403, "verify token does not match WHATSAPP_VERIFY_TOKEN in .env")


@app.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request, background: BackgroundTasks,
                           x_hub_signature_256: str = Header(default="")):
    from . import whatsapp
    body = await request.body()
    if not whatsapp.verify_signature(body, x_hub_signature_256):
        raise HTTPException(401)
    background.add_task(whatsapp.process, json.loads(body or b"{}"))
    return {"ok": True}


# ------------------------------------------------------------------ files
@app.get("/files/{folder}/{filename}")
def get_file(folder: str, filename: str, request: Request, e: str = "", s: str = ""):
    from . import filelinks
    if not folder.isalnum() or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400)
    if not filelinks.ok(folder, filename, e, s):        # unsigned, tampered or expired link
        raise HTTPException(403, "This file link has expired or is not valid. Ask VERONICA for the report again.")
    p = config.OUTPUT_DIR / folder / filename
    if not p.is_file():
        raise HTTPException(404)
    if config.LINKS_REQUIRE_LOGIN and not link_viewer(request):        # file link alone is not enough: signed-in browser
        from . import security, dash
        security.denied({"name": "(not signed in)", "role": "-"}, "link_without_login", f"file {filename} opened without signing in",
                        "web", ip=client_ip(request), notify=False)
        return HTMLResponse(_dash_login_page(request), status_code=401)
    if p.suffix == ".html":                                  # older saved reports: swap internet links for local copies
        return HTMLResponse(vendor.localize(p.read_text(encoding="utf-8", errors="replace")),
                            headers={"Content-Disposition": f'inline; filename="{filename}"'})
    inline = p.suffix in (".png", ".pdf")
    return FileResponse(p, filename=filename,
                        content_disposition_type="inline" if inline else "attachment")
