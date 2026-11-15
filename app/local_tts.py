"""Free, unlimited, offline voice for VERONICA: Kokoro TTS (Apache-2.0) running on this PC.

No internet, no quota, text never leaves the machine. Installed by INSTALL_FREE_VOICE.bat:
  models/kokoro/kokoro-v1.0.int8.onnx + voices-v1.0.bin  and the pip packages kokoro-onnx + soundfile.
English and Hindi (Devanagari) are spoken here; scripts Kokoro can't read (Gujarati, Odia) go to Gemini.
"""
from __future__ import annotations

import io
import logging
import re
import threading

from . import config

log = logging.getLogger("veronica.voice")
_lock = threading.Lock()
_speak_lock = threading.Lock()
_engine = None
_failed = ""


def _paths():
    d = config.KOKORO_DIR
    model = next((p for p in (d / "kokoro-v1.0.int8.onnx", d / "kokoro-v1.0.fp16.onnx", d / "kokoro-v1.0.onnx") if p.is_file()), None)
    return model, d / "voices-v1.0.bin"


def available() -> bool:
    if config.TTS_ENGINE == "gemini" or _failed:
        return False
    model, voices = _paths()
    if not model or not voices.is_file():
        return False
    try:
        import kokoro_onnx  # noqa: F401
        import soundfile  # noqa: F401
    except Exception:
        return False
    return True


def _get():
    global _engine, _failed
    if _engine is None:
        with _lock:
            if _engine is None:
                try:
                    import onnxruntime as rt
                    from kokoro_onnx import Kokoro
                    model, voices = _paths()
                    so = rt.SessionOptions()                 # leave CPU for the server: the voice uses at most 2 cores
                    so.intra_op_num_threads = config.KOKORO_THREADS
                    so.inter_op_num_threads = 1
                    _engine = Kokoro.from_session(rt.InferenceSession(str(model), sess_options=so, providers=["CPUExecutionProvider"]), str(voices))
                    log.info("Kokoro voice ready (%s, voice %s)", model.name, config.KOKORO_VOICE)
                except Exception as e:                      # broken install: fall back to Gemini from now on
                    _failed = str(e)
                    log.warning("Kokoro could not start: %s", e)
                    raise
    return _engine


def warm():
    """Load the model in the background at start-up so the first answer speaks quickly."""
    if available():
        threading.Thread(target=lambda: _safe(lambda: synth("Ready.", "en-IN", "audio/mp3")), daemon=True).start()


def _safe(fn):
    try:
        fn()
    except Exception:
        pass


def handles(text: str) -> bool:
    return not re.search(r"[઀-૿଀-୿]", text)   # Gujarati / Odia scripts -> Gemini


def short(text: str) -> str:
    """The offline voice is slow on this PC (~1 s per 5 characters): speak only the first sentences, up to KOKORO_MAX_CHARS."""
    n = config.KOKORO_MAX_CHARS
    if len(text) <= n:
        return text
    cut = max(text.rfind(c, 0, n) for c in ".!?।\n")
    return text[:cut + 1] if cut > 40 else text[:n].rsplit(" ", 1)[0] + "…"


def synth(text: str, lang: str, fmt: str = "audio/mp3") -> bytes:
    import soundfile as sf
    k = _get()
    kl = "hi" if re.search(r"[ऀ-ॿ]", text) else ("en-gb" if config.KOKORO_VOICE.startswith("b") else "en-us")
    text = short(text)
    if not _speak_lock.acquire(timeout=2):                  # already speaking: skip instead of queueing minutes of CPU work
        raise RuntimeError("offline voice busy")
    try:
        audio, sr = k.create(text, voice=config.KOKORO_VOICE, speed=config.KOKORO_SPEED, lang=kl)
    finally:
        _speak_lock.release()
    buf = io.BytesIO()
    if "ogg" in fmt:
        sf.write(buf, audio, sr, format="OGG", subtype="OPUS")
    else:
        sf.write(buf, audio, sr, format="MP3")
    return buf.getvalue()
