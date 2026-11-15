"""Central settings, read from environment / .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import logging as _logging
for _noisy in ("httpx", "httpcore"):   # never write full request URLs to logs (Telegram URLs contain the bot token)
    _logging.getLogger(_noisy).setLevel(_logging.WARNING)

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
CLAUDE_MODEL = _get("CLAUDE_MODEL", "claude-sonnet-5-5")

DATA_DB_URL = _get("DATA_DB_URL", "sqlite:///sample_data.db")
BOT_DB_URL = _get("BOT_DB_URL", "sqlite:///reportbot.db")

TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_MODE = _get("TELEGRAM_MODE", "direct")  # direct | n8n
# Telegram switched off by management (web app only); set TELEGRAM_ENABLED=true in .env to bring it back
TELEGRAM_ENABLED = _get("TELEGRAM_ENABLED", "false").lower() in ("1", "true", "yes")
TELEGRAM_WEBHOOK_SECRET = _get("TELEGRAM_WEBHOOK_SECRET")

PUBLIC_BASE_URL = _get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
SERVICE_API_KEY = _get("SERVICE_API_KEY")

BOOTSTRAP_ADMIN_NAME = _get("BOOTSTRAP_ADMIN_NAME", "admin")
BOOTSTRAP_ADMIN_TELEGRAM_ID = _get("BOOTSTRAP_ADMIN_TELEGRAM_ID")
BOOTSTRAP_ADMIN_WEB_TOKEN = _get("BOOTSTRAP_ADMIN_WEB_TOKEN")

MAX_ROWS = int(_get("MAX_ROWS", "5000"))
QUERY_TIMEOUT_SECONDS = int(_get("QUERY_TIMEOUT_SECONDS", "30"))
TIMEZONE = _get("TIMEZONE", "Asia/Kolkata")


def local_dt(d):
    """VERONICA's own database stores UTC (no zone). Turn it into India time (TIMEZONE, GMT+05:30)."""
    from datetime import datetime as _d, timezone as _tz
    from zoneinfo import ZoneInfo as _Z
    if not isinstance(d, _d):
        return d
    return (d if d.tzinfo else d.replace(tzinfo=_tz.utc)).astimezone(_Z(TIMEZONE))


def ist(d) -> str:
    """'30-10-2026 20:29 IST' - for answers and the AI (never raw UTC)."""
    x = local_dt(d)
    return x.strftime("%d-%m-%Y %H:%M IST") if hasattr(x, "strftime") else str(x or "")


def iso_local(d) -> str:
    """ISO with the +05:30 offset, so the browser shows the right clock time."""
    x = local_dt(d)
    return x.isoformat(timespec="seconds") if hasattr(x, "isoformat") else str(x or "")
COMPANY_NAME = _get("COMPANY_NAME", "Your Company")
CREATOR_NAME = _get("CREATOR_NAME", "Shubham Kakde")      # who built VERONICA (she answers "who made you?")
# only these login usernames are greeted "Hello Boss" (with the intro music); everyone else by their own name
# roles with the "power" features: hand-gesture control and every theme (others: DEFAULT_THEMES unless the admin ticks more)
POWER_ROLES = {r.strip().lower() for r in _get("POWER_ROLES", "admin,manager").split(",") if r.strip()}
DEFAULT_THEMES = [t.strip().lower() for t in _get("DEFAULT_THEMES", "aurora").split(",") if t.strip()]
GESTURE_LOCAL_ONLY = _get("GESTURE_LOCAL_ONLY", "false").lower() in ("1", "true", "yes")
BOSS_USERNAMES = {u.strip().lower() for u in _get("BOSS_USERNAMES", "admin").split(",") if u.strip()}
ASSISTANT_NAME = _get("ASSISTANT_NAME", "VERONICA")
# dry = calm, witty one-liners like a film AI butler (default); off = plain and formal
HUMOR = _get("HUMOR", "dry").lower()
ASSISTANT_TAGLINE = _get("ASSISTANT_TAGLINE", "Your Smart Partner in Pipes & Tubes")

# Voice (Google Gemini). Leave GEMINI_API_KEY empty to switch voice off.
GEMINI_API_KEY = _get("GEMINI_API_KEY")
# ---- sending reports out ("send this to Bharat on WhatsApp / Telegram / mail")
SMTP_HOST = _get("SMTP_HOST")                   # company mail server only (e.g. smtp.office365.com)
SMTP_PORT = int(_get("SMTP_PORT", "587") or 587)
SMTP_USER = _get("SMTP_USER")
SMTP_PASSWORD = _get("SMTP_PASSWORD")
SMTP_FROM = _get("SMTP_FROM") or SMTP_USER
SMTP_SSL = _get("SMTP_SSL", "false").lower() == "true"     # true = port 465 SSL, false = STARTTLS
# e-mail reports may go only to these domains (comma list). Empty = the domain of SMTP_FROM, i.e. company mail only.
MAIL_ALLOWED_DOMAINS = [d.strip().lower().lstrip("@") for d in (_get("MAIL_ALLOWED_DOMAINS") or
                        (SMTP_FROM.split("@")[-1] if SMTP_FROM and "@" in SMTP_FROM else "")).split(",") if d.strip()]
WHATSAPP_TOKEN = _get("WHATSAPP_TOKEN")         # Meta WhatsApp Cloud API permanent token
WHATSAPP_PHONE_ID = _get("WHATSAPP_PHONE_ID")   # phone-number id of the business sender
WHATSAPP_TEMPLATE = _get("WHATSAPP_TEMPLATE")
WHATSAPP_VERIFY_TOKEN = _get("WHATSAPP_VERIFY_TOKEN")   # any secret word you also type in Meta -> Webhook -> Verify token
WHATSAPP_APP_SECRET = _get("WHATSAPP_APP_SECRET")       # Meta app -> Settings -> Basic -> App secret (checks every call)   # optional approved template to open the chat (no reply in 24 h)
SEND_MAX_MB = int(_get("SEND_MAX_MB", "20") or 20)
GEMINI_TTS_MODEL = _get("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")
GEMINI_STT_MODEL = _get("GEMINI_STT_MODEL", "gemini-3.8-flash")
GEMINI_VOICE = _get("GEMINI_VOICE", "Sulafat")   # warm female voice; see: python -m tools.manage voices hi-IN
# Gemini Live = real-time talking (fast, interruptible). Claude still answers every data question via tools.
LIVE_ENABLED = _get("LIVE_ENABLED", "false").lower() in ("1", "true", "yes")
# comma list allowed; tried in order. gemini-3.1-flash-live-preview is legacy (it may ignore the voice = male voice)
GEMINI_LIVE_MODEL = _get("GEMINI_LIVE_MODEL", "gemini-3.8-live")
GEMINI_LIVE_VOICE = _get("GEMINI_LIVE_VOICE") or GEMINI_VOICE
LIVE_NONBLOCKING = _get("LIVE_NONBLOCKING", "true").lower() in ("1", "true", "yes")   # keep talking while data loads
LIVE_SILENCE_MS = int(_get("LIVE_SILENCE_MS", "700"))       # pause that ends your turn
# tts    = Talk speaks with the SAME voice as chat / "manage say" (GEMINI_VOICE via Gemini TTS). Recommended.
# native = Live model's own voice: fastest, but sounds different (can sound male on some models)
LIVE_VOICE_MODE = _get("LIVE_VOICE_MODE", "tts").lower()
# Empty (best) = she follows whatever language you speak. Set e.g. hi-IN only to force one language.
LIVE_LANGUAGE_CODE = _get("LIVE_LANGUAGE_CODE")
# browser = Chrome/Edge live speech recognition (fastest); gemini = record + Gemini (best for mixed Hinglish)
VOICE_INPUT = _get("VOICE_INPUT", "browser")
# Optional faster Claude model only for spoken questions, e.g. claude-haiku-5-5 (empty = same as CLAUDE_MODEL)
CLAUDE_VOICE_MODEL = _get("CLAUDE_VOICE_MODEL")
# true = ONLY the exact GEMINI_VOICE + GEMINI_TTS_MODEL is ever used (no lite model, no phone/browser voice).
# If Gemini is busy it retries; if still busy she shows text instead of speaking in another voice.
VOICE_STRICT = _get("VOICE_STRICT", "true").lower() in ("1", "true", "yes")
# Voice engine: auto   = her Gemini voice first; the free offline Kokoro voice (INSTALL_FREE_VOICE.bat) takes over
#                        whenever Gemini can't speak (daily limit used up, busy)
#               kokoro = Kokoro first (unlimited), Gemini only for Gujarati/Odia ;  gemini = Gemini only
TTS_ENGINE = _get("TTS_ENGINE", "auto").lower()
# true = each answer is spoken as ONE clip (one Gemini request) instead of one per sentence - the free plan's
# 10 clips/day then last for 10 answers instead of 2-3. Set false once billing is on (sentence clips start faster).
VOICE_ONE_CLIP = _get("VOICE_ONE_CLIP", "true").lower() in ("1", "true", "yes")
KOKORO_VOICE = _get("KOKORO_VOICE", "hf_alpha")      # hf_alpha / hf_beta (Indian), af_heart (US), bf_emma (UK)
KOKORO_THREADS = int(_get("KOKORO_THREADS", "2"))           # CPU cores the offline voice may use
KOKORO_MAX_CHARS = int(_get("KOKORO_MAX_CHARS", "220"))       # offline voice reads only the first sentences
KOKORO_SPEED = float(_get("KOKORO_SPEED", "1.0"))
KOKORO_DIR = BASE_DIR / "models" / "kokoro"
VOICE_STYLE = _get("VOICE_STYLE", "warm, sincere and polite, calm clear pace, like a caring Indian colleague")

# Web login. True = username + password required; personal ?token= links stop working.
WEB_REQUIRE_PASSWORD = _get("WEB_REQUIRE_PASSWORD", "true").lower() in ("1", "true", "yes")
SESSION_HOURS = int(_get("SESSION_HOURS", "12"))
LOGIN_MAX_FAILS = int(_get("LOGIN_MAX_FAILS", "5"))
LOGIN_LOCK_MINUTES = int(_get("LOGIN_LOCK_MINUTES", "15"))

# Private views: only admins (and roles that list them by name) can read these. Comma separated.
PRIVATE_TABLES = [t.strip() for t in _get("PRIVATE_TABLES", "VIEW_EMP_MAST_PBI").split(",") if t.strip()]

# Live dashboards: signed links for HODs (web + Telegram), valid this many hours; results cached this many seconds
DASH_LINK_HOURS = int(_get("DASH_LINK_HOURS", "24"))
LINKS_REQUIRE_LOGIN = _get("LINKS_REQUIRE_LOGIN", "true").lower() in ("1", "true", "yes", "on")   # dashboard / file links also need a signed-in browser
DASH_CACHE_SECONDS = int(_get("DASH_CACHE_SECONDS", "600"))
FILE_LINK_DAYS = int(_get("FILE_LINK_DAYS", "7"))          # report file links stop working after this many days
# Access-denied alerts to admins ("telegram,email", or empty to only log), once per user + kind every N minutes
SECURITY_ALERTS = [x.strip().lower() for x in _get("SECURITY_ALERTS", "telegram,email").split(",") if x.strip()]
SECURITY_ALERT_MINUTES = int(_get("SECURITY_ALERT_MINUTES", "10"))
SECURITY_ALERT_USERS = [int(x) for x in _get("SECURITY_ALERT_USERS", "").replace(" ", "").split(",") if x.isdigit()]
# Big views (Sales Order book): rows kept in memory this long, served stale up to SO_STALE_SECONDS while refreshing
SO_CACHE_SECONDS = int(_get("SO_CACHE_SECONDS", "900"))
SO_STALE_SECONDS = int(_get("SO_STALE_SECONDS", "7200"))
ENGINE_QUERY_TIMEOUT_SECONDS = int(_get("ENGINE_QUERY_TIMEOUT_SECONDS", "240"))

# How many previous chat turns the agent remembers per chat
CHAT_MEMORY_TURNS = int(_get("CHAT_MEMORY_TURNS", "12"))
# Max tool-use rounds per request (safety stop)
MAX_AGENT_STEPS = int(_get("MAX_AGENT_STEPS", "12"))
FAST_REPORTS = _get("FAST_REPORTS", "true").lower() != "false"   # report + period -> run the engine directly, no AI round-trips
UPLOAD_MAX_MB = int(_get("UPLOAD_MAX_MB", "15") or 15)
