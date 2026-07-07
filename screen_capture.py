from __future__ import annotations

from typing import Any, Optional, Tuple

import cv2
import mss
import numpy as np


def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def capture_monitor_np(monitor_index: int, sct: Optional[Any] = None) -> np.ndarray:
    if sct is None:
        with mss.mss() as s:
            return _capture_monitor_np_impl(s, monitor_index)
    return _capture_monitor_np_impl(sct, monitor_index)


def _capture_monitor_np_impl(sct: Any, monitor_index: int) -> np.ndarray:
    monitors = sct.monitors
    if monitor_index < 1 or monitor_index >= len(monitors):
        monitor_index = 1
    mon = monitors[monitor_index]
    img = np.array(sct.grab(mon))  # BGRA
    bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return bgr


def capture_roi_np(monitor_index: int, r: Any, sct: Optional[Any] = None) -> np.ndarray:
    if not r.valid():
        return np.zeros((0, 0, 3), dtype=np.uint8)

    if sct is None:
        with mss.mss() as s:
            return _capture_roi_np_impl(s, monitor_index, r)
    return _capture_roi_np_impl(sct, monitor_index, r)


def _capture_roi_np_impl(sct: Any, monitor_index: int, r: Any) -> np.ndarray:
    monitors = sct.monitors
    if monitor_index < 1 or monitor_index >= len(monitors):
        monitor_index = 1
    mon = monitors[monitor_index]

    bbox = {
        "left": int(mon["left"] + r.x),
        "top": int(mon["top"] + r.y),
        "width": int(r.w),
        "height": int(r.h),
    }
    img = np.array(sct.grab(bbox))  # BGRA
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def capture_roi_np_global(r: Any, sct: Optional[Any] = None) -> np.ndarray:
    if not r.valid():
        return np.zeros((0, 0, 3), dtype=np.uint8)
    if sct is None:
        with mss.mss() as s:
            return _capture_roi_np_global_impl(s, r)
    return _capture_roi_np_global_impl(sct, r)


def _capture_roi_np_global_impl(sct: Any, r: Any) -> np.ndarray:
    bbox = {
        "left": int(r.x),
        "top": int(r.y),
        "width": int(r.w),
        "height": int(r.h),
    }
    img = np.array(sct.grab(bbox))  # BGRA
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def capture_pixel_bgr(x: int, y: int, sample: int = 1, sct: Optional[Any] = None) -> Tuple[int, int, int]:
    if sct is None:
        with mss.mss() as s:
            return _capture_pixel_bgr_impl(s, x, y, sample)
    return _capture_pixel_bgr_impl(sct, x, y, sample)


def _capture_pixel_bgr_impl(sct: Any, x: int, y: int, sample: int = 1) -> Tuple[int, int, int]:
    s = max(1, int(sample))
    half = s // 2
    left = int(x - half)
    top = int(y - half)
    bbox = {"left": left, "top": top, "width": s, "height": s}
    img = np.array(sct.grab(bbox))  # BGRA
    bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    b = int(np.median(bgr[..., 0]))
    g = int(np.median(bgr[..., 1]))
    r = int(np.median(bgr[..., 2]))
    return b, g, r


def capture_pixel_bgr_monitor(monitor_index: int, x: int, y: int, sample: int = 1, sct: Optional[Any] = None) -> Tuple[int, int, int]:
    frame = capture_monitor_np(monitor_index, sct=sct)
    h, w = frame.shape[:2]
    s = max(1, int(sample))
    half = s // 2
    cx = clamp(int(x), 0, w - 1)
    cy = clamp(int(y), 0, h - 1)
    left = clamp(cx - half, 0, w - 1)
    top = clamp(cy - half, 0, h - 1)
    right = clamp(left + s, 0, w)
    bottom = clamp(top + s, 0, h)
    roi = frame[top:bottom, left:right]
    if roi.size == 0:
        return 0, 0, 0
    b = int(np.median(roi[..., 0]))
    g = int(np.median(roi[..., 1]))
    r = int(np.median(roi[..., 2]))
    return b, g, r


def _monitor_offset(monitor_index: int) -> Tuple[int, int]:
    try:
        with mss.mss() as sct:
            mons = sct.monitors
            if monitor_index < 1 or monitor_index >= len(mons):
                return 0, 0
            mon = mons[monitor_index]
            return int(mon["left"]), int(mon["top"])
    except Exception:
        return 0, 0


def rect_local_to_global(monitor_index: int, r: Any) -> Any:
    dx, dy = _monitor_offset(monitor_index)
    rect_type = type(r)
    return rect_type(x=int(r.x + dx), y=int(r.y + dy), w=int(r.w), h=int(r.h))


def xy_local_to_global(monitor_index: int, x: int, y: int) -> Tuple[int, int]:
    dx, dy = _monitor_offset(monitor_index)
    return int(x + dx), int(y + dy)


def crop(bgr: np.ndarray, r: Any) -> np.ndarray:
    h, w = bgr.shape[:2]
    x = clamp(r.x, 0, w - 1)
    y = clamp(r.y, 0, h - 1)
    ww = clamp(r.w, 0, w - x)
    hh = clamp(r.h, 0, h - y)
    if ww <= 0 or hh <= 0:
        return bgr[0:0, 0:0]
    return bgr[y:y + hh, x:x + ww]
