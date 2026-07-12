# diagnostics.py
# -*- coding: utf-8 -*-
"""Lightweight app-flow recorder and diagnostic ZIP exporter.

This module intentionally has no Qt imports and no dependency on the rest of the
app.  It is safe to import from timerauto.py, spectator_log_watcher.py and
browser_overlay.py.
"""

from __future__ import annotations

import json
import os
import platform
import re
import threading
import time
import traceback
import zipfile
from collections import deque
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


_SECRET_KEY_RE = re.compile(r"(token|secret|password|passwd|api[_-]?key|auth|cookie)", re.I)
_USER_PATH_RE = re.compile(r"([A-Za-z]:\\\\Users\\\\)[^\\\\/]+", re.I)
_HOME_PATH_RE = re.compile(r"/home/[^/]+")


def _tail_text(path: str, lines: int = 100, max_bytes: int = 512 * 1024) -> str:
    try:
        if not path or not os.path.isfile(path):
            return ""
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(max(0, size - max_bytes))
            data = f.read()
        text = data.decode("utf-8-sig", errors="replace")
        if lines and lines > 0:
            parts = text.splitlines()
            if len(parts) > int(lines):
                text = "\n".join(parts[-int(lines):])
        return text
    except Exception as exc:
        return f"<read failed: {exc}>"


def _mask_string(value: str) -> str:
    s = str(value)
    s = _USER_PATH_RE.sub(r"\1<USER>", s)
    s = _HOME_PATH_RE.sub("/home/<USER>", s)
    return s


def _safe_json(value: Any, *, mask_sensitive: bool = False, max_depth: int = 5, max_list: int = 40) -> Any:
    """Convert arbitrary app values into JSON-safe, compact values."""
    if max_depth <= 0:
        return "<max_depth>"
    try:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            s = _mask_string(value) if mask_sensitive else value
            return s if len(s) <= 2000 else s[:2000] + "...<truncated>"
        if isinstance(value, bytes):
            return f"<bytes {len(value)}>"
        # Avoid serializing images / numpy arrays / Qt objects.
        cls_name = type(value).__name__
        mod_name = getattr(type(value), "__module__", "")
        if cls_name in ("ndarray", "QImage", "QPixmap") or "numpy" in mod_name or "PyQt" in mod_name:
            shape = getattr(value, "shape", None)
            if shape is not None:
                return f"<{cls_name} shape={tuple(shape)}>"
            return f"<{cls_name}>"
        if is_dataclass(value):
            return _safe_json(asdict(value), mask_sensitive=mask_sensitive, max_depth=max_depth - 1, max_list=max_list)
        if isinstance(value, dict):
            out: Dict[str, Any] = {}
            for k, v in list(value.items())[:max_list]:
                key = str(k)
                if mask_sensitive and _SECRET_KEY_RE.search(key):
                    out[key] = "<redacted>"
                else:
                    out[key] = _safe_json(v, mask_sensitive=mask_sensitive, max_depth=max_depth - 1, max_list=max_list)
            if len(value) > max_list:
                out["<truncated>"] = len(value) - max_list
            return out
        if isinstance(value, (list, tuple, set, deque)):
            seq = list(value)
            out = [_safe_json(v, mask_sensitive=mask_sensitive, max_depth=max_depth - 1, max_list=max_list) for v in seq[:max_list]]
            if len(seq) > max_list:
                out.append(f"<truncated {len(seq) - max_list}>")
            return out
        return repr(value)[:2000]
    except Exception as exc:
        return f"<safe_json failed: {exc}>"


class DiagnosticRecorder:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.enabled = True
        self.mask_sensitive_default = True
        self.raw_sample_lines = 100
        self.events: deque[dict] = deque(maxlen=5000)
        self.incidents: deque[dict] = deque(maxlen=200)
        self.errors: deque[dict] = deque(maxlen=400)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.start_time = time.time()

    def set_options(self, *, enabled: Optional[bool] = None, max_events: Optional[int] = None,
                    raw_sample_lines: Optional[int] = None, mask_sensitive: Optional[bool] = None) -> None:
        with self._lock:
            if enabled is not None:
                self.enabled = bool(enabled)
            if raw_sample_lines is not None:
                try:
                    self.raw_sample_lines = max(10, min(2000, int(raw_sample_lines)))
                except Exception:
                    pass
            if mask_sensitive is not None:
                self.mask_sensitive_default = bool(mask_sensitive)
            if max_events is not None:
                try:
                    n = max(300, min(50000, int(max_events)))
                    old = list(self.events)[-n:]
                    self.events = deque(old, maxlen=n)
                except Exception:
                    pass

    def record(self, event_type: str, **payload: Any) -> None:
        if not self.enabled:
            return
        try:
            now = time.time()
            item = {
                "t": round(now, 3),
                "dt": round(now - self.start_time, 3),
                "type": str(event_type or "event"),
                "payload": _safe_json(payload, mask_sensitive=False, max_depth=4, max_list=60),
            }
            with self._lock:
                self.events.append(item)
        except Exception:
            # Diagnostics must never break the app.
            pass

    def error(self, event_type: str, exc: BaseException | None = None, **payload: Any) -> None:
        try:
            item = {
                "t": round(time.time(), 3),
                "type": str(event_type or "error"),
                "payload": _safe_json(payload, mask_sensitive=False, max_depth=4, max_list=60),
                "traceback": traceback.format_exc() if exc is None else "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            }
            with self._lock:
                self.errors.append(item)
                if self.enabled:
                    self.events.append({"t": item["t"], "dt": round(item["t"] - self.start_time, 3), "type": "error", "payload": item})
        except Exception:
            pass

    def mark_incident(self, note: str = "") -> dict:
        item = {
            "t": round(time.time(), 3),
            "dt": round(time.time() - self.start_time, 3),
            "note": str(note or "사용자 문제 발생 표시"),
        }
        with self._lock:
            self.incidents.append(item)
            self.events.append({"t": item["t"], "dt": item["dt"], "type": "incident_mark", "payload": dict(item)})
        return item

    def snapshot(self, *, mask_sensitive: bool = False) -> dict:
        with self._lock:
            return {
                "session_id": self.session_id,
                "enabled": bool(self.enabled),
                "start_time": self.start_time,
                "now": time.time(),
                "event_count": len(self.events),
                "incident_count": len(self.incidents),
                "error_count": len(self.errors),
                "events": _safe_json(list(self.events), mask_sensitive=mask_sensitive, max_depth=6, max_list=len(self.events) + 5),
                "incidents": _safe_json(list(self.incidents), mask_sensitive=mask_sensitive, max_depth=5, max_list=500),
                "errors": _safe_json(list(self.errors), mask_sensitive=mask_sensitive, max_depth=5, max_list=500),
            }

    def summary(self, *, mask_sensitive: bool = False, tail: int = 8) -> dict:
        """Compact diagnostics state for app_state/current-state text.

        Full event lists are still exported as recent_trace.jsonl. Putting the full
        nested trace inside app_state made the clipboard summary unreadable and
        produced <max_depth> noise.
        """
        with self._lock:
            ev_tail = list(self.events)[-max(0, int(tail or 0)):]
            inc_tail = list(self.incidents)[-3:]
            err_tail = list(self.errors)[-3:]
            return {
                "session_id": self.session_id,
                "enabled": bool(self.enabled),
                "start_time": self.start_time,
                "now": time.time(),
                "event_count": len(self.events),
                "incident_count": len(self.incidents),
                "error_count": len(self.errors),
                "events_tail": _safe_json(ev_tail, mask_sensitive=mask_sensitive, max_depth=6, max_list=40),
                "incidents_tail": _safe_json(inc_tail, mask_sensitive=mask_sensitive, max_depth=5, max_list=10),
                "errors_tail": _safe_json(err_tail, mask_sensitive=mask_sensitive, max_depth=5, max_list=10),
            }

    def current_state_text(self, app_state: Optional[dict] = None) -> str:
        app_state = app_state or {}
        with self._lock:
            last = list(self.events)[-8:]
            incident = list(self.incidents)[-1:] or []
            err_count = len(self.errors)
        lines = []
        lines.append("RFC Diagnostic State")
        lines.append(f"session={self.session_id}")
        lines.append(f"events={len(self.events)} errors={err_count} incidents={len(self.incidents)}")
        if app_state:
            try:
                compact_state = dict(app_state or {})
                if isinstance(compact_state.get("diagnostics"), dict) and "events" in compact_state.get("diagnostics", {}):
                    compact_state["diagnostics"] = self.summary(mask_sensitive=True, tail=3)
                lines.append("app_state=" + json.dumps(_safe_json(compact_state, mask_sensitive=True, max_depth=6, max_list=60), ensure_ascii=False))
            except Exception:
                lines.append("app_state=<failed>")
        if incident:
            lines.append("last_incident=" + json.dumps(incident[-1], ensure_ascii=False))
        lines.append("recent_events:")
        for ev in last:
            lines.append(json.dumps(_safe_json(ev, mask_sensitive=True, max_depth=4, max_list=20), ensure_ascii=False))
        return "\n".join(lines)

    def export_zip(self, output_dir: str, *, app_state: Optional[dict] = None, cfg_snapshot: Optional[Any] = None,
                   spectator_root: str = "", overlay_snapshot: Optional[dict] = None,
                   mask_sensitive: Optional[bool] = None, raw_sample_lines: Optional[int] = None) -> str:
        mask = self.mask_sensitive_default if mask_sensitive is None else bool(mask_sensitive)
        lines = self.raw_sample_lines if raw_sample_lines is None else int(raw_sample_lines or self.raw_sample_lines)
        os.makedirs(output_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = os.path.abspath(os.path.join(output_dir, f"RFC_Diagnostic_{stamp}.zip"))
        snap = self.snapshot(mask_sensitive=mask)
        app_state_safe = _safe_json(app_state or {}, mask_sensitive=mask, max_depth=6, max_list=120)
        cfg_safe = _safe_json(cfg_snapshot or {}, mask_sensitive=mask, max_depth=6, max_list=250)
        overlay_safe = _safe_json(overlay_snapshot or {}, mask_sensitive=mask, max_depth=6, max_list=120)
        format_detected = self._detect_spectator_format(spectator_root)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("README.txt", self._readme())
            zf.writestr("diagnostic_meta.json", json.dumps({
                "created_at": stamp,
                "platform": platform.platform(),
                "python": platform.python_version(),
                "session_id": self.session_id,
                "mask_sensitive": mask,
            }, ensure_ascii=False, indent=2))
            zf.writestr("app_state.json", json.dumps(app_state_safe, ensure_ascii=False, indent=2))
            zf.writestr("settings_snapshot.json", json.dumps(cfg_safe, ensure_ascii=False, indent=2))
            zf.writestr("recent_trace.jsonl", "\n".join(json.dumps(ev, ensure_ascii=False) for ev in snap.get("events", [])))
            zf.writestr("recent_errors.jsonl", "\n".join(json.dumps(ev, ensure_ascii=False) for ev in snap.get("errors", [])))
            zf.writestr("incidents.json", json.dumps(snap.get("incidents", []), ensure_ascii=False, indent=2))
            zf.writestr("overlay_snapshot.json", json.dumps(overlay_safe, ensure_ascii=False, indent=2))
            zf.writestr("spectator_format_detected.json", json.dumps(format_detected, ensure_ascii=False, indent=2))
            if spectator_root and os.path.isdir(spectator_root):
                for rel in self._raw_sample_files():
                    path = os.path.join(spectator_root, *rel.split("/"))
                    text = _tail_text(path, lines=lines)
                    if text:
                        if mask:
                            text = _mask_string(text)
                        zf.writestr("raw_log_samples/" + rel.replace("/", "__"), text)
            # Include the app's own latest log files if present.
            for candidate in self._app_log_candidates(os.getcwd()):
                if os.path.isfile(candidate):
                    text = _tail_text(candidate, lines=400, max_bytes=1024 * 1024)
                    if mask:
                        text = _mask_string(text)
                    zf.writestr("app_logs/" + os.path.basename(candidate), text)
        self.record("diagnostic_zip_exported", path=zip_path)
        return zip_path

    def _readme(self) -> str:
        return (
            "RFC Diagnostic Package\n"
            "======================\n\n"
            "이 ZIP은 앱 버그/업그레이드 재현을 위해 만든 진단 패키지입니다.\n"
            "중요 파일:\n"
            "- recent_trace.jsonl: 앱 내부 흐름 기록\n"
            "- app_state.json: 현재 앱/타이머/오버레이 상태\n"
            "- settings_snapshot.json: 설정 스냅샷\n"
            "- raw_log_samples/: SpectatorLog 최근 원본 샘플\n"
            "- spectator_format_detected.json: 로그 포맷 감지 결과\n"
        )

    def _raw_sample_files(self) -> List[str]:
        return [
            "match/round_state.txt",
            "match/round_time.txt",
            "match/round_number.txt",
            "match/round_total.txt",
            "match/damage_events.txt",
            "match/punches_thrown.txt",
            "match/scores.csv",
            "match/winner.txt",
            "match/camera_input.txt",
            "blue/punishment_mid.txt",
            "blue/punishment_long_raw.txt",
            "blue/punishment_long_weighted.txt",
            "red/punishment_mid.txt",
            "red/punishment_long_raw.txt",
            "red/punishment_long_weighted.txt",
            "blue/name.txt",
            "red/name.txt",
            "blue/accessibility.txt",
            "red/accessibility.txt",
            "blue/cosmetics.txt",
            "red/cosmetics.txt",
        ]

    def _app_log_candidates(self, base: str) -> Iterable[str]:
        for rel in ("timerauto.log", "app.log", "logs/timerauto.log", "logs/app.log", "logs/error.log"):
            yield os.path.join(base, rel)
        logs_dir = os.path.join(base, "logs")
        try:
            dated = [
                os.path.join(logs_dir, name)
                for name in os.listdir(logs_dir)
                if name.lower().startswith("timerauto_") and name.lower().endswith(".log")
            ]
            for path in sorted(dated, key=os.path.getmtime, reverse=True)[:3]:
                yield path
        except Exception:
            return

    def _detect_spectator_format(self, root: str) -> dict:
        info: Dict[str, Any] = {"root_exists": bool(root and os.path.isdir(root)), "root": _mask_string(root or "")}
        if not root or not os.path.isdir(root):
            return info
        dmg = os.path.join(root, "match", "damage_events.txt")
        last = ""
        for line in _tail_text(dmg, lines=20).splitlines():
            if line.strip():
                last = line.strip()
        if last:
            parts = last.split("\t")
            info["damage_events_columns"] = len(parts)
            info["damage_events_has_hand_column"] = bool(len(parts) >= 12 and str(parts[3]).lower() in ("left", "right"))
            info["damage_events_last_sample"] = _safe_json(parts, mask_sensitive=True, max_depth=2, max_list=20)
        for rel in ("match/punches_thrown.txt", "match/scores.csv", "match/winner.txt", "match/round_total.txt", "match/camera_input.txt"):
            path = os.path.join(root, *rel.split("/"))
            info[rel.replace("/", "_").replace(".", "_")] = os.path.isfile(path)
        return info


diagnostics = DiagnosticRecorder()

__all__ = ["diagnostics", "DiagnosticRecorder"]
