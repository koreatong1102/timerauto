"""Measured offline audio metadata, never guessed speech/word timings.

Runtime admission reads a WAV header only when its stat identity changes. PCM
pause scanning happens on explicit preparation/render, not on live log frames.
"""
from array import array
from collections import OrderedDict
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import wave

_LOCK = threading.RLock()
_CACHE = OrderedDict()
_LIMIT = 2048


def _identity(path):
    path = Path(path)
    stat = path.stat()
    return (str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)


def wav_info(path):
    """Return validated mono PCM16 duration; corrupt/missing files return None."""
    try:
        identity = _identity(path)
        with _LOCK:
            if identity in _CACHE:
                result = _CACHE.pop(identity)
                _CACHE[identity] = result
                return dict(result) if result is not None else None
        result = None
        try:
            with wave.open(str(path), "rb") as stream:
                channels, width, rate, frames = (stream.getnchannels(), stream.getsampwidth(),
                                                  stream.getframerate(), stream.getnframes())
                if channels == 1 and width == 2 and 8000 <= rate <= 96000 and frames > 0:
                    # Validate the actual final PCM frame, including WAVs with
                    # extra header chunks; file-size arithmetic alone can lie.
                    stream.setpos(frames - 1)
                    if len(stream.readframes(1)) == 2:
                        result = {"version": 1, "duration_seconds": frames / rate,
                                  "sample_rate": rate, "frames": frames, "channels": channels,
                                  "sample_width": width, "size_bytes": identity[1],
                                  "mtime_ns": identity[2], "ctime_ns": identity[3]}
        except (OSError, wave.Error, EOFError, ValueError):
            pass
        # If a background build replaced the file during header inspection,
        # don't publish metadata for two different generations as one clip.
        if _identity(path) != identity:
            return None
        with _LOCK:
            _CACHE[identity] = result
            while len(_CACHE) > _LIMIT:
                _CACHE.popitem(last=False)
        return dict(result) if result is not None else None
    except (OSError, ValueError):
        return None


def _sidecar(path):
    return Path(str(path) + ".delivery.json")


def _matches(metadata, current):
    return bool(isinstance(metadata, dict) and current and
                all(metadata.get(key) == current[key] for key in
                    ("version", "duration_seconds", "sample_rate", "frames", "channels", "sample_width",
                     "size_bytes", "mtime_ns", "ctime_ns")))


def _read_sidecar(path, current):
    try:
        source = _sidecar(path)
        if source.stat().st_size > 100_000:
            return None
        data = json.loads(source.read_text(encoding="utf-8"))
        return data if (_matches(data, current) and isinstance(data.get("pause_boundaries_ms"), list)
                        and len(data["pause_boundaries_ms"]) <= 1000) else None
    except (OSError, ValueError, TypeError):
        return None


def _observed_pauses(path, current):
    """PCM silence windows, NOT semantic sentence/phoneme boundaries.

    A conservative 180ms quiet run yields one point 40ms into the gap. Leading
    and trailing silence are excluded so they cannot produce fake handoffs.
    """
    rate = current["sample_rate"]
    window = max(1, rate // 50)  # 20ms measured PCM blocks.
    minimum = math.ceil(.18 * rate)
    leading = math.ceil(.35 * rate)
    trailing = current["frames"] - math.ceil(.18 * rate)
    pauses, position, quiet_at = [], 0, None
    with wave.open(str(path), "rb") as stream:
        while True:
            data = stream.readframes(window)
            if not data:
                break
            pcm = array("h")
            pcm.frombytes(data)
            if sys.byteorder != "little":
                pcm.byteswap()
            quiet = bool(pcm) and max(abs(value) for value in pcm) <= 128
            if quiet and quiet_at is None:
                quiet_at = position
            elif not quiet and quiet_at is not None:
                if position - quiet_at >= minimum and quiet_at >= leading and position <= trailing:
                    pauses.append(round((quiet_at + .04 * rate) / rate * 1000))
                quiet_at = None
            position += len(pcm)
    return tuple(pauses)


def write_delivery(path, *, role="", delivery="neutral"):
    """Add a resumable stat-bound sidecar on a preparation worker.

    `delivery` describes authored intent only. It is not a claim that a Base
    cloning model supports per-sentence emotion instructions.
    """
    current = wav_info(path)
    if current is None:
        return None
    old = _read_sidecar(path, current)
    if old is not None and old.get("role") == role and old.get("delivery") == delivery:
        return old
    metadata = {**current, "role": role, "delivery": delivery,
                "pause_boundaries_ms": old["pause_boundaries_ms"] if old else list(_observed_pauses(path, current)),
                "boundary_source": "pcm_quiet_180ms", "sentence_boundaries_ms": []}
    # Don't bind a sidecar to a replacement that raced the PCM read.
    if not _matches(metadata, wav_info(path)):
        return None
    staged = None
    try:
        target = _sidecar(path)
        fd, staged = tempfile.mkstemp(prefix="delivery_", suffix=".json", dir=str(target.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(metadata, output, ensure_ascii=False, sort_keys=True)
        os.replace(staged, target)
        staged = None
        return metadata
    finally:
        if staged:
            try:
                os.unlink(staged)
            except OSError:
                pass


def pause_boundaries(path):
    """Read only previously measured, current-file-bound quiet points."""
    info = wav_info(path)
    data = _read_sidecar(path, info)
    if data is None or data.get("boundary_source") != "pcm_quiet_180ms":
        return ()
    values = data.get("pause_boundaries_ms")
    if not isinstance(values, list) or len(values) > 1000:
        return ()
    duration = info["duration_seconds"] * 1000
    try:
        return tuple(sorted(set(int(value) for value in values
                                if isinstance(value, (int, float)) and math.isfinite(value)
                                and 350 <= value < duration - 180)))
    except (ValueError, OverflowError):
        return ()
