"""Shared speech cache keys and bounded request pacing (no audio playback)."""
import hashlib
import json
import logging
import os
import tempfile
import threading
import time


def commentary_cache_dir():
    return os.path.join(tempfile.gettempdir(), "timerauto_tts_cache")


def commentary_cache_path(text, role, voice, rate, volume, pitch, *, directory=None):
    # Preserve the existing live-commentary cache keys, including prosody.
    blob = json.dumps({"text": str(text or ""), "role": str(role or ""),
        "voice": str(voice or ""), "rate": int(rate),
        "volume": round(float(volume), 1), "pitch": int(pitch)},
        ensure_ascii=False, sort_keys=True)
    suffix = ".wav" if str(voice).startswith("rfc-qwen3:") else ".mp3"
    return os.path.join(directory or commentary_cache_dir(), hashlib.sha1(blob.encode("utf-8")).hexdigest() + suffix)


def is_cached_commentary(path):
    return os.path.dirname(os.path.abspath(str(path))) == os.path.abspath(commentary_cache_dir())


class SpeechRequestGate:
    """All app runners/prewarm/tests share one network lane, not one per voice.

    Cache lookup belongs inside the lane too, so a waiting test can reuse a
    file that a prewarm worker has just finished. Retry 429 once, respecting
    Retry-After; never spin or block the Qt/UI thread.
    """
    def __init__(self, interval=1.25, *, clock=time.monotonic, sleep=time.sleep):
        self._lock = threading.Lock()
        self._clock, self._sleep = clock, sleep
        self._interval = float(interval)
        self._next_request = 0.0
        self._blocked_until = 0.0

    def run(self, operation, *, cached=lambda: False, timeout=12.0):
        deadline = self._clock() + float(timeout)
        if not self._lock.acquire(timeout=max(0.0, float(timeout))):
            raise TimeoutError("speech queue busy")
        try:
            if cached():
                return True
            for attempt in range(2):
                now = self._clock()
                wait = max(0.0, self._next_request - now, self._blocked_until - now)
                if now + wait >= deadline:
                    raise TimeoutError("speech request cooldown")
                if wait:
                    self._sleep(wait)
                self._next_request = self._clock() + self._interval
                try:
                    return operation(max(0.01, deadline - self._clock()))
                except Exception as exc:
                    if getattr(exc, "status", None) != 429:
                        raise
                    headers = getattr(exc, "headers", None) or {}
                    try:
                        retry_after = max(2.0, float(headers.get("Retry-After", 2.0)))
                    except (ValueError, TypeError):
                        retry_after = 2.0
                    self._blocked_until = self._clock() + retry_after
                    logging.warning("TTS_SERVICE_RATE_LIMIT attempt=%s retry_after=%.1f", attempt + 1, retry_after)
                    # A long server cooldown is retained for future calls,
                    # but this caller must not hang for minutes waiting on it.
                    if attempt or self._blocked_until >= deadline:
                        raise
        finally:
            self._lock.release()


SPEECH_REQUESTS = SpeechRequestGate()
_ERROR = threading.local()


def set_speech_error(exc=None):
    status = getattr(exc, "status", None)
    if exc is None:
        message = ""
    elif getattr(exc, "speech_message", None):
        message = exc.speech_message
    elif status == 429:
        message = "Edge 음성 서버가 요청을 일시 제한했습니다(429). 잠시 후 다시 테스트해 주세요."
    elif status:
        message = f"Edge 음성 서버가 요청을 거절했습니다(HTTP {status})."
    elif isinstance(exc, TimeoutError):
        message = "음성 서버 응답 또는 요청 대기시간을 초과했습니다. 잠시 후 다시 테스트해 주세요."
    else:
        message = f"Edge 음성 생성에 실패했습니다({type(exc).__name__})."
    _ERROR.message = message
    return message


def last_speech_error():
    return getattr(_ERROR, "message", "") or "Edge TTS 음성 파일 생성 실패"
