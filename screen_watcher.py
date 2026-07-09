from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import cv2
import mss
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from screen_capture import capture_pixel_bgr, capture_roi_np_global


@dataclass
class _CaptureRect:
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0

    def valid(self) -> bool:
        return self.w > 0 and self.h > 0


def bgr_distance(c1: Tuple[int, int, int], c2: Tuple[int, int, int]) -> float:
    return float(np.linalg.norm(np.array(c1, dtype=np.float32) - np.array(c2, dtype=np.float32)))


class ScreenWatcher(QObject):
    trigger_fired = pyqtSignal()
    pixel_fired = pyqtSignal(str)

    def __init__(self, cfg: Any):
        super().__init__()
        self.cfg = cfg
        self._actions_by_event = dict(self.cfg.actions or {})
        self._stop = False
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_event = threading.Event()
        self._cooldown_until = 0.0
        self._window: List[bool] = []
        self._trigger_level_active = False
        self._pixel_state: Dict[str, dict] = {}
        self._trigger_detection_enabled = False
        self._pixel_detection_enabled = False

        self.last_debug = {
            "bgr": (0, 0, 0),
            "dist": 9999.0,
            "is_hit": False,
            "hits_in_window": 0,
            "window_len": 0,
            "cooldown_left": 0.0,
        }
        self._dbg_lock = threading.Lock()

    def get_debug(self) -> dict:
        with self._dbg_lock:
            return dict(self.last_debug)

    def _event_edge_enabled(self, event: str) -> bool:
        edge_map = getattr(self.cfg, "action_edge_triggers", {}) or {}
        direct = edge_map.get(event)
        if direct is not None:
            return bool(direct)
        if event.startswith("pixel:"):
            name = event.split(":", 1)[1]
            pid = ""
            for rule in self.cfg.pixel_rules or []:
                if str(rule.get("name", "")) == str(name):
                    pid = str(rule.get("id") or "")
                    break
            if pid:
                alt = edge_map.get(f"pixel_id:{pid}")
                if alt is not None:
                    return bool(alt)
        if event.startswith("pixel_id:"):
            pid = event.split(":", 1)[1]
            name = ""
            for rule in self.cfg.pixel_rules or []:
                if str(rule.get("id", "")) == str(pid):
                    name = str(rule.get("name") or "")
                    break
            if name:
                alt = edge_map.get(f"pixel:{name}")
                if alt is not None:
                    return bool(alt)
        return False

    def get_pixel_state(self, key: str) -> dict:
        return dict(self._pixel_state.get(str(key or ""), {}) or {})

    def start(self):
        self._stop = False
        try:
            if self._thread and self._thread.is_alive():
                self._stop_event.set()
        except Exception:
            pass
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop_event,), daemon=True)
        self._thread.start()
        self._running = True

    def stop(self):
        self._stop = True
        try:
            self._stop_event.set()
        except Exception:
            pass
        self._running = False

    def is_running(self) -> bool:
        return bool(self._running and self._thread and self._thread.is_alive())

    def set_detection_modes(self, *, trigger: Optional[bool] = None, pixel: Optional[bool] = None):
        if trigger is not None:
            self._trigger_detection_enabled = bool(trigger)
            if not self._trigger_detection_enabled:
                self._window.clear()
                self._trigger_level_active = False
        if pixel is not None:
            self._pixel_detection_enabled = bool(pixel)

    def trigger_detection_enabled(self) -> bool:
        return bool(self._trigger_detection_enabled)

    def pixel_detection_enabled(self) -> bool:
        return bool(self._pixel_detection_enabled)

    def _run(self, stop_event: threading.Event):
        try:
            with mss.mss() as sct:
                while not stop_event.is_set():
                    time.sleep(0.05)  # ~20fps
                    if self._pixel_detection_enabled:
                        self._check_pixel_rules(sct)
                    if not self._trigger_detection_enabled:
                        self._window.clear()
                        self._trigger_level_active = False
                        continue
                    if not self.cfg.trigger.enabled:
                        self._window.clear()
                        self._trigger_level_active = False
                        continue
                    if not self.cfg.roi_trigger.valid():
                        self._window.clear()
                        self._trigger_level_active = False
                        continue

                    now = time.time()

                    roi = capture_roi_np_global(self.cfg.roi_trigger, sct=sct)
                    if roi.size == 0:
                        continue

                    b = int(np.median(roi[..., 0]))
                    g = int(np.median(roi[..., 1]))
                    r = int(np.median(roi[..., 2]))
                    dist = bgr_distance((b, g, r), self.cfg.trigger.target_bgr)
                    is_hit = dist <= float(self.cfg.trigger.tolerance)
                    self._window.append(is_hit)
                    if len(self._window) > self.cfg.trigger.window_frames:
                        self._window.pop(0)

                    hits = int(sum(self._window))
                    wlen = int(len(self._window))
                    cooldown_left = max(0.0, self._cooldown_until - time.time())
                    level_ready = (wlen >= self.cfg.trigger.window_frames
                                   and hits >= self.cfg.trigger.consecutive_needed)
                    can_fire_by_cooldown = (now >= self._cooldown_until)

                    with self._dbg_lock:
                        self.last_debug = {
                            "bgr": (b, g, r),
                            "dist": float(dist),
                            "is_hit": bool(is_hit),
                            "hits_in_window": hits,
                            "window_len": wlen,
                            "cooldown_left": float(cooldown_left),
                        }

                    if self._event_edge_enabled("on_trigger"):
                        should_fire = bool(level_ready and (not self._trigger_level_active) and can_fire_by_cooldown)
                        self._trigger_level_active = bool(level_ready)
                        if should_fire:
                            self._cooldown_until = time.time() + self.cfg.trigger.cooldown_sec
                            self._window.clear()
                            self.trigger_fired.emit()
                    else:
                        if level_ready and can_fire_by_cooldown:
                            self._cooldown_until = time.time() + self.cfg.trigger.cooldown_sec
                            self._window.clear()
                            self.trigger_fired.emit()
        finally:
            if self._thread == threading.current_thread():
                self._running = False

    def _check_pixel_rules(self, sct: Any):
        rules = self.cfg.pixel_rules or []
        now = time.time()
        pixel_cache = self._build_pixel_capture_cache(rules, sct)
        for i, rule in enumerate(rules):
            name = str(rule.get("name") or f"rule{i + 1}")
            rid = str(rule.get("id") or "")
            if not bool(rule.get("enabled", True)):
                continue
            state_key = rid or name
            state = self._pixel_state.setdefault(state_key, {"window": [], "cooldown_until": 0.0})
            cooldown_until = float(state.get("cooldown_until", 0.0))
            if now < cooldown_until:
                state["cooldown_left"] = float(max(0.0, cooldown_until - now))
                continue
            x = int(rule.get("x", 0))
            y = int(rule.get("y", 0))
            sample = int(rule.get("sample", 1))
            tgt = rule.get("target_bgr", [0, 0, 0])
            tolerance = int(rule.get("tolerance", 5))
            window_frames = int(rule.get("window_frames", 1))
            consecutive = int(rule.get("consecutive_needed", 1))
            cooldown = float(rule.get("cooldown_sec", 0.5))

            mode = str(rule.get("mode", "pixel"))
            if mode == "roi":
                rr = rule.get("roi", {}) or {}
                rect = _CaptureRect(
                    x=int(rr.get("x", 0)),
                    y=int(rr.get("y", 0)),
                    w=int(rr.get("w", 0)),
                    h=int(rr.get("h", 0)),
                )
                if not rect.valid():
                    continue
                roi = capture_roi_np_global(rect, sct=sct)
                if roi.size == 0:
                    continue
                mean = roi.reshape(-1, 3).mean(axis=0)
                b, g, r = int(mean[0]), int(mean[1]), int(mean[2])
            else:
                b, g, r = self._sample_cached_pixel(pixel_cache, int(x), int(y), sample, sct)
            dist = bgr_distance((b, g, r), (int(tgt[0]), int(tgt[1]), int(tgt[2])))
            is_hit = dist <= float(tolerance)

            win = state.get("window", [])
            win.append(bool(is_hit))
            if len(win) > window_frames:
                win.pop(0)
            state["window"] = win
            state["last_bgr"] = (int(b), int(g), int(r))
            state["last_dist"] = float(dist)
            state["last_hit"] = bool(is_hit)
            state["window_len"] = int(len(win))
            state["window_hits"] = int(sum(win))
            state["last_time"] = float(now)

            hits = int(sum(win))
            level_ready = bool(len(win) >= window_frames and hits >= consecutive)
            edge_event_key = f"pixel_id:{rid}" if rid else f"pixel:{name}"
            edge_enabled = self._event_edge_enabled(edge_event_key)
            if edge_enabled:
                prev_level = bool(state.get("level_active", False))
                should_fire = bool(level_ready and (not prev_level))
                # Keep edge-active while the sampled pixel is still HIT. Otherwise
                # clearing the window after a fire makes the next still-HIT frame
                # look like HIT -> NO -> HIT and retriggers every cooldown cycle.
                state["level_active"] = bool(level_ready or (prev_level and is_hit))
            else:
                should_fire = bool(level_ready)
                state["level_active"] = bool(level_ready)

            if should_fire:
                state["cooldown_until"] = time.time() + cooldown
                state["cooldown_left"] = float(cooldown)
                if not edge_enabled:
                    state["window"] = []
                self.pixel_fired.emit(rid or name)

    def _build_pixel_capture_cache(self, rules: List[dict], sct: Any) -> Optional[dict]:
        boxes = []
        for rule in rules or []:
            if not bool(rule.get("enabled", True)):
                continue
            if str(rule.get("mode", "pixel")) == "roi":
                continue
            try:
                x = int(rule.get("x", 0))
                y = int(rule.get("y", 0))
                sample = max(1, int(rule.get("sample", 1)))
            except Exception:
                continue
            half = sample // 2
            boxes.append((x - half, y - half, x - half + sample, y - half + sample))
        if len(boxes) < 3:
            return None
        left = min(b[0] for b in boxes)
        top = min(b[1] for b in boxes)
        right = max(b[2] for b in boxes)
        bottom = max(b[3] for b in boxes)
        width = max(1, int(right - left))
        height = max(1, int(bottom - top))
        area = width * height
        # Far-apart points can make a full-screen capture slower than tiny grabs.
        if area > 2_000_000:
            return None
        try:
            img = np.array(sct.grab({"left": int(left), "top": int(top), "width": width, "height": height}))
            frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            return {"left": int(left), "top": int(top), "frame": frame}
        except Exception:
            return None

    def _sample_cached_pixel(self, cache: Optional[dict], x: int, y: int, sample: int, sct: Any) -> Tuple[int, int, int]:
        if not cache:
            return capture_pixel_bgr(x, y, sample, sct=sct)
        frame = cache.get("frame")
        if frame is None or getattr(frame, "size", 0) == 0:
            return capture_pixel_bgr(x, y, sample, sct=sct)
        s = max(1, int(sample))
        half = s // 2
        left = int(x - half) - int(cache.get("left", 0))
        top = int(y - half) - int(cache.get("top", 0))
        h, w = frame.shape[:2]
        if left < 0 or top < 0 or left >= w or top >= h:
            return capture_pixel_bgr(x, y, sample, sct=sct)
        right = min(w, left + s)
        bottom = min(h, top + s)
        roi = frame[top:bottom, left:right]
        if roi.size == 0:
            return capture_pixel_bgr(x, y, sample, sct=sct)
        b = int(np.median(roi[..., 0]))
        g = int(np.median(roi[..., 1]))
        r = int(np.median(roi[..., 2]))
        return b, g, r
