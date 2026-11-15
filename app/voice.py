"""Voice for VERONICA, using Google Gemini (Interactions API, REST).

  speak(text, lang)      -> MP3 / OGG-Opus bytes   (gemini-3.8-flash-tts, warm female voice)
  transcribe(bytes, mt)  -> text in the speaker's own language/script (gemini-3.8-flash)

Claude still does all the thinking and the database work; Gemini is only the voice.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import re
import time

import httpx

from .net import TLS

from . import config

log = logging.getLogger("veronica.voice")
API = "https://generativelanguage.googleapis.com/v1beta/interactions"
_http = httpx.Client(timeout=httpx.Timeout(60, connect=10), verify=TLS)

LANGS = {"en": "en-IN", "hi": "hi-IN", "gu": "gu-IN", "mr": "mr-IN", "or": "or-IN", "raj": "raj-IN"}
# languages Gemini TTS has no code for: speak with the nearest code + a dialect instruction
TTS_CODE = {"raj-IN": "hi-IN"}
DIALECT = {"raj-IN": "Speak in Rajasthani (Marwari) with a natural Rajasthani accent. ",
           "or-IN": "Speak natural Odia with native Odia pronunciation. "}


class VoiceError(Exception):
    pass


def enabled() -> bool:
    from . import local_tts
    return bool(config.GEMINI_API_KEY) or local_tts.available()


# ------------------------------------------------------------------ text for speaking
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿️]")


def spoken_text(text: str, limit: int = 900) -> str:
    """Turn a chat reply into something pleasant to listen to."""
    t = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[*_`#>|]+", " ", t)
    t = re.sub(r"https?://\S+", " ", t)
    t = t.replace("✅", "").replace("⚠️", "Note: ")
    t = _EMOJI.sub(" ", t)
    t = re.sub(r"[-=]{3,}", " ", t)
    t = t.replace("→", " to ").replace("%", " percent").replace("₹", " rupees ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t).strip()
    if len(t) > limit:   # cut at a sentence end
        cut = max(t.rfind(".", 0, limit), t.rfind("।", 0, limit), t.rfind("\n", 0, limit))
        t = t[: cut + 1 if cut > limit // 2 else limit].strip()
    return t


def detect_lang(text: str, hint: str | None = None) -> str:
    """Language for the voice: from the script of the text; the UI language button only decides
    Hindi vs Marathi (same script) and the accent for romanised Hinglish."""
    hint = hint if hint in LANGS.values() else None
    if re.search(r"[\u0B00-\u0B7F]", text):
        return "or-IN"
    if re.search(r"[\u0A80-\u0AFF]", text):
        return "gu-IN"
    if re.search(r"[\u0900-\u097F]", text):
        return hint if hint in ("mr-IN", "raj-IN") else "hi-IN"
    return hint or "en-IN"


# ------------------------------------------------------------------ Gemini calls
BUSY = (429, 500, 502, 503, 504)   # overloaded / rate limited -> try again or use the next model


def _models(setting: str, extra: tuple[str, ...]) -> list[str]:
    """GEMINI_*_MODEL may list several models, comma separated; built-in backups are added at the end."""
    out = []
    for m in [x.strip() for x in setting.split(",")] + list(extra):
        if m and m not in out:
            out.append(m)
    return out


_quota_until = 0.0          # daily free-tier limit hit -> don't keep calling Gemini until it resets


def _daily_limit(text: str) -> float | None:
    """Seconds until reset when Gemini says the per-day quota is used up, else None."""
    if not re.search(r"per day|daily", text, re.I):
        return None
    m = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", text)
    secs = (int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)) if m else 0
    return float(secs or 3600)


def _post(body: dict, models: list[str]) -> dict:
    """Send to the first model; on 'high demand' retry once, then fall back to the next model."""
    global _quota_until
    if not enabled():
        raise VoiceError("Voice is not configured (GEMINI_API_KEY missing).")
    if time.time() < _quota_until:
        raise VoiceError("Rate limit: VERONICA's daily voice limit (Gemini free tier) is used up - it resets in "
                         f"{int((_quota_until - time.time()) // 3600)}h {int((_quota_until - time.time()) % 3600 // 60)}m.")
    last = ""
    tries = 4 if (config.VOICE_STRICT and len(models) == 1) else 2
    for model in models:
        for attempt in range(tries):
            try:
                r = _http.post(API, json={**body, "model": model},
                               headers={"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"})
            except httpx.HTTPError as e:
                last = f"network error: {e}"
                time.sleep(0.8)
                continue
            if r.status_code < 400:
                return r.json()
            last = f"{model} → {r.status_code}: {r.text[:200]}"
            wait = _daily_limit(r.text) if r.status_code == 429 else None
            if wait:
                _quota_until = time.time() + wait
                log.warning("Gemini daily voice limit reached - voice paused for %.1f h", wait / 3600)
                raise VoiceError("Rate limit: VERONICA's daily voice limit (Gemini free tier) is used up.")
            if r.status_code not in BUSY and r.status_code != 404:
                raise VoiceError(f"Gemini error {last}")       # real error (bad key, bad request): stop
            log.warning("Gemini busy/unavailable (%s), %s", last, "retrying" if attempt < tries - 1 else "next model")
            if r.status_code == 404:
                break                                         # model name not available: next model
            time.sleep(0.8 * (attempt + 1))
    raise VoiceError("Voice service is busy right now, please try again in a minute. (" + last + ")")


def _outputs(resp: dict, kind: str) -> list[dict]:
    out = []
    for step in resp.get("steps") or []:
        if step.get("type") == "model_output":
            if step.get("error"):
                raise VoiceError(f"Gemini: {step['error']}")
            out += [c for c in step.get("content") or [] if c.get("type") == kind]
    if not out:   # convenience fields on the Interaction object
        if kind == "audio" and isinstance(resp.get("output_audio"), dict):
            out = [resp["output_audio"]]
        elif kind == "text" and resp.get("output_text"):
            out = [{"type": "text", "text": resp["output_text"]}]
    return out


def TTS_MODELS() -> list[str]:
    if config.VOICE_STRICT:      # one model only: a different TTS model = a different sounding voice
        return _models(config.GEMINI_TTS_MODEL.split(",")[0], ())
    return _models(config.GEMINI_TTS_MODEL, ("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"))


def STT_MODELS() -> list[str]:
    return _models(config.GEMINI_STT_MODEL, ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite",
                                            "gemini-3.1-flash-lite"))


def tts_body(text: str, lang: str, fmt: str) -> dict:
    return {
        "model": TTS_MODELS()[0],
        "input": [{"type": "user_input", "content": [{
            "type": "text", "text": text,
            "annotations": [{"type": "speech_metadata",
                             "style": DIALECT.get(lang, "") + config.VOICE_STYLE}],
        }]}],
        "response_format": {"type": "audio", "mime_type": fmt},
        "generation_config": {"speech_config": [{"voice": config.GEMINI_VOICE, "language": TTS_CODE.get(lang, lang)}]},
        "stream": False,
    }


def _gemini_speak(say: str, lang: str, fmt: str) -> bytes:
    key = hashlib.sha1(f"{TTS_MODELS()[0]}|{config.GEMINI_VOICE}|{config.VOICE_STYLE}|{lang}|{fmt}|{say}"
                       .encode()).hexdigest()
    cache = config.OUTPUT_DIR / "tts" / f"{key}.{'ogg' if 'ogg' in fmt else 'mp3'}"
    if cache.exists():
        return cache.read_bytes()
    parts = _outputs(_post(tts_body(say, lang, fmt), TTS_MODELS()), "audio")
    if not parts or not parts[-1].get("data"):
        raise VoiceError("Gemini returned no audio.")
    audio = base64.b64decode(parts[-1]["data"])
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(audio)
    return audio


def gemini_paused() -> bool:
    """True while Gemini's daily voice limit is used up (the offline backup voice is speaking)."""
    return time.time() < _quota_until


def _kokoro_speak(say: str, lang: str, fmt: str) -> bytes:
    from . import local_tts
    key = hashlib.sha1(f"kokoro|{config.KOKORO_VOICE}|{config.KOKORO_SPEED}|{lang}|{fmt}|{say}".encode()).hexdigest()
    cache = config.OUTPUT_DIR / "tts" / f"{key}.{'ogg' if 'ogg' in fmt else 'mp3'}"
    if cache.exists():
        return cache.read_bytes()
    audio = local_tts.synth(say, lang, fmt)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(audio)
    return audio


def speak(text: str, lang: str | None = None, fmt: str = "audio/mp3", engine: str | None = None) -> bytes:
    """fmt: audio/mp3 (web) or audio/ogg_opus (Telegram voice note). Results are cached.
    Order (TTS_ENGINE=auto): her Gemini voice first; when Gemini can't (daily limit, busy, no key) the free
    offline Kokoro voice answers instead. TTS_ENGINE=kokoro puts Kokoro first. engine="gemini" = Gemini only."""
    from . import local_tts
    say = spoken_text(text)
    if not say:
        raise VoiceError("Nothing to say.")
    lang = detect_lang(say, lang)
    kok = engine != "gemini" and local_tts.available() and local_tts.handles(say)
    if kok and (config.TTS_ENGINE == "kokoro" or not config.GEMINI_API_KEY):
        try:
            return _kokoro_speak(say, lang, fmt)
        except Exception as e:
            log.warning("Kokoro voice failed (%s) - trying Gemini", e)
    if not config.GEMINI_API_KEY:
        raise VoiceError("Voice is not available for this text.")
    try:
        return _gemini_speak(say, lang, fmt)
    except VoiceError as e:
        if not kok or config.TTS_ENGINE == "kokoro":
            raise
        log.info("Gemini voice unavailable (%s) - using the free offline voice", str(e)[:80])
        try:
            return _kokoro_speak(say, lang, fmt)
        except Exception as e2:
            log.warning("Kokoro voice failed too: %s", e2)
            raise e


def stt_body(audio: bytes, mime: str) -> dict:
    return {
        "model": STT_MODELS()[0],
        "input": [{"type": "user_input", "content": [
            {"type": "text", "text": (
                "Transcribe this voice message exactly as spoken. The speaker may use English, Hindi, "
                "Gujarati, Marathi, Rajasthani/Marwari, Odia or a mix (Hinglish). Keep each word in the script it "
                "was spoken in (Hindi/Marathi/Rajasthani in Devanagari, Gujarati in Gujarati script, Odia in Odia "
                "script, English words in Latin). "
                "Keep numbers, report names and codes like /daily_sales as said. Return ONLY the text.")},
            {"type": "audio", "data": base64.b64encode(audio).decode(), "mime_type": mime},
        ]}],
        "stream": False,
    }


def transcribe(audio: bytes, mime: str) -> str:
    mime = (mime or "audio/webm").split(";")[0].strip().lower()
    mime = {"audio/x-m4a": "audio/m4a", "audio/mp4": "audio/m4a", "audio/oga": "audio/ogg",
            "video/webm": "audio/webm"}.get(mime, mime)
    if len(audio) > 15 * 1024 * 1024:
        raise VoiceError("Voice message too long.")
    texts = _outputs(_post(stt_body(audio, mime), STT_MODELS()), "text")
    return " ".join(t.get("text", "") for t in texts).strip()


def list_voices(language_code: str = "hi-IN", gender: str = "female") -> list[dict]:
    """Gemini voice library, e.g. to pick an Indian female voice for GEMINI_VOICE."""
    r = _http.get("https://generativelanguage.googleapis.com/v1beta/voices",
                  params={"language_code": language_code, "gender": gender},
                  headers={"x-goog-api-key": config.GEMINI_API_KEY})
    r.raise_for_status()
    return r.json().get("voices", [])
