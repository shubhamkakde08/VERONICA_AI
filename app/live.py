"""Gemini Live voice: real-time, interruptible conversation with VERONICA.

Browser  <-- WebSocket (/api/live) -->  this server  <-- Gemini Live (SDK) -->  Google

* Audio streams both ways (16 kHz PCM up, 24 kHz PCM down), so she answers in about a second.
* Gemini only talks. For any company number it calls a tool; the tools run our Claude agent on MySQL
  (same rules, skills, roles and read-only safety as the chat), or read the latest saved KPIs.
* The Gemini key never leaves the server.

Browser -> server messages: {"type":"audio","data":<b64 pcm16 16k>} | {"type":"text","text":...} | {"type":"end"}
Server -> browser messages: ready | audio | heard | said | interrupted | turn | tool | report | error
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

import re

from . import agent, config, store, voice

log = logging.getLogger("veronica.live")

LANG_NAMES = {"en-IN": "English (India)", "hi-IN": "Hindi", "gu-IN": "Gujarati", "mr-IN": "Marathi",
              "or-IN": "Odia", "raj-IN": "Rajasthani (Marwari)"}
LEGACY = ("gemini-3.1-flash-live", "gemini-2.5-flash-native-audio")   # no background tools on these


def live_models() -> list[str]:
    out = []
    for m in [x.strip() for x in config.GEMINI_LIVE_MODEL.split(",")] + ["gemini-3.8-live", "gemini-3.1-flash-live-preview"]:
        if m and m not in out:
            out.append(m)
    return out


LANGUAGE_RULES = """LANGUAGE (most important):
- Detect the language of EVERY user turn and answer in exactly that language and dialect, with natural native pronunciation:
  English (Indian English), Hindi, Hinglish (Hindi in English words - answer in Hinglish), Marathi, Gujarati,
  Rajasthani / Marwari (use Rajasthani words and grammar: "mhain", "thaane", "kai", "ghano", "padsi", "hai/ho" -
  not plain Hindi), Odia (proper Odia, not Bengali or Hindi). If the user switches language, you switch too.
- You are a WOMAN. Always use feminine first-person forms:
  Hindi "main dekh rahi hoon, maine check kiya, main bata sakti hoon"; Marathi "mi baghte, mi sangte, mi keli";
  Gujarati "hu joi rahi chhu, me check karyu"; Rajasthani "mhain dekh rai hoon, mhain bata sakoon";
  Odia natural polite forms ("mun dekhuchhi, mun kahibi").
- Pronounce like a native speaker of that language. Numbers: Indian system in the user's language
  (Hindi "chaar lakh bees hazaar", Marathi "chaar laakh", Gujarati "chaar laakh", Odia "chaari lakhya"; English "4.2 lakh").
  Say "percent" in English, "pratishat" or "percent" in Hindi/Marathi/Gujarati as people normally speak, "pratishata" in Odia.
  Units: MT = "metric ton", kg = "kilo". Codes/grades: OD = "O D", WT = "W T", 304L = "three-oh-four L", 316 = "three sixteen".
  Dates spoken naturally ("23 October"). Never read symbols, brackets or table text aloud."""


def enabled() -> bool:
    return bool(config.GEMINI_API_KEY) and config.LIVE_ENABLED


# ------------------------------------------------------------------ tools Gemini may call
def tool_declarations(nonblocking: bool) -> list[dict]:
    beh = {"behavior": "NON_BLOCKING"} if nonblocking else {}
    return [
        {"name": "get_company_data", **beh,
         "description": ("Get ANY company figure or report from the live ERP database: production, scrap, "
                         "dispatch, orders, stock, sales, job cards, plants, comparisons, trends, taught /reports. "
                         "Always use this before saying a number. Takes 5-30 seconds; tell the user briefly "
                         "that you are checking. The full tables, KPI cards and files appear on screen."),
         "parameters": {"type": "object", "properties": {
             "question": {"type": "string", "description": "The user's request in their own words, with "
                          "period, plant and filters, e.g. 'pichhle mahine ka jobcardwise scrap, Hollow section'"}},
             "required": ["question"]}},
        {"name": "latest_numbers", **beh,
         "description": "Instant: the key numbers of the most recent reports already prepared today "
                        "(with time). Use for quick 'what was the last scrap %' style questions.",
         "parameters": {"type": "object", "properties": {}}},
        {"name": "list_reports",
         "description": "List the reports (skills) this user can ask for.",
         "parameters": {"type": "object", "properties": {}}},
    ]


def system_instruction(user: dict, lang: str) -> str:
    skills = ", ".join(s["title"] for s in store.list_skills(user)) or "none yet"
    return f"""You are {config.ASSISTANT_NAME}, the voice assistant of {config.COMPANY_NAME} (stainless steel pipes and tubes).
You are a warm, sincere, polite Indian WOMAN colleague with a soft female voice. Speak naturally and briefly, like a
real person on a call: 1-3 short sentences per turn, no lists, no markdown, no reading out tables.
The user is {user['name']}. Their preferred language is {LANG_NAMES.get(lang, 'English (India)')} - use it for your
greeting, then follow the language they actually speak.
{LANGUAGE_RULES}
NEVER guess or invent company numbers. For any figure, report or comparison call get_company_data (or latest_numbers
for the last prepared numbers). While it runs, say one short natural line in the user's language (e.g. "Ji, ek minute, main data dekh rahi hoon").
When the result arrives, speak the 1-3 most important points with rounded numbers (e.g. "about 4 lakh kg", "9.5 percent")
and mention that the details are on the screen. If numbers look bad, say it gently and give the reason from the data.
Reports this user has: {skills}. If asked what you can do, explain simply. Keep a calm, respectful tone ("aap", "ji")."""


def build_config(user: dict, lang: str, nonblocking: bool):
    from google.genai import types as t
    return t.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=t.SpeechConfig(
            voice_config=t.VoiceConfig(prebuilt_voice_config=t.PrebuiltVoiceConfig(voice_name=config.GEMINI_LIVE_VOICE)),
            **({"language_code": config.LIVE_LANGUAGE_CODE} if config.LIVE_LANGUAGE_CODE else {})),
        system_instruction=system_instruction(user, lang),
        tools=[t.Tool(function_declarations=[t.FunctionDeclaration(**d) for d in tool_declarations(nonblocking)])],
        input_audio_transcription=t.AudioTranscriptionConfig(),
        output_audio_transcription=t.AudioTranscriptionConfig(),
        realtime_input_config=t.RealtimeInputConfig(automatic_activity_detection=t.AutomaticActivityDetection(
            silence_duration_ms=config.LIVE_SILENCE_MS)),
        context_window_compression=t.ContextWindowCompressionConfig(sliding_window=t.SlidingWindow()),
    )


def _connect(user: dict, lang: str, nonblocking: bool, model: str | None = None):
    """Returns the SDK's async context manager (patched in tests)."""
    from google import genai
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    return client.aio.live.connect(model=model or live_models()[0], config=build_config(user, lang, nonblocking))


def _reply_json(r) -> dict:
    return {"text": r.text, "report_ids": r.report_ids, "tables": r.tables, "preview": r.preview, "kpis": r.kpis,
            "files": [{k: f[k] for k in ("format", "filename", "url")} for f in r.files]}


async def run_tool(name: str, args: dict, user: dict, ws: WebSocket) -> dict:
    t0 = time.time()
    await ws.send_json({"type": "tool", "name": name, "status": "running", "args": args})
    try:
        if name == "get_company_data":
            q = str(args.get("question") or "").strip()[:2000]
            reply = await run_in_threadpool(agent.handle_message, user, q, "web", f"web:{user['id']}",
                                            user.get("telegram_id") or "", True, True)
            await ws.send_json({"type": "report", "question": q, "reply": _reply_json(reply)})
            out = {"answer": reply.text[:1500], "key_numbers": reply.kpis[:8],
                   "files_on_screen": [f["format"] for f in reply.files], "report_ids": reply.report_ids}
        elif name == "latest_numbers":
            panels = []
            for r in store.search_reports(user, limit=20, include_preview=True):
                dp = r.get("data_preview") or []
                k = dp[0].get("kpis") if dp and isinstance(dp[0], dict) else None
                if k:
                    panels.append({"report": r["title"], "prepared_at": config.ist(r["created_at"]), "numbers": k[:6]})
                if len(panels) >= 3:
                    break
            out = {"latest": panels} if panels else {"latest": [], "note": "No report prepared yet - use get_company_data."}
        elif name == "list_reports":
            out = {"reports": [{"command": "/" + s["name"], "title": s["title"]} for s in store.list_skills(user)]}
        else:
            out = {"error": f"unknown tool {name}"}
    except Exception as e:
        log.exception("live tool failed")
        out = {"error": f"{type(e).__name__}: {str(e)[:300]}"}
    ms = int((time.time() - t0) * 1000)
    await ws.send_json({"type": "tool", "name": name, "status": "error" if "error" in out else "done", "ms": ms})
    log.info("timing live tool %s %.1fs", name, ms / 1000)
    return out


async def bridge(ws: WebSocket, user: dict, lang: str) -> None:
    from google.genai import types as t
    lang = lang if lang in LANG_NAMES else "en-IN"
    cm = session = None
    model_used, last_err = "", ""
    for model in live_models():
        tries = [True, False] if (config.LIVE_NONBLOCKING and not model.startswith(LEGACY)) else [False]
        for nb in tries:
            try:
                cm = _connect(user, lang, nb, model)
                session = await cm.__aenter__()
                nonblocking, model_used = nb, model
                break
            except Exception as e:
                last_err = str(e)[:200]
                log.warning("live connect %s (nonblocking=%s) failed: %s", model, nb, e)
                cm = session = None
        if session is not None:
            break
    if session is None:
        await ws.send_json({"type": "error", "message": f"Live voice unavailable: {last_err}"})
        return
    log.info("live connected model=%s voice=%s nonblocking=%s", model_used, config.GEMINI_LIVE_VOICE, nonblocking)
    tts = config.LIVE_VOICE_MODE == "tts"
    await ws.send_json({"type": "ready", "model": model_used,
                        "voice": (config.GEMINI_VOICE + " (same as chat)") if tts else config.GEMINI_LIVE_VOICE})
    pending: set[asyncio.Task] = set()

    # ---- "tts" voice mode: Live's own audio is dropped; her words are spoken with GEMINI_VOICE (Gemini TTS),
    # sentence by sentence. TTS runs in parallel, clips are sent in order.
    st = {"gen": 0, "buf": "", "last": None}

    async def speak_clip(text_: str, gen: int, prev):
        audio = None
        try:
            audio = await run_in_threadpool(voice.speak, text_, lang, "audio/mp3")
        except Exception as e:
            log.warning("live tts failed: %s", e)
        if prev is not None:
            try:
                await prev
            except Exception:
                pass
        if audio and gen == st["gen"]:
            await ws.send_json({"type": "clip", "mime": "audio/mp3", "data": base64.b64encode(audio).decode()})

    def queue_speech(text_: str):
        text_ = text_.strip()
        if not re.search(r"\w", text_):
            return
        task = asyncio.create_task(speak_clip(text_, st["gen"], st["last"]))
        st["last"] = task
        pending.add(task)
        task.add_done_callback(pending.discard)

    def feed(chunk: str, final: bool = False):
        st["buf"] += chunk
        while True:
            m = re.search(r"[.!?।॥]+[\"')\]]*\s", st["buf"])
            if not m and len(st["buf"]) > 180:            # very long sentence: cut at a comma
                cut = st["buf"].rfind(",", 0, 180)
                m = re.match(r".{%d}" % (cut + 1), st["buf"], re.S) if cut > 40 else None
            if not m:
                break
            queue_speech(st["buf"][: m.end()]); st["buf"] = st["buf"][m.end():]
        if final:
            queue_speech(st["buf"]); st["buf"] = ""

    async def answer_tool(fc):
        result = await run_tool(fc.name, dict(fc.args or {}), user, ws)
        resp = t.FunctionResponse(id=fc.id, name=fc.name, response=result,
                                  **({"scheduling": t.FunctionResponseScheduling.WHEN_IDLE} if nonblocking else {}))
        await session.send_tool_response(function_responses=[resp])

    async def upstream():
        while True:
            msg = await ws.receive_json()
            kind = msg.get("type")
            if kind == "audio" and msg.get("data"):
                await session.send_realtime_input(audio=t.Blob(data=base64.b64decode(msg["data"]),
                                                               mime_type="audio/pcm;rate=16000"))
            elif kind == "text" and msg.get("text"):
                await session.send_realtime_input(text=str(msg["text"])[:2000])
            elif kind == "end":
                return

    async def downstream():
        while True:
            async for m in session.receive():
                sc = getattr(m, "server_content", None)
                if sc:
                    if sc.model_turn and sc.model_turn.parts and not tts:
                        for p in sc.model_turn.parts:
                            if p.inline_data and p.inline_data.data:
                                await ws.send_json({"type": "audio",
                                                    "data": base64.b64encode(p.inline_data.data).decode()})
                    if sc.input_transcription and sc.input_transcription.text:
                        await ws.send_json({"type": "heard", "text": sc.input_transcription.text})
                    if sc.output_transcription and sc.output_transcription.text:
                        await ws.send_json({"type": "said", "text": sc.output_transcription.text})
                        if tts:
                            feed(sc.output_transcription.text)
                    if sc.interrupted:
                        st["gen"] += 1; st["buf"] = ""; st["last"] = None
                        await ws.send_json({"type": "interrupted"})
                    if sc.turn_complete:
                        if tts:
                            feed("", final=True)
                        await ws.send_json({"type": "turn"})
                tc = getattr(m, "tool_call", None)
                if tc and tc.function_calls:
                    for fc in tc.function_calls:
                        task = asyncio.create_task(answer_tool(fc))
                        pending.add(task)
                        task.add_done_callback(pending.discard)

    up = asyncio.create_task(upstream())
    down = asyncio.create_task(downstream())
    try:
        done, _ = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
        for d in done:
            if d.exception() and not isinstance(d.exception(), WebSocketDisconnect):
                log.warning("live session ended: %r", d.exception())
                try:
                    await ws.send_json({"type": "error", "message": "Voice connection ended - tap Talk to reconnect."})
                except Exception:
                    pass
    finally:
        for task in (up, down, *pending):
            task.cancel()
        try:
            await cm.__aexit__(None, None, None)
        except Exception:
            pass
