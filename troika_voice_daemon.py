#!/usr/bin/env python3
"""
Troika Voice Daemon — всегда-слушающий голосовой режим Тройки на ПК (Windows).

Как на телефоне: постоянно слушает микрофон, по слову «тройка» принимает команду,
шлёт в локальный мозг (gateway) и отвечает голосом. Не зависит от Flutter-записи
(record_windows на Windows оказался хрупким) — весь звук идёт через Python.

Поток:
  микрофон (sounddevice) → энерго-VAD (реплика между паузами) → STT-прокси :8643
  (Groq Whisper) → если есть wake-word «тройка» → команда в gateway :8642
  → ответ → TTS (pyttsx3, офлайн Windows-голос).

Запуск:  python troika_voice_daemon.py
Требует поднятых: gateway (:8642) и stt_proxy (:8643).
"""

from __future__ import annotations

import io
import os
import re
import sys
import json
import secrets
import time
import wave
import queue
import urllib.request

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

# ── Конфиг ──────────────────────────────────────────────────────────────────
GATEWAY = os.getenv("TROIKA_GATEWAY", "http://127.0.0.1:8642")
STT_URL = os.getenv("TROIKA_STT", "http://127.0.0.1:8643") + "/v1/audio/transcriptions"
API_KEY = os.getenv("API_SERVER_KEY", "").strip()
# Per-user identifiers can be supplied by a launcher to preserve history across
# restarts.  They must never fall back to a shared identity.
SESSION_KEY = os.getenv("TROIKA_SESSION_KEY", "").strip() or f"desktop-{secrets.token_urlsafe(24)}"
SESSION_ID = os.getenv("TROIKA_SESSION_ID", "").strip() or SESSION_KEY

STT_RATE = 16000               # частота, которую ждёт Whisper
CAP_RATE = 48000               # частота захвата (уточняется по устройству)
SILENCE_HANGOVER = 0.8         # сек тишины = конец реплики
MIN_SPEECH = 0.35              # мин длина реплики, сек
MAX_UTTERANCE = 15.0           # макс длина реплики, сек

WAKE_WORDS = ("тройка", "троика", "тройк", "troika")

_q: "queue.Queue[np.ndarray]" = queue.Queue()


try:  # консоль/редирект на Windows часто cp1251 — принудительно UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def log(*a):
    print("[voice]", *a, flush=True)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}


# ── TTS (офлайн, pyttsx3 → Windows SAPI) ────────────────────────────────────
class Speaker:
    def __init__(self):
        import pyttsx3
        self.eng = pyttsx3.init()
        self.eng.setProperty("rate", 185)
        # выбрать русский голос, если установлен
        for v in self.eng.getProperty("voices"):
            name = (getattr(v, "name", "") or "").lower()
            langs = str(getattr(v, "languages", "")).lower()
            if "russ" in name or "irina" in name or "ru" in langs or "рус" in name:
                self.eng.setProperty("voice", v.id)
                log("TTS voice:", v.name)
                break

    def say(self, text: str):
        if not text.strip():
            return
        self.eng.say(text)
        self.eng.runAndWait()


# ── Аудио-колбэк ────────────────────────────────────────────────────────────
def _audio_cb(indata, frames, time_info, status):
    if status:
        pass
    _q.put(indata[:, 0].copy())


def _rms(x: np.ndarray) -> float:
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))


def _calibrate(seconds=1.2) -> float:
    """Измерить фоновый шум и вернуть порог начала речи."""
    log("калибровка тишины…")
    vals = []
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            frame = _q.get(timeout=1.0)
            vals.append(_rms(frame))
        except queue.Empty:
            break
    base = np.median(vals) if vals else 60.0
    thr = max(base * 3.0, base + 120.0, 220.0)
    log(f"фон≈{base:.0f} → порог≈{thr:.0f}")
    return thr


def _to_16k(samples: np.ndarray) -> np.ndarray:
    """Ресемпл захваченного звука (CAP_RATE) → 16 кГц для Whisper."""
    if CAP_RATE == STT_RATE:
        return samples.astype(np.int16)
    from math import gcd
    g = gcd(CAP_RATE, STT_RATE)
    up, down = STT_RATE // g, CAP_RATE // g
    out = resample_poly(samples.astype(np.float64), up, down)
    return np.clip(out, -32768, 32767).astype(np.int16)


def _wav_bytes(samples16k: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(STT_RATE)
        w.writeframes(samples16k.astype(np.int16).tobytes())
    return buf.getvalue()


def transcribe(samples: np.ndarray) -> str:
    """Отправить реплику на STT-прокси, вернуть текст."""
    wav = _wav_bytes(_to_16k(samples))
    boundary = "----troikavoice"
    body = io.BytesIO()
    def w(s): body.write(s if isinstance(s, bytes) else s.encode("utf-8"))
    w(f"--{boundary}\r\n")
    w('Content-Disposition: form-data; name="language"\r\n\r\nru\r\n')
    w(f"--{boundary}\r\n")
    w('Content-Disposition: form-data; name="file"; filename="voice.wav"\r\n')
    w("Content-Type: audio/wav\r\n\r\n")
    w(wav); w("\r\n")
    w(f"--{boundary}--\r\n")
    req = urllib.request.Request(
        STT_URL, data=body.getvalue(), method="POST",
        headers={**_auth_headers(),
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return (json.loads(r.read().decode("utf-8")).get("text") or "").strip()
    except Exception as e:
        log("STT ошибка:", str(e)[:120])
        return ""


_EMO = re.compile(r"\[emo:[^\]]*\]", re.I)


def ask_brain(text: str) -> str:
    body = json.dumps({"model": "hermes-agent",
                       "messages": [{"role": "user", "content": text}]}).encode("utf-8")
    req = urllib.request.Request(
        GATEWAY + "/v1/chat/completions", data=body, method="POST",
        headers={**_auth_headers(), "Content-Type": "application/json",
                 "X-Hermes-Session-Key": SESSION_KEY, "X-Hermes-Session-Id": SESSION_ID})
    try:
        r = urllib.request.urlopen(req, timeout=180)
        d = json.loads(r.read().decode("utf-8"))
        msg = d.get("choices", [{}])[0].get("message", {}).get("content", "")
        return _EMO.sub("", msg).strip()
    except Exception as e:
        log("мозг ошибка:", str(e)[:120])
        return "Не получилось связаться с мозгом."


def strip_wake(text: str) -> str | None:
    """Если в тексте есть wake-word — вернуть команду после него (или '')."""
    low = text.lower()
    for w in WAKE_WORDS:
        i = low.find(w)
        if i != -1:
            after = text[i + len(w):].lstrip(" ,.!—- ")
            return after
    return None


def _open_stream():
    """Открыть входной поток надёжно, перебирая host-API и число каналов.

    WASAPI shared-mode требует нативное число каналов устройства (1 канал →
    'Invalid device'). Поэтому открываем со столькими каналами, сколько у
    устройства, а в колбэке берём канал 0.
    """
    global CAP_RATE
    # Приоритет host-API: WASAPI → DirectSound → MME.
    prefer = ["WASAPI", "DirectSound", "MME"]
    candidates = []  # (device_index_or_None,)
    try:
        hostapis = sd.query_hostapis()
        for name in prefer:
            for h in hostapis:
                if name in h["name"] and h["default_input_device"] >= 0:
                    candidates.append(h["default_input_device"])
    except Exception:
        pass
    candidates.append(None)  # дефолтное устройство ОС

    last_err = None
    seen = set()
    for dev in candidates:
        if dev in seen:
            continue
        seen.add(dev)
        try:
            idx = dev if dev is not None else sd.default.device[0]
            info = sd.query_devices(idx, "input")
            rate = int(info.get("default_samplerate") or 48000)
            ch = max(1, int(info.get("max_input_channels") or 1))
            ch = min(ch, 2)  # берём моно/стерео, канал 0 в колбэке
            stream = sd.InputStream(device=dev, samplerate=rate, channels=ch,
                                    dtype="int16", blocksize=0, callback=_audio_cb)
            stream.start()
            CAP_RATE = rate
            ha = sd.query_hostapis(info["hostapi"])["name"]
            log(f"мик: dev={dev} rate={rate} ch={ch} api={ha}")
            return stream
        except Exception as e:
            last_err = e
            log(f"мик dev={dev} не открылся: {str(e)[:70]}")
    raise RuntimeError(f"нет доступного микрофона: {last_err}")


def main():
    log(f"gateway={GATEWAY}  stt={STT_URL}")
    speaker = Speaker()
    stream = _open_stream()
    thr = _calibrate()

    speech: list[np.ndarray] = []
    speech_secs = 0.0
    silence_secs = 0.0
    in_speech = False
    awaiting_command = False  # сказали «тройка», ждём следующую фразу-команду

    log("слушаю… (скажи «Тройка …»)")
    _dbg_max = 0.0
    _dbg_t = time.time()
    while True:
        try:
            frame = _q.get(timeout=1.0)
        except queue.Empty:
            continue
        dur = len(frame) / CAP_RATE
        level = _rms(frame)

        # DEBUG: раз в секунду печатаем пиковый уровень — видно, ловит ли мик голос
        _dbg_max = max(_dbg_max, level)
        if time.time() - _dbg_t >= 1.0:
            log(f"[уровень] пик={_dbg_max:.0f} (порог={thr:.0f})")
            _dbg_max = 0.0
            _dbg_t = time.time()

        if level >= thr:
            in_speech = True
            silence_secs = 0.0
            speech.append(frame)
            speech_secs += dur
            if speech_secs > MAX_UTTERANCE:
                silence_secs = SILENCE_HANGOVER  # форсим финализацию
        elif in_speech:
            speech.append(frame)
            silence_secs += dur

        # конец реплики
        if in_speech and silence_secs >= SILENCE_HANGOVER:
            utt = np.concatenate(speech) if speech else np.array([], dtype=np.int16)
            got_secs = speech_secs
            speech = []
            in_speech = False
            speech_secs = 0.0
            silence_secs = 0.0
            if got_secs < MIN_SPEECH:
                continue

            text = transcribe(utt)
            if not text:
                continue
            log("услышал:", text)

            command = None
            if awaiting_command:
                command = text
                awaiting_command = False
            else:
                after = strip_wake(text)
                if after is None:
                    continue  # нет wake-word — игнор (чужой разговор)
                if after == "":
                    speaker.say("Слушаю")
                    awaiting_command = True
                    continue
                command = after

            if not command:
                continue
            log("команда:", command)
            reply = ask_brain(command)
            log("ответ:", reply[:160])
            speaker.say(reply)
            log("слушаю…")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
