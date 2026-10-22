"""Persistent, authored voice packs. Runtime lookup never synthesizes speech.

Only exact full sentences or an explicitly supplied focus/name boundary may be
joined. No regex stripping, fabricated values, or arbitrary fragment assembly.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import wave

from app_paths import app_path
from local_tts import commentary_voice, decode_voice, save_local, LocalTTSError, PREFIX

_BUILD = threading.Lock()
_NAMES = threading.Lock()
_names_pending = []
_names_worker = False


def enabled(cfg):
    return getattr(cfg, "spectator_tts_engine", "edge") == "qwen3" and bool(getattr(cfg, "spectator_tts_pack_enabled", False))


def base_voice(voice):
    if not str(voice).startswith(PREFIX):
        return voice
    import base64
    options = decode_voice(voice)
    options.pop("pack", None)
    return PREFIX + base64.urlsafe_b64encode(json.dumps(options, sort_keys=True, ensure_ascii=False).encode("utf-8")).decode("ascii")


def root():
    return Path(app_path("commentary_voice_packs"))


def clip_path(voice, text, *, directory=None):
    options = decode_voice(base_voice(voice))
    options.pop("port", None)  # Changing a server port doesn't change its voice.
    identity = hashlib.sha256(json.dumps(options, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
    key = hashlib.sha256(str(text).encode("utf-8")).hexdigest()
    return Path(directory or root()) / identity / (key + ".wav")


def ready(path):
    try:
        with wave.open(str(path), "rb") as stream:
            return (stream.getnchannels() == 1 and stream.getsampwidth() == 2
                    and 8000 <= stream.getframerate() <= 96000 and stream.getnframes() > 0
                    and Path(path).stat().st_size >= 44 + stream.getnframes() * 2)
    except (OSError, wave.Error, EOFError):
        return False


def prepare_dialogue(cfg, role, dialogue, *, narration_only=False):
    if not enabled(cfg) or not dialogue or dialogue.get("continuation"):
        return dialogue
    packet = dict(dialogue)
    requested = dict(packet.get("pack_requested_focus") or packet.get("focus") or {})
    packet["pack_requested_focus"] = requested
    if narration_only:
        packet["pack_narration_only"] = True
        packet["focus"] = None  # No audible name: do not establish a spoken subject.
        return packet
    packet["focus"] = dict(requested)
    if requested.get("named") and requested.get("name") and requested.get("side") in ("blue", "red"):
        voice = commentary_voice(cfg, role, "")
        name = str(requested["name"])
        if not ready(clip_path(voice, name + "!")):
            corner = "블루 선수" if requested["side"] == "blue" else "레드 선수"
            # SpokenFocus must reflect the identifier actually heard, not an
            # unplayed nickname. This prevents unsafe later name omission.
            packet["focus"] = {**requested, "name": corner}
    return packet


def usage_voice(cfg, role, edge_voice, timing=None, dialogue=None):
    if (timing or {}).get("kind") == "report":
        return edge_voice
    voice = commentary_voice(cfg, role, edge_voice)
    if not enabled(cfg):
        return voice
    import base64
    options = decode_voice(voice)
    packet = dialogue or {}
    requested = dict(packet.get("pack_requested_focus") or packet.get("focus") or {})
    actual = dict(packet.get("focus") or requested)
    options["pack"] = {"version": 1, "role": role, "directory": str(root()),
                       "focus": {key: requested.get(key) for key in ("name", "named", "side")},
                       "prefix": str(actual.get("name") or "") + "!" if requested.get("named") else ""}
    options["pack"]["narration_only"] = bool(packet.get("pack_narration_only"))
    return PREFIX + base64.urlsafe_b64encode(json.dumps(options, sort_keys=True, ensure_ascii=False).encode()).decode("ascii")


def render(text, path, voice):
    """Copy a prepared sentence, optionally preceded by its prepared name call."""
    options = decode_voice(voice)
    plan = options["pack"]
    directory = Path(plan["directory"])
    # Only app-owned pack roots, never user-controlled paths in a descriptor.
    if directory.resolve() != root().resolve():
        raise LocalTTSError("해설팩 경로가 현재 프로그램과 다릅니다.")
    focus = plan.get("focus") or {}
    name = str(focus.get("name") or "")
    prefix = name + ", "
    parts = []
    if focus.get("named") and name and str(text).startswith(prefix):
        bare = str(text)[len(prefix):]
        parts = [clip_path(voice, bare, directory=directory)]
        if not plan.get("narration_only"):
            parts.insert(0, clip_path(voice, plan["prefix"], directory=directory))
    else:
        parts = [clip_path(voice, text, directory=directory)]
    if not all(ready(part) for part in parts):
        raise LocalTTSError("해설팩에 준비되지 않은 멘트입니다. 실시간 합성을 기다리지 않고 생략합니다. 팩 생성/이어 만들기를 실행해 주세요.")
    staged = ""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        fd, staged = tempfile.mkstemp(prefix="pack_", suffix=".wav", dir=os.path.dirname(os.path.abspath(path)))
        os.close(fd)
        with wave.open(staged, "wb") as output:
            params = None
            for index, part in enumerate(parts):
                with wave.open(str(part), "rb") as source:
                    current = (source.getnchannels(), source.getsampwidth(), source.getframerate())
                    if params is None:
                        params = current
                        output.setnchannels(params[0])
                        output.setsampwidth(params[1])
                        output.setframerate(params[2])
                    elif current != params:
                        raise LocalTTSError("해설팩 음성 형식이 서로 다릅니다. 같은 음성 설정으로 다시 준비해 주세요.")
                    if index:
                        output.writeframes(b"\0" * int(params[2] * .08) * params[0] * params[1])
                    output.writeframes(source.readframes(source.getnframes()))
        os.replace(staged, path)
        staged = ""
        return True
    finally:
        if staged:
            try:
                os.remove(staged)
            except OSError:
                pass


def catalog(scope="full"):
    from commentary_calls import SHORT_CALLS, REPEATED_COUNTER, REVERSAL, LONG_COMBO
    from commentary_story import SCENES, IDLE_SCENES, LATE_SCENES
    targets = ("급소", "왼쪽 눈", "오른쪽 눈", "턱", "코", "왼쪽 관자놀이", "오른쪽 관자놀이", "간", "명치", "이마")
    rows = []
    def add(role, text):
        rows.append((role, text))
    for role in ("caster", "analyst"):
        for name in ("블루 선수!", "레드 선수!"):
            add(role, name)
        for tag, lines in SHORT_CALLS.items():
            if scope == "sample":
                if tag not in ("counter", "heavy", "knockdown") or role != "caster":
                    continue
                lines = lines[:1]
            elif scope == "calls" and role == "analyst":
                continue
            elif role == "analyst" and tag not in ("counter", "combo", "heavy", "weak", "hit"):
                continue
            hits = (3,)
            places = targets if tag == "weak" else ("급소",)
            counts = ("첫 번째", "두 번째", "세 번째") if tag == "knockdown" and scope != "sample" else ("첫 번째",)
            for line in lines:
                for count in counts:
                    for hit in hits:
                        for target in places:
                            add(role, line.format(hits=hit, target=target, count_label=count))
            if tag in LONG_COMBO:
                for line in LONG_COMBO[tag]:
                    add(role, line)
        if scope != "sample" and role == "caster":
            for text in REPEATED_COUNTER + REVERSAL:
                add(role, text)
    if scope == "sample":
        script = next(s for s in SCENES["counter"] if s.lead.startswith("{setup}") and s.lead_role == "caster")
        add("analyst", script.reply)
    if scope == "full":
        for tag, scripts in SCENES.items():
            if tag == "hit":
                continue  # Ordinary hits never play the old optional replies.
            for script in scripts:
                if not script.lead.startswith("{setup}"):
                    continue
                add("caster" if script.lead_role == "analyst" else "analyst", script.reply)
        for script in IDLE_SCENES + LATE_SCENES:
            add("caster", script.lead)
            add("analyst", script.reply)
    return list(dict.fromkeys(rows))


def rehearsal(cfg, *, names=()):
    """Resolve a representative offline playlist; never invoke synthesis."""
    from commentary_calls import SHORT_CALLS, LONG_COMBO
    from commentary_story import SCENES
    cfg = copy.copy(cfg)
    cfg.spectator_tts_pack_enabled = True
    rows = []
    for tag in ("counter", "combo", "counter_combo", "heavy", "weak", "stun", "knockdown", "tko"):
        text = SHORT_CALLS[tag][0].format(hits=3, target="왼쪽 눈", count_label="첫 번째")
        rows.append((tag, "caster", text))
    rows.append(("긴 연타", "caster", LONG_COMBO["combo"][0]))
    for tag in ("counter", "combo", "heavy"):
        scripts = [s for s in SCENES[tag] if s.lead.startswith("{setup}") and s.lead_role == "caster"]
        if scripts:
            rows.extend(((tag + " 콜", "caster", SHORT_CALLS[tag][0]),
                         (tag + " 응답", "analyst", scripts[0].reply)))
    for role in ("caster", "analyst"):
        rows.append(("코너명", role, "블루 선수!"))
        rows.append(("코너명", role, "레드 선수!"))
    for name in list(names)[:2]:
        rows.append(("닉네임", "caster", str(name) + "!"))
        rows.append(("닉네임", "analyst", str(name) + "!"))
    steps, missing = [], []
    for label, role, text in rows:
        path = clip_path(commentary_voice(cfg, role, ""), text)
        if ready(path):
            steps.append({"role": role, "text": text, "media_path": str(path), "label": label, "post_ms": 350})
        else:
            missing.append(role + ": " + text)
    return steps, missing


def build(cfg, scope="full", *, names=(), cancel=None, progress=None, renderer=None):
    """Explicit resumable job, one at a time. Never invoked by a live hit."""
    cfg = copy.copy(cfg)
    if getattr(cfg, "spectator_tts_engine", "edge") != "qwen3":
        raise LocalTTSError("해설팩 제작은 Qwen 엔진을 선택하고 서버를 실행한 뒤 사용해 주세요.")
    if not _BUILD.acquire(blocking=False):
        raise LocalTTSError("이미 해설팩 또는 닉네임을 준비 중입니다.")
    try:
        rows = [] if scope == "names" else catalog(scope)
        for name in list(dict.fromkeys(str(name).strip() for name in names if str(name).strip()))[:16]:
            if len(name) > 80:
                continue  # Never silently truncate a player's identity.
            rows.extend((role, name + "!") for role in ("caster", "analyst"))
        rows = list(dict.fromkeys(rows))
        completed, generated = 0, 0
        for role, text in rows:
            if cancel is not None and cancel.is_set():
                return {"complete": False, "done": completed, "total": len(rows), "generated": generated}
            voice = commentary_voice(cfg, role, "")
            path = clip_path(voice, text)
            if not ready(path):
                if path.exists():
                    path.unlink()  # Invalid app-owned cache must not suppress regeneration.
                if renderer is None:
                    save_local(text, str(path), voice, timeout=90.)
                else:
                    renderer(text, str(path), voice)
                if not ready(path):
                    raise LocalTTSError("해설팩 파일 검증에 실패했습니다. 완성된 파일은 남겨 두고 제작을 중단합니다.")
                generated += 1
            completed += 1
            if progress:
                progress(completed, len(rows), role, text)
        return {"complete": True, "done": completed, "total": len(rows), "generated": generated}
    finally:
        _BUILD.release()


def prepare_names(cfg, names):
    """Bounded latest-name job. Never wait for synthesis on the UI thread."""
    global _names_worker, _names_pending
    if not enabled(cfg) or not getattr(cfg, "spectator_tts_pack_auto_names", True):
        return
    with _NAMES:
        _names_pending = [(copy.copy(cfg), tuple(names)[:2])]
        if _names_worker:
            return
        _names_worker = True
    def worker():
        global _names_worker, _names_pending
        while True:
            with _NAMES:
                if not _names_pending:
                    _names_worker = False
                    return
                current, values = _names_pending.pop()
            try:
                build(current, "names", names=values)
            except Exception:
                # Another explicit build or report can own the model. Existing
                # corner calls remain usable; no retries or GPU request storm.
                pass
    threading.Thread(target=worker, daemon=True, name="CommentaryPackNames").start()
