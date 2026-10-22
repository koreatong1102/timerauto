"""Optional loopback Qwen client. No torch, model loading, or cloud fallback."""
import base64
import io
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave

PREFIX = "rfc-qwen3:"
MODELS = {size: f"Qwen/Qwen3-TTS-12Hz-{size}-CustomVoice" for size in ("0.6B", "1.7B")}
SPEAKERS = ("Sohee", "Ryan", "Aiden", "Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric", "Ono_Anna")
_LANE = threading.Lock()
MAX_AUDIO = 24 * 1024 * 1024


class LocalTTSError(RuntimeError):
    def __init__(self, message):
        super().__init__(message)
        self.speech_message = message


def is_local_voice(voice):
    return str(voice or "").startswith(PREFIX)


def request_options(voice, *, deadline=None, now=None):
    """Preview/report generation can wait; live requests retain their deadline.

    These limits change waiting, not inference speed. A stale live result must
    still never be played, even if the model completes after disconnection.
    """
    if not is_local_voice(voice):
        return {}
    remaining = 90. if deadline is None else deadline - (time.monotonic() if now is None else now)
    if remaining < .05:
        raise LocalTTSError("유효시간이 지난 Qwen 실시간 합성 요청을 생략합니다.")
    return {"local_timeout": max(.05, min(90., remaining))}


def settings(cfg, role):
    role = "caster" if role == "caster" else "analyst"
    size = str(getattr(cfg, "spectator_qwen_model", "1.7B"))
    if size not in MODELS:
        size = "1.7B"
    port = max(1024, min(65535, int(getattr(cfg, "spectator_qwen_port", 8768))))
    speaker = str(getattr(cfg, f"spectator_qwen_{role}_speaker", "Sohee" if role == "caster" else "Ryan"))
    if speaker not in SPEAKERS:
        speaker = "Sohee" if role == "caster" else "Ryan"
    instruction = str(getattr(cfg, f"spectator_qwen_{role}_instruction", "") or "")[:500]
    return {"port": port, "model": MODELS[size], "speaker": speaker,
            "language": str(getattr(cfg, "spectator_qwen_language", "Korean")),
            "instruction": instruction if size == "1.7B" else "",
            "speed": max(.7, min(1.5, float(getattr(cfg, "spectator_qwen_speed", 1.0))))}


def commentary_voice(cfg, role, edge_voice):
    if is_local_voice(edge_voice):
        return edge_voice
    if getattr(cfg, "spectator_tts_engine", "edge") != "qwen3":
        return edge_voice  # Preserve every existing Edge cache identity.
    value = json.dumps(settings(cfg, role), sort_keys=True, ensure_ascii=False).encode("utf-8")
    return PREFIX + base64.urlsafe_b64encode(value).decode("ascii")


def decode_voice(voice):
    try:
        value = json.loads(base64.urlsafe_b64decode(str(voice)[len(PREFIX):]).decode("utf-8"))
        if value["model"] not in MODELS.values() or value["speaker"] not in SPEAKERS:
            raise ValueError("model or speaker")
        if not 1024 <= int(value["port"]) <= 65535:
            raise ValueError("port")
        return value
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise LocalTTSError("Qwen 음성 설정이 올바르지 않습니다. 설정을 다시 저장해 주세요.") from exc


def _request(port, path, *, payload=None, timeout=3):
    # Numeric loopback only, ignore system/OBS/VPN HTTP proxy settings. Never
    # forward local commentary text to another host through a redirect.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(f"http://127.0.0.1:{int(port)}{path}",
        data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-RFC-TTS": "1"})
    try:
        with opener.open(request, timeout=timeout) as response:
            data = response.read(MAX_AUDIO + 1)
            if len(data) > MAX_AUDIO:
                raise LocalTTSError("Qwen 응답이 너무 큽니다. 문장을 짧게 나눠 주세요.")
            return data
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read(4096))
            detail = body.get("error", "") if isinstance(body, dict) else ""
        except (ValueError, TypeError):
            detail = ""
        finally:
            exc.close()
        raise LocalTTSError(f"Qwen 로컬 서버 오류({exc.code}): {str(detail)[:220]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LocalTTSError("Qwen 로컬 서버에 연결하지 못했거나 응답 시간이 초과됐습니다. Qwen_서버실행.bat와 포트를 확인해 주세요.") from exc


def check_server(cfg):
    options = settings(cfg, "caster")
    try:
        info = json.loads(_request(options["port"], "/health"))
    except (ValueError, UnicodeError) as exc:
        raise LocalTTSError("해당 포트의 응답이 Qwen 서버 형식이 아닙니다.") from exc
    if not isinstance(info, dict) or info.get("service") != "rfc-qwen3" or info.get("model") != options["model"]:
        raise LocalTTSError("서버 모델과 설정 모델이 다릅니다. 0.6B / 1.7B 선택을 맞춰 주세요.")
    if not info.get("ready"):
        raise LocalTTSError("Qwen 모델을 준비 중입니다. 서버 창에서 준비 완료 후 다시 확인해 주세요.")
    return info


def save_local(text, path, voice, *, volume="+0%", timeout=90.):
    options = decode_voice(voice)
    if not _LANE.acquire(timeout=.1):
        raise LocalTTSError("Qwen이 이전 음성을 생성 중입니다. 오래된 콜을 쌓지 않고 생략합니다.")
    staged = ""
    try:
        if os.path.isfile(path) and os.path.getsize(path) > 44:
            return True
        text = str(text or "").strip()
        if not text or len(text) > 1200:
            raise LocalTTSError("Qwen 문장은 1~1200자로 입력해 주세요.")
        gain = max(0., min(1., 1 + float(str(volume).rstrip("%")) / 100.))
        audio = _request(options["port"], "/synthesize", payload={**options, "text": text, "gain": gain},
                         timeout=max(.05, min(90., float(timeout))))
        try:
            with wave.open(io.BytesIO(audio), "rb") as wav:
                if wav.getsampwidth() != 2 or wav.getnchannels() != 1 or not 8000 <= wav.getframerate() <= 96000 or wav.getnframes() < 1:
                    raise ValueError("unsupported WAV")
                if len(wav.readframes(wav.getnframes())) != wav.getnframes() * 2:
                    raise ValueError("truncated WAV")
        except (wave.Error, EOFError, ValueError) as exc:
            raise LocalTTSError("Qwen 서버에서 정상적인 PCM WAV 음성을 받지 못했습니다.") from exc
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        fd, staged = tempfile.mkstemp(prefix="qwen_", suffix=".wav", dir=directory)
        with os.fdopen(fd, "wb") as stream:
            stream.write(audio)
        os.replace(staged, path)
        staged = ""
        return True
    finally:
        if staged:
            try:
                os.remove(staged)
            except OSError:
                pass
        _LANE.release()
