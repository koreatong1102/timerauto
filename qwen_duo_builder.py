"""Isolated one-click Korean sports duo pack builder.

Run only with the optional Qwen Python runtime. The GUI imports this module
without importing torch, qwen_tts, numpy or any GPU dependency. Original voice
design references are reused; no real person's recordings or identity are used.
The active manifest is published only after the complete pack is verified.
"""
from __future__ import annotations

import argparse
from array import array
from contextlib import contextmanager
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import wave

from app_paths import app_path
from commentary_pack import build, catalog, clip_path, ready, line_delivery
from local_tts import commentary_voice


PROFILE_ID = "ko_sports_duo_v1"
PROFILE = PROFILE_ID
DESIGN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
CLONE_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
ROLES = ("caster", "analyst")
PERSONAS = {
    "caster": {
        "text": "자, 두 선수 준비됐습니다. 받아칩니다! 카운터에서 연타까지 이어가요. 바로 이 장면입니다!",
        "instruction": (
            "한국어를 모국어로 쓰는 30대 성인 남성의 독창적인 스포츠 캐스터 목소리. "
            "밝고 선명한 중음, 힘 있는 흉성, 명확한 한국어 발음과 자연스러운 서울말 억양. "
            "현장 중계처럼 빠르게 반응하지만 모든 음절을 분명하게 말한다. "
            "평범한 안내는 침착하게, 카운터와 연타 콜은 생동감 있게 강세를 준다. "
            "광고나 뉴스 낭독, 인위적인 저음, 외국어 억양, 과도한 비명은 피한다. "
            "어떤 실제 인물도 흉내 내지 않는 새로운 목소리. 제공된 문장만 읽는다."
        ),
    },
    "analyst": {
        "text": "타이밍을 정말 잘 잡았어요. 먼저 들어간 쪽이 오히려 맞았죠. 이거, 들어갈 때마다 입장료를 내네요.",
        "instruction": (
            "한국어를 모국어로 쓰는 40대 성인 남성의 독창적인 격투 스포츠 해설자 목소리. "
            "캐스터와 뚜렷하게 구별되는 묵직하고 살짝 거친 중저음. "
            "또렷한 한국어 발음과 자연스러운 서울말 구어체로 편안하게 설명한다. "
            "경기를 잘 아는 해설자가 옆 사람에게 이야기하듯 말하며, 마지막 농담은 "
            "과장된 웃음 없이 담백하고 재치 있게 살린다. 너무 느리거나 무겁게 끌지 않는다. "
            "기계적인 낭독과 외국어 억양은 피한다. 어떤 실제 인물도 흉내 내지 않는 "
            "새로운 목소리. 제공된 문장만 읽는다."
        ),
    },
}

# These are expressive reference passages spoken by the SAME cloned role,
# never a new VoiceDesign identity or an unsupported Base `instruct` argument.
# Their prosody can guide generation; exact emotion is not guaranteed.
DELIVERY_VERSION = 1
DELIVERY_TEXTS = {
    "caster": {
        "excited": "들어갑니다! 카운터! 받아치고 연타까지 이어가요! 와, 바로 이 장면입니다!",
        "surprised": "어, 이걸 받아칩니다! 이번엔 반대쪽이에요. 아, 타이밍이 정말 절묘했습니다!",
        "dry": "잠깐만요. 들어갈 때마다 맞고 돌아오네요. 오늘 입장료가 좀 비쌉니다.",
    },
    "analyst": {
        "excited": "와, 이건 제대로 들어갔어요! 받아친 다음에도 공격을 안 멈춥니다. 저 연결이 정말 좋았어요!",
        "surprised": "어? 이번엔 반대네요! 받아치던 쪽이 오히려 맞았어요. 방금은 저도 놀랐습니다!",
        "dry": "아니, 잠깐만요. 공격하러 갔는데 영수증은 본인이 받네요. 계산이 좀 이상한데요.",
    },
}


class Cancelled(Exception):
    pass


def profile_root():
    return Path(app_path(".qwen_duo_profiles", PROFILE_ID))


def _digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(256 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _json_read(path, *, limit=1024 * 1024):
    path = Path(path)
    if path.stat().st_size > limit:
        raise ValueError("설정 파일이 너무 큽니다.")
    with path.open(encoding="utf-8-sig") as stream:
        result = json.load(stream)
    if not isinstance(result, dict):
        raise ValueError("설정 파일 형식이 올바르지 않습니다.")
    return result


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix="duo_", suffix=".json", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _write_wave(path, samples, sample_rate, *, reference=False):
    """Publish complete PCM16 mono only; never leave a partial cache entry."""
    rate = int(sample_rate)
    if rate != sample_rate or not 8000 <= rate <= 96000:
        raise ValueError("음성 샘플레이트가 올바르지 않습니다.")
    # Qwen returns a flat numpy array. Keep that optional dependency out of the
    # GUI process and use the buffer-independent representation here.
    values = samples.tolist() if hasattr(samples, "tolist") else list(samples)
    minimum, maximum = (2.0, 45.0) if reference else (.08, 120.0)
    if not rate * minimum <= len(values) <= rate * maximum:
        raise ValueError("목소리 음성 길이가 비정상입니다. 기존 팩은 유지됩니다.")
    pcm = array("h")
    peak = 0.
    for sample in values:
        value = float(sample)
        if not math.isfinite(value):
            raise ValueError("모델이 비정상적인 음성을 반환했습니다.")
        peak = max(peak, abs(value))
        pcm.append(round(max(-1., min(1., value)) * 32767))
    if peak < .00001:
        raise ValueError("모델이 무음 파일을 반환했습니다.")
    if sys.byteorder != "little":
        pcm.byteswap()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix="duo_", suffix=".wav", dir=str(path.parent))
        os.close(fd)
        with wave.open(temporary, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(pcm.tobytes())
        if not ready(temporary):
            raise ValueError("생성된 WAV 파일 검증에 실패했습니다.")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


@contextmanager
def _exclusive(path):
    """Process lock released by the OS even after a crash; no stale PID lock."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    locked = False
    try:
        stream.seek(0, os.SEEK_END)
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise RuntimeError("한국어 남성 듀오 팩을 이미 제작 중입니다.") from exc
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


class Runtime:
    """One heavy model at a time, never in TimerAuto's GUI interpreter."""
    supports_delivery_references = True
    def __init__(self, device="auto"):
        import torch
        from qwen_tts import Qwen3TTSModel
        self.torch, self.factory = torch, Qwen3TTSModel
        torch.set_num_threads(2)
        self.device = ("cuda:0" if torch.cuda.is_available() else "cpu") if device == "auto" else device
        if self.device == "cuda:0" and not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU를 사용할 수 없습니다. Qwen 설치 상태를 확인해 주세요.")
        self.model = None

    def load(self, model_id):
        self.release()
        self.model = self.factory.from_pretrained(model_id, device_map=self.device,
            dtype=self.torch.float16 if self.device.startswith("cuda") else self.torch.float32,
            attn_implementation="sdpa")

    def design(self, role):
        with self.torch.inference_mode():
            wavs, rate = self.model.generate_voice_design(text=PERSONAS[role]["text"], language="Korean",
                instruct=PERSONAS[role]["instruction"], max_new_tokens=2048)
        return wavs[0], rate

    def prompt(self, role, reference):
        with self.torch.inference_mode():
            return self.model.create_voice_clone_prompt(ref_audio=str(reference),
                ref_text=PERSONAS[role]["text"], x_vector_only_mode=False)

    def delivery_prompt(self, reference, text):
        with self.torch.inference_mode():
            return self.model.create_voice_clone_prompt(ref_audio=str(reference),
                ref_text=text, x_vector_only_mode=False)

    def clone(self, text, prompt):
        with self.torch.inference_mode():
            wavs, rate = self.model.generate_voice_clone(text=text, language="Korean",
                voice_clone_prompt=prompt, max_new_tokens=2048)
        return wavs[0], rate

    def release(self):
        self.model = None
        gc.collect()
        if self.device.startswith("cuda"):
            self.torch.cuda.empty_cache()


class Cancellation:
    def __init__(self, path=None):
        self.path = Path(path) if path else None

    def is_set(self):
        return self.path is not None and self.path.exists()

    def check(self):
        if self.is_set():
            raise Cancelled("제작을 중지했습니다. 완성된 파일은 다음에 재사용합니다.")


def candidate_config(job):
    if not isinstance(job, dict):
        raise ValueError("제작 설정이 올바르지 않습니다.")
    raw = job.get("config", job)
    if not isinstance(raw, dict):
        raise ValueError("제작 설정이 올바르지 않습니다.")
    # Identity fields are fixed for this original duo. Live-mode slider changes
    # must not make a half-built pack look like a complete different voice.
    return SimpleNamespace(spectator_tts_engine="qwen3", spectator_tts_pack_enabled=True,
        spectator_tts_pack_auto_names=False, spectator_qwen_model="1.7B", spectator_qwen_language="Korean",
        spectator_qwen_port=max(1024, min(65535, int(raw.get("spectator_qwen_port", 8768)))),
        spectator_qwen_speed=1.0, spectator_qwen_caster_speaker="Sohee", spectator_qwen_analyst_speaker="Ryan",
        spectator_qwen_caster_instruction="", spectator_qwen_analyst_instruction="",
        spectator_qwen_duo_profile=PROFILE_ID, spectator_qwen_duo_revision="")


def _revision(references, signature):
    identity = {"signature": signature, "roles": references["roles"]}
    if references.get("deliveries"):
        identity["deliveries"] = references["deliveries"]
    return hashlib.sha256(json.dumps(identity,
        sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _delivery_signature():
    return hashlib.sha256(json.dumps({"version": DELIVERY_VERSION, "texts": DELIVERY_TEXTS},
        sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _deliveries_ready(root, references):
    metadata = references.get("deliveries") or {}
    if metadata.get("signature") != _delivery_signature():
        return False
    rows = metadata.get("roles") or {}
    for role, texts in DELIVERY_TEXTS.items():
        if (rows.get(role) or {}).get("source_sha256") != (references["roles"].get(role) or {}).get("sha256"):
            return False
        for delivery, text in texts.items():
            path = root / f"{role}_{delivery}_reference.wav"
            entry = (rows.get(role) or {}).get(delivery) or {}
            if not ready(path) or entry.get("text") != text or entry.get("sha256") != _digest(path):
                return False
    return True


def _prepare_deliveries(runtime, root, references, prompts, cancel, emit):
    metadata = references.get("deliveries") or {}
    if metadata.get("signature") != _delivery_signature():
        metadata = {"signature": _delivery_signature(), "version": DELIVERY_VERSION, "roles": {}}
    references["deliveries"] = metadata
    output = {(role, "neutral"): prompt for role, prompt in prompts.items()}
    for role, texts in DELIVERY_TEXTS.items():
        source_sha = (references["roles"].get(role) or {}).get("sha256")
        rows = metadata["roles"].get(role) or {}
        if rows.get("source_sha256") != source_sha:
            rows = {"source_sha256": source_sha}
            metadata["roles"][role] = rows
        for delivery, text in texts.items():
            cancel.check()
            path = root / f"{role}_{delivery}_reference.wav"
            prior = rows.get(delivery) or {}
            if not (ready(path) and prior.get("text") == text and prior.get("sha256") == _digest(path)):
                emit({"status": "progress", "done": 0, "total": 0,
                      "message": ("캐스터" if role == "caster" else "해설") + " 같은 목소리의 연기 기준 준비 · " + delivery})
                samples, rate = runtime.clone(text, prompts[role])
                cancel.check()
                _write_wave(path, samples, rate, reference=True)
                rows[delivery] = {"text": text, "sha256": _digest(path)}
                _atomic_json(root / "references.json", references)
            output[role, delivery] = runtime.delivery_prompt(path, text)
    return output


def _publish(cfg, root, revision, signature, result, emit):
    if any(not ready(clip_path(commentary_voice(cfg, role, ""), text)) for role, text in catalog("full")):
        raise RuntimeError("전체 음성 파일 검증에 실패했습니다. 기존 팩은 유지됩니다.")
    manifest = {"profile": PROFILE_ID, "revision": revision, "status": "complete",
                "design_model": DESIGN_MODEL, "clone_model": CLONE_MODEL,
                "reference_signature": signature, "done": result["done"], "total": result["total"]}
    _atomic_json(root / "manifest.json", manifest)
    final = {**result, "status": "complete", "profile": PROFILE_ID, "revision": revision,
             "message": "한국어 남성 캐스터·해설 전체 팩 제작 및 파일 검증을 완료했습니다."}
    emit(final)
    return final


def run_job(job, emit, *, cancel_file=None, runtime_factory=Runtime):
    """Build without activating user settings; the GUI commits only on success."""
    cfg = candidate_config(job)
    device = job.get("device", "auto")
    if device not in ("auto", "cpu", "cuda:0"):
        raise ValueError("지원되지 않는 장치입니다.")
    cancel = Cancellation(cancel_file)
    root = profile_root()
    root.mkdir(parents=True, exist_ok=True)
    signature = hashlib.sha256(json.dumps({"model": DESIGN_MODEL, "personas": PERSONAS},
        sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    delivery_supported = getattr(runtime_factory, "supports_delivery_references", False) is True
    with _exclusive(root / "build.lock"):
        cancel.check()
        try:
            references = _json_read(root / "references.json")
        except (OSError, ValueError):
            references = {}
        if references.get("signature") != signature:
            references = {"profile": PROFILE_ID, "signature": signature, "roles": {}}
        valid = {}
        for role in ROLES:
            path = root / (role + "_reference.wav")
            previous = (references.get("roles") or {}).get(role) or {}
            valid[role] = ready(path) and previous.get("sha256") == _digest(path)
        # Clicking again after completion verifies the files, but does not load
        # a several-GB model merely to rediscover that nothing needs synthesis.
        if all(valid.values()) and (not delivery_supported or _deliveries_ready(root, references)):
            revision = _revision(references, signature)
            cfg.spectator_qwen_duo_revision = revision
            rows = catalog("full")
            if rows and all(ready(clip_path(commentary_voice(cfg, role, ""), text)) for role, text in rows):
                cancel.check()
                return _publish(cfg, root, revision, signature,
                    {"complete": True, "done": len(rows), "total": len(rows), "generated": 0}, emit)
        runtime = None
        try:
            emit({"status": "progress", "done": 0, "total": 0,
                  "message": "Qwen 제작 환경 준비 · 처음에는 모델 다운로드에 수 GB가 필요할 수 있습니다."})
            runtime = runtime_factory(device)
            if runtime.device == "cpu":
                emit({"status": "progress", "done": 0, "total": 0,
                      "message": "CPU 제작 모드입니다. 전체 해설팩 완성에 오랜 시간이 걸릴 수 있습니다."})
            if not all(valid.values()):
                emit({"status": "progress", "done": 0, "total": 0, "message": "독창적인 한국어 남성 목소리 설계 모델 준비 중…"})
                runtime.load(DESIGN_MODEL)
                for role in ROLES:
                    cancel.check()
                    if valid[role]:
                        continue
                    label = "캐스터" if role == "caster" else "해설자"
                    emit({"status": "progress", "done": 0, "total": 0, "message": label + " 목소리 제작 중…"})
                    samples, rate = runtime.design(role)
                    cancel.check()
                    path = root / (role + "_reference.wav")
                    _write_wave(path, samples, rate, reference=True)
                    references["roles"][role] = {"sha256": _digest(path), "text": PERSONAS[role]["text"]}
                    _atomic_json(root / "references.json", references)
                # Never hold VoiceDesign and Base on the GPU together.
                runtime.release()
            cancel.check()
            emit({"status": "progress", "done": 0, "total": len(catalog("full")),
                  "message": "선택한 두 목소리로 전체 해설팩 제작 준비 중…"})
            runtime.load(CLONE_MODEL)
            prompts = {role: runtime.prompt(role, root / (role + "_reference.wav")) for role in ROLES}
            deliveries = (_prepare_deliveries(runtime, root, references, prompts, cancel, emit)
                          if delivery_supported else {})
            revision = _revision(references, signature)
            cfg.spectator_qwen_duo_revision = revision
            voices = {commentary_voice(cfg, role, ""): role for role in ROLES}
            if len(voices) != len(ROLES):
                raise RuntimeError("캐스터와 해설 목소리 식별자가 겹칩니다. 프로그램을 업데이트해 주세요.")
            def renderer(text, destination, voice):
                cancel.check()
                role = voices.get(voice)
                if role is None:
                    raise ValueError("알 수 없는 해설 목소리입니다.")
                prompt = deliveries.get((role, line_delivery(role, text)), prompts[role])
                samples, rate = runtime.clone(text, prompt)
                cancel.check()
                _write_wave(destination, samples, rate)
            def progress(done, total, role, text):
                emit({"status": "progress", "done": done, "total": total,
                      "message": ("캐스터" if role == "caster" else "해설") + ": " + text})
            result = build(cfg, "full", cancel=cancel, renderer=renderer, progress=progress)
            cancel.check()
            if not result.get("complete"):
                raise Cancelled("제작을 중지했습니다. 완성된 파일은 다음에 재사용합니다.")
            return _publish(cfg, root, revision, signature, result, emit)
        finally:
            if runtime is not None:
                runtime.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True)
    parser.add_argument("--progress", required=True)
    parser.add_argument("--cancel")
    args = parser.parse_args(argv)
    progress = Path(args.progress)
    progress.parent.mkdir(parents=True, exist_ok=True)
    def emit(event):
        with progress.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()
    os.environ.setdefault("HF_HOME", app_path(".qwen_models"))
    os.environ.setdefault("PYTHONUTF8", "1")
    try:
        run_job(_json_read(args.job), emit, cancel_file=args.cancel)
        return 0
    except Cancelled as exc:
        emit({"status": "cancelled", "message": str(exc)})
        return 2
    except Exception as exc:
        message = str(exc)
        if "out of memory" in message.lower():
            message = "GPU 메모리가 부족합니다. 방송과 다른 Qwen 서버를 종료한 뒤 이어 만들기를 실행해 주세요."
        emit({"status": "error", "message": message[:1000], "error_type": type(exc).__name__})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
