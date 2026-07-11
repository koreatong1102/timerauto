# timerauto.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import copy
import ctypes
from ctypes import wintypes
import json
import shutil
import os
import sys
import time
import math
import hashlib
import threading
import uuid
import logging
import traceback
import re
import tempfile
import fnmatch
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from datetime import datetime
from dataclasses import asdict
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING
from collections import deque

APP_VERSION = "1.0.14"
UPDATE_FEED_URL = "https://github.com/koreatong1102/timerauto/releases/download/latest/latest.json"

# Ensure a non-native Qt Quick Controls style for QML customization.
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Fusion")

# Improve DPI handling on Windows to keep coordinates/ROI accurate.
def _set_dpi_awareness() -> None:
    try:
        # Per-monitor v2 (best on modern Windows)
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        # Per-monitor v1
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        # Legacy system-DPI awareness
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

_set_dpi_awareness()

if sys.stdout is None:
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass
if sys.stderr is None:
    try:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass

import numpy as np
try:
    import winsound
except Exception:
    winsound = None
# Avoid importing pyautogui during startup. It can be relatively slow and is
# only needed when executing keyboard/mouse actions. UI key pickers fall back to
# the WinAPI key map, and actions.py lazily imports pyautogui on first use.
_PYAUTO_KEYS = []

# --- GUI ---
from PyQt6.QtCore import Qt, QTimer, QEvent, pyqtSignal, QObject, pyqtProperty, pyqtSlot, QSize, QPointF, QPoint, QMetaObject, Q_ARG, QUrl, QAbstractNativeEventFilter
from PyQt6.QtGui import QPixmap, QImage, QAction, QColor, QCursor, QPainter, QPen, QBrush, QPainterPath, QLinearGradient, QGuiApplication, QKeySequence, QPolygonF, QPalette, QShortcut, QDesktopServices
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtQuick import QQuickImageProvider, QQuickWindow
try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    HAS_QTMULTIMEDIA = True
except Exception:
    QMediaPlayer = None
    QAudioOutput = None
    HAS_QTMULTIMEDIA = False
try:
    from PyQt6.QtQuickControls2 import QQuickStyle  # type: ignore[reportMissingImports]
    HAS_QQUICKSTYLE = True
except Exception:
    QQuickStyle = None
    HAS_QQUICKSTYLE = False
from PyQt6.QtWidgets import (
    QApplication, QWidget, QDialog, QMainWindow, QLabel, QPushButton, QHBoxLayout,
    QVBoxLayout, QGridLayout, QTabWidget, QComboBox, QSpinBox, QLineEdit,
    QMessageBox, QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QInputDialog,
    QColorDialog, QListWidget, QStackedWidget, QScrollArea, QGroupBox, QDoubleSpinBox, QProgressBar,
    QMenu, QKeySequenceEdit, QTextEdit, QSlider, QFontComboBox, QFrame, QLayout, QSizePolicy
)

# --- Screen capture / image ---
import mss
import cv2

# --- Fuzzy match ---
try:
    from rapidfuzz import process as rf_process, fuzz as rf_fuzz
    HAS_RAPIDFUZZ = True
except Exception:
    HAS_RAPIDFUZZ = False

# --- Player segmentation: MediaPipe ---
mp = None
HAS_MEDIAPIPE = True
_MEDIAPIPE_IMPORT_ERROR = None

from actions import ActionRunner
from browser_overlay import BrowserOverlayServer
from browser_overlay_sync import BrowserOverlaySync
from hotkey_engine import build_vk_map, GlobalHotkeys, press_vk_once
from screen_capture import (
    capture_monitor_np,
    capture_pixel_bgr,
    capture_pixel_bgr_monitor,
    capture_roi_np,
    capture_roi_np_global,
    crop,
    rect_local_to_global,
    xy_local_to_global,
)
from screen_watcher import ScreenWatcher
from spectator_log_watcher import (
    COUNTER_DEALT_DAMAGE_THRESHOLD,
    COUNTER_PREV_DAMAGE_THRESHOLD,
    COUNTER_WINDOW_SEC,
    SpectatorLogWatcher,
)
from player_utils import (
    canonical_player_gid_for_cfg as _canonical_player_gid_for_cfg,
    player_gid_key_for_match as _player_gid_key_for_match,
    player_similarity_for_match as _player_similarity_for_match,
)

from app_paths import (
    get_app_base_dir,
    app_path,
    normalize_app_path,
    to_app_rel,
    resolve_spectatorlog_path,
    resolve_player_image_path,
)
from config_model import (
    Rect,
    TriggerConfig,
    PaletteConfig,
    AppConfig,
    default_win_effects,
    _normalize_win_effects_paths,
    _normalize_player_country,
    _player_image_path_for_gid,
    _player_flag_path_for_gid,
    _player_country_for_gid,
    _default_overlay_style_round,
    _default_overlay_style_time,
    _default_overlay_style_blue_name,
    _default_overlay_style_red_name,
    _default_overlay_style_arena,
    _default_browser_text_styles,
    _normalize_overlay_style,
    _normalize_browser_text_styles,
    _normalize_player_mask,
    _merge_dict,
    _normalize_hex_color,
    migrate_action_keys,
    sync_action_keys,
    prune_actions,
)
from runtime_support import resolve_config_path, _setup_logging
from update_manager import _parse_version, _download_file, _file_sha256, _write_update_script
from diagnostics import diagnostics as DIAG
from ai_project_snapshot import export_project_snapshot

_MP_SELFIE = None
_MP_LOCK = threading.Lock()
_NO_UPDATE = object()
PLAYER_ID_ALLOW_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-."
UNKNOWN_PLAYER_LABEL = "UNKNOWN"







def _suppress_qt_window_warnings():
    # Suppress noisy Qt DPI warnings on some systems.
    rule = "qt.qpa.window=false"
    existing = os.environ.get("QT_LOGGING_RULES", "").strip()
    if not existing:
        os.environ["QT_LOGGING_RULES"] = rule
        return
    if rule in existing:
        return
    os.environ["QT_LOGGING_RULES"] = existing + ";" + rule


def _ensure_std_streams():
    try:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass
    try:
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass


def _play_win_effect_sfx(path: str) -> bool:
    if not path:
        return False
    if winsound is None:
        return False
    try:
        raw = os.path.expanduser(str(path).strip())
        if os.path.isabs(raw):
            path = os.path.abspath(raw)
        else:
            path = os.path.abspath(os.path.join(get_app_base_dir(), raw))
    except Exception:
        path = str(path).strip()
    if not path or not os.path.isfile(path):
        return False
    if not path.lower().endswith(".wav"):
        return False
    try:
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        return True
    except Exception:
        return False


def _play_media_sfx(player, audio_out, path: str, playback_rate: float = 1.0) -> bool:
    if not path:
        return False
    if player is None or audio_out is None:
        return False
    try:
        raw = os.path.expanduser(str(path).strip())
        if os.path.isabs(raw):
            path = os.path.abspath(raw)
        else:
            # Prefer app base for relative assets
            path = os.path.abspath(os.path.join(get_app_base_dir(), raw))
    except Exception:
        return False
    if not path or not os.path.isfile(path):
        return False
    try:
        url = QUrl.fromLocalFile(path)
    except Exception:
        return False
    try:
        player.stop()
        try:
            player.setPlaybackRate(max(0.25, min(4.0, float(playback_rate or 1.0))))
        except Exception:
            pass
        player.setSource(url)
        player.play()
        return True
    except Exception:
        return False


def _store_player_image(gid: str, src_path: str) -> str:
    if not gid or not src_path or not os.path.exists(src_path):
        return ""
    base_dir = app_path("image", "players")
    os.makedirs(base_dir, exist_ok=True)
    _, ext = os.path.splitext(src_path)
    ext = ext if ext else ".png"
    dst = os.path.join(base_dir, f"{gid}_{uuid.uuid4().hex[:8]}{ext}")
    try:
        shutil.copy2(src_path, dst)
        return to_app_rel(dst)
    except Exception:
        return to_app_rel(src_path)




def _store_player_flag(gid: str, src_path: str) -> str:
    if not gid or not src_path or not os.path.exists(src_path):
        return ""
    base_dir = app_path("image", "flags")
    os.makedirs(base_dir, exist_ok=True)
    _, ext = os.path.splitext(src_path)
    ext = ext if ext else ".png"
    dst = os.path.join(base_dir, f"{gid}_flag_{uuid.uuid4().hex[:8]}{ext}")
    try:
        shutil.copy2(src_path, dst)
        return to_app_rel(dst)
    except Exception:
        return to_app_rel(src_path)
    try:
        player.stop()
        player.setSource(url)
        player.play()
        return True
    except Exception:
        return False


# -----------------------------
# Config / Data
# -----------------------------


















def _make_spectator_log_watcher(cfg: "AppConfig") -> SpectatorLogWatcher:
    return SpectatorLogWatcher(
        cfg,
        spectatorlog_path_resolver=resolve_spectatorlog_path,
        game_id_normalizer=normalize_game_id,
        player_gid_canonicalizer=_canonical_player_gid_for_cfg,
    )






























# -----------------------------
# Utilities
# -----------------------------
def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def normalize_game_id(s: str, allow: str) -> str:
    s = (s or "").upper().strip()
    s = "".join(ch for ch in s if ch in allow)
    return s


def snap_round_seconds(sec: Optional[int]) -> Optional[int]:
    if sec is None:
        return None
    try:
        v = int(sec)
    except Exception:
        return None
    options = [60, 120, 180]
    return min(options, key=lambda x: abs(x - v))


def snap_arena_name(text: str) -> str:
    options = ["기념관", "홈 체육관", "야간 체육관", "호텔"]
    raw = (text or "").strip()
    if not raw:
        return ""
    if raw in options:
        return raw
    if HAS_RAPIDFUZZ:
        result = rf_process.extractOne(raw, options, scorer=rf_fuzz.ratio)
        if result and int(result[1]) >= 60:
            return result[0]
        return raw
    # Fallback: longest common substring heuristic
    best = raw
    best_score = 0
    for opt in options:
        score = sum(1 for ch in opt if ch in raw)
        if score > best_score:
            best_score = score
            best = opt
    return best


def bgr_distance(c1: Tuple[int, int, int], c2: Tuple[int, int, int]) -> float:
    return float(np.linalg.norm(np.array(c1, dtype=np.float32) - np.array(c2, dtype=np.float32)))


def _find_window_by_title_contains(title_part: str) -> int:
    title_part = str(title_part or "").strip().lower()
    if not title_part or os.name != "nt":
        return 0
    user32 = ctypes.windll.user32
    found = ctypes.c_void_p(0)
    enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _enum_proc(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = int(user32.GetWindowTextLengthW(hwnd))
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if title_part in str(buf.value or "").lower():
                found.value = int(hwnd)
                return False
        except Exception:
            return True
        return True

    cb = enum_proc_type(_enum_proc)
    try:
        user32.EnumWindows(cb, 0)
    except Exception:
        return 0
    return int(found.value or 0)


def _window_title(hwnd: int) -> str:
    if os.name != "nt" or not hwnd:
        return ""
    try:
        user32 = ctypes.windll.user32
        length = int(user32.GetWindowTextLengthW(hwnd))
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return str(buf.value or "")
    except Exception:
        return ""


def _window_fullscreenish(hwnd: int, tolerance_px: int = 8) -> Tuple[bool, str]:
    if os.name != "nt" or not hwnd:
        return False, ""
    user32 = ctypes.windll.user32

    class RECT(ctypes.Structure):
        _fields_ = (
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        )

    class MONITORINFO(ctypes.Structure):
        _fields_ = (
            ("cbSize", ctypes.c_ulong),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", ctypes.c_ulong),
        )

    try:
        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False, "GetWindowRect failed"
        monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return False, "GetMonitorInfo failed"
        tol = max(0, int(tolerance_px))
        wr = (
            int(rect.left),
            int(rect.top),
            int(rect.right),
            int(rect.bottom),
        )
        mr = (
            int(info.rcMonitor.left),
            int(info.rcMonitor.top),
            int(info.rcMonitor.right),
            int(info.rcMonitor.bottom),
        )
        full = (
            abs(wr[0] - mr[0]) <= tol
            and abs(wr[1] - mr[1]) <= tol
            and abs(wr[2] - mr[2]) <= tol
            and abs(wr[3] - mr[3]) <= tol
        )
        return bool(full), f"window_rect={wr} monitor_rect={mr}"
    except Exception as e:
        return False, str(e)


def _press_vk_sendinput_held(vk: int, hold_sec: float = 0.08) -> Tuple[bool, str]:
    if os.name != "nt":
        return press_vk_once(vk)
    try:
        vk = int(vk) & 0xFF
        hold_sec = max(0.02, min(0.3, float(hold_sec or 0.08)))
    except Exception:
        return False, "invalid vk"

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
    INPUT_KEYBOARD = 1
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_SCANCODE = 0x0008
    MAPVK_VK_TO_VSC = 0
    extended_vk = {
        0x21, 0x22, 0x23, 0x24,
        0x25, 0x26, 0x27, 0x28,
        0x2D, 0x2E,
        0xA3, 0xA5,
    }

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = (
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ULONG_PTR),
        )

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = (
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ULONG_PTR),
        )

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = (
            ("uMsg", ctypes.c_ulong),
            ("wParamL", ctypes.c_short),
            ("wParamH", ctypes.c_ushort),
        )

    class INPUT_UNION(ctypes.Union):
        _fields_ = (
            ("ki", KEYBDINPUT),
            ("mi", MOUSEINPUT),
            ("hi", HARDWAREINPUT),
        )

    class INPUT(ctypes.Structure):
        _fields_ = (
            ("type", ctypes.c_ulong),
            ("u", INPUT_UNION),
        )

    try:
        scan = int(user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)) & 0xFFFF
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if vk in extended_vk else 0)
        down = INPUT()
        down.type = INPUT_KEYBOARD
        down.u.ki = KEYBDINPUT(0, scan, flags, 0, ULONG_PTR(0))
        sent_down = int(user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT)))
        if sent_down != 1:
            return False, f"SendInput down failed err={ctypes.get_last_error()}"
        time.sleep(hold_sec)
        up = INPUT()
        up.type = INPUT_KEYBOARD
        up.u.ki = KEYBDINPUT(0, scan, flags | KEYEVENTF_KEYUP, 0, ULONG_PTR(0))
        sent_up = int(user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT)))
        if sent_up != 1:
            return False, f"SendInput up failed err={ctypes.get_last_error()}"
        return True, ""
    except Exception as e:
        return False, str(e)


def _activate_window_reliably(hwnd: int, *, restore: bool = False) -> Tuple[bool, str]:
    """Activate a window while cooperating with Windows foreground-lock rules."""
    if os.name != "nt" or not hwnd:
        return False, "invalid window"
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.SetActiveWindow.argtypes = [wintypes.HWND]
    user32.SetActiveWindow.restype = wintypes.HWND
    current_tid = int(kernel32.GetCurrentThreadId() or 0)
    foreground_hwnd = int(user32.GetForegroundWindow() or 0)
    foreground_pid = wintypes.DWORD()
    target_pid = wintypes.DWORD()
    foreground_tid = int(
        user32.GetWindowThreadProcessId(wintypes.HWND(foreground_hwnd), ctypes.byref(foreground_pid)) or 0
    )
    target_tid = int(
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(target_pid)) or 0
    )
    attached = []
    try:
        for thread_id in (foreground_tid, target_tid):
            if thread_id and current_tid and thread_id != current_tid and thread_id not in attached:
                if user32.AttachThreadInput(current_tid, thread_id, True):
                    attached.append(thread_id)
        if not restore:
            user32.ShowWindow(wintypes.HWND(hwnd), 9)  # SW_RESTORE
        user32.BringWindowToTop(wintypes.HWND(hwnd))
        user32.SetActiveWindow(wintypes.HWND(hwnd))
        user32.SetForegroundWindow(wintypes.HWND(hwnd))
        time.sleep(0.08)
        active = int(user32.GetForegroundWindow() or 0)
        return active == int(hwnd), (
            f"requested={int(hwnd)} active={active} "
            f"target='{_window_title(hwnd)}' active_title='{_window_title(active)}'"
        )
    except Exception as exc:
        return False, str(exc)
    finally:
        for thread_id in reversed(attached):
            try:
                user32.AttachThreadInput(current_tid, thread_id, False)
            except Exception:
                pass


def press_vk_for_window_title(
    vk: int,
    title_part: str,
    *,
    activate: bool = True,
    restore_previous: bool = True,
    skip_if_fullscreen: bool = False,
) -> Tuple[bool, str]:
    if os.name != "nt":
        return press_vk_once(vk)
    title_part = str(title_part or "").strip()
    if not title_part:
        ok, err = _press_vk_sendinput_held(vk)
        if ok:
            return True, ""
        fallback_ok, fallback_err = press_vk_once(vk)
        return bool(fallback_ok), str(err or fallback_err or "")
    user32 = ctypes.windll.user32
    hwnd = _find_window_by_title_contains(title_part)
    if not hwnd:
        return False, f"window not found: {title_part}"
    if skip_if_fullscreen:
        is_full, full_info = _window_fullscreenish(hwnd)
        if is_full:
            return True, f"skipped=already_fullscreen hwnd={hwnd} target='{_window_title(hwnd)}' {full_info}".strip()
    prev = 0
    try:
        prev = int(user32.GetForegroundWindow())
    except Exception:
        prev = 0
    before_title = _window_title(prev)
    target_title = _window_title(hwnd)
    try:
        if activate:
            _activate_window_reliably(hwnd)
            time.sleep(0.28)
        active = 0
        try:
            active = int(user32.GetForegroundWindow())
        except Exception:
            active = 0
        ok, err = _press_vk_sendinput_held(vk, hold_sec=0.08)
        method = "held_sendinput"
        if not ok:
            fallback_ok, fallback_err = press_vk_once(vk)
            ok = bool(fallback_ok)
            err = f"{err}; fallback={fallback_err}"
            method = "fallback_press_vk_once"
        time.sleep(0.16)
        if restore_previous and prev and prev != hwnd:
            _activate_window_reliably(prev, restore=True)
        active_title = _window_title(active)
        return bool(ok), (
            f"{err or ''} method={method} hwnd={hwnd} target='{target_title}' "
            f"prev={prev} prev_title='{before_title}' active={active} active_title='{active_title}'"
        ).strip()
    except Exception as e:
        return False, str(e)


def window_client_point_from_cursor(title_part: str) -> Tuple[bool, int, int, str]:
    """Return the current cursor position in the target window's client coordinates."""
    if os.name != "nt":
        return False, 0, 0, "Windows only"
    title_part = str(title_part or "").strip()
    if not title_part:
        return False, 0, 0, "관전툴 창 제목이 비어 있습니다."
    hwnd = _find_window_by_title_contains(title_part)
    if not hwnd:
        return False, 0, 0, f"관전툴 창을 찾지 못했습니다: {title_part}"
    user32 = ctypes.windll.user32
    point = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return False, 0, 0, "GetCursorPos failed"
    screen_x, screen_y = int(point.x), int(point.y)
    if not user32.ScreenToClient(hwnd, ctypes.byref(point)):
        return False, 0, 0, "ScreenToClient failed"
    client_x, client_y = int(point.x), int(point.y)
    if client_x < 0 or client_y < 0:
        return False, client_x, client_y, "마우스가 관전툴 창 내부에 있지 않습니다."
    return True, client_x, client_y, (
        f"hwnd={hwnd} target='{_window_title(hwnd)}' "
        f"screen=({screen_x},{screen_y}) client=({client_x},{client_y})"
    )


def _current_cursor_screen_position() -> Tuple[int, int]:
    if os.name != "nt":
        pos = QCursor.pos()
        return int(pos.x()), int(pos.y())
    point = wintypes.POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
        return 0, 0
    return int(point.x), int(point.y)


def click_window_client_point(
    title_part: str,
    client_x: int,
    client_y: int,
    *,
    activate: bool = True,
    restore_focus: bool = True,
    restore_cursor: bool = True,
    minimize_target: bool = False,
    previous_hwnd_override: int = 0,
    previous_cursor_override: Optional[Tuple[int, int]] = None,
) -> Tuple[bool, str]:
    """Perform one real left click at a client-relative point in a target window."""
    if os.name != "nt":
        return False, "Windows only"
    title_part = str(title_part or "").strip()
    if not title_part:
        return False, "관전툴 창 제목이 비어 있습니다."
    hwnd = _find_window_by_title_contains(title_part)
    if not hwnd:
        return False, f"관전툴 창을 찾지 못했습니다: {title_part}"
    try:
        client_x = max(0, int(client_x))
        client_y = max(0, int(client_y))
    except Exception:
        return False, "시작 버튼 좌표가 올바르지 않습니다."

    user32 = ctypes.windll.user32
    target = wintypes.POINT(client_x, client_y)
    if not user32.ClientToScreen(hwnd, ctypes.byref(target)):
        return False, "ClientToScreen failed"
    target_x, target_y = int(target.x), int(target.y)
    previous_hwnd = int(previous_hwnd_override or user32.GetForegroundWindow() or 0)
    previous_cursor = wintypes.POINT()
    have_previous_cursor = bool(user32.GetCursorPos(ctypes.byref(previous_cursor)))
    if previous_cursor_override is not None:
        previous_cursor.x = int(previous_cursor_override[0])
        previous_cursor.y = int(previous_cursor_override[1])
        have_previous_cursor = True

    click_ok = False
    detail = ""
    try:
        if activate:
            activated, activate_detail = _activate_window_reliably(hwnd)
            if not activated:
                logging.warning("LOBBY_AUTO_START_ACTIVATE_FAIL %s", activate_detail)
            time.sleep(0.12)
        if not user32.SetCursorPos(target_x, target_y):
            detail = "SetCursorPos failed"
        else:
            time.sleep(0.035)
            mouse_left_down = 0x0002
            mouse_left_up = 0x0004
            user32.mouse_event(mouse_left_down, 0, 0, 0, 0)
            time.sleep(0.045)
            user32.mouse_event(mouse_left_up, 0, 0, 0, 0)
            time.sleep(0.08)
            click_ok = True
            detail = (
                f"hwnd={hwnd} target='{_window_title(hwnd)}' "
                f"client=({client_x},{client_y}) screen=({target_x},{target_y})"
            )
    except Exception as e:
        detail = str(e)
    finally:
        if restore_cursor and have_previous_cursor:
            try:
                user32.SetCursorPos(int(previous_cursor.x), int(previous_cursor.y))
            except Exception:
                pass
        if minimize_target:
            try:
                user32.ShowWindow(wintypes.HWND(hwnd), 6)  # SW_MINIMIZE
                logging.info("LOBBY_AUTO_START_TARGET_MINIMIZED hwnd=%s", hwnd)
            except Exception:
                logging.exception("LOBBY_AUTO_START_TARGET_MINIMIZE_FAIL")
        if restore_focus and previous_hwnd and previous_hwnd != hwnd:
            restored, restore_detail = _activate_window_reliably(previous_hwnd, restore=True)
            if restored:
                logging.info("LOBBY_AUTO_START_FOCUS_RESTORE_OK %s", restore_detail)
            else:
                logging.warning("LOBBY_AUTO_START_FOCUS_RESTORE_FAIL %s", restore_detail)
            detail = f"{detail} focus_restored={restored} {restore_detail}".strip()
    return click_ok, detail

def _get_mediapipe_selfie():
    global mp, HAS_MEDIAPIPE, _MEDIAPIPE_IMPORT_ERROR, _MP_SELFIE
    if not HAS_MEDIAPIPE:
        return None
    if _MP_SELFIE is not None:
        return _MP_SELFIE
    with _MP_LOCK:
        if mp is None:
            try:
                import mediapipe as _mp
                if not hasattr(_mp, "solutions") or not hasattr(_mp.solutions, "selfie_segmentation"):
                    raise RuntimeError("mediapipe selfie_segmentation unavailable")
                mp = _mp
                HAS_MEDIAPIPE = True
                _MEDIAPIPE_IMPORT_ERROR = None
            except Exception as e:
                HAS_MEDIAPIPE = False
                _MEDIAPIPE_IMPORT_ERROR = str(e)
                return None
        if _MP_SELFIE is None:
            _MP_SELFIE = mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=1)
    return _MP_SELFIE


def extract_palette_bgr(
    bgr_roi: np.ndarray,
    k: int,
    mask_thresh: float,
    max_pixels: int,
    min_v_cut: int
) -> List[Tuple[int, int, int]]:
    """
    Extract dominant BGR colors from an ROI.
    """
    if bgr_roi is None or bgr_roi.size == 0:
        return []

    seg = _get_mediapipe_selfie()
    mask = None

    if seg is not None:
        rgb = cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2RGB)
        rgb_small = cv2.resize(rgb, (256, 256), interpolation=cv2.INTER_AREA)

        try:
            res = seg.process(rgb_small)
        except Exception:
            res = None

        if res is not None and res.segmentation_mask is not None:
            mask = (res.segmentation_mask > float(mask_thresh)).astype(np.uint8)
            mask = cv2.resize(mask, (bgr_roi.shape[1], bgr_roi.shape[0]), interpolation=cv2.INTER_NEAREST)

    hsv = cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2HSV)
    V = hsv[..., 2]

    if mask is None:
        person = bgr_roi[V >= int(min_v_cut)]
        if person.size == 0:
            person = bgr_roi.reshape(-1, 3)
    else:
        person = bgr_roi[(mask == 1) & (V >= int(min_v_cut))]
        if person.size == 0:
            # Fallback to all pixels when the mask removes everything.
            person = bgr_roi[mask == 1]
            if person.size == 0:
                return []

    pts = person.reshape(-1, 3).astype(np.float32)
    if pts.shape[0] > int(max_pixels):
        idx = np.random.choice(pts.shape[0], int(max_pixels), replace=False)
        pts = pts[idx]

    # Downsample pixels before kmeans for speed.
    k_use = int(min(int(k), max(1, pts.shape[0])))
    if k_use <= 1:
        b, g, r = pts.mean(axis=0)
        return [(int(b), int(g), int(r))]

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 25, 1.0)
    flags = cv2.KMEANS_PP_CENTERS

    try:
        compactness, labels, centers = cv2.kmeans(pts, k_use, None, criteria, 3, flags)
    except Exception:
        b, g, r = pts.mean(axis=0)
        return [(int(b), int(g), int(r))]

    labels = labels.reshape(-1)
    counts = np.bincount(labels, minlength=k_use)
    order = np.argsort(-counts)

    palette: List[Tuple[int, int, int]] = []
    for i in order:
        b, g, r = centers[i]
        palette.append((int(b), int(g), int(r)))

    return palette


def extract_player_cutout_bgra(bgr_roi: np.ndarray) -> Optional[np.ndarray]:
    if bgr_roi is None or bgr_roi.size == 0:
        return None
    h, w = bgr_roi.shape[:2]
    if h < 8 or w < 8:
        return None

    rect = (
        int(w * 0.08),
        int(h * 0.08),
        max(1, int(w * 0.84)),
        max(1, int(h * 0.84)),
    )
    mask = np.zeros((h, w), np.uint8)
    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)

    try:
        cv2.grabCut(bgr_roi, mask, rect, bgd_model, fgd_model, 3, cv2.GC_INIT_WITH_RECT)
    except Exception:
        return cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2BGRA)

    fg = (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)
    alpha = (fg.astype(np.uint8)) * 255
    bgra = cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2BGRA)
    bgra[..., 3] = alpha
    return bgra


def cartoonize_bgr(bgr_roi: np.ndarray) -> Optional[np.ndarray]:
    if bgr_roi is None or bgr_roi.size == 0:
        return None
    try:
        # Smooth colors while preserving edges
        color = cv2.bilateralFilter(bgr_roi, d=7, sigmaColor=75, sigmaSpace=75)
        gray = cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2GRAY)
        gray = cv2.medianBlur(gray, 5)
        edges = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 2
        )
        edges_bgr = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        cartoon = cv2.bitwise_and(color, edges_bgr)
        return cartoon
    except Exception:
        return bgr_roi


def bgr_to_qimage(bgr: np.ndarray) -> Optional[QImage]:
    if bgr is None or bgr.size == 0:
        return None
    h, w = bgr.shape[:2]
    if bgr.shape[2] == 4:
        fmt_bgra = getattr(QImage.Format, "Format_BGRA8888", None)
        if fmt_bgra is not None:
            qimg = QImage(bgr.data, w, h, 4 * w, fmt_bgra).copy()
        else:
            rgba = cv2.cvtColor(bgr, cv2.COLOR_BGRA2RGBA)
            qimg = QImage(rgba.data, w, h, 4 * w, QImage.Format.Format_RGBA8888).copy()
    else:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    return qimg


def qimage_to_bgr(qimg: QImage) -> Optional[np.ndarray]:
    if qimg is None or qimg.isNull():
        return None
    try:
        img = qimg.convertToFormat(QImage.Format.Format_RGB888)
        w = img.width()
        h = img.height()
        ptr = img.bits()
        ptr.setsize(h * img.bytesPerLine())
        arr = np.frombuffer(ptr, np.uint8).reshape((h, img.bytesPerLine()))
        arr = arr[:, :w * 3].reshape((h, w, 3))
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR).copy()
    except Exception:
        return None


def safe_cv2_imread(path: str, flags: int = cv2.IMREAD_UNCHANGED) -> Optional[np.ndarray]:
    """Read images safely on Windows unicode paths and avoid OpenCV console spam.

    OpenCV's cv2.imread can fail noisily when the app lives under a Korean/non-ASCII
    folder path. np.fromfile + cv2.imdecode handles those paths correctly and does
    not print repeated loadsave.cpp warnings.
    """
    try:
        if not path or not os.path.isfile(path):
            return None
        data = np.fromfile(path, dtype=np.uint8)
        if data is None or data.size == 0:
            return None
        img = cv2.imdecode(data, flags)
        if img is None or getattr(img, "size", 0) == 0:
            return None
        return img
    except Exception:
        return None


# -----------------------------
# ROI Selection Dialog (drag)
# -----------------------------
class RoiPickerDialog(QDialog):
    def __init__(self, parent: QWidget, bgr_frame: np.ndarray, title: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.frame = bgr_frame
        self.start = None
        self.end = None
        self.rect = Rect()

        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setMinimumSize(900, 500)

        btn_ok = QPushButton("\ud655\uc778")
        btn_cancel = QPushButton("\uCDE8\uC18C")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)

        lay_btn = QHBoxLayout()
        lay_btn.addStretch(1)
        lay_btn.addWidget(btn_ok)
        lay_btn.addWidget(btn_cancel)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("마우스로 드래그해서 박스를 그려주세요."))
        layout.addWidget(self.label)
        layout.addLayout(lay_btn)
        self.setLayout(layout)

        self._update_pixmap()

        self.label.mousePressEvent = self._mouse_press
        self.label.mouseMoveEvent = self._mouse_move
        self.label.mouseReleaseEvent = self._mouse_release

    def _update_pixmap(self):
        draw = self.frame.copy()
        if self.start and self.end:
            x1, y1 = self.start
            x2, y2 = self.end
            x, y = min(x1, x2), min(y1, y2)
            w, h = abs(x2 - x1), abs(y2 - y1)
            cv2.rectangle(draw, (x, y), (x + w, y + h), (0, 255, 255), 2)

        rgb = cv2.cvtColor(draw, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg)
        self.label.setPixmap(
            pix.scaled(self.label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )

    def _map_to_image_coords(self, pos) -> Tuple[int, int]:
        pix = self.label.pixmap()
        if pix is None:
            return 0, 0

        lbl_w = self.label.width()
        lbl_h = self.label.height()
        img_h, img_w = self.frame.shape[:2]

        scale = min(lbl_w / img_w, lbl_h / img_h)
        disp_w = int(img_w * scale)
        disp_h = int(img_h * scale)
        offset_x = (lbl_w - disp_w) // 2
        offset_y = (lbl_h - disp_h) // 2

        x = int((pos.x() - offset_x) / max(scale, 1e-6))
        y = int((pos.y() - offset_y) / max(scale, 1e-6))
        x = clamp(x, 0, img_w - 1)
        y = clamp(y, 0, img_h - 1)
        return x, y

    def _mouse_press(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.start = self._map_to_image_coords(ev.pos())
            self.end = self.start
            self._update_pixmap()

    def _mouse_move(self, ev):
        if self.start is not None:
            self.end = self._map_to_image_coords(ev.pos())
            self._update_pixmap()

    def _mouse_release(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self.start and self.end:
            x1, y1 = self.start
            x2, y2 = self.end
            x, y = min(x1, x2), min(y1, y2)
            w, h = abs(x2 - x1), abs(y2 - y1)
            self.rect = Rect(x=x, y=y, w=w, h=h)
            self._update_pixmap()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)


class HotkeyPickDialog(QDialog):
    def __init__(self, parent: QWidget, sample: int = 1):
        super().__init__(parent)
        self.setWindowTitle("\uD53D\uC140 \uC120\uD0DD \uBAA8\uB4DC")
        self.setModal(True)
        self.sample = int(sample)
        self.pos = None
        self.bgr = None

        lay = QVBoxLayout(self)
        msg = QLabel("커서를 위치시키고 아무 키나 누르세요. (ESC 취소)")
        msg.setWordWrap(True)
        lay.addWidget(msg)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        pos = QCursor.pos()
        b, g, r = capture_pixel_bgr(pos.x(), pos.y(), self.sample)
        self.pos = pos
        self.bgr = (b, g, r)
        self.accept()


class ClickCaptureOverlay(QWidget):
    clicked = pyqtSignal(int, int, str)

    def __init__(self, parent: Optional[QWidget] = None, message: str = "\uD074\uB9AD\uD574\uC11C \uC704\uCE58\uB97C \uC9C0\uC815\uD569\uB2C8\uB2E4. (ESC \uCDE8\uC18C)"):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        msg = QLabel(message)
        msg.setStyleSheet("color:#fff; font-size:16px;")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(msg, 1)
        self.setStyleSheet("background: rgba(0,0,0,120);")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            self.close()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        pos = event.globalPosition().toPoint()
        btn = event.button()
        if btn == Qt.MouseButton.LeftButton:
            name = "left"
        elif btn == Qt.MouseButton.RightButton:
            name = "right"
        elif btn == Qt.MouseButton.MiddleButton:
            name = "middle"
        else:
            name = "left"
        self.clicked.emit(int(pos.x()), int(pos.y()), name)
        self.close()


class ImeAwareLineEdit(QLineEdit):
    queryTextChanged = pyqtSignal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ime_preedit = ""
        self.textChanged.connect(self._emit_query_text)

    def _emit_query_text(self):
        base = str(self.text() or "")
        preedit = str(self._ime_preedit or "")
        self.queryTextChanged.emit(base + preedit)

    def inputMethodEvent(self, event):
        try:
            self._ime_preedit = str(event.preeditString() or "")
        except Exception:
            self._ime_preedit = ""
        super().inputMethodEvent(event)
        self._emit_query_text()

    def focusOutEvent(self, event):
        self._ime_preedit = ""
        super().focusOutEvent(event)
        self._emit_query_text()


class PixelPickOverlay(QWidget):
    def __init__(
        self,
        sample_func: Callable[[QPoint], Tuple[int, int, int]],
        parent: Optional[QWidget] = None,
        message: str = "\uD53D\uC140 \uC120\uD0DD \uBAA8\uB4DC: \uB9C8\uC6B0\uC2A4\uB97C \uC6C0\uC9C1\uC774\uACE0 \uB2E8\uCD95\uD0A4\uB97C \uB2E4\uC2DC \uB204\uB974\uBA74 \uC801\uC6A9\uB429\uB2C8\uB2E4. (ESC \uCDE8\uC18C)",
        accept_on_key: bool = False,
        on_accept: Optional[Callable[[], None]] = None,
    ):
        super().__init__(None)
        self._sample_func = sample_func
        self._last_pos = QCursor.pos()
        self._last_bgr = (0, 0, 0)
        self._last_update = 0.0
        self._accept_on_key = bool(accept_on_key)
        self._on_accept = on_accept
        self._fixed_msg_pos: Optional[QPoint] = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(1)

        self._msg_box = QLabel(message, self)
        self._msg_box.setStyleSheet(
            "color:#fff; font-size:16px; font-weight:600;"
            "background:rgba(0,0,0,200); padding:10px 14px; border-radius:10px;"
            "border:1px solid rgba(255,255,255,0.2);"
        )
        self._msg_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._msg_box.adjustSize()

        self.info_box = QWidget(self)
        info_lay = QHBoxLayout(self.info_box)
        info_lay.setContentsMargins(8, 6, 8, 6)
        info_lay.setSpacing(6)
        self.lbl_color = QLabel()
        self.lbl_color.setFixedSize(16, 16)
        self.lbl_color.setStyleSheet("background:#000; border:1px solid #fff; border-radius:3px;")
        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet("color:#fff; font-size:12px;")
        info_lay.addWidget(self.lbl_color)
        info_lay.addWidget(self.lbl_info)
        self.info_box.setStyleSheet("background:rgba(0,0,0,170); border-radius:8px;")

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

        QTimer.singleShot(0, lambda: self._update_at(QCursor.pos()))

    def _tick(self):
        self._update_at(QCursor.pos())

    def _place_message(self):
        if not hasattr(self, "_msg_box") or self._msg_box is None:
            return
        self._msg_box.adjustSize()
        mw = self._msg_box.width()
        mh = self._msg_box.height()
        if self._fixed_msg_pos is not None:
            x = int(self._fixed_msg_pos.x() - (mw / 2))
            y = int(self._fixed_msg_pos.y() - (mh / 2))
        else:
            try:
                scr = QGuiApplication.screenAt(QCursor.pos())
                if scr is None:
                    scr = QGuiApplication.primaryScreen()
                geo = scr.geometry() if scr is not None else self.geometry()
                gx = int(geo.x() + (geo.width() / 2))
                gy = int(geo.y() + (geo.height() * 0.12))
                local = self.mapFromGlobal(QPoint(gx, gy))
                x = int(local.x() - (mw / 2))
                y = int(local.y() - (mh / 2))
            except Exception:
                x = int((self.width() - mw) / 2)
                y = int(self.height() * 0.12)
        x = max(12, min(self.width() - mw - 12, x))
        y = max(12, min(self.height() - mh - 12, y))
        self._msg_box.move(x, y)
        self._msg_box.raise_()

    def _update_at(self, pos):
        now = time.time()
        if now - self._last_update < 0.03:
            return
        self._last_update = now
        self._place_message()
        b, g, r = self._sample_func(pos)
        self._last_pos = pos
        self._last_bgr = (int(b), int(g), int(r))
        r_i, g_i, b_i = int(r), int(g), int(b)
        hex_color = f"#{r_i:02X}{g_i:02X}{b_i:02X}"
        self.lbl_info.setText(f"x={pos.x()} y={pos.y()}  RGB {r_i},{g_i},{b_i}  {hex_color}")
        self.lbl_info.adjustSize()
        self.lbl_color.setStyleSheet(
            f"background: rgb({r_i},{g_i},{b_i}); border:1px solid #fff; border-radius:3px;"
        )
        self.info_box.adjustSize()
        local = self.mapFromGlobal(pos)
        x = local.x() + 16
        y = local.y() + 16
        if x + self.info_box.width() > self.width():
            x = self.width() - self.info_box.width() - 8
        if y + self.info_box.height() > self.height():
            y = self.height() - self.info_box.height() - 8
        x = max(8, x)
        y = max(8, y)
        self.info_box.move(x, y)
        self.info_box.raise_()

    def current_sample(self) -> Tuple[QPoint, Tuple[int, int, int]]:
        self._update_at(QCursor.pos())
        return self._last_pos, self._last_bgr

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._safe_close()
            event.accept()
            return
        if self._accept_on_key and self._on_accept:
            self._on_accept()
            self.close()
            event.accept()
            return
        return super().keyPressEvent(event)

    def _safe_close(self):
        try:
            self.hide()
        except Exception:
            pass
        try:
            self.close()
        except Exception:
            pass

    def showEvent(self, event):
        self.grabKeyboard()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        try:
            self._place_message()
        except Exception:
            pass
        return super().showEvent(event)

    def resizeEvent(self, event):
        try:
            self._place_message()
        except Exception:
            pass
        return super().resizeEvent(event)

    def closeEvent(self, event):
        try:
            self.releaseKeyboard()
        except Exception:
            pass
        return super().closeEvent(event)

    def mousePressEvent(self, event):
        # 오버레이 메시지 영역은 클릭으로 이동하지 않음
        return


class ActionMiniDialog(QDialog):
    def __init__(self, parent: QWidget, action: Optional[dict] = None, default_pos: Optional[Tuple[int, int]] = None):
        super().__init__(parent)
        self.setWindowTitle("액션 설정")
        self.resize(520, 260)
        self.cfg = getattr(parent, "cfg", None)
        self._action = dict(action or {"type": "delay_ms", "ms": 100})
        self._default_pos = default_pos
        self._fallback_pos = default_pos
        if self._fallback_pos is None:
            try:
                pos = QCursor.pos()
                self._fallback_pos = (int(pos.x()), int(pos.y()))
            except Exception:
                self._fallback_pos = None
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        lay = QVBoxLayout(self)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("종류"))
        self.cmb_type = QComboBox()
        self.cmb_type.addItem("\uC9C0\uC5F0(s)", "delay_ms")
        self.cmb_type.addItem("키 누르기", "key_press")
        self.cmb_type.addItem("\uD56B\uD0A4(\uB3D9\uC2DC\uD0A4)", "hotkey")
        self.cmb_type.addItem("\uD14D\uC2A4\uD2B8 \uC785\uB825", "type_text")
        self.cmb_type.addItem("\uB9C8\uC6B0\uC2A4 \uC774\uB3D9", "mouse_move")
        self.cmb_type.addItem("\uB9C8\uC6B0\uC2A4 \uD074\uB9AD", "mouse_click")
        self.cmb_type.addItem("\uD0C0\uC774\uBA38 \uC2DC\uC791", "timer_start")
        self.cmb_type.addItem("\uD0C0\uC774\uBA38 \uC815\uC9C0", "timer_stop")
        self.cmb_type.addItem("\uD0C0\uC774\uBA38 \uCD08\uAE30\uD654", "timer_reset")
        self.cmb_type.addItem("\uD0C0\uC774\uBA38 \uAC12 \uC124\uC815", "timer_set")
        self.cmb_type.addItem("TTS(\uC601\uC5B4)", "tts_en")
        self.cmb_type.addItem("\uB9E4\uCE58\uC5C5 \uC548\uB0B4 TTS(\uC601\uC5B4)", "matchup_tts_en")
        self.cmb_type.addItem("\uD314\uB808\uD2B8 \uCEA1\uCC98", "palette_capture")
        type_row.addWidget(self.cmb_type, 1)
        lay.addLayout(type_row)

        self.stack = QStackedWidget()

        self.pg_delay = QWidget()
        r = QHBoxLayout(self.pg_delay)
        self.sp_delay = QDoubleSpinBox(); self.sp_delay.setRange(0.0, 60.0); self.sp_delay.setSingleStep(0.1)
        r.addWidget(QLabel("지연(s):")); r.addWidget(self.sp_delay); r.addStretch(1)
        self.stack.addWidget(self.pg_delay)

        self.pg_key = QWidget()
        r = QHBoxLayout(self.pg_key)
        self.cmb_key = QComboBox()
        key_items = _PYAUTO_KEYS or list(build_vk_map().keys())
        self.cmb_key.addItems(key_items)
        self.sp_hold = QSpinBox(); self.sp_hold.setRange(0, 5000)
        r.addWidget(QLabel("키")); r.addWidget(self.cmb_key)
        r.addWidget(QLabel("누름(ms):")); r.addWidget(self.sp_hold)
        self.stack.addWidget(self.pg_key)

        self.pg_hotkey = QWidget()
        r = QHBoxLayout(self.pg_hotkey)
        self.txt_hotkey = QLineEdit()
        self.txt_hotkey.setPlaceholderText("예: ctrl,shift,a")
        r.addWidget(QLabel("핫키 조합:")); r.addWidget(self.txt_hotkey, 1)
        self.stack.addWidget(self.pg_hotkey)

        self.pg_type = QWidget()
        r = QHBoxLayout(self.pg_type)
        self.txt_type = QLineEdit()
        self.sp_interval = QSpinBox(); self.sp_interval.setRange(0, 2000)
        r.addWidget(QLabel("텍스트:")); r.addWidget(self.txt_type, 1)
        r.addWidget(QLabel("간격(ms):")); r.addWidget(self.sp_interval)
        self.stack.addWidget(self.pg_type)

        self.pg_mouse = QWidget()
        r = QHBoxLayout(self.pg_mouse)
        self.sp_x = QSpinBox(); self.sp_x.setRange(0, 10000)
        self.sp_y = QSpinBox(); self.sp_y.setRange(0, 10000)
        self.sp_move_ms = QSpinBox(); self.sp_move_ms.setRange(0, 5000)
        self.chk_mouse_mon = QCheckBox("모니터 기준")
        default_mon = int(getattr(self.cfg, "monitor_index", 1) if self.cfg else 1)
        self.sp_mouse_mon = QSpinBox(); self.sp_mouse_mon.setRange(1, 8); self.sp_mouse_mon.setValue(default_mon)
        self.chk_mouse_mon.setChecked(False)
        self.chk_mouse_mon.setVisible(False)
        self.sp_mouse_mon.setVisible(False)
        btn_pick = QPushButton("현재 위치")
        btn_pick.clicked.connect(self._pick_mouse)
        r.addWidget(QLabel("X:")); r.addWidget(self.sp_x)
        r.addWidget(QLabel("Y:")); r.addWidget(self.sp_y)
        r.addWidget(QLabel("이동(ms):")); r.addWidget(self.sp_move_ms)
        r.addWidget(self.chk_mouse_mon); r.addWidget(self.sp_mouse_mon)
        r.addWidget(btn_pick)
        self.stack.addWidget(self.pg_mouse)

        self.pg_click = QWidget()
        r = QHBoxLayout(self.pg_click)
        self.sp_cx = QSpinBox(); self.sp_cx.setRange(0, 10000)
        self.sp_cy = QSpinBox(); self.sp_cy.setRange(0, 10000)
        self.cmb_btn = QComboBox(); self.cmb_btn.addItems(["left", "right", "middle"])
        self.sp_clicks = QSpinBox(); self.sp_clicks.setRange(1, 10)
        self.sp_click_gap = QSpinBox(); self.sp_click_gap.setRange(0, 2000)
        self.chk_click_mon = QCheckBox("모니터 기준")
        self.sp_click_mon = QSpinBox(); self.sp_click_mon.setRange(1, 8); self.sp_click_mon.setValue(default_mon)
        self.chk_click_mon.setChecked(False)
        self.chk_click_mon.setVisible(False)
        self.sp_click_mon.setVisible(False)
        btn_pick = QPushButton("현재 위치")
        btn_pick.clicked.connect(self._pick_click)
        r.addWidget(QLabel("X:")); r.addWidget(self.sp_cx)
        r.addWidget(QLabel("Y:")); r.addWidget(self.sp_cy)
        r.addWidget(self.chk_click_mon); r.addWidget(self.sp_click_mon)
        r.addWidget(btn_pick)
        r.addWidget(QLabel("버튼:")); r.addWidget(self.cmb_btn)
        r.addWidget(QLabel("횟수:")); r.addWidget(self.sp_clicks)
        r.addWidget(QLabel("간격(ms):")); r.addWidget(self.sp_click_gap)
        self.stack.addWidget(self.pg_click)

        self.pg_timer = QWidget()
        r = QHBoxLayout(self.pg_timer)
        self.sp_round = QSpinBox(); self.sp_round.setRange(1, 99)
        self.sp_total = QSpinBox(); self.sp_total.setRange(1, 99)
        self.sp_sec = QSpinBox(); self.sp_sec.setRange(1, 3600)
        r.addWidget(QLabel("현재 라운드:")); r.addWidget(self.sp_round)
        r.addWidget(QLabel("총 라운드:")); r.addWidget(self.sp_total)
        r.addWidget(QLabel("초:")); r.addWidget(self.sp_sec)
        self.stack.addWidget(self.pg_timer)

        self.pg_tts = QWidget()
        r = QHBoxLayout(self.pg_tts)
        self.txt_tts = QLineEdit()
        self.sp_rate = QSpinBox(); self.sp_rate.setRange(80, 300); self.sp_rate.setValue(200)
        self.sp_vol = QSpinBox(); self.sp_vol.setRange(0, 100); self.sp_vol.setValue(100)
        self.cmb_voice_mode = QComboBox()
        self.cmb_voice_mode.addItem("\uC790\uB3D9", "auto")
        self.cmb_voice_mode.addItem("\uD55C\uAD6D\uC5B4 \uC6B0\uC120", "ko")
        self.cmb_voice_mode.addItem("\uC601\uC5B4 \uC6B0\uC120", "en")
        self.sp_tts_repeat = QSpinBox(); self.sp_tts_repeat.setRange(1, 10); self.sp_tts_repeat.setValue(1)
        r.addWidget(QLabel("\uD14D\uC2A4\uD2B8:")); r.addWidget(self.txt_tts, 1)
        r.addWidget(QLabel("속도:")); r.addWidget(self.sp_rate)
        r.addWidget(QLabel("볼륨(%):")); r.addWidget(self.sp_vol)
        r.addWidget(QLabel("\uC74C\uC131:")); r.addWidget(self.cmb_voice_mode)
        r.addWidget(QLabel("\uD69F\uC218:")); r.addWidget(self.sp_tts_repeat)
        self.stack.addWidget(self.pg_tts)

        self.pg_none = QWidget()
        self.stack.addWidget(self.pg_none)

        lay.addWidget(self.stack)

        delay_row = QHBoxLayout()
        self.sp_pre = QDoubleSpinBox(); self.sp_pre.setRange(0.0, 60.0); self.sp_pre.setSingleStep(0.1)
        self.sp_post = QDoubleSpinBox(); self.sp_post.setRange(0.0, 60.0); self.sp_post.setSingleStep(0.1)
        delay_row.addWidget(QLabel("선행 지연(s):")); delay_row.addWidget(self.sp_pre)
        delay_row.addSpacing(12)
        delay_row.addWidget(QLabel("\uD6C4\uB51C\uB808\uC774(s):")); delay_row.addWidget(self.sp_post)
        delay_row.addStretch(1)
        lay.addLayout(delay_row)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("\ud655\uc778")
        btn_cancel = QPushButton("\uCDE8\uC18C")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        lay.addLayout(btn_row)

        self._apply_action_dialog_style()

        self.cmb_type.currentIndexChanged.connect(self._on_type_changed)
        self._load_action(self._action)

    def _apply_action_dialog_style(self) -> None:
        self.setStyleSheet(
            "QDialog { background:#1f2430; color:#e5e7eb; font-family:'Segoe UI'; font-size:12px; }"
            "QLabel { color:#e5e7eb; }"
            "QPushButton { background:#6d5dfc; color:#ffffff; border:0; border-radius:10px; padding:6px 12px; }"
            "QPushButton:hover { background:#7b6bff; }"
            "QPushButton:pressed { background:#5b4ce0; }"
            "QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit { background:#141a25; color:#e5e7eb; "
            "border:1px solid #2c3444; border-radius:8px; padding:4px 8px; }"
            "QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width:22px; "
            "border-left:1px solid #2c3444; background:#1f2735; border-top-right-radius:8px; border-bottom-right-radius:8px; }"
            "QComboBox::down-arrow { image:none; width:0; height:0; "
            "border-left:5px solid transparent; border-right:5px solid transparent; border-top:7px solid #e5e7eb; }"
            "QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { "
            "width:18px; background:#1f2735; border-left:1px solid #2c3444; }"
            "QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image:none; width:0; height:0; "
            "border-left:5px solid transparent; border-right:5px solid transparent; border-bottom:7px solid #e5e7eb; }"
            "QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image:none; width:0; height:0; "
            "border-left:5px solid transparent; border-right:5px solid transparent; border-top:7px solid #e5e7eb; }"
        )

    def _pick_mouse(self):
        pos = QCursor.pos()
        x = int(pos.x())
        y = int(pos.y())
        self.sp_x.setValue(int(x))
        self.sp_y.setValue(int(y))

    def _pick_click(self):
        pos = QCursor.pos()
        x = int(pos.x())
        y = int(pos.y())
        self.sp_cx.setValue(int(x))
        self.sp_cy.setValue(int(y))

    def _on_type_changed(self, _idx: int):
        t = self.cmb_type.currentData()
        mapping = {
            "delay_ms": self.pg_delay,
            "key_press": self.pg_key,
            "hotkey": self.pg_hotkey,
            "type_text": self.pg_type,
            "mouse_move": self.pg_mouse,
            "mouse_click": self.pg_click,
            "timer_set": self.pg_timer,
            "tts_en": self.pg_tts,
            "matchup_tts_en": self.pg_tts,
        }
        self.stack.setCurrentWidget(mapping.get(t, self.pg_none))
        if hasattr(self, "txt_tts"):
            if t == "matchup_tts_en":
                self.txt_tts.setEnabled(True)
                self.txt_tts.setPlaceholderText("{blue} versus {red}, the match will begin shortly.")
            else:
                self.txt_tts.setEnabled(True)
                self.txt_tts.setPlaceholderText("")

    def _load_action(self, action: dict):
        t = action.get("type", "delay_ms")
        for i in range(self.cmb_type.count()):
            if self.cmb_type.itemData(i) == t:
                self.cmb_type.setCurrentIndex(i)
                break
        self.sp_pre.setValue(int(action.get("pre_delay_ms", 0)) / 1000.0)
        self.sp_post.setValue(int(action.get("post_delay_ms", 0)) / 1000.0)
        self.sp_delay.setValue(int(action.get("ms", 0)) / 1000.0)
        key_name = str(action.get("key", "") or "")
        if key_name and hasattr(self, "cmb_key"):
            idx = self.cmb_key.findText(key_name)
            if idx < 0:
                idx = self.cmb_key.findText(key_name.lower())
            if idx >= 0:
                self.cmb_key.setCurrentIndex(idx)
        self.sp_hold.setValue(int(action.get("hold_ms", 0)))
        self.txt_hotkey.setText(",".join(action.get("keys", []) or []))
        self.txt_type.setText(str(action.get("text", "")))
        self.sp_interval.setValue(int(action.get("interval_ms", 0)))
        if t in ("mouse_move", "mouse_click"):
            use_mon = bool(action.get("use_monitor", False))
            mon = int(action.get("monitor", getattr(self.cfg, "monitor_index", 1) if self.cfg else 1))
            if t == "mouse_move":
                if hasattr(self, "chk_mouse_mon"):
                    self.chk_mouse_mon.setChecked(use_mon)
                    self.sp_mouse_mon.setValue(mon)
            else:
                if hasattr(self, "chk_click_mon"):
                    self.chk_click_mon.setChecked(use_mon)
                    self.sp_click_mon.setValue(mon)
        has_xy = ("x" in action) or ("y" in action)
        if has_xy:
            x = int(action.get("x", 0))
            y = int(action.get("y", 0))
            if self._default_pos and x == 0 and y == 0:
                x, y = self._default_pos
            self._action_pick_monitor = None
        elif self._fallback_pos:
            x, y = self._fallback_pos
        else:
            x, y = 0, 0
        self.sp_x.setValue(int(x))
        self.sp_y.setValue(int(y))
        self.sp_move_ms.setValue(int(action.get("duration_ms", 0)))
        self.sp_cx.setValue(int(x))
        self.sp_cy.setValue(int(y))
        self.cmb_btn.setCurrentText(str(action.get("button", "left")))
        self.sp_clicks.setValue(int(action.get("clicks", 1)))
        self.sp_click_gap.setValue(int(action.get("interval_ms", 0)))
        self.sp_round.setValue(int(action.get("round_current", 1)))
        self.sp_total.setValue(int(action.get("round_total", 1)))
        self.sp_sec.setValue(int(action.get("seconds_left", 60)))
        self.txt_tts.setText(str(action.get("text", "")))
        self.sp_rate.setValue(int(action.get("rate", 200)))
        self.sp_vol.setValue(int(action.get("volume", 100)))
        vm = str(action.get("voice_mode", "auto") or "auto")
        idx_vm = self.cmb_voice_mode.findData(vm)
        self.cmb_voice_mode.setCurrentIndex(idx_vm if idx_vm >= 0 else 0)
        self.sp_tts_repeat.setValue(int(action.get("repeat", 1)))
        self._on_type_changed(0)

    def action_result(self) -> dict:
        t = self.cmb_type.currentData()
        action = {"type": t}
        pre_delay = int(self.sp_pre.value() * 1000)
        if pre_delay > 0:
            action["pre_delay_ms"] = pre_delay
        post_delay = int(self.sp_post.value() * 1000)
        if post_delay > 0:
            action["post_delay_ms"] = post_delay
        if t == "delay_ms":
            action["ms"] = int(self.sp_delay.value() * 1000)
        elif t == "key_press":
            key_name = self.cmb_key.currentText() if hasattr(self, "cmb_key") else ""
            action["key"] = show_non_empty(key_name)
            action["hold_ms"] = int(self.sp_hold.value())
        elif t == "hotkey":
            keys = [k.strip() for k in self.txt_hotkey.text().split(",") if k.strip()]
            action["keys"] = keys
        elif t == "type_text":
            action["text"] = self.txt_type.text()
            action["interval_ms"] = int(self.sp_interval.value())
        elif t == "mouse_move":
            action["x"] = int(self.sp_x.value())
            action["y"] = int(self.sp_y.value())
            action["duration_ms"] = int(self.sp_move_ms.value())
            use_mon = bool(self.chk_mouse_mon.isChecked()) if hasattr(self, "chk_mouse_mon") else False
            action["use_monitor"] = use_mon
            if use_mon:
                action["monitor"] = int(self.sp_mouse_mon.value()) if hasattr(self, "sp_mouse_mon") else int(getattr(self.cfg, "monitor_index", 1) if self.cfg else 1)
        elif t == "mouse_click":
            action["x"] = int(self.sp_cx.value())
            action["y"] = int(self.sp_cy.value())
            action["button"] = self.cmb_btn.currentText()
            action["clicks"] = int(self.sp_clicks.value())
            action["interval_ms"] = int(self.sp_click_gap.value())
            use_mon = bool(self.chk_click_mon.isChecked()) if hasattr(self, "chk_click_mon") else False
            action["use_monitor"] = use_mon
            if use_mon:
                action["monitor"] = int(self.sp_click_mon.value()) if hasattr(self, "sp_click_mon") else int(getattr(self.cfg, "monitor_index", 1) if self.cfg else 1)
        elif t == "tts_en":
            action["text"] = self.txt_tts.text()
            action["rate"] = int(self.sp_rate.value())
            action["volume"] = int(self.sp_vol.value())
            action["voice_mode"] = str(self.cmb_voice_mode.currentData() or "auto")
        elif t == "matchup_tts_en":
            action["text"] = self.txt_tts.text().strip() or "{blue} versus {red}, the match will begin shortly."
            action["rate"] = int(self.sp_rate.value())
            action["volume"] = int(self.sp_vol.value())
            action["voice_mode"] = str(self.cmb_voice_mode.currentData() or "auto")
            action["repeat"] = int(self.sp_tts_repeat.value())
        elif t == "timer_set":
            action["round_current"] = int(self.sp_round.value())
            action["round_total"] = int(self.sp_total.value())
            action["seconds_left"] = int(self.sp_sec.value())
        return action


class PixelActionsDialog(QDialog):
    def __init__(self, parent: QWidget, sd: "SettingsDialog", event: str,
                 default_pos: Optional[Tuple[int, int]] = None):
        super().__init__(parent)
        self.sd = sd
        self.event = event
        self._default_pos = default_pos
        self.setWindowTitle("\uC561\uC158 \uC124\uC815")
        self.resize(520, 360)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        if not hasattr(self.sd, "_actions_by_event"):
            self.sd._actions_by_event = dict(self.sd.cfg.actions or {})
        if hasattr(self.sd, "_ensure_event_actions"):
            self.sd._ensure_event_actions(event)
        self._actions = list(self.sd._actions_by_event.get(event, []))

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("\uC561\uC158"))
        self.lst_actions = QListWidget()
        self.lst_actions.itemDoubleClicked.connect(self._edit_action)
        lay.addWidget(self.lst_actions, 1)

        row = QHBoxLayout()
        self.btn_add = QPushButton("\uCD94\uAC00")
        self.btn_edit = QPushButton("\uC218\uC815")
        self.btn_del = QPushButton("\uC0AD\uC81C")
        self.btn_up = QPushButton("\uC704\uB85C")
        self.btn_down = QPushButton("아래로")
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_edit)
        row.addWidget(self.btn_del)
        row.addWidget(self.btn_up)
        row.addWidget(self.btn_down)
        lay.addLayout(row)

        btn_row = QHBoxLayout()
        btn_close = QPushButton("?リ린")
        btn_close.clicked.connect(self.close)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)

        self.btn_add.clicked.connect(self._add_action)
        self.btn_edit.clicked.connect(self._edit_action)
        self.btn_del.clicked.connect(self._del_action)
        self.btn_up.clicked.connect(self._move_action_up)
        self.btn_down.clicked.connect(self._move_action_down)

        self._reload_actions()

    def _reload_actions(self):
        self.lst_actions.clear()
        for action in self._actions:
            self.lst_actions.addItem(self.sd._action_summary(action))

    def _save_actions(self):
        if self._default_pos:
            dx, dy = self._default_pos
            for action in self._actions:
                atype = str(action.get("type", "")).lower()
                if atype in ("mouse_move", "mouse_click", "mouse_down", "mouse_up"):
                    has_x = "x" in action
                    has_y = "y" in action
                    x = int(action.get("x", 0)) if has_x else None
                    y = int(action.get("y", 0)) if has_y else None
                    if (not has_x) or (not has_y) or (x == 0 and y == 0):
                        action["x"] = int(dx)
                        action["y"] = int(dy)
        if hasattr(self.sd, "_set_actions_for_event"):
            self.sd._set_actions_for_event(self.event, list(self._actions))
            return
        self.sd._actions_by_event[self.event] = list(self._actions)
        self.sd.cfg.actions = dict(self.sd._actions_by_event)
        if hasattr(self.sd, "_update_action_summary_label"):
            self.sd._update_action_summary_label(self.event)

    def _add_action(self):
        dlg = ActionMiniDialog(self, default_pos=self._default_pos)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._actions.append(dlg.action_result())
        self._reload_actions()
        self.lst_actions.setCurrentRow(len(self._actions) - 1)

    def _edit_action(self, *_args):
        idx = self.lst_actions.currentRow()
        if idx < 0 or idx >= len(self._actions):
            return
        dlg = ActionMiniDialog(self, self._actions[idx], default_pos=self._default_pos)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._actions[idx] = dlg.action_result()
        self._reload_actions()
        self.lst_actions.setCurrentRow(idx)

    def _del_action(self):
        idx = self.lst_actions.currentRow()
        if idx < 0 or idx >= len(self._actions):
            return
        del self._actions[idx]
        self._reload_actions()
        self.lst_actions.setCurrentRow(min(idx, len(self._actions) - 1))

    def _move_action_up(self):
        idx = self.lst_actions.currentRow()
        if idx <= 0:
            return
        self._actions[idx - 1], self._actions[idx] = self._actions[idx], self._actions[idx - 1]
        self._reload_actions()
        self.lst_actions.setCurrentRow(idx - 1)

    def _move_action_down(self):
        idx = self.lst_actions.currentRow()
        if idx < 0 or idx >= len(self._actions) - 1:
            return
        self._actions[idx + 1], self._actions[idx] = self._actions[idx], self._actions[idx + 1]
        self._reload_actions()
        self.lst_actions.setCurrentRow(idx + 1)

    def closeEvent(self, event):
        try:
            self._save_actions()
        except Exception:
            pass
        return super().closeEvent(event)


class PixelActionDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        sd: "SettingsDialog",
        gx: int,
        gy: int,
        bgr: Tuple[int, int, int],
    ):
        super().__init__(parent)
        self.sd = sd
        self.lx = int(gx)
        self.ly = int(gy)
        self.bgr = (int(bgr[0]), int(bgr[1]), int(bgr[2]))
        self.setWindowTitle("색상 선택")
        self.resize(360, 300)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self._default_pos = (self.lx, self.ly)

        if not hasattr(self.sd, "_pixel_rules"):
            self.sd._pixel_rules = list(self.sd.cfg.pixel_rules or [])
        main = QVBoxLayout(self)

        info_row = QHBoxLayout()
        self.color_box = QLabel()
        self.color_box.setFixedSize(18, 18)
        r, g, b = self.bgr[2], self.bgr[1], self.bgr[0]
        self.color_box.setStyleSheet(f"background: rgb({r},{g},{b}); border:1px solid #fff; border-radius:3px;")
        self.lbl_info = QLabel(f"x={self.lx} y={self.ly}  RGB {r},{g},{b}")
        self.lbl_info.setStyleSheet("color:#e5e7eb;")
        info_row.addWidget(self.color_box)
        info_row.addWidget(self.lbl_info)
        info_row.addStretch(1)
        main.addLayout(info_row)

        main.addWidget(QLabel("조건"))
        self.lst_rules = QListWidget()
        main.addWidget(self.lst_rules, 1)

        rule_row = QHBoxLayout()
        self.btn_add = QPushButton("\uC0C8 \uC870\uAC74 \uCD94\uAC00")
        self.btn_close = QPushButton("\uB2EB\uAE30")
        rule_row.addWidget(self.btn_add)
        rule_row.addStretch(1)
        rule_row.addWidget(self.btn_close)
        main.addLayout(rule_row)

        self.btn_add.clicked.connect(self._add_rule)
        self.btn_close.clicked.connect(self.close)
        self.lst_rules.itemClicked.connect(self._on_rule_clicked)
        self._reload_rules()

    def _reload_rules(self):
        self.lst_rules.clear()
        for idx, rule in enumerate(self.sd._pixel_rules):
            name = str(rule.get("name") or f"rule{idx+1}")
            self.lst_rules.addItem(f"{idx+1}. {name}")

    def _apply_to_rule(self, idx: int) -> Optional[str]:
        if idx < 0 or idx >= len(self.sd._pixel_rules):
            return None
        rule = self.sd._pixel_rules[idx]
        rule["mode"] = "pixel"
        rule["x"] = int(self.lx)
        rule["y"] = int(self.ly)
        rule["sample"] = 1
        rule["roi"] = {"x": 0, "y": 0, "w": 0, "h": 0}
        rule["target_bgr"] = [int(self.bgr[0]), int(self.bgr[1]), int(self.bgr[2])]
        if "tolerance" not in rule:
            rule["tolerance"] = 5
        if "cooldown_sec" not in rule:
            rule["cooldown_sec"] = 1.0
        self.sd.cfg.pixel_rules = list(self.sd._pixel_rules)
        if hasattr(self.sd, "_render_pixel_cards"):
            self.sd._render_pixel_cards()
            self.sd._refresh_action_events()
        name = str(rule.get("name") or f"rule{idx+1}")
        return f"pixel:{name}"

    def _add_rule(self):
        name = f"rule{len(self.sd._pixel_rules)+1}"
        self.sd._pixel_rules.append({
            "id": f"pixel_{uuid.uuid4().hex}",
            "name": name,
            "enabled": True,
            "mode": "pixel",
            "x": int(self.lx),
            "y": int(self.ly),
            "sample": 1,
            "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
            "target_bgr": [int(self.bgr[0]), int(self.bgr[1]), int(self.bgr[2])],
            "tolerance": 5,
            "window_frames": 1,
            "consecutive_needed": 1,
            "cooldown_sec": 1.0
        })
        self.sd.cfg.pixel_rules = list(self.sd._pixel_rules)
        self._reload_rules()
        self._open_actions_for_rule(len(self.sd._pixel_rules) - 1)

    def _on_rule_clicked(self, item):
        row = self.lst_rules.row(item)
        self._open_actions_for_rule(row)

    def _open_actions_for_rule(self, row: int):
        event = self._apply_to_rule(row)
        if not event:
            return
        dlg = PixelActionsDialog(self, self.sd, event, default_pos=self._default_pos)
        self.close()
        dlg.exec()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._safe_close()
            event.accept()
            return
        return super().keyPressEvent(event)
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
VK_LBUTTON = 0x01
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_F9 = 0x78


def _key_pressed(vk: int) -> bool:
    try:
        state = _user32.GetAsyncKeyState(int(vk))
    except Exception:
        return False
    return bool(state & 0x8000) or bool(state & 0x0001)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


ULONG_PTR = getattr(wintypes, "ULONG_PTR", ctypes.c_size_t)


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


LowLevelMouseProc = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class _MouseHotkeyEmitter(QObject):
    roi_requested = pyqtSignal()
    pixel_requested = pyqtSignal()


class GlobalMouseHook:
    def __init__(self, emitter: _MouseHotkeyEmitter, is_busy: Callable[[], bool]):
        self._emitter = emitter
        self._is_busy = is_busy
        self._hook = None
        self._proc = None
        self._thread = None
        self._thread_id = 0
        self._stop = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)

    def _run(self):
        self._thread_id = int(_kernel32.GetCurrentThreadId())

        @LowLevelMouseProc
        def _callback(nCode, wParam, lParam):
            if nCode == 0 and wParam == WM_LBUTTONDOWN:
                if not self._is_busy():
                    ctrl = (_user32.GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0
                    shift = (_user32.GetAsyncKeyState(VK_SHIFT) & 0x8000) != 0
                    alt = (_user32.GetAsyncKeyState(VK_MENU) & 0x8000) != 0
                    if ctrl and shift:
                        self._emitter.roi_requested.emit()
                    elif alt and shift:
                        self._emitter.pixel_requested.emit()
            return _user32.CallNextHookEx(self._hook, nCode, wParam, lParam)

        self._proc = _callback
        hmod = _kernel32.GetModuleHandleW(None)
        self._hook = _user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, hmod, 0)
        if not self._hook:
            return

        msg = MSG()
        while not self._stop.is_set():
            r = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break

        try:
            if self._hook:
                _user32.UnhookWindowsHookEx(self._hook)
        except Exception:
            pass

class QuickRoiOverlay(QWidget):
    _instances = []

    def __init__(
        self,
        monitor_index: int,
        bgr_frame: np.ndarray,
        roi_items: List[Tuple[str, str]],
        on_pick: Callable[[str, Rect], None],
    ):
        super().__init__(None)
        self.monitor_index = monitor_index
        self.frame = bgr_frame
        self.roi_items = roi_items
        self.on_pick = on_pick
        self.start = None
        self.end = None
        self.selection = Rect()
        self._qimg = bgr_to_qimage(self.frame)
        self._menu = None
        self._closing = False
        self._esc_timer = QTimer(self)
        self._esc_timer.timeout.connect(self._poll_esc)
        self._event_filter_installed = False
        QuickRoiOverlay._instances.append(self)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        with mss.mss() as sct:
            mons = sct.monitors
            if monitor_index == 0:
                rect = QGuiApplication.primaryScreen().virtualGeometry()
                self.setGeometry(rect)
            elif 0 < monitor_index < len(mons):
                mon = mons[monitor_index]
                self.setGeometry(mon["left"], mon["top"], mon["width"], mon["height"])
            else:
                self.showFullScreen()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._qimg is not None:
            painter.drawImage(0, 0, self._qimg)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if self.start and self.end:
            x1, y1 = self.start
            x2, y2 = self.end
            x, y = min(x1, x2), min(y1, y2)
            w, h = abs(x2 - x1), abs(y2 - y1)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(x, y, w, h, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor("#facc15"), 2))
            painter.drawRect(x, y, w, h)

    def begin_at_global(self, pos):
        local = self.mapFromGlobal(pos)
        self.start = (int(local.x()), int(local.y()))
        self.end = self.start
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def showEvent(self, event):
        QTimer.singleShot(0, self._grab_inputs)
        if not self._esc_timer.isActive():
            self._esc_timer.start(30)
        try:
            app = QApplication.instance()
            if app and not self._event_filter_installed:
                app.installEventFilter(self)
                self._event_filter_installed = True
        except Exception:
            pass
        try:
            self.raise_()
            self.activateWindow()
            self.setFocus()
        except Exception:
            pass
        return super().showEvent(event)

    def closeEvent(self, event):
        try:
            self.releaseMouse()
            self.releaseKeyboard()
        except Exception:
            pass
        try:
            if self._esc_timer.isActive():
                self._esc_timer.stop()
        except Exception:
            pass
        try:
            app = QApplication.instance()
            if app and self._event_filter_installed:
                app.removeEventFilter(self)
                self._event_filter_installed = False
        except Exception:
            pass
        self._menu = None
        try:
            if self in QuickRoiOverlay._instances:
                QuickRoiOverlay._instances.remove(self)
        except Exception:
            pass
        return super().closeEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._safe_close()
                return True
        return super().eventFilter(obj, event)

    def _grab_inputs(self):
        if not self.isVisible():
            return
        try:
            self.grabMouse()
            self.grabKeyboard()
        except Exception:
            pass

    def _poll_esc(self):
        try:
            if _key_pressed(0x1B):
                QuickRoiOverlay.close_all()
        except Exception:
            pass

    def mousePressEvent(self, event):
        if self._closing:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._safe_close()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.start = (int(event.position().x()), int(event.position().y()))
            self.end = self.start
            self.update()

    def mouseMoveEvent(self, event):
        if self._closing:
            return
        if self.start is not None:
            self.end = (int(event.position().x()), int(event.position().y()))
            self.update()

    def mouseReleaseEvent(self, event):
        if self._closing:
            return
        if event.button() != Qt.MouseButton.LeftButton or not self.start or not self.end:
            return
        x1, y1 = self.start
        x2, y2 = self.end
        x, y = min(x1, x2), min(y1, y2)
        w, h = abs(x2 - x1), abs(y2 - y1)
        self.selection = Rect(x=x, y=y, w=w, h=h)
        if not self.selection.valid():
            self._safe_close()
            return
        try:
            self.releaseMouse()
            self.releaseKeyboard()
        except Exception:
            pass
        menu = QMenu()
        menu.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        action_map = {}
        for label, key in self.roi_items:
            act = menu.addAction(label)
            action_map[act] = key
        self._menu = menu
        act = menu.exec(QCursor.pos())
        if act in action_map:
            self.on_pick(action_map[act], self.selection)
        self._menu = None
        self._safe_close()

    def _safe_close(self):
        if self._closing:
            return
        self._closing = True
        if self._menu is not None:
            try:
                self._menu.close()
            except Exception:
                pass
            self._menu = None
        try:
            self.hide()
        except Exception:
            pass
        try:
            self.close()
        except RuntimeError:
            pass

    @classmethod
    def close_all(cls):
        for inst in list(cls._instances):
            try:
                inst._safe_close()
            except Exception:
                pass


# -----------------------------
# App controller
# -----------------------------
class Controller(QObject):
    ui_update = pyqtSignal(dict)
    status_update = pyqtSignal(str)

    def __init__(self, cfg: AppConfig):
        super().__init__()
        self.cfg = cfg
        self._player_img_cache: Dict[str, Optional[np.ndarray]] = {}
        self._round_seen = False
        self._time_seen = False
        self._last_blue_id: Optional[str] = None
        self._last_red_id: Optional[str] = None

    def read_palette_test_once(self):
        # Read player palette colors from configured ROIs.
        if not HAS_MEDIAPIPE:
            self.status_update.emit("mediapipe \uC5C6\uC74C: ROI \uC774\uBBF8\uC9C0\uC758 \uC804\uCCB4 \uC0C9\uC744 \uC0AC\uC6A9(\uC2E4\uD589\uC740 \uAC00\uB2A5)")
        self.status_update.emit("\uC120\uC218 \uD314\uB808\uD2B8 \uC2DC\uC791...")
        result = self._read_player_palettes()
        if result:
            self.ui_update.emit(result)
        self.status_update.emit("팔레트 업데이트 완료")

    def _load_player_image(self, path: str) -> Optional[np.ndarray]:
        path = (path or "").strip()
        if not path:
            return None
        path = resolve_player_image_path(path)
        cached = self._player_img_cache.get(path)
        if cached is not None:
            return cached
        if not os.path.exists(path):
            try:
                logging.warning("Player image not found: %s", path)
            except Exception:
                pass
            self._player_img_cache[path] = None
            return None
        try:
            size = os.path.getsize(path)
            if size <= 0:
                logging.warning("Player image is empty: %s", path)
        except Exception:
            pass
        try:
            img = safe_cv2_imread(path, cv2.IMREAD_UNCHANGED)
        except Exception:
            img = None
        if img is None:
            try:
                qimg = QImage(path)
                if not qimg.isNull():
                    img = qimage_to_bgr(qimg)
            except Exception:
                img = None
        if img is None:
            try:
                logging.warning("Player image load failed: %s", path)
            except Exception:
                pass
        self._player_img_cache[path] = img
        return img

    def _read_player_palettes(self) -> dict:
        # Palette capture is optional because it can be expensive.
        if not bool(getattr(self.cfg, "capture_player_images", True)):
            return {}
        left_pals: List[List[Tuple[int, int, int]]] = []
        right_pals: List[List[Tuple[int, int, int]]] = []
        last_left = None
        last_right = None

        for _ in range(max(1, self.cfg.palette.frames)):
            if self.cfg.roi_left_player.valid():
                last_left = capture_roi_np_global(self.cfg.roi_left_player)
                left_roi = last_left
                pal = extract_palette_bgr(
                    left_roi,
                    k=self.cfg.palette.k_colors,
                    mask_thresh=self.cfg.palette.mask_thresh,
                    max_pixels=self.cfg.palette.max_pixels,
                    min_v_cut=self.cfg.palette.min_v_cut
                )
                if pal:
                    left_pals.append(pal)

            if self.cfg.roi_right_player.valid():
                last_right = capture_roi_np_global(self.cfg.roi_right_player)
                right_roi = last_right
                pal = extract_palette_bgr(
                    right_roi,
                    k=self.cfg.palette.k_colors,
                    mask_thresh=self.cfg.palette.mask_thresh,
                    max_pixels=self.cfg.palette.max_pixels,
                    min_v_cut=self.cfg.palette.min_v_cut
                )
                if pal:
                    right_pals.append(pal)

            time.sleep(0.05)

        # Build result after all sampled frames are processed.
        out = {}
        if left_pals:
            out["blue_palette"] = left_pals[-1]
        if right_pals:
            out["red_palette"] = right_pals[-1]

        if bool(getattr(self.cfg, "capture_player_images", True)):
            if last_left is not None and self.cfg.roi_left_player.valid():
                left_roi = crop(last_left, self.cfg.roi_left_player)
                if left_roi is not None and left_roi.size > 0:
                    out["blue_player_img"] = left_roi
            if last_right is not None and self.cfg.roi_right_player.valid():
                right_roi = crop(last_right, self.cfg.roi_right_player)
                if right_roi is not None and right_roi.size > 0:
                    out["red_player_img"] = right_roi
        return out


def show_non_empty(s: str) -> str:
    return (s or "").strip()


def observe_unique(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for it in items:
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
    return out


# -----------------------------
# GUI: Palette widgets
# -----------------------------
class ColorBox(QLabel):
    def __init__(self, size: int = 18):
        super().__init__()
        self.setFixedSize(size, size)
        self.setStyleSheet("border: 1px solid #333; background: #444;")

    def set_bgr(self, bgr: Tuple[int, int, int]):
        b, g, r = bgr
        self.setStyleSheet(f"border: 1px solid #333; background: rgb({r},{g},{b});")


class PaletteRow(QWidget):
    def __init__(self, n: int = 5, box_size: int = 18):
        super().__init__()
        self.boxes: List[ColorBox] = [ColorBox(box_size) for _ in range(n)]
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        for b in self.boxes:
            lay.addWidget(b)
        self.setLayout(lay)

    def set_palette(self, colors_bgr: List[Tuple[int, int, int]]):
        # Fill unused palette boxes with placeholders.
        fill = list(colors_bgr[:len(self.boxes)])
        while len(fill) < len(self.boxes):
            fill.append((80, 80, 80))
        for box, bgr in zip(self.boxes, fill):
            box.set_bgr(bgr)


# -----------------------------
# GUI: QML Timer Window
# -----------------------------
class PlayerImageProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._raw_images: Dict[str, QImage] = {"blue": QImage(), "red": QImage()}
        self._mask_shape = "square"
        self._lock = threading.Lock()

    def set_mask_shape(self, shape: str) -> None:
        with self._lock:
            self._mask_shape = _normalize_player_mask(shape)

    def set_image(self, key: str, img: QImage) -> None:
        with self._lock:
            self._raw_images[key] = img.copy()

    def image(self, key: str) -> QImage:
        with self._lock:
            return self._raw_images.get(key, QImage()).copy()

    def _apply_mask(self, img: QImage) -> QImage:
        return img

    def requestImage(self, id_str: str, size: QSize, requestedSize: QSize = QSize()):
        key = (id_str or "").split("?", 1)[0]
        with self._lock:
            img = self._raw_images.get(key, QImage())
        if img.isNull():
            img = QImage(1, 1, QImage.Format.Format_RGBA8888)
            img.fill(Qt.GlobalColor.transparent)
        img = self._apply_mask(img)
        size.setWidth(img.width())
        size.setHeight(img.height())
        return img, img.size()


class TimerBackend(QObject):
    open_settings_requested = pyqtSignal()
    check_updates_requested = pyqtSignal()
    start_detection_requested = pyqtSignal()
    start_screen_detection_requested = pyqtSignal()
    toggle_pixel_detection_requested = pyqtSignal()
    toggle_log_detection_requested = pyqtSignal()
    select_player_requested = pyqtSignal(str)
    overlayVisibilityRequested = pyqtSignal(str, bool)
    trigger_test_requested = pyqtSignal()
    burstSfxRequested = pyqtSignal(str)
    failSfxRequested = pyqtSignal(str)
    profileRegisterRequested = pyqtSignal(str)
    profileEditRequested = pyqtSignal(str)
    chapterSyncNowRequested = pyqtSignal()
    chapterClearRequested = pyqtSignal()
    chapterExportRequested = pyqtSignal()
    hudDemoStopRequested = pyqtSignal()
    spectatorReplayRequested = pyqtSignal()
    spectatorFullDemoRequested = pyqtSignal()
    spectatorVsIntroTestRequested = pyqtSignal()
    roundIntroRequested = pyqtSignal()

    timeTextChanged = pyqtSignal()
    roundTextChanged = pyqtSignal()
    statusTextChanged = pyqtSignal()
    restModeChanged = pyqtSignal()
    blueNameChanged = pyqtSignal()
    redNameChanged = pyqtSignal()
    arenaNameChanged = pyqtSignal()
    startLabelChanged = pyqtSignal()
    blueImageRevChanged = pyqtSignal()
    redImageRevChanged = pyqtSignal()
    blueWinStreakChanged = pyqtSignal()
    redWinStreakChanged = pyqtSignal()
    blueDamageTextChanged = pyqtSignal()
    redDamageTextChanged = pyqtSignal()
    blueTotalDamageTextChanged = pyqtSignal()
    redTotalDamageTextChanged = pyqtSignal()
    spectatorMatchTextChanged = pyqtSignal()
    spectatorRecentHitTextChanged = pyqtSignal()
    blueRecentHitTextChanged = pyqtSignal()
    redRecentHitTextChanged = pyqtSignal()
    blueComboHitTextChanged = pyqtSignal()
    redComboHitTextChanged = pyqtSignal()
    blueComboDamageTextChanged = pyqtSignal()
    redComboDamageTextChanged = pyqtSignal()
    spectatorRecentTextSizeChanged = pyqtSignal()
    bluePunishmentTextChanged = pyqtSignal()
    redPunishmentTextChanged = pyqtSignal()
    bluePunishmentMidChanged = pyqtSignal()
    redPunishmentMidChanged = pyqtSignal()
    bluePunishmentLongChanged = pyqtSignal()
    redPunishmentLongChanged = pyqtSignal()
    blueSpRatioChanged = pyqtSignal()
    redSpRatioChanged = pyqtSignal()
    blueRoundKnockdownsChanged = pyqtSignal()
    redRoundKnockdownsChanged = pyqtSignal()
    blueLogMetaTextChanged = pyqtSignal()
    redLogMetaTextChanged = pyqtSignal()
    cameraTextChanged = pyqtSignal()
    stunFlashRequested = pyqtSignal(str)
    spectatorEffectRequested = pyqtSignal(str, str)
    hitImpactRequested = pyqtSignal(str, float)
    winChangeReasonChanged = pyqtSignal()
    winChangeSideChanged = pyqtSignal()
    bluePlayerIdChanged = pyqtSignal()
    redPlayerIdChanged = pyqtSignal()
    bluePlayerRegisteredChanged = pyqtSignal()
    redPlayerRegisteredChanged = pyqtSignal()
    bluePlayerValidChanged = pyqtSignal()
    redPlayerValidChanged = pyqtSignal()
    blueFlagSourceChanged = pyqtSignal()
    redFlagSourceChanged = pyqtSignal()
    runningChanged = pyqtSignal(bool)
    effectSettingsChanged = pyqtSignal()
    overlayBgColorChanged = pyqtSignal()
    overlayUiBgOpacityChanged = pyqtSignal()
    overlayWindowOpacityChanged = pyqtSignal()
    overlayUiScaleChanged = pyqtSignal()
    overlayPresetChanged = pyqtSignal()
    overlayResetRequested = pyqtSignal()
    vsIntroResetRequested = pyqtSignal()
    overlayPlayerMaskChanged = pyqtSignal()
    overlayShowRoundChanged = pyqtSignal()
    overlayShowTimeChanged = pyqtSignal()
    overlayShowBlueImgChanged = pyqtSignal()
    overlayShowBlueNameChanged = pyqtSignal()
    overlayShowRedImgChanged = pyqtSignal()
    overlayShowRedNameChanged = pyqtSignal()
    overlayShowArenaNameChanged = pyqtSignal()
    overlayShowFlagsChanged = pyqtSignal()
    overlayShowCinematicChanged = pyqtSignal()
    overlayVsBackgroundChanged = pyqtSignal()
    overlayVsHoldMsChanged = pyqtSignal()
    overlayStyleChanged = pyqtSignal()
    qmlPreviewEnabledChanged = pyqtSignal()
    qmlEffectsEnabledChanged = pyqtSignal()
    broadcastSyncActiveChanged = pyqtSignal()
    screenDetectRunningChanged = pyqtSignal()
    pixelDetectRunningChanged = pyqtSignal()
    logDetectRunningChanged = pyqtSignal()
    hudDemoRunningChanged = pyqtSignal()
    restThirtySecondsReached = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._time_text = "3:00"
        self._round_text = "RD 1 of 3"
        self._status_text = "Ready"
        self._blue_name = "BLUE"
        self._red_name = "RED"
        self._arena_name = ""
        self._start_label = "Start"
        self._blue_image_rev = 0
        self._red_image_rev = 0
        self._blue_win_streak = 0
        self._red_win_streak = 0
        self._blue_damage_text = "DMG 0"
        self._red_damage_text = "DMG 0"
        self._blue_total_damage_text = "0"
        self._red_total_damage_text = "0"
        self._spectator_match_text = ""
        self._spectator_recent_hit_text = ""
        self._blue_recent_hit_text = ""
        self._red_recent_hit_text = ""
        self._blue_combo_hit_text = ""
        self._red_combo_hit_text = ""
        self._blue_combo_damage_text = ""
        self._red_combo_damage_text = ""
        self._spectator_recent_text_size = 23
        self._blue_punishment_text = ""
        self._red_punishment_text = ""
        self._blue_punishment_mid = 0.0
        self._red_punishment_mid = 0.0
        self._blue_punishment_long = 0.0
        self._red_punishment_long = 0.0
        self._blue_sp_ratio = 1.0
        self._red_sp_ratio = 1.0
        self._last_blue_round_damage_for_sp = 0.0
        self._last_red_round_damage_for_sp = 0.0
        self._last_rest_seconds_for_sp = None
        self._last_fight_seconds_for_sp = None
        self._sp_recovery_delay = {"blue": 0.0, "red": 0.0}
        self._blue_round_knockdowns = 0
        self._red_round_knockdowns = 0
        self._knockdown_round_key = None
        self._blue_log_meta_text = ""
        self._red_log_meta_text = ""
        self._camera_text = ""
        self._blue_player_id = ""
        self._red_player_id = ""
        self._blue_player_registered = False
        self._red_player_registered = False
        self._blue_player_valid = False
        self._red_player_valid = False
        self._blue_flag_source = ""
        self._red_flag_source = ""
        self._effect_settings = default_win_effects()
        self._overlay_bg_color = "transparent"
        self._overlay_bg_opacity = 0.0
        self._overlay_ui_bg_opacity = 0.75
        self._overlay_window_opacity = 1.0
        self._overlay_ui_scale = 1.0
        self._overlay_preset = "classic"
        self._overlay_player_mask = "square"
        self._overlay_show_round = True
        self._overlay_show_time = True
        self._overlay_show_blue_img = True
        self._overlay_show_blue_name = True
        self._overlay_show_red_img = True
        self._overlay_show_red_name = True
        self._overlay_show_arena_name = True
        self._overlay_show_flags = True
        self._overlay_show_cinematic = True
        self._overlay_vs_bg_path = ""
        self._overlay_vs_bg_opacity = 1.0
        self._overlay_vs_bg_by_arena: Dict[str, str] = {}
        self._overlay_vs_hold_sec = 2.85
        self._overlay_style = {
            "round": _default_overlay_style_round(),
            "time": _default_overlay_style_time(),
            "blue_name": _default_overlay_style_blue_name(),
            "red_name": _default_overlay_style_red_name(),
            "arena": _default_overlay_style_arena(),
        }
        self._qml_preview_enabled = True
        self._qml_effects_enabled = False
        self._broadcast_sync_active = False
        self._screen_detect_running = False
        self._pixel_detect_running = False
        self._log_detect_running = False
        self._hud_demo_running = False
        self._reset_cooldown_until = 0.0
        self._win_change_reason = ""
        self._win_change_side = ""

        self.total_rounds = 3
        self.current_round = 1
        self.seconds_left = 180
        self.round_duration_sec = 180
        self.rest_duration_sec = 60
        self.in_rest = False
        self.running = False
        self._qtimer = QTimer(self)
        self._qtimer.timeout.connect(self._tick)
        self._refresh_time()

    @pyqtProperty(str, notify=timeTextChanged)
    def timeText(self) -> str:
        return self._time_text

    @pyqtProperty(str, notify=roundTextChanged)
    def roundText(self) -> str:
        return self._round_text

    @pyqtProperty(str, notify=statusTextChanged)
    def statusText(self) -> str:
        return self._status_text

    @pyqtProperty(bool, notify=restModeChanged)
    def restMode(self) -> bool:
        return bool(self.in_rest)

    @pyqtProperty(str, notify=blueNameChanged)
    def blueName(self) -> str:
        return self._blue_name

    @pyqtProperty(str, notify=redNameChanged)
    def redName(self) -> str:
        return self._red_name

    @pyqtProperty(str, notify=arenaNameChanged)
    def arenaName(self) -> str:
        return self._arena_name

    @pyqtProperty(str, notify=startLabelChanged)
    def startLabel(self) -> str:
        return self._start_label

    @pyqtProperty(str, notify=overlayBgColorChanged)
    def overlayBgColor(self) -> str:
        return self._overlay_bg_color

    @pyqtProperty(float, notify=overlayBgColorChanged)
    def overlayBgOpacity(self) -> float:
        return float(self._overlay_bg_opacity)

    @pyqtProperty(float, notify=overlayUiBgOpacityChanged)
    def overlayUiBgOpacity(self) -> float:
        return float(self._overlay_ui_bg_opacity)

    @pyqtProperty(float, notify=overlayWindowOpacityChanged)
    def overlayWindowOpacity(self) -> float:
        return float(self._overlay_window_opacity)

    @pyqtProperty(float, notify=overlayUiScaleChanged)
    def overlayUiScale(self) -> float:
        return float(self._overlay_ui_scale)

    @pyqtProperty(str, notify=overlayPresetChanged)
    def overlayPreset(self) -> str:
        return str(self._overlay_preset or "classic")

    @pyqtProperty(str, notify=overlayPlayerMaskChanged)
    def overlayPlayerMask(self) -> str:
        return str(self._overlay_player_mask)

    @pyqtProperty(str, notify=winChangeReasonChanged)
    def winChangeReason(self) -> str:
        return str(self._win_change_reason or "")

    @pyqtProperty(str, notify=winChangeSideChanged)
    def winChangeSide(self) -> str:
        return str(self._win_change_side or "")

    def _set_win_change(self, reason: str, side: str):
        reason = str(reason or "")
        side = str(side or "")
        if reason != self._win_change_reason:
            self._win_change_reason = reason
            self.winChangeReasonChanged.emit()
        if side != self._win_change_side:
            self._win_change_side = side
            self.winChangeSideChanged.emit()

    @pyqtProperty(bool, notify=overlayShowRoundChanged)
    def overlayShowRound(self) -> bool:
        return bool(self._overlay_show_round)

    @pyqtProperty(bool, notify=overlayShowTimeChanged)
    def overlayShowTime(self) -> bool:
        return bool(self._overlay_show_time)

    @pyqtProperty(bool, notify=overlayShowBlueImgChanged)
    def overlayShowBlueImg(self) -> bool:
        return bool(self._overlay_show_blue_img)

    @pyqtProperty(bool, notify=overlayShowBlueNameChanged)
    def overlayShowBlueName(self) -> bool:
        return bool(self._overlay_show_blue_name)

    @pyqtProperty(bool, notify=overlayShowRedImgChanged)
    def overlayShowRedImg(self) -> bool:
        return bool(self._overlay_show_red_img)

    @pyqtProperty(bool, notify=overlayShowRedNameChanged)
    def overlayShowRedName(self) -> bool:
        return bool(self._overlay_show_red_name)

    @pyqtProperty(bool, notify=overlayShowArenaNameChanged)
    def overlayShowArenaName(self) -> bool:
        return bool(self._overlay_show_arena_name)

    @pyqtProperty(bool, notify=overlayShowFlagsChanged)
    def overlayShowFlags(self) -> bool:
        return bool(self._overlay_show_flags)

    @pyqtProperty(bool, notify=overlayShowCinematicChanged)
    def overlayShowCinematic(self) -> bool:
        return bool(self._overlay_show_cinematic)

    @pyqtProperty(str, notify=overlayVsBackgroundChanged)
    def overlayVsBackgroundSource(self) -> str:
        path = self._resolve_vs_background_path()
        if not path:
            return ""
        try:
            ab = os.path.abspath(path) if os.path.isabs(path) else os.path.abspath(os.path.join(get_app_base_dir(), path))
            return QUrl.fromLocalFile(ab).toString()
        except Exception:
            return ""

    @pyqtProperty(float, notify=overlayVsBackgroundChanged)
    def overlayVsBackgroundOpacity(self) -> float:
        return max(0.0, min(1.0, float(self._overlay_vs_bg_opacity if self._overlay_vs_bg_opacity is not None else 1.0)))

    @pyqtProperty(int, notify=overlayVsHoldMsChanged)
    def overlayVsHoldMs(self) -> int:
        try:
            sec = max(0.5, min(15.0, float(self._overlay_vs_hold_sec)))
        except Exception:
            sec = 2.85
        return int(sec * 1000)

    @pyqtProperty("QVariantMap", notify=overlayStyleChanged)
    def overlayStyle(self) -> dict:
        return dict(self._overlay_style or {})

    @pyqtProperty(bool, notify=broadcastSyncActiveChanged)
    def broadcastSyncActive(self) -> bool:
        return bool(self._broadcast_sync_active)

    @pyqtProperty(bool, notify=screenDetectRunningChanged)
    def screenDetectRunning(self) -> bool:
        return bool(self._screen_detect_running)

    @pyqtProperty(bool, notify=pixelDetectRunningChanged)
    def pixelDetectRunning(self) -> bool:
        return bool(self._pixel_detect_running)

    @pyqtProperty(bool, notify=logDetectRunningChanged)
    def logDetectRunning(self) -> bool:
        return bool(self._log_detect_running)

    @pyqtProperty(bool, notify=hudDemoRunningChanged)
    def hudDemoRunning(self) -> bool:
        return bool(self._hud_demo_running)

    @pyqtProperty(int, notify=blueImageRevChanged)
    def blueImageRev(self) -> int:
        return self._blue_image_rev

    @pyqtProperty(int, notify=redImageRevChanged)
    def redImageRev(self) -> int:
        return self._red_image_rev

    @pyqtProperty(int, notify=blueWinStreakChanged)
    def blueWinStreak(self) -> int:
        return int(self._blue_win_streak)

    @pyqtProperty(int, notify=redWinStreakChanged)
    def redWinStreak(self) -> int:
        return int(self._red_win_streak)

    @pyqtProperty(str, notify=blueDamageTextChanged)
    def blueDamageText(self) -> str:
        return str(self._blue_damage_text or "")

    @pyqtProperty(str, notify=redDamageTextChanged)
    def redDamageText(self) -> str:
        return str(self._red_damage_text or "")

    @pyqtProperty(str, notify=blueTotalDamageTextChanged)
    def blueTotalDamageText(self) -> str:
        return str(self._blue_total_damage_text or "0")

    @pyqtProperty(str, notify=redTotalDamageTextChanged)
    def redTotalDamageText(self) -> str:
        return str(self._red_total_damage_text or "0")

    @pyqtProperty(str, notify=spectatorMatchTextChanged)
    def spectatorMatchText(self) -> str:
        return str(self._spectator_match_text or "")

    @pyqtProperty(str, notify=spectatorRecentHitTextChanged)
    def spectatorRecentHitText(self) -> str:
        return str(self._spectator_recent_hit_text or "")

    @pyqtProperty(str, notify=blueRecentHitTextChanged)
    def blueRecentHitText(self) -> str:
        return str(self._blue_recent_hit_text or "")

    @pyqtProperty(str, notify=redRecentHitTextChanged)
    def redRecentHitText(self) -> str:
        return str(self._red_recent_hit_text or "")

    @pyqtProperty(str, notify=blueComboHitTextChanged)
    def blueComboHitText(self) -> str:
        return str(self._blue_combo_hit_text or "")

    @pyqtProperty(str, notify=redComboHitTextChanged)
    def redComboHitText(self) -> str:
        return str(self._red_combo_hit_text or "")

    @pyqtProperty(str, notify=blueComboDamageTextChanged)
    def blueComboDamageText(self) -> str:
        return str(self._blue_combo_damage_text or "")

    @pyqtProperty(str, notify=redComboDamageTextChanged)
    def redComboDamageText(self) -> str:
        return str(self._red_combo_damage_text or "")

    @pyqtProperty(int, notify=spectatorRecentTextSizeChanged)
    def spectatorRecentTextSize(self) -> int:
        return int(self._spectator_recent_text_size or 23)

    def set_spectator_recent_text_size(self, size: Optional[int]):
        try:
            v = int(size if size is not None else 23)
        except Exception:
            v = 23
        v = max(10, min(80, v))
        if v != int(self._spectator_recent_text_size or 23):
            self._spectator_recent_text_size = v
            self.spectatorRecentTextSizeChanged.emit()

    @pyqtSlot(str)
    def clear_combo_display(self, side: str):
        side = str(side or "").lower().strip()
        if side in ("blue", "all"):
            if self._blue_combo_hit_text:
                self._blue_combo_hit_text = ""
                self.blueComboHitTextChanged.emit()
            if self._blue_combo_damage_text:
                self._blue_combo_damage_text = ""
                self.blueComboDamageTextChanged.emit()
        if side in ("red", "all"):
            if self._red_combo_hit_text:
                self._red_combo_hit_text = ""
                self.redComboHitTextChanged.emit()
            if self._red_combo_damage_text:
                self._red_combo_damage_text = ""
                self.redComboDamageTextChanged.emit()

    @pyqtProperty(str, notify=bluePunishmentTextChanged)
    def bluePunishmentText(self) -> str:
        return str(self._blue_punishment_text or "")

    @pyqtProperty(str, notify=redPunishmentTextChanged)
    def redPunishmentText(self) -> str:
        return str(self._red_punishment_text or "")

    @pyqtProperty(float, notify=bluePunishmentMidChanged)
    def bluePunishmentMid(self) -> float:
        return float(self._blue_punishment_mid or 0.0)

    @pyqtProperty(float, notify=redPunishmentMidChanged)
    def redPunishmentMid(self) -> float:
        return float(self._red_punishment_mid or 0.0)

    @pyqtProperty(float, notify=bluePunishmentLongChanged)
    def bluePunishmentLong(self) -> float:
        return float(self._blue_punishment_long or 0.0)

    @pyqtProperty(float, notify=redPunishmentLongChanged)
    def redPunishmentLong(self) -> float:
        return float(self._red_punishment_long or 0.0)

    @pyqtProperty(float, notify=blueSpRatioChanged)
    def blueSpRatio(self) -> float:
        return max(0.0, min(1.0, float(self._blue_sp_ratio or 0.0)))

    @pyqtProperty(float, notify=redSpRatioChanged)
    def redSpRatio(self) -> float:
        return max(0.0, min(1.0, float(self._red_sp_ratio or 0.0)))

    @pyqtProperty(int, notify=blueRoundKnockdownsChanged)
    def blueRoundKnockdowns(self) -> int:
        return int(self._blue_round_knockdowns or 0)

    @pyqtProperty(int, notify=redRoundKnockdownsChanged)
    def redRoundKnockdowns(self) -> int:
        return int(self._red_round_knockdowns or 0)

    @pyqtProperty(str, notify=blueLogMetaTextChanged)
    def blueLogMetaText(self) -> str:
        return str(self._blue_log_meta_text or "")

    @pyqtProperty(str, notify=redLogMetaTextChanged)
    def redLogMetaText(self) -> str:
        return str(self._red_log_meta_text or "")

    @pyqtProperty(str, notify=cameraTextChanged)
    def cameraText(self) -> str:
        return str(self._camera_text or "")

    @pyqtProperty(str, notify=bluePlayerIdChanged)
    def bluePlayerId(self) -> str:
        return str(self._blue_player_id or "")

    @pyqtProperty(str, notify=redPlayerIdChanged)
    def redPlayerId(self) -> str:
        return str(self._red_player_id or "")

    @pyqtProperty(bool, notify=bluePlayerRegisteredChanged)
    def bluePlayerRegistered(self) -> bool:
        return bool(self._blue_player_registered)

    @pyqtProperty(bool, notify=redPlayerRegisteredChanged)
    def redPlayerRegistered(self) -> bool:
        return bool(self._red_player_registered)

    @pyqtProperty(bool, notify=bluePlayerValidChanged)
    def bluePlayerValid(self) -> bool:
        return bool(self._blue_player_valid)

    @pyqtProperty(bool, notify=redPlayerValidChanged)
    def redPlayerValid(self) -> bool:
        return bool(self._red_player_valid)

    @pyqtProperty(str, notify=blueFlagSourceChanged)
    def blueFlagSource(self) -> str:
        return str(self._blue_flag_source or "")

    @pyqtProperty(str, notify=redFlagSourceChanged)
    def redFlagSource(self) -> str:
        return str(self._red_flag_source or "")

    @pyqtProperty("QVariantMap", notify=effectSettingsChanged)
    def effectSettings(self) -> dict:
        return dict(self._effect_settings or {})

    @pyqtProperty(bool, notify=qmlPreviewEnabledChanged)
    def qmlPreviewEnabled(self) -> bool:
        return bool(getattr(self, "_qml_preview_enabled", True))

    def set_qml_preview_enabled(self, enabled: bool):
        v = bool(enabled)
        if v == bool(getattr(self, "_qml_preview_enabled", True)):
            return
        self._qml_preview_enabled = v
        self.qmlPreviewEnabledChanged.emit()

    @pyqtProperty(bool, notify=qmlEffectsEnabledChanged)
    def qmlEffectsEnabled(self) -> bool:
        return bool(getattr(self, "_qml_effects_enabled", False))

    def set_qml_effects_enabled(self, enabled: bool):
        v = bool(enabled)
        if v == bool(getattr(self, "_qml_effects_enabled", False)):
            return
        self._qml_effects_enabled = v
        self.qmlEffectsEnabledChanged.emit()

    def set_status(self, s: str):
        if s is None:
            return
        self._status_text = s
        self.statusTextChanged.emit()

    def set_broadcast_sync_active(self, active: bool):
        v = bool(active)
        if v == self._broadcast_sync_active:
            return
        self._broadcast_sync_active = v
        self.broadcastSyncActiveChanged.emit()

    @pyqtSlot(bool)
    def setBroadcastSyncActive(self, active: bool):
        # QML-friendly camelCase alias
        self.set_broadcast_sync_active(active)

    @pyqtSlot(float)
    def set_overlay_ui_scale(self, value: float):
        try:
            scale = float(value)
        except Exception:
            scale = 1.0
        if scale <= 0:
            scale = 1.0
        if abs(scale - self._overlay_ui_scale) < 1e-6:
            return
        self._overlay_ui_scale = scale
        self.overlayUiScaleChanged.emit()

    @pyqtSlot(float)
    def setOverlayUiScale(self, value: float):
        # QML-friendly camelCase alias
        self.set_overlay_ui_scale(value)

    def set_palettes(self, _blue_pal, _red_pal):
        return

    def set_names(self, blue: Optional[str], red: Optional[str]):
        if blue is not None:
            blue_text = str(blue)
            if blue_text != self._blue_name:
                self._blue_name = blue_text
                self.blueNameChanged.emit()
        if red is not None:
            red_text = str(red)
            if red_text != self._red_name:
                self._red_name = red_text
                self.redNameChanged.emit()

    def set_arena_name(self, name: Optional[str]):
        name = str(name or "").strip()
        if name != self._arena_name:
            self._arena_name = name
            self.arenaNameChanged.emit()
            self.overlayVsBackgroundChanged.emit()

    def set_round_time(self, current_round: Optional[int], total_rounds: Optional[int], seconds_left: Optional[int]):
        if total_rounds:
            self.total_rounds = int(total_rounds)
        if current_round:
            next_round = int(current_round)
            prev_key = self._knockdown_round_key
            next_key = (next_round, int(self.total_rounds or 0))
            if prev_key is not None and next_key != prev_key:
                if int(self._blue_round_knockdowns or 0) != 0:
                    self._blue_round_knockdowns = 0
                    self.blueRoundKnockdownsChanged.emit()
                if int(self._red_round_knockdowns or 0) != 0:
                    self._red_round_knockdowns = 0
                    self.redRoundKnockdownsChanged.emit()
            self._knockdown_round_key = next_key
            self.current_round = next_round
        if seconds_left is not None:
            self.seconds_left = max(0, int(seconds_left))
            if self.in_rest:
                self._sp_apply_rest_recovery(self.seconds_left)
                self._sp_apply_fight_recovery(None)
            else:
                self._sp_apply_fight_recovery(self.seconds_left)
                self._sp_apply_rest_recovery(None)
        self._refresh_time()

    def set_log_rest_mode(self, is_rest: bool):
        self._set_rest(bool(is_rest))
        if bool(is_rest):
            self._sp_apply_rest_recovery(self.seconds_left)
            self._sp_apply_fight_recovery(None)
        else:
            self._sp_apply_rest_recovery(None)
            self._sp_apply_fight_recovery(self.seconds_left)
        self._refresh_time()

    def apply_timer_settings(
        self,
        total_rounds: Optional[int],
        round_sec: Optional[int],
        rest_sec: Optional[int],
        current_round: Optional[int],
        seconds_left: Optional[int],
    ):
        if total_rounds is not None:
            self.total_rounds = max(1, int(total_rounds))
        if round_sec is not None:
            self.round_duration_sec = max(1, int(round_sec))
        if rest_sec is not None:
            self.rest_duration_sec = max(1, int(rest_sec))
        if current_round is not None:
            self.current_round = max(1, int(current_round))
        if seconds_left is not None:
            self.seconds_left = max(0, int(seconds_left))
        self._refresh_time()

    def bump_blue_image(self):
        self._blue_image_rev += 1
        self.blueImageRevChanged.emit()

    def bump_red_image(self):
        self._red_image_rev += 1
        self.redImageRevChanged.emit()

    def set_win_streaks(self, blue: int, red: int):
        blue = max(0, int(blue))
        red = max(0, int(red))
        if blue != self._blue_win_streak:
            self._blue_win_streak = blue
            self.blueWinStreakChanged.emit()
        if red != self._red_win_streak:
            self._red_win_streak = red
            self.redWinStreakChanged.emit()

    def _set_sp_ratio(self, side: str, value: float):
        value = max(0.0, min(1.0, float(value if value is not None else 1.0)))
        if side == "blue":
            if abs(value - float(self._blue_sp_ratio or 0.0)) > 0.0005:
                self._blue_sp_ratio = value
                self.blueSpRatioChanged.emit()
        elif side == "red":
            if abs(value - float(self._red_sp_ratio or 0.0)) > 0.0005:
                self._red_sp_ratio = value
                self.redSpRatioChanged.emit()

    def _sp_apply_damage_delta(self, side: str, delta_damage: float):
        try:
            delta = max(0.0, float(delta_damage or 0.0))
        except Exception:
            delta = 0.0
        if delta <= 0:
            return
        if side in self._sp_recovery_delay:
            self._sp_recovery_delay[side] = 1.2
        spend = delta / 3000.0
        if side == "blue":
            self._set_sp_ratio("blue", float(self._blue_sp_ratio or 0.0) - spend)
        elif side == "red":
            self._set_sp_ratio("red", float(self._red_sp_ratio or 0.0) - spend)

    def _sp_apply_fight_recovery(self, seconds_left: Optional[int]):
        if self.in_rest or seconds_left is None:
            self._last_fight_seconds_for_sp = None
            return
        try:
            cur = max(0, int(seconds_left))
        except Exception:
            return
        if self._last_fight_seconds_for_sp is None:
            self._last_fight_seconds_for_sp = cur
            return
        prev = int(self._last_fight_seconds_for_sp)
        elapsed = max(0, prev - cur)
        self._last_fight_seconds_for_sp = cur
        if elapsed <= 0:
            return
        round_sec = max(1, int(self.round_duration_sec or 180))
        for side in ("blue", "red"):
            delay = max(0.0, float((self._sp_recovery_delay or {}).get(side, 0.0) or 0.0))
            recover_elapsed = float(elapsed)
            if delay > 0:
                used_delay = min(delay, recover_elapsed)
                delay -= used_delay
                recover_elapsed -= used_delay
                self._sp_recovery_delay[side] = delay
            if recover_elapsed <= 0:
                continue
            gain = 0.30 * (recover_elapsed / float(round_sec))
            current = float(self._blue_sp_ratio if side == "blue" else self._red_sp_ratio)
            self._set_sp_ratio(side, current + gain)

    def _sp_apply_rest_recovery(self, seconds_left: Optional[int]):
        if not self.in_rest or seconds_left is None:
            self._last_rest_seconds_for_sp = None
            return
        try:
            cur = max(0, int(seconds_left))
        except Exception:
            return
        if self._last_rest_seconds_for_sp is None:
            self._last_rest_seconds_for_sp = cur
            return
        prev = int(self._last_rest_seconds_for_sp)
        elapsed = max(0, prev - cur)
        self._last_rest_seconds_for_sp = cur
        if elapsed <= 0:
            return
        rest_sec = max(1, int(self.rest_duration_sec or 60))
        gain = 0.60 * (float(elapsed) / float(rest_sec))
        self._set_sp_ratio("blue", float(self._blue_sp_ratio or 0.0) + gain)
        self._set_sp_ratio("red", float(self._red_sp_ratio or 0.0) + gain)

    def reset_spectator_sp(self):
        self._last_blue_round_damage_for_sp = 0.0
        self._last_red_round_damage_for_sp = 0.0
        self._last_rest_seconds_for_sp = None
        self._last_fight_seconds_for_sp = None
        self._sp_recovery_delay = {"blue": 0.0, "red": 0.0}
        self._set_sp_ratio("blue", 1.0)
        self._set_sp_ratio("red", 1.0)

    def set_spectator_damage(self, blue_dealt: float, red_dealt: float):
        def fmt(v: float) -> str:
            try:
                f = max(0.0, float(v))
            except Exception:
                f = 0.0
            return f"DMG {f:.0f}"

        try:
            blue_f = max(0.0, float(blue_dealt or 0.0))
        except Exception:
            blue_f = 0.0
        try:
            red_f = max(0.0, float(red_dealt or 0.0))
        except Exception:
            red_f = 0.0
        if blue_f >= float(self._last_blue_round_damage_for_sp or 0.0):
            self._sp_apply_damage_delta("blue", blue_f - float(self._last_blue_round_damage_for_sp or 0.0))
        self._last_blue_round_damage_for_sp = blue_f
        if red_f >= float(self._last_red_round_damage_for_sp or 0.0):
            self._sp_apply_damage_delta("red", red_f - float(self._last_red_round_damage_for_sp or 0.0))
        self._last_red_round_damage_for_sp = red_f

        b = fmt(blue_dealt)
        r = fmt(red_dealt)
        if b != self._blue_damage_text:
            self._blue_damage_text = b
            self.blueDamageTextChanged.emit()
        if r != self._red_damage_text:
            self._red_damage_text = r
            self.redDamageTextChanged.emit()

    def set_spectator_total_damage(self, blue_dealt: float, red_dealt: float):
        def fmt(v: float) -> str:
            try:
                f = max(0.0, float(v))
            except Exception:
                f = 0.0
            return f"{f:.0f}"

        b = fmt(blue_dealt)
        r = fmt(red_dealt)
        if b != self._blue_total_damage_text:
            self._blue_total_damage_text = b
            self.blueTotalDamageTextChanged.emit()
        if r != self._red_total_damage_text:
            self._red_total_damage_text = r
            self.redTotalDamageTextChanged.emit()

    def trigger_stun_flash(self, side: str):
        side = str(side or "").lower().strip()
        if side in ("blue", "red"):
            self.stunFlashRequested.emit(side)

    def trigger_spectator_effect(self, side: str, kind: str):
        side = str(side or "").lower().strip()
        kind = str(kind or "").lower().strip()
        if side in ("blue", "red") and kind in ("stun", "knockdown", "tko"):
            if kind in ("knockdown", "tko"):
                if side == "blue":
                    new_count = max(0, min(3, int(self._blue_round_knockdowns or 0) + 1))
                    if new_count != int(self._blue_round_knockdowns or 0):
                        self._blue_round_knockdowns = new_count
                        self.blueRoundKnockdownsChanged.emit()
                elif side == "red":
                    new_count = max(0, min(3, int(self._red_round_knockdowns or 0) + 1))
                    if new_count != int(self._red_round_knockdowns or 0):
                        self._red_round_knockdowns = new_count
                        self.redRoundKnockdownsChanged.emit()
                if side == "blue" and abs(float(self._blue_punishment_mid or 0.0) - 100.0) > 0.001:
                    self._blue_punishment_mid = 100.0
                    self.bluePunishmentMidChanged.emit()
                elif side == "red" and abs(float(self._red_punishment_mid or 0.0) - 100.0) > 0.001:
                    self._red_punishment_mid = 100.0
                    self.redPunishmentMidChanged.emit()
            self.spectatorEffectRequested.emit(side, kind)

    def trigger_hit_impact(self, side: str, damage: float):
        side = str(side or "").lower().strip()
        try:
            dmg = float(damage)
        except Exception:
            dmg = 0.0
        if side in ("blue", "red"):
            self.hitImpactRequested.emit(side, max(0.0, dmg))

    def set_spectator_log_info(self, info: Optional[dict]):
        info = dict(info or {})

        def set_text(attr: str, signal, value: object):
            text = str(value or "")
            if getattr(self, attr) != text:
                setattr(self, attr, text)
                signal.emit()

        def set_float(attr: str, signal, value: object):
            try:
                val = max(0.0, min(100.0, float(value or 0.0)))
            except Exception:
                val = 0.0
            if abs(float(getattr(self, attr) or 0.0) - val) > 0.001:
                setattr(self, attr, val)
                signal.emit()

        set_text("_spectator_match_text", self.spectatorMatchTextChanged, info.get("match_text", ""))
        set_text("_spectator_recent_hit_text", self.spectatorRecentHitTextChanged, info.get("recent_hit_text", ""))
        set_text("_blue_recent_hit_text", self.blueRecentHitTextChanged, info.get("blue_recent_hit_text", ""))
        set_text("_red_recent_hit_text", self.redRecentHitTextChanged, info.get("red_recent_hit_text", ""))
        if "blue_combo_hit_text" in info:
            set_text("_blue_combo_hit_text", self.blueComboHitTextChanged, info.get("blue_combo_hit_text", ""))
        if "red_combo_hit_text" in info:
            set_text("_red_combo_hit_text", self.redComboHitTextChanged, info.get("red_combo_hit_text", ""))
        if "blue_combo_damage_text" in info:
            set_text("_blue_combo_damage_text", self.blueComboDamageTextChanged, info.get("blue_combo_damage_text", ""))
        if "red_combo_damage_text" in info:
            set_text("_red_combo_damage_text", self.redComboDamageTextChanged, info.get("red_combo_damage_text", ""))
        if "blue_punishment_text" in info:
            set_text("_blue_punishment_text", self.bluePunishmentTextChanged, info.get("blue_punishment_text", ""))
        if "red_punishment_text" in info:
            set_text("_red_punishment_text", self.redPunishmentTextChanged, info.get("red_punishment_text", ""))
        if "blue_punishment_mid" in info:
            set_float("_blue_punishment_mid", self.bluePunishmentMidChanged, info.get("blue_punishment_mid", 0.0))
        if "red_punishment_mid" in info:
            set_float("_red_punishment_mid", self.redPunishmentMidChanged, info.get("red_punishment_mid", 0.0))
        if "blue_punishment_long" in info:
            set_float("_blue_punishment_long", self.bluePunishmentLongChanged, info.get("blue_punishment_long", 0.0))
        if "red_punishment_long" in info:
            set_float("_red_punishment_long", self.redPunishmentLongChanged, info.get("red_punishment_long", 0.0))
        if "blue_round_knockdowns" in info:
            try:
                val = max(0, min(3, int(info.get("blue_round_knockdowns") or 0)))
            except Exception:
                val = 0
            if val != int(self._blue_round_knockdowns or 0):
                self._blue_round_knockdowns = val
                self.blueRoundKnockdownsChanged.emit()
        if "red_round_knockdowns" in info:
            try:
                val = max(0, min(3, int(info.get("red_round_knockdowns") or 0)))
            except Exception:
                val = 0
            if val != int(self._red_round_knockdowns or 0):
                self._red_round_knockdowns = val
                self.redRoundKnockdownsChanged.emit()
        set_text("_blue_log_meta_text", self.blueLogMetaTextChanged, info.get("blue_meta_text", ""))
        set_text("_red_log_meta_text", self.redLogMetaTextChanged, info.get("red_meta_text", ""))
        set_text("_camera_text", self.cameraTextChanged, info.get("camera_text", ""))

    def set_player_info(
        self,
        blue_id: Optional[str],
        red_id: Optional[str],
        blue_registered: Optional[bool],
        red_registered: Optional[bool],
        blue_valid: Optional[bool],
        red_valid: Optional[bool],
    ):
        b_id = str(blue_id or "")
        r_id = str(red_id or "")
        if b_id != self._blue_player_id:
            self._blue_player_id = b_id
            self.bluePlayerIdChanged.emit()
        if r_id != self._red_player_id:
            self._red_player_id = r_id
            self.redPlayerIdChanged.emit()
        if blue_registered is not None and bool(blue_registered) != self._blue_player_registered:
            self._blue_player_registered = bool(blue_registered)
            self.bluePlayerRegisteredChanged.emit()
        if red_registered is not None and bool(red_registered) != self._red_player_registered:
            self._red_player_registered = bool(red_registered)
            self.redPlayerRegisteredChanged.emit()
        if blue_valid is not None and bool(blue_valid) != self._blue_player_valid:
            self._blue_player_valid = bool(blue_valid)
            self.bluePlayerValidChanged.emit()
        if red_valid is not None and bool(red_valid) != self._red_player_valid:
            self._red_player_valid = bool(red_valid)
            self.redPlayerValidChanged.emit()

    def set_player_flags(self, blue_source: Optional[str], red_source: Optional[str]):
        b = str(blue_source or "")
        r = str(red_source or "")
        if b != self._blue_flag_source:
            self._blue_flag_source = b
            self.blueFlagSourceChanged.emit()
        if r != self._red_flag_source:
            self._red_flag_source = r
            self.redFlagSourceChanged.emit()

    def set_effect_settings(self, settings: Optional[dict]):
        self._effect_settings = dict(settings or {})
        self.effectSettingsChanged.emit()

    def set_overlay_bg_color(self, color: Optional[str]):
        c = str(color or "transparent").strip()
        if not c:
            c = "transparent"
        if c != self._overlay_bg_color:
            self._overlay_bg_color = c
            self.overlayBgColorChanged.emit()

    @pyqtSlot(float)
    def set_overlay_bg_opacity(self, opacity: Optional[float]):
        try:
            v = float(opacity if opacity is not None else 0.0)
        except Exception:
            v = 0.0
        v = max(0.0, min(1.0, v))
        if v != self._overlay_bg_opacity:
            self._overlay_bg_opacity = v
            self.overlayBgColorChanged.emit()

    @pyqtSlot(float)
    def setOverlayBgOpacity(self, opacity: Optional[float]):
        # QML-friendly camelCase alias
        self.set_overlay_bg_opacity(opacity)

    @pyqtSlot(float)
    def set_overlay_ui_bg_opacity(self, opacity: Optional[float]):
        try:
            v = float(opacity if opacity is not None else 0.75)
        except Exception:
            v = 0.75
        v = max(0.0, min(1.0, v))
        if abs(float(self._overlay_ui_bg_opacity or 0.0) - v) > 0.0001:
            self._overlay_ui_bg_opacity = v
            self.overlayUiBgOpacityChanged.emit()

    @pyqtSlot(float)
    def setOverlayUiBgOpacity(self, opacity: Optional[float]):
        self.set_overlay_ui_bg_opacity(opacity)

    @pyqtSlot(float)
    def set_overlay_window_opacity(self, opacity: Optional[float]):
        try:
            v = float(opacity if opacity is not None else 1.0)
        except Exception:
            v = 1.0
        # 0.0이면 창을 다시 잡기 힘들어서 최소 20%는 남긴다.
        v = max(0.2, min(1.0, v))
        if v != self._overlay_window_opacity:
            self._overlay_window_opacity = v
            self.overlayWindowOpacityChanged.emit()

    @pyqtSlot(float)
    def setOverlayWindowOpacity(self, opacity: Optional[float]):
        self.set_overlay_window_opacity(opacity)

    def set_overlay_player_mask(self, mask: Optional[str]):
        v = _normalize_player_mask(mask)
        if v != self._overlay_player_mask:
            self._overlay_player_mask = v
            self.overlayPlayerMaskChanged.emit()

    def set_overlay_preset(self, preset: Optional[str]):
        v = str(preset or "classic").strip().lower()
        if v not in ("classic", "tekken8"):
            v = "classic"
        if v != self._overlay_preset:
            self._overlay_preset = v
            self.overlayPresetChanged.emit()

    def set_overlay_visibility(
        self,
        round_visible: Optional[bool] = None,
        time_visible: Optional[bool] = None,
        blue_img_visible: Optional[bool] = None,
        blue_name_visible: Optional[bool] = None,
        red_img_visible: Optional[bool] = None,
        red_name_visible: Optional[bool] = None,
        arena_name_visible: Optional[bool] = None,
        flags_visible: Optional[bool] = None,
        cinematic_visible: Optional[bool] = None,
    ):
        if round_visible is not None and bool(round_visible) != self._overlay_show_round:
            self._overlay_show_round = bool(round_visible)
            self.overlayShowRoundChanged.emit()
        if time_visible is not None and bool(time_visible) != self._overlay_show_time:
            self._overlay_show_time = bool(time_visible)
            self.overlayShowTimeChanged.emit()
        if blue_img_visible is not None and bool(blue_img_visible) != self._overlay_show_blue_img:
            self._overlay_show_blue_img = bool(blue_img_visible)
            self.overlayShowBlueImgChanged.emit()
        if blue_name_visible is not None and bool(blue_name_visible) != self._overlay_show_blue_name:
            self._overlay_show_blue_name = bool(blue_name_visible)
            self.overlayShowBlueNameChanged.emit()
        if red_img_visible is not None and bool(red_img_visible) != self._overlay_show_red_img:
            self._overlay_show_red_img = bool(red_img_visible)
            self.overlayShowRedImgChanged.emit()
        if red_name_visible is not None and bool(red_name_visible) != self._overlay_show_red_name:
            self._overlay_show_red_name = bool(red_name_visible)
            self.overlayShowRedNameChanged.emit()
        if arena_name_visible is not None and bool(arena_name_visible) != self._overlay_show_arena_name:
            self._overlay_show_arena_name = bool(arena_name_visible)
            self.overlayShowArenaNameChanged.emit()
        if flags_visible is not None and bool(flags_visible) != self._overlay_show_flags:
            self._overlay_show_flags = bool(flags_visible)
            self.overlayShowFlagsChanged.emit()
        if cinematic_visible is not None and bool(cinematic_visible) != self._overlay_show_cinematic:
            self._overlay_show_cinematic = bool(cinematic_visible)
            self.overlayShowCinematicChanged.emit()

    def set_overlay_style(self, style: Optional[dict]):
        if not isinstance(style, dict):
            return
        self._overlay_style = dict(style)
        self.overlayStyleChanged.emit()

    def _resolve_vs_background_path(self) -> str:
        arena = str(self._arena_name or "").strip().lower()
        if arena:
            for key, val in (self._overlay_vs_bg_by_arena or {}).items():
                if str(key or "").strip().lower() == arena and str(val or "").strip():
                    return str(val or "").strip()
        return str(self._overlay_vs_bg_path or "").strip()

    def set_overlay_vs_background(self, default_path: str = "", by_arena: Optional[dict] = None, opacity: float = 1.0):
        changed = False
        default_path = str(default_path or "").strip()
        if default_path != self._overlay_vs_bg_path:
            self._overlay_vs_bg_path = default_path
            changed = True
        clean = {str(k).strip(): str(v).strip() for k, v in (by_arena or {}).items() if str(k).strip() and str(v).strip()} if isinstance(by_arena, dict) else {}
        if clean != (self._overlay_vs_bg_by_arena or {}):
            self._overlay_vs_bg_by_arena = clean
            changed = True
        try:
            op = max(0.0, min(1.0, float(opacity)))
        except Exception:
            op = 1.0
        if abs(op - float(self._overlay_vs_bg_opacity or 0.0)) > 0.001:
            self._overlay_vs_bg_opacity = op
            changed = True
        if changed:
            self.overlayVsBackgroundChanged.emit()

    def set_overlay_vs_hold_sec(self, sec: float):
        try:
            val = max(0.5, min(15.0, float(sec)))
        except Exception:
            val = 2.85
        if abs(val - float(self._overlay_vs_hold_sec or 0.0)) > 0.001:
            self._overlay_vs_hold_sec = val
            self.overlayVsHoldMsChanged.emit()

    @pyqtSlot()
    def test_vs_intro(self):
        changed = False
        if not str(self._blue_name or "").strip():
            self._blue_name = "BLUE TEST"
            changed = True
            self.blueNameChanged.emit()
        if not str(self._red_name or "").strip():
            self._red_name = "RED TEST"
            changed = True
            self.redNameChanged.emit()
        if not str(self._arena_name or "").strip():
            self._arena_name = "DEFAULT"
            changed = True
            self.arenaNameChanged.emit()
            self.overlayVsBackgroundChanged.emit()
        self.vsIntroResetRequested.emit()
        if not changed:
            self.blueNameChanged.emit()
        logging.info("VS_INTRO_TEST_REQUEST blue=%s red=%s arena=%s", self._blue_name, self._red_name, self._arena_name)

    def set_screen_detect_running(self, running: bool):
        v = bool(running)
        if v != self._screen_detect_running:
            self._screen_detect_running = v
            self.screenDetectRunningChanged.emit()

    def set_pixel_detect_running(self, running: bool):
        v = bool(running)
        if v != self._pixel_detect_running:
            self._pixel_detect_running = v
            self.pixelDetectRunningChanged.emit()

    def set_log_detect_running(self, running: bool):
        v = bool(running)
        if v != self._log_detect_running:
            self._log_detect_running = v
            self.logDetectRunningChanged.emit()

    def set_hud_demo_running(self, running: bool):
        v = bool(running)
        if v != self._hud_demo_running:
            self._hud_demo_running = v
            self.hudDemoRunningChanged.emit()

    @pyqtSlot()
    def toggle_timer(self):
        self._set_running(not self.running)

    @pyqtSlot()
    def reset_timer(self):
        if time.time() < float(self._reset_cooldown_until or 0.0):
            try:
                logging.info(
                    "TIMER_RESET_SKIP reason=cooldown remain=%.3f",
                    max(0.0, float(self._reset_cooldown_until or 0.0) - time.time()),
                )
            except Exception:
                pass
            return
        self._reset_cooldown_until = time.time() + 10.0
        self._reset_timer_core()

    @pyqtSlot()
    def force_reset_timer(self):
        self._reset_timer_core()

    def _reset_timer_core(self):
        self._set_running(False)
        self.current_round = 1
        self.seconds_left = int(self.round_duration_sec)
        self._set_rest(False)
        self._blue_image_rev += 1
        self._red_image_rev += 1
        self.blueImageRevChanged.emit()
        self.redImageRevChanged.emit()
        # Keep win streaks on timer reset
        # Clear overlay fields on reset
        self._blue_name = ""
        self._red_name = ""
        self._arena_name = ""
        self.reset_spectator_sp()
        self.blueNameChanged.emit()
        self.redNameChanged.emit()
        self.arenaNameChanged.emit()
        self.overlayResetRequested.emit()
        self._refresh_time()

    @pyqtSlot()
    def start_timer(self):
        if self.running:
            return
        self._set_running(True)

    @pyqtSlot()
    def stop_timer(self):
        self._set_running(False)

    @pyqtSlot()
    def increment_round(self):
        total = max(1, int(self.total_rounds))
        cur = int(self.current_round) + 1
        if cur > total:
            cur = 1
        self.current_round = cur
        self._refresh_time()

    @pyqtSlot()
    def decrement_round(self):
        total = max(1, int(self.total_rounds))
        cur = int(self.current_round) - 1
        if cur < 1:
            cur = total
        self.current_round = cur
        self._refresh_time()

    @pyqtSlot()
    def toggle_rest_mode(self):
        if self.in_rest:
            self.in_rest = False
            self.seconds_left = int(self.round_duration_sec)
        else:
            self.in_rest = True
            self.seconds_left = int(self.rest_duration_sec)
        self.restModeChanged.emit()
        self._refresh_time()

    @pyqtSlot(str)
    def add_win(self, side: str):
        side = (side or "").lower().strip()
        if side == "blue":
            self._set_win_change("score", "blue")
            self.set_win_streaks(self._blue_win_streak + 1, 0)
            self._set_win_change("", "")
        elif side == "red":
            self._set_win_change("score", "red")
            self.set_win_streaks(0, self._red_win_streak + 1)
            self._set_win_change("", "")

    @pyqtSlot(str)
    def decrement_win(self, side: str):
        side = (side or "").lower().strip()
        if side == "blue":
            self._set_win_change("decrement", "blue")
            self.set_win_streaks(max(0, self._blue_win_streak - 1), self._red_win_streak)
            self._set_win_change("", "")
        elif side == "red":
            self._set_win_change("decrement", "red")
            self.set_win_streaks(self._blue_win_streak, max(0, self._red_win_streak - 1))
            self._set_win_change("", "")

    def _set_running(self, running: bool):
        self.running = bool(running)
        self._start_label = "Pause" if self.running else "Start"
        self.startLabelChanged.emit()
        self.runningChanged.emit(self.running)
        if self.running:
            self._qtimer.start(1000)
        else:
            self._qtimer.stop()

    @pyqtSlot()
    def _diagnostic_folder(self) -> str:
        try:
            folder = app_path("diagnostics")
        except Exception:
            folder = os.path.abspath(os.path.join(os.getcwd(), "diagnostics"))
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception:
            pass
        return folder

    def _diagnostic_app_state(self) -> dict:
        try:
            overlay_state = {}
            if getattr(self, "browser_overlay", None) is not None:
                try:
                    snap = self.browser_overlay.snapshot()
                    overlay_state = {
                        "seq": snap.get("seq"),
                        "events_tail": list((snap.get("events") or [])[-12:]),
                        "blueHasImage": bool(snap.get("blueHasImage")),
                        "redHasImage": bool(snap.get("redHasImage")),
                        "blueName": snap.get("blueName"),
                        "redName": snap.get("redName"),
                    }
                except Exception:
                    overlay_state = {"error": "overlay snapshot failed"}
            backend = getattr(getattr(self, "timer_win", None), "_backend", None)
            return {
                "app_version": APP_VERSION,
                "cfg_path": self.cfg_path,
                "time": datetime.now().isoformat(timespec="seconds"),
                "timer": {
                    "round": int(getattr(self.cfg, "timer_current_round", 1) or 1),
                    "total_rounds": int(getattr(self.cfg, "timer_total_rounds", 3) or 3),
                    "seconds_left": int(getattr(self.cfg, "timer_seconds_left", 0) or 0),
                    "round_sec": int(getattr(self.cfg, "timer_round_sec", 180) or 180),
                    "rest_sec": int(getattr(self.cfg, "timer_rest_sec", 60) or 60),
                },
                "spectatorlog": {
                    "enabled": bool(getattr(self.cfg, "spectatorlog_enabled", False)),
                    "running": bool(getattr(self, "spectator_watcher", None) and self.spectator_watcher.is_running()),
                    "path": str(getattr(self.cfg, "spectatorlog_path", "") or ""),
                    "resolved_path": self._diagnostic_spectator_root(),
                    "blackbox_enabled": bool(getattr(self.cfg, "spectatorlog_blackbox_enabled", False)),
                    "blackbox_dir": str(getattr(self.cfg, "spectatorlog_blackbox_dir", "SpectatorLogArchive") or "SpectatorLogArchive"),
                    "blackbox_mode": str(getattr(self.cfg, "spectatorlog_blackbox_mode", "smart") or "smart"),
                },
                "players": {
                    "blue_id": str(getattr(self, "_current_blue_id", "") or ""),
                    "red_id": str(getattr(self, "_current_red_id", "") or ""),
                    "blue_registered": bool(getattr(self, "_current_blue_registered", False)),
                    "red_registered": bool(getattr(self, "_current_red_registered", False)),
                },
                "detectors": {
                    "screen_running": bool(self._screen_detection_running() if self._screen_detection_running else False),
                    "log_running": bool(self._log_detection_running() if self._log_detection_running else False),
                },
                "overlay": overlay_state,
                "backend_state": {
                    "exists": bool(backend is not None),
                },
                "diagnostics": DIAG.summary(mask_sensitive=True),
            }
        except Exception as exc:
            return {"error": str(exc)}

    def _diagnostic_spectator_root(self) -> str:
        try:
            return resolve_spectatorlog_path(str(getattr(self.cfg, "spectatorlog_path", "") or ""))
        except Exception:
            return ""

    def _diagnostic_mark_incident(self, note: str = "") -> object:
        item = DIAG.mark_incident(note or "사용자 문제 발생 표시")
        try:
            self.timer_win.set_status("진단: 문제 발생 시점 표시 완료")
        except Exception:
            pass
        return item

    def _diagnostic_export_zip(self) -> str:
        try:
            DIAG.set_options(
                enabled=bool(getattr(self.cfg, "diagnostics_enabled", True)),
                max_events=max(500, int(getattr(self.cfg, "diagnostics_trace_minutes", 10) or 10) * 500),
                raw_sample_lines=int(getattr(self.cfg, "diagnostics_raw_sample_lines", 120) or 120),
                mask_sensitive=bool(getattr(self.cfg, "diagnostics_mask_sensitive", True)),
            )
        except Exception:
            pass
        root = self._diagnostic_spectator_root()
        overlay_snapshot = {}
        try:
            if getattr(self, "browser_overlay", None) is not None:
                overlay_snapshot = self.browser_overlay.snapshot()
        except Exception:
            overlay_snapshot = {"error": "snapshot failed"}
        path = DIAG.export_zip(
            self._diagnostic_folder(),
            app_state=self._diagnostic_app_state(),
            cfg_snapshot=getattr(self.cfg, "__dict__", {}),
            spectator_root=root,
            overlay_snapshot=overlay_snapshot,
            mask_sensitive=bool(getattr(self.cfg, "diagnostics_mask_sensitive", True)),
            raw_sample_lines=int(getattr(self.cfg, "diagnostics_raw_sample_lines", 120) or 120),
        )
        try:
            self.timer_win.set_status(f"진단 ZIP 생성: {os.path.basename(path)}")
        except Exception:
            pass
        return path

    def _diagnostic_open_folder(self) -> str:
        return self._diagnostic_folder()

    def _diagnostic_copy_state(self) -> str:
        return DIAG.current_state_text(self._diagnostic_app_state())

    @pyqtSlot()
    def open_settings(self):
        self.open_settings_requested.emit()

    @pyqtSlot()
    def openSettings(self):
        # QML-friendly camelCase alias.
        self.open_settings()

    @pyqtSlot()
    def check_updates(self):
        self.check_updates_requested.emit()

    @pyqtSlot(str, bool)
    def set_overlay_visible(self, key: str, visible: bool):
        self.overlayVisibilityRequested.emit(str(key or ""), bool(visible))

    @pyqtSlot(str)
    def hide_overlay(self, key: str):
        self.overlayVisibilityRequested.emit(str(key or ""), False)

    @pyqtSlot()
    def start_detection(self):
        self.start_detection_requested.emit()

    @pyqtSlot()
    def start_screen_detection(self):
        self.start_screen_detection_requested.emit()

    @pyqtSlot()
    def toggle_screen_detection(self):
        self.start_screen_detection_requested.emit()

    @pyqtSlot()
    def toggle_pixel_detection(self):
        self.toggle_pixel_detection_requested.emit()

    @pyqtSlot()
    def toggle_log_detection(self):
        self.toggle_log_detection_requested.emit()

    @pyqtSlot()
    def test_trigger(self):
        self.trigger_test_requested.emit()

    @pyqtSlot(str)
    def select_player(self, side: str):
        self.select_player_requested.emit(str(side or ""))

    @pyqtSlot(str)
    def play_burst_sfx(self, path: str):
        self.burstSfxRequested.emit(str(path or ""))

    @pyqtSlot(str)
    def play_fail_sfx(self, path: str):
        self.failSfxRequested.emit(str(path or ""))

    @pyqtSlot(str, result=str)
    def resolve_asset_url(self, path: str) -> str:
        p = str(path or "").strip()
        if not p:
            return ""
        try:
            if os.path.isabs(p):
                ab = os.path.abspath(p)
            else:
                ab = os.path.abspath(os.path.join(get_app_base_dir(), p))
        except Exception:
            ab = p
        try:
            return QUrl.fromLocalFile(ab).toString()
        except Exception:
            return str(ab)

    @pyqtSlot(str)
    def open_profile_register(self, side: str):
        self.profileRegisterRequested.emit(str(side or ""))

    @pyqtSlot(str)
    def open_profile_edit(self, side: str):
        self.profileEditRequested.emit(str(side or ""))

    @pyqtSlot()
    def sync_chapter_now(self):
        self.chapterSyncNowRequested.emit()

    @pyqtSlot()
    def toggle_chapter_sync(self):
        if self._broadcast_sync_active:
            self.chapterClearRequested.emit()
        else:
            self.chapterSyncNowRequested.emit()

    @pyqtSlot()
    def clear_chapter_anchor(self):
        self.chapterClearRequested.emit()

    @pyqtSlot()
    def export_chapter_txt(self):
        self.chapterExportRequested.emit()

    @pyqtSlot()
    def stop_hud_demo(self):
        self.hudDemoStopRequested.emit()

    @pyqtSlot()
    def replay_spectator_last_log(self):
        self.spectatorReplayRequested.emit()

    @pyqtSlot()
    def test_spectator_full_demo(self):
        self.spectatorFullDemoRequested.emit()

    @pyqtSlot()
    def test_spectator_vs_intro(self):
        self.spectatorVsIntroTestRequested.emit()

    def request_round_intro(self):
        self.roundIntroRequested.emit()

    def _refresh_time(self):
        m = self.seconds_left // 60
        s = self.seconds_left % 60
        time_text = f"{m}:{s:02d}"
        round_text = f"RD {self.current_round} of {self.total_rounds}"
        if time_text != self._time_text:
            self._time_text = time_text
            self.timeTextChanged.emit()
        if round_text != self._round_text:
            self._round_text = round_text
            self.roundTextChanged.emit()

    def _set_rest(self, is_rest: bool):
        if self.in_rest == bool(is_rest):
            return
        self.in_rest = bool(is_rest)
        self.restModeChanged.emit()

    def _tick(self):
        if self.seconds_left > 0:
            self.seconds_left -= 1
            if self.in_rest:
                self._sp_apply_rest_recovery(self.seconds_left)
                self._sp_apply_fight_recovery(None)
            else:
                self._sp_apply_fight_recovery(self.seconds_left)
                self._sp_apply_rest_recovery(None)
            if self.in_rest and int(self.seconds_left) == 30:
                self.restThirtySecondsReached.emit()
        else:
            if self.in_rest:
                if self.current_round >= self.total_rounds:
                    self._set_running(False)
                else:
                    self.current_round += 1
                    self.seconds_left = int(self.round_duration_sec)
                    self._set_rest(False)
                    self._sp_apply_rest_recovery(None)
                    self._sp_apply_fight_recovery(self.seconds_left)
            else:
                if self.current_round >= self.total_rounds:
                    self._set_running(False)
                else:
                    self.seconds_left = int(self.rest_duration_sec)
                    self._set_rest(True)
                    self._sp_apply_rest_recovery(self.seconds_left)
                    self._sp_apply_fight_recovery(None)
        self._refresh_time()


class LayoutBackend(QObject):
    def __init__(self, cfg: AppConfig, cfg_path: str):
        super().__init__()
        self._cfg = cfg
        self._cfg_path = cfg_path

    @pyqtSlot(result="QVariantMap")
    def loadLayout(self):
        return dict(self._cfg.layout or {})

    @pyqtSlot("QVariantMap")
    def saveLayout(self, layout):
        if layout is None:
            return
        try:
            self._cfg.layout = dict(layout)
            self._cfg.to_json(self._cfg_path)
        except Exception:
            pass


class _WinMsg(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


class OverlayHitTestFilter(QAbstractNativeEventFilter):
    WM_NCHITTEST = 0x0084
    HTTRANSPARENT = -1

    def __init__(self, timer_window: "QmlTimerWindow"):
        super().__init__()
        self._timer_window = timer_window

    @staticmethod
    def _signed_word(value: int) -> int:
        value &= 0xFFFF
        return value - 0x10000 if value & 0x8000 else value

    def nativeEventFilter(self, event_type, message):
        try:
            tw = self._timer_window
            root = getattr(tw, "_root", None)
            if root is None or not tw._main_overlay_capture_mode():
                return False, 0
            msg = _WinMsg.from_address(int(message))
            if int(msg.message) != self.WM_NCHITTEST:
                return False, 0
            try:
                if int(msg.hwnd) != int(root.winId()):
                    return False, 0
            except Exception:
                return False, 0
            if bool(root.property("editMode")):
                return False, 0
            lparam = int(msg.lParam)
            screen_y = self._signed_word(lparam >> 16)
            local_y = screen_y - int(float(root.y()))
            if local_y <= tw._main_overlay_interactive_height():
                return False, 0
            return True, self.HTTRANSPARENT
        except Exception:
            return False, 0


class QmlTimerWindow(QObject):
    open_settings = pyqtSignal()
    check_updates = pyqtSignal()

    def __init__(self, cfg: AppConfig, cfg_path: str):
        super().__init__()
        self._backend = TimerBackend()
        self._backend.open_settings_requested.connect(self.open_settings.emit)
        self._backend.check_updates_requested.connect(self.check_updates.emit)
        self._backend.overlayResetRequested.connect(self._on_overlay_reset)
        self._layout = LayoutBackend(cfg, cfg_path)

        self._provider = PlayerImageProvider()
        self._cinematic_provider = PlayerImageProvider()
        self._qml_preview_enabled = True
        self._qml_effects_enabled = False
        self._provider.set_mask_shape(getattr(cfg, "overlay_player_mask", "square"))
        self._cinematic_provider.set_mask_shape(getattr(cfg, "overlay_player_mask", "square"))
        self._blue_image_sig = None
        self._red_image_sig = None
        self._backend.set_overlay_player_mask(getattr(cfg, "overlay_player_mask", "square"))
        self._backend.set_overlay_preset(getattr(cfg, "overlay_preset", "classic"))
        self._backend.set_spectator_recent_text_size(getattr(cfg, "spectator_recent_text_size", 23))
        self._backend.set_overlay_visibility(
            round_visible=getattr(cfg, "overlay_show_round", True),
            time_visible=getattr(cfg, "overlay_show_time", True),
            blue_img_visible=getattr(cfg, "overlay_show_blue_img", True),
            blue_name_visible=getattr(cfg, "overlay_show_blue_name", True),
            red_img_visible=getattr(cfg, "overlay_show_red_img", True),
            red_name_visible=getattr(cfg, "overlay_show_red_name", True),
            arena_name_visible=getattr(cfg, "overlay_show_arena_name", True),
            flags_visible=getattr(cfg, "overlay_show_flags", True),
            cinematic_visible=(bool(getattr(cfg, "overlay_show_cinematic", True)) and not bool(getattr(cfg, "browser_overlay_output_only", True))),
        )
        self._backend.set_overlay_style({
            "round": getattr(cfg, "overlay_style_round", _default_overlay_style_round()),
            "time": getattr(cfg, "overlay_style_time", _default_overlay_style_time()),
            "blue_name": getattr(cfg, "overlay_style_blue_name", _default_overlay_style_blue_name()),
            "red_name": getattr(cfg, "overlay_style_red_name", _default_overlay_style_red_name()),
            "arena": getattr(cfg, "overlay_style_arena", _default_overlay_style_arena()),
        })
        self._backend.set_overlay_vs_background(
            getattr(cfg, "overlay_vs_bg_path", ""),
            getattr(cfg, "overlay_vs_bg_by_arena", {}) or {},
            getattr(cfg, "overlay_vs_bg_opacity", 1.0),
        )
        self._backend.set_overlay_vs_hold_sec(getattr(cfg, "overlay_vs_hold_sec", 2.85))
        self._backend.set_overlay_ui_scale(getattr(cfg, "overlay_ui_scale", 1.0))
        if HAS_QQUICKSTYLE and QQuickStyle is not None:
            try:
                QQuickStyle.setStyle("Fusion")
            except Exception:
                pass
        QQuickWindow.setDefaultAlphaBuffer(True)
        self._engine = QQmlApplicationEngine()
        self._engine.rootContext().setContextProperty("backend", self._backend)
        self._engine.rootContext().setContextProperty("layoutApi", self._layout)
        self._engine.addImageProvider("players", self._provider)

        qml_path = app_path("timer_ui.qml")
        self._engine.load(qml_path)
        roots = self._engine.rootObjects()
        self._root = roots[0] if roots else None

        self._cinematic_engine = QQmlApplicationEngine()
        self._cinematic_engine.rootContext().setContextProperty("backend", self._backend)
        self._cinematic_engine.addImageProvider("players", self._cinematic_provider)
        cinematic_qml_path = app_path("cinematic_overlay.qml")
        self._cinematic_engine.load(cinematic_qml_path)
        cinematic_roots = self._cinematic_engine.rootObjects()
        self._cinematic_root = cinematic_roots[0] if cinematic_roots else None
        if self._cinematic_root is not None:
            try:
                self._cinematic_root.hide()
            except Exception:
                pass
        self._hit_test_filter = OverlayHitTestFilter(self)
        self._input_transparent_active = False
        self._input_transparent_timer = QTimer(self)
        self._input_transparent_timer.setInterval(50)
        self._input_transparent_timer.timeout.connect(self._sync_main_overlay_input_transparency)
        self._input_transparent_timer.start()
        try:
            app = QApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self._hit_test_filter)
        except Exception:
            logging.exception("OVERLAY_HITTEST_INSTALL_FAIL")
        if self._root is not None:
            for sig_name in ("xChanged", "yChanged", "widthChanged", "heightChanged"):
                try:
                    getattr(self._root, sig_name).connect(self._sync_cinematic_geometry)
                except Exception:
                    pass
            try:
                self._backend.overlayPresetChanged.connect(self._sync_main_overlay_geometry)
                self._backend.overlayShowCinematicChanged.connect(self._sync_main_overlay_geometry)
            except Exception:
                pass
        for sig_name in ("roundIntroRequested", "spectatorEffectRequested", "blueNameChanged", "redNameChanged"):
            try:
                getattr(self._backend, sig_name).connect(self._raise_cinematic_overlay)
            except Exception:
                pass
        self._sync_main_overlay_geometry()
        self._sync_cinematic_geometry()
        self.set_qml_preview_enabled(bool(getattr(cfg, "qml_preview_enabled", True)))
        self.set_qml_effects_enabled(bool(getattr(cfg, "qml_effects_enabled", False)))

        self._ctrl = None

    def _main_overlay_capture_mode(self) -> bool:
        if not bool(getattr(self, "_qml_preview_enabled", True)):
            return False
        try:
            return (
                str(getattr(self._backend, "overlayPreset", "") or "").lower() == "tekken8"
                and bool(getattr(self._backend, "overlayShowCinematic", False))
            )
        except Exception:
            return False

    def _main_overlay_interactive_height(self) -> int:
        try:
            scale = max(0.5, min(2.5, float(getattr(self._backend, "overlayUiScale", 1.0) or 1.0)))
        except Exception:
            scale = 1.0
        base = 135
        try:
            if bool(self._root.property("showControls")) or bool(self._root.property("topBarHover")):
                base = 190
        except Exception:
            pass
        return int(math.ceil(base * scale))

    def _set_main_overlay_input_transparent(self, enabled: bool) -> None:
        if self._root is None or os.name != "nt":
            return
        enabled = bool(enabled)
        if enabled == bool(getattr(self, "_input_transparent_active", False)):
            return
        try:
            hwnd = int(self._root.winId())
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            user32 = ctypes.windll.user32
            get_long = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
            set_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
            style = int(get_long(hwnd, GWL_EXSTYLE))
            if enabled:
                style |= (WS_EX_TRANSPARENT | WS_EX_LAYERED)
            else:
                style &= ~WS_EX_TRANSPARENT
            set_long(hwnd, GWL_EXSTYLE, style)
            self._input_transparent_active = enabled
        except Exception:
            logging.exception("MAIN_OVERLAY_INPUT_TRANSPARENT_FAIL enabled=%s", enabled)

    def _sync_main_overlay_input_transparency(self) -> None:
        if self._root is None or not bool(getattr(self, "_qml_preview_enabled", True)):
            self._set_main_overlay_input_transparent(False)
            return
        try:
            if not self._main_overlay_capture_mode() or bool(self._root.property("editMode")):
                self._set_main_overlay_input_transparent(False)
                return
            pos = QCursor.pos()
            local_y = int(pos.y()) - int(float(self._root.y()))
            self._set_main_overlay_input_transparent(local_y > self._main_overlay_interactive_height())
        except Exception:
            self._set_main_overlay_input_transparent(False)

    def _sync_main_overlay_geometry(self, *args) -> None:
        if not bool(getattr(self, "_qml_preview_enabled", True)):
            self._set_main_overlay_input_transparent(False)
            try:
                if self._root is not None:
                    self._root.hide()
                if self._cinematic_root is not None:
                    self._cinematic_root.hide()
            except Exception:
                pass
            return
        if self._root is None or not self._main_overlay_capture_mode():
            self._set_main_overlay_input_transparent(False)
            return
        try:
            # Tekken fullscreen-capture mode renders cinematic effects inside
            # timer_ui.qml. Keep the legacy separate cinematic window hidden to
            # avoid duplicate VS/ROUND/KO overlays.
            if self._cinematic_root is not None:
                try:
                    self._cinematic_root.hide()
                except Exception:
                    pass
            screen = None
            try:
                cx = int(float(self._root.x()) + float(self._root.width()) / 2.0)
                cy = int(float(self._root.y()) + min(float(self._root.height()), 320.0) / 2.0)
                screen = QGuiApplication.screenAt(QPoint(cx, cy))
            except Exception:
                screen = None
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            geo = screen.geometry() if screen is not None else None
            if geo is None:
                return
            self._root.setX(int(geo.x()))
            self._root.setY(int(geo.y()))
            self._root.setWidth(int(geo.width()))
            self._root.setHeight(int(geo.height()))
            try:
                self._root.show()
                self._root.raise_()
                self._root.requestUpdate()
            except Exception:
                pass
            logging.info(
                "MAIN_OVERLAY_CAPTURE_GEOMETRY x=%s y=%s w=%s h=%s interactive_h=%s",
                int(geo.x()),
                int(geo.y()),
                int(geo.width()),
                int(geo.height()),
                self._main_overlay_interactive_height(),
            )
        except Exception:
            logging.exception("MAIN_OVERLAY_CAPTURE_GEOMETRY_FAIL")

    def _raise_cinematic_overlay(self, *args) -> None:
        if not bool(getattr(self, "_qml_preview_enabled", True)):
            try:
                if self._cinematic_root is not None:
                    self._cinematic_root.hide()
            except Exception:
                pass
            return
        self._sync_main_overlay_geometry()
        if self._main_overlay_capture_mode():
            if self._cinematic_root is not None:
                try:
                    self._cinematic_root.hide()
                except Exception:
                    pass
            return
        if not self._cinematic_root:
            logging.info("CINEMATIC_RAISE_SKIP reason=no_root args=%s", args)
            return
        try:
            self._sync_cinematic_geometry()
            self._cinematic_root.show()
            self._cinematic_root.raise_()
            try:
                self._cinematic_root.requestUpdate()
            except Exception:
                pass
            logging.info(
                "CINEMATIC_RAISE args=%s preset=%s enabled=%s x=%s y=%s w=%s h=%s visible=%s",
                args,
                getattr(self._backend, "overlayPreset", ""),
                getattr(self._backend, "overlayShowCinematic", False),
                int(self._cinematic_root.x()),
                int(self._cinematic_root.y()),
                int(self._cinematic_root.width()),
                int(self._cinematic_root.height()),
                bool(self._cinematic_root.isVisible()),
            )
        except Exception:
            logging.exception("CINEMATIC_RAISE_FAIL args=%s", args)

    def _sync_cinematic_geometry(self) -> None:
        if not self._cinematic_root:
            return
        try:
            screen = None
            if self._root is not None:
                try:
                    cx = int(float(self._root.x()) + float(self._root.width()) / 2.0)
                    cy = int(float(self._root.y()) + float(self._root.height()) / 2.0)
                    screen = QGuiApplication.screenAt(QPoint(cx, cy))
                except Exception:
                    screen = None
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            geo = screen.geometry() if screen is not None else None
            if geo is not None:
                self._cinematic_root.setX(int(geo.x()))
                self._cinematic_root.setY(int(geo.y()))
                self._cinematic_root.setWidth(int(geo.width()))
                self._cinematic_root.setHeight(int(geo.height()))
        except Exception:
            pass

    def set_status(self, s: str):
        self._backend.set_status(s)

    def set_broadcast_sync_active(self, active: bool):
        self._backend.set_broadcast_sync_active(active)

    def set_overlay_on_top(self, enabled: bool) -> None:
        if not self._root or not bool(getattr(self, "_qml_preview_enabled", True)):
            return
        try:
            flags = self._root.flags()
            if enabled:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            else:
                flags &= ~Qt.WindowType.WindowStaysOnTopHint
            self._root.setFlags(flags)
            if enabled:
                self._root.show()
                self._root.raise_()
                if self._cinematic_root is not None:
                    self._cinematic_root.show()
                    self._cinematic_root.raise_()
        except Exception:
            pass

    def set_names(self, blue: Optional[str], red: Optional[str]):
        self._backend.set_names(blue, red)

    def set_arena_name(self, name: Optional[str]):
        self._backend.set_arena_name(name)

    def set_palettes(self, blue_pal: List[Tuple[int, int, int]] | None, red_pal: List[Tuple[int, int, int]] | None):
        self._backend.set_palettes(blue_pal, red_pal)

    def set_player_images(self, blue_img, red_img):
        def _image_sig(img):
            if img is None:
                return None
            try:
                arr = np.ascontiguousarray(img)
                h = hashlib.blake2b(digest_size=16)
                h.update(str(arr.shape).encode("ascii", "ignore"))
                h.update(str(arr.dtype).encode("ascii", "ignore"))
                h.update(arr.tobytes())
                return h.hexdigest()
            except Exception:
                return object()

        def _prepare(img):
            try:
                if img is None or getattr(img, "size", 0) == 0:
                    return img
                h, w = img.shape[:2]
                max_dim = max(h, w)
                if max_dim <= 0 or max_dim >= 512:
                    return img
                scale = min(4.0, 512.0 / float(max_dim))
                if scale <= 1.05:
                    return img
                return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
            except Exception:
                return img

        if blue_img is not _NO_UPDATE:
            sig = _image_sig(blue_img)
            if sig == self._blue_image_sig:
                blue_img = _NO_UPDATE
            else:
                self._blue_image_sig = sig
        if red_img is not _NO_UPDATE:
            sig = _image_sig(red_img)
            if sig == self._red_image_sig:
                red_img = _NO_UPDATE
            else:
                self._red_image_sig = sig

        if blue_img is not _NO_UPDATE:
            if blue_img is None:
                self._provider.set_image("blue", QImage())
                self._cinematic_provider.set_image("blue", QImage())
                self._backend.bump_blue_image()
            else:
                qimg = bgr_to_qimage(_prepare(blue_img))
                if qimg is not None:
                    self._provider.set_image("blue", qimg)
                    self._cinematic_provider.set_image("blue", qimg)
                    self._backend.bump_blue_image()
        if red_img is not _NO_UPDATE:
            if red_img is None:
                self._provider.set_image("red", QImage())
                self._cinematic_provider.set_image("red", QImage())
                self._backend.bump_red_image()
            else:
                qimg = bgr_to_qimage(_prepare(red_img))
                if qimg is not None:
                    self._provider.set_image("red", qimg)
                    self._cinematic_provider.set_image("red", qimg)
                    self._backend.bump_red_image()

    def set_player_mask_shape(self, shape: str):
        normalized = _normalize_player_mask(shape)
        try:
            old = str(self._backend.overlayPlayerMask or "square")
        except Exception:
            old = "square"
        if normalized == old:
            return
        self._provider.set_mask_shape(normalized)
        self._cinematic_provider.set_mask_shape(normalized)
        self._backend.set_overlay_player_mask(normalized)
        self._backend.bump_blue_image()
        self._backend.bump_red_image()

    def set_overlay_visibility(
        self,
        round_visible: Optional[bool] = None,
        time_visible: Optional[bool] = None,
        blue_img_visible: Optional[bool] = None,
        blue_name_visible: Optional[bool] = None,
        red_img_visible: Optional[bool] = None,
        red_name_visible: Optional[bool] = None,
        arena_name_visible: Optional[bool] = None,
        flags_visible: Optional[bool] = None,
        cinematic_visible: Optional[bool] = None,
    ):
        self._backend.set_overlay_visibility(
            round_visible=round_visible,
            time_visible=time_visible,
            blue_img_visible=blue_img_visible,
            blue_name_visible=blue_name_visible,
            red_img_visible=red_img_visible,
            red_name_visible=red_name_visible,
            arena_name_visible=arena_name_visible,
            flags_visible=flags_visible,
            cinematic_visible=cinematic_visible,
        )

    def set_overlay_style(self, style: Optional[dict]):
        self._backend.set_overlay_style(style)

    def set_overlay_preset(self, preset: Optional[str]):
        self._backend.set_overlay_preset(preset)

    def set_overlay_ui_scale(self, value: Optional[float]):
        try:
            self._backend.set_overlay_ui_scale(float(value if value is not None else 1.0))
        except Exception:
            self._backend.set_overlay_ui_scale(1.0)

    def set_overlay_layout(self, layout: Optional[dict]):
        if not layout:
            return
        try:
            self._layout.saveLayout(layout)
        except Exception:
            pass
        try:
            if self._root is not None:
                QMetaObject.invokeMethod(
                    self._root,
                    "applyLayout",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG("QVariant", dict(layout)),
                )
        except Exception:
            pass

    def _on_overlay_reset(self):
        try:
            self._provider.set_image("blue", QImage())
            self._provider.set_image("red", QImage())
            self._cinematic_provider.set_image("blue", QImage())
            self._cinematic_provider.set_image("red", QImage())
        except Exception:
            pass
        self._backend.bump_blue_image()
        self._backend.bump_red_image()

    def set_round_time(self, current_round: Optional[int], total_rounds: Optional[int], seconds_left: Optional[int]):
        self._backend.set_round_time(current_round, total_rounds, seconds_left)

    def request_round_intro(self):
        self._backend.request_round_intro()

    def set_log_rest_mode(self, is_rest: bool):
        self._backend.set_log_rest_mode(is_rest)

    def set_timer_settings(
        self,
        total_rounds: Optional[int],
        round_sec: Optional[int],
        rest_sec: Optional[int],
        current_round: Optional[int],
        seconds_left: Optional[int],
    ):
        self._backend.apply_timer_settings(total_rounds, round_sec, rest_sec, current_round, seconds_left)

    def add_win(self, side: str):
        try:
            self._backend.add_win(side)
        except Exception:
            pass

    def set_win_streaks(self, blue: Optional[int], red: Optional[int]):
        b = self._backend.blueWinStreak if blue is None else int(blue)
        r = self._backend.redWinStreak if red is None else int(red)
        self._backend.set_win_streaks(b, r)

    def set_spectator_damage(self, blue_dealt: float, red_dealt: float):
        self._backend.set_spectator_damage(blue_dealt, red_dealt)

    def set_spectator_total_damage(self, blue_dealt: float, red_dealt: float):
        self._backend.set_spectator_total_damage(blue_dealt, red_dealt)

    def trigger_stun_flash(self, side: str):
        self._backend.trigger_stun_flash(side)

    def trigger_spectator_effect(self, side: str, kind: str):
        self._backend.trigger_spectator_effect(side, kind)

    def trigger_hit_impact(self, side: str, damage: float):
        self._backend.trigger_hit_impact(side, damage)

    def set_spectator_log_info(self, info: Optional[dict]):
        self._backend.set_spectator_log_info(info)

    def set_spectator_recent_text_size(self, size: Optional[int]):
        self._backend.set_spectator_recent_text_size(size)

    def set_player_info(
        self,
        blue_id: Optional[str],
        red_id: Optional[str],
        blue_registered: Optional[bool],
        red_registered: Optional[bool],
        blue_valid: Optional[bool],
        red_valid: Optional[bool],
    ):
        self._backend.set_player_info(blue_id, red_id, blue_registered, red_registered, blue_valid, red_valid)

    def set_player_flags(self, blue_path: Optional[str], red_path: Optional[str]):
        def _to_source(path: Optional[str]) -> str:
            raw = str(path or "").strip()
            if not raw:
                return ""
            try:
                ab = normalize_app_path(raw)
                if not os.path.exists(ab):
                    base_name = os.path.basename(ab)
                    for candidate in (
                        app_path("image", "flags", base_name),
                        app_path("image", base_name),
                    ):
                        if os.path.exists(candidate):
                            ab = candidate
                            break
                url = QUrl.fromLocalFile(os.path.abspath(ab))
                try:
                    if os.path.exists(ab):
                        url.setQuery(f"v={int(os.path.getmtime(ab))}_{int(os.path.getsize(ab))}")
                except Exception:
                    pass
                return url.toString()
            except Exception:
                return ""

        self._backend.set_player_flags(_to_source(blue_path), _to_source(red_path))

    def set_effect_settings(self, settings: Optional[dict]):
        self._backend.set_effect_settings(settings or {})

    def set_overlay_bg_color(self, color: Optional[str]):
        self._backend.set_overlay_bg_color(color or "transparent")

    @pyqtSlot(float)
    def set_overlay_bg_opacity(self, opacity: Optional[float]):
        self._backend.set_overlay_bg_opacity(opacity if opacity is not None else 0.0)

    @pyqtSlot(float)
    def set_overlay_ui_bg_opacity(self, opacity: Optional[float]):
        self._backend.set_overlay_ui_bg_opacity(opacity if opacity is not None else 0.75)

    @pyqtSlot(float)
    def set_overlay_window_opacity(self, opacity: Optional[float]):
        self._backend.set_overlay_window_opacity(opacity if opacity is not None else 1.0)

    def set_qml_preview_enabled(self, enabled: bool):
        enabled = bool(enabled)
        was_enabled = bool(getattr(self, "_qml_preview_enabled", True))
        self._qml_preview_enabled = enabled
        try:
            self._backend.set_qml_preview_enabled(enabled)
        except Exception:
            pass
        try:
            if self._root is not None:
                if enabled:
                    self._root.show()
                    self._root.raise_()
                    try:
                        self._root.requestUpdate()
                    except Exception:
                        pass
                else:
                    self._root.show()
            if self._cinematic_root is not None:
                self._cinematic_root.hide()
        except Exception:
            pass
        self._sync_main_overlay_input_transparency()
        if enabled and not was_enabled:
            self._sync_main_overlay_geometry()

    def set_qml_effects_enabled(self, enabled: bool):
        enabled = bool(enabled)
        self._qml_effects_enabled = enabled
        try:
            self._backend.set_qml_effects_enabled(enabled)
        except Exception:
            pass


    def is_running(self) -> bool:
        return bool(self._backend.running)

    def is_in_rest(self) -> bool:
        return bool(self._backend.in_rest)

    def timer_start(self):
        self._backend.start_timer()

    def timer_stop(self):
        self._backend.stop_timer()

    def timer_reset(self):
        self._backend.reset_timer()

    def timer_force_reset(self):
        self._backend.force_reset_timer()

    def show(self):
        if self._root is not None:
            self._root.show()


# -----------------------------
# GUI: Timer Window (legacy)
# -----------------------------
class TimerWindow(QMainWindow):
    open_settings = pyqtSignal()
    check_updates = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Box Timer (Output)")
        self.setFixedSize(420, 160)

        menubar = self.menuBar()
        menu_file = menubar.addMenu("File")
        act_open_browser_overlay = QAction("Open Browser Overlay", self)
        act_open_browser_overlay.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl("http://127.0.0.1:17872/overlay"))
        )
        menu_file.addAction(act_open_browser_overlay)
        act_check_updates = QAction("Check for Updates", self)
        act_check_updates.triggered.connect(lambda: self.check_updates.emit())
        menu_file.addAction(act_check_updates)
        act_quit = QAction("Exit", self)
        act_quit.triggered.connect(self.close)
        menu_file.addAction(act_quit)

        root = QWidget()
        self.setCentralWidget(root)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color:#666; font-size:11px;")

        self.lbl_title = QLabel("RFC - RANKING FIGHT")
        self.lbl_title.setStyleSheet("font-size:12px; font-weight:700; color:#333;")
        self.lbl_arena = QLabel("")
        self.lbl_arena.setStyleSheet("font-size:11px; font-weight:700; color:#444; font-family:'Malgun Gothic';")

        self.lbl_round = QLabel("RD 1 of 3")
        self.lbl_round.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_round.setStyleSheet(
            "font-size:14px; font-weight:800; color:#5a2d1c; background:#f1d2c5; border:2px solid #b76b4c; border-radius:6px;"
        )
        self.lbl_round.setFixedSize(70, 60)

        self._time_style_base = (
            "font-size:36px; font-weight:900; color:{color}; background:#333; border:2px solid #111; "
            "border-radius:6px; padding:4px 8px;"
        )
        self.lbl_time = QLabel("3:00")
        self.lbl_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_time.setStyleSheet(self._time_style_base.format(color="#fff"))
        self.lbl_time.setFixedSize(140, 60)

        self.blue_name = QLabel("BLUE")
        self.blue_name.setStyleSheet("font-size:14px; font-weight:800; color:#fff; background:#3b6ee8; padding:6px; border-radius:4px;")
        self.red_name = QLabel("RED")
        self.red_name.setStyleSheet("font-size:14px; font-weight:800; color:#fff; background:#d24b4b; padding:6px; border-radius:4px;")
        self.blue_name.setMinimumHeight(28)
        self.red_name.setMinimumHeight(28)

        # Player palette previews.
        self.blue_palette = PaletteRow(n=5, box_size=18)
        self.red_palette = PaletteRow(n=5, box_size=18)
        self.blue_palette.setVisible(False)
        self.red_palette.setVisible(False)

        self.blue_img = QLabel()
        self.red_img = QLabel()
        for lbl in (self.blue_img, self.red_img):
            lbl.setFixedSize(28, 28)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("background:#222; border:1px solid #333;")

        self.btn_start = QPushButton("타이머 시작/일시정지")
        self.btn_reset = QPushButton("타이머 리셋")
        self.btn_gear = QPushButton("설정")

        self.total_rounds = 3
        self.current_round = 1
        self.seconds_left = 180
        self.round_duration_sec = 180
        self.rest_duration_sec = 60
        self.in_rest = False
        self.running = False
        self._qtimer = QTimer(self)
        self._qtimer.timeout.connect(self._tick)

        self.btn_start.clicked.connect(self.toggle_timer)
        self.btn_reset.clicked.connect(self.reset_timer)
        self.btn_gear.clicked.connect(lambda: self.open_settings.emit())

        main_row = QHBoxLayout()
        main_row.addWidget(self.lbl_round)
        main_row.addWidget(self.lbl_time)

        right = QVBoxLayout()
        row1 = QHBoxLayout()
        row1.addWidget(self.blue_img)
        row1.addWidget(self.blue_name, 1)
        row2 = QHBoxLayout()
        row2.addWidget(self.red_img)
        row2.addWidget(self.red_name, 1)
        right.addLayout(row1)
        right.addLayout(row2)
        main_row.addLayout(right, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(self.btn_start)
        btns.addWidget(self.btn_reset)
        btns.addWidget(self.btn_gear)

        layout = QVBoxLayout()
        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_arena)
        layout.addLayout(main_row)
        layout.addWidget(self.lbl_status)
        layout.addLayout(btns)

        root.setLayout(layout)
        self.setStyleSheet("background:#e9e6df;")
        self._refresh_time()

    def set_status(self, s: str):
        self.lbl_status.setText(s)

    def set_names(self, blue: str, red: str):
        self.blue_name.setText(blue or "BLUE")
        self.red_name.setText(red or "RED")

    def set_arena_name(self, name: Optional[str]):
        self.lbl_arena.setText(name or "")

    def set_palettes(self, blue_pal: List[Tuple[int, int, int]] | None, red_pal: List[Tuple[int, int, int]] | None):
        if blue_pal:
            self.blue_palette.set_palette(blue_pal)
        if red_pal:
            self.red_palette.set_palette(red_pal)

    def set_player_images(self, blue_img: Optional[np.ndarray], red_img: Optional[np.ndarray]):
        self._set_img(self.blue_img, blue_img)
        self._set_img(self.red_img, red_img)

    def set_round_time(self, current_round: Optional[int], total_rounds: Optional[int], seconds_left: Optional[int]):
        if total_rounds:
            self.total_rounds = int(total_rounds)
        if current_round:
            self.current_round = int(current_round)
        if seconds_left is not None:
            if not (self.running and self.in_rest):
                self.seconds_left = max(0, int(seconds_left))
                self.in_rest = False
        self._refresh_time()

    def _set_img(self, lbl: QLabel, img: Optional[np.ndarray]):
        if img is None or img.size == 0:
            return
        h, w = img.shape[:2]
        if img.shape[2] == 4:
            qimg = QImage(img.data, w, h, 4 * w, QImage.Format.Format_RGBA8888).copy()
        else:
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg)
        lbl.setPixmap(pix.scaled(lbl.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _refresh_time(self):
        m = self.seconds_left // 60
        s = self.seconds_left % 60
        self.lbl_time.setText(f"{m}:{s:02d}")
        self.lbl_round.setText(f"RD {self.current_round} of {self.total_rounds}")
        color = "#ff5a5a" if self.in_rest else "#fff"
        self.lbl_time.setStyleSheet(self._time_style_base.format(color=color))

    def toggle_timer(self):
        self.running = not self.running
        if self.running:
            self._qtimer.start(1000)
        else:
            self._qtimer.stop()

    def reset_timer(self):
        self.running = False
        self._qtimer.stop()
        self.current_round = 1
        self.seconds_left = int(self.round_duration_sec)
        self.in_rest = False
        self._refresh_time()

    def is_running(self) -> bool:
        return bool(self.running)

    def is_in_rest(self) -> bool:
        return bool(self.in_rest)

    def _tick(self):
        if self.seconds_left > 0:
            self.seconds_left -= 1
        else:
            if self.in_rest:
                if self.current_round >= self.total_rounds:
                    self.running = False
                    self._qtimer.stop()
                else:
                    self.current_round += 1
                    self.seconds_left = int(self.round_duration_sec)
                    self.in_rest = False
            else:
                if self.current_round >= self.total_rounds:
                    self.running = False
                    self._qtimer.stop()
                else:
                    self.seconds_left = int(self.rest_duration_sec)
                    self.in_rest = True
        self._refresh_time()


class WheelFocusFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel:
            if isinstance(obj, (QSpinBox, QDoubleSpinBox, QComboBox, QSlider, QFontComboBox)):
                event.ignore()
                return True
            if hasattr(obj, "hasFocus"):
                if not obj.hasFocus():
                    event.ignore()
                    return True
        return super().eventFilter(obj, event)


class _NoopTimerWindow:
    def timer_start(self):
        return

    def timer_stop(self):
        return

    def timer_reset(self):
        return

    def set_round_time(self, *_args, **_kwargs):
        return


# -----------------------------
# Settings Dialog
# -----------------------------
def _square_pixmap(path: str, size: int) -> Optional[QPixmap]:
    path = resolve_player_image_path(path or "")
    if not path or not os.path.exists(path):
        return None
    pix = QPixmap(path)
    if pix.isNull():
        return None
    scaled = pix.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    dx = (scaled.width() - size) // 2
    dy = (scaled.height() - size) // 2
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.drawPixmap(-dx, -dy, scaled)
    painter.end()
    return out


def _circle_pixmap(path: str, size: int) -> Optional[QPixmap]:
    path = resolve_player_image_path(path or "")
    if not path or not os.path.exists(path):
        return None
    pix = QPixmap(path)
    if pix.isNull():
        return None
    scaled = pix.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    dx = (scaled.width() - size) // 2
    dy = (scaled.height() - size) // 2
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path_circle = QPainterPath()
    path_circle.addEllipse(0, 0, size, size)
    painter.setClipPath(path_circle)
    painter.drawPixmap(-dx, -dy, scaled)
    painter.end()
    return out


def _paste_clipboard_image(gid: str) -> str:
    cb = QGuiApplication.clipboard()
    img = cb.image()
    if not img.isNull():
        base_dir = app_path("image", "players")
        os.makedirs(base_dir, exist_ok=True)
        filename = f"{gid}_{uuid.uuid4().hex[:8]}.png"
        path = os.path.join(base_dir, filename)
        img.save(path, "PNG")
        return to_app_rel(path)
    md = cb.mimeData()
    if md and md.hasUrls():
        local = md.urls()[0].toLocalFile()
        if local:
            return to_app_rel(local)
    return ""


def _download_image_url(url: str, gid: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return ""
    try:
        req = Request(url, headers={"User-Agent": "TimerAuto"})
        with urlopen(req, timeout=10) as resp:
            if getattr(resp, "status", 200) >= 400:
                return ""
            content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            data = resp.read(10 * 1024 * 1024 + 1)
    except Exception:
        return ""
    if not data or len(data) > 10 * 1024 * 1024:
        return ""
    ext = ""
    if content_type in ("image/png",):
        ext = ".png"
    elif content_type in ("image/jpeg", "image/jpg"):
        ext = ".jpg"
    elif content_type in ("image/bmp",):
        ext = ".bmp"
    else:
        _, uext = os.path.splitext(parsed.path)
        if uext.lower() in (".png", ".jpg", ".jpeg", ".bmp"):
            ext = uext.lower()
        else:
            ext = ".png"
    base_dir = app_path("image", "players")
    os.makedirs(base_dir, exist_ok=True)
    safe_gid = (gid or "URL").strip() or "URL"
    filename = f"{safe_gid}_{uuid.uuid4().hex[:8]}{ext}"
    path = os.path.join(base_dir, filename)
    try:
        with open(path, "wb") as f:
            f.write(data)
    except Exception:
        return ""
    pix = QPixmap(path)
    if pix.isNull():
        try:
            os.remove(path)
        except Exception:
            pass
        return ""
    return to_app_rel(path)


def _ask_image_url(parent: Optional[QWidget]) -> str:
    host = parent
    if host is None:
        try:
            host = QApplication.activeWindow()
        except Exception:
            host = None
    dlg = QInputDialog(host)
    dlg.setWindowTitle("\uC774\uBBF8\uC9C0 URL")
    dlg.setLabelText("\uC774\uBBF8\uC9C0 URL\uC744 \uBD99\uC5EC\uB123\uC73C\uC138\uC694.")
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
    dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    dlg.setWindowFlag(Qt.WindowType.Tool, True)
    dlg.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
    try:
        dlg.raise_()
        dlg.activateWindow()
    except Exception:
        pass
    ok = dlg.exec() == QDialog.DialogCode.Accepted
    if not ok:
        return ""
    return str(dlg.textValue() or "").strip()


class PlayerCard(QWidget):
    def __init__(
        self,
        parent: QWidget,
        gid: str,
        name: str,
        img_path: str,
        on_profile: Callable[[str], None],
        on_delete: Callable[[str], None],
        avatar_shape: str,
        is_list: bool,
    ):
        super().__init__(parent)
        self.gid = gid
        self.name = name
        self.img_path = img_path
        self.on_profile = on_profile
        self.on_delete = on_delete
        self.avatar_shape = avatar_shape
        self.is_list = is_list
        self.setObjectName("PlayerCard")

        lay = QVBoxLayout()
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        self.lbl_img = QLabel()
        self.lbl_img.setFixedSize(90 if not is_list else 64, 90 if not is_list else 64)
        self.lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_img.setStyleSheet("background:transparent;")
        self._set_image()
        if is_list:
            row = QHBoxLayout()
            row.addWidget(self.lbl_img)
            row.setAlignment(self.lbl_img, Qt.AlignmentFlag.AlignVCenter)

            text_col = QVBoxLayout()
            self.lbl_name = QLabel(self.name)
            self.lbl_name.setStyleSheet("font-size:14px; font-weight:700; color:#f7f7f7;")
            self.lbl_id = QLabel(f"@{self.gid}")
            self.lbl_id.setStyleSheet("font-size:11px; color:#f7f7f7;")
            text_col.addWidget(self.lbl_name)
            text_col.addWidget(self.lbl_id)
            text_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            row.addLayout(text_col, 1)

            btn_col = QVBoxLayout()
            btn_img = QPushButton("\uD504\uB85C\uD544 \uC218\uC815")
            btn_del = QPushButton("\uC0AD\uC81C")
            btn_img.clicked.connect(lambda: self.on_profile(self.gid))
            btn_del.clicked.connect(lambda: self.on_delete(self.gid))
            btn_col.addWidget(btn_img)
            btn_col.addWidget(btn_del)
            row.addLayout(btn_col)
            lay.addLayout(row)
        else:
            lay.addWidget(self.lbl_img, 0, Qt.AlignmentFlag.AlignHCenter)

            self.lbl_name = QLabel(self.name)
            self.lbl_name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.lbl_name.setStyleSheet("font-size:14px; font-weight:700; color:#f7f7f7;")
            lay.addWidget(self.lbl_name)

            self.lbl_id = QLabel(f"@{self.gid}")
            self.lbl_id.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.lbl_id.setStyleSheet("font-size:11px; color:#f7f7f7;")
            lay.addWidget(self.lbl_id)

            btn_row = QHBoxLayout()
            btn_img = QPushButton("\uD504\uB85C\uD544 \uC218\uC815")
            btn_del = QPushButton("\uC0AD\uC81C")
            btn_img.clicked.connect(lambda: self.on_profile(self.gid))
            btn_del.clicked.connect(lambda: self.on_delete(self.gid))
            btn_row.addWidget(btn_img)
            btn_row.addWidget(btn_del)
            lay.addLayout(btn_row)

        self.setLayout(lay)
        self.setStyleSheet(
            "QWidget#PlayerCard{background:#1b1f2a; border:1px solid #2a3040; border-radius:16px;}"
        )

    def _set_image(self):
        size = 90 if not self.is_list else 64
        if self.avatar_shape == "square":
            pix = _square_pixmap(self.img_path, size)
        else:
            pix = _circle_pixmap(self.img_path, size)
        if pix is None:
            self.lbl_img.setText("NO PORTRAIT")
            self.lbl_img.setStyleSheet("color:#999; font-size:10px;")
        else:
            self.lbl_img.setPixmap(pix)


class PlayerImageDialog(QDialog):
    def __init__(self, parent: QWidget, cfg: "AppConfig", on_changed: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.cfg = cfg
        self._on_changed = on_changed or (lambda: None)
        self._gid: str = ""
        self.setWindowTitle("선수 초상화 관리")

        lay = QVBoxLayout()
        self.tbl_images = QTableWidget(0, 4)
        self.tbl_images.setHorizontalHeaderLabels(["GAME_ID", "선수 닉네임", "초상화 경로", "미리보기"])
        self.tbl_images.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_images.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_images.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tbl_images.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.tbl_images)

        row = QHBoxLayout()
        btn_edit = QPushButton("초상화 변경")
        btn_paste = QPushButton("\uBD99\uC5EC\uB123\uAE30")
        btn_del = QPushButton("\uCD08\uC0C1\uD654 \uC0AD\uC81C")
        btn_close = QPushButton("\uB2EB\uAE30")
        btn_edit.clicked.connect(self._edit_image)
        btn_paste.clicked.connect(self._paste_image)
        btn_del.clicked.connect(self._delete_image)
        btn_close.clicked.connect(self.close)
        row.addWidget(btn_edit)
        row.addWidget(btn_paste)
        row.addWidget(btn_del)
        row.addStretch(1)
        row.addWidget(btn_close)
        lay.addLayout(row)

        self.setLayout(lay)
        self._reload()

    def set_gid(self, gid: str):
        self._gid = gid or ""
        self._reload()

    def _reload(self):
        self.tbl_images.setRowCount(0)
        gid = self._gid
        if not gid:
            return
        if gid not in self.cfg.players:
            return
        name = self.cfg.players.get(gid, "")
        r = self.tbl_images.rowCount()
        self.tbl_images.insertRow(r)
        self.tbl_images.setItem(r, 0, QTableWidgetItem(gid))
        self.tbl_images.setItem(r, 1, QTableWidgetItem(name))
        img_path = _player_image_path_for_gid(self.cfg, gid)
        self.tbl_images.setItem(r, 2, QTableWidgetItem(img_path))

        preview = QLabel()
        preview.setFixedSize(80, 80)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_path = resolve_player_image_path(img_path)
        if preview_path and os.path.exists(preview_path):
            pix = QPixmap(preview_path)
            if not pix.isNull():
                preview.setPixmap(
                    pix.scaled(
                        80,
                        80,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                preview.setText("?놁쓬")
        else:
            preview.setText("?놁쓬")
        self.tbl_images.setCellWidget(r, 3, preview)

    def _current_gid(self) -> str:
        row = self.tbl_images.currentRow()
        if row < 0:
            return ""
        gid_item = self.tbl_images.item(row, 0)
        if gid_item is None:
            return ""
        return gid_item.text()

    def select_gid(self, gid: str):
        self.set_gid(gid)
        if self.tbl_images.rowCount() > 0:
            self.tbl_images.setCurrentCell(0, 0)

    def _edit_image(self):
        gid = self._current_gid()
        if not gid:
            return
        path, _ = QFileDialog.getOpenFileName(self, "\uC120\uC218 \uCD08\uC0C1\uD654 \uC120\uD0DD", "", "\uC774\uBBF8\uC9C0 \uD30C\uC77C (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        self.cfg.players_images[gid] = to_app_rel(path)
        self._reload()
        self._on_changed()

    def _paste_image(self):
        gid = self._current_gid()
        if not gid:
            return
        cb = QGuiApplication.clipboard()
        img = cb.image()
        if img.isNull():
            md = cb.mimeData()
            if md and md.hasUrls():
                local = md.urls()[0].toLocalFile()
                if local:
                    self.cfg.players_images[gid] = to_app_rel(local)
                    self._reload()
                    self._on_changed()
                    return
            QMessageBox.information(self, "\uBD99\uC5EC\uB123\uAE30", "\uD074\uB9BD\uBCF4\uB4DC\uC5D0 \uCD08\uC0C1\uD654\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4.")
            return
        base_dir = app_path("image", "players")
        os.makedirs(base_dir, exist_ok=True)
        filename = f"{gid}_{uuid.uuid4().hex[:8]}.png"
        path = os.path.join(base_dir, filename)
        img.save(path, "PNG")
        self.cfg.players_images[gid] = to_app_rel(path)
        self._reload()
        self._on_changed()

    def _delete_image(self):
        gid = self._current_gid()
        if not gid:
            return
        if not self.cfg.players_images.get(gid, ""):
            return
        resp = QMessageBox.question(
            self,
            "\uCD08\uC0C1\uD654 \uC0AD\uC81C",
            "\uC120\uD0DD\uD55C \uCD08\uC0C1\uD654\uB97C \uC0AD\uC81C\uD560\uAE4C\uC694?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        self.cfg.players_images[gid] = ""
        self._reload()
        self._on_changed()


class AvatarButton(QWidget):
    def __init__(self, parent: QWidget, size: int, img_path: str, on_click: Callable[[], None]):
        super().__init__(parent)
        self._size = size
        self._img_path = img_path
        self._on_click = on_click
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_image(self, img_path: str):
        self._img_path = img_path
        self.update()

    def mousePressEvent(self, event):
        if self._on_click:
            self._on_click()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        if self._img_path:
            pix = _circle_pixmap(self._img_path, self._size)
            if pix is not None:
                painter.drawPixmap(0, 0, pix)
                return
        # Fallback avatar with camera icon
        painter.setBrush(QColor("#6f737a"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(rect)
        painter.setBrush(QColor("#8b9098"))
        inner = rect.adjusted(10, 10, -10, -10)
        painter.drawEllipse(inner)
        # Camera icon
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(Qt.PenStyle.NoPen)
        cam = rect.adjusted(26, 32, -26, -22)
        painter.drawRoundedRect(cam, 6, 6)
        lens = cam.adjusted(10, 6, -10, -6)
        painter.setBrush(QColor("#cfd3d9"))
        painter.drawEllipse(lens)


class EditPlayerDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        gid: str,
        name: str,
        country: str = "KR",
        flag_path: str = "",
        on_flag_pick: Optional[Callable[[str], str]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("\uD504\uB85C\uD544 \uC218\uC815")
        self._gid = gid
        self._name = name
        self._flag_path = flag_path or ""
        self._on_flag_pick = on_flag_pick
        self.setStyleSheet("QWidget{font-family:'Malgun Gothic','맑은 고딕','Segoe UI',sans-serif;}")

        lay = QVBoxLayout()

        form = QGridLayout()
        form.addWidget(QLabel("GAME_ID"), 0, 0)
        self.txt_gid = QLineEdit(gid)
        form.addWidget(self.txt_gid, 0, 1)

        form.addWidget(QLabel("\uC120\uC218 \uB2C9\uB124\uC784"), 1, 0)
        self.txt_name = QLineEdit(name)
        form.addWidget(self.txt_name, 1, 1)

        form.addWidget(QLabel("국적"), 2, 0)
        self.cmb_country = QComboBox()
        self.cmb_country.setStyleSheet("QComboBox,QAbstractItemView{font-family:'Malgun Gothic','맑은 고딕','Segoe UI',sans-serif;}")
        self.cmb_country.addItem("한국", "KR")
        self.cmb_country.addItem("일본", "JP")
        idx = self.cmb_country.findData(_normalize_player_country(country))
        self.cmb_country.setCurrentIndex(idx if idx >= 0 else 0)
        form.addWidget(self.cmb_country, 2, 1)

        form.addWidget(QLabel("국기 이미지"), 3, 0)
        flag_row = QHBoxLayout()
        self.lbl_flag_path = QLabel("")
        self.lbl_flag_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        btn_flag = QPushButton("\uAD6D\uAE30 \uC120\uD0DD")
        btn_flag_clear = QPushButton("\uC0AD\uC81C")
        btn_flag.clicked.connect(self._pick_flag)
        btn_flag_clear.clicked.connect(self._clear_flag)
        flag_row.addWidget(self.lbl_flag_path, 1)
        flag_row.addWidget(btn_flag)
        flag_row.addWidget(btn_flag_clear)
        form.addLayout(flag_row, 3, 1)
        lay.addLayout(form)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("\ud655\uc778")
        btn_cancel = QPushButton("\uCDE8\uC18C")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        lay.addLayout(btn_row)

        self.setLayout(lay)

    def _pick_flag(self):
        gid = (self.txt_gid.text() or "").upper().strip()
        if not gid:
            QMessageBox.information(self, "\uC785\uB825 \uC624\uB958", "\uBA3C\uC800 GAME_ID\uB97C \uC785\uB825\uD558\uC138\uC694.")
            return
        path = ""
        if self._on_flag_pick is not None:
            path = self._on_flag_pick(gid)
        if path:
            self._flag_path = path
            self.lbl_flag_path.setText(path)

    def _clear_flag(self):
        self._flag_path = ""
        self.lbl_flag_path.setText("")

    def values(self) -> Tuple[str, str, str, str]:
        gid = (self.txt_gid.text() or "").upper().strip()
        name = (self.txt_name.text() or "").strip()
        country = _normalize_player_country(self.cmb_country.currentData())
        return gid, name, country, self._flag_path


class ProfileEditDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        gid: str,
        name: str,
        img_path: str,
        country: str,
        flag_path: str,
        on_edit: Callable[[str, str, str, str, str], None],
        on_image: Callable[[str], None],
        on_paste: Callable[[str], str],
        on_flag: Callable[[str], str],
    ):
        super().__init__(parent)
        self.setWindowTitle("프로필 수정")
        self._gid = gid
        self._name = name
        self._img_path = img_path
        self._country = _normalize_player_country(country)
        self._flag_path = flag_path or ""
        self._on_edit = on_edit
        self._on_image = on_image
        self._on_paste = on_paste
        self._on_flag = on_flag
        self.setStyleSheet("QWidget{font-family:'Malgun Gothic','맑은 고딕','Segoe UI',sans-serif;}")

        lay = QHBoxLayout()
        self.avatar_btn = AvatarButton(self, 96, img_path, self._edit_image)
        lay.addWidget(self.avatar_btn)

        body = QVBoxLayout()
        self.lbl_id = QLabel(self._gid)
        self.lbl_id.setStyleSheet("font-size:13px; font-weight:700;")
        self.lbl_name = QLabel(self._name)
        self.lbl_name.setStyleSheet("font-size:12px; color:#666;")
        self.lbl_country = QLabel("국적: " + ("일본" if self._country == "JP" else "한국"))
        self.lbl_country.setStyleSheet("font-size:11px; color:#777;")
        body.addWidget(self.lbl_id)
        body.addWidget(self.lbl_name)
        body.addWidget(self.lbl_country)

        btn_row = QHBoxLayout()
        btn_edit = QPushButton("프로필 설정")
        btn_edit.clicked.connect(self._edit_profile)
        btn_row.addWidget(btn_edit)
        body.addLayout(btn_row)
        lay.addLayout(body, 1)

        self.setLayout(lay)

    def _edit_profile(self):
        dlg = EditPlayerDialog(self, self._gid, self._name, self._country, self._flag_path, self._on_flag)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_gid, new_name, new_country, new_flag = dlg.values()
        ok, final_gid, final_name = self._on_edit(self._gid, new_gid, new_name, new_country, new_flag)
        if not ok:
            return
        self._gid = final_gid
        self._name = final_name
        self._country = new_country
        self._flag_path = new_flag
        self.lbl_id.setText(self._gid)
        self.lbl_name.setText(self._name)
        self.lbl_country.setText("국적: " + ("일본" if self._country == "JP" else "한국"))

    def _edit_image(self):
        new_path = self._on_image(self._gid)
        if new_path:
            self._img_path = new_path
            self.avatar_btn.set_image(new_path)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            path = self._on_paste(self._gid)
            if not path:
                QMessageBox.information(self, "\uBD99\uC5EC\uB123\uAE30", "\uD074\uB9BD\uBCF4\uB4DC\uC5D0 \uCD08\uC0C1\uD654\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4.")
                return
            self._img_path = path
            self.avatar_btn.set_image(path)
            event.accept()
            return
        super().keyPressEvent(event)


class OverlayProfileDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        gid: str,
        name: str,
        img_path: str,
        country: str,
        flag_path: str,
        mode: str,
        on_pick: Callable[[str], str],
        on_paste: Callable[[str], str],
        on_url: Callable[[str], Optional[str]],
        on_flag_pick: Callable[[str], str],
        on_save: Callable[[str, str, str, str, str, str], bool],
        on_delete: Optional[Callable[[str], bool]] = None,
        existing_names: Optional[List[str]] = None,
    ):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._gid = gid
        self._name = name
        self._img_path = img_path or ""
        self._country = _normalize_player_country(country)
        self._flag_path = flag_path or ""
        self._on_pick = on_pick
        self._on_paste = on_paste
        self._on_url = on_url
        self._on_flag_pick = on_flag_pick
        self._on_save = on_save
        self._on_delete = on_delete
        self._mode = mode
        self._existing_names = [str(v or "").strip() for v in (existing_names or []) if str(v or "").strip()]
        self.setStyleSheet("QWidget{font-family:'Malgun Gothic','맑은 고딕','Segoe UI',sans-serif;}")

        title = "프로필 등록" if mode == "register" else "프로필 수정"
        self.setWindowTitle(title)

        lay = QVBoxLayout()
        head = QHBoxLayout()
        self.avatar_btn = AvatarButton(self, 96, self._img_path, self._pick_image)
        head.addWidget(self.avatar_btn)
        info = QVBoxLayout()
        info.addWidget(QLabel("ID"))
        row_gid = QHBoxLayout()
        self.txt_gid = QLineEdit(self._gid)
        self.txt_gid.editingFinished.connect(self._normalize_gid)
        btn_copy_gid = QPushButton("ID 복사")
        btn_copy_gid.clicked.connect(self._copy_gid)
        row_gid.addWidget(self.txt_gid, 1)
        row_gid.addWidget(btn_copy_gid)
        info.addLayout(row_gid)
        info.addWidget(QLabel(""))
        row_name = QHBoxLayout()
        self.txt_name = QLineEdit(self._name)
        btn_copy_name = QPushButton("닉네임 복사")
        btn_copy_name.clicked.connect(self._copy_name)
        row_name.addWidget(self.txt_name, 1)
        row_name.addWidget(btn_copy_name)
        info.addLayout(row_name)
        info.addWidget(QLabel("\uAD6D\uC801"))
        self.cmb_country = QComboBox()
        self.cmb_country.setStyleSheet("QComboBox,QAbstractItemView{font-family:'Malgun Gothic','맑은 고딕','Segoe UI',sans-serif;}")
        self.cmb_country.addItem("한국", "KR")
        self.cmb_country.addItem("일본", "JP")
        cidx = self.cmb_country.findData(self._country)
        self.cmb_country.setCurrentIndex(cidx if cidx >= 0 else 0)
        info.addWidget(self.cmb_country)
        if self._mode == "register" and self._existing_names:
            info.addWidget(QLabel("\uAE30\uC874 \uB2C9\uB124\uC784 \uC120\uD0DD"))
            self.cmb_existing_name = QComboBox()
            self.cmb_existing_name.addItem("직접 입력")
            seen = set()
            for nm in sorted(self._existing_names, key=lambda s: s.lower()):
                key = nm.lower()
                if key in seen:
                    continue
                seen.add(key)
                self.cmb_existing_name.addItem(nm)
            self.cmb_existing_name.currentIndexChanged.connect(self._on_existing_name_changed)
            info.addWidget(self.cmb_existing_name)
        head.addLayout(info, 1)
        lay.addLayout(head)

        btn_row = QHBoxLayout()
        btn_pick = QPushButton("\uC0AC\uC9C4 \uC120\uD0DD")
        btn_paste = QPushButton("\uBD99\uC5EC\uB123\uAE30")
        btn_url = QPushButton("URL 붙여넣기")
        btn_clear = QPushButton("\uC0AC\uC9C4 \uC0AD\uC81C")
        btn_pick.clicked.connect(self._pick_image)
        btn_paste.clicked.connect(self._paste_image)
        btn_url.clicked.connect(self._url_image)
        btn_clear.clicked.connect(self._clear_image)
        btn_row.addWidget(btn_pick)
        btn_row.addWidget(btn_paste)
        btn_row.addWidget(btn_url)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        flag_row = QHBoxLayout()
        self.lbl_flag_path = QLabel("")
        self.lbl_flag_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        btn_flag = QPushButton("\uAD6D\uAE30 \uC774\uBBF8\uC9C0")
        btn_flag_clear = QPushButton("\uAD6D\uAE30 \uC0AD\uC81C")
        btn_flag.clicked.connect(self._pick_flag)
        btn_flag_clear.clicked.connect(self._clear_flag)
        flag_row.addWidget(QLabel("국기"))
        flag_row.addWidget(self.lbl_flag_path, 1)
        flag_row.addWidget(btn_flag)
        flag_row.addWidget(btn_flag_clear)
        lay.addLayout(flag_row)

        row = QHBoxLayout()
        if self._on_delete is not None:
            btn_delete = QPushButton("\uC774 ID \uC0AD\uC81C")
            btn_delete.clicked.connect(self._delete_id)
            row.addWidget(btn_delete)
            row.addStretch(1)
        else:
            row.addStretch(1)
        btn_ok = QPushButton("저장")
        btn_cancel = QPushButton("\uCDE8\uC18C")
        btn_ok.clicked.connect(self._save)
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_ok)
        row.addWidget(btn_cancel)
        lay.addLayout(row)
        self.setLayout(lay)

    def _normalize_gid(self):
        self.txt_gid.setText((self.txt_gid.text() or "").strip().upper())

    def _current_gid(self) -> str:
        return (self.txt_gid.text() or "").strip().upper()

    def _copy_text(self, text: str):
        txt = str(text or "")
        if not txt:
            return
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(txt)

    def _copy_gid(self):
        self._copy_text(self._current_gid())

    def _copy_name(self):
        self._copy_text((self.txt_name.text() or "").strip())

    def _pick_image(self):
        path = self._on_pick(self._current_gid())
        if path:
            self._img_path = path
            self.avatar_btn.set_image(path)

    def _paste_image(self):
        path = self._on_paste(self._current_gid())
        if not path:
            QMessageBox.information(self, "\uBD99\uC5EC\uB123\uAE30", "\uD074\uB9BD\uBCF4\uB4DC\uC5D0 \uCD08\uC0C1\uD654\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4.")
            return
        self._img_path = path
        self.avatar_btn.set_image(path)

    def _url_image(self):
        path = self._on_url(self._current_gid())
        if path is None:
            return
        if not path:
            QMessageBox.information(self, "URL", "\uC774\uBBF8\uC9C0 URL\uC744 \uBD88\uB7EC\uC624\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4.")
            return
        self._img_path = path
        self.avatar_btn.set_image(path)

    def _clear_image(self):
        self._img_path = ""
        self.avatar_btn.set_image("")

    def _pick_flag(self):
        path = self._on_flag_pick(self._current_gid())
        if path:
            self._flag_path = path
            self.lbl_flag_path.setText(path)

    def _clear_flag(self):
        self._flag_path = ""
        self.lbl_flag_path.setText("")

    def _on_existing_name_changed(self, _idx: int):
        if not hasattr(self, "cmb_existing_name"):
            return
        if self.cmb_existing_name.currentIndex() <= 0:
            return
        sel = str(self.cmb_existing_name.currentText() or "").strip()
        if sel:
            self.txt_name.setText(sel)

    def _save(self):
        new_gid = self._current_gid()
        name = (self.txt_name.text() or "").strip()
        if not new_gid:
            QMessageBox.information(self, "\uC785\uB825 \uC624\uB958", "ID\uB97C \uC785\uB825\uD558\uC138\uC694.")
            return
        if not name:
            QMessageBox.information(self, "\uC785\uB825 \uC624\uB958", "\uB2C9\uB124\uC784\uC744 \uC785\uB825\uD558\uC138\uC694.")
            return
        ok = False
        try:
            ok = bool(self._on_save(
                self._gid,
                new_gid,
                name,
                self._img_path,
                _normalize_player_country(self.cmb_country.currentData()),
                self._flag_path,
            ))
        except Exception:
            ok = False
        if not ok:
            return
        self._gid = new_gid
        self._name = name
        self.accept()

    def _delete_id(self):
        if self._on_delete is None:
            return
        gid = self._current_gid()
        if not gid:
            return
        resp = QMessageBox.question(
            self,
            "ID 삭제",
            f"{gid} 아이디를 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        ok = False
        try:
            ok = bool(self._on_delete(gid))
        except Exception:
            ok = False
        if ok:
            self.accept()


class SettingsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        cfg: AppConfig,
        controller: Controller,
        watcher: ScreenWatcher,
        cfg_path: Optional[str] = None,
        timer_win: Optional[object] = None,
        chapter_sync_now: Optional[Callable[[], None]] = None,
        chapter_clear: Optional[Callable[[], None]] = None,
        chapter_export: Optional[Callable[[], str]] = None,
        chapter_open: Optional[Callable[[], str]] = None,
        chapter_status_getter: Optional[Callable[[], str]] = None,
        action_runner: Optional[ActionRunner] = None,
        player_state_apply: Optional[Callable[[AppConfig], None]] = None,
        detection_start: Optional[Callable[[], None]] = None,
        detection_stop: Optional[Callable[[], None]] = None,
        detection_running: Optional[Callable[[], bool]] = None,
        screen_detection_start: Optional[Callable[[], None]] = None,
        screen_detection_stop: Optional[Callable[[], None]] = None,
        screen_detection_running: Optional[Callable[[], bool]] = None,
        log_detection_start: Optional[Callable[[], None]] = None,
        log_detection_stop: Optional[Callable[[], None]] = None,
        log_detection_running: Optional[Callable[[], bool]] = None,
        diagnostic_mark_incident: Optional[Callable[[str], object]] = None,
        diagnostic_export_zip: Optional[Callable[[], str]] = None,
        diagnostic_open_folder: Optional[Callable[[], str]] = None,
        diagnostic_copy_state: Optional[Callable[[], str]] = None,
        diagnostic_project_snapshot: Optional[Callable[[], str]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setMinimumSize(760, 560)
        self.resize(980, 700)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setSizeGripEnabled(True)
        self.setWindowState(Qt.WindowState.WindowNoState)
        self.cfg = cfg
        self._actions_by_event = dict(self.cfg.actions or {})
        self._action_cooldowns_by_event = dict(self.cfg.action_cooldowns or {})
        self._action_edge_triggers_by_event = dict(getattr(self.cfg, "action_edge_triggers", {}) or {})
        self.controller = controller
        self.watcher = watcher
        self._cfg_path = cfg_path
        self._player_image_dlg: Optional[PlayerImageDialog] = None
        self._quick_roi_overlay: Optional[QuickRoiOverlay] = None
        self._pixel_pick_overlay: Optional[PixelPickOverlay] = None
        self._trigger_pixel_overlay: Optional[PixelPickOverlay] = None
        self._quick_pick_active = False
        self._quick_roi_monitor: Optional[int] = None
        self._quick_roi_virtual_offset: Optional[Tuple[int, int]] = None
        self._timer_win = timer_win
        self._chapter_sync_now = chapter_sync_now
        self._chapter_clear = chapter_clear
        self._chapter_export = chapter_export
        self._chapter_open = chapter_open
        self._chapter_status_getter = chapter_status_getter
        self._player_state_apply = player_state_apply
        self._detection_start = detection_start
        self._detection_stop = detection_stop
        self._detection_running = detection_running
        self._screen_detection_start = screen_detection_start or detection_start
        self._screen_detection_stop = screen_detection_stop or detection_stop
        self._screen_detection_running = screen_detection_running or detection_running
        self._log_detection_start = log_detection_start or detection_start
        self._log_detection_stop = log_detection_stop or detection_stop
        self._log_detection_running = log_detection_running or detection_running
        self._diagnostic_mark_incident = diagnostic_mark_incident
        self._diagnostic_export_zip = diagnostic_export_zip
        self._diagnostic_open_folder = diagnostic_open_folder
        self._diagnostic_copy_state = diagnostic_copy_state
        self._diagnostic_project_snapshot = diagnostic_project_snapshot
        timer_target = self._timer_win or getattr(self.controller, "timer_win", None)
        if timer_target is None:
            timer_target = _NoopTimerWindow()
        self.action_runner = action_runner or ActionRunner(self.controller, timer_target, self._noop_status)
        self._tts_test_audio_outs: Dict[str, Any] = {}
        self._tts_test_players: Dict[str, Any] = {}
        self._tts_test_files: Dict[str, List[str]] = {"analyst": [], "caster": []}
        self._tts_test_busy: Dict[str, bool] = {"analyst": False, "caster": False}
        self._commentary_test_script_token: Optional[object] = None
        self._commentary_test_script_queue = deque()
        self._commentary_test_script_name: str = ""
        # Build-release exe에서 설정창 열 때 Qt Multimedia 백엔드 로딩이 GUI를 멈출 수 있어
        # 사운드/TTS 테스트 플레이어는 버튼을 눌렀을 때만 지연 생성한다.
        self._spectator_sfx_audio_out = None
        self._spectator_sfx_player = None
        try:
            logging.info(
                "SETTINGS_ACTION_RUNNER shared=%s id=%s",
                bool(action_runner is not None),
                hex(id(self.action_runner)),
            )
        except Exception:
            pass
        self._action_default_pos: Optional[Tuple[int, int]] = None
        self._action_pick_monitor: Optional[int] = None
        self._pending_action_pick: Optional[str] = None
        self._pending_action_pick_btn: Optional[QPushButton] = None
        self._pending_action_pick_text: str = ""
        self._test_action_last_run: Dict[str, float] = {}
        self._test_blue_streak = 0
        self._test_red_streak = 0
        self._new_player_image_path = ""
        self._new_player_flag_path = ""

        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.tab_players = QWidget()
        self.tab_timer = QWidget()
        self.tab_overlay = QWidget()
        self.tab_hit_effects = QWidget()
        self.tab_logs = QWidget()
        self.tab_log_records = QWidget()
        self.tab_auto_start = QWidget()
        self.tab_sound = QWidget()
        self.tab_tests = QWidget()
        self.tab_legacy = QWidget()
        self.tab_palette = QWidget()
        self.tab_actions = QWidget()
        self.tab_pixels = QWidget()
        self.tab_automation = QWidget()
        self.tab_effects = QWidget()
        self.tab_diagnostics = QWidget()

        self.tabs.addTab(self.tab_players, "플레이어")
        self.tabs.addTab(self.tab_overlay, "오버레이")
        self.tabs.addTab(self.tab_hit_effects, "피격 효과")
        self.tabs.addTab(self.tab_logs, "로그 감지")
        self.tabs.addTab(self.tab_log_records, "기록")
        self.tabs.addTab(self.tab_auto_start, "자동 시작")
        self.tabs.addTab(self.tab_sound, "사운드")
        self.tabs.addTab(self.tab_tests, "테스트")
        self.tabs.addTab(self.tab_legacy, "화면감지 / 액션")
        self.tabs.addTab(self.tab_effects, "연승 이펙트")
        self.tabs.addTab(self.tab_diagnostics, "진단")

        self.btn_apply = QPushButton("적용")
        self.btn_save = QPushButton("저장")
        self.btn_load = QPushButton("불러오기")
        self.btn_help = QPushButton("\ub3c4\uc6c0\ub9d0")
        self.btn_close = QPushButton("닫기")
        self.btn_quit = QPushButton("종료")
        self.btn_detect_toggle = QPushButton("감지 시작")
        self.btn_screen_detect_toggle = QPushButton("화면 감지 시작")
        self.btn_apply.clicked.connect(self.apply_only)
        self.btn_save.clicked.connect(self.save_profile)
        self.btn_load.clicked.connect(self.load_profile)
        self.btn_help.clicked.connect(self._open_help)
        self.btn_close.clicked.connect(self.close)
        self.btn_quit.clicked.connect(QApplication.instance().quit)
        self.btn_detect_toggle.clicked.connect(self._toggle_detection)
        self.btn_screen_detect_toggle.clicked.connect(self._toggle_screen_detection)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.btn_apply)
        bottom.addWidget(self.btn_detect_toggle)
        bottom.addWidget(self.btn_screen_detect_toggle)
        bottom.addWidget(self.btn_save)
        bottom.addWidget(self.btn_load)
        bottom.addWidget(self.btn_help)
        bottom.addWidget(self.btn_close)
        bottom.addWidget(self.btn_quit)

        layout = QVBoxLayout()
        layout.addWidget(self.tabs)
        layout.addLayout(bottom)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        self.setLayout(layout)

        self._apply_settings_style()

        self._build_quick()
        self._build_players()
        self._build_timer()
        self._build_effects()
        self._build_diagnostics()
        self._build_actions()
        self._build_pixels()
        self._build_automation()
        self._build_legacy_tab()
        self._normalize_settings_layout()
        self.setWindowTitle("설정")

        self._refresh_action_pick_labels()

        self.btn_apply.setVisible(False)

        self._suspend_apply = False
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.timeout.connect(self._apply_silent)
        self._install_auto_apply()
        self._install_wheel_focus()
        self._timer_apply_armed_until = 0.0

        self._sync_watcher_labels()
        QApplication.instance().installEventFilter(self)

    def _sync_watcher_labels(self):
        if hasattr(self, "lbl_pixel_state") and self.watcher:
            running = self._screen_running()
            self.lbl_pixel_state.setText("실행 중" if running else "중지")
        self._update_detect_button()

    def _log_running(self) -> bool:
        if callable(getattr(self, "_log_detection_running", None)):
            return bool(self._log_detection_running())
        if callable(getattr(self, "_detection_running", None)):
            return bool(self._detection_running())
        return False

    def _screen_running(self) -> bool:
        if callable(getattr(self, "_screen_detection_running", None)):
            return bool(self._screen_detection_running())
        return bool(self.watcher and self.watcher.is_running())

    def eventFilter(self, obj, event):
        if not hasattr(self, "_pending_action_pick"):
            self._pending_action_pick = None
            self._pending_action_pick_btn = None
            self._pending_action_pick_text = ""
        if self._pending_action_pick and event.type() == QEvent.Type.KeyPress:
            try:
                pos = QCursor.pos()
                x = int(pos.x())
                y = int(pos.y())
                if self._pending_action_pick == "mouse":
                    if hasattr(self, "sp_mouse_x"):
                        self.sp_mouse_x.setValue(x)
                    if hasattr(self, "sp_mouse_y"):
                        self.sp_mouse_y.setValue(y)
                elif self._pending_action_pick == "click":
                    if hasattr(self, "sp_click_x"):
                        self.sp_click_x.setValue(x)
                    if hasattr(self, "sp_click_y"):
                        self.sp_click_y.setValue(y)
            except Exception:
                pass
            if self._pending_action_pick_btn is not None:
                try:
                    self._pending_action_pick_btn.setText(self._pending_action_pick_text)
                except Exception:
                    pass
            self._pending_action_pick = None
            self._pending_action_pick_btn = None
            self._pending_action_pick_text = ""
            return True
        return False

    def _update_detect_button(self):
        log_running = self._log_running()
        screen_running = self._screen_running()
        if hasattr(self, "btn_detect_toggle"):
            if log_running:
                self.btn_detect_toggle.setText("로그 감지 중지")
                self.btn_detect_toggle.setStyleSheet("background:#ef4444; color:#ffffff; border-radius:10px; padding:8px 14px;")
            else:
                self.btn_detect_toggle.setText("로그 감지 시작")
                self.btn_detect_toggle.setStyleSheet("background:#22c55e; color:#ffffff; border-radius:10px; padding:8px 14px;")
        if hasattr(self, "btn_screen_detect_toggle"):
            if screen_running:
                self.btn_screen_detect_toggle.setText("화면 감지 중지")
                self.btn_screen_detect_toggle.setStyleSheet("background:#ef4444; color:#ffffff; border-radius:10px; padding:8px 14px;")
            else:
                self.btn_screen_detect_toggle.setText("화면 감지 시작")
                self.btn_screen_detect_toggle.setStyleSheet("background:#2563eb; color:#ffffff; border-radius:10px; padding:8px 14px;")

    def _toggle_detection(self):
        if self._log_running():
            self._log_stop()
        else:
            self._log_start()
        self._update_detect_button()

    def _toggle_screen_detection(self):
        if self._screen_running():
            self._screen_stop()
        else:
            self._screen_start()
        self._update_detect_button()

    def _open_help(self):
        path = app_path("HELP.md")
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            text = ""
        dlg = QDialog(self)
        dlg.setWindowTitle("\ub3c4\uc6c0\ub9d0")
        dlg.resize(780, 640)
        lay = QVBoxLayout(dlg)
        view = QTextEdit()
        view.setReadOnly(True)
        if text:
            view.setPlainText(text)
        else:
            view.setPlainText("HELP.md \ud30c\uc77c\uc744 \ucc3e\uc744 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.")
        lay.addWidget(view)
        btn = QPushButton("\ub2eb\uae30")
        btn.clicked.connect(dlg.close)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn)
        lay.addLayout(row)
        dlg.exec()

    def _roi_quick_items(self) -> List[Tuple[str, str]]:
        return [
            ("왼쪽 선수 이미지 범위 (= BLUE)", "roi_left_player"),
            ("오른쪽 선수 이미지 범위 (= RED)", "roi_right_player"),
        ]
    def _apply_quick_roi(self, attr_name: str, rect: Rect):
        if self._quick_roi_monitor is not None:
            rect = rect_local_to_global(int(self._quick_roi_monitor), rect)
        elif self._quick_roi_virtual_offset is not None:
            dx, dy = self._quick_roi_virtual_offset
            rect = Rect(x=int(rect.x + dx), y=int(rect.y + dy), w=int(rect.w), h=int(rect.h))
        setattr(self.cfg, attr_name, rect)
        self._update_quick_labels()
        if hasattr(self, "lbl_lplayer"):
            self.lbl_lplayer.setText(self._roi_text(self.cfg.roi_left_player))
        if hasattr(self, "lbl_rplayer"):
            self.lbl_rplayer.setText(self._roi_text(self.cfg.roi_right_player))
        if hasattr(self, "_refresh_koth_setup_state"):
            self._refresh_koth_setup_state()
        self._schedule_apply()

    def _roi_text(self, r: Rect) -> str:
        if r is None:
            return "Unset"
        if not r.valid():
            return "Unset"
        return f"x={int(r.x)}, y={int(r.y)}, w={int(r.w)}, h={int(r.h)}"

    def _trigger_pixel_text(self) -> str:
        r = self.cfg.roi_trigger
        if r.valid() and int(r.w) == 1 and int(r.h) == 1:
            b, g, rr = self.cfg.trigger.target_bgr
            return f"픽셀 x={int(r.x)}, y={int(r.y)} | BGR=({int(b)},{int(g)},{int(rr)})"
        return "Pixel unset"

    def _trigger_pixel_copy_text(self) -> str:
        r = self.cfg.roi_trigger
        if not (r.valid() and int(r.w) == 1 and int(r.h) == 1):
            return ""
        if hasattr(self, "sp_b") and hasattr(self, "sp_g") and hasattr(self, "sp_r"):
            b = int(self.sp_b.value())
            g = int(self.sp_g.value())
            rr = int(self.sp_r.value())
        else:
            b, g, rr = self.cfg.trigger.target_bgr
            b = int(b); g = int(g); rr = int(rr)
        return f"x={int(r.x)}, y={int(r.y)}, B={b}, G={g}, R={rr}"

    def _copy_trigger_pixel_value(self):
        text = self._trigger_pixel_copy_text()
        if not text:
            QMessageBox.information(self, "안내", "트리거 픽셀이 설정되어 있지 않습니다.")
            return
        cb = QApplication.clipboard()
        if cb is None:
            return
        cb.setText(text)
        if hasattr(self, "btn_copy_trigger_pixel"):
            self.btn_copy_trigger_pixel.setText("")
            QTimer.singleShot(900, lambda: hasattr(self, "btn_copy_trigger_pixel") and self.btn_copy_trigger_pixel.setText("값 복사"))

    def _update_quick_labels(self):
        if hasattr(self, "lbl_trigger"):
            self.lbl_trigger.setText(self._roi_text(self.cfg.roi_trigger))
        if hasattr(self, "lbl_trigger_pixel"):
            self.lbl_trigger_pixel.setText(self._trigger_pixel_text())

    def _start_quick_trigger_pixel_pick(self):
        if self._trigger_pixel_overlay and self._trigger_pixel_overlay.isVisible():
            return
        if self._quick_pick_active:
            return
        if hasattr(self, "trigger_group"):
            self._set_trigger_group_visible(True)
        self._quick_pick_active = True
        overlay = PixelPickOverlay(
            self._sample_pixel_at_global,
            message="트리거 픽셀 선택: 마우스를 움직이고 아무 키나 누르세요. (ESC 취소)",
            accept_on_key=True,
            on_accept=self._finish_quick_trigger_pixel_pick,
        )
        rect = QGuiApplication.primaryScreen().geometry()
        for scr in QGuiApplication.screens():
            rect = rect.united(scr.geometry())
        overlay.setGeometry(rect)
        overlay.destroyed.connect(lambda _o=None: setattr(self, "_quick_pick_active", False))
        overlay.destroyed.connect(lambda _o=None: setattr(self, "_trigger_pixel_overlay", None))
        overlay.show()
        overlay.raise_()
        self._trigger_pixel_overlay = overlay

    def _show_trigger_settings(self):
        if hasattr(self, "trigger_group"):
            self._set_trigger_group_visible(not self.trigger_group.isVisible())

    def _set_trigger_group_visible(self, visible: bool):
        if not hasattr(self, "trigger_group"):
            return
        self.trigger_group.setVisible(bool(visible))

    def _emit_win_streaks(self):
        try:
            self.controller.ui_update.emit({
                "blue_win_streak": int(self._test_blue_streak),
                "red_win_streak": int(self._test_red_streak),
            })
        except Exception:
            pass

    def _test_blue_win(self):
        self._test_blue_streak = int(self._test_blue_streak) + 1
        self._test_red_streak = 0
        self._emit_win_streaks()

    def _test_red_win(self):
        self._test_red_streak = int(self._test_red_streak) + 1
        self._test_blue_streak = 0
        self._emit_win_streaks()

    def _test_reset_win(self):
        self._test_blue_streak = 0
        self._test_red_streak = 0
        self._emit_win_streaks()

    def _finish_quick_trigger_pixel_pick(self):
        if not self._trigger_pixel_overlay:
            return
        pos, bgr = self._trigger_pixel_overlay.current_sample()
        try:
            self._trigger_pixel_overlay.close()
        except Exception:
            pass
        self._trigger_pixel_overlay = None
        self._quick_pick_active = False
        self._apply_trigger_pixel_from_sample(pos, bgr)

    def _apply_trigger_pixel_from_sample(self, pos: QPoint, bgr: Tuple[int, int, int]):
        self.cfg.roi_trigger = Rect(x=int(pos.x()), y=int(pos.y()), w=1, h=1)
        self.cfg.trigger.target_bgr = (int(bgr[0]), int(bgr[1]), int(bgr[2]))
        self.cfg.trigger.enabled = True
        if hasattr(self, "trigger_group"):
            self._set_trigger_group_visible(True)
        self._update_quick_labels()
        if hasattr(self, "_refresh_trigger_color_ui"):
            self._refresh_trigger_color_ui()
        self._schedule_apply()

    def _start_quick_roi_pick(self, start_pos=None):
        if self._quick_pick_active:
            return
        pos = start_pos or QCursor.pos()
        try:
            with mss.mss() as sct:
                mon = sct.monitors[0]
                frame = np.array(sct.grab(mon))
                self._quick_roi_virtual_offset = (int(mon["left"]), int(mon["top"]))
        except Exception:
            mon = self._monitor_from_pos(pos.x(), pos.y())
            frame = capture_monitor_np(mon)
            self._quick_roi_virtual_offset = None
        self._quick_pick_active = True
        self._quick_roi_monitor = None
        self._quick_roi_overlay = QuickRoiOverlay(0, frame, self._roi_quick_items(), self._apply_quick_roi)
        self._quick_roi_overlay.destroyed.connect(lambda _o=None: setattr(self, "_quick_pick_active", False))
        self._quick_roi_overlay.show()
        self._quick_roi_overlay.raise_()
        if start_pos is not None:
            self._quick_roi_overlay.begin_at_global(start_pos)

    def pick_roi(self, label: str, attr_name: str):
        if self._quick_pick_active:
            return
        if self._pixel_pick_overlay and self._pixel_pick_overlay.isVisible():
            try:
                self._pixel_pick_overlay.close()
            except Exception:
                pass
            self._pixel_pick_overlay = None
        try:
            with mss.mss() as sct:
                mon = sct.monitors[0]
                img = np.array(sct.grab(mon))
                frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                vleft = int(mon["left"])
                vtop = int(mon["top"])
                vwidth = int(mon["width"])
                vheight = int(mon["height"])
        except Exception:
            frame = None
            vleft = vtop = vwidth = vheight = 0
        if frame is None or frame.size == 0:
            try:
                QMessageBox.warning(self, "ROI 오류", "화면 캡처에 실패했습니다.")
            except Exception:
                pass
            return
        self._quick_pick_active = True
        self._quick_roi_monitor = None
        self._quick_roi_virtual_offset = (vleft, vtop)
        overlay = QuickRoiOverlay(0, frame, [(label, attr_name)], self._apply_quick_roi)
        try:
            overlay.setGeometry(vleft, vtop, vwidth, vheight)
        except Exception:
            pass
        overlay.destroyed.connect(lambda _o=None: setattr(self, "_quick_pick_active", False))
        overlay.destroyed.connect(lambda _o=None: setattr(self, "_quick_roi_monitor", None))
        overlay.destroyed.connect(lambda _o=None: setattr(self, "_quick_roi_virtual_offset", None))
        overlay.show()
        overlay.raise_()
        self._quick_roi_overlay = overlay

    def _monitor_from_pos(self, x: int, y: int) -> int:
        with mss.mss() as sct:
            mons = sct.monitors
            for i in range(1, len(mons)):
                mon = mons[i]
                if mon["left"] <= x < mon["left"] + mon["width"] and mon["top"] <= y < mon["top"] + mon["height"]:
                    return i
        return int(self.cfg.monitor_index)

    def _vk_from_key_name(self, name: str) -> Optional[int]:
        if not name:
            return None
        key = name.upper()
        if key.startswith("F") and key[1:].isdigit():
            n = int(key[1:])
            if 1 <= n <= 12:
                return 0x70 + (n - 1)
        if len(key) == 1:
            ch = key[0]
            if "A" <= ch <= "Z":
                return ord(ch)
            if "0" <= ch <= "9":
                return 0x30 + int(ch)
        return None

    def _parse_hotkey(self, seq: str) -> Optional[Tuple[int, dict]]:
        if not seq:
            return None
        parts = [p for p in seq.replace(" ", "").split("+") if p]
        mods = {"ctrl": False, "alt": False, "shift": False}
        key_part = ""
        for part in parts:
            up = part.upper()
            if up in ("CTRL", "CONTROL"):
                mods["ctrl"] = True
            elif up == "ALT":
                mods["alt"] = True
            elif up == "SHIFT":
                mods["shift"] = True
            else:
                key_part = up
        vk = self._vk_from_key_name(key_part)
        if vk is None:
            return None
        return vk, mods

    def _hotkey_info(self, seq: str) -> Optional[Tuple[int, dict]]:
        if seq in self._hotkey_cache:
            return self._hotkey_cache[seq]
        info = self._parse_hotkey(seq)
        self._hotkey_cache[seq] = info
        return info

    def _start_quick_pixel_pick(self, pos=None):
        if self._pixel_pick_overlay and self._pixel_pick_overlay.isVisible():
            self._finish_quick_pixel_pick()
            return
        if self._quick_pick_active:
            return
        self._quick_pick_active = True
        self._pixel_pick_overlay = PixelPickOverlay(self._sample_pixel_at_global)
        rect = QGuiApplication.primaryScreen().geometry()
        for scr in QGuiApplication.screens():
            rect = rect.united(scr.geometry())
        self._pixel_pick_overlay.setGeometry(rect)
        self._pixel_pick_overlay.destroyed.connect(lambda _o=None: setattr(self, "_quick_pick_active", False))
        self._pixel_pick_overlay.destroyed.connect(lambda _o=None: setattr(self, "_pixel_pick_overlay", None))
        self._pixel_pick_overlay.show()

    def _finish_quick_pixel_pick(self):
        if not self._pixel_pick_overlay:
            return
        pos, bgr = self._pixel_pick_overlay.current_sample()
        self._quick_pick_active = False
        try:
            self._pixel_pick_overlay.close()
        except Exception:
            pass
        self._pixel_pick_overlay = None
        self._show_pixel_pick_menu(pos, int(pos.x()), int(pos.y()), bgr)

    def _cancel_quick_pixel_pick(self):
        if not self._pixel_pick_overlay:
            return
        self._quick_pick_active = False
        try:
            self._pixel_pick_overlay.close()
        except Exception:
            pass
        self._pixel_pick_overlay = None

    def _sample_pixel_at_global(self, pos) -> Tuple[int, int, int]:
        b, g, r = capture_pixel_bgr(int(pos.x()), int(pos.y()), 1)
        return int(b), int(g), int(r)

    def _on_quick_pixel_clicked(self, x: int, y: int, _btn: str):
        b, g, r = capture_pixel_bgr(int(x), int(y), 1)
        self._show_pixel_pick_menu(QCursor.pos(), int(x), int(y), (int(b), int(g), int(r)))

    def _apply_pixel_pick_to_rule(self, idx: int, gx: int, gy: int, bgr: Tuple[int, int, int]):
        if idx < 0 or idx >= len(self._pixel_rules):
            return
        rule = self._pixel_rules[idx]
        rule["mode"] = "pixel"
        rule["x"] = int(gx)
        rule["y"] = int(gy)
        rule["sample"] = 1
        rule["roi"] = {"x": 0, "y": 0, "w": 0, "h": 0}
        rule["target_bgr"] = [int(bgr[0]), int(bgr[1]), int(bgr[2])]
        self._apply_pixel_rules()
        self._render_pixel_cards()
        self._refresh_action_events()
        self._show_actions_for_event(f"pixel:{rule.get('name', f'rule{idx+1}')}")

    def _show_pixel_pick_menu(self, pos, gx: int, gy: int, bgr: Tuple[int, int, int]):
        menu = QMenu()
        menu.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        act_new = menu.addAction("새 조건 추가")
        menu.addSeparator()
        action_map = {}
        for idx, rule in enumerate(self._pixel_rules):
            name = str(rule.get("name", f"rule{idx+1}"))
            act = menu.addAction(f"화면 감지 {idx+1}: {name}")
            action_map[act] = idx
        act = menu.exec(pos)
        if act is None:
            return
        if act == act_new:
            name = f"rule{len(self._pixel_rules)+1}"
            self._pixel_rules.append({
                "id": f"pixel_{uuid.uuid4().hex}",
                "name": name,
                "enabled": True,
                "mode": "pixel",
                "x": int(gx),
                "y": int(gy),
                "sample": 1,
                "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
                "target_bgr": [int(bgr[0]), int(bgr[1]), int(bgr[2])],
                "tolerance": 5,
                "window_frames": 1,
                "consecutive_needed": 1,
                "cooldown_sec": 1.0
            })
            self._apply_pixel_rules()
            self._render_pixel_cards()
            self._refresh_action_events()
            self._show_actions_for_event(f"pixel:{name}")
            return
        if act in action_map:
            self._apply_pixel_pick_to_rule(action_map[act], gx, gy, bgr)

    def _apply_settings_style(self):
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#1f2430"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#e5e7eb"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#141a25"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#1b2230"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#e5e7eb"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#2a3242"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#e5e7eb"))
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#3b82f6"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        self.setPalette(pal)
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            "QDialog { background:#1f2430; color:#e5e7eb; font-family:'Segoe UI'; font-size:12px; }"
            "QWidget { color:#e5e7eb; background:#1f2430; }"
            "QMainWindow { background:#1f2430; }"
            "QTabWidget::pane { border:1px solid #2c3444; background:#232a38; border-radius:10px; }"
            "QTabBar::tab { background:#2a3242; color:#cbd5e1; padding:9px 16px; margin:3px; border-radius:8px; }"
            "QTabBar::tab:selected { background:#1e2533; color:#ffffff; border:1px solid #2c3444; border-bottom-color:#1e2533; }"
            "QTabBar::tab:!selected { color:#9aa3b2; }"
            "QLabel { color:#e5e7eb; }"
            "QScrollArea, QAbstractScrollArea { background:#1f2430; border:0; }"
            "QScrollArea > QWidget { background:#1f2430; }"
            "QScrollArea > QWidget > QWidget { background:#1f2430; }"
            "QAbstractScrollArea::viewport { background:#1f2430; }"
            "QFrame { background:#1f2430; }"
            "QGroupBox { border:1px solid #2c3444; border-radius:12px; margin-top:16px; padding:14px; background:#1b2230; }"
            "QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding:0 10px; "
            "color:#e5e7eb; font-weight:700; background:#1f2735; }"
            "QPushButton { background:#6d5dfc; color:#ffffff; border:0; border-radius:10px; padding:8px 14px; }"
            "QPushButton:hover { background:#7b6bff; }"
            "QPushButton:pressed { background:#5b4ce0; }"
            "QPushButton:disabled { background:#3a4252; color:#9aa3b2; }"
            "QLineEdit, QComboBox, QSpinBox, QTextEdit { background:#141a25; color:#e5e7eb; border:1px solid #2c3444; "
            "border-radius:8px; padding:6px 10px; }"
            "QAbstractItemView { background:#141a25; color:#e5e7eb; border:1px solid #2c3444; selection-background-color:#2b3350; selection-color:#e5e7eb; }"
            "QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width:24px; "
            "border-left:1px solid #2c3444; background:#1f2735; border-top-right-radius:8px; border-bottom-right-radius:8px; }"
            "QComboBox::down-arrow { image:none; width:0; height:0; "
            "border-left:6px solid transparent; border-right:6px solid transparent; border-top:8px solid #e5e7eb; }"
            "QSpinBox::up-button, QSpinBox::down-button { width:20px; background:#1f2735; border-left:1px solid #2c3444; }"
            "QSpinBox::up-arrow { image:none; width:0; height:0; "
            "border-left:5px solid transparent; border-right:5px solid transparent; border-bottom:7px solid #e5e7eb; }"
            "QSpinBox::down-arrow { image:none; width:0; height:0; "
            "border-left:5px solid transparent; border-right:5px solid transparent; border-top:7px solid #e5e7eb; }"
            "QCheckBox::indicator { width:16px; height:16px; border:1px solid #3a455a; background:#141a25; border-radius:4px; }"
            "QCheckBox::indicator:checked { background:#6d5dfc; }"
            "QTableWidget { background:#141a25; color:#e5e7eb; border:1px solid #2c3444; gridline-color:#2c3444; }"
            "QTableWidget::item:selected { background:#2b3350; color:#e5e7eb; }"
            "QHeaderView::section { background:#1f2735; color:#e5e7eb; padding:6px; border:0; border-bottom:1px solid #2c3444; }"
            "QCheckBox { spacing:6px; color:#e5e7eb; }"
        )

    def _normalize_settings_layout(self):
        """Keep settings usable at normal window sizes.

        Several tabs contain old dense grids. Those widgets should scroll inside
        the tab, not force the whole dialog to be maximized.
        """
        try:
            self.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        except Exception:
            pass
        for scroll in self.findChildren(QScrollArea):
            try:
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QFrame.Shape.NoFrame)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                scroll.setMinimumWidth(0)
                scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                w = scroll.widget()
                if w is not None:
                    w.setMinimumWidth(0)
                    w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            except Exception:
                pass
        for line in self.findChildren(QLineEdit):
            try:
                line.setMinimumWidth(0)
                if line.maximumWidth() > 16777200:
                    line.setMaximumWidth(520)
            except Exception:
                pass
        for edit in self.findChildren(QKeySequenceEdit):
            try:
                edit.setMaximumWidth(160)
            except Exception:
                pass

    def _install_auto_apply(self):
        for sp in self.findChildren(QSpinBox):
            sp.valueChanged.connect(self._schedule_apply)
        for dsp in self.findChildren(QDoubleSpinBox):
            dsp.valueChanged.connect(self._schedule_apply)
        for cb in self.findChildren(QComboBox):
            cb.currentIndexChanged.connect(self._schedule_apply)
        for le in self.findChildren(QLineEdit):
            le.editingFinished.connect(self._schedule_apply)
        for ks in self.findChildren(QKeySequenceEdit):
            ks.keySequenceChanged.connect(lambda _seq, self=self: self._schedule_apply())
        for chk in self.findChildren(QCheckBox):
            chk.stateChanged.connect(self._schedule_apply)
        for sl in self.findChildren(QSlider):
            sl.valueChanged.connect(self._schedule_apply)

    def _install_wheel_focus(self):
        self._wheel_filter = WheelFocusFilter(self)
        for sp in self.findChildren(QSpinBox):
            sp.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            sp.installEventFilter(self._wheel_filter)
        for sp in self.findChildren(QDoubleSpinBox):
            sp.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            sp.installEventFilter(self._wheel_filter)
        for cb in self.findChildren(QComboBox):
            cb.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            cb.installEventFilter(self._wheel_filter)
        for sl in self.findChildren(QSlider):
            sl.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            sl.installEventFilter(self._wheel_filter)
        for fb in self.findChildren(QFontComboBox):
            fb.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            fb.installEventFilter(self._wheel_filter)

    def _apply_wheel_filter(self, widget: QWidget):
        if not hasattr(self, "_wheel_filter"):
            self._wheel_filter = WheelFocusFilter(self)
        if isinstance(widget, (QSpinBox, QDoubleSpinBox, QComboBox)):
            widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            widget.installEventFilter(self._wheel_filter)

    def _schedule_apply(self):
        if self._suspend_apply:
            return
        self._apply_timer.start(150)

    def _apply_silent(self):
        self.apply_only(silent=True)

    def _copy_browser_overlay_url(self):
        url = "http://127.0.0.1:17872/overlay"
        try:
            if hasattr(self, "le_browser_overlay_url"):
                url = str(self.le_browser_overlay_url.text() or url)
            QApplication.clipboard().setText(url)
            QMessageBox.information(self, "OBS 브라우저 소스", f"주소를 복사했습니다.\n{url}")
        except Exception as e:
            QMessageBox.warning(self, "OBS 브라우저 소스", f"주소 복사 실패: {e}")

    def _open_browser_overlay_url(self):
        url = "http://127.0.0.1:17872/overlay"
        try:
            if hasattr(self, "le_browser_overlay_url"):
                url = str(self.le_browser_overlay_url.text() or url)
            QDesktopServices.openUrl(QUrl(url))
        except Exception as e:
            QMessageBox.warning(self, "OBS 브라우저 소스", f"브라우저 열기 실패: {e}")

    def _apply_browser_overlay_settings(self):
        if hasattr(self, "sp_browser_overlay_poll"):
            self.cfg.browser_overlay_poll_ms = int(self.sp_browser_overlay_poll.value())
        if hasattr(self, "sp_browser_overlay_scale"):
            self.cfg.browser_overlay_scale = max(0.25, min(4.0, float(self.sp_browser_overlay_scale.value()) / 100.0))
        if hasattr(self, "chk_browser_overlay_output_only"):
            self.cfg.browser_overlay_output_only = bool(self.chk_browser_overlay_output_only.isChecked())
        if hasattr(self, "sp_browser_fullscreen_fx_intensity"):
            self.cfg.browser_fullscreen_fx_intensity = max(0.0, min(3.0, float(self.sp_browser_fullscreen_fx_intensity.value()) / 100.0))
        if hasattr(self, "chk_qml_preview_enabled"):
            self.cfg.qml_preview_enabled = bool(self.chk_qml_preview_enabled.isChecked())
        if hasattr(self, "chk_qml_effects_enabled"):
            self.cfg.qml_effects_enabled = bool(self.chk_qml_effects_enabled.isChecked())
        try:
            if self.controller and hasattr(self.controller, "_browser_overlay_timer"):
                interval = max(16, min(1000, int(getattr(self.cfg, "browser_overlay_poll_ms", 50) or 50)))
                self.controller._browser_overlay_timer.setInterval(interval)
            if self.controller and hasattr(self.controller, "timer_win"):
                self.controller.timer_win.set_qml_preview_enabled(bool(getattr(self.cfg, "qml_preview_enabled", True)))
                self.controller.timer_win.set_qml_effects_enabled(bool(getattr(self.cfg, "qml_effects_enabled", False)))
                self.controller.timer_win.set_overlay_visibility(
                    cinematic_visible=(bool(getattr(self.cfg, "overlay_show_cinematic", True)) and not bool(getattr(self.cfg, "browser_overlay_output_only", True)))
                )
        except Exception:
            pass
        self._schedule_apply()

    # ---- Quick tab ----
    # ---- Quick tab ----
    def _build_diagnostics(self):
        lay = QVBoxLayout()
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        group = QGroupBox("진단 / 버그 리포트")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self.chk_diagnostics_enabled = QCheckBox("앱 흐름 기록 켜기")
        self.chk_diagnostics_enabled.setChecked(bool(getattr(self.cfg, "diagnostics_enabled", True)))
        self.chk_diagnostics_enabled.setToolTip("켜두면 최근 앱 흐름, 로그 파싱, 오버레이 전송 기록을 메모리에 보관합니다. 문제 생겼을 때 진단 ZIP에 들어갑니다.")
        grid.addWidget(self.chk_diagnostics_enabled, 0, 0, 1, 2)

        self.chk_diagnostics_mask = QCheckBox("개인정보/경로 가리고 내보내기")
        self.chk_diagnostics_mask.setChecked(bool(getattr(self.cfg, "diagnostics_mask_sensitive", True)))
        self.chk_diagnostics_mask.setToolTip("진단 ZIP 생성 시 사용자 폴더 경로와 민감해 보이는 값을 최대한 가립니다.")
        grid.addWidget(self.chk_diagnostics_mask, 0, 2, 1, 2)

        self.sp_diagnostics_minutes = QSpinBox()
        self.sp_diagnostics_minutes.setRange(1, 120)
        self.sp_diagnostics_minutes.setValue(int(getattr(self.cfg, "diagnostics_trace_minutes", 10) or 10))
        self.sp_diagnostics_minutes.setToolTip("최근 몇 분 정도의 앱 흐름을 보관할지 정합니다. 실제 저장은 이벤트 개수 기준 ring buffer입니다.")
        grid.addWidget(QLabel("최근 기록 보관"), 1, 0)
        grid.addWidget(self.sp_diagnostics_minutes, 1, 1)
        grid.addWidget(QLabel("분"), 1, 2)

        self.sp_diagnostics_raw_lines = QSpinBox()
        self.sp_diagnostics_raw_lines.setRange(20, 2000)
        self.sp_diagnostics_raw_lines.setValue(int(getattr(self.cfg, "diagnostics_raw_sample_lines", 120) or 120))
        self.sp_diagnostics_raw_lines.setToolTip("진단 ZIP에 넣을 SpectatorLog 원본 파일별 최근 줄 수입니다.")
        grid.addWidget(QLabel("원본 로그 샘플"), 2, 0)
        grid.addWidget(self.sp_diagnostics_raw_lines, 2, 1)
        grid.addWidget(QLabel("줄"), 2, 2)

        self.btn_diag_mark = QPushButton("문제 발생 표시")
        self.btn_diag_mark.setToolTip("방송/테스트 중 이상한 순간에 누르면 그 시점이 recent_trace에 표시됩니다.")
        self.btn_diag_mark.clicked.connect(self._diagnostics_mark_incident_clicked)
        grid.addWidget(self.btn_diag_mark, 3, 0)

        self.btn_diag_export = QPushButton("진단 ZIP 생성")
        self.btn_diag_export.setToolTip("최근 앱 흐름, 설정, 오버레이 상태, SpectatorLog 샘플을 ZIP 하나로 묶습니다.")
        self.btn_diag_export.clicked.connect(self._diagnostics_export_clicked)
        grid.addWidget(self.btn_diag_export, 3, 1)

        self.btn_diag_copy = QPushButton("현재 상태 복사")
        self.btn_diag_copy.setToolTip("채팅에 바로 붙여넣을 수 있는 짧은 상태 요약을 클립보드에 복사합니다.")
        self.btn_diag_copy.clicked.connect(self._diagnostics_copy_clicked)
        grid.addWidget(self.btn_diag_copy, 3, 2)

        self.btn_diag_open = QPushButton("진단 폴더 열기")
        self.btn_diag_open.setToolTip("생성된 진단 ZIP이 저장되는 폴더를 엽니다.")
        self.btn_diag_open.clicked.connect(self._diagnostics_open_clicked)
        grid.addWidget(self.btn_diag_open, 3, 3)

        self.btn_project_snapshot = QPushButton("프로젝트 전체 스냅샷 생성")
        self.btn_project_snapshot.setToolTip("새 채팅이나 다른 AI가 프로그램 전체 구조를 파악할 수 있게 AI 인수인계 ZIP을 만듭니다.")
        self.btn_project_snapshot.clicked.connect(self._diagnostics_project_snapshot_clicked)
        grid.addWidget(self.btn_project_snapshot, 4, 0, 1, 2)

        self.lbl_diag_status = QLabel("진단 ZIP은 버그 상황용, 프로젝트 스냅샷은 새 채팅 인수인계/전체 파악용입니다.")
        self.lbl_diag_status.setWordWrap(True)
        grid.addWidget(self.lbl_diag_status, 5, 0, 1, 4)

        guide = QTextEdit()
        guide.setReadOnly(True)
        guide.setMinimumHeight(160)
        guide.setPlainText(
            "사용 흐름:\n"
            "1) 이상한 장면이 나오면 [문제 발생 표시]를 누름\n"
            "2) 테스트/방송 끝나고 [진단 ZIP 생성]을 누름\n"
            "3) 생성된 ZIP을 채팅에 업로드\n\n"
            "진단 ZIP 안에는 recent_trace.jsonl, app_state.json, settings_snapshot.json, "
            "raw_log_samples, spectator_format_detected.json 등이 들어갑니다.\n"
            "초상화/피격 이펙트, 로그 파싱, 타이머 꼬임, 해설 지연 같은 문제를 추적하기 위한 기능입니다.\n\n"
            "[프로젝트 전체 스냅샷 생성]은 새 채팅에서 전체 구조를 파악하게 하는 AI 인수인계 ZIP입니다. "
            "CHAT_HANDOFF.md, PROJECT_OVERVIEW.md, ARCHITECTURE.md, CODE_INDEX.json 등이 들어갑니다."
        )
        lay.addWidget(group)
        lay.addWidget(guide)
        lay.addStretch(1)
        self.tab_diagnostics.setLayout(lay)

    def _diagnostics_apply_options(self):
        try:
            self.cfg.diagnostics_enabled = bool(self.chk_diagnostics_enabled.isChecked())
            self.cfg.diagnostics_mask_sensitive = bool(self.chk_diagnostics_mask.isChecked())
            self.cfg.diagnostics_trace_minutes = int(self.sp_diagnostics_minutes.value())
            self.cfg.diagnostics_raw_sample_lines = int(self.sp_diagnostics_raw_lines.value())
            try:
                DIAG.set_options(
                    enabled=self.cfg.diagnostics_enabled,
                    max_events=max(500, int(self.cfg.diagnostics_trace_minutes) * 500),
                    raw_sample_lines=self.cfg.diagnostics_raw_sample_lines,
                    mask_sensitive=self.cfg.diagnostics_mask_sensitive,
                )
            except Exception:
                pass
        except Exception:
            pass

    def _diagnostics_mark_incident_clicked(self):
        self._diagnostics_apply_options()
        note = "사용자 문제 발생 표시"
        try:
            if self._diagnostic_mark_incident:
                self._diagnostic_mark_incident(note)
            else:
                DIAG.mark_incident(note)
            self.lbl_diag_status.setText("문제 발생 시점 표시 완료. 이제 진단 ZIP을 만들면 이 시점이 같이 들어갑니다.")
        except Exception as e:
            self.lbl_diag_status.setText(f"문제 발생 표시 실패: {e}")

    def _diagnostics_export_clicked(self):
        self._diagnostics_apply_options()
        try:
            path = self._diagnostic_export_zip() if self._diagnostic_export_zip else ""
            if path:
                self.lbl_diag_status.setText(f"진단 ZIP 생성 완료: {path}")
                QMessageBox.information(self, "진단 ZIP 생성", f"진단 ZIP을 만들었습니다.\n\n{path}")
            else:
                self.lbl_diag_status.setText("진단 ZIP 생성 실패: 경로 없음")
        except Exception as e:
            self.lbl_diag_status.setText(f"진단 ZIP 생성 실패: {e}")
            QMessageBox.warning(self, "진단 ZIP 생성 실패", str(e))

    def _diagnostics_copy_clicked(self):
        self._diagnostics_apply_options()
        try:
            text = self._diagnostic_copy_state() if self._diagnostic_copy_state else DIAG.current_state_text({})
            QApplication.clipboard().setText(str(text or ""))
            self.lbl_diag_status.setText("현재 상태 요약을 클립보드에 복사했습니다.")
        except Exception as e:
            self.lbl_diag_status.setText(f"상태 복사 실패: {e}")

    def _diagnostics_project_snapshot_clicked(self):
        self._diagnostics_apply_options()
        try:
            path = self._diagnostic_project_snapshot() if self._diagnostic_project_snapshot else ""
            if path:
                self.lbl_diag_status.setText(f"프로젝트 스냅샷 생성 완료: {path}")
                QMessageBox.information(self, "프로젝트 전체 스냅샷 생성", f"AI 인수인계용 프로젝트 스냅샷을 만들었습니다.\n\n{path}")
            else:
                self.lbl_diag_status.setText("프로젝트 스냅샷 생성 실패: 경로 없음")
        except Exception as e:
            self.lbl_diag_status.setText(f"프로젝트 스냅샷 생성 실패: {e}")
            QMessageBox.warning(self, "프로젝트 스냅샷 생성 실패", str(e))

    def _diagnostics_open_clicked(self):
        self._diagnostics_apply_options()
        try:
            folder = self._diagnostic_open_folder() if self._diagnostic_open_folder else ""
            if folder:
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
                self.lbl_diag_status.setText(f"진단 폴더 열기: {folder}")
        except Exception as e:
            self.lbl_diag_status.setText(f"진단 폴더 열기 실패: {e}")

    def _build_quick(self):
        log_lay = QVBoxLayout()
        record_lay = QVBoxLayout()
        auto_start_outer = QVBoxLayout()
        hit_effects_outer = QVBoxLayout()
        sound_lay_outer = QVBoxLayout()
        test_lay_outer = QVBoxLayout()

        self.cmb_monitor = QComboBox()
        self._refresh_monitors()
        self.cmb_monitor.setVisible(False)

        chapter_group = QGroupBox("방송 챕터 로그")
        chapter_lay = QGridLayout(chapter_group)
        self.lbl_chapter_status = QLabel("-")
        chapter_lay.addWidget(QLabel("기준 시각"), 0, 0)
        chapter_lay.addWidget(self.lbl_chapter_status, 0, 1, 1, 4)
        chapter_lay.addWidget(QLabel("보정(초)"), 1, 0)
        self.sp_chapter_offset = QSpinBox()
        self.sp_chapter_offset.setRange(-36000, 36000)
        self.sp_chapter_offset.setValue(int(getattr(self.cfg, "chapter_offset_sec", 0)))
        chapter_lay.addWidget(self.sp_chapter_offset, 1, 1)
        chapter_lay.addWidget(QLabel("중복 무시(초)"), 1, 2)
        self.sp_chapter_dedupe = QSpinBox()
        self.sp_chapter_dedupe.setRange(0, 600)
        self.sp_chapter_dedupe.setValue(int(getattr(self.cfg, "chapter_dedupe_sec", 20)))
        chapter_lay.addWidget(self.sp_chapter_dedupe, 1, 3)
        chapter_lay.addWidget(QLabel("저장 폴더"), 2, 0)
        self.le_chapter_dir = QLineEdit(str(getattr(self.cfg, "chapter_output_dir", "") or ""))
        chapter_lay.addWidget(self.le_chapter_dir, 2, 1, 1, 2)
        btn_chapter_dir = QPushButton("폴더 선택")
        btn_chapter_dir.clicked.connect(self._pick_chapter_output_dir)
        chapter_lay.addWidget(btn_chapter_dir, 2, 3)
        self.chk_chapter_nickname_only = QCheckBox("닉네임만 기록 (ID 제외)")
        self.chk_chapter_nickname_only.setChecked(bool(getattr(self.cfg, "chapter_nickname_only", False)))
        chapter_lay.addWidget(self.chk_chapter_nickname_only, 3, 0, 1, 4)
        self.chk_chapter_hide_time = QCheckBox("시간 숨기기 (제목만 기록)")
        self.chk_chapter_hide_time.setChecked(bool(getattr(self.cfg, "chapter_hide_time", False)))
        chapter_lay.addWidget(self.chk_chapter_hide_time, 4, 0, 1, 4)
        btn_sync_now = QPushButton("방송 시작 동기화(지금)")
        btn_sync_clear = QPushButton("기준 해제")
        btn_export = QPushButton("챕터 TXT 저장")
        btn_open_chapter = QPushButton("열기")
        chapter_lay.addWidget(btn_sync_now, 5, 0, 1, 2)
        chapter_lay.addWidget(btn_sync_clear, 5, 2)
        chapter_lay.addWidget(btn_export, 5, 3)
        chapter_lay.addWidget(btn_open_chapter, 5, 4)
        btn_sync_now.clicked.connect(lambda: self._chapter_sync_now and self._chapter_sync_now())
        btn_sync_clear.clicked.connect(lambda: self._chapter_clear and self._chapter_clear())
        btn_export.clicked.connect(self._export_chapter_txt_from_settings)
        btn_open_chapter.clicked.connect(self._open_chapter_txt_from_settings)
        self._refresh_chapter_status_label()
        record_lay.addWidget(chapter_group)

        blackbox_group = QGroupBox("관전툴 로그 전체 기록 / 블랙박스")
        blackbox_lay = QGridLayout(blackbox_group)
        self.chk_spectatorlog_blackbox_enabled = QCheckBox("SpectatorLog 폴더 전체 기록 켜기")
        self.chk_spectatorlog_blackbox_enabled.setChecked(bool(getattr(self.cfg, "spectatorlog_blackbox_enabled", False)))
        self.chk_spectatorlog_blackbox_enabled.setToolTip("켜면 SpectatorLog 폴더 안의 모든 파일 생성/수정/삭제를 원본 그대로 기록합니다. 평소에는 OFF 권장.")
        self.chk_spectatorlog_blackbox_enabled.setStyleSheet("font-weight:700; color:#facc15;")
        blackbox_lay.addWidget(self.chk_spectatorlog_blackbox_enabled, 0, 0, 1, 2)
        self.cmb_spectatorlog_blackbox_mode = QComboBox()
        self.cmb_spectatorlog_blackbox_mode.addItem("light", "light")
        self.cmb_spectatorlog_blackbox_mode.addItem("smart", "smart")
        self.cmb_spectatorlog_blackbox_mode.addItem("full", "full")
        _bb_mode = str(getattr(self.cfg, "spectatorlog_blackbox_mode", "smart") or "smart").strip().lower()
        _bb_idx = self.cmb_spectatorlog_blackbox_mode.findData(_bb_mode)
        self.cmb_spectatorlog_blackbox_mode.setCurrentIndex(_bb_idx if _bb_idx >= 0 else 1)
        self.cmb_spectatorlog_blackbox_mode.setToolTip("smart 권장. 카메라/글러브/머리 같은 고빈도 파일은 샘플링 저장합니다.")
        blackbox_lay.addWidget(QLabel("기록 모드"), 0, 2)
        blackbox_lay.addWidget(self.cmb_spectatorlog_blackbox_mode, 0, 3)
        self.btn_spectatorlog_blackbox_open = QPushButton("기록 폴더 열기")
        self.btn_spectatorlog_blackbox_open.setToolTip("SpectatorLogArchive 폴더를 엽니다. 기록이 꺼져 있어도 폴더 확인은 가능합니다.")
        blackbox_lay.addWidget(self.btn_spectatorlog_blackbox_open, 0, 4)
        blackbox_lay.addWidget(QLabel("기록 폴더"), 1, 0)
        self.le_spectatorlog_blackbox_dir = QLineEdit(str(getattr(self.cfg, "spectatorlog_blackbox_dir", "SpectatorLogArchive") or "SpectatorLogArchive"))
        self.le_spectatorlog_blackbox_dir.setPlaceholderText("SpectatorLogArchive")
        self.le_spectatorlog_blackbox_dir.setMaximumWidth(720)
        self.le_spectatorlog_blackbox_dir.setToolTip("블랙박스 세션 폴더가 저장될 위치입니다. 상대 경로면 프로그램 폴더 기준입니다.")
        blackbox_lay.addWidget(self.le_spectatorlog_blackbox_dir, 1, 1, 1, 4)
        self.lbl_spectatorlog_blackbox_hint = QLabel("기본 OFF. 관전툴 로그 포맷 분석할 때만 켜세요. 원본 로그 파일에는 시간/메타데이터를 붙이지 않고 그대로 저장합니다.")
        self.lbl_spectatorlog_blackbox_hint.setWordWrap(True)
        self.lbl_spectatorlog_blackbox_hint.setStyleSheet("color:#9ca3af;")
        blackbox_lay.addWidget(self.lbl_spectatorlog_blackbox_hint, 2, 0, 1, 5)
        blackbox_lay.setColumnStretch(1, 1)
        record_lay.addWidget(blackbox_group)

        spectator_group = QGroupBox("ThrillOfTheFight2 SpectatorLog 연동 / 리플레이 / 피격 이펙트")
        spectator_lay = QGridLayout(spectator_group)
        self.chk_spectatorlog_enabled = QCheckBox("SpectatorLog 사용")
        self.chk_spectatorlog_enabled.setChecked(bool(getattr(self.cfg, "spectatorlog_enabled", False)))
        spectator_lay.addWidget(self.chk_spectatorlog_enabled, 0, 0, 1, 4)
        self.chk_spectatorlog_sync_players = QCheckBox("Sync log players")
        self.chk_spectatorlog_sync_players.setChecked(bool(getattr(self.cfg, "spectatorlog_sync_players", True)))
        spectator_lay.addWidget(self.chk_spectatorlog_sync_players, 1, 0, 1, 4)
        self.chk_spectatorlog_sync_timer = QCheckBox("Sync log timer")
        self.chk_spectatorlog_sync_timer.setChecked(bool(getattr(self.cfg, "spectatorlog_sync_timer", False)))
        spectator_lay.addWidget(self.chk_spectatorlog_sync_timer, 2, 0, 1, 4)
        self.le_spectatorlog_path = QLineEdit(str(getattr(self.cfg, "spectatorlog_path", "") or ""))
        self.le_spectatorlog_path.setPlaceholderText(r"예: ThrillOfTheFight2\SpectatorLog")
        self.le_spectatorlog_path.setMaximumWidth(520)
        spectator_lay.addWidget(QLabel("폴더"), 6, 0)
        spectator_lay.addWidget(self.le_spectatorlog_path, 6, 1, 1, 2)
        self.btn_spectatorlog_browse = QPushButton("폴더 선택")
        self.btn_spectatorlog_browse.clicked.connect(self._browse_spectatorlog_path)
        spectator_lay.addWidget(self.btn_spectatorlog_browse, 6, 3)
        spectator_lay.addWidget(QLabel("읽기 간격(ms)"), 7, 0)
        self.sp_spectatorlog_poll = QSpinBox()
        self.sp_spectatorlog_poll.setRange(100, 5000)
        self.sp_spectatorlog_poll.setSingleStep(50)
        self.sp_spectatorlog_poll.setValue(int(getattr(self.cfg, "spectatorlog_poll_ms", 250) or 250))
        self.sp_spectatorlog_poll.setToolTip("파일 변경 감지를 끈 경우에만 사용하는 직접 확인 간격입니다.")
        spectator_lay.addWidget(self.sp_spectatorlog_poll, 7, 1)
        self.chk_spectatorlog_file_watch = QCheckBox("파일 변경 감지 사용")
        self.chk_spectatorlog_file_watch.setChecked(bool(getattr(self.cfg, "spectatorlog_file_watch_enabled", True)))
        self.chk_spectatorlog_file_watch.setToolTip("켜면 로그 파일이 바뀌는 즉시 읽고, 읽기 간격은 백업 확인용으로만 동작합니다.")
        spectator_lay.addWidget(self.chk_spectatorlog_file_watch, 7, 2, 1, 2)
        spectator_lay.addWidget(QLabel("변경 안정화(ms)"), 8, 0)
        self.sp_spectatorlog_debounce = QSpinBox()
        self.sp_spectatorlog_debounce.setRange(0, 500)
        self.sp_spectatorlog_debounce.setSingleStep(5)
        self.sp_spectatorlog_debounce.setValue(int(getattr(self.cfg, "spectatorlog_debounce_ms", 35) or 35))
        self.sp_spectatorlog_debounce.setToolTip("로그 파일 쓰기가 끝날 시간을 아주 짧게 기다립니다. 너무 크면 반응이 느려집니다.")
        spectator_lay.addWidget(self.sp_spectatorlog_debounce, 8, 1)
        spectator_lay.addWidget(QLabel("백업 확인(ms)"), 8, 2)
        self.sp_spectatorlog_backup_poll = QSpinBox()
        self.sp_spectatorlog_backup_poll.setRange(250, 10000)
        self.sp_spectatorlog_backup_poll.setSingleStep(250)
        self.sp_spectatorlog_backup_poll.setValue(int(getattr(self.cfg, "spectatorlog_backup_poll_ms", 1500) or 1500))
        self.sp_spectatorlog_backup_poll.setToolTip("파일 변경 이벤트를 놓쳤을 때를 대비한 느린 백업 확인 간격입니다.")
        spectator_lay.addWidget(self.sp_spectatorlog_backup_poll, 8, 3)

        self.btn_spectatorlog_test_blue_stun= QPushButton("블루 스턴 테스트")
        self.btn_spectatorlog_test_red_stun= QPushButton("레드 스턴 테스트")
        self.btn_spectatorlog_test_blue_kd= QPushButton("블루 KD 테스트")
        self.btn_spectatorlog_test_red_kd= QPushButton("레드 KD 테스트")
        self.btn_spectatorlog_test_blue_tko= QPushButton("블루 TKO 테스트")
        self.btn_spectatorlog_test_red_tko= QPushButton("레드 TKO 테스트")
        self.btn_spectatorlog_test_damage= QPushButton("데미지 표시 테스트")
        self.btn_spectatorlog_test_hit_fx_sprite = QPushButton("폭발 피격 테스트")
        self.btn_spectatorlog_test_hp= QPushButton("게이지 테스트")
        self.btn_spectatorlog_test_blue_combo= QPushButton("블루 콤보 테스트")
        self.btn_spectatorlog_test_red_combo= QPushButton("레드 콤보 테스트")
        self.btn_spectatorlog_test_counter= QPushButton("카운터 테스트")
        self.btn_spectatorlog_test_lives= QPushButton("남은 생명 테스트")
        self.btn_spectatorlog_test_timer_state= QPushButton("타이머 상태 테스트")
        self.btn_spectatorlog_test_vs_intro= QPushButton("VS 오버레이 테스트")
        self.btn_spectatorlog_test_full_demo = QPushButton("전체 HUD 데모")
        self.btn_spectatorlog_test_round_report = QPushButton("라운드 리포트 테스트")
        self.btn_spectatorlog_test_final_report = QPushButton("경기 종료 리포트 테스트")
        self.btn_spectatorlog_replay_last = QPushButton("과거 로그 리플레이")
        self.btn_spectatorlog_replay_stop = QPushButton("리플레이 중지")
        self.btn_spectatorlog_clear_damage = QPushButton("데미지 초기화")
        self.btn_spectator_commentary_tts_test = QPushButton("자동해설 TTS 테스트")
        self.btn_spectator_commentary_full_test = QPushButton("자동해설 종합 테스트")
        self.btn_spectator_commentary_duo_test = QPushButton("듀오 해설 테스트")
        self.btn_spectator_commentary_down_test = QPushButton("다운 멘트 테스트")
        self.btn_spectator_commentary_summary_test = QPushButton("요약 멘트 테스트")
        self.btn_spectator_commentary_stop_test = QPushButton("해설 테스트 중지")
        self.btn_spectator_commentary_full_test_tab = QPushButton("자동해설 종합 테스트")
        self.btn_spectator_commentary_duo_test_tab = QPushButton("듀오 해설 테스트")
        self.btn_spectator_commentary_down_test_tab = QPushButton("다운 멘트 테스트")
        self.btn_spectator_commentary_summary_test_tab = QPushButton("요약 멘트 테스트")
        self.btn_spectator_commentary_stop_test_tab = QPushButton("해설 테스트 중지")
        test_tabs = QTabWidget()
        test_tabs.setDocumentMode(True)

        def _test_page(title: str, rows: List[List[QWidget]]) -> None:
            page = QWidget()
            page_lay = QGridLayout(page)
            page_lay.setContentsMargins(18, 18, 18, 18)
            page_lay.setHorizontalSpacing(12)
            page_lay.setVerticalSpacing(12)
            for row_index, widgets in enumerate(rows):
                for column_index, widget in enumerate(widgets):
                    page_lay.addWidget(widget, row_index, column_index)
                page_lay.setRowStretch(row_index + 1, 0)
            page_lay.setRowStretch(len(rows), 1)
            test_tabs.addTab(page, title)

        _test_page(
            "전투 효과",
            [
                [self.btn_spectatorlog_test_blue_stun, self.btn_spectatorlog_test_red_stun],
                [self.btn_spectatorlog_test_blue_kd, self.btn_spectatorlog_test_red_kd],
                [self.btn_spectatorlog_test_blue_tko, self.btn_spectatorlog_test_red_tko],
                [self.btn_spectatorlog_test_blue_combo, self.btn_spectatorlog_test_red_combo],
                [self.btn_spectatorlog_test_counter],
            ],
        )
        _test_page(
            "HUD",
            [
                [self.btn_spectatorlog_test_damage, self.btn_spectatorlog_test_hp],
                [self.btn_spectatorlog_test_lives, self.btn_spectatorlog_test_timer_state],
                [self.btn_spectatorlog_clear_damage, self.btn_spectatorlog_test_full_demo],
            ],
        )
        _test_page(
            "오버레이 / 리포트",
            [
                [self.btn_spectatorlog_test_vs_intro],
                [self.btn_spectatorlog_test_round_report, self.btn_spectatorlog_test_final_report],
            ],
        )
        _test_page(
            "리플레이",
            [[self.btn_spectatorlog_replay_last, self.btn_spectatorlog_replay_stop]],
        )
        _test_page(
            "해설",
            [
                [self.btn_spectator_commentary_full_test_tab, self.btn_spectator_commentary_duo_test_tab],
                [self.btn_spectator_commentary_down_test_tab, self.btn_spectator_commentary_summary_test_tab],
                [self.btn_spectator_commentary_stop_test_tab],
            ],
        )
        test_lay_outer.addWidget(test_tabs)
        sound_group = QGroupBox("자동해설 TTS / Spectator 효과음")
        sound_lay = QGridLayout(sound_group)
        self.chk_spectator_commentary = QCheckBox("자동해설 사용")
        self.chk_spectator_commentary.setChecked(bool(getattr(self.cfg, "spectator_commentary_enabled", False)))
        sound_lay.addWidget(self.chk_spectator_commentary, 7, 0)
        self.cmb_spectator_commentary_mode = QComboBox()
        self.cmb_spectator_commentary_mode.addItem("조용함", "quiet")
        self.cmb_spectator_commentary_mode.addItem("표준", "standard")
        self.cmb_spectator_commentary_mode.addItem("활발함", "active")
        idx = self.cmb_spectator_commentary_mode.findData(str(getattr(self.cfg, "spectator_commentary_mode", "standard") or "standard"))
        self.cmb_spectator_commentary_mode.setCurrentIndex(idx if idx >= 0 else 1)
        sound_lay.addWidget(QLabel("해설 모드"), 7, 1)
        sound_lay.addWidget(self.cmb_spectator_commentary_mode, 7, 2)
        self.cmb_spectator_commentary_voice = QComboBox()
        self._fill_edge_voice_combo(self.cmb_spectator_commentary_voice)
        vidx = self.cmb_spectator_commentary_voice.findData(str(getattr(self.cfg, "spectator_commentary_voice", "ko-KR-SunHiNeural") or "ko-KR-SunHiNeural"))
        self.cmb_spectator_commentary_voice.setCurrentIndex(vidx if vidx >= 0 else 0)
        sound_lay.addWidget(QLabel("해설 음성"), 7, 3)
        sound_lay.addWidget(self.cmb_spectator_commentary_voice, 7, 4)
        self.cmb_spectator_caster_voice = QComboBox()
        self._fill_edge_voice_combo(self.cmb_spectator_caster_voice)
        cidx = self.cmb_spectator_caster_voice.findData(str(getattr(self.cfg, "spectator_caster_voice", "ko-KR-InJoonNeural") or "ko-KR-InJoonNeural"))
        self.cmb_spectator_caster_voice.setCurrentIndex(cidx if cidx >= 0 else 1)
        sound_lay.addWidget(QLabel("캐스터 음성"), 8, 0)
        sound_lay.addWidget(self.cmb_spectator_caster_voice, 8, 1)
        self.sp_spectator_commentary_damage = QDoubleSpinBox()
        self.sp_spectator_commentary_damage.setRange(0.0, 200.0)
        self.sp_spectator_commentary_damage.setSingleStep(1.0)
        self.sp_spectator_commentary_damage.setValue(float(getattr(self.cfg, "spectator_commentary_min_damage", 25.0) or 25.0))
        sound_lay.addWidget(QLabel("최소 데미지"), 8, 2)
        sound_lay.addWidget(self.sp_spectator_commentary_damage, 8, 3)
        self.sp_spectator_commentary_cooldown = QDoubleSpinBox()
        self.sp_spectator_commentary_cooldown.setRange(0.0, 60.0)
        self.sp_spectator_commentary_cooldown.setSingleStep(0.5)
        self.sp_spectator_commentary_cooldown.setValue(
            max(0.0, float(getattr(self.cfg, "spectator_commentary_cooldown_sec", 6.0)))
        )
        self.sp_spectator_commentary_cooldown.setToolTip(
            "일반 자동해설이 다시 생성될 때까지 기다리는 최소 시간입니다. 0초면 제한하지 않습니다."
        )
        sound_lay.addWidget(QLabel("해설 쿨타임(초)"), 8, 4)
        sound_lay.addWidget(self.sp_spectator_commentary_cooldown, 8, 5)
        self.sp_spectator_commentary_rate = QSpinBox()
        self.sp_spectator_commentary_rate.setRange(80, 320)
        self.sp_spectator_commentary_rate.setSingleStep(10)
        self.sp_spectator_commentary_rate.setSuffix(" wpm")
        self.sp_spectator_commentary_rate.setValue(int(getattr(self.cfg, "spectator_commentary_rate", 200) or 200))
        sound_lay.addWidget(QLabel("읽는 속도"), 9, 0)
        sound_lay.addWidget(self.sp_spectator_commentary_rate, 9, 1)
        self.sp_spectator_commentary_volume = QDoubleSpinBox()
        self.sp_spectator_commentary_volume.setRange(0.0, 100.0)
        self.sp_spectator_commentary_volume.setSingleStep(5.0)
        self.sp_spectator_commentary_volume.setSuffix("%")
        self.sp_spectator_commentary_volume.setValue(float(getattr(self.cfg, "spectator_commentary_volume", 100.0) or 100.0))
        sound_lay.addWidget(QLabel("해설 볼륨"), 9, 2)
        sound_lay.addWidget(self.sp_spectator_commentary_volume, 9, 3)
        self.sp_spectator_commentary_pitch = QSpinBox()
        self.sp_spectator_commentary_pitch.setRange(-100, 100)
        self.sp_spectator_commentary_pitch.setSingleStep(10)
        self.sp_spectator_commentary_pitch.setSuffix(" Hz")
        self.sp_spectator_commentary_pitch.setValue(int(getattr(self.cfg, "spectator_commentary_pitch", 0) or 0))
        sound_lay.addWidget(QLabel("피치"), 9, 4)
        sound_lay.addWidget(self.sp_spectator_commentary_pitch, 9, 5)
        self.sp_spectator_replay_speed = QDoubleSpinBox()
        self.sp_spectator_replay_speed.setRange(0.1, 20.0)
        self.sp_spectator_replay_speed.setSingleStep(0.5)
        self.sp_spectator_replay_speed.setDecimals(1)
        self.sp_spectator_replay_speed.setValue(float(getattr(self.cfg, "spectator_replay_speed", 1.0) or 1.0))
        spectator_lay.addWidget(QLabel("리플레이 배속"), 9, 0)
        spectator_lay.addWidget(self.sp_spectator_replay_speed, 9, 1)
        self.chk_spectator_replay_real_time = QCheckBox("리플레이 실제 시간")
        self.chk_spectator_replay_real_time.setChecked(bool(getattr(self.cfg, "spectator_replay_real_time", False)))
        self.chk_spectator_replay_real_time.setToolTip("켜면 damage_events.txt 시간 간격을 압축하지 않고 그대로 재생합니다.")
        spectator_lay.addWidget(self.chk_spectator_replay_real_time, 9, 2)
        self.sp_spectator_hit_effect_damage = QDoubleSpinBox()
        self.sp_spectator_hit_effect_damage.setRange(0.0, 300.0)
        self.sp_spectator_hit_effect_damage.setSingleStep(1.0)
        self.sp_spectator_hit_effect_damage.setDecimals(1)
        self.sp_spectator_hit_effect_damage.setSuffix(" dmg")
        self.sp_spectator_hit_effect_damage.setValue(float(getattr(self.cfg, "spectator_hit_effect_damage", 45.0) or 45.0))
        self.sp_spectator_hit_effect_damage.setToolTip("이 값 이상 데미지일 때 피격 이펙트가 뜹니다. 0이면 모든 타격에 표시합니다. 스턴/다운/TKO는 이 값보다 낮아도 표시됩니다.")
        spectator_lay.addWidget(QLabel("피격 이펙트 발동 데미지"), 9, 3)
        spectator_lay.addWidget(self.sp_spectator_hit_effect_damage, 9, 4)
        self.cb_spectator_hit_fx_color_preset = QComboBox()
        self.cb_spectator_hit_fx_color_preset.addItem("기본", "classic")
        self.cb_spectator_hit_fx_color_preset.addItem("아이스/파이어", "icefire")
        self.cb_spectator_hit_fx_color_preset.addItem("네온", "neon")
        self.cb_spectator_hit_fx_color_preset.addItem("커스텀", "custom")
        _fx_preset = str(getattr(self.cfg, "spectator_hit_effect_color_preset", "classic") or "classic").strip().lower()
        _fx_idx = self.cb_spectator_hit_fx_color_preset.findData(_fx_preset)
        self.cb_spectator_hit_fx_color_preset.setCurrentIndex(_fx_idx if _fx_idx >= 0 else 0)
        spectator_lay.addWidget(QLabel("피격 이펙트 컬러"), 10, 2)
        spectator_lay.addWidget(self.cb_spectator_hit_fx_color_preset, 10, 3)
        self.le_spectator_hit_fx_color_low = QLineEdit(str(getattr(self.cfg, "spectator_hit_effect_color_low", "#38bdf8") or "#38bdf8"))
        self.le_spectator_hit_fx_color_mid = QLineEdit(str(getattr(self.cfg, "spectator_hit_effect_color_mid", "#fb923c") or "#fb923c"))
        self.le_spectator_hit_fx_color_high = QLineEdit(str(getattr(self.cfg, "spectator_hit_effect_color_high", "#f87171") or "#f87171"))
        self.le_spectator_hit_fx_color_weak = QLineEdit(str(getattr(self.cfg, "spectator_hit_effect_color_weak", "#facc15") or "#facc15"))
        self.le_spectator_hit_fx_color_stun = QLineEdit(str(getattr(self.cfg, "spectator_hit_effect_color_stun", "#ef4444") or "#ef4444"))
        for _le in (self.le_spectator_hit_fx_color_low, self.le_spectator_hit_fx_color_mid, self.le_spectator_hit_fx_color_high, self.le_spectator_hit_fx_color_weak, self.le_spectator_hit_fx_color_stun):
            _le.setVisible(False)
        self.btn_spectator_hit_fx_color_low = QPushButton()
        self.btn_spectator_hit_fx_color_mid = QPushButton()
        self.btn_spectator_hit_fx_color_high = QPushButton()
        self.btn_spectator_hit_fx_color_weak = QPushButton()
        self.btn_spectator_hit_fx_color_stun = QPushButton()
        self._set_hit_fx_color_button(self.btn_spectator_hit_fx_color_low, self.le_spectator_hit_fx_color_low.text())
        self._set_hit_fx_color_button(self.btn_spectator_hit_fx_color_mid, self.le_spectator_hit_fx_color_mid.text())
        self._set_hit_fx_color_button(self.btn_spectator_hit_fx_color_high, self.le_spectator_hit_fx_color_high.text())
        self._set_hit_fx_color_button(self.btn_spectator_hit_fx_color_weak, self.le_spectator_hit_fx_color_weak.text())
        self._set_hit_fx_color_button(self.btn_spectator_hit_fx_color_stun, self.le_spectator_hit_fx_color_stun.text())
        spectator_lay.addWidget(QLabel("Low"), 11, 0)
        spectator_lay.addWidget(self.btn_spectator_hit_fx_color_low, 11, 1)
        spectator_lay.addWidget(QLabel("Mid"), 11, 2)
        spectator_lay.addWidget(self.btn_spectator_hit_fx_color_mid, 11, 3)
        spectator_lay.addWidget(QLabel("High"), 11, 4)
        spectator_lay.addWidget(self.btn_spectator_hit_fx_color_high, 11, 5)
        spectator_lay.addWidget(QLabel("Weak"), 12, 0)
        spectator_lay.addWidget(self.btn_spectator_hit_fx_color_weak, 12, 1)
        spectator_lay.addWidget(QLabel("Stun/Down"), 12, 2)
        spectator_lay.addWidget(self.btn_spectator_hit_fx_color_stun, 12, 3)
        self.sp_spectator_hit_fx_duration = QSpinBox()
        self.sp_spectator_hit_fx_duration.setRange(80, 1200)
        self.sp_spectator_hit_fx_duration.setSingleStep(10)
        self.sp_spectator_hit_fx_duration.setSuffix(" ms")
        self.sp_spectator_hit_fx_duration.setValue(int(getattr(self.cfg, "spectator_hit_effect_duration_ms", 170) or 170))
        spectator_lay.addWidget(QLabel("이펙트 시간"), 13, 0)
        spectator_lay.addWidget(self.sp_spectator_hit_fx_duration, 13, 1)
        self.sp_spectator_hit_fx_pop = QSpinBox()
        self.sp_spectator_hit_fx_pop.setRange(30, 280)
        self.sp_spectator_hit_fx_pop.setSingleStep(5)
        self.sp_spectator_hit_fx_pop.setSuffix(" ms")
        self.sp_spectator_hit_fx_pop.setValue(int(getattr(self.cfg, "spectator_hit_effect_pop_ms", 58) or 58))
        self.sp_spectator_hit_fx_pop.setToolTip("첫 프레임이 팍 터지는 속도입니다. 짧을수록 더 순간적으로 폭발합니다.")
        spectator_lay.addWidget(QLabel("팍 터지는 시간"), 13, 2)
        spectator_lay.addWidget(self.sp_spectator_hit_fx_pop, 13, 3)
        self.sp_spectator_hit_fx_base_size = QSpinBox()
        self.sp_spectator_hit_fx_base_size.setRange(24, 240)
        self.sp_spectator_hit_fx_base_size.setSingleStep(2)
        self.sp_spectator_hit_fx_base_size.setSuffix(" px")
        self.sp_spectator_hit_fx_base_size.setValue(int(getattr(self.cfg, "spectator_hit_effect_base_size", 86) or 86))
        spectator_lay.addWidget(QLabel("기본 크기"), 13, 4)
        spectator_lay.addWidget(self.sp_spectator_hit_fx_base_size, 13, 5)
        self.sp_spectator_hit_fx_damage_scale = QDoubleSpinBox()
        self.sp_spectator_hit_fx_damage_scale.setRange(0.0, 3.0)
        self.sp_spectator_hit_fx_damage_scale.setSingleStep(0.05)
        self.sp_spectator_hit_fx_damage_scale.setDecimals(2)
        self.sp_spectator_hit_fx_damage_scale.setValue(float(getattr(self.cfg, "spectator_hit_effect_damage_scale", 0.42) or 0.42))
        spectator_lay.addWidget(QLabel("데미지 크기배수"), 17, 0)
        spectator_lay.addWidget(self.sp_spectator_hit_fx_damage_scale, 17, 1)
        self.sp_spectator_hit_fx_ring_width = QSpinBox()
        self.sp_spectator_hit_fx_ring_width.setRange(1, 20)
        self.sp_spectator_hit_fx_ring_width.setSingleStep(1)
        self.sp_spectator_hit_fx_ring_width.setSuffix(" px")
        self.sp_spectator_hit_fx_ring_width.setValue(int(getattr(self.cfg, "spectator_hit_effect_ring_width", 4) or 4))
        spectator_lay.addWidget(QLabel("링 두께"), 14, 0)
        spectator_lay.addWidget(self.sp_spectator_hit_fx_ring_width, 14, 1)
        self.sp_spectator_hit_fx_opacity = QDoubleSpinBox()
        self.sp_spectator_hit_fx_opacity.setRange(0.05, 1.5)
        self.sp_spectator_hit_fx_opacity.setSingleStep(0.05)
        self.sp_spectator_hit_fx_opacity.setDecimals(2)
        self.sp_spectator_hit_fx_opacity.setValue(float(getattr(self.cfg, "spectator_hit_effect_opacity", 1.0) or 1.0))
        spectator_lay.addWidget(QLabel("전체 투명도/강도"), 14, 2)
        spectator_lay.addWidget(self.sp_spectator_hit_fx_opacity, 14, 3)
        self.sp_spectator_hit_fx_glow = QDoubleSpinBox()
        self.sp_spectator_hit_fx_glow.setRange(0.0, 3.0)
        self.sp_spectator_hit_fx_glow.setSingleStep(0.05)
        self.sp_spectator_hit_fx_glow.setDecimals(2)
        self.sp_spectator_hit_fx_glow.setValue(float(getattr(self.cfg, "spectator_hit_effect_glow", 1.0) or 1.0))
        spectator_lay.addWidget(QLabel("글로우 강도"), 14, 4)
        spectator_lay.addWidget(self.sp_spectator_hit_fx_glow, 14, 5)
        self.sp_spectator_hit_fx_fill_opacity = QDoubleSpinBox()
        self.sp_spectator_hit_fx_fill_opacity.setRange(0.0, 1.5)
        self.sp_spectator_hit_fx_fill_opacity.setSingleStep(0.05)
        self.sp_spectator_hit_fx_fill_opacity.setDecimals(2)
        self.sp_spectator_hit_fx_fill_opacity.setValue(float(getattr(self.cfg, "spectator_hit_effect_fill_opacity", 1.0) or 1.0))
        spectator_lay.addWidget(QLabel("중앙 채움 강도"), 15, 0)
        spectator_lay.addWidget(self.sp_spectator_hit_fx_fill_opacity, 15, 1)
        self.chk_spectator_hit_fx_show_text = QCheckBox("데미지 숫자 표시")
        self.chk_spectator_hit_fx_show_text.setChecked(bool(getattr(self.cfg, "spectator_hit_effect_show_text", True)))
        spectator_lay.addWidget(self.chk_spectator_hit_fx_show_text, 15, 2)
        self.sp_spectator_hit_fx_text_scale = QDoubleSpinBox()
        self.sp_spectator_hit_fx_text_scale.setRange(0.5, 2.0)
        self.sp_spectator_hit_fx_text_scale.setSingleStep(0.1)
        self.sp_spectator_hit_fx_text_scale.setDecimals(1)
        self.sp_spectator_hit_fx_text_scale.setValue(float(getattr(self.cfg, "spectator_hit_effect_text_scale", 1.0) or 1.0))
        spectator_lay.addWidget(QLabel("숫자 크기배수"), 15, 4)
        spectator_lay.addWidget(self.sp_spectator_hit_fx_text_scale, 15, 5)
        self.chk_spectator_hit_fx_fast_emit = QCheckBox("피격 Fast Path")
        self.chk_spectator_hit_fx_fast_emit.setChecked(bool(getattr(self.cfg, "spectator_hit_effect_fast_emit", True)))
        self.chk_spectator_hit_fx_fast_emit.setToolTip("damage_events 새 줄이 감지되면 해설/요약/통계 처리 전에 피격 이펙트만 먼저 보냅니다.")
        spectator_lay.addWidget(self.chk_spectator_hit_fx_fast_emit, 16, 0, 1, 2)
        self.chk_spectator_hit_fx_latency_log = QCheckBox("피격 지연 로그")
        self.chk_spectator_hit_fx_latency_log.setChecked(bool(getattr(self.cfg, "spectator_hit_effect_latency_log", True)))
        self.chk_spectator_hit_fx_latency_log.setToolTip("damage_events 감지 → overlay push → 브라우저 실행 시점을 로그/콘솔에 남깁니다.")
        spectator_lay.addWidget(self.chk_spectator_hit_fx_latency_log, 16, 2, 1, 2)
        self.chk_spectator_hit_fx_sprite_enabled = QCheckBox("폭발 스프라이트")
        self.chk_spectator_hit_fx_sprite_enabled.setChecked(bool(getattr(self.cfg, "spectator_hit_effect_sprite_enabled", True)))
        self.chk_spectator_hit_fx_sprite_enabled.setToolTip("철권식 짧은 폭발 sprite atlas를 미리 로드해 피격 위치에 즉시 재생합니다.")
        spectator_lay.addWidget(self.chk_spectator_hit_fx_sprite_enabled, 16, 4)
        self.chk_spectator_hit_fx_ring_enabled = QCheckBox("기존 링 같이 표시")
        self.chk_spectator_hit_fx_ring_enabled.setChecked(bool(getattr(self.cfg, "spectator_hit_effect_ring_enabled", False)))
        self.chk_spectator_hit_fx_ring_enabled.setToolTip("폭발 sprite 위에 기존 원형 링/글로우도 같이 표시합니다. 끄면 sprite만 남습니다.")
        spectator_lay.addWidget(self.chk_spectator_hit_fx_ring_enabled, 16, 5)
        sound_lay.addWidget(self.btn_spectator_commentary_tts_test, 10, 5)
        sound_lay.addWidget(self.btn_spectator_commentary_full_test, 11, 0, 1, 2)
        sound_lay.addWidget(self.btn_spectator_commentary_duo_test, 11, 2)
        sound_lay.addWidget(self.btn_spectator_commentary_down_test, 11, 3)
        sound_lay.addWidget(self.btn_spectator_commentary_summary_test, 11, 4)
        sound_lay.addWidget(self.btn_spectator_commentary_stop_test, 11, 5)
        self.sp_spectator_recent_text_size = QSpinBox()
        self.sp_spectator_recent_text_size.setRange(10, 80)
        self.sp_spectator_recent_text_size.setSuffix(" px")
        self.sp_spectator_recent_text_size.setValue(int(getattr(self.cfg, "spectator_recent_text_size", 23) or 23))
        spectator_lay.addWidget(QLabel("타격 텍스트 크기"), 10, 0)
        spectator_lay.addWidget(self.sp_spectator_recent_text_size, 10, 1)
        self.sp_spectator_sfx_rate = QDoubleSpinBox()
        self.sp_spectator_sfx_rate.setRange(0.5, 2.0)
        self.sp_spectator_sfx_rate.setSingleStep(0.1)
        self.sp_spectator_sfx_rate.setDecimals(2)
        self.sp_spectator_sfx_rate.setSuffix("x")
        self.sp_spectator_sfx_rate.setValue(float(getattr(self.cfg, "spectator_sfx_playback_rate", 1.0) or 1.0))
        sound_lay.addWidget(QLabel("효과음 배속"), 12, 2)
        sound_lay.addWidget(self.sp_spectator_sfx_rate, 12, 3)
        self.le_spectator_stun_sfx = QLineEdit(str(getattr(self.cfg, "spectator_stun_sfx_path", "") or ""))
        self.le_spectator_stun_sfx.setPlaceholderText("스턴 효과음 WAV/MP3")
        self.btn_spectator_stun_sfx_pick = QPushButton("찾기")
        self.btn_spectator_stun_sfx_test = QPushButton("테스트")
        sound_lay.addWidget(QLabel("스턴 효과음"), 13, 0)
        sound_lay.addWidget(self.le_spectator_stun_sfx, 13, 1, 1, 3)
        sound_lay.addWidget(self.btn_spectator_stun_sfx_pick, 13, 4)
        sound_lay.addWidget(self.btn_spectator_stun_sfx_test, 13, 5)
        self.le_spectator_kd_sfx = QLineEdit(str(getattr(self.cfg, "spectator_knockdown_sfx_path", "") or ""))
        self.le_spectator_kd_sfx.setPlaceholderText("넉다운 효과음 WAV/MP3")
        self.btn_spectator_kd_sfx_pick = QPushButton("찾기")
        self.btn_spectator_kd_sfx_test = QPushButton("테스트")
        sound_lay.addWidget(QLabel("다운 효과음"), 14, 0)
        sound_lay.addWidget(self.le_spectator_kd_sfx, 14, 1, 1, 3)
        sound_lay.addWidget(self.btn_spectator_kd_sfx_pick, 14, 4)
        sound_lay.addWidget(self.btn_spectator_kd_sfx_test, 14, 5)
        self.le_spectator_tko_sfx = QLineEdit(str(getattr(self.cfg, "spectator_tko_sfx_path", "") or ""))
        self.le_spectator_tko_sfx.setPlaceholderText("TKO 효과음 WAV/MP3")
        self.btn_spectator_tko_sfx_pick = QPushButton("찾기")
        self.btn_spectator_tko_sfx_test = QPushButton("테스트")
        sound_lay.addWidget(QLabel("종료 효과음"), 15, 0)
        sound_lay.addWidget(self.le_spectator_tko_sfx, 15, 1, 1, 3)
        sound_lay.addWidget(self.btn_spectator_tko_sfx_pick, 15, 4)
        sound_lay.addWidget(self.btn_spectator_tko_sfx_test, 15, 5)
        spectator_group.setToolTip("위쪽은 SpectatorLog 읽기 설정, 아래쪽은 리플레이 / 피격 이펙트 설정입니다.")
        _spectator_tips = {
            self.chk_spectatorlog_enabled: "TOTF2 SpectatorLog 폴더를 읽어서 HUD를 자동으로 움직입니다.",
            self.chk_spectatorlog_sync_players: "로그에 나온 선수 이름으로 좌/우 선수 정보를 자동 갱신합니다.",
            self.chk_spectatorlog_sync_timer: "로그에서 라운드 시간/상태를 읽어 타이머를 자동으로 맞춥니다.",
            self.le_spectatorlog_path: "damage_events.txt 등이 저장되는 SpectatorLog 폴더를 넣습니다.",
            self.btn_spectatorlog_browse: "SpectatorLog 폴더를 찾아서 바로 넣습니다.",
            self.sp_spectatorlog_poll: "파일 변경 감지를 끈 경우 직접 확인하는 간격입니다.",
            self.sp_spectatorlog_debounce: "로그 기록이 완전히 끝난 뒤 읽기까지 잠깐 기다리는 시간입니다.",
            self.sp_spectatorlog_backup_poll: "이벤트를 놓친 경우를 대비한 느린 백업 확인 간격입니다.",
            self.chk_spectatorlog_blackbox_enabled: "관전툴 로그 포맷 분석이 필요할 때만 켭니다. 원본 로그는 그대로 저장하고 메타데이터는 events.jsonl에 따로 저장합니다.",
            self.le_spectatorlog_blackbox_dir: "블랙박스 기록 세션이 쌓일 폴더입니다. 기본값은 SpectatorLogArchive입니다.",
            self.cmb_spectatorlog_blackbox_mode: "light는 가볍게, smart는 권장, full은 디버그용입니다.",
            self.btn_spectatorlog_blackbox_open: "기록 폴더를 파일 탐색기로 엽니다.",
            self.sp_spectator_replay_speed: "과거 로그 리플레이를 몇 배속으로 보여줄지 정합니다.",
            self.chk_spectator_replay_real_time: "켜면 리플레이가 실제 경기 시간 간격을 그대로 따라갑니다.",
            self.sp_spectator_recent_text_size: "좌우에 뜨는 최근 타격 텍스트의 글자 크기입니다.",
            self.sp_spectator_hit_effect_damage: "이 수치 이상 데미지에서만 피격 이펙트를 띄웁니다. 0이면 모든 타격에 표시됩니다.",
            self.cb_spectator_hit_fx_color_preset: "피격 이펙트 전체 색 조합을 빠르게 바꿉니다.",
            self.btn_spectator_hit_fx_color_low: "약한 타격 색입니다.",
            self.btn_spectator_hit_fx_color_mid: "중간 타격 색입니다.",
            self.btn_spectator_hit_fx_color_high: "강한 타격 색입니다.",
            self.btn_spectator_hit_fx_color_weak: "약타/연속타용 보조 색입니다.",
            self.btn_spectator_hit_fx_color_stun: "스턴/다운/TKO 계열 색입니다.",
            self.sp_spectator_hit_fx_duration: "폭발 피격 이펙트가 전체적으로 남아있는 시간입니다.",
            self.sp_spectator_hit_fx_pop: "첫 프레임이 얼마나 빠르게 팍 터질지 정합니다. 짧을수록 더 순간 폭발 느낌입니다.",
            self.sp_spectator_hit_fx_base_size: "피격 이펙트 기본 크기입니다.",
            self.sp_spectator_hit_fx_damage_scale: "데미지가 클수록 이펙트가 얼마나 더 커질지 정합니다.",
            self.sp_spectator_hit_fx_ring_width: "원형 링을 같이 쓸 때 링 두께입니다.",
            self.sp_spectator_hit_fx_opacity: "피격 이펙트 전체 강도/투명도입니다.",
            self.sp_spectator_hit_fx_glow: "폭발 외곽 불빛 강도입니다.",
            self.sp_spectator_hit_fx_fill_opacity: "폭발 중심부 채움 강도입니다.",
            self.chk_spectator_hit_fx_show_text: "피격 위치에 데미지 숫자를 같이 띄웁니다.",
            self.sp_spectator_hit_fx_text_scale: "데미지 숫자 크기 배수입니다.",
            self.chk_spectator_hit_fx_fast_emit: "로그를 읽자마자 피격 이펙트만 먼저 보내 반응 속도를 높입니다.",
            self.chk_spectator_hit_fx_latency_log: "피격 이펙트가 얼마나 빨리 나가는지 콘솔/로그에 기록합니다.",
            self.chk_spectator_hit_fx_sprite_enabled: "화염 폭발 느낌의 스프라이트 이펙트를 켭니다.",
            self.chk_spectator_hit_fx_ring_enabled: "폭발 위에 원형 링도 같이 표시합니다."
        }
        for _w, _tip in _spectator_tips.items():
            try:
                _w.setToolTip(_tip)
            except Exception:
                pass
        for _btn, _tip in (
            (self.btn_spectatorlog_test_hit_fx_sprite, "현재 피격 이펙트 설정을 바로 미리 봅니다."),
            (self.btn_spectatorlog_test_damage, "데미지 숫자/피격 텍스트 표시를 미리 봅니다."),
            (self.btn_spectatorlog_replay_last, "방금 읽은 로그를 다시 재생합니다."),
            (self.btn_spectatorlog_replay_stop, "진행 중인 리플레이 데모를 중지합니다."),
            (self.btn_spectatorlog_test_full_demo, "게이지, 콤보, 다운, 리포트까지 한 번에 데모합니다.")
        ):
            _btn.setToolTip(_tip)

        self.lbl_spectatorlog_state = QLabel("")
        self.lbl_spectatorlog_state.setStyleSheet("color:#667085;")
        self.lbl_spectatorlog_state.setWordWrap(True)
        spectator_lay.addWidget(self.lbl_spectatorlog_state, 17, 0, 1, 6)
        self.chk_spectatorlog_enabled.stateChanged.connect(lambda _v: (self._schedule_apply(), self._refresh_spectatorlog_state()))
        self.chk_spectatorlog_sync_players.stateChanged.connect(self._schedule_apply)
        self.chk_spectatorlog_sync_timer.stateChanged.connect(self._schedule_apply)
        self.le_spectatorlog_path.textChanged.connect(lambda _v: (self._schedule_apply(), self._refresh_spectatorlog_state()))
        self.sp_spectatorlog_poll.valueChanged.connect(self._schedule_apply)
        self.chk_spectatorlog_file_watch.stateChanged.connect(self._schedule_apply)
        self.sp_spectatorlog_debounce.valueChanged.connect(self._schedule_apply)
        self.sp_spectatorlog_backup_poll.valueChanged.connect(self._schedule_apply)
        self.chk_spectatorlog_blackbox_enabled.stateChanged.connect(lambda _v: (self._schedule_apply(), self._refresh_spectatorlog_state()))
        self.cmb_spectatorlog_blackbox_mode.currentIndexChanged.connect(self._schedule_apply)
        self.le_spectatorlog_blackbox_dir.textChanged.connect(lambda _v: (self._schedule_apply(), self._refresh_spectatorlog_state()))
        self.btn_spectatorlog_blackbox_open.clicked.connect(self._open_spectatorlog_blackbox_dir)
        self.btn_spectatorlog_test_blue_stun.clicked.connect(lambda: self._test_spectator_stun("blue"))
        self.btn_spectatorlog_test_red_stun.clicked.connect(lambda: self._test_spectator_stun("red"))
        self.btn_spectatorlog_test_blue_kd.clicked.connect(lambda: self._test_spectator_effect("blue", "knockdown"))
        self.btn_spectatorlog_test_red_kd.clicked.connect(lambda: self._test_spectator_effect("red", "knockdown"))
        self.btn_spectatorlog_test_blue_tko.clicked.connect(lambda: self._test_spectator_effect("blue", "tko"))
        self.btn_spectatorlog_test_red_tko.clicked.connect(lambda: self._test_spectator_effect("red", "tko"))
        self.btn_spectatorlog_test_damage.clicked.connect(self._test_spectator_damage)
        self.btn_spectatorlog_test_hit_fx_sprite.clicked.connect(self._test_spectator_hit_fx_sprite)
        self.btn_spectatorlog_test_hp.clicked.connect(self._test_spectator_hp_gauge)
        self.btn_spectatorlog_test_blue_combo.clicked.connect(lambda: self._test_spectator_combo("blue"))
        self.btn_spectatorlog_test_red_combo.clicked.connect(lambda: self._test_spectator_combo("red"))
        self.btn_spectatorlog_test_counter.clicked.connect(self._test_spectator_counter)
        self.btn_spectatorlog_test_lives.clicked.connect(self._test_spectator_lives)
        self.btn_spectatorlog_test_timer_state.clicked.connect(self._test_spectator_timer_state)
        self.btn_spectatorlog_test_vs_intro.clicked.connect(self._test_spectator_vs_intro)
        self.btn_spectatorlog_test_full_demo.clicked.connect(self._test_spectator_full_demo)
        self.btn_spectatorlog_test_round_report.clicked.connect(self._test_spectator_round_report)
        self.btn_spectatorlog_test_final_report.clicked.connect(
            lambda _checked=False: self._test_spectator_round_report(final=True)
        )
        self.btn_spectatorlog_replay_last.clicked.connect(self._test_spectator_last_log)
        self.btn_spectatorlog_replay_stop.clicked.connect(self._stop_spectator_hud_demo)
        self.btn_spectatorlog_clear_damage.clicked.connect(self._clear_spectator_damage)
        self.btn_spectator_commentary_tts_test.clicked.connect(self._test_spectator_commentary_tts)
        self.btn_spectator_commentary_full_test.clicked.connect(self._test_spectator_commentary_full_suite)
        self.btn_spectator_commentary_duo_test.clicked.connect(self._test_spectator_commentary_duo_suite)
        self.btn_spectator_commentary_down_test.clicked.connect(self._test_spectator_commentary_down_suite)
        self.btn_spectator_commentary_summary_test.clicked.connect(self._test_spectator_commentary_summary_suite)
        self.btn_spectator_commentary_stop_test.clicked.connect(self._stop_spectator_commentary_test_script)
        self.btn_spectator_commentary_full_test_tab.clicked.connect(self._test_spectator_commentary_full_suite)
        self.btn_spectator_commentary_duo_test_tab.clicked.connect(self._test_spectator_commentary_duo_suite)
        self.btn_spectator_commentary_down_test_tab.clicked.connect(self._test_spectator_commentary_down_suite)
        self.btn_spectator_commentary_summary_test_tab.clicked.connect(self._test_spectator_commentary_summary_suite)
        self.btn_spectator_commentary_stop_test_tab.clicked.connect(self._stop_spectator_commentary_test_script)
        self.btn_spectator_stun_sfx_pick.clicked.connect(lambda: self._pick_spectator_sfx(self.le_spectator_stun_sfx))
        self.btn_spectator_kd_sfx_pick.clicked.connect(lambda: self._pick_spectator_sfx(self.le_spectator_kd_sfx))
        self.btn_spectator_tko_sfx_pick.clicked.connect(lambda: self._pick_spectator_sfx(self.le_spectator_tko_sfx))
        self.btn_spectator_stun_sfx_test.clicked.connect(lambda: self._test_spectator_sfx("stun"))
        self.btn_spectator_kd_sfx_test.clicked.connect(lambda: self._test_spectator_sfx("knockdown"))
        self.btn_spectator_tko_sfx_test.clicked.connect(lambda: self._test_spectator_sfx("tko"))
        self.chk_spectator_commentary.stateChanged.connect(self._schedule_apply)
        self.cmb_spectator_commentary_mode.currentIndexChanged.connect(self._schedule_apply)
        self.cmb_spectator_commentary_voice.currentIndexChanged.connect(self._schedule_apply)
        self.cmb_spectator_caster_voice.currentIndexChanged.connect(self._schedule_apply)
        self.sp_spectator_commentary_damage.valueChanged.connect(self._schedule_apply)
        self.sp_spectator_hit_effect_damage.valueChanged.connect(self._schedule_apply)
        self.cb_spectator_hit_fx_color_preset.currentIndexChanged.connect(self._schedule_apply)
        self.le_spectator_hit_fx_color_low.textChanged.connect(self._schedule_apply)
        self.le_spectator_hit_fx_color_mid.textChanged.connect(self._schedule_apply)
        self.le_spectator_hit_fx_color_high.textChanged.connect(self._schedule_apply)
        self.le_spectator_hit_fx_color_weak.textChanged.connect(self._schedule_apply)
        self.le_spectator_hit_fx_color_stun.textChanged.connect(self._schedule_apply)
        self.btn_spectator_hit_fx_color_low.clicked.connect(lambda: self._pick_spectator_hit_fx_color(self.le_spectator_hit_fx_color_low, self.btn_spectator_hit_fx_color_low, "Low 피격 색상"))
        self.btn_spectator_hit_fx_color_mid.clicked.connect(lambda: self._pick_spectator_hit_fx_color(self.le_spectator_hit_fx_color_mid, self.btn_spectator_hit_fx_color_mid, "Mid 피격 색상"))
        self.btn_spectator_hit_fx_color_high.clicked.connect(lambda: self._pick_spectator_hit_fx_color(self.le_spectator_hit_fx_color_high, self.btn_spectator_hit_fx_color_high, "High 피격 색상"))
        self.btn_spectator_hit_fx_color_weak.clicked.connect(lambda: self._pick_spectator_hit_fx_color(self.le_spectator_hit_fx_color_weak, self.btn_spectator_hit_fx_color_weak, "Weak 피격 색상"))
        self.btn_spectator_hit_fx_color_stun.clicked.connect(lambda: self._pick_spectator_hit_fx_color(self.le_spectator_hit_fx_color_stun, self.btn_spectator_hit_fx_color_stun, "Stun/Down 피격 색상"))
        self.sp_spectator_hit_fx_duration.valueChanged.connect(self._schedule_apply)
        self.sp_spectator_hit_fx_base_size.valueChanged.connect(self._schedule_apply)
        self.sp_spectator_hit_fx_damage_scale.valueChanged.connect(self._schedule_apply)
        self.sp_spectator_hit_fx_ring_width.valueChanged.connect(self._schedule_apply)
        self.sp_spectator_hit_fx_opacity.valueChanged.connect(self._schedule_apply)
        self.sp_spectator_hit_fx_glow.valueChanged.connect(self._schedule_apply)
        self.sp_spectator_hit_fx_fill_opacity.valueChanged.connect(self._schedule_apply)
        self.chk_spectator_hit_fx_show_text.stateChanged.connect(self._schedule_apply)
        self.sp_spectator_hit_fx_text_scale.valueChanged.connect(self._schedule_apply)
        self.chk_spectator_hit_fx_fast_emit.stateChanged.connect(self._schedule_apply)
        self.chk_spectator_hit_fx_latency_log.stateChanged.connect(self._schedule_apply)
        self.chk_spectator_hit_fx_sprite_enabled.stateChanged.connect(self._schedule_apply)
        self.chk_spectator_hit_fx_ring_enabled.stateChanged.connect(self._schedule_apply)
        self.sp_spectator_hit_fx_pop.valueChanged.connect(self._schedule_apply)
        self.sp_spectator_commentary_cooldown.valueChanged.connect(self._schedule_apply)
        self.sp_spectator_commentary_rate.valueChanged.connect(self._schedule_apply)
        self.sp_spectator_commentary_volume.valueChanged.connect(self._schedule_apply)
        self.sp_spectator_commentary_pitch.valueChanged.connect(self._schedule_apply)
        self.sp_spectator_replay_speed.valueChanged.connect(self._schedule_apply)
        self.chk_spectator_replay_real_time.stateChanged.connect(self._schedule_apply)
        self.sp_spectator_recent_text_size.valueChanged.connect(self._schedule_apply)
        self.sp_spectator_sfx_rate.valueChanged.connect(self._schedule_apply)
        self.le_spectator_stun_sfx.textChanged.connect(self._schedule_apply)
        self.le_spectator_kd_sfx.textChanged.connect(self._schedule_apply)
        self.le_spectator_tko_sfx.textChanged.connect(self._schedule_apply)
        self._refresh_spectatorlog_state()

        # Keep log ingestion focused on files/replay; visual hit tuning lives in
        # its own tab so users can find and test it without scanning the log grid.
        for row in range(10, 18):
            for column in range(spectator_lay.columnCount()):
                item = spectator_lay.itemAtPosition(row, column)
                if item is not None and item.widget() is not None:
                    item.widget().setVisible(False)

        hit_group = QGroupBox("브라우저 피격 이펙트")
        hit_lay = QGridLayout(hit_group)
        hit_lay.setHorizontalSpacing(12)
        hit_lay.setVerticalSpacing(10)
        hit_lay.addWidget(QLabel("표시 최소 데미지"), 0, 0)
        hit_lay.addWidget(self.sp_spectator_hit_effect_damage, 0, 1)
        hit_lay.addWidget(QLabel("색상 프리셋"), 0, 2)
        hit_lay.addWidget(self.cb_spectator_hit_fx_color_preset, 0, 3)
        hit_lay.addWidget(self.btn_spectatorlog_test_hit_fx_sprite, 0, 4)

        for row, (label, button) in enumerate(
            (
                ("낮은 데미지", self.btn_spectator_hit_fx_color_low),
                ("중간 데미지", self.btn_spectator_hit_fx_color_mid),
                ("높은 데미지", self.btn_spectator_hit_fx_color_high),
                ("약점 타격", self.btn_spectator_hit_fx_color_weak),
                ("스턴 / 다운", self.btn_spectator_hit_fx_color_stun),
            ),
            start=1,
        ):
            hit_lay.addWidget(QLabel(label), row, 0)
            hit_lay.addWidget(button, row, 1)

        hit_lay.addWidget(QLabel("전체 지속시간"), 1, 2)
        hit_lay.addWidget(self.sp_spectator_hit_fx_duration, 1, 3)
        hit_lay.addWidget(QLabel("초기 폭발시간"), 1, 4)
        hit_lay.addWidget(self.sp_spectator_hit_fx_pop, 1, 5)
        hit_lay.addWidget(QLabel("기본 크기"), 2, 2)
        hit_lay.addWidget(self.sp_spectator_hit_fx_base_size, 2, 3)
        hit_lay.addWidget(QLabel("데미지 크기 배율"), 2, 4)
        hit_lay.addWidget(self.sp_spectator_hit_fx_damage_scale, 2, 5)
        hit_lay.addWidget(QLabel("링 두께"), 3, 2)
        hit_lay.addWidget(self.sp_spectator_hit_fx_ring_width, 3, 3)
        hit_lay.addWidget(QLabel("전체 투명도"), 3, 4)
        hit_lay.addWidget(self.sp_spectator_hit_fx_opacity, 3, 5)
        hit_lay.addWidget(QLabel("발광 강도"), 4, 2)
        hit_lay.addWidget(self.sp_spectator_hit_fx_glow, 4, 3)
        hit_lay.addWidget(QLabel("내부 채움"), 4, 4)
        hit_lay.addWidget(self.sp_spectator_hit_fx_fill_opacity, 4, 5)
        hit_lay.addWidget(self.chk_spectator_hit_fx_show_text, 5, 2)
        hit_lay.addWidget(self.sp_spectator_hit_fx_text_scale, 5, 3)
        hit_lay.addWidget(self.chk_spectator_hit_fx_sprite_enabled, 5, 4)
        hit_lay.addWidget(self.chk_spectator_hit_fx_ring_enabled, 5, 5)
        hit_lay.addWidget(self.chk_spectator_hit_fx_fast_emit, 6, 2, 1, 2)
        hit_lay.addWidget(self.chk_spectator_hit_fx_latency_log, 6, 4, 1, 2)
        for widget in (
            self.sp_spectator_hit_effect_damage,
            self.cb_spectator_hit_fx_color_preset,
            self.btn_spectatorlog_test_hit_fx_sprite,
            self.btn_spectator_hit_fx_color_low,
            self.btn_spectator_hit_fx_color_mid,
            self.btn_spectator_hit_fx_color_high,
            self.btn_spectator_hit_fx_color_weak,
            self.btn_spectator_hit_fx_color_stun,
            self.sp_spectator_hit_fx_duration,
            self.sp_spectator_hit_fx_pop,
            self.sp_spectator_hit_fx_base_size,
            self.sp_spectator_hit_fx_damage_scale,
            self.sp_spectator_hit_fx_ring_width,
            self.sp_spectator_hit_fx_opacity,
            self.sp_spectator_hit_fx_glow,
            self.sp_spectator_hit_fx_fill_opacity,
            self.chk_spectator_hit_fx_show_text,
            self.sp_spectator_hit_fx_text_scale,
            self.chk_spectator_hit_fx_sprite_enabled,
            self.chk_spectator_hit_fx_ring_enabled,
            self.chk_spectator_hit_fx_fast_emit,
            self.chk_spectator_hit_fx_latency_log,
        ):
            widget.setVisible(True)
        hit_lay.setColumnStretch(3, 1)
        hit_lay.setColumnStretch(5, 1)
        hit_effects_outer.addWidget(hit_group)
        hit_effects_outer.addStretch(1)

        log_lay.addWidget(spectator_group)

        auto_start_group = QGroupBox("매치 로비 자동 시작")
        auto_start_lay = QGridLayout(auto_start_group)
        self.chk_spectator_lobby_auto_start = QCheckBox("양쪽 선수가 레디하면 시작 버튼 자동 클릭")
        self.chk_spectator_lobby_auto_start.setChecked(bool(getattr(self.cfg, "spectator_lobby_auto_start_enabled", False)))
        self.chk_spectator_lobby_auto_start.setToolTip("lobby.txt의 ready_to_start가 OFF에서 ON으로 바뀌는 순간 한 번만 클릭합니다.")
        auto_start_lay.addWidget(self.chk_spectator_lobby_auto_start, 0, 0, 1, 5)

        auto_start_lay.addWidget(QLabel("관전툴 창 제목"), 1, 0)
        self.le_spectator_lobby_auto_start_title = QLineEdit(
            str(
                getattr(
                    self.cfg,
                    "spectator_lobby_auto_start_target_title",
                    "The Thrill of the Fight 2",
                )
                or "The Thrill of the Fight 2"
            )
        )
        self.le_spectator_lobby_auto_start_title.setPlaceholderText("The Thrill of the Fight 2")
        self.le_spectator_lobby_auto_start_title.setToolTip("창 제목 일부만 입력해도 됩니다. 오작동 방지를 위해 비워두면 자동 클릭하지 않습니다.")
        auto_start_lay.addWidget(self.le_spectator_lobby_auto_start_title, 1, 1, 1, 4)

        auto_start_lay.addWidget(QLabel("시작 버튼 위치"), 2, 0)
        self.sp_spectator_lobby_auto_start_x = QSpinBox()
        self.sp_spectator_lobby_auto_start_x.setRange(0, 20000)
        self.sp_spectator_lobby_auto_start_x.setValue(int(getattr(self.cfg, "spectator_lobby_auto_start_client_x", 0) or 0))
        self.sp_spectator_lobby_auto_start_y = QSpinBox()
        self.sp_spectator_lobby_auto_start_y.setRange(0, 20000)
        self.sp_spectator_lobby_auto_start_y.setValue(int(getattr(self.cfg, "spectator_lobby_auto_start_client_y", 0) or 0))
        self.btn_spectator_lobby_auto_start_capture = QPushButton("2초 후 현재 마우스 위치 찍기")
        self.btn_spectator_lobby_auto_start_test = QPushButton("자동 클릭 테스트")
        auto_start_lay.addWidget(QLabel("X"), 2, 1)
        auto_start_lay.addWidget(self.sp_spectator_lobby_auto_start_x, 2, 2)
        auto_start_lay.addWidget(QLabel("Y"), 2, 3)
        auto_start_lay.addWidget(self.sp_spectator_lobby_auto_start_y, 2, 4)
        auto_start_lay.addWidget(self.btn_spectator_lobby_auto_start_capture, 3, 1, 1, 2)
        auto_start_lay.addWidget(self.btn_spectator_lobby_auto_start_test, 3, 3, 1, 2)

        auto_start_lay.addWidget(QLabel("클릭 전 대기"), 4, 0)
        self.sp_spectator_lobby_auto_start_delay = QSpinBox()
        self.sp_spectator_lobby_auto_start_delay.setRange(0, 5000)
        self.sp_spectator_lobby_auto_start_delay.setSingleStep(50)
        self.sp_spectator_lobby_auto_start_delay.setSuffix(" ms")
        self.sp_spectator_lobby_auto_start_delay.setValue(
            int(getattr(self.cfg, "spectator_lobby_auto_start_delay_ms", 300) or 300)
        )
        auto_start_lay.addWidget(self.sp_spectator_lobby_auto_start_delay, 4, 1)
        auto_start_lay.addWidget(QLabel("클릭 횟수"), 4, 2)
        self.sp_spectator_lobby_auto_start_click_count = QSpinBox()
        self.sp_spectator_lobby_auto_start_click_count.setRange(1, 10)
        self.sp_spectator_lobby_auto_start_click_count.setSuffix(" 회")
        self.sp_spectator_lobby_auto_start_click_count.setValue(
            int(getattr(self.cfg, "spectator_lobby_auto_start_click_count", 1) or 1)
        )
        auto_start_lay.addWidget(self.sp_spectator_lobby_auto_start_click_count, 4, 3)
        self.chk_spectator_lobby_auto_start_activate = QCheckBox("클릭 전 관전툴 활성화")
        self.chk_spectator_lobby_auto_start_activate.setChecked(
            bool(getattr(self.cfg, "spectator_lobby_auto_start_activate", True))
        )
        self.chk_spectator_lobby_auto_start_restore_focus = QCheckBox("클릭 후 이전 창 복원")
        self.chk_spectator_lobby_auto_start_restore_focus.setChecked(
            bool(getattr(self.cfg, "spectator_lobby_auto_start_restore_focus", True))
        )
        self.chk_spectator_lobby_auto_start_restore_cursor = QCheckBox("클릭 후 마우스 원위치")
        self.chk_spectator_lobby_auto_start_restore_cursor.setChecked(
            bool(getattr(self.cfg, "spectator_lobby_auto_start_restore_cursor", True))
        )
        self.chk_spectator_lobby_auto_start_minimize_target = QCheckBox("클릭 후 관전툴 최소화")
        self.chk_spectator_lobby_auto_start_minimize_target.setChecked(
            bool(getattr(self.cfg, "spectator_lobby_auto_start_minimize_target", False))
        )
        auto_start_lay.addWidget(self.chk_spectator_lobby_auto_start_activate, 5, 1)
        auto_start_lay.addWidget(self.chk_spectator_lobby_auto_start_restore_focus, 5, 2, 1, 2)
        auto_start_lay.addWidget(self.chk_spectator_lobby_auto_start_restore_cursor, 5, 4)
        auto_start_lay.addWidget(self.chk_spectator_lobby_auto_start_minimize_target, 6, 1, 1, 2)
        self.lbl_spectator_lobby_auto_start_state = QLabel("대기")
        self.lbl_spectator_lobby_auto_start_state.setStyleSheet("color:#94a3b8;")
        auto_start_lay.addWidget(self.lbl_spectator_lobby_auto_start_state, 7, 0, 1, 5)
        auto_start_lay.setColumnStretch(1, 1)

        self.btn_spectator_lobby_auto_start_capture.clicked.connect(self._capture_spectator_lobby_auto_start_point)
        self.btn_spectator_lobby_auto_start_test.clicked.connect(self._test_spectator_lobby_auto_start_click)
        for widget, signal_name in (
            (self.chk_spectator_lobby_auto_start, "stateChanged"),
            (self.le_spectator_lobby_auto_start_title, "textChanged"),
            (self.sp_spectator_lobby_auto_start_x, "valueChanged"),
            (self.sp_spectator_lobby_auto_start_y, "valueChanged"),
            (self.sp_spectator_lobby_auto_start_delay, "valueChanged"),
            (self.sp_spectator_lobby_auto_start_click_count, "valueChanged"),
            (self.chk_spectator_lobby_auto_start_activate, "stateChanged"),
            (self.chk_spectator_lobby_auto_start_restore_focus, "stateChanged"),
            (self.chk_spectator_lobby_auto_start_restore_cursor, "stateChanged"),
            (self.chk_spectator_lobby_auto_start_minimize_target, "stateChanged"),
        ):
            getattr(widget, signal_name).connect(self._schedule_apply)
        auto_start_outer.addWidget(auto_start_group)
        auto_start_outer.addStretch(1)
        log_lay.addStretch(1)
        log_container = QWidget()
        log_container.setLayout(log_lay)
        self.log_scroll = QScrollArea()
        self.log_scroll.setWidgetResizable(True)
        self.log_scroll.setWidget(log_container)
        log_outer = QVBoxLayout()
        log_outer.addWidget(self.log_scroll)
        self.tab_logs.setLayout(log_outer)

        hit_effects_container = QWidget()
        hit_effects_container.setLayout(hit_effects_outer)
        self.hit_effects_scroll = QScrollArea()
        self.hit_effects_scroll.setWidgetResizable(True)
        self.hit_effects_scroll.setWidget(hit_effects_container)
        hit_effects_tab_lay = QVBoxLayout()
        hit_effects_tab_lay.addWidget(self.hit_effects_scroll)
        self.tab_hit_effects.setLayout(hit_effects_tab_lay)

        record_lay.addStretch(1)
        record_container = QWidget()
        record_container.setLayout(record_lay)
        self.record_scroll = QScrollArea()
        self.record_scroll.setWidgetResizable(True)
        self.record_scroll.setWidget(record_container)
        record_outer = QVBoxLayout()
        record_outer.addWidget(self.record_scroll)
        self.tab_log_records.setLayout(record_outer)

        auto_start_container = QWidget()
        auto_start_container.setLayout(auto_start_outer)
        self.auto_start_scroll = QScrollArea()
        self.auto_start_scroll.setWidgetResizable(True)
        self.auto_start_scroll.setWidget(auto_start_container)
        auto_start_tab_lay = QVBoxLayout()
        auto_start_tab_lay.addWidget(self.auto_start_scroll)
        self.tab_auto_start.setLayout(auto_start_tab_lay)

        sound_lay_outer.addWidget(sound_group)
        sound_lay_outer.addStretch(1)
        self._sound_lay_outer = sound_lay_outer
        sound_container = QWidget()
        sound_container.setLayout(sound_lay_outer)
        self.sound_scroll = QScrollArea()
        self.sound_scroll.setWidgetResizable(True)
        self.sound_scroll.setWidget(sound_container)
        sound_outer = QVBoxLayout()
        sound_outer.addWidget(self.sound_scroll)
        self.tab_sound.setLayout(sound_outer)

        test_lay_outer.addStretch(1)
        test_container = QWidget()
        test_container.setLayout(test_lay_outer)
        self.test_scroll = QScrollArea()
        self.test_scroll.setWidgetResizable(True)
        self.test_scroll.setWidget(test_container)
        test_outer = QVBoxLayout()
        test_outer.addWidget(self.test_scroll)
        self.tab_tests.setLayout(test_outer)

    def _refresh_chapter_status_label(self):
        if not hasattr(self, "lbl_chapter_status"):
            return
        if callable(self._chapter_status_getter):
            try:
                txt = str(self._chapter_status_getter() or "").strip()
            except Exception:
                txt = ""
            self.lbl_chapter_status.setText(txt or "-")
            return
        anchor = float(getattr(self.cfg, "chapter_anchor_epoch", 0.0) or 0.0)
        if anchor <= 0:
            self.lbl_chapter_status.setText("")
        else:
            self.lbl_chapter_status.setText(datetime.fromtimestamp(anchor).strftime("%Y-%m-%d %H:%M:%S"))

    def _export_chapter_txt_from_settings(self):
        if not callable(self._chapter_export):
            QMessageBox.information(self, "챕터", "내보내기 기능이 연결되지 않았습니다.")
            return
        path = ""
        try:
            path = str(self._chapter_export() or "")
        except Exception:
            path = ""
        if path:
            QMessageBox.information(self, "챕터", f"저장 완료\n{path}")
        else:
            QMessageBox.information(self, "챕터", "저장할 챕터가 없습니다.")
        self._refresh_chapter_status_label()

    def _open_chapter_txt_from_settings(self):
        if not callable(getattr(self, "_chapter_open", None)):
            QMessageBox.information(self, "챕터", "열기 기능이 연결되지 않았습니다.")
            return
        path = ""
        try:
            path = str(self._chapter_open() or "")
        except Exception as e:
            QMessageBox.warning(self, "챕터", f"파일을 열 수 없습니다.\n{e}")
            return
        if not path:
            QMessageBox.information(self, "챕터", "열 챕터 파일이 없습니다.")
            return
        self._refresh_chapter_status_label()

    def _browse_spectatorlog_path(self):
        current = str(self.le_spectatorlog_path.text() or "").strip() if hasattr(self, "le_spectatorlog_path") else ""
        start = resolve_spectatorlog_path(current)
        if not os.path.isdir(start):
            parent = os.path.dirname(start)
            start = parent if os.path.isdir(parent) else get_app_base_dir()
        path = QFileDialog.getExistingDirectory(self, "SpectatorLog 폴더 선택", start)
        if not path:
            return
        resolved = resolve_spectatorlog_path(path)
        if hasattr(self, "le_spectatorlog_path"):
            self.le_spectatorlog_path.setText(to_app_rel(resolved))
        self._refresh_spectatorlog_state()
        self._schedule_apply()

    def _refresh_spectatorlog_state(self):
        if not hasattr(self, "lbl_spectatorlog_state"):
            return
        raw = str(self.le_spectatorlog_path.text() or "").strip() if hasattr(self, "le_spectatorlog_path") else ""
        root = resolve_spectatorlog_path(raw)
        enabled = bool(self.chk_spectatorlog_enabled.isChecked()) if hasattr(self, "chk_spectatorlog_enabled") else bool(getattr(self.cfg, "spectatorlog_enabled", False))
        needed = [
            os.path.join(root, "blue", "name.txt"),
            os.path.join(root, "red", "name.txt"),
            os.path.join(root, "match", "round_time.txt"),
            os.path.join(root, "match", "round_number.txt"),
        ]
        ok = os.path.isdir(root) and all(os.path.exists(p) for p in needed)
        state = "ON" if enabled else "OFF"
        bb_enabled = bool(self.chk_spectatorlog_blackbox_enabled.isChecked()) if hasattr(self, "chk_spectatorlog_blackbox_enabled") else bool(getattr(self.cfg, "spectatorlog_blackbox_enabled", False))
        bb_state = "BB REC" if bb_enabled else "BB OFF"
        if ok:
            self.lbl_spectatorlog_state.setText(f"{state} | {bb_state} | 인식 폴더: {root}")
        else:
            self.lbl_spectatorlog_state.setText(f"{state} | {bb_state} | 폴더/필수 파일 확인 필요: {root}")

    def _capture_spectator_lobby_auto_start_point(self):
        title = str(self.le_spectator_lobby_auto_start_title.text() or "").strip()
        if not title:
            QMessageBox.warning(self, "자동 시작", "먼저 관전툴 창 제목을 입력하세요.")
            return
        self.btn_spectator_lobby_auto_start_capture.setEnabled(False)
        self.btn_spectator_lobby_auto_start_capture.setText("2초 안에 시작 버튼에 마우스를 올리세요")
        self.lbl_spectator_lobby_auto_start_state.setText("시작 버튼 위에 마우스를 올려두세요.")

        def _capture():
            ok, x, y, detail = window_client_point_from_cursor(title)
            self.btn_spectator_lobby_auto_start_capture.setEnabled(True)
            self.btn_spectator_lobby_auto_start_capture.setText("2초 후 현재 마우스 위치 찍기")
            if not ok:
                self.lbl_spectator_lobby_auto_start_state.setText(f"위치 저장 실패: {detail}")
                QMessageBox.warning(self, "자동 시작 위치 저장 실패", detail)
                return
            self.sp_spectator_lobby_auto_start_x.setValue(x)
            self.sp_spectator_lobby_auto_start_y.setValue(y)
            self.lbl_spectator_lobby_auto_start_state.setText(f"저장 완료: 창 내부 X={x}, Y={y}")
            logging.info("LOBBY_AUTO_START_CAPTURE %s", detail)
            self._schedule_apply()

        QTimer.singleShot(2000, _capture)

    def _test_spectator_lobby_auto_start_click(self):
        title = str(self.le_spectator_lobby_auto_start_title.text() or "").strip()
        x = int(self.sp_spectator_lobby_auto_start_x.value())
        y = int(self.sp_spectator_lobby_auto_start_y.value())
        if not title:
            QMessageBox.warning(self, "자동 시작 테스트", "관전툴 창 제목을 입력하세요.")
            return
        click_count = int(self.sp_spectator_lobby_auto_start_click_count.value())
        original_hwnd = int(ctypes.windll.user32.GetForegroundWindow() or 0) if os.name == "nt" else 0
        original_cursor = _current_cursor_screen_position()
        ok, detail = True, ""
        for index in range(click_count):
            ok, detail = click_window_client_point(
                title,
                x,
                y,
                activate=bool(self.chk_spectator_lobby_auto_start_activate.isChecked()) and index == 0,
                restore_focus=(
                    bool(self.chk_spectator_lobby_auto_start_restore_focus.isChecked())
                    and index == click_count - 1
                ),
                restore_cursor=(
                    bool(self.chk_spectator_lobby_auto_start_restore_cursor.isChecked())
                    and index == click_count - 1
                ),
                minimize_target=(
                    bool(self.chk_spectator_lobby_auto_start_minimize_target.isChecked())
                    and index == click_count - 1
                ),
                previous_hwnd_override=original_hwnd,
                previous_cursor_override=original_cursor,
            )
            if not ok:
                break
            if index < click_count - 1:
                time.sleep(0.12)
        logging.info("LOBBY_AUTO_START_TEST ok=%s %s", ok, detail)
        self.lbl_spectator_lobby_auto_start_state.setText(
            ("테스트 성공: " if ok else "테스트 실패: ") + detail
        )
        if not ok:
            QMessageBox.warning(self, "자동 시작 테스트 실패", detail)

    def _open_spectatorlog_blackbox_dir(self):
        raw = ""
        try:
            if hasattr(self, "le_spectatorlog_blackbox_dir"):
                raw = str(self.le_spectatorlog_blackbox_dir.text() or "").strip()
            if not raw:
                raw = str(getattr(self.cfg, "spectatorlog_blackbox_dir", "SpectatorLogArchive") or "SpectatorLogArchive")
            path = normalize_app_path(raw)
            os.makedirs(path, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path)))
        except Exception as exc:
            try:
                QMessageBox.warning(self, "기록 폴더 열기 실패", str(exc))
            except Exception:
                pass

    def _set_hit_fx_color_button(self, button, value: str) -> None:
        try:
            color = _normalize_hex_color(str(value or "#ffffff").strip() or "#ffffff")
        except Exception:
            color = "#ffffff"
        try:
            button.setText(color.upper())
            button.setStyleSheet(
                "QPushButton {"
                f"background:{color};"
                "color:#111827;"
                "border:1px solid #334155;"
                "border-radius:6px;"
                "font-weight:700;"
                "padding:4px 8px;"
                "}"
            )
            button.setProperty("color_hex", color)
        except Exception:
            pass

    def _pick_spectator_hit_fx_color(self, line_edit, button, title: str = "색상 선택") -> None:
        try:
            current = _normalize_hex_color(str(line_edit.text() or button.property("color_hex") or "#ffffff"))
        except Exception:
            current = "#ffffff"
        try:
            color = QColorDialog.getColor(QColor(current), self, title)
            if not color.isValid():
                return
            value = color.name(QColor.HexRgb)
            line_edit.setText(value)
            self._set_hit_fx_color_button(button, value)
            try:
                if hasattr(self, "cb_spectator_hit_fx_color_preset"):
                    idx = self.cb_spectator_hit_fx_color_preset.findData("custom")
                    if idx >= 0:
                        self.cb_spectator_hit_fx_color_preset.setCurrentIndex(idx)
            except Exception:
                pass
            self._schedule_apply()
        except Exception:
            logging.exception("SPECTATOR_HIT_FX_COLOR_PICK_FAIL")

    def _pick_spectator_sfx(self, line_edit: QLineEdit):
        current = str(line_edit.text() or "").strip() if line_edit is not None else ""
        resolved = ""
        if current:
            try:
                raw = os.path.expanduser(current)
                resolved = os.path.abspath(raw if os.path.isabs(raw) else os.path.join(get_app_base_dir(), raw))
            except Exception:
                resolved = current
        start = os.path.dirname(resolved) if resolved and os.path.exists(os.path.dirname(resolved)) else get_app_base_dir()
        path, _ = QFileDialog.getOpenFileName(self, "효과음 선택", start, "Audio Files (*.wav *.mp3);;All Files (*.*)")
        if path and line_edit is not None:
            line_edit.setText(to_app_rel(path))

    def _spectator_sfx_path(self, kind: str) -> str:
        kind = str(kind or "").lower().strip()
        if kind == "stun":
            if hasattr(self, "le_spectator_stun_sfx"):
                return str(self.le_spectator_stun_sfx.text() or "").strip()
            return str(getattr(self.cfg, "spectator_stun_sfx_path", "") or "").strip()
        if kind == "tko":
            if hasattr(self, "le_spectator_tko_sfx"):
                return str(self.le_spectator_tko_sfx.text() or "").strip()
            return str(getattr(self.cfg, "spectator_tko_sfx_path", "") or "").strip()
        if hasattr(self, "le_spectator_kd_sfx"):
            return str(self.le_spectator_kd_sfx.text() or "").strip()
        return str(getattr(self.cfg, "spectator_knockdown_sfx_path", "") or "").strip()

    def _test_spectator_sfx(self, kind: str):
        try:
            self.apply_only(silent=True)
        except Exception:
            pass
        if not self._spectator_sfx_path(kind):
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return
        self._play_spectator_sfx(kind, show_warning=True)

    def _ensure_spectator_sfx_player(self) -> bool:
        if self._spectator_sfx_player is not None and self._spectator_sfx_audio_out is not None:
            return True
        if not HAS_QTMULTIMEDIA or QMediaPlayer is None or QAudioOutput is None:
            return False
        try:
            self._spectator_sfx_audio_out = QAudioOutput()
            self._spectator_sfx_player = QMediaPlayer()
            self._spectator_sfx_player.setAudioOutput(self._spectator_sfx_audio_out)
            self._spectator_sfx_audio_out.setVolume(1.0)
            return True
        except Exception:
            self._spectator_sfx_audio_out = None
            self._spectator_sfx_player = None
            logging.debug("SETTINGS_SFX_PLAYER_INIT_FAIL", exc_info=True)
            return False

    def _ensure_tts_test_player(self, role: str) -> bool:
        role = "caster" if str(role or "").lower() == "caster" else "analyst"
        if (getattr(self, "_tts_test_players", {}) or {}).get(role) is not None and (getattr(self, "_tts_test_audio_outs", {}) or {}).get(role) is not None:
            return True
        if not HAS_QTMULTIMEDIA or QMediaPlayer is None or QAudioOutput is None:
            return False
        try:
            audio_out = QAudioOutput()
            player = QMediaPlayer()
            player.setAudioOutput(audio_out)
            audio_out.setVolume(1.0)
            player.mediaStatusChanged.connect(lambda status, r=role: self._on_tts_test_media_status(r, status))
            self._tts_test_audio_outs[role] = audio_out
            self._tts_test_players[role] = player
            return True
        except Exception:
            logging.debug("SETTINGS_TTS_PLAYER_INIT_FAIL role=%s", role, exc_info=True)
            self._tts_test_audio_outs.pop(role, None)
            self._tts_test_players.pop(role, None)
            return False

    def _play_spectator_sfx(self, kind: str, show_warning: bool = False):
        raw = self._spectator_sfx_path(kind)
        if not raw:
            return False
        try:
            playback_rate = float(self.sp_spectator_sfx_rate.value()) if hasattr(self, "sp_spectator_sfx_rate") else float(getattr(self.cfg, "spectator_sfx_playback_rate", 1.0) or 1.0)
        except Exception:
            playback_rate = 1.0
        try:
            expanded = os.path.expanduser(raw)
            resolved = os.path.abspath(expanded if os.path.isabs(expanded) else os.path.join(get_app_base_dir(), expanded))
        except Exception:
            resolved = raw
        if not os.path.isfile(resolved):
            if show_warning:
                QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return False
        ext = str(resolved).lower().strip()
        ok = False
        if ext.endswith((".wav", ".mp3")):
            if self._ensure_spectator_sfx_player():
                ok = _play_media_sfx(self._spectator_sfx_player, self._spectator_sfx_audio_out, resolved, playback_rate=playback_rate)
        if not ok and ext.endswith(".wav"):
            ok = _play_win_effect_sfx(resolved)
        if not ok and show_warning:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
        return bool(ok)

    def _spectator_timer_target(self):
        return self._timer_win or getattr(self.controller, "timer_win", None)

    def _push_browser_overlay_event(self, kind: str, **payload):
        try:
            overlay = getattr(self.controller, "browser_overlay", None) if self.controller else None
            if overlay is not None:
                overlay.push_event(str(kind or ""), **payload)
                return True
        except Exception:
            logging.exception("BROWSER_OVERLAY_PUSH_FAIL kind=%s payload=%s", kind, payload)
        return False

    def _emit_spectator_test_update(self, payload: dict) -> bool:
        """Route Settings test-tab HUD changes through the same path as SpectatorLog.

        In browser-output-only mode the QML overlay methods are intentionally
        mostly bypassed, so calling only TimerWindow methods makes many test
        buttons appear broken in OBS.  Emitting controller.ui_update keeps QML
        preview and browser overlay behavior aligned.
        """
        try:
            data = dict(payload or {})
            if not data:
                return False
            if self.controller is not None and hasattr(self.controller, "ui_update"):
                self.controller.ui_update.emit(data)
                return True
        except Exception:
            logging.exception("SPECTATOR_TEST_UI_UPDATE_FAIL payload=%s", payload)
        return False

    def _test_set_spectator_info(self, info: dict, extra: Optional[dict] = None) -> bool:
        data = dict(extra or {})
        data["spectator_log_info"] = dict(info or {})
        return self._emit_spectator_test_update(data)

    def _test_spectator_stun(self, side: str):
        tw = self._spectator_timer_target()
        if tw is None:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return
        try:
            side = str(side or "blue")
            tw.trigger_stun_flash(side)
            self._emit_spectator_test_update({
                "spectator_effect_events": [{"side": side, "kind": "stun"}],
            })
            if bool(getattr(self.cfg, "spectator_commentary_enabled", False)):
                self._speak_tts_test_qt("크게 흔들립니다!", role="analyst")
        except Exception as e:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")

    def _test_spectator_effect(self, side: str, kind: str):
        tw = self._spectator_timer_target()
        if tw is None:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return
        try:
            side = str(side or "blue")
            kind = str(kind or "stun")
            tw.trigger_spectator_effect(side, kind)
            self._emit_spectator_test_update({
                "spectator_effect_events": [{"side": side, "kind": kind}],
            })
        except Exception as e:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")

    def _load_spectatorlog_players_for_test(self, tw) -> bool:
        root = resolve_spectatorlog_path(str(getattr(self.cfg, "spectatorlog_path", "") or ""))
        if not root or not os.path.isdir(root):
            return False
        loaded = False
        helper = _make_spectator_log_watcher(self.cfg)
        try:
            blue_raw = helper._read_text(os.path.join(root, "blue", "name.txt"))
            red_raw = helper._read_text(os.path.join(root, "red", "name.txt"))
            if blue_raw or red_raw:
                bid, bname, breg, bvalid = helper._name_payload(blue_raw) if blue_raw else ("", "", False, False)
                rid, rname, rreg, rvalid = helper._name_payload(red_raw) if red_raw else ("", "", False, False)
                tw.set_player_info(bid, rid, breg, rreg, bvalid, rvalid)
                tw.set_names(bname if blue_raw else None, rname if red_raw else None)
                tw.set_player_flags(
                    _player_flag_path_for_gid(self.cfg, bid),
                    _player_flag_path_for_gid(self.cfg, rid),
                )
                self._emit_spectator_test_update({
                    "blue_player_id": bid,
                    "red_player_id": rid,
                    "blue_name": bname if blue_raw else "",
                    "red_name": rname if red_raw else "",
                    "blue_player_registered": breg,
                    "red_player_registered": rreg,
                    "blue_player_valid": bvalid,
                    "red_player_valid": rvalid,
                })
                loaded = True
            b_img = safe_cv2_imread(os.path.join(root, "blue", "portrait.png"), cv2.IMREAD_UNCHANGED)
            r_img = safe_cv2_imread(os.path.join(root, "red", "portrait.png"), cv2.IMREAD_UNCHANGED)
            if b_img is not None or r_img is not None:
                tw.set_player_images(b_img if b_img is not None else _NO_UPDATE, r_img if r_img is not None else _NO_UPDATE)
                tw.set_overlay_visibility(
                    blue_img_visible=True,
                    blue_name_visible=True,
                    red_img_visible=True,
                    red_name_visible=True,
                )
                self._emit_spectator_test_update({
                    "blue_player_img": b_img if b_img is not None else _NO_UPDATE,
                    "red_player_img": r_img if r_img is not None else _NO_UPDATE,
                    "overlay_show_blue_img": True,
                    "overlay_show_red_img": True,
                    "overlay_show_blue_name": True,
                    "overlay_show_red_name": True,
                })
                loaded = True
        except Exception:
            logging.exception("SPECTATOR_TEST_PROFILE_LOAD_FAIL")
        return bool(loaded)

    def _test_spectator_vs_intro(self):
        tw = self._spectator_timer_target()
        if tw is None:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return
        try:
            try:
                self.apply_only(silent=True)
            except Exception:
                pass
            loaded_players = self._load_spectatorlog_players_for_test(tw)
            if not loaded_players:
                try:
                    tw.set_names("BLUE TEST", "RED TEST")
                except Exception:
                    pass
            vs_payload = {"vs_intro_event": {"source": "settings_test"}}
            if not loaded_players:
                vs_payload.update({"blue_name": "BLUE TEST", "red_name": "RED TEST"})
            self._emit_spectator_test_update(vs_payload)
            if hasattr(tw, "_backend") and hasattr(tw._backend, "test_vs_intro"):
                tw._backend.test_vs_intro()
            else:
                self._push_browser_overlay_event("vs")
            if bool(getattr(self.cfg, "spectator_commentary_enabled", False)):
                helper = _make_spectator_log_watcher(self.cfg)
                self._speak_tts_test_qt(helper._build_vs_caster_text(), role="caster", rate_override=200, pitch_override=0)
        except Exception as e:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")

    def _test_spectator_damage(self):
        tw = self._spectator_timer_target()
        if tw is None:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return
        try:
            tw.set_spectator_damage(123.4, 98.7)
            info = {
                "match_text": "",
                "recent_hit_text": "",
                "blue_recent_hit_text": "Straight 32",
                "red_recent_hit_text": "훅 28\n복부",
                "blue_punishment_text": "MID 42%  LONG 18%",
                "red_punishment_text": "MID 36%  LONG 22%",
                "blue_punishment_mid": 42.0,
                "red_punishment_mid": 36.0,
                "blue_punishment_long": 18.0,
                "red_punishment_long": 22.0,
                "blue_meta_text": "테스트 블루 HUD",
                "red_meta_text": "테스트 레드 HUD",
            }
            tw.set_spectator_log_info(info)
            dmg = max(1.0, float(getattr(self.cfg, "spectator_hit_effect_damage", 45.0) or 45.0))
            self._test_set_spectator_info(info, {
                "blue_round_damage_dealt": 123.4,
                "red_round_damage_dealt": 98.7,
                "spectator_hit_effect_events": [{
                    "side": "red",
                    "attacker_side": "blue",
                    "punch": "Straight",
                    "damage": dmg,
                }],
            })
            tw.trigger_hit_impact("red", dmg)
            def _blue_damage_step(d=dmg):
                tw.trigger_hit_impact("blue", d)
                self._emit_spectator_test_update({
                    "spectator_hit_effect_events": [{
                        "side": "blue",
                        "attacker_side": "red",
                        "punch": "Hook",
                        "damage": d,
                        "weak_point": "Body",
                    }]
                })
            QTimer.singleShot(280, _blue_damage_step)
        except Exception as e:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")

    def _test_spectator_hit_fx_sprite(self):
        tw = self._spectator_timer_target()
        if tw is None:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return
        try:
            dmg = max(60.0, float(getattr(self.cfg, "spectator_hit_effect_damage", 45.0) or 45.0) + 20.0)
            now_key = int(time.time() * 1000)
            def _impact(side: str, attacker: str, damage: float, kind: str = ""):
                key = "settings_sprite_%s_%d" % (side, int(time.time() * 1000))
                ev = {
                    "side": side,
                    "attacker_side": attacker,
                    "punch": "Straight" if side == "red" else "Hook",
                    "damage": float(damage),
                    "screen_x": 0.5,
                    "screen_y": 0.5,
                    "screenX": 0.5,
                    "screenY": 0.5,
                    "weak_point": "Head",
                    "effect_kind": kind,
                    "hitfx_key": key,
                    "hitfxKey": key,
                    "event_time": time.time(),
                    "eventTime": time.time(),
                }
                # Direct browser event: settings test must appear even if the SpectatorLog controller path is idle.
                try:
                    self._push_browser_overlay_event(
                        "impact",
                        side=side,
                        damage=float(damage),
                        effectKind=kind,
                        attackerSide=attacker,
                        punch=str(ev.get("punch") or ""),
                        weakPoint="Head",
                        coordSource="settings_test_center",
                        gloveHand="",
                        screenX=0.5,
                        screenY=0.5,
                        eventTime=float(ev.get("event_time") or 0.0),
                        hitfxKey=key,
                        pushPerfMs=time.perf_counter() * 1000.0,
                    )
                except Exception:
                    logging.exception("HITFX_SETTINGS_DIRECT_PUSH_FAIL")
                # Also send through the normal controller path so QML/preview state stays aligned.
                self._emit_spectator_test_update({"spectator_hit_effect_events": [ev]})
                try:
                    tw.trigger_hit_impact(side, float(damage))
                except Exception:
                    pass
            _impact("red", "blue", dmg, "")
            QTimer.singleShot(260, lambda: _impact("blue", "red", dmg + 12.0, "stun"))
        except Exception:
            logging.exception("HITFX_SETTINGS_TEST_FAIL")
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")

    def _test_spectator_hp_gauge(self):
        tw = self._spectator_timer_target()
        if tw is None:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return
        try:
            info = {
                "match_text": "",
                "recent_hit_text": "",
                "blue_recent_hit_text": "",
                "red_recent_hit_text": "",
                "blue_punishment_text": "PUN M 58% L 24%",
                "red_punishment_text": "PUN M 86% L 62%",
                "blue_punishment_mid": 58.0,
                "red_punishment_mid": 86.0,
                "blue_punishment_long": 24.0,
                "red_punishment_long": 62.0,
                "blue_round_knockdowns": 1,
                "red_round_knockdowns": 2,
                "blue_meta_text": "Gauge test",
                "red_meta_text": "Gauge test",
            }
            tw.set_spectator_log_info(info)
            self._test_set_spectator_info(info)
        except Exception as e:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")

    def _test_spectator_combo(self, side: str):
        tw = self._spectator_timer_target()
        if tw is None:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return
        side = "red" if str(side or "").lower() == "red" else "blue"
        receiver = "blue" if side == "red" else "red"
        try:
            token = getattr(self, "_hud_demo_token", None)
            def still_active() -> bool:
                cur = getattr(self, "_hud_demo_token", None)
                return token is None or cur is token
            info = {
                "match_text": "",
                "recent_hit_text": "",
                "blue_combo_hit_text": "",
                "blue_combo_damage_text": "",
                "red_combo_hit_text": "",
                "red_combo_damage_text": "",
                "blue_recent_hit_text": "",
                "red_recent_hit_text": "",
            }
            info[f"{side}_combo_hit_text"] = "3 HIT COMBO"
            info[f"{side}_combo_damage_text"] = "96 DAMAGE"
            info[f"{side}_recent_hit_text"] = "Hit 24"
            tw.set_spectator_log_info(info)
            self._test_set_spectator_info(info, {
                "spectator_hit_effect_events": [{
                    "side": receiver,
                    "attacker_side": side,
                    "punch": "Combo",
                    "damage": 48.0,
                }]
            })
            tw.trigger_hit_impact(receiver, 48.0)
            self._push_browser_overlay_event("hit", side=receiver, damage=48.0)
            self._speak_tts_test_qt("좋은 콤보가 적중합니다", role="analyst")
            def _browser_combo_step2():
                if still_active():
                    self._test_set_spectator_info({
                        f"{side}_combo_hit_text": "4 HIT COMBO",
                        f"{side}_combo_damage_text": "127 DAMAGE",
                        f"{side}_recent_hit_text": "Straight 31",
                    })
            def _browser_combo_clear():
                if still_active():
                    self._test_set_spectator_info({
                        f"{side}_combo_hit_text": "",
                        f"{side}_combo_damage_text": "",
                    })
            QTimer.singleShot(700, _browser_combo_step2)
            QTimer.singleShot(1450, _browser_combo_clear)
            QTimer.singleShot(700, lambda: still_active() and tw.set_spectator_log_info({
                f"{side}_combo_hit_text": "4 HIT COMBO",
                f"{side}_combo_damage_text": "127 DAMAGE",
                                f"{side}_recent_hit_text": "Straight 31",
            }))
            QTimer.singleShot(1450, lambda: still_active() and tw.set_spectator_log_info({
                f"{side}_combo_hit_text": "",
                f"{side}_combo_damage_text": "",
            }))
        except Exception as e:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")

    def _test_spectator_counter(self):
        tw = self._spectator_timer_target()
        if tw is None:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return
        try:
            token = getattr(self, "_hud_demo_token", None)
            def still_active() -> bool:
                cur = getattr(self, "_hud_demo_token", None)
                return token is None or cur is token
            info = {
                "match_text": "",
                "recent_hit_text": "",
                "blue_combo_hit_text": "COUNTER",
                "blue_combo_damage_text": "46 DAMAGE",
                "red_combo_hit_text": "",
                "red_combo_damage_text": "",
                "blue_recent_hit_text": "Straight 46",
                "red_recent_hit_text": "",
            }
            tw.set_spectator_log_info(info)
            self._test_set_spectator_info(info, {
                "spectator_hit_effect_events": [{
                    "side": "red",
                    "attacker_side": "blue",
                    "punch": "Counter",
                    "damage": 46.0,
                }]
            })
            tw.trigger_hit_impact("red", 46.0)
            self._push_browser_overlay_event("counter", side="blue", damage=46.0)
            self._speak_tts_test_qt("카운터가 적중됩니다!", role="analyst")
            def _counter_clear():
                if not still_active():
                    return
                clear_info = {
                    "blue_combo_hit_text": "",
                    "blue_combo_damage_text": "",
                }
                tw.set_spectator_log_info(clear_info)
                self._test_set_spectator_info(clear_info)
            QTimer.singleShot(1500, _counter_clear)
        except Exception as e:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")

    def _test_spectator_lives(self):
        tw = self._spectator_timer_target()
        if tw is None:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return
        try:
            steps = [
                (0, 0, 0),
                (700, 1, 0),
                (1400, 2, 1),
                (2100, 3, 2),
                (3200, 0, 0),
            ]
            for delay, blue_kd, red_kd in steps:
                def _apply_lives(b=blue_kd, r=red_kd):
                    info = {
                        "blue_round_knockdowns": b,
                        "red_round_knockdowns": r,
                    }
                    tw.set_spectator_log_info(info)
                    self._test_set_spectator_info(info)
                QTimer.singleShot(delay, _apply_lives)
        except Exception as e:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")

    def _test_spectator_timer_state(self):
        tw = self._spectator_timer_target()
        if tw is None:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return
        token = object()
        self._hud_demo_token = token

        def active() -> bool:
            return getattr(self, "_hud_demo_token", None) is token

        def apply_state(delay_ms: int, state: str, round_no: int, seconds_left: int, rest: bool):
            def _run():
                if not active():
                    return
                try:
                    total_rounds = int(getattr(self.cfg, "timer_total_rounds", 3) or 3)
                    tw.set_log_rest_mode(bool(rest))
                    tw.set_round_time(int(round_no), total_rounds, int(seconds_left))
                    self._emit_spectator_test_update({
                        "round_current": int(round_no),
                        "round_total": total_rounds,
                        "seconds_left": int(seconds_left),
                        "spectator_rest_mode": bool(rest),
                        "spectator_time_mode": str(state),
                    })
                    logging.info(
                        "SPECTATOR_TIMER_TEST state=%s rest=%s round=%s seconds_left=%s",
                        state,
                        bool(rest),
                        int(round_no),
                        int(seconds_left),
                    )
                except Exception:
                    logging.exception("SPECTATOR_TIMER_TEST_FAIL state=%s", state)
            QTimer.singleShot(max(0, int(delay_ms)), _run)

        try:
            self._noop_status("타이머 상태 테스트 시작")
            scenario = [
                (0, "roundfight", 1, 178, False),
                (2500, "roundfight", 1, 175, False),
                (5000, "roundknockdown_hold", 1, 175, False),
                (7500, "roundfoul_hold", 1, 175, False),
                (10000, "roundfight_resync", 1, 168, False),
                (12500, "roundbreak_rest", 1, 59, True),
                (15000, "roundbreak_rest", 1, 55, True),
                (18000, "roundfight_next", 2, 180, False),
            ]
            for delay, state, round_no, sec, rest in scenario:
                apply_state(delay, state, round_no, sec, rest)
            QTimer.singleShot(20500, lambda: active() and self._noop_status("타이머 상태 테스트 완료"))
        except Exception as e:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")

    def _test_spectator_round_report(self, final: bool = False):
        """Show the Round Report v2 card without requiring SpectatorLog files.

        This is intentionally synthetic: it lets the user tune the browser overlay
        design, portrait layout, decisive-moment block, and body heatmap without
        waiting for a real round break or preparing damage_events.txt.
        """
        tw = self._spectator_timer_target()
        if tw is None:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return
        try:
            try:
                self.apply_only(silent=True)
            except Exception:
                pass

            # Keep current in-app names when available, but never depend on logs.
            backend = getattr(tw, "_backend", None)
            blue_name = str(getattr(backend, "_blue_name", "") or "").strip() or "BLUE TEST"
            red_name = str(getattr(backend, "_red_name", "") or "").strip() or "RED TEST"
            if blue_name.upper() == "BLUE":
                blue_name = "BLUE TEST"
            if red_name.upper() == "RED":
                red_name = "RED TEST"
            try:
                tw.set_names(blue_name, red_name)
            except Exception:
                pass

            round_no = 2
            try:
                total_rounds = int(getattr(self.cfg, "timer_total_rounds", 3) or 3)
            except Exception:
                total_rounds = 3
            try:
                tw.set_log_rest_mode(True)
                tw.set_round_time(round_no, total_rounds, int(getattr(self.cfg, "timer_rest_sec", 60) or 60))
            except Exception:
                pass

            payload = {
                "round": round_no,
                "leader": "blue",
                "leaderName": blue_name,
                "summaryLine": "다운 장면과 턱 피격이 라운드 인상을 크게 바꿨습니다.",
                "roundTag": "DOWN ROUND",
                "displayMs": 22000,
                "bestShot": {
                    "attacker": "blue",
                    "receiver": "red",
                    "attackerName": blue_name,
                    "receiverName": red_name,
                    "damage": 82,
                    "punch": "스트레이트",
                    "weak": "턱",
                    "effect": "knockdown",
                    "time": 126.4,
                },
                "decisiveMoment": {
                    "attacker": "blue",
                    "receiver": "red",
                    "attackerName": blue_name,
                    "receiverName": red_name,
                    "damage": 82,
                    "punch": "스트레이트",
                    "weak": "턱",
                    "effect": "knockdown",
                    "time": 126.4,
                },
                "blue": {
                    "name": blue_name,
                    "landed": 24,
                    "damage": 214,
                    "bigHits": 3,
                    "knockdowns": 1,
                    "tkos": 0,
                    "stuns": 1,
                    "punchTop": [
                        {"key": "cross", "label": "스트레이트", "count": 6, "damage": 128},
                        {"key": "jab", "label": "잽", "count": 9, "damage": 54},
                        {"key": "hook", "label": "훅", "count": 4, "damage": 32},
                    ],
                    "punchBreakdown": [
                        {"key": "jab", "shortLabel": "JAB", "label": "잽", "count": 9, "damage": 54},
                        {"key": "cross", "shortLabel": "CROSS", "label": "스트레이트", "count": 6, "damage": 128},
                        {"key": "hook", "shortLabel": "HOOK", "label": "훅", "count": 4, "damage": 32},
                        {"key": "upper", "shortLabel": "UPPER", "label": "어퍼", "count": 2, "damage": 18},
                        {"key": "over", "shortLabel": "OVER", "label": "오버핸드", "count": 1, "damage": 10},
                        {"key": "other", "shortLabel": "OTHER", "label": "기타", "count": 2, "damage": 12},
                    ],
                    "weakReceivedTop": [
                        {"label": "명치", "count": 2, "damage": 44},
                        {"label": "간", "count": 1, "damage": 22},
                        {"label": "왼쪽 관자놀이", "count": 1, "damage": 18},
                    ],
                    "weakReceivedAll": [
                        {"label": "명치", "count": 2, "damage": 44},
                        {"label": "간", "count": 1, "damage": 22},
                        {"label": "왼쪽 관자놀이", "count": 1, "damage": 18},
                        {"label": "턱", "count": 1, "damage": 14},
                    ],
                    "allHits": [
                        {"screenX": 0.32, "screenY": 0.59, "damage": 16, "weak": "명치", "punch": "훅", "effect": "hit"},
                        {"screenX": 0.30, "screenY": 0.64, "damage": 18, "weak": "간", "punch": "바디 훅", "effect": "hit"},
                        {"screenX": 0.29, "screenY": 0.42, "damage": 14, "weak": "왼쪽 관자놀이", "punch": "훅", "effect": "hit"},
                        {"screenX": 0.33, "screenY": 0.50, "damage": 10, "weak": "턱", "punch": "잽", "effect": "hit"},
                        {"screenX": 0.31, "screenY": 0.55, "damage": 9, "weak": "", "punch": "잽", "effect": "hit"},
                        {"screenX": 0.35, "screenY": 0.57, "damage": 11, "weak": "", "punch": "스트레이트", "effect": "hit"},
                        {"screenX": 0.28, "screenY": 0.61, "damage": 8, "weak": "", "punch": "훅", "effect": "hit"},
                        {"screenX": 0.34, "screenY": 0.46, "damage": 7, "weak": "", "punch": "잽", "effect": "hit"},
                    ],
                },
                "red": {
                    "name": red_name,
                    "landed": 17,
                    "damage": 151,
                    "bigHits": 1,
                    "knockdowns": 0,
                    "tkos": 0,
                    "stuns": 0,
                    "punchTop": [
                        {"key": "hook", "label": "훅", "count": 6, "damage": 72},
                        {"key": "jab", "label": "잽", "count": 5, "damage": 31},
                        {"key": "upper", "label": "어퍼", "count": 2, "damage": 28},
                    ],
                    "punchBreakdown": [
                        {"key": "jab", "shortLabel": "JAB", "label": "잽", "count": 5, "damage": 31},
                        {"key": "cross", "shortLabel": "CROSS", "label": "스트레이트", "count": 1, "damage": 9},
                        {"key": "hook", "shortLabel": "HOOK", "label": "훅", "count": 6, "damage": 72},
                        {"key": "upper", "shortLabel": "UPPER", "label": "어퍼", "count": 2, "damage": 28},
                        {"key": "over", "shortLabel": "OVER", "label": "오버핸드", "count": 1, "damage": 7},
                        {"key": "other", "shortLabel": "OTHER", "label": "기타", "count": 2, "damage": 4},
                    ],
                    "weakReceivedTop": [
                        {"label": "턱", "count": 4, "damage": 126},
                        {"label": "오른쪽 관자놀이", "count": 2, "damage": 58},
                        {"label": "코", "count": 1, "damage": 18},
                    ],
                    "weakReceivedAll": [
                        {"label": "턱", "count": 4, "damage": 126},
                        {"label": "오른쪽 관자놀이", "count": 2, "damage": 58},
                        {"label": "코", "count": 1, "damage": 18},
                        {"label": "명치", "count": 1, "damage": 16},
                    ],
                    "allHits": [
                        {"screenX": 0.58, "screenY": 0.50, "damage": 32, "weak": "턱", "punch": "스트레이트", "effect": "knockdown"},
                        {"screenX": 0.60, "screenY": 0.45, "damage": 22, "weak": "오른쪽 관자놀이", "punch": "훅", "effect": "hit"},
                        {"screenX": 0.57, "screenY": 0.41, "damage": 18, "weak": "코", "punch": "잽", "effect": "hit"},
                        {"screenX": 0.56, "screenY": 0.60, "damage": 16, "weak": "명치", "punch": "바디 잽", "effect": "hit"},
                        {"screenX": 0.55, "screenY": 0.53, "damage": 12, "weak": "", "punch": "잽", "effect": "hit"},
                        {"screenX": 0.62, "screenY": 0.54, "damage": 14, "weak": "", "punch": "스트레이트", "effect": "hit"},
                        {"screenX": 0.59, "screenY": 0.58, "damage": 9, "weak": "", "punch": "훅", "effect": "hit"},
                        {"screenX": 0.61, "screenY": 0.47, "damage": 11, "weak": "", "punch": "잽", "effect": "hit"},
                        {"screenX": 0.58, "screenY": 0.64, "damage": 8, "weak": "", "punch": "바디 훅", "effect": "hit"},
                    ],
                },
            }
            if bool(final):
                payload.update({
                    "isFinal": True,
                    "winner": "blue",
                    "winnerName": blue_name,
                    "leader": "blue",
                    "leaderName": blue_name,
                    "roundTag": "MATCH RESULT",
                    "summaryLine": f"{blue_name} 선수가 경기 승리를 가져갑니다.",
                    "displayMs": 20000,
                })

            info = {
                "match_text": "MATCH REPORT TEST" if bool(final) else "ROUND REPORT TEST",
                "recent_hit_text": "",
                "blue_recent_hit_text": "Straight 82\n턱",
                "red_recent_hit_text": "Hook 36\n명치",
                "blue_combo_hit_text": "",
                "blue_combo_damage_text": "",
                "red_combo_hit_text": "",
                "red_combo_damage_text": "",
                "blue_round_knockdowns": 1,
                "red_round_knockdowns": 0,
                "blue_punishment_mid": 42.0,
                "red_punishment_mid": 68.0,
                "blue_punishment_long": 18.0,
                "red_punishment_long": 44.0,
                "blue_punishment_text": "MID 42%  LONG 18%",
                "red_punishment_text": "MID 68%  LONG 44%",
            }
            update = {
                "blue_name": blue_name,
                "red_name": red_name,
                "round_current": round_no,
                "round_total": total_rounds,
                "seconds_left": int(getattr(self.cfg, "timer_rest_sec", 60) or 60),
                "spectator_rest_mode": True,
                "spectator_log_info": info,
                "blue_round_damage_dealt": float(payload["blue"].get("damage", 0) or 0),
                "red_round_damage_dealt": float(payload["red"].get("damage", 0) or 0),
                "spectator_round_report": payload,
            }
            emitted = self._emit_spectator_test_update(update)
            if not emitted:
                self._push_browser_overlay_event("round_report", **payload)
            self._noop_status("경기 종료 리포트 테스트 표시" if bool(final) else "라운드 리포트 테스트 표시")
        except Exception as e:
            logging.exception("SPECTATOR_ROUND_REPORT_TEST_FAIL")
            QMessageBox.warning(
                self,
                "경고",
                "경기 종료 리포트 테스트에 실패했습니다." if bool(final) else "라운드 리포트 테스트에 실패했습니다.",
            )

    def _test_spectator_full_demo(self):
        tw = self._spectator_timer_target()
        if tw is None:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return

        token = object()
        self._hud_demo_token = token
        logging.info("HUD_DEMO_START")
        self._noop_status("전체 HUD 데모 시작")
        try:
            tw._backend.set_hud_demo_running(True)
        except Exception:
            pass

        def active() -> bool:
            return getattr(self, "_hud_demo_token", None) is token

        def safe(delay_ms: int, fn):
            def _wrapped():
                if active():
                    fn()
            QTimer.singleShot(max(0, int(delay_ms)), _wrapped)

        def emit_info(info: dict, extra: Optional[dict] = None):
            self._test_set_spectator_info(dict(info or {}), dict(extra or {}))

        def emit_damage(info: dict, blue_total: float, red_total: float, side: str, attacker: str, punch: str, damage: float, weak: str = ""):
            payload = {
                "blue_round_damage_dealt": float(blue_total),
                "red_round_damage_dealt": float(red_total),
                "spectator_hit_effect_events": [{
                    "side": str(side),
                    "attacker_side": str(attacker),
                    "punch": str(punch),
                    "damage": float(damage),
                    "weak_point": str(weak or ""),
                }],
            }
            emit_info(info, payload)

        def emit_effect(side: str, kind: str, info: Optional[dict] = None):
            self._emit_spectator_test_update({
                "spectator_log_info": dict(info or {}),
                "spectator_effect_events": [{"side": str(side), "kind": str(kind)}],
            })

        try:
            tw.set_names("BLUE TEST", "RED TEST")
            tw.set_round_time(1, 3, 180)
            if hasattr(tw, "_backend"):
                tw._backend.reset_spectator_sp()
            tw.set_spectator_damage(0, 0)
            if hasattr(tw, "set_spectator_total_damage"):
                tw.set_spectator_total_damage(0, 0)
            if hasattr(tw, "request_round_intro"):
                safe(250, tw.request_round_intro)
            elif hasattr(tw, "_backend"):
                safe(250, tw._backend.request_round_intro)
            safe(250, lambda: self._push_browser_overlay_event("round_intro", round=1))
            safe(250, lambda: self._emit_spectator_test_update({"round_intro_event": {"round": 1}}))
            initial_info = {
                "match_text": "",
                "recent_hit_text": "",
                "blue_recent_hit_text": "",
                "red_recent_hit_text": "",
                "blue_combo_hit_text": "",
                "blue_combo_damage_text": "",
                "red_combo_hit_text": "",
                "red_combo_damage_text": "",
                "blue_punishment_mid": 0.0,
                "red_punishment_mid": 0.0,
                "blue_punishment_long": 0.0,
                "red_punishment_long": 0.0,
                "blue_round_knockdowns": 0,
                "red_round_knockdowns": 0,
            }
            tw.set_spectator_log_info(initial_info)
            emit_info(initial_info, {
                "blue_name": "BLUE TEST",
                "red_name": "RED TEST",
                "round_current": 1,
                "round_total": 3,
                "seconds_left": 180,
                "blue_round_damage_dealt": 0.0,
                "red_round_damage_dealt": 0.0,
                "blue_damage_dealt": 0.0,
                "red_damage_dealt": 0.0,
                "spectator_sp_reset": True,
                "spectator_match_stats_reset": True,
            })
            safe(1000, lambda: tw.set_spectator_damage(42, 18))
            safe(1000, lambda: hasattr(tw, "set_spectator_total_damage") and tw.set_spectator_total_damage(42, 18))
            safe(1000, lambda: tw.set_spectator_log_info({
                "blue_recent_hit_text": "Hit 18",
                "red_recent_hit_text": "",
                "blue_punishment_mid": 18.0,
                "red_punishment_mid": 8.0,
                "blue_punishment_long": 6.0,
                "red_punishment_long": 4.0,
            }))
            safe(1000, lambda: emit_damage({
                "blue_recent_hit_text": "Hit 18",
                "red_recent_hit_text": "",
                "blue_punishment_mid": 18.0,
                "red_punishment_mid": 8.0,
                "blue_punishment_long": 6.0,
                "red_punishment_long": 4.0,
            }, 42, 18, "red", "blue", "Hit", 42.0))
            safe(1100, lambda: tw.trigger_hit_impact("red", 42.0))
            safe(4200, lambda: self._test_spectator_combo("blue"))
            safe(7600, lambda: tw.set_spectator_damage(74, 61))
            safe(7600, lambda: hasattr(tw, "set_spectator_total_damage") and tw.set_spectator_total_damage(74, 61))
            safe(7600, lambda: tw.set_spectator_log_info({
                "red_recent_hit_text": "훅 43\n명치",
                "blue_punishment_mid": 34.0,
                "red_punishment_mid": 24.0,
                "blue_punishment_long": 12.0,
                "red_punishment_long": 10.0,
            }))
            safe(7600, lambda: emit_damage({
                "red_recent_hit_text": "훅 43\n명치",
                "blue_punishment_mid": 34.0,
                "red_punishment_mid": 24.0,
                "blue_punishment_long": 12.0,
                "red_punishment_long": 10.0,
            }, 74, 61, "blue", "red", "훅", 43.0, "명치"))
            safe(7700, lambda: tw.trigger_hit_impact("blue", 43.0))
            safe(10800, lambda: self._test_spectator_counter())
            safe(13500, lambda: self._test_spectator_combo("red"))
            safe(16500, lambda: tw.trigger_spectator_effect("red", "stun"))
            safe(16500, lambda: emit_effect("red", "stun"))
            safe(16500, lambda: bool(getattr(self.cfg, "spectator_commentary_enabled", False)) and self._speak_tts_test_qt("크게 흔들립니다!", role="analyst"))
            safe(19000, lambda: tw.set_spectator_damage(142, 109))
            safe(19000, lambda: hasattr(tw, "set_spectator_total_damage") and tw.set_spectator_total_damage(142, 109))
            safe(19000, lambda: tw.set_spectator_log_info({
                "blue_recent_hit_text": "Uppercut 68",
                "red_recent_hit_text": "",
                "blue_punishment_mid": 62.0,
                "red_punishment_mid": 74.0,
                "blue_punishment_long": 27.0,
                "red_punishment_long": 38.0,
                "red_round_knockdowns": 1,
            }))
            safe(19000, lambda: emit_damage({
                "blue_recent_hit_text": "Uppercut 68",
                "red_recent_hit_text": "",
                "blue_punishment_mid": 62.0,
                "red_punishment_mid": 74.0,
                "blue_punishment_long": 27.0,
                "red_punishment_long": 38.0,
                "red_round_knockdowns": 1,
            }, 142, 109, "red", "blue", "Uppercut", 68.0))
            safe(19100, lambda: tw.trigger_hit_impact("red", 68.0))
            safe(21500, lambda: tw.set_spectator_log_info({
                "red_round_knockdowns": 2,
                "red_punishment_mid": 88.0,
                "red_punishment_long": 55.0,
            }))
            safe(21500, lambda: emit_effect("red", "knockdown", {
                "red_round_knockdowns": 2,
                "red_punishment_mid": 88.0,
                "red_punishment_long": 55.0,
            }))
            safe(21500, lambda: tw.trigger_spectator_effect("red", "knockdown"))
            safe(21500, lambda: bool(getattr(self.cfg, "spectator_commentary_enabled", False)) and self._speak_tts_test_qt("레드 테스트, 다운 당합니다", role="caster"))
            safe(25500, lambda: tw.set_spectator_log_info({
                "red_round_knockdowns": 1,
                "blue_round_knockdowns": 1,
                "blue_punishment_mid": 80.0,
                "blue_punishment_long": 48.0,
            }))
            safe(25500, lambda: emit_info({
                "red_round_knockdowns": 1,
                "blue_round_knockdowns": 1,
                "blue_punishment_mid": 80.0,
                "blue_punishment_long": 48.0,
            }))
            safe(25600, lambda: emit_effect("blue", "knockdown"))
            safe(25600, lambda: tw.trigger_spectator_effect("blue", "knockdown"))
            safe(25600, lambda: bool(getattr(self.cfg, "spectator_commentary_enabled", False)) and self._speak_tts_test_qt("블루 테스트, 다운 당합니다", role="caster"))
            safe(30000, lambda: tw.set_spectator_log_info({
                "blue_round_knockdowns": 0,
                "red_round_knockdowns": 0,
                "blue_combo_hit_text": "",
                "blue_combo_damage_text": "",
                "red_combo_hit_text": "",
                "red_combo_damage_text": "",
            }))
            safe(30000, lambda: emit_info({
                "blue_round_knockdowns": 0,
                "red_round_knockdowns": 0,
                "blue_combo_hit_text": "",
                "blue_combo_damage_text": "",
                "red_combo_hit_text": "",
                "red_combo_damage_text": "",
            }))
            safe(30050, lambda: tw._backend.set_hud_demo_running(False))
            safe(30050, lambda: setattr(self, "_hud_demo_token", None))
            safe(30050, lambda: logging.info("HUD_DEMO_DONE"))
        except Exception as e:
            try:
                tw._backend.set_hud_demo_running(False)
            except Exception:
                pass
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")

    def _stop_spectator_hud_demo(self):
        self._spectator_replay_token = None
        self._spectator_replay_state = None
        self._hud_demo_token = None
        tw = self._spectator_timer_target()
        if tw is not None:
            try:
                tw._backend.set_hud_demo_running(False)
                clear_info = {
                    "blue_combo_hit_text": "",
                    "blue_combo_damage_text": "",
                    "red_combo_hit_text": "",
                    "red_combo_damage_text": "",
                }
                tw.set_spectator_log_info(clear_info)
                self._test_set_spectator_info(clear_info)
            except Exception:
                pass
        self._noop_status("HUD \uB370\uBAA8/\uD14C\uC2A4\uD2B8 \uC0C1\uD0DC \uCD08\uAE30\uD654 \uC644\uB8CC")

    def _stop_spectator_commentary_test_script(self):
        self._commentary_test_script_token = None
        try:
            self._commentary_test_script_queue.clear()
        except Exception:
            self._commentary_test_script_queue = deque()
        try:
            for role, player in (getattr(self, "_tts_test_players", {}) or {}).items():
                try:
                    player.stop()
                except Exception:
                    pass
                self._tts_test_busy[str(role)] = False
            old_files = []
            for role in ("analyst", "caster"):
                old_files.extend(list((getattr(self, "_tts_test_files", {}) or {}).get(role, []) or []))
                self._tts_test_files[role] = []
            for path in old_files:
                try:
                    os.remove(path)
                except Exception:
                    pass
        except Exception:
            pass
        self._noop_status("자동해설 테스트 중지")

    def _start_spectator_commentary_script(self, name: str, steps: List[dict]):
        try:
            self.apply_only(silent=True)
        except Exception:
            pass
        self._stop_spectator_commentary_test_script()
        token = object()
        self._commentary_test_script_token = token
        self._commentary_test_script_name = str(name or "자동해설 테스트")
        self._commentary_test_script_queue = deque(list(steps or []))
        self._noop_status(f"{self._commentary_test_script_name} 시작")
        QTimer.singleShot(0, lambda t=token: self._run_next_spectator_commentary_script_step(t))


    def _schedule_tts_test_followup(self, text: str, role: str = "analyst", delay_ms: int = 1050, token=None):
        text = str(text or "").strip()
        if not text:
            return
        role = "caster" if str(role or "").lower() == "caster" else "analyst"
        try:
            delay_ms = max(0, min(8000, int(delay_ms or 1050)))
        except Exception:
            delay_ms = 1050

        def _attempt(remaining: int = 4):
            try:
                if token is not None and getattr(self, "_commentary_test_script_token", None) is not token:
                    logging.info("TTS_TEST_FOLLOWUP_CANCELLED role=%s text=%s", role, text)
                    return
                # 듀오 테스트도 실제 자동해설처럼 역할별 독립 재생한다.
                # 캐스터가 아직 말하고 있어도 해설자 후속 멘트는 별도 플레이어로 들어간다.
                if bool((getattr(self, "_tts_test_busy", {}) or {}).get(role, False)):
                    if remaining > 0:
                        QTimer.singleShot(260, lambda r=remaining - 1: _attempt(r))
                    else:
                        logging.info("TTS_TEST_FOLLOWUP_SKIP_BUSY role=%s text=%s", role, text)
                    return
                self._speak_tts_test_qt(text, role=role)
                logging.info("TTS_TEST_DUO_FOLLOWUP role=%s text=%s", role, text)
            except Exception:
                logging.exception("TTS_TEST_DUO_FOLLOWUP_FAIL")

        QTimer.singleShot(delay_ms, lambda: _attempt(4))

    def _run_next_spectator_commentary_script_step(self, token):
        if getattr(self, "_commentary_test_script_token", None) is not token:
            return
        try:
            if bool((getattr(self, "_tts_test_busy", {}) or {}).get("caster", False)) or bool((getattr(self, "_tts_test_busy", {}) or {}).get("analyst", False)):
                QTimer.singleShot(180, lambda t=token: self._run_next_spectator_commentary_script_step(t))
                return
            if not self._commentary_test_script_queue:
                name = str(getattr(self, "_commentary_test_script_name", "자동해설 테스트") or "자동해설 테스트")
                self._commentary_test_script_token = None
                self._noop_status(f"{name} 완료")
                return
            step = dict(self._commentary_test_script_queue.popleft() or {})
            text = str(step.get("text", "") or "").strip()
            role = "caster" if str(step.get("role", "analyst") or "analyst").lower() == "caster" else "analyst"
            post_ms = int(step.get("post_ms", 900) or 900)
            rate_override = step.get("rate_override", None)
            pitch_override = step.get("pitch_override", None)
            action = step.get("action", None)
            if callable(action):
                try:
                    action()
                except Exception:
                    logging.exception("COMMENTARY_SCRIPT_TEST_ACTION_FAIL")
            if text:
                self._speak_tts_test_qt(text, role=role, rate_override=rate_override, pitch_override=pitch_override)
            follow_text = str(step.get("followup_text", "") or step.get("duo_text", "") or "").strip()
            if follow_text:
                try:
                    follow_delay = int(step.get("followup_delay_ms", step.get("duo_delay_ms", 1050)) or 1050)
                except Exception:
                    follow_delay = 1050
                follow_role = str(step.get("followup_role", "analyst") or "analyst")
                self._schedule_tts_test_followup(follow_text, role=follow_role, delay_ms=follow_delay, token=token)
            QTimer.singleShot(max(180, post_ms), lambda t=token: self._run_next_spectator_commentary_script_step(t))
        except Exception:
            logging.exception("COMMENTARY_SCRIPT_TEST_STEP_FAIL")
            self._commentary_test_script_token = None
            self._noop_status("자동해설 테스트 실패")

    def _test_spectator_commentary_full_suite(self):
        steps = [
            {"role": "caster", "text": "RFC 자동해설 종합 테스트 시작합니다.", "post_ms": 900},
            {"role": "caster", "text": "경기 시작합니다!", "post_ms": 700},
            {"role": "analyst", "text": "초반은 거리 싸움부터 봐야 합니다.", "post_ms": 900},
            {"role": "caster", "text": "눈치게임입니다.", "followup_text": "둘 다 먼저 가긴 싫죠.", "followup_delay_ms": 950, "post_ms": 650},
            {"role": "caster", "text": "앞손 싸움입니다.", "followup_text": "앞손이 오늘 바쁩니다.", "followup_delay_ms": 950, "post_ms": 650},
            {"role": "analyst", "text": "카운터가 정확합니다.", "post_ms": 800},
            {"role": "analyst", "text": "데미지가 쌓이고 있습니다.", "post_ms": 850},
            {"role": "caster", "text": "다니엘, 다운입니다!", "post_ms": 700},
            {"role": "analyst", "text": "충격이 큽니다.", "post_ms": 650},
            {"role": "analyst", "text": "버텨야 합니다.", "post_ms": 650},
            {"role": "caster", "text": "경기 계속됩니다!", "post_ms": 700},
            {"role": "caster", "text": "라운드 종료, 휴식 시간입니다.", "post_ms": 850},
            {"role": "analyst", "text": "네리가 이번 라운드 유효타에서 앞섰습니다.", "post_ms": 1000},
            {"role": "analyst", "text": "후반에는 압박이 살아났고, 받은 데미지도 쌓였습니다.", "post_ms": 1100},
            {"role": "analyst", "text": "다음 라운드는 초반 수비 정리가 중요합니다.", "post_ms": 1000},
            {"role": "caster", "text": "경기 종료됩니다!", "post_ms": 700},
            {"role": "analyst", "text": "스코어카드 기준으로는 네리가 앞선 경기였습니다.", "post_ms": 1000},
            {"role": "analyst", "text": "자동해설 종합 테스트 완료입니다.", "post_ms": 700},
        ]
        self._start_spectator_commentary_script("자동해설 종합 테스트", steps)


    def _test_spectator_commentary_duo_suite(self):
        steps = [
            {"role": "caster", "text": "듀오 해설 테스트 시작합니다.", "post_ms": 800},
            {"role": "caster", "text": "잠시 소강상태입니다.", "followup_text": "둘 다 먼저 가긴 싫죠.", "followup_delay_ms": 950, "post_ms": 700},
            {"role": "caster", "text": "눈치게임입니다.", "followup_text": "서로 오라고만 합니다.", "followup_delay_ms": 900, "post_ms": 700},
            {"role": "caster", "text": "앞손 싸움입니다.", "followup_text": "앞손이 오늘 바쁩니다.", "followup_delay_ms": 900, "post_ms": 700},
            {"role": "caster", "text": "크게 휘둘렀지만 빗나갑니다.", "followup_text": "폼은 멋졌습니다.", "followup_delay_ms": 950, "post_ms": 850},
            {"role": "caster", "text": "라운드 막판입니다.", "followup_text": "막판엔 한 방입니다.", "followup_delay_ms": 900, "post_ms": 750},
            {"role": "caster", "text": "위험 상황은 드립 없이 갑니다.", "post_ms": 800},
            {"role": "caster", "text": "다니엘, 다운입니다!", "post_ms": 650},
            {"role": "analyst", "text": "충격이 큽니다.", "post_ms": 700},
            {"role": "caster", "text": "듀오 해설 테스트 완료입니다.", "post_ms": 700},
        ]
        self._start_spectator_commentary_script("듀오 해설 테스트", steps)

    def _test_spectator_commentary_down_suite(self):
        steps = [
            {"role": "caster", "text": "다운 멘트 테스트 시작합니다.", "post_ms": 800},
            {"role": "caster", "text": "다니엘, 다운입니다!", "post_ms": 650},
            {"role": "analyst", "text": "충격이 큽니다.", "post_ms": 600},
            {"role": "analyst", "text": "아직 끝난 건 아닙니다.", "post_ms": 750},
            {"role": "caster", "text": "경기 계속됩니다!", "post_ms": 750},
            {"role": "caster", "text": "다니엘, 다시 다운입니다!", "post_ms": 650},
            {"role": "analyst", "text": "이건 정말 큽니다.", "post_ms": 600},
            {"role": "analyst", "text": "수비가 먼저입니다.", "post_ms": 700},
            {"role": "caster", "text": "다시 일어납니다!", "post_ms": 700},
            {"role": "caster", "text": "다니엘, 세 번째 다운입니다!", "post_ms": 650},
            {"role": "caster", "text": "여기서 멈춥니다!", "post_ms": 650},
            {"role": "caster", "text": "경기 종료됩니다!", "post_ms": 700},
            {"role": "analyst", "text": "승부가 갈렸습니다.", "post_ms": 700},
        ]
        self._start_spectator_commentary_script("다운 멘트 테스트", steps)

    def _test_spectator_commentary_summary_suite(self):
        steps = [
            {"role": "caster", "text": "요약 멘트 테스트 시작합니다.", "post_ms": 800},
            {"role": "caster", "text": "라운드 종료, 휴식 시간입니다.", "post_ms": 850},
            {"role": "analyst", "text": "다니엘이 이번 라운드 초반 유효타에서 앞섰습니다.", "post_ms": 1050},
            {"role": "analyst", "text": "중반 이후에는 네리의 압박이 살아났습니다.", "post_ms": 1000},
            {"role": "analyst", "text": "바디 데미지가 쌓인 건 다음 라운드에도 영향을 줄 수 있습니다.", "post_ms": 1100},
            {"role": "analyst", "text": "눈치싸움이 길었지만, 점수에 남을 장면은 있었습니다.", "post_ms": 1100},
            {"role": "analyst", "text": "다음 라운드는 첫 교전이 중요합니다.", "post_ms": 950},
            {"role": "caster", "text": "경기 종료됩니다!", "post_ms": 750},
            {"role": "analyst", "text": "스코어카드 기준으로는 접전이었습니다.", "post_ms": 950},
            {"role": "analyst", "text": "후반 정타와 다운 장면이 승부를 갈랐습니다.", "post_ms": 1000},
            {"role": "analyst", "text": "요약 멘트 테스트 완료입니다.", "post_ms": 700},
        ]
        self._start_spectator_commentary_script("요약 멘트 테스트", steps)

    def _test_spectator_commentary_tts(self):
        try:
            self.apply_only(silent=True)
        except Exception:
            pass
        self._speak_tts_test_qt("정타가 들어갑니다.", role="analyst")
        QTimer.singleShot(900, lambda: self._speak_tts_test_qt("다니엘, 다운입니다!", role="caster"))

    def _fill_edge_voice_combo(self, combo: QComboBox):
        combo.addItem("한국어 여성 - SunHi", "ko-KR-SunHiNeural")
        combo.addItem("한국어 남성 - InJoon", "ko-KR-InJoonNeural")
        combo.addItem("영어 남성 - Guy", "en-US-GuyNeural")
        combo.addItem("영어 여성 - Jenny", "en-US-JennyNeural")

    def _commentary_tts_voice(self, role: str = "analyst") -> str:
        if str(role or "").lower() == "caster":
            if hasattr(self, "cmb_spectator_caster_voice"):
                return str(self.cmb_spectator_caster_voice.currentData() or "ko-KR-InJoonNeural")
            return str(getattr(self.cfg, "spectator_caster_voice", "ko-KR-InJoonNeural") or "ko-KR-InJoonNeural")
        if hasattr(self, "cmb_spectator_commentary_voice"):
            return str(self.cmb_spectator_commentary_voice.currentData() or "ko-KR-SunHiNeural")
        return str(getattr(self.cfg, "spectator_commentary_voice", "ko-KR-SunHiNeural") or "ko-KR-SunHiNeural")

    def _commentary_tts_rate(self) -> int:
        try:
            if hasattr(self, "sp_spectator_commentary_rate"):
                return int(self.sp_spectator_commentary_rate.value())
            return int(getattr(self.cfg, "spectator_commentary_rate", 200) or 200)
        except Exception:
            return 200

    def _commentary_tts_volume(self) -> float:
        try:
            if hasattr(self, "sp_spectator_commentary_volume"):
                return float(self.sp_spectator_commentary_volume.value())
            return float(getattr(self.cfg, "spectator_commentary_volume", 100.0) or 100.0)
        except Exception:
            return 100.0

    def _commentary_tts_pitch(self) -> int:
        try:
            if hasattr(self, "sp_spectator_commentary_pitch"):
                return int(self.sp_spectator_commentary_pitch.value())
            return int(getattr(self.cfg, "spectator_commentary_pitch", 0) or 0)
        except Exception:
            return 0

    def _speak_tts_test_qt(self, text: str, role: str = "analyst", rate_override: Optional[int] = None, pitch_override: Optional[int] = None):
        role = "caster" if str(role or "").lower() == "caster" else "analyst"
        self._ensure_tts_test_player(role)
        player = (getattr(self, "_tts_test_players", {}) or {}).get(role)
        audio_out = (getattr(self, "_tts_test_audio_outs", {}) or {}).get(role)
        if bool((getattr(self, "_tts_test_busy", {}) or {}).get(role, False)):
            logging.info("TTS_TEST_SKIP_BUSY role=%s text=%s", role, text)
            return
        if not HAS_QTMULTIMEDIA or player is None or audio_out is None:
            try:
                logging.warning("TTS_TEST_QT_UNAVAILABLE")
            except Exception:
                pass
            rate = self._commentary_tts_rate()
            if rate_override is not None:
                try:
                    rate = max(80, min(320, int(rate_override)))
                except Exception:
                    rate = 200
            self.action_runner.speak_text(text, rate=rate, volume=self._commentary_tts_volume(), voice_mode=self._commentary_tts_voice(role))
            self._noop_status("자동해설 TTS 테스트 재생 요청")
            return
        self._tts_test_busy[role] = True

        def _worker():
            media_path = ""
            try:
                if not self.action_runner._ensure_tts_ready():
                    QMetaObject.invokeMethod(
                        self,
                        "_clear_tts_test_busy",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, role),
                    )
                    QMetaObject.invokeMethod(
                        self,
                        "_show_tts_test_error",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, "edge-tts를 사용할 수 없습니다. pip install edge-tts 확인 필요"),
                    )
                    return
                fd, media_path = tempfile.mkstemp(prefix="timerauto_tts_test_", suffix=".mp3")
                os.close(fd)
                voice = self._commentary_tts_voice(role)
                rate = self._commentary_tts_rate()
                pitch = self._commentary_tts_pitch()
                if rate_override is not None:
                    try:
                        rate = max(80, min(320, int(rate_override)))
                    except Exception:
                        rate = 200
                if pitch_override is not None:
                    try:
                        pitch = max(-100, min(100, int(pitch_override)))
                    except Exception:
                        pitch = 0
                ok = self.action_runner._edge_save_cli(
                    str(text or ""),
                    media_path,
                    voice,
                    self.action_runner._edge_rate(rate),
                    self.action_runner._edge_volume(self._commentary_tts_volume()),
                    self.action_runner._edge_pitch(pitch),
                )
                if not ok:
                    try:
                        os.remove(media_path)
                    except Exception:
                        pass
                    QMetaObject.invokeMethod(
                        self,
                        "_clear_tts_test_busy",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, role),
                    )
                    QMetaObject.invokeMethod(
                        self,
                        "_show_tts_test_error",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, "Edge TTS 음성 파일 생성 실패"),
                    )
                    return
                QMetaObject.invokeMethod(
                    self,
                    "_play_tts_test_file",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, role),
                    Q_ARG(str, media_path),
                )
            except Exception as e:
                if media_path:
                    try:
                        os.remove(media_path)
                    except Exception:
                        pass
                QMetaObject.invokeMethod(
                    self,
                    "_clear_tts_test_busy",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, role),
                )
                QMetaObject.invokeMethod(
                    self,
                    "_show_tts_test_error",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, str(e)),
                )

        threading.Thread(target=_worker, daemon=True).start()
        self._noop_status("자동해설 TTS 생성 중...")

    @pyqtSlot(str, str)
    def _play_tts_test_file(self, role: str, media_path: str):
        try:
            role = "caster" if str(role or "").lower() == "caster" else "analyst"
            path = os.path.abspath(str(media_path or ""))
            if not os.path.isfile(path):
                self._tts_test_busy[role] = False
                self._show_tts_test_error("TTS 파일이 없습니다.")
                return
            player = (getattr(self, "_tts_test_players", {}) or {}).get(role)
            audio_out = (getattr(self, "_tts_test_audio_outs", {}) or {}).get(role)
            if player is None or audio_out is None:
                self._tts_test_busy[role] = False
                return
            self._tts_test_files.setdefault(role, []).append(path)
            player.setSource(QUrl.fromLocalFile(path))
            audio_out.setVolume(max(0.0, min(1.0, self._commentary_tts_volume() / 100.0)))
            player.play()
            logging.info("TTS_TEST_QT_PLAY role=%s path=%s", role, path)
            self._noop_status("자동해설 TTS 테스트 재생")
        except Exception as e:
            try:
                self._tts_test_busy[role] = False
            except Exception:
                pass
            QMessageBox.warning(self, "경고", "TTS 테스트 재생에 실패했습니다.")

    def _on_tts_test_media_status(self, role: str, status):
        try:
            role = "caster" if str(role or "").lower() == "caster" else "analyst"
            if QMediaPlayer is None:
                return
            if status in (
                QMediaPlayer.MediaStatus.EndOfMedia,
                QMediaPlayer.MediaStatus.InvalidMedia,
            ):
                old = list((getattr(self, "_tts_test_files", {}) or {}).get(role, []) or [])
                self._tts_test_files[role] = []
                for path in old:
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                self._tts_test_busy[role] = False
        except Exception:
            pass

    @pyqtSlot(str)
    def _clear_tts_test_busy(self, role: str):
        try:
            role = "caster" if str(role or "").lower() == "caster" else "analyst"
            self._tts_test_busy[role] = False
        except Exception:
            pass

    @pyqtSlot(str)
    def _show_tts_test_error(self, message: str):
        msg = str(message or "알 수 없는 오류")
        try:
            logging.warning("TTS_TEST_FAIL %s", msg)
        except Exception:
            pass
        QMessageBox.warning(self, "자동해설 TTS 테스트 실패", msg)

    def _test_spectator_last_log(self):
        tw = self._spectator_timer_target()
        if tw is None:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return
        try:
            self.apply_only(silent=True)
        except Exception:
            pass
        root = resolve_spectatorlog_path(str(getattr(self.cfg, "spectatorlog_path", "") or ""))
        path = os.path.join(root, "match", "damage_events.txt")
        if not os.path.exists(path):
            candidates = []
            for base in (
                os.path.join(os.path.expanduser("~"), "Documents", "ThrillOfTheFight2", "SpectatorLog", "match", "damage_events.txt"),
                os.path.join(os.path.expanduser("~"), "Downloads", "ThrillOfTheFight2", "SpectatorLog", "match", "damage_events.txt"),
            ):
                try:
                    if os.path.exists(base):
                        candidates.append(base)
                except Exception:
                    pass
            if candidates:
                path = max(candidates, key=lambda p: os.path.getmtime(p))
                root = os.path.dirname(os.path.dirname(path))
                logging.info("SPECTATOR_REPLAY_FALLBACK_PATH path=%s", path)
            else:
                msg = f"과거 로그 리플레이 실패: damage_events.txt를 찾지 못했습니다.\n확인 경로: {path}"
                logging.warning("SPECTATOR_REPLAY_NO_DAMAGE_FILE path=%s", path)
                QMessageBox.information(self, "과거 로그 리플레이", msg)
                self._noop_status("과거 로그 리플레이 실패: 로그 파일 없음")
                return
        try:
            with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                lines = f.readlines()
        except Exception as e:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return
        events = []
        for line in lines:
            parts = str(line or "").strip().split("\t")
            if len(parts) < 10:
                continue
            try:
                damage = float(parts[1])
            except Exception:
                continue
            corner = str(parts[2] or "").strip().lower()
            if corner == "red":
                attacker = "BLUE"
                attacker_side = "blue"
            elif corner == "blue":
                attacker = "RED"
                attacker_side = "red"
            else:
                continue
            try:
                t = float(parts[0])
            except Exception:
                t = 0.0
            events.append({
                "time": t,
                "attacker": attacker,
                "attacker_side": attacker_side,
                "receiver": corner.upper(),
                "receiver_side": corner,
                "damage": damage,
                "punch": str(parts[8] or "").strip(),
                "damage_type": str(parts[9] or "").strip(),
                "weak_point": str(parts[10] or "").strip() if len(parts) > 10 else "",
            })
        if not events:
            logging.warning("SPECTATOR_REPLAY_NO_EVENTS path=%s line_count=%s", path, len(lines))
            QMessageBox.information(self, "과거 로그 리플레이", f"damage_events.txt는 찾았지만 재생 가능한 타격 이벤트가 없습니다.\n경로: {path}")
            self._noop_status("과거 로그 리플레이 실패: 이벤트 없음")
            return
        browser_output_only = bool(getattr(self.cfg, "browser_overlay_output_only", True))
        helper = _make_spectator_log_watcher(self.cfg)
        try:
            replay_round_no = int(float(helper._read_text(os.path.join(root, "match", "round_number.txt")) or "1"))
        except Exception:
            replay_round_no = 1
        replay_state_raw = helper._read_text(os.path.join(root, "match", "round_state.txt"))
        replay_round_state = helper._normalize_round_state(replay_state_raw) or "fight"
        replay_total_rounds = int(getattr(self.cfg, "timer_total_rounds", 3) or 3)
        try:
            self._load_spectatorlog_players_for_test(tw)
        except Exception:
            logging.exception("SPECTATOR_REPLAY_PROFILE_LOAD_FAIL")
        try:
            if hasattr(tw, "_backend"):
                tw._backend.reset_spectator_sp()
        except Exception:
            pass
        replay_state = {
            "idx": 0,
            "blue_dealt": 0.0,
            "red_dealt": 0.0,
            "round_no": replay_round_no,
            "round_state": replay_round_state,
            "last_fight_seconds": None,
            "combo": {
                "attacker_side": "",
                "receiver_side": "",
                "last_time": None,
                "count": 0,
                "damage": 0.0,
            },
            "last_counter_event": None,
            "token": time.time(),
        }
        self._spectator_replay_token = replay_state["token"]
        self._spectator_replay_state = replay_state
        try:
            tw._backend.set_hud_demo_running(True)
        except Exception:
            pass
        if bool(getattr(self.cfg, "spectator_commentary_enabled", False)):
            try:
                self._speak_tts_test_qt(helper._build_vs_caster_text(), role="caster", rate_override=200, pitch_override=0)
                QTimer.singleShot(
                    1200,
                    lambda: getattr(self, "_spectator_replay_token", None) == replay_state["token"]
                    and self._speak_tts_test_qt(
                        helper._round_caster_text("start", replay_round_no, replay_total_rounds),
                        role="caster",
                    ),
                )
            except Exception:
                logging.exception("SPECTATOR_REPLAY_CASTER_INTRO_FAIL")
        try:
            replay_speed = float(getattr(self.cfg, "spectator_replay_speed", 1.0) or 1.0)
        except Exception:
            replay_speed = 1.0
        replay_speed = max(0.1, min(20.0, replay_speed))
        replay_real_time = bool(getattr(self.cfg, "spectator_replay_real_time", False))
        replay_mode_text = "실제 시간" if replay_real_time else "압축"
        self._noop_status(f"과거 로그 리플레이 시작: {len(events)}개 이벤트 / {replay_speed:.1f}배속 / {replay_mode_text}")

        def _event_gap_ms(cur_idx: int) -> int:
            if cur_idx <= 0 or cur_idx >= len(events):
                return 0
            prev_t = float(events[cur_idx - 1].get("time", 0.0) or 0.0)
            cur_t = float(events[cur_idx].get("time", 0.0) or 0.0)
            gap = abs(cur_t - prev_t)
            ms = int((gap / replay_speed) * 1000.0)
            if replay_real_time:
                return max(0, ms)
            return max(60, min(2500, ms))

        def _apply_replay_timer(ev: dict):
            try:
                state = str(replay_state.get("round_state") or "fight")
                ev_seconds = int(max(0.0, float((ev or {}).get("time", 0.0) or 0.0)))
                if state == "break":
                    shown = ev_seconds
                    rest = True
                    mode = "break_rest"
                elif state in ("knockdown", "foul", "results", "cancel", "intro", "end"):
                    shown = replay_state.get("last_fight_seconds")
                    if shown is None:
                        shown = ev_seconds
                    rest = False
                    mode = f"{state}_hold"
                else:
                    shown = ev_seconds
                    replay_state["last_fight_seconds"] = int(shown)
                    rest = False
                    mode = "fight_sync"
                replay_state["current_seconds_left"] = int(shown)
                replay_state["current_rest_mode"] = bool(rest)
                tw.set_log_rest_mode(bool(rest))
                tw.set_round_time(int(replay_state.get("round_no") or 1), replay_total_rounds, int(shown))
                logging.info(
                    "SPECTATOR_REPLAY_TIMER state=%s mode=%s round=%s seconds_left=%s",
                    state,
                    mode,
                    int(replay_state.get("round_no") or 1),
                    int(shown),
                )
            except Exception:
                logging.exception("SPECTATOR_REPLAY_TIMER_FAIL")

        def _step():
            if getattr(self, "_spectator_replay_state", None) is not replay_state:
                return
            idx = int(replay_state["idx"])
            if idx >= len(events):
                self._noop_status("과거 로그 리플레이 완료")
                self._spectator_replay_token = None
                self._spectator_replay_state = None
                try:
                    tw._backend.set_hud_demo_running(False)
                except Exception:
                    pass
                return
            ev = events[idx]
            _apply_replay_timer(ev)
            receiver_side = str(ev.get("receiver_side") or "")
            damage = float(ev.get("damage", 0.0) or 0.0)
            if receiver_side == "red":
                replay_state["blue_dealt"] += damage
            elif receiver_side == "blue":
                replay_state["red_dealt"] += damage

            kind = helper._damage_effect_kind(str(ev.get("damage_type", "") or ""))
            attacker_side = "red" if receiver_side == "blue" else "blue"
            attacker_name = helper._commentary_name(attacker_side)
            recent = helper._format_recent_hit_text(ev)
            try:
                combo_info: Dict[str, str] = {}
                combo_state = dict(replay_state.get("combo") or {})
                combo_min_damage = 15.0
                combo_break_damage = 20.0
                combo_gap = 0.8
                counter_prev_damage = COUNTER_PREV_DAMAGE_THRESHOLD
                counter_damage = COUNTER_DEALT_DAMAGE_THRESHOLD
                counter_window = COUNTER_WINDOW_SEC
                ev_time = float(ev.get("time", 0.0) or 0.0)
                last_counter_event = dict(replay_state.get("last_counter_event") or {})
                counter_hit = False
                try:
                    prev_t = float(last_counter_event.get("time", -9999.0))
                    prev_dmg = float(last_counter_event.get("damage", 0.0) or 0.0)
                except Exception:
                    prev_t = -9999.0
                    prev_dmg = 0.0
                if (
                    str(last_counter_event.get("attacker_side") or "").lower() == receiver_side
                    and str(last_counter_event.get("receiver_side") or "").lower() == attacker_side
                    and prev_dmg >= counter_prev_damage
                    and damage >= counter_damage
                    and 0.0 <= (ev_time - prev_t) <= counter_window
                ):
                    counter_hit = True
                active_attacker = str(combo_state.get("attacker_side") or "")
                active_receiver = str(combo_state.get("receiver_side") or "")
                if (
                    active_attacker in ("blue", "red")
                    and active_receiver in ("blue", "red")
                    and attacker_side == active_receiver
                    and receiver_side == active_attacker
                    and damage < combo_break_damage
                ):
                    replay_state["last_counter_event"] = dict(ev)
                else:
                    if (
                        active_attacker in ("blue", "red")
                        and active_receiver in ("blue", "red")
                        and attacker_side == active_receiver
                        and receiver_side == active_attacker
                        and damage >= combo_break_damage
                    ):
                        combo_info[f"{active_attacker}_combo_hit_text"] = ""
                        combo_info[f"{active_attacker}_combo_damage_text"] = ""
                        combo_state = {"attacker_side": "", "receiver_side": "", "last_time": None, "count": 0, "damage": 0.0}
                    if damage >= combo_min_damage:
                        last_time = combo_state.get("last_time", None)
                        same_chain = (
                            combo_state.get("attacker_side") == attacker_side
                            and combo_state.get("receiver_side") == receiver_side
                            and last_time is not None
                            and abs(ev_time - float(last_time or 0.0)) <= combo_gap
                        )
                        if same_chain:
                            prev_count = int(combo_state.get("count", 0) or 0)
                            combo_count = int(combo_state.get("count", 0) or 0) + 1
                            combo_damage = float(combo_state.get("damage", 0.0) or 0.0) + damage
                        else:
                            prev_count = 0
                            old_attacker = str(combo_state.get("attacker_side") or "")
                            if old_attacker in ("blue", "red") and int(combo_state.get("count", 0) or 0) >= 2:
                                combo_info[f"{old_attacker}_combo_hit_text"] = ""
                                combo_info[f"{old_attacker}_combo_damage_text"] = ""
                            combo_count = 1
                            combo_damage = damage
                        combo_state = {
                            "attacker_side": attacker_side,
                            "receiver_side": receiver_side,
                            "last_time": ev_time,
                            "count": combo_count,
                            "damage": combo_damage,
                        }
                        if combo_count >= 2:
                            combo_info[f"{attacker_side}_combo_hit_text"] = f"{combo_count} HIT COMBO"
                            combo_info[f"{attacker_side}_combo_damage_text"] = f"{int(round(combo_damage))} DAMAGE"
                            if prev_count < 2:
                                combo_info["_combo_commentary_text"] = "좋은 콤보가 적중합니다"
                    if counter_hit:
                        combo_info[f"{attacker_side}_combo_hit_text"] = "COUNTER"
                        combo_info[f"{attacker_side}_combo_damage_text"] = f"{int(round(damage))} DAMAGE"
                    replay_state["last_counter_event"] = dict(ev)
                replay_state["combo"] = combo_state
                log_info = {
                    "match_text": "",
                    "recent_hit_text": "",
                    "blue_recent_hit_text": recent if attacker_side == "blue" else "",
                    "red_recent_hit_text": recent if attacker_side == "red" else "",
                }
                log_info.update(combo_info)
                tw.set_spectator_total_damage(replay_state["blue_dealt"], replay_state["red_dealt"])
                tw.set_spectator_damage(replay_state["blue_dealt"], replay_state["red_dealt"])
                tw.set_spectator_log_info(log_info)
                replay_payload = {
                    "round_current": int(replay_state.get("round_no") or 1),
                    "round_total": int(replay_total_rounds),
                    "seconds_left": int(replay_state.get("current_seconds_left", 0) or 0),
                    "spectator_rest_mode": bool(replay_state.get("current_rest_mode", False)),
                    "blue_round_damage_dealt": replay_state["blue_dealt"],
                    "red_round_damage_dealt": replay_state["red_dealt"],
                    "blue_damage_dealt": replay_state["blue_dealt"],
                    "red_damage_dealt": replay_state["red_dealt"],
                    "spectator_hit_effect_events": [{
                        "side": receiver_side,
                        "attacker_side": attacker_side,
                        "punch": str(ev.get("punch") or "Hit"),
                        "damage": damage,
                        "weak_point": str(ev.get("weak_point") or ""),
                        "effect_kind": kind,
                    }],
                }
                if kind:
                    replay_payload["spectator_effect_events"] = [{"side": receiver_side, "kind": kind}]
                emitted = self._test_set_spectator_info(log_info, replay_payload)
                if kind:
                    if not browser_output_only:
                        tw.trigger_spectator_effect(receiver_side, kind)
                    if not emitted:
                        self._play_spectator_sfx(kind, show_warning=False)
                try:
                    hit_threshold = max(0.0, float(getattr(self.cfg, "spectator_hit_effect_damage", 45.0) or 45.0))
                except Exception:
                    hit_threshold = 45.0
                if (not browser_output_only) and hit_threshold > 0 and receiver_side in ("blue", "red") and damage >= hit_threshold and kind != "stun":
                    tw.trigger_hit_impact(receiver_side, damage)
                if counter_hit:
                    self._push_browser_overlay_event("counter", side=attacker_side, damage=damage)
                ev_for_summary = dict(ev)
                ev_for_summary["seen_at"] = time.time()
                ev_for_summary["effect_kind"] = kind
                helper._recent_damage_events.append(ev_for_summary)
                effect_events = [{"side": receiver_side, "kind": kind}] if kind else []
                if counter_hit and bool(getattr(self.cfg, "spectator_commentary_enabled", False)):
                    self._speak_tts_test_qt("카운터가 적중됩니다!", role="analyst")
                else_combo_text = str(combo_info.pop("_combo_commentary_text", "") or "").strip()
                if not counter_hit and else_combo_text and bool(getattr(self.cfg, "spectator_commentary_enabled", False)):
                    self._speak_tts_test_qt(else_combo_text, role="analyst")
                elif not counter_hit:
                    commentary, role = helper._build_fight_summary_commentary([ev_for_summary], effect_events, path)
                    if commentary and bool(getattr(self.cfg, "spectator_commentary_enabled", False)):
                        self._speak_tts_test_qt(commentary, role=role)
            except Exception as e:
                self._spectator_replay_token = None
                self._spectator_replay_state = None
                try:
                    tw._backend.set_hud_demo_running(False)
                except Exception:
                    pass
                QMessageBox.warning(self, "경고", "설정을 확인하세요.")
                return
            replay_state["idx"] = idx + 1
            if replay_state["idx"] < len(events):
                QTimer.singleShot(_event_gap_ms(replay_state["idx"]), _step)

        _step()

    def _clear_spectator_damage(self):
        tw = self._spectator_timer_target()
        if tw is None:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")
            return
        try:
            if hasattr(tw, "_backend"):
                tw._backend.reset_spectator_sp()
            tw.set_spectator_total_damage(0, 0)
            tw.set_spectator_damage(0, 0)
            clear_info = {
                "blue_round_knockdowns": 0,
                "red_round_knockdowns": 0,
                "blue_punishment_mid": 0.0,
                "red_punishment_mid": 0.0,
                "blue_punishment_long": 0.0,
                "red_punishment_long": 0.0,
                "blue_combo_hit_text": "",
                "blue_combo_damage_text": "",
                "red_combo_hit_text": "",
                "red_combo_damage_text": "",
                "blue_recent_hit_text": "",
                "red_recent_hit_text": "",
            }
            tw.set_spectator_log_info(clear_info)
            self._test_set_spectator_info(clear_info, {
                "blue_round_damage_dealt": 0.0,
                "red_round_damage_dealt": 0.0,
                "blue_damage_dealt": 0.0,
                "red_damage_dealt": 0.0,
                "spectator_sp_reset": True,
                "spectator_match_stats_reset": True,
            })
        except Exception as e:
            QMessageBox.warning(self, "경고", "설정을 확인하세요.")

    def _pick_chapter_output_dir(self):
        cur = str(self.le_chapter_dir.text() or "").strip() if hasattr(self, "le_chapter_dir") else ""
        if not cur:
            cur = os.path.dirname(os.path.abspath(self._cfg_path)) if self._cfg_path else get_app_base_dir()
        path = QFileDialog.getExistingDirectory(self, "챕터 저장 폴더 선택", cur)
        if not path:
            return
        if hasattr(self, "le_chapter_dir"):
            self.le_chapter_dir.setText(str(path))

    def _build_players(self):
        lay = QVBoxLayout()
        def _tt(w: QWidget, text: str):
            try:
                w.setToolTip(text)
            except Exception:
                pass

        profile_group = QGroupBox("새 선수 프로필 등록")
        profile_lay = QGridLayout(profile_group)
        profile_lay.setHorizontalSpacing(12)
        profile_lay.setVerticalSpacing(10)
        self.txt_new_id = QLineEdit()
        self.txt_new_id.setPlaceholderText("GAME_ID1,ID2 (쉼표로 여러 개)")
        _tt(self.txt_new_id, "등록할 선수의 GAME_ID를 입력합니다. 여러 개면 쉼표로 구분합니다.")
        self.txt_new_name = QLineEdit()
        self.txt_new_name.setPlaceholderText("")
        _tt(self.txt_new_name, "표시할 선수 닉네임을 입력합니다.")
        self.cmb_new_country = QComboBox()
        self.cmb_new_country.setStyleSheet("QComboBox,QAbstractItemView{font-family:'Malgun Gothic','맑은 고딕','Segoe UI',sans-serif;}")
        self.cmb_new_country.addItem("한국", "KR")
        self.cmb_new_country.addItem("일본", "JP")
        _tt(self.cmb_new_country, "선수 국적을 선택합니다. 기본값은 한국입니다.")
        self._new_player_flag_path = ""
        self.lbl_new_flag_path = QLabel("")
        self.lbl_new_flag_path.setStyleSheet("color:#94a3b8;")
        _tt(self.lbl_new_flag_path, "Selected flag image file name")
        self.lbl_new_avatar = QLabel("사진")
        self.lbl_new_avatar.setFixedSize(56, 56)
        self.lbl_new_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_new_avatar.setStyleSheet("border:1px solid #2c3444; background:#0f141e; color:#94a3b8;")
        _tt(self.lbl_new_avatar, "선수 초상화 미리보기")
        self.lbl_new_avatar_path = QLabel("")
        self.lbl_new_avatar_path.setStyleSheet("color:#94a3b8;")
        _tt(self.lbl_new_avatar_path, "Selected avatar image file name")
        btn_pick_img = QPushButton("사진 선택")
        btn_pick_img.clicked.connect(self._pick_new_player_image)
        btn_paste_img = QPushButton("붙여넣기")
        btn_paste_img.clicked.connect(self._paste_new_player_image)
        btn_url_img = QPushButton("URL 붙여넣기")
        btn_url_img.clicked.connect(self._url_new_player_image)
        btn_clear_img = QPushButton("제거")
        btn_clear_img.clicked.connect(self._clear_new_player_image)
        btn_pick_flag = QPushButton("국기 선택")
        btn_pick_flag.clicked.connect(self._pick_new_player_flag)
        btn_clear_flag = QPushButton("국기 제거")
        btn_clear_flag.clicked.connect(self._clear_new_player_flag)
        btn_add = QPushButton("추가")
        btn_add.clicked.connect(self.add_player)
        _tt(btn_pick_img, "로컬 이미지 파일을 선택합니다.")
        _tt(btn_paste_img, "클립보드 이미지/파일을 붙여넣습니다.")
        _tt(btn_url_img, "이미지 URL을 붙여넣어 다운로드합니다.")
        _tt(btn_clear_img, "선택한 이미지를 제거합니다.")
        _tt(btn_pick_flag, "로컬 국기 이미지 파일을 선택합니다.")
        _tt(btn_clear_flag, "선택한 국기 이미지를 제거합니다.")
        _tt(btn_add, "입력한 정보로 선수를 추가합니다.")

        profile_lay.addWidget(self.lbl_new_avatar, 0, 0, 2, 1)
        profile_lay.addWidget(QLabel("GAME ID"), 0, 1)
        profile_lay.addWidget(self.txt_new_id, 0, 2, 1, 3)
        profile_lay.addWidget(QLabel("닉네임"), 1, 1)
        profile_lay.addWidget(self.txt_new_name, 1, 2)
        profile_lay.addWidget(QLabel("국적"), 1, 3)
        profile_lay.addWidget(self.cmb_new_country, 1, 4)
        profile_lay.addWidget(btn_add, 0, 5, 2, 1)
        profile_lay.addWidget(QLabel("초상화"), 2, 0)
        profile_lay.addWidget(self.lbl_new_avatar_path, 2, 1, 1, 2)
        profile_lay.addWidget(btn_pick_img, 2, 3)
        profile_lay.addWidget(btn_paste_img, 2, 4)
        profile_lay.addWidget(btn_url_img, 2, 5)
        profile_lay.addWidget(btn_clear_img, 2, 6)
        profile_lay.addWidget(QLabel("국기 이미지"), 3, 0)
        profile_lay.addWidget(self.lbl_new_flag_path, 3, 1, 1, 2)
        profile_lay.addWidget(btn_pick_flag, 3, 3)
        profile_lay.addWidget(btn_clear_flag, 3, 4)
        profile_lay.setColumnStretch(2, 1)
        self._player_profile_editor_group = profile_group
        profile_group.setVisible(False)

        player_actions = QHBoxLayout()
        self.btn_open_new_player_profile = QPushButton("새 선수 프로필 등록")
        self.btn_open_new_player_profile.clicked.connect(self._open_new_player_profile_dialog)
        self.btn_open_player_roster_tools = QPushButton("명단 내보내기 / 불러오기")
        self.btn_open_player_roster_tools.clicked.connect(self._open_player_roster_tools_dialog)
        self.btn_open_new_player_profile.setMinimumHeight(38)
        self.btn_open_player_roster_tools.setMinimumHeight(38)
        player_actions.addWidget(self.btn_open_new_player_profile)
        player_actions.addWidget(self.btn_open_player_roster_tools)
        player_actions.addStretch(1)
        lay.addLayout(player_actions)

        list_group = QGroupBox("선수 목록")
        view_row = QGridLayout(list_group)
        view_row.addWidget(QLabel("보기 방식"), 0, 0)
        self.cmb_players_view = QComboBox()
        self.cmb_players_view.addItems(["그리드", "리스트"])
        self.cmb_players_view.currentIndexChanged.connect(self._reload_players_cards)
        _tt(self.cmb_players_view, "선수 목록 표시 방식을 선택합니다.")
        view_row.addWidget(self.cmb_players_view, 0, 1)

        view_row.addWidget(QLabel("초상화 모양"), 0, 2)
        self.cmb_players_avatar = QComboBox()
        self.cmb_players_avatar.addItems(["원형", "사각형"])
        self.cmb_players_avatar.currentIndexChanged.connect(self._reload_players_cards)
        _tt(self.cmb_players_avatar, "선수 카드의 초상화 모양을 선택합니다.")
        view_row.addWidget(self.cmb_players_avatar, 0, 3)
        view_row.addWidget(QLabel("초상화 우선"), 0, 4)
        self.cmb_portrait_priority = QComboBox()
        self.cmb_portrait_priority.addItem("로그", "log")
        self.cmb_portrait_priority.addItem("프로필", "profile")
        self.cmb_portrait_priority.currentIndexChanged.connect(self._schedule_apply)
        _tt(self.cmb_portrait_priority, "자동 로그 동기화 시 초상화 선택 기준입니다. 기본은 로그 초상화입니다.")
        view_row.addWidget(self.cmb_portrait_priority, 0, 5)
        view_row.addWidget(QLabel("정렬"), 0, 6)
        self.cmb_players_sort = QComboBox()
        self.cmb_players_sort.addItems(["ID", "닉네임"])
        self.cmb_players_sort.currentIndexChanged.connect(self._reload_players_cards)
        self.cmb_players_sort.setCurrentText("닉네임")
        _tt(self.cmb_players_sort, "선수 목록 정렬 기준을 선택합니다.")
        view_row.addWidget(self.cmb_players_sort, 0, 7)
        view_row.addWidget(QLabel("닉네임 검색"), 1, 0)
        self._players_search_query = ""
        self.txt_players_search = ImeAwareLineEdit()
        self.txt_players_search.setPlaceholderText("닉네임 입력")
        self.txt_players_search.queryTextChanged.connect(self._on_players_search_query_changed)
        self.txt_players_search.editingFinished.connect(
            lambda: self._on_players_search_query_changed(self.txt_players_search.text())
        )
        _tt(self.txt_players_search, "입력한 닉네임이 포함된 선수만 표시합니다.")
        view_row.addWidget(self.txt_players_search, 1, 1, 1, 3)
        self.chk_players_missing_img = QCheckBox("사진 미등록만")
        self.chk_players_missing_img.stateChanged.connect(self._reload_players_cards)
        _tt(self.chk_players_missing_img, "초상화가 등록되지 않은 선수만 표시합니다.")
        view_row.addWidget(self.chk_players_missing_img, 1, 4)
        self.btn_export_players_txt = QPushButton("명단 TXT 내보내기")
        self.btn_export_players_txt.clicked.connect(self._export_players_txt)
        _tt(self.btn_export_players_txt, "등록된 선수 명단을 '닉네임 아이디' 형식의 TXT로 저장합니다.")
        self.btn_import_players_txt = QPushButton("명단 TXT 불러오기")
        self.btn_import_players_txt.clicked.connect(self._import_players_txt)
        _tt(self.btn_import_players_txt, "TXT에서 '닉네임 GAME_ID1,ID2 [이미지URL]' 형식의 여러 줄을 한 번에 불러옵니다.")
        self.btn_import_players_paste = QPushButton("명단 텍스트 붙여넣기")
        self.btn_import_players_paste.clicked.connect(self._import_players_paste)
        _tt(self.btn_import_players_paste, "텍스트를 직접 붙여넣어 '닉네임 GAME_ID1,ID2 [이미지URL]' 여러 줄을 한 번에 불러옵니다.")
        view_row.setColumnStretch(3, 1)
        lay.addWidget(list_group)
        manage_group = QGroupBox("닉네임별 GAME_ID 관리")
        manage_lay = QGridLayout(manage_group)
        manage_lay.addWidget(QLabel(""), 0, 0)
        self.cmb_manage_name = QComboBox()
        self.cmb_manage_name.currentIndexChanged.connect(self._on_manage_name_changed)
        manage_lay.addWidget(self.cmb_manage_name, 0, 1)
        manage_lay.addWidget(QLabel("추가할 GAME_ID"), 0, 2)
        self.txt_manage_add_gid = QLineEdit()
        self.txt_manage_add_gid.setPlaceholderText("새 GAME_ID")
        manage_lay.addWidget(self.txt_manage_add_gid, 0, 3)
        btn_add_gid = QPushButton("ID 추가")
        btn_add_gid.clicked.connect(self._add_player_id_to_selected_name)
        manage_lay.addWidget(btn_add_gid, 0, 4)
        manage_lay.addWidget(QLabel("등록된 GAME_ID"), 1, 0)
        self.cmb_manage_gid = QComboBox()
        manage_lay.addWidget(self.cmb_manage_gid, 1, 1)
        btn_del_sel = QPushButton("선택 ID 삭제")
        btn_del_sel.clicked.connect(self._delete_selected_player_id_by_name)
        btn_del_all = QPushButton("닉네임 전체 ID 삭제")
        btn_del_all.clicked.connect(self._delete_all_player_ids_by_name)
        manage_lay.addWidget(btn_del_sel, 1, 2)
        manage_lay.addWidget(btn_del_all, 1, 3)
        _tt(btn_del_sel, "선택한 GAME_ID 하나만 삭제합니다.")
        _tt(btn_del_all, "해당 닉네임에 연결된 모든 GAME_ID를 삭제합니다.")
        _tt(btn_add_gid, "선택한 닉네임에 새 GAME_ID를 추가합니다.")
        lay.addWidget(manage_group)

        self.players_container = QWidget()
        self.players_grid = QGridLayout()
        self.players_grid.setContentsMargins(6, 6, 6, 6)
        self.players_grid.setHorizontalSpacing(12)
        self.players_grid.setVerticalSpacing(12)
        self.players_container.setLayout(self.players_grid)

        self.players_scroll = QScrollArea()
        self.players_scroll.setWidgetResizable(True)
        self.players_scroll.setWidget(self.players_container)
        _tt(self.players_scroll, "선수 목록을 스크롤로 확인합니다.")
        lay.addWidget(self.players_scroll)

        self._reload_players_cards()
        self._refresh_player_manage_ui()
        self.tab_players.setLayout(lay)

    def _open_new_player_profile_dialog(self):
        group = getattr(self, "_player_profile_editor_group", None)
        if group is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("새 선수 프로필 등록")
        dialog.setModal(True)
        dialog.resize(920, 300)
        layout = QVBoxLayout(dialog)
        group.setParent(dialog)
        group.setVisible(True)
        layout.addWidget(group)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(dialog.accept)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)
        try:
            dialog.exec()
        finally:
            layout.removeWidget(group)
            group.setParent(self)
            group.setVisible(False)

    def _open_player_roster_tools_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("선수 명단 내보내기 / 불러오기")
        dialog.setModal(True)
        dialog.resize(620, 220)
        layout = QVBoxLayout(dialog)
        info = QLabel(
            "등록된 선수 명단을 TXT로 저장하거나, TXT 파일 또는 붙여넣은 텍스트로 여러 선수를 한 번에 등록합니다."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        export_button = QPushButton("명단 TXT 내보내기")
        import_button = QPushButton("명단 TXT 불러오기")
        paste_button = QPushButton("명단 텍스트 붙여넣기")
        export_button.clicked.connect(self._export_players_txt)
        import_button.clicked.connect(self._import_players_txt)
        paste_button.clicked.connect(self._import_players_paste)
        for button in (export_button, import_button, paste_button):
            button.setMinimumHeight(40)
            layout.addWidget(button)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(dialog.accept)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)
        dialog.exec()

    # ---- Overlay controls ----
    def _apply_overlay_bg_live(self):
        if self._suspend_apply:
            return
        color = "transparent"
        if hasattr(self, "le_overlay_bg"):
            color = _normalize_hex_color(str(self.le_overlay_bg.text() or "transparent").strip() or "transparent")
        opacity = float(getattr(self.cfg, "overlay_bg_opacity", 0.0))
        if hasattr(self, "sl_overlay_opacity"):
            opacity = float(1.0 - (self.sl_overlay_opacity.value() / 100.0))
        if hasattr(self, "sl_overlay_scale"):
            self.cfg.overlay_ui_scale = float(self.sl_overlay_scale.value()) / 100.0
        self.cfg.overlay_bg_color = _normalize_hex_color(color)
        self.cfg.overlay_bg_opacity = opacity
        try:
            if self.controller:
                self.controller.ui_update.emit({
                    "overlay_bg_color": self.cfg.overlay_bg_color,
                    "overlay_bg_opacity": self.cfg.overlay_bg_opacity,
                    "overlay_ui_scale": float(getattr(self.cfg, "overlay_ui_scale", 1.0) or 1.0),
                })
        except Exception:
            pass
        self._schedule_apply()

    def _apply_overlay_scale_live(self):
        if self._suspend_apply:
            return
        try:
            if hasattr(self, "sp_overlay_scale"):
                scale = float(self.sp_overlay_scale.value()) / 100.0
            elif hasattr(self, "sl_overlay_scale"):
                scale = float(self.sl_overlay_scale.value()) / 100.0
            else:
                scale = float(getattr(self.cfg, "overlay_ui_scale", 1.0) or 1.0)
        except Exception:
            scale = 1.0
        scale = max(0.5, min(2.0, scale))
        self.cfg.overlay_ui_scale = scale
        try:
            if self.controller:
                self.controller.ui_update.emit({
                    "overlay_ui_scale": scale,
                    "overlay_show_time": bool(getattr(self.cfg, "overlay_show_time", True)),
                    "overlay_show_round": bool(getattr(self.cfg, "overlay_show_round", True)),
                })
        except Exception:
            pass
        self._schedule_apply()

    def _apply_browser_overlay_scale_live(self):
        if self._suspend_apply:
            return
        try:
            if hasattr(self, "sp_browser_overlay_scale"):
                scale = float(self.sp_browser_overlay_scale.value()) / 100.0
            else:
                scale = float(getattr(self.cfg, "browser_overlay_scale", 1.0) or 1.0)
        except Exception:
            scale = 1.0
        scale = max(0.25, min(4.0, scale))
        self.cfg.browser_overlay_scale = scale
        try:
            if self.controller:
                self.controller.ui_update.emit({"browser_overlay_scale": scale})
        except Exception:
            pass
        self._schedule_apply()

    def _apply_overlay_timer_layout_live(self):
        if self._suspend_apply:
            return
        try:
            if hasattr(self, "sp_overlay_timer_font"):
                self.cfg.overlay_timer_font_size = int(self.sp_overlay_timer_font.value())
            if hasattr(self, "sp_overlay_timer_x"):
                self.cfg.overlay_timer_x = int(self.sp_overlay_timer_x.value())
            if hasattr(self, "sp_overlay_timer_y"):
                self.cfg.overlay_timer_y = int(self.sp_overlay_timer_y.value())
            if hasattr(self, "sp_overlay_round_font"):
                self.cfg.overlay_round_font_size = int(self.sp_overlay_round_font.value())
            if hasattr(self, "sp_overlay_round_x"):
                self.cfg.overlay_round_x = int(self.sp_overlay_round_x.value())
            if hasattr(self, "sp_overlay_round_y"):
                self.cfg.overlay_round_y = int(self.sp_overlay_round_y.value())
        except Exception:
            pass
        try:
            if self.controller:
                self.controller.ui_update.emit({
                    "overlay_timer_font_size": int(getattr(self.cfg, "overlay_timer_font_size", 54) or 54),
                    "overlay_timer_x": int(getattr(self.cfg, "overlay_timer_x", 0) or 0),
                    "overlay_timer_y": int(getattr(self.cfg, "overlay_timer_y", 0) or 0),
                    "overlay_round_font_size": int(getattr(self.cfg, "overlay_round_font_size", 11) or 11),
                    "overlay_round_x": int(getattr(self.cfg, "overlay_round_x", 0) or 0),
                    "overlay_round_y": int(getattr(self.cfg, "overlay_round_y", 0) or 0),
                })
        except Exception:
            pass
        self._schedule_apply()

    def _overlay_preset_mode_from_ui(self) -> str:
        if not hasattr(self, "cmb_overlay_style_mode"):
            return str(getattr(self.cfg, "overlay_preset", "classic") or "classic")
        v = self.cmb_overlay_style_mode.currentData()
        v = str(v or "classic").strip().lower()
        return v if v in ("classic", "tekken8") else "classic"

    def _apply_overlay_preset_mode_live(self):
        if self._suspend_apply:
            return
        mode = self._overlay_preset_mode_from_ui()
        self.cfg.overlay_preset = mode
        try:
            if self.controller:
                self.controller.ui_update.emit({"overlay_preset": mode})
        except Exception:
            pass
        self._schedule_apply()

    def _overlay_mask_from_ui(self) -> str:
        if not hasattr(self, "cmb_overlay_avatar"):
            return _normalize_player_mask(getattr(self.cfg, "overlay_player_mask", "square"))
        text = str(self.cmb_overlay_avatar.currentText() or "").strip()
        if text == "원형":
            return "circle"
        if text == "circle":
            return "hex"
        return "square"

    def _apply_overlay_mask_live(self):
        if self._suspend_apply:
            return
        shape = self._overlay_mask_from_ui()
        self.cfg.overlay_player_mask = shape
        try:
            if self.controller:
                self.controller.ui_update.emit({
                    "overlay_player_mask": shape,
                })
        except Exception:
            pass
        self._schedule_apply()

    def _apply_overlay_elements_live(self):
        if self._suspend_apply:
            return
        if hasattr(self, "chk_overlay_round"):
            self.cfg.overlay_show_round = bool(self.chk_overlay_round.isChecked())
        if hasattr(self, "chk_overlay_time"):
            self.cfg.overlay_show_time = bool(self.chk_overlay_time.isChecked())
        if hasattr(self, "chk_overlay_blue_img"):
            self.cfg.overlay_show_blue_img = bool(self.chk_overlay_blue_img.isChecked())
        if hasattr(self, "chk_overlay_blue_name"):
            self.cfg.overlay_show_blue_name = bool(self.chk_overlay_blue_name.isChecked())
        if hasattr(self, "chk_overlay_red_img"):
            self.cfg.overlay_show_red_img = bool(self.chk_overlay_red_img.isChecked())
        if hasattr(self, "chk_overlay_red_name"):
            self.cfg.overlay_show_red_name = bool(self.chk_overlay_red_name.isChecked())
        if hasattr(self, "chk_overlay_arena_name"):
            self.cfg.overlay_show_arena_name = bool(self.chk_overlay_arena_name.isChecked())
        if hasattr(self, "chk_overlay_flags"):
            self.cfg.overlay_show_flags = bool(self.chk_overlay_flags.isChecked())
        if hasattr(self, "chk_overlay_cinematic"):
            self.cfg.overlay_show_cinematic = bool(self.chk_overlay_cinematic.isChecked())
        if hasattr(self, "sp_browser_overlay_scale"):
            self.cfg.browser_overlay_scale = max(0.25, min(4.0, float(self.sp_browser_overlay_scale.value()) / 100.0))
        if hasattr(self, "chk_browser_overlay_output_only"):
            self.cfg.browser_overlay_output_only = bool(self.chk_browser_overlay_output_only.isChecked())
        if hasattr(self, "chk_qml_preview_enabled"):
            self.cfg.qml_preview_enabled = bool(self.chk_qml_preview_enabled.isChecked())
            try:
                if self.controller and getattr(self.controller, "timer_win", None):
                    self.controller.timer_win.set_qml_preview_enabled(self.cfg.qml_preview_enabled)
            except Exception:
                pass
        if hasattr(self, "chk_qml_effects_enabled"):
            self.cfg.qml_effects_enabled = bool(self.chk_qml_effects_enabled.isChecked())
            try:
                if self.controller and getattr(self.controller, "timer_win", None):
                    self.controller.timer_win.set_qml_effects_enabled(self.cfg.qml_effects_enabled)
            except Exception:
                pass
        try:
            if self.controller:
                self.controller.ui_update.emit({
                    "overlay_show_round": self.cfg.overlay_show_round,
                    "overlay_show_time": self.cfg.overlay_show_time,
                    "overlay_show_blue_img": self.cfg.overlay_show_blue_img,
                    "overlay_show_blue_name": self.cfg.overlay_show_blue_name,
                    "overlay_show_red_img": self.cfg.overlay_show_red_img,
                    "overlay_show_red_name": self.cfg.overlay_show_red_name,
                    "overlay_show_arena_name": self.cfg.overlay_show_arena_name,
                    "overlay_show_flags": self.cfg.overlay_show_flags,
                    "overlay_show_cinematic": self.cfg.overlay_show_cinematic,
                    "overlay_timer_font_size": int(getattr(self.cfg, "overlay_timer_font_size", 54) or 54),
                    "overlay_timer_x": int(getattr(self.cfg, "overlay_timer_x", 0) or 0),
                    "overlay_timer_y": int(getattr(self.cfg, "overlay_timer_y", 0) or 0),
                    "overlay_round_font_size": int(getattr(self.cfg, "overlay_round_font_size", 11) or 11),
                    "overlay_round_x": int(getattr(self.cfg, "overlay_round_x", 0) or 0),
                    "overlay_round_y": int(getattr(self.cfg, "overlay_round_y", 0) or 0),
                    "browser_overlay_output_only": self.cfg.browser_overlay_output_only,
                    "qml_preview_enabled": self.cfg.qml_preview_enabled,
                    "qml_effects_enabled": self.cfg.qml_effects_enabled,
                })
        except Exception:
            pass
        self._schedule_apply()

    def _format_overlay_vs_bg_map(self, mapping: Dict[str, str]) -> str:
        if not isinstance(mapping, dict):
            return ""
        return "\n".join([f"{k}={v}" for k, v in mapping.items() if str(k).strip() and str(v).strip()])

    def _parse_overlay_vs_bg_map(self) -> Dict[str, str]:
        text = ""
        if hasattr(self, "txt_overlay_vs_bg_map"):
            text = self.txt_overlay_vs_bg_map.toPlainText()
        out: Dict[str, str] = {}
        for raw in str(text or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            if key and val:
                out[key] = val
        return out

    def _browse_overlay_vs_bg(self):
        start = get_app_base_dir()
        cur = str(self.le_overlay_vs_bg.text() or "").strip() if hasattr(self, "le_overlay_vs_bg") else ""
        if cur:
            try:
                start = os.path.dirname(os.path.abspath(cur if os.path.isabs(cur) else os.path.join(get_app_base_dir(), cur)))
            except Exception:
                start = get_app_base_dir()
        path, _ = QFileDialog.getOpenFileName(self, "VS 기본 배경 이미지 선택", start, "이미지 파일 (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*.*)")
        if path and hasattr(self, "le_overlay_vs_bg"):
            self.le_overlay_vs_bg.setText(to_app_rel(path))

    def _apply_overlay_vs_bg_live(self):
        if self._suspend_apply:
            return
        self.cfg.overlay_vs_bg_path = str(self.le_overlay_vs_bg.text() or "").strip() if hasattr(self, "le_overlay_vs_bg") else ""
        self.cfg.overlay_vs_bg_by_arena = self._parse_overlay_vs_bg_map()
        if hasattr(self, "sl_overlay_vs_bg_opacity"):
            self.cfg.overlay_vs_bg_opacity = float(self.sl_overlay_vs_bg_opacity.value()) / 100.0
        if hasattr(self, "sp_overlay_vs_hold_sec"):
            self.cfg.overlay_vs_hold_sec = float(self.sp_overlay_vs_hold_sec.value())
        try:
            if self.controller:
                self.controller.ui_update.emit({
                    "overlay_vs_bg_path": self.cfg.overlay_vs_bg_path,
                    "overlay_vs_bg_by_arena": dict(self.cfg.overlay_vs_bg_by_arena or {}),
                    "overlay_vs_bg_opacity": float(self.cfg.overlay_vs_bg_opacity),
                    "overlay_vs_hold_sec": float(self.cfg.overlay_vs_hold_sec),
                })
        except Exception:
            pass
        self._schedule_apply()

    def _overlay_style_for_key(self, key: str) -> Dict[str, object]:
        defaults = {
            "round": _default_overlay_style_round(),
            "time": _default_overlay_style_time(),
            "blue_name": _default_overlay_style_blue_name(),
            "red_name": _default_overlay_style_red_name(),
            "arena": _default_overlay_style_arena(),
        }
        browser_defaults = _default_browser_text_styles()
        if str(key or "").startswith("browser_"):
            bkey = str(key or "")[8:]
            current = (getattr(self.cfg, "browser_text_styles", {}) or {}).get(bkey, {})
            return _normalize_overlay_style(current, browser_defaults.get(bkey, {}))
        if key == "round":
            current = getattr(self.cfg, "overlay_style_round", {}) or {}
        elif key == "time":
            current = getattr(self.cfg, "overlay_style_time", {}) or {}
        elif key == "blue_name":
            current = getattr(self.cfg, "overlay_style_blue_name", {}) or {}
        elif key == "red_name":
            current = getattr(self.cfg, "overlay_style_red_name", {}) or {}
        elif key == "arena":
            current = getattr(self.cfg, "overlay_style_arena", {}) or {}
        else:
            current = {}
        return _normalize_overlay_style(current, defaults.get(key, {}))

    def _collect_overlay_style(self, key: str) -> Dict[str, object]:
        w = self._overlay_style_widgets.get(key, {})
        data = {
            "bg_color": str(w["bg_color"].text()).strip() or "#000000",
            "bg_opacity": float(w["bg_opacity"].value() / 100.0),
            "border_color": str(w["border_color"].text()).strip() or "#000000",
            "border_opacity": float(w["border_opacity"].value() / 100.0),
            "border_width": int(w["border_width"].value()),
            "text_color": str(w["text_color"].text()).strip() or "#ffffff",
            "text_opacity": float(w["text_opacity"].value() / 100.0),
            "font_family": str(w["font_family"].currentFont().family()),
            "font_size": int(w["font_size"].value()),
            "font_bold": bool(w["font_bold"].isChecked()),
            "font_weight": int(w["font_weight"].value()),
        }
        if key in ("blue_name", "red_name") and "badge_enabled" in w:
            data["badge_enabled"] = bool(w["badge_enabled"].isChecked())
            data["badge_color"] = str(w["badge_color"].text()).strip() or ("#3b82f6" if key == "blue_name" else "#ef4444")
            data["badge_width"] = int(w["badge_width"].value())
            data["badge_height"] = int(w["badge_height"].value())
            data["badge_side"] = "left" if w["badge_side"].currentIndex() == 0 else "right"
        if key == "time":
            cur = getattr(self.cfg, "overlay_style_time", {}) or {}
            rest_color = cur.get("rest_text_color", "#ff5a5a")
            if hasattr(self, "le_rest_text_color"):
                rest_color = str(self.le_rest_text_color.text() or rest_color).strip() or rest_color
            data["rest_text_color"] = rest_color
            data["rest_text_opacity"] = float(cur.get("rest_text_opacity", 1.0))
        return data

    def _apply_overlay_style_live(self):
        if self._suspend_apply:
            return
        self.cfg.overlay_style_round = self._collect_overlay_style("round")
        self.cfg.overlay_style_time = self._collect_overlay_style("time")
        self.cfg.overlay_style_blue_name = self._collect_overlay_style("blue_name")
        self.cfg.overlay_style_red_name = self._collect_overlay_style("red_name")
        self.cfg.overlay_style_arena = self._collect_overlay_style("arena")
        browser_styles = dict(getattr(self.cfg, "browser_text_styles", {}) or {})
        for key in ("time", "total", "dmg", "combo", "recent"):
            wkey = "browser_" + key
            if wkey in getattr(self, "_overlay_style_widgets", {}):
                browser_styles[key] = self._collect_overlay_style(wkey)
        self.cfg.browser_text_styles = _normalize_browser_text_styles(browser_styles)
        try:
            if self.controller:
                self.controller.ui_update.emit({
                    "overlay_style": {
                        "round": self.cfg.overlay_style_round,
                        "time": self.cfg.overlay_style_time,
                        "blue_name": self.cfg.overlay_style_blue_name,
                        "red_name": self.cfg.overlay_style_red_name,
                        "arena": self.cfg.overlay_style_arena,
                    }
                    ,
                    "browser_text_styles": self.cfg.browser_text_styles,
                })
        except Exception:
            pass
        self._schedule_apply()

    def _collect_overlay_preset(self) -> dict:
        bg_color = getattr(self.cfg, "overlay_bg_color", "transparent")
        bg_opacity = float(getattr(self.cfg, "overlay_bg_opacity", 0.0))
        overlay_preset = str(getattr(self.cfg, "overlay_preset", "classic") or "classic")
        player_mask = getattr(self.cfg, "overlay_player_mask", "square")
        show_round = bool(getattr(self.cfg, "overlay_show_round", True))
        show_time = bool(getattr(self.cfg, "overlay_show_time", True))
        show_blue_img = bool(getattr(self.cfg, "overlay_show_blue_img", True))
        show_blue_name = bool(getattr(self.cfg, "overlay_show_blue_name", True))
        show_red_img = bool(getattr(self.cfg, "overlay_show_red_img", True))
        show_red_name = bool(getattr(self.cfg, "overlay_show_red_name", True))
        show_arena_name = bool(getattr(self.cfg, "overlay_show_arena_name", True))
        show_flags = bool(getattr(self.cfg, "overlay_show_flags", True))
        show_cinematic = bool(getattr(self.cfg, "overlay_show_cinematic", True))
        style_round = getattr(self.cfg, "overlay_style_round", _default_overlay_style_round())
        style_time = getattr(self.cfg, "overlay_style_time", _default_overlay_style_time())
        style_blue = getattr(self.cfg, "overlay_style_blue_name", _default_overlay_style_blue_name())
        style_red = getattr(self.cfg, "overlay_style_red_name", _default_overlay_style_red_name())
        style_arena = getattr(self.cfg, "overlay_style_arena", _default_overlay_style_arena())
        layout = dict(getattr(self.cfg, "layout", {}) or {})
        vs_bg_path = str(getattr(self.cfg, "overlay_vs_bg_path", "") or "")
        vs_bg_opacity = float(getattr(self.cfg, "overlay_vs_bg_opacity", 1.0) or 1.0)
        vs_bg_map = dict(getattr(self.cfg, "overlay_vs_bg_by_arena", {}) or {})
        vs_hold_sec = float(getattr(self.cfg, "overlay_vs_hold_sec", 2.85) or 2.85)

        if hasattr(self, "le_overlay_bg"):
            bg_color = _normalize_hex_color(str(self.le_overlay_bg.text() or "transparent").strip() or "transparent")
        if hasattr(self, "sl_overlay_opacity"):
            bg_opacity = float(1.0 - (self.sl_overlay_opacity.value() / 100.0))
        if hasattr(self, "sl_overlay_scale"):
            self.cfg.overlay_ui_scale = float(self.sl_overlay_scale.value()) / 100.0
        if hasattr(self, "sp_overlay_scale"):
            self.cfg.overlay_ui_scale = float(self.sp_overlay_scale.value()) / 100.0
        if hasattr(self, "cmb_overlay_style_mode"):
            overlay_preset = self._overlay_preset_mode_from_ui()
        if hasattr(self, "cmb_overlay_avatar"):
            player_mask = self._overlay_mask_from_ui()
        if hasattr(self, "chk_overlay_round"):
            show_round = bool(self.chk_overlay_round.isChecked())
        if hasattr(self, "chk_overlay_time"):
            show_time = bool(self.chk_overlay_time.isChecked())
        if hasattr(self, "chk_overlay_blue_img"):
            show_blue_img = bool(self.chk_overlay_blue_img.isChecked())
        if hasattr(self, "chk_overlay_blue_name"):
            show_blue_name = bool(self.chk_overlay_blue_name.isChecked())
        if hasattr(self, "chk_overlay_red_img"):
            show_red_img = bool(self.chk_overlay_red_img.isChecked())
        if hasattr(self, "chk_overlay_red_name"):
            show_red_name = bool(self.chk_overlay_red_name.isChecked())
        if hasattr(self, "chk_overlay_arena_name"):
            show_arena_name = bool(self.chk_overlay_arena_name.isChecked())
        if hasattr(self, "chk_overlay_flags"):
            show_flags = bool(self.chk_overlay_flags.isChecked())
        if hasattr(self, "chk_overlay_cinematic"):
            show_cinematic = bool(self.chk_overlay_cinematic.isChecked())
        if hasattr(self, "_overlay_style_widgets"):
            try:
                style_round = self._collect_overlay_style("round")
                style_time = self._collect_overlay_style("time")
                style_blue = self._collect_overlay_style("blue_name")
                style_red = self._collect_overlay_style("red_name")
                style_arena = self._collect_overlay_style("arena")
            except Exception:
                pass
        if hasattr(self, "le_overlay_vs_bg"):
            vs_bg_path = str(self.le_overlay_vs_bg.text() or "").strip()
        if hasattr(self, "sl_overlay_vs_bg_opacity"):
            vs_bg_opacity = float(self.sl_overlay_vs_bg_opacity.value()) / 100.0
        if hasattr(self, "txt_overlay_vs_bg_map"):
            vs_bg_map = self._parse_overlay_vs_bg_map()
        if hasattr(self, "sp_overlay_vs_hold_sec"):
            vs_hold_sec = float(self.sp_overlay_vs_hold_sec.value())

        return {
            "version": 1,
            "overlay_bg_color": bg_color,
            "overlay_bg_opacity": bg_opacity,
            "overlay_ui_scale": float(getattr(self.cfg, "overlay_ui_scale", 1.0) or 1.0),
            "overlay_preset": overlay_preset,
            "overlay_player_mask": player_mask,
            "overlay_show_round": show_round,
            "overlay_show_time": show_time,
            "overlay_show_blue_img": show_blue_img,
            "overlay_show_blue_name": show_blue_name,
            "overlay_show_red_img": show_red_img,
            "overlay_show_red_name": show_red_name,
            "overlay_show_arena_name": show_arena_name,
            "overlay_show_flags": show_flags,
            "overlay_show_cinematic": show_cinematic,
            "browser_overlay_scale": float(getattr(self.cfg, "browser_overlay_scale", 1.0) or 1.0),
            "browser_overlay_output_only": bool(getattr(self.cfg, "browser_overlay_output_only", True)),
            "qml_effects_enabled": bool(getattr(self.cfg, "qml_effects_enabled", False)),
            "overlay_style": {
                "round": style_round,
                "time": style_time,
                "blue_name": style_blue,
                "red_name": style_red,
                "arena": style_arena,
            },
            "overlay_layout": layout,
            "overlay_vs_bg_path": to_app_rel(vs_bg_path),
            "overlay_vs_bg_opacity": max(0.0, min(1.0, float(vs_bg_opacity))),
            "overlay_vs_bg_by_arena": {str(k): to_app_rel(str(v)) for k, v in (vs_bg_map or {}).items()},
            "overlay_vs_hold_sec": max(0.5, min(15.0, float(vs_hold_sec))),
        }

    def _apply_overlay_preset(self, data: dict):
        if not isinstance(data, dict):
            return
        bg_color = _normalize_hex_color(str(data.get("overlay_bg_color", "transparent")))
        try:
            bg_opacity = float(data.get("overlay_bg_opacity", 0.0))
        except Exception:
            bg_opacity = 0.0
        bg_opacity = max(0.0, min(1.0, bg_opacity))
        overlay_preset = str(data.get("overlay_preset", "classic") or "classic").strip().lower()
        if overlay_preset not in ("classic", "tekken8"):
            overlay_preset = "classic"
        player_mask = _normalize_player_mask(data.get("overlay_player_mask", "square"))
        show_round = bool(data.get("overlay_show_round", True))
        show_time = bool(data.get("overlay_show_time", True))
        show_blue_img = bool(data.get("overlay_show_blue_img", True))
        show_blue_name = bool(data.get("overlay_show_blue_name", True))
        show_red_img = bool(data.get("overlay_show_red_img", True))
        show_red_name = bool(data.get("overlay_show_red_name", True))
        show_arena = bool(data.get("overlay_show_arena_name", True))
        show_flags = bool(data.get("overlay_show_flags", True))
        show_cinematic = bool(data.get("overlay_show_cinematic", True))
        browser_output_only = bool(data.get("browser_overlay_output_only", True))
        vs_bg_path = str(data.get("overlay_vs_bg_path", "") or "")
        try:
            vs_bg_opacity = max(0.0, min(1.0, float(data.get("overlay_vs_bg_opacity", 1.0) or 1.0)))
        except Exception:
            vs_bg_opacity = 1.0
        vs_bg_map = data.get("overlay_vs_bg_by_arena", {}) or {}
        if not isinstance(vs_bg_map, dict):
            vs_bg_map = {}
        vs_bg_map = {str(k): str(v) for k, v in vs_bg_map.items()}
        try:
            vs_hold_sec = max(0.5, min(15.0, float(data.get("overlay_vs_hold_sec", 2.85) or 2.85)))
        except Exception:
            vs_hold_sec = 2.85
        style = data.get("overlay_style", None)
        if style is None:
            style = {
                "round": data.get("overlay_style_round", _default_overlay_style_round()),
                "time": data.get("overlay_style_time", _default_overlay_style_time()),
                "blue_name": data.get("overlay_style_blue_name", _default_overlay_style_blue_name()),
                "red_name": data.get("overlay_style_red_name", _default_overlay_style_red_name()),
                "arena": data.get("overlay_style_arena", _default_overlay_style_arena()),
            }
        style_round = _normalize_overlay_style(style.get("round"), _default_overlay_style_round())
        style_time = _normalize_overlay_style(style.get("time"), _default_overlay_style_time())
        style_blue = _normalize_overlay_style(style.get("blue_name"), _default_overlay_style_blue_name())
        style_red = _normalize_overlay_style(style.get("red_name"), _default_overlay_style_red_name())
        style_arena = _normalize_overlay_style(style.get("arena"), _default_overlay_style_arena())
        layout = data.get("overlay_layout", None)
        if isinstance(layout, dict):
            self.cfg.layout = dict(layout)

        prev_suspend = bool(getattr(self, "_suspend_apply", False))
        self._suspend_apply = True
        if hasattr(self, "le_overlay_bg"):
            self.le_overlay_bg.setText(str(bg_color))
        if hasattr(self, "sl_overlay_opacity"):
            self.sl_overlay_opacity.setValue(int((1.0 - bg_opacity) * 100))
        if hasattr(self, "sl_overlay_scale"):
            try:
                scale_pct = int(float(data.get("overlay_ui_scale", getattr(self.cfg, "overlay_ui_scale", 1.0)) or 1.0) * 100)
                self.sl_overlay_scale.setValue(scale_pct)
                if hasattr(self, "sp_overlay_scale"):
                    self.sp_overlay_scale.setValue(scale_pct)
            except Exception:
                self.sl_overlay_scale.setValue(100)
                if hasattr(self, "sp_overlay_scale"):
                    self.sp_overlay_scale.setValue(100)
        if hasattr(self, "cmb_overlay_style_mode"):
            idx = self.cmb_overlay_style_mode.findData(overlay_preset)
            self.cmb_overlay_style_mode.setCurrentIndex(idx if idx >= 0 else 0)
        if hasattr(self, "cmb_overlay_avatar"):
            if player_mask == "circle":
                self.cmb_overlay_avatar.setCurrentText("원형")
            elif player_mask == "hex":
                self.cmb_overlay_avatar.setCurrentText("원형")
            else:
                self.cmb_overlay_avatar.setCurrentText("육각형")
        if hasattr(self, "chk_overlay_round"):
            self.chk_overlay_round.setChecked(show_round)
        if hasattr(self, "chk_overlay_time"):
            self.chk_overlay_time.setChecked(show_time)
        if hasattr(self, "chk_overlay_blue_img"):
            self.chk_overlay_blue_img.setChecked(show_blue_img)
        if hasattr(self, "chk_overlay_blue_name"):
            self.chk_overlay_blue_name.setChecked(show_blue_name)
        if hasattr(self, "chk_overlay_red_img"):
            self.chk_overlay_red_img.setChecked(show_red_img)
        if hasattr(self, "chk_overlay_red_name"):
            self.chk_overlay_red_name.setChecked(show_red_name)
        if hasattr(self, "chk_overlay_arena_name"):
            self.chk_overlay_arena_name.setChecked(show_arena)
        if hasattr(self, "chk_overlay_flags"):
            self.chk_overlay_flags.setChecked(show_flags)
        if hasattr(self, "chk_overlay_cinematic"):
            self.chk_overlay_cinematic.setChecked(show_cinematic)
        if hasattr(self, "sp_browser_overlay_scale"):
            try:
                self.sp_browser_overlay_scale.setValue(int(float(data.get("browser_overlay_scale", getattr(self.cfg, "browser_overlay_scale", 1.0)) or 1.0) * 100))
            except Exception:
                self.sp_browser_overlay_scale.setValue(100)
        if hasattr(self, "chk_browser_overlay_output_only"):
            self.chk_browser_overlay_output_only.setChecked(browser_output_only)
        if hasattr(self, "le_overlay_vs_bg"):
            self.le_overlay_vs_bg.setText(vs_bg_path)
        if hasattr(self, "sl_overlay_vs_bg_opacity"):
            self.sl_overlay_vs_bg_opacity.setValue(int(vs_bg_opacity * 100))
        if hasattr(self, "txt_overlay_vs_bg_map"):
            self.txt_overlay_vs_bg_map.setPlainText(self._format_overlay_vs_bg_map(vs_bg_map))
        if hasattr(self, "sp_overlay_vs_hold_sec"):
            self.sp_overlay_vs_hold_sec.setValue(vs_hold_sec)
        if hasattr(self, "_overlay_style_widgets"):
            for key, style_data in (
                ("round", style_round),
                ("time", style_time),
                ("blue_name", style_blue),
                ("red_name", style_red),
                ("arena", style_arena),
            ):
                w = self._overlay_style_widgets.get(key, {})
                if not w:
                    continue
                w["bg_color"].setText(str(style_data.get("bg_color", "#000000")))
                w["bg_opacity"].setValue(int(float(style_data.get("bg_opacity", 1.0)) * 100))
                w["border_color"].setText(str(style_data.get("border_color", "#000000")))
                w["border_opacity"].setValue(int(float(style_data.get("border_opacity", 1.0)) * 100))
                w["border_width"].setValue(int(style_data.get("border_width", 1)))
                w["text_color"].setText(str(style_data.get("text_color", "#ffffff")))
                w["text_opacity"].setValue(int(float(style_data.get("text_opacity", 1.0)) * 100))
                try:
                    from PyQt6.QtGui import QFont
                    w["font_family"].setCurrentFont(QFont(str(style_data.get("font_family", ""))))
                except Exception:
                    pass
                w["font_size"].setValue(int(style_data.get("font_size", 0)))
                w["font_bold"].setChecked(bool(style_data.get("font_bold", False)))
                w["font_weight"].setValue(int(style_data.get("font_weight", 700)))
        self._suspend_apply = prev_suspend

        self.cfg.overlay_preset = overlay_preset
        try:
            self.cfg.browser_overlay_scale = max(0.25, min(4.0, float(data.get("browser_overlay_scale", getattr(self.cfg, "browser_overlay_scale", 1.0)) or 1.0)))
        except Exception:
            self.cfg.browser_overlay_scale = 1.0
        self.cfg.browser_overlay_output_only = browser_output_only
        self._apply_overlay_bg_live()
        self._apply_overlay_preset_mode_live()
        self._apply_overlay_mask_live()
        self._apply_overlay_elements_live()
        self._apply_overlay_vs_bg_live()
        self._apply_overlay_style_live()
        if isinstance(layout, dict):
            try:
                if self.controller:
                    self.controller.ui_update.emit({"overlay_layout": dict(layout)})
            except Exception:
                pass

    def _attach_color_preview(self, target: QLineEdit, preview: QLabel):
        def _apply_preview():
            c = _normalize_hex_color(str(target.text() or "").strip() or "#000000")
            if c == "transparent":
                preview.setStyleSheet("background: transparent; border:1px solid #999;")
            else:
                preview.setStyleSheet(f"background:{c}; border:1px solid #333;")
        target.textChanged.connect(lambda _t: _apply_preview())
        _apply_preview()

    def _attach_color_button(self, target: QLineEdit, button: QPushButton):
        def _apply_button():
            c = _normalize_hex_color(str(target.text() or "").strip() or "#000000")
            if c == "transparent":
                button.setStyleSheet("background: transparent; border:1px solid #999;")
            else:
                button.setStyleSheet(f"background:{c}; border:1px solid #333;")
        target.textChanged.connect(lambda _t: _apply_button())
        _apply_button()

    def _overlay_custom_list(self) -> List[dict]:
        layout = dict(getattr(self.cfg, "layout", {}) or {})
        return list(layout.get("custom_elements", []) or [])

    def _set_overlay_custom_list(self, items: List[dict], refresh: bool = False):
        keep_id = None
        if hasattr(self, "lst_overlay_custom"):
            try:
                cur = self.lst_overlay_custom.currentRow()
                cur_items = self._overlay_custom_list()
                if 0 <= cur < len(cur_items):
                    keep_id = str(cur_items[cur].get("id") or "")
            except Exception:
                keep_id = None
        layout = dict(getattr(self.cfg, "layout", {}) or {})
        layout["custom_elements"] = list(items or [])
        self.cfg.layout = layout
        try:
            if self.controller:
                self.controller.ui_update.emit({"overlay_layout": layout})
        except Exception:
            pass
        if self._cfg_path:
            try:
                self.cfg.to_json(self._cfg_path)
            except Exception:
                pass
        if refresh or hasattr(self, "lst_overlay_custom"):
            self._refresh_overlay_custom_list(keep_id=keep_id)

    def _refresh_overlay_custom_list(self, keep_id: Optional[str] = None, select_last: bool = False):
        if not hasattr(self, "lst_overlay_custom"):
            return
        items = self._overlay_custom_list()
        current_id = keep_id
        if current_id is None and self.lst_overlay_custom.currentRow() >= 0:
            idx = self.lst_overlay_custom.currentRow()
            if 0 <= idx < len(items):
                current_id = str(items[idx].get("id") or "")
        self._overlay_custom_loading = True
        self.lst_overlay_custom.clear()
        for i, it in enumerate(items):
            name = str(it.get("text") or it.get("id") or f"custom{i+1}")
            self.lst_overlay_custom.addItem(f"{i+1}. {name}")
        self._overlay_custom_loading = False
        target_idx = -1
        if select_last and items:
            target_idx = len(items) - 1
        elif current_id:
            for i, it in enumerate(items):
                if str(it.get("id") or "") == current_id:
                    target_idx = i
                    break
        if target_idx >= 0:
            self.lst_overlay_custom.setCurrentRow(target_idx)
        else:
            self._load_overlay_custom_selected()

    def _set_overlay_custom_controls_enabled(self, enabled: bool):
        for w in getattr(self, "_overlay_custom_controls", []):
            try:
                w.setEnabled(bool(enabled))
            except Exception:
                pass

    def _load_overlay_custom_selected(self):
        if not hasattr(self, "lst_overlay_custom"):
            return
        items = self._overlay_custom_list()
        idx = self.lst_overlay_custom.currentRow()
        if idx < 0 or idx >= len(items):
            self._set_overlay_custom_controls_enabled(False)
            return
        it = items[idx] or {}
        self._overlay_custom_loading = True
        try:
            if hasattr(self, "le_overlay_custom_text_edit"):
                self.le_overlay_custom_text_edit.setText(str(it.get("text") or ""))
            if hasattr(self, "chk_overlay_custom_visible"):
                self.chk_overlay_custom_visible.setChecked(bool(it.get("visible", True)))
            if hasattr(self, "le_overlay_custom_bg"):
                self.le_overlay_custom_bg.setText(str(it.get("bg_color") or "#1f2937"))
            if hasattr(self, "le_overlay_custom_text_color"):
                self.le_overlay_custom_text_color.setText(str(it.get("text_color") or "#ffffff"))
            if hasattr(self, "le_overlay_custom_border_color"):
                self.le_overlay_custom_border_color.setText(str(it.get("border_color") or "#111827"))
            if hasattr(self, "sl_overlay_custom_bg_opacity"):
                self.sl_overlay_custom_bg_opacity.setValue(int(float(it.get("bg_opacity", 0.85)) * 100))
            if hasattr(self, "sl_overlay_custom_text_opacity"):
                self.sl_overlay_custom_text_opacity.setValue(int(float(it.get("text_opacity", 1.0)) * 100))
            if hasattr(self, "sl_overlay_custom_border_opacity"):
                self.sl_overlay_custom_border_opacity.setValue(int(float(it.get("border_opacity", 1.0)) * 100))
            if hasattr(self, "sp_overlay_custom_border_width"):
                self.sp_overlay_custom_border_width.setValue(int(it.get("border_width", 2)))
            if hasattr(self, "sp_overlay_custom_font_size"):
                self.sp_overlay_custom_font_size.setValue(int(it.get("font_size", 0)))
            if hasattr(self, "chk_overlay_custom_font_bold"):
                self.chk_overlay_custom_font_bold.setChecked(bool(it.get("font_bold", True)))
            if hasattr(self, "sp_overlay_custom_font_weight"):
                self.sp_overlay_custom_font_weight.setValue(int(it.get("font_weight", 700)))
            if hasattr(self, "cmb_overlay_custom_font"):
                try:
                    from PyQt6.QtGui import QFont
                    self.cmb_overlay_custom_font.setCurrentFont(QFont(str(it.get("font_family") or "")))
                except Exception:
                    pass
        finally:
            self._overlay_custom_loading = False
        self._set_overlay_custom_controls_enabled(True)

    def _apply_overlay_custom_edit(self):
        if getattr(self, "_overlay_custom_loading", False):
            return
        if not hasattr(self, "lst_overlay_custom"):
            return
        items = self._overlay_custom_list()
        idx = self.lst_overlay_custom.currentRow()
        if idx < 0 or idx >= len(items):
            return
        it = dict(items[idx] or {})
        if hasattr(self, "le_overlay_custom_text_edit"):
            it["text"] = str(self.le_overlay_custom_text_edit.text() or "")
        if hasattr(self, "chk_overlay_custom_visible"):
            it["visible"] = bool(self.chk_overlay_custom_visible.isChecked())
        if hasattr(self, "le_overlay_custom_bg"):
            it["bg_color"] = _normalize_hex_color(str(self.le_overlay_custom_bg.text() or "#000000").strip() or "#000000")
        if hasattr(self, "le_overlay_custom_text_color"):
            it["text_color"] = _normalize_hex_color(str(self.le_overlay_custom_text_color.text() or "#ffffff").strip() or "#ffffff")
        if hasattr(self, "le_overlay_custom_border_color"):
            it["border_color"] = _normalize_hex_color(str(self.le_overlay_custom_border_color.text() or "#000000").strip() or "#000000")
        if hasattr(self, "sl_overlay_custom_bg_opacity"):
            it["bg_opacity"] = float(self.sl_overlay_custom_bg_opacity.value() / 100.0)
        if hasattr(self, "sl_overlay_custom_text_opacity"):
            it["text_opacity"] = float(self.sl_overlay_custom_text_opacity.value() / 100.0)
        if hasattr(self, "sl_overlay_custom_border_opacity"):
            it["border_opacity"] = float(self.sl_overlay_custom_border_opacity.value() / 100.0)
        if hasattr(self, "sp_overlay_custom_border_width"):
            it["border_width"] = int(self.sp_overlay_custom_border_width.value())
        if hasattr(self, "sp_overlay_custom_font_size"):
            it["font_size"] = int(self.sp_overlay_custom_font_size.value())
        if hasattr(self, "chk_overlay_custom_font_bold"):
            it["font_bold"] = bool(self.chk_overlay_custom_font_bold.isChecked())
        if hasattr(self, "sp_overlay_custom_font_weight"):
            it["font_weight"] = int(self.sp_overlay_custom_font_weight.value())
        if hasattr(self, "cmb_overlay_custom_font"):
            it["font_family"] = str(self.cmb_overlay_custom_font.currentFont().family())
        items[idx] = it
        self._set_overlay_custom_list(items)
        try:
            name = str(it.get("text") or it.get("id") or f"custom{idx+1}")
            item = self.lst_overlay_custom.item(idx)
            if item:
                item.setText(f"{idx+1}. {name}")
        except Exception:
            pass

    def _delete_overlay_custom_selected(self):
        if not hasattr(self, "lst_overlay_custom"):
            return
        items = self._overlay_custom_list()
        idx = self.lst_overlay_custom.currentRow()
        if idx < 0 or idx >= len(items):
            return
        items.pop(idx)
        self._set_overlay_custom_list(items, refresh=True)

    def _save_overlay_preset(self):
        data = self._collect_overlay_preset()
        base = self._overlay_preset_dir()
        default_path = os.path.join(base, "overlay_preset.json")
        path, _ = QFileDialog.getSaveFileName(self, "오버레이 프리셋 저장", default_path, "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "저장 완료", "오버레이 프리셋을 저장했습니다.")
        except Exception:
            QMessageBox.warning(self, "저장 실패", "오버레이 프리셋을 저장할 수 없습니다.")

    def _load_overlay_preset(self):
        base = self._overlay_preset_dir()
        path, _ = QFileDialog.getOpenFileName(self, "오버레이 프리셋 불러오기", base, "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            QMessageBox.warning(self, "불러오기 실패", "프리셋 파일을 열 수 없습니다.")
            return
        try:
            self._apply_overlay_preset(data or {})
            QMessageBox.information(self, "불러오기", f"오버레이 프리셋 적용 완료!\n{path}")
        except Exception:
            QMessageBox.warning(self, "적용 실패", "오버레이 프리셋 적용 중 오류가 발생했습니다.")

    def _add_overlay_custom_element(self):
        text = ""
        if hasattr(self, "le_overlay_custom_text"):
            text = str(self.le_overlay_custom_text.text() or "").strip()
        if not text:
            text = "CUSTOM"
        layout = dict(getattr(self.cfg, "layout", {}) or {})
        custom = list(layout.get("custom_elements", []) or [])
        custom.append({
            "id": f"custom_{uuid.uuid4().hex[:8]}",
            "x": 20,
            "y": 40,
            "w": 160,
            "h": 48,
            "text": text,
        })
        layout["custom_elements"] = custom
        self.cfg.layout = layout
        if hasattr(self, "le_overlay_custom_text"):
            self.le_overlay_custom_text.clear()
        self._refresh_overlay_custom_list(select_last=True)
        try:
            if self.controller:
                self.controller.ui_update.emit({"overlay_layout": layout})
        except Exception:
            pass
        if self._cfg_path:
            try:
                self.cfg.to_json(self._cfg_path)
            except Exception:
                pass

    def _build_timer(self):
        content = QWidget()
        lay = QVBoxLayout(content)
        overlay_content = QWidget()
        overlay_lay = QVBoxLayout(overlay_content)
        def _tt(w: QWidget, text: str):
            try:
                w.setToolTip(text)
            except Exception:
                pass

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("오버레이 프리셋:"))
        self.cmb_overlay_preset = QComboBox()
        self._overlay_presets = {}
        self._refresh_overlay_presets()
        self.cmb_overlay_preset.currentIndexChanged.connect(self._apply_overlay_preset_from_ui)
        _tt(self.cmb_overlay_preset, "저장해둔 오버레이 프리셋을 불러옵니다.")
        preset_row.addWidget(self.cmb_overlay_preset)
        preset_row.addStretch(1)
        overlay_lay.addLayout(preset_row)

        row = QHBoxLayout()
        row.addWidget(QLabel("총 라운드 수:"))
        self.sp_timer_total = QSpinBox(); self.sp_timer_total.setRange(1, 99); self.sp_timer_total.setValue(self.cfg.timer_total_rounds)
        _tt(self.sp_timer_total, "전체 라운드 수를 설정합니다.")
        row.addWidget(self.sp_timer_total)
        row.addSpacing(12)
        row.addWidget(QLabel("현재 라운드:"))
        self.sp_timer_current = QSpinBox(); self.sp_timer_current.setRange(1, 99); self.sp_timer_current.setValue(self.cfg.timer_current_round)
        _tt(self.sp_timer_current, "현재 라운드 번호를 설정합니다.")
        row.addWidget(self.sp_timer_current)
        row.addStretch(1)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("라운드 시간(초):"))
        self.sp_timer_round_sec = QSpinBox(); self.sp_timer_round_sec.setRange(10, 3600); self.sp_timer_round_sec.setValue(self.cfg.timer_round_sec)
        _tt(self.sp_timer_round_sec, "한 라운드의 길이(초)입니다.")
        row2.addWidget(self.sp_timer_round_sec)
        row2.addSpacing(12)
        row2.addWidget(QLabel("휴식 시간(초):"))
        self.sp_timer_rest_sec = QSpinBox(); self.sp_timer_rest_sec.setRange(0, 3600); self.sp_timer_rest_sec.setValue(self.cfg.timer_rest_sec)
        _tt(self.sp_timer_rest_sec, "라운드 사이 휴식 시간(초)입니다.")
        row2.addWidget(self.sp_timer_rest_sec)
        row2.addSpacing(12)
        row2.addWidget(QLabel("현재 남은 시간(초):"))
        self.sp_timer_left = QSpinBox(); self.sp_timer_left.setRange(0, 3600); self.sp_timer_left.setValue(self.cfg.timer_seconds_left)
        _tt(self.sp_timer_left, "현재 남은 시간을 직접 설정합니다.")
        row2.addWidget(self.sp_timer_left)
        btn_apply = QPushButton("지금 적용")
        btn_apply.clicked.connect(self._apply_timer_settings_now)
        _tt(btn_apply, "현재 설정값을 즉시 타이머 오버레이에 반영합니다.")
        row2.addWidget(btn_apply)
        row2.addStretch(1)
        lay.addLayout(row2)
        row_tts = QHBoxLayout()
        self.chk_rest_30s_tts = QCheckBox("쉬는시간 30초 안내 TTS 사용")
        self.chk_rest_30s_tts.setChecked(bool(getattr(self.cfg, "timer_rest_30s_tts_enabled", True)))
        _tt(self.chk_rest_30s_tts, "쉬는시간이 30초가 되면 안내 문구 TTS를 2회 재생합니다.")
        row_tts.addWidget(self.chk_rest_30s_tts)
        row_tts.addSpacing(12)
        row_tts.addWidget(QLabel("속도:"))
        self.sp_rest_30s_tts_rate = QSpinBox()
        self.sp_rest_30s_tts_rate.setRange(80, 300)
        self.sp_rest_30s_tts_rate.setValue(int(getattr(self.cfg, "timer_rest_30s_tts_rate", 200)))
        _tt(self.sp_rest_30s_tts_rate, "쉬는시간 30초 안내 TTS 속도입니다. (낮을수록 느림)")
        row_tts.addWidget(self.sp_rest_30s_tts_rate)
        row_tts.addStretch(1)
        timer_tts_group = QGroupBox("타이머 TTS")
        timer_tts_group.setLayout(row_tts)
        if hasattr(self, "_sound_lay_outer"):
            self._sound_lay_outer.insertWidget(max(0, self._sound_lay_outer.count() - 1), timer_tts_group)
        else:
            lay.addWidget(timer_tts_group)

        row_rest_color = QHBoxLayout()
        row_rest_color.addWidget(QLabel("쉬는시간 텍스트 색:"))
        self.le_rest_text_color = QLineEdit()
        self.le_rest_text_color.setVisible(False)
        self.btn_rest_text_color = QPushButton("")
        self.btn_rest_text_color.setFixedSize(26, 18)
        self._attach_color_button(self.le_rest_text_color, self.btn_rest_text_color)
        rest_color = "#ff5a5a"
        try:
            rest_color = (getattr(self.cfg, "overlay_style_time", {}) or {}).get("rest_text_color", rest_color)
        except Exception:
            pass
        self.le_rest_text_color.setText(str(rest_color))
        def _pick_rest_text():
            c = QColor(self.le_rest_text_color.text() or "#ff5a5a")
            dlg = QColorDialog(c, self)
            dlg.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
            if dlg.exec():
                q = dlg.currentColor()
                if q.isValid():
                    self.le_rest_text_color.setText(q.name())
        self.btn_rest_text_color.clicked.connect(_pick_rest_text)
        self.le_rest_text_color.textChanged.connect(lambda _t: self._apply_overlay_style_live())
        _tt(self.btn_rest_text_color, "쉬는시간(휴식 상태)일 때 타이머 텍스트 색상을 설정합니다.")
        row_rest_color.addWidget(self.le_rest_text_color)
        row_rest_color.addWidget(self.btn_rest_text_color)
        row_rest_color.addStretch(1)
        overlay_lay.addLayout(row_rest_color)
        row_bg = QHBoxLayout()
        row_bg.addWidget(QLabel("오버레이 배경색:"))
        self.le_overlay_bg = QLineEdit(); self.le_overlay_bg.setPlaceholderText("#00000000")
        self.le_overlay_bg.setText(getattr(self.cfg, "overlay_bg_color", "transparent"))
        self.le_overlay_bg.setVisible(False)
        self.btn_overlay_bg = QPushButton("")
        self.btn_overlay_bg.setFixedSize(26, 18)
        self._attach_color_button(self.le_overlay_bg, self.btn_overlay_bg)
        self.btn_overlay_bg_clear = QPushButton("투명")
        _tt(self.btn_overlay_bg, "오버레이 배경색을 선택합니다.")
        _tt(self.btn_overlay_bg_clear, "배경색을 완전 투명으로 설정합니다.")
        self.btn_overlay_bg_clear.clicked.connect(lambda: self.le_overlay_bg.setText("transparent"))
        self.le_overlay_bg.textChanged.connect(lambda _t: self._apply_overlay_bg_live())
        def _pick_overlay_bg():
            c = QColor(self.le_overlay_bg.text() or "transparent")
            dlg = QColorDialog(c, self)
            dlg.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
            if dlg.exec():
                q = dlg.currentColor()
                if q.isValid():
                    self.le_overlay_bg.setText(q.name())
        self.btn_overlay_bg.clicked.connect(_pick_overlay_bg)
        row_bg.addWidget(self.le_overlay_bg)
        row_bg.addWidget(self.btn_overlay_bg)
        row_bg.addWidget(self.btn_overlay_bg_clear)
        row_bg.addStretch(1)
        overlay_lay.addLayout(row_bg)

        row_bg2 = QHBoxLayout()
        row_bg2.addWidget(QLabel("전체 크기:"))
        self.sp_overlay_scale = QSpinBox()
        self.sp_overlay_scale.setRange(50, 200)
        self.sp_overlay_scale.setSuffix("%")
        self.sp_overlay_scale.setValue(int(float(getattr(self.cfg, "overlay_ui_scale", 1.0) or 1.0) * 100))
        _tt(self.sp_overlay_scale, "타이머 UI 전체 크기를 확대/축소합니다.")
        self.sl_overlay_scale = QSlider(Qt.Orientation.Horizontal)
        self.sl_overlay_scale.setRange(50, 200)
        self.sl_overlay_scale.setFixedWidth(130)
        self.sl_overlay_scale.setValue(self.sp_overlay_scale.value())
        self.lbl_overlay_scale = QLabel(f"{self.sl_overlay_scale.value()}%")
        self.lbl_overlay_scale.setFixedWidth(42)
        self.sp_browser_overlay_scale = QSpinBox()
        self.sp_browser_overlay_scale.setRange(25, 400)
        self.sp_browser_overlay_scale.setSuffix("%")
        self.sp_browser_overlay_scale.setValue(int(float(getattr(self.cfg, "browser_overlay_scale", 1.0) or 1.0) * 100))
        self.sp_browser_overlay_scale.setFixedWidth(76)
        _tt(self.sp_browser_overlay_scale, "OBS browser overlay only scale. 100% keeps current browser size.")
        _tt(self.sl_overlay_scale, "타이머 UI 전체 크기를 확대/축소합니다.")
        self.sl_overlay_scale.valueChanged.connect(lambda v: self.sp_overlay_scale.setValue(int(v)) if self.sp_overlay_scale.value() != int(v) else None)
        self.sp_overlay_scale.valueChanged.connect(lambda v: self.sl_overlay_scale.setValue(int(v)) if self.sl_overlay_scale.value() != int(v) else None)
        self.sp_overlay_scale.valueChanged.connect(lambda v: self.lbl_overlay_scale.setText(f"{int(v)}%"))
        self.sl_overlay_scale.valueChanged.connect(lambda v: self.lbl_overlay_scale.setText(f"{int(v)}%"))
        self.sp_overlay_scale.valueChanged.connect(lambda _v: self._apply_overlay_scale_live())
        self.sl_overlay_scale.valueChanged.connect(lambda _v: self._apply_overlay_scale_live())
        self.sp_browser_overlay_scale.valueChanged.connect(lambda _v: self._apply_browser_overlay_scale_live())
        row_bg2.addWidget(self.sp_overlay_scale)
        row_bg2.addWidget(self.sl_overlay_scale)
        row_bg2.addWidget(self.lbl_overlay_scale)
        row_bg2.addSpacing(8)
        row_bg2.addWidget(QLabel("Browser"))
        row_bg2.addWidget(self.sp_browser_overlay_scale)
        row_bg2.addSpacing(8)
        row_bg2.addWidget(QLabel("배경 투명도"))
        self.sl_overlay_opacity = QSlider(Qt.Orientation.Horizontal)
        self.sl_overlay_opacity.setRange(0, 100)
        self.sl_overlay_opacity.setValue(int((1.0 - float(getattr(self.cfg, "overlay_bg_opacity", 0.0))) * 100))
        self.lbl_overlay_opacity = QLabel(f"{self.sl_overlay_opacity.value()}%")
        _tt(self.sl_overlay_opacity, "오버레이 배경 투명도를 조절합니다.")
        self.sl_overlay_opacity.valueChanged.connect(lambda v: self.lbl_overlay_opacity.setText(f"{int(v)}%"))
        self.sl_overlay_opacity.valueChanged.connect(lambda _v: self._apply_overlay_bg_live())
        row_bg2.addWidget(self.sl_overlay_opacity, 1)
        row_bg2.addWidget(self.lbl_overlay_opacity)
        overlay_lay.addLayout(row_bg2)

        timer_text_group = QGroupBox("타이머/라운드 텍스트")
        timer_text_grid = QGridLayout(timer_text_group)
        timer_text_grid.setContentsMargins(8, 8, 8, 8)
        timer_text_grid.setHorizontalSpacing(8)
        timer_text_grid.setVerticalSpacing(6)

        self.sp_overlay_timer_font = QSpinBox()
        self.sp_overlay_timer_font.setRange(24, 96)
        self.sp_overlay_timer_font.setSuffix(" px")
        self.sp_overlay_timer_font.setValue(int(getattr(self.cfg, "overlay_timer_font_size", 54) or 54))
        self.sp_overlay_timer_font.setFixedWidth(86)

        self.sp_overlay_timer_x = QSpinBox()
        self.sp_overlay_timer_x.setRange(-160, 160)
        self.sp_overlay_timer_x.setSuffix(" px")
        self.sp_overlay_timer_x.setValue(int(getattr(self.cfg, "overlay_timer_x", 0) or 0))
        self.sp_overlay_timer_x.setFixedWidth(86)

        self.sp_overlay_timer_y = QSpinBox()
        self.sp_overlay_timer_y.setRange(-80, 120)
        self.sp_overlay_timer_y.setSuffix(" px")
        self.sp_overlay_timer_y.setValue(int(getattr(self.cfg, "overlay_timer_y", 0) or 0))
        self.sp_overlay_timer_y.setFixedWidth(86)

        self.sp_overlay_round_font = QSpinBox()
        self.sp_overlay_round_font.setRange(6, 40)
        self.sp_overlay_round_font.setSuffix(" px")
        self.sp_overlay_round_font.setValue(int(getattr(self.cfg, "overlay_round_font_size", 11) or 11))
        self.sp_overlay_round_font.setFixedWidth(86)

        self.sp_overlay_round_x = QSpinBox()
        self.sp_overlay_round_x.setRange(-160, 160)
        self.sp_overlay_round_x.setSuffix(" px")
        self.sp_overlay_round_x.setValue(int(getattr(self.cfg, "overlay_round_x", 0) or 0))
        self.sp_overlay_round_x.setFixedWidth(86)

        self.sp_overlay_round_y = QSpinBox()
        self.sp_overlay_round_y.setRange(-80, 120)
        self.sp_overlay_round_y.setSuffix(" px")
        self.sp_overlay_round_y.setValue(int(getattr(self.cfg, "overlay_round_y", 0) or 0))
        self.sp_overlay_round_y.setFixedWidth(86)

        timer_text_grid.addWidget(QLabel("Timer size"), 0, 0)
        timer_text_grid.addWidget(self.sp_overlay_timer_font, 0, 1)
        timer_text_grid.addWidget(QLabel("Timer X"), 0, 2)
        timer_text_grid.addWidget(self.sp_overlay_timer_x, 0, 3)
        timer_text_grid.addWidget(QLabel("Timer Y"), 0, 4)
        timer_text_grid.addWidget(self.sp_overlay_timer_y, 0, 5)
        timer_text_grid.addWidget(QLabel("Round size"), 1, 0)
        timer_text_grid.addWidget(self.sp_overlay_round_font, 1, 1)
        timer_text_grid.addWidget(QLabel("Round X"), 1, 2)
        timer_text_grid.addWidget(self.sp_overlay_round_x, 1, 3)
        timer_text_grid.addWidget(QLabel("Round Y"), 1, 4)
        timer_text_grid.addWidget(self.sp_overlay_round_y, 1, 5)
        timer_text_grid.setColumnStretch(6, 1)

        for _w in (
            self.sp_overlay_timer_font,
            self.sp_overlay_timer_x,
            self.sp_overlay_timer_y,
            self.sp_overlay_round_font,
            self.sp_overlay_round_x,
            self.sp_overlay_round_y,
        ):
            _w.valueChanged.connect(lambda _v: self._apply_overlay_timer_layout_live())
        overlay_lay.addWidget(timer_text_group)

        row_preset_style = QHBoxLayout()
        row_preset_style.addWidget(QLabel("오버레이 스타일:"))
        self.cmb_overlay_style_mode = QComboBox()
        self.cmb_overlay_style_mode.addItem("기존 오버레이", "classic")
        self.cmb_overlay_style_mode.addItem("철권8 스타일", "tekken8")
        current_overlay_preset = str(getattr(self.cfg, "overlay_preset", "classic") or "classic").lower()
        idx = self.cmb_overlay_style_mode.findData(current_overlay_preset)
        self.cmb_overlay_style_mode.setCurrentIndex(idx if idx >= 0 else 0)
        _tt(self.cmb_overlay_style_mode, "기존 오버레이를 보존한 채 새 HUD 스타일만 전환합니다.")
        self.cmb_overlay_style_mode.currentIndexChanged.connect(lambda _i: self._apply_overlay_preset_mode_live())
        row_preset_style.addWidget(self.cmb_overlay_style_mode)
        row_preset_style.addStretch(1)
        overlay_lay.addLayout(row_preset_style)

        row_bg3 = QHBoxLayout()
        row_bg3.addWidget(QLabel("초상화 오버레이 마스크:"))
        self.cmb_overlay_avatar = QComboBox()
        self.cmb_overlay_avatar.addItems(["사각형", "원형", "육각형"])
        _tt(self.cmb_overlay_avatar, "초상화 마스크 모양을 선택합니다.")
        mask = _normalize_player_mask(getattr(self.cfg, "overlay_player_mask", "square"))
        if mask == "circle":
            self.cmb_overlay_avatar.setCurrentText("원형")
        elif mask == "hex":
            self.cmb_overlay_avatar.setCurrentText("육각형")
        else:
            self.cmb_overlay_avatar.setCurrentText("사각형")
        self.cmb_overlay_avatar.currentIndexChanged.connect(lambda _i: self._apply_overlay_mask_live())
        row_bg3.addWidget(self.cmb_overlay_avatar)
        row_bg3.addStretch(1)
        overlay_lay.addLayout(row_bg3)

        row_bg4 = QHBoxLayout()
        row_bg4.addWidget(QLabel("오버레이 표시:"))
        self.chk_overlay_round = QCheckBox("Round")
        self.chk_overlay_time = QCheckBox("타이머")
        self.chk_overlay_blue_img = QCheckBox("BLUE 사진")
        self.chk_overlay_blue_name = QCheckBox("BLUE 이름")
        self.chk_overlay_red_img = QCheckBox("RED 사진")
        self.chk_overlay_red_name = QCheckBox("RED 이름")
        self.chk_overlay_arena_name = QCheckBox("Arena")
        self.chk_overlay_flags = QCheckBox("국기")
        self.chk_overlay_cinematic = QCheckBox("전체화면 연출")
        _tt(self.chk_overlay_round, "라운드 박스 표시 여부")
        _tt(self.chk_overlay_time, "타이머 박스 표시 여부")
        _tt(self.chk_overlay_blue_img, "블루 초상화 표시 여부")
        _tt(self.chk_overlay_blue_name, "블루 닉네임 표시 여부")
        _tt(self.chk_overlay_red_img, "레드 초상화 표시 여부")
        _tt(self.chk_overlay_red_name, "레드 닉네임 표시 여부")
        _tt(self.chk_overlay_arena_name, "경기장 이름 표시 여부")
        _tt(self.chk_overlay_flags, "철권8 스타일에서 국기 표시 여부")
        _tt(self.chk_overlay_cinematic, "VS, ROUND/READY/FIGHT, KO/TKO 전체화면 연출 표시 여부")
        self.chk_overlay_round.setChecked(bool(getattr(self.cfg, "overlay_show_round", True)))
        self.chk_overlay_time.setChecked(bool(getattr(self.cfg, "overlay_show_time", True)))
        self.chk_overlay_blue_img.setChecked(bool(getattr(self.cfg, "overlay_show_blue_img", True)))
        self.chk_overlay_blue_name.setChecked(bool(getattr(self.cfg, "overlay_show_blue_name", True)))
        self.chk_overlay_red_img.setChecked(bool(getattr(self.cfg, "overlay_show_red_img", True)))
        self.chk_overlay_red_name.setChecked(bool(getattr(self.cfg, "overlay_show_red_name", True)))
        self.chk_overlay_arena_name.setChecked(bool(getattr(self.cfg, "overlay_show_arena_name", True)))
        self.chk_overlay_flags.setChecked(bool(getattr(self.cfg, "overlay_show_flags", True)))
        self.chk_overlay_cinematic.setChecked(bool(getattr(self.cfg, "overlay_show_cinematic", True)))
        self.chk_overlay_round.stateChanged.connect(lambda _s: self._apply_overlay_elements_live())
        self.chk_overlay_time.stateChanged.connect(lambda _s: self._apply_overlay_elements_live())
        self.chk_overlay_blue_img.stateChanged.connect(lambda _s: self._apply_overlay_elements_live())
        self.chk_overlay_blue_name.stateChanged.connect(lambda _s: self._apply_overlay_elements_live())
        self.chk_overlay_red_img.stateChanged.connect(lambda _s: self._apply_overlay_elements_live())
        self.chk_overlay_red_name.stateChanged.connect(lambda _s: self._apply_overlay_elements_live())
        self.chk_overlay_arena_name.stateChanged.connect(lambda _s: self._apply_overlay_elements_live())
        self.chk_overlay_flags.stateChanged.connect(lambda _s: self._apply_overlay_elements_live())
        self.chk_overlay_cinematic.stateChanged.connect(lambda _s: self._apply_overlay_elements_live())
        row_bg4.addWidget(self.chk_overlay_round)
        row_bg4.addWidget(self.chk_overlay_time)
        row_bg4.addWidget(self.chk_overlay_blue_img)
        row_bg4.addWidget(self.chk_overlay_blue_name)
        row_bg4.addWidget(self.chk_overlay_red_img)
        row_bg4.addWidget(self.chk_overlay_red_name)
        row_bg4.addWidget(self.chk_overlay_arena_name)
        row_bg4.addWidget(self.chk_overlay_flags)
        row_bg4.addWidget(self.chk_overlay_cinematic)
        row_bg4.addStretch(1)
        overlay_lay.addLayout(row_bg4)

        vs_bg_group = QGroupBox("철권8 VS 오버레이 배경")
        vs_bg_lay = QGridLayout(vs_bg_group)
        self.le_overlay_vs_bg = QLineEdit(str(getattr(self.cfg, "overlay_vs_bg_path", "") or ""))
        self.le_overlay_vs_bg.setPlaceholderText("기본 배경 이미지 파일")
        self.btn_overlay_vs_bg_browse = QPushButton("기본 배경 선택")
        self.btn_overlay_vs_bg_clear = QPushButton("지우기")
        self.btn_overlay_vs_bg_browse.clicked.connect(self._browse_overlay_vs_bg)
        self.btn_overlay_vs_bg_clear.clicked.connect(lambda: self.le_overlay_vs_bg.setText(""))
        vs_bg_lay.addWidget(QLabel("기본"), 0, 0)
        vs_bg_lay.addWidget(self.le_overlay_vs_bg, 0, 1, 1, 4)
        vs_bg_lay.addWidget(self.btn_overlay_vs_bg_browse, 0, 5)
        vs_bg_lay.addWidget(self.btn_overlay_vs_bg_clear, 0, 6)
        self.sl_overlay_vs_bg_opacity = QSlider(Qt.Orientation.Horizontal)
        self.sl_overlay_vs_bg_opacity.setRange(0, 100)
        self.sl_overlay_vs_bg_opacity.setValue(int(max(0.0, min(1.0, float(getattr(self.cfg, "overlay_vs_bg_opacity", 1.0) or 1.0))) * 100))
        self.lbl_overlay_vs_bg_opacity = QLabel(f"{self.sl_overlay_vs_bg_opacity.value()}%")
        self.sl_overlay_vs_bg_opacity.valueChanged.connect(lambda v: self.lbl_overlay_vs_bg_opacity.setText(f"{int(v)}%"))
        vs_bg_lay.addWidget(QLabel(""), 1, 0)
        vs_bg_lay.addWidget(self.sl_overlay_vs_bg_opacity, 1, 1, 1, 4)
        vs_bg_lay.addWidget(self.lbl_overlay_vs_bg_opacity, 1, 5)
        self.sp_overlay_vs_hold_sec = QDoubleSpinBox()
        self.sp_overlay_vs_hold_sec.setRange(0.5, 15.0)
        self.sp_overlay_vs_hold_sec.setDecimals(2)
        self.sp_overlay_vs_hold_sec.setSingleStep(0.25)
        self.sp_overlay_vs_hold_sec.setSuffix("")
        self.sp_overlay_vs_hold_sec.setValue(max(0.5, min(15.0, float(getattr(self.cfg, "overlay_vs_hold_sec", 2.85) or 2.85))))
        vs_bg_lay.addWidget(QLabel("유지시간"), 1, 6)
        vs_bg_lay.addWidget(self.sp_overlay_vs_hold_sec, 1, 7)
        self.txt_overlay_vs_bg_map = QTextEdit()
        self.txt_overlay_vs_bg_map.setPlaceholderText("경기장명=이미지파일경로\n예: ORTIZ FARM=image\\ortiz.png")
        self.txt_overlay_vs_bg_map.setFixedHeight(70)
        self.txt_overlay_vs_bg_map.setPlainText(self._format_overlay_vs_bg_map(getattr(self.cfg, "overlay_vs_bg_by_arena", {}) or {}))
        vs_bg_lay.addWidget(QLabel("경기장별"), 2, 0)
        vs_bg_lay.addWidget(self.txt_overlay_vs_bg_map, 2, 1, 1, 7)
        self.le_overlay_vs_bg.textChanged.connect(lambda _v: self._apply_overlay_vs_bg_live())
        self.sl_overlay_vs_bg_opacity.valueChanged.connect(lambda _v: self._apply_overlay_vs_bg_live())
        self.sp_overlay_vs_hold_sec.valueChanged.connect(lambda _v: self._apply_overlay_vs_bg_live())
        self.txt_overlay_vs_bg_map.textChanged.connect(self._apply_overlay_vs_bg_live)
        _tt(self.le_overlay_vs_bg, "경기장 값이 없거나 매핑되지 않았을 때 사용할 VS 기본 배경입니다.")
        _tt(self.sp_overlay_vs_hold_sec, "VS 오버레이가 화면에 머무는 시간입니다. 등장/퇴장 애니메이션 시간은 별도로 유지됩니다.")
        _tt(self.txt_overlay_vs_bg_map, "한 줄에 경기장명=이미지파일경로 형식으로 입력합니다. 로그 경기장명과 일치하면 해당 이미지가 뜹니다.")
        overlay_lay.addWidget(vs_bg_group)

        browser_group = QGroupBox("OBS 브라우저 출력")
        browser_lay = QGridLayout(browser_group)
        browser_url = "http://127.0.0.1:17872/overlay"
        try:
            if self.controller and hasattr(self.controller, "browser_overlay"):
                browser_url = str(self.controller.browser_overlay.url)
        except Exception:
            pass
        self.le_browser_overlay_url = QLineEdit(browser_url)
        self.le_browser_overlay_url.setReadOnly(True)
        self.btn_browser_overlay_copy = QPushButton("URL 복사")
        self.btn_browser_overlay_copy.clicked.connect(self._copy_browser_overlay_url)
        self.btn_browser_overlay_open = QPushButton("열기")
        self.btn_browser_overlay_open.clicked.connect(self._open_browser_overlay_url)
        self.sp_browser_overlay_poll = QSpinBox()
        self.sp_browser_overlay_poll.setRange(16, 1000)
        self.sp_browser_overlay_poll.setSingleStep(10)
        self.sp_browser_overlay_poll.setSuffix(" ms")
        self.sp_browser_overlay_poll.setValue(max(16, min(1000, int(getattr(self.cfg, "browser_overlay_poll_ms", 50) or 50))))
        self.sp_browser_overlay_poll.valueChanged.connect(lambda _v: self._apply_browser_overlay_settings())
        self.sp_browser_fullscreen_fx_intensity = QSpinBox()
        self.sp_browser_fullscreen_fx_intensity.setRange(0, 300)
        self.sp_browser_fullscreen_fx_intensity.setSingleStep(10)
        self.sp_browser_fullscreen_fx_intensity.setSuffix("%")
        self.sp_browser_fullscreen_fx_intensity.setValue(int(max(0.0, min(3.0, float(getattr(self.cfg, "browser_fullscreen_fx_intensity", 1.6) or 1.6))) * 100))
        self.sp_browser_fullscreen_fx_intensity.valueChanged.connect(lambda _v: self._apply_browser_overlay_settings())
        self.chk_browser_overlay_output_only = QCheckBox("전체화면 효과는 OBS 브라우저에만 표시")
        self.chk_browser_overlay_output_only.setChecked(bool(getattr(self.cfg, "browser_overlay_output_only", True)))
        self.chk_browser_overlay_output_only.stateChanged.connect(lambda _s: self._apply_browser_overlay_settings())
        self.chk_qml_preview_enabled = QCheckBox("QML HUD 미리보기 사용")
        self.chk_qml_preview_enabled.setChecked(bool(getattr(self.cfg, "qml_preview_enabled", True)))
        self.chk_qml_preview_enabled.stateChanged.connect(lambda _s: self._apply_browser_overlay_settings())
        self.chk_qml_effects_enabled = QCheckBox("QML 이펙트 사용")
        self.chk_qml_effects_enabled.setChecked(bool(getattr(self.cfg, "qml_effects_enabled", False)))
        self.chk_qml_effects_enabled.stateChanged.connect(lambda _s: self._apply_browser_overlay_settings())
        is_browser_running = bool(self.controller and getattr(self.controller, "browser_overlay", None))
        self.lbl_browser_overlay_status = QLabel("")
        self.lbl_browser_overlay_status.setStyleSheet("color:#0f766e;font-weight:700;" if is_browser_running else "color:#64748b;")
        browser_lay.addWidget(QLabel("OBS URL"), 0, 0)
        browser_lay.addWidget(self.le_browser_overlay_url, 0, 1, 1, 3)
        browser_lay.addWidget(self.btn_browser_overlay_open, 0, 4)
        browser_lay.addWidget(self.btn_browser_overlay_copy, 0, 5)
        browser_lay.addWidget(QLabel("갱신 주기"), 1, 0)
        browser_lay.addWidget(self.sp_browser_overlay_poll, 1, 1)
        browser_lay.addWidget(QLabel("상태"), 1, 2)
        browser_lay.addWidget(self.lbl_browser_overlay_status, 1, 3, 1, 2)
        browser_lay.addWidget(QLabel("전체화면 효과 강도"), 1, 5)
        browser_lay.addWidget(self.sp_browser_fullscreen_fx_intensity, 1, 6)
        browser_lay.addWidget(self.chk_browser_overlay_output_only, 2, 0, 1, 6)
        browser_lay.addWidget(self.chk_qml_preview_enabled, 3, 0, 1, 6)
        browser_lay.addWidget(self.chk_qml_effects_enabled, 4, 0, 1, 6)
        _tt(self.le_browser_overlay_url, "OBS 브라우저 소스 주소입니다. timerauto 실행 중에 사용하세요.")
        _tt(self.sp_browser_overlay_poll, "timerauto 상태를 OBS 브라우저 소스에 갱신하는 주기입니다. 짧을수록 반응은 빠르지만 CPU 사용량이 늘 수 있습니다.")
        _tt(self.sp_browser_fullscreen_fx_intensity, "다운/KO/TKO 때 브라우저 화면 전체를 덮는 플래시와 충격 효과의 강도입니다.")
        _tt(self.chk_browser_overlay_output_only, "Show fullscreen effects only in the OBS browser source, not on the local Qt overlay.")
        _tt(self.chk_qml_preview_enabled, "끄면 로컬 QML HUD 창을 숨기고 OBS 브라우저 오버레이만 렌더링합니다.")
        overlay_lay.addWidget(browser_group)

        row_preset = QHBoxLayout()
        row_preset.addWidget(QLabel("오버레이 프리셋:"))
        self.btn_overlay_save = QPushButton("저장")
        self.btn_overlay_load = QPushButton("불러오기")
        self.btn_overlay_save.clicked.connect(self._save_overlay_preset)
        self.btn_overlay_load.clicked.connect(self._load_overlay_preset)
        _tt(self.btn_overlay_save, "현재 오버레이 설정을 프리셋으로 저장합니다.")
        _tt(self.btn_overlay_load, "프리셋 파일을 불러와 적용합니다.")
        row_preset.addWidget(self.btn_overlay_save)
        row_preset.addWidget(self.btn_overlay_load)
        row_preset.addStretch(1)
        overlay_lay.addLayout(row_preset)

        row_custom = QHBoxLayout()
        self.le_overlay_custom_text = QLineEdit()
        self.le_overlay_custom_text.setPlaceholderText("CUSTOM")
        _tt(self.le_overlay_custom_text, "새 커스텀 요소에 들어갈 텍스트를 입력합니다.")
        row_custom.addWidget(self.le_overlay_custom_text, 1)
        self.btn_overlay_custom_add = QPushButton("추가")
        self.btn_overlay_custom_add.clicked.connect(self._add_overlay_custom_element)
        _tt(self.btn_overlay_custom_add, "입력한 텍스트로 커스텀 요소를 추가합니다.")
        row_custom.addWidget(self.btn_overlay_custom_add)
        row_custom.addStretch(1)

        self._overlay_custom_loading = False
        custom_group = QGroupBox("커스텀 요소 설정")
        custom_lay = QGridLayout(custom_group)
        self.lst_overlay_custom = QListWidget()
        self.lst_overlay_custom.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.lst_overlay_custom.currentRowChanged.connect(lambda _i: self._load_overlay_custom_selected())
        _tt(self.lst_overlay_custom, "추가된 커스텀 요소 목록입니다. 선택 후 오른쪽에서 편집합니다.")
        custom_lay.addLayout(row_custom, 0, 0, 1, 2)
        custom_lay.addWidget(QLabel("요소 목록"), 1, 0)
        self.lst_overlay_custom.setMinimumWidth(220)
        self.lst_overlay_custom.setMinimumHeight(180)
        custom_lay.addWidget(self.lst_overlay_custom, 2, 0, 7, 1)
        self.btn_overlay_custom_delete = QPushButton("삭제")
        self.btn_overlay_custom_delete.clicked.connect(self._delete_overlay_custom_selected)
        _tt(self.btn_overlay_custom_delete, "선택된 커스텀 요소를 삭제합니다.")
        custom_lay.addWidget(self.btn_overlay_custom_delete, 9, 0)

        style_lay = QGridLayout()
        custom_lay.addLayout(style_lay, 1, 1, 9, 8)
        custom_lay.setColumnStretch(0, 1)
        custom_lay.setColumnStretch(1, 4)
        custom_lay.setRowStretch(2, 1)
        custom_lay.setRowStretch(8, 1)

        self.le_overlay_custom_text_edit = QLineEdit()
        self.le_overlay_custom_text_edit.editingFinished.connect(self._apply_overlay_custom_edit)
        _tt(self.le_overlay_custom_text_edit, "선택한 커스텀 요소의 표시 텍스트입니다.")
        style_lay.addWidget(QLabel(""), 0, 0)
        style_lay.addWidget(self.le_overlay_custom_text_edit, 0, 1, 1, 5)

        self.chk_overlay_custom_visible = QCheckBox("표시")
        self.chk_overlay_custom_visible.stateChanged.connect(lambda _s: self._apply_overlay_custom_edit())
        _tt(self.chk_overlay_custom_visible, "선택한 커스텀 요소를 표시/숨김 처리합니다.")
        style_lay.addWidget(self.chk_overlay_custom_visible, 1, 1)

        def _pick_color(le: QLineEdit):
            c = QColor(le.text() or "#000000")
            dlg = QColorDialog(c, self)
            dlg.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
            if dlg.exec():
                q = dlg.currentColor()
                if q.isValid():
                    le.setText(q.name())
                    self._apply_overlay_custom_edit()

        self.le_overlay_custom_bg = QLineEdit()
        self.le_overlay_custom_bg.setVisible(False)
        self.btn_overlay_custom_bg = QPushButton("")
        self.btn_overlay_custom_bg.setFixedSize(26, 18)
        self._attach_color_button(self.le_overlay_custom_bg, self.btn_overlay_custom_bg)
        self.btn_overlay_custom_bg.clicked.connect(lambda: _pick_color(self.le_overlay_custom_bg))
        self.le_overlay_custom_bg.editingFinished.connect(self._apply_overlay_custom_edit)
        _tt(self.btn_overlay_custom_bg, "커스텀 요소 배경색을 선택합니다.")
        style_lay.addWidget(QLabel(""), 2, 0)
        style_lay.addWidget(self.le_overlay_custom_bg, 2, 1)
        style_lay.addWidget(self.btn_overlay_custom_bg, 2, 2)

        self.le_overlay_custom_text_color = QLineEdit()
        self.le_overlay_custom_text_color.setVisible(False)
        self.btn_overlay_custom_text_color = QPushButton("")
        self.btn_overlay_custom_text_color.setFixedSize(26, 18)
        self._attach_color_button(self.le_overlay_custom_text_color, self.btn_overlay_custom_text_color)
        self.btn_overlay_custom_text_color.clicked.connect(lambda: _pick_color(self.le_overlay_custom_text_color))
        self.le_overlay_custom_text_color.editingFinished.connect(self._apply_overlay_custom_edit)
        _tt(self.btn_overlay_custom_text_color, "커스텀 요소 텍스트 색상을 선택합니다.")
        style_lay.addWidget(QLabel("텍스트색"), 4, 0)
        style_lay.addWidget(self.le_overlay_custom_text_color, 4, 1)
        style_lay.addWidget(self.btn_overlay_custom_text_color, 4, 2)

        self.le_overlay_custom_border_color = QLineEdit()
        self.le_overlay_custom_border_color.setVisible(False)
        self.btn_overlay_custom_border_color = QPushButton("")
        self.btn_overlay_custom_border_color.setFixedSize(26, 18)
        self._attach_color_button(self.le_overlay_custom_border_color, self.btn_overlay_custom_border_color)
        self.btn_overlay_custom_border_color.clicked.connect(lambda: _pick_color(self.le_overlay_custom_border_color))
        self.le_overlay_custom_border_color.editingFinished.connect(self._apply_overlay_custom_edit)
        _tt(self.btn_overlay_custom_border_color, "커스텀 요소 테두리 색상을 선택합니다.")
        style_lay.addWidget(QLabel("테두리색"), 3, 0)
        style_lay.addWidget(self.le_overlay_custom_border_color, 3, 1)
        style_lay.addWidget(self.btn_overlay_custom_border_color, 3, 2)

        self.sl_overlay_custom_bg_opacity = QSlider(Qt.Orientation.Horizontal)
        self.sl_overlay_custom_bg_opacity.setRange(0, 100)
        self.lbl_overlay_custom_bg_opacity = QLabel("0%")
        self.sl_overlay_custom_bg_opacity.valueChanged.connect(lambda v: self.lbl_overlay_custom_bg_opacity.setText(f"{int(v)}%"))
        self.sl_overlay_custom_bg_opacity.valueChanged.connect(lambda _v: self._apply_overlay_custom_edit())
        _tt(self.sl_overlay_custom_bg_opacity, "배경 투명도를 조절합니다.")
        style_lay.addWidget(QLabel("불투명도"), 2, 3)
        style_lay.addWidget(self.sl_overlay_custom_bg_opacity, 2, 4)
        style_lay.addWidget(self.lbl_overlay_custom_bg_opacity, 2, 5)

        self.sl_overlay_custom_text_opacity = QSlider(Qt.Orientation.Horizontal)
        self.sl_overlay_custom_text_opacity.setRange(0, 100)
        self.lbl_overlay_custom_text_opacity = QLabel("0%")
        self.sl_overlay_custom_text_opacity.valueChanged.connect(lambda v: self.lbl_overlay_custom_text_opacity.setText(f"{int(v)}%"))
        self.sl_overlay_custom_text_opacity.valueChanged.connect(lambda _v: self._apply_overlay_custom_edit())
        _tt(self.sl_overlay_custom_text_opacity, "텍스트 투명도를 조절합니다.")
        style_lay.addWidget(QLabel("불투명도"), 4, 3)
        style_lay.addWidget(self.sl_overlay_custom_text_opacity, 4, 4)
        style_lay.addWidget(self.lbl_overlay_custom_text_opacity, 4, 5)

        self.sl_overlay_custom_border_opacity = QSlider(Qt.Orientation.Horizontal)
        self.sl_overlay_custom_border_opacity.setRange(0, 100)
        self.lbl_overlay_custom_border_opacity = QLabel("0%")
        self.sl_overlay_custom_border_opacity.valueChanged.connect(lambda v: self.lbl_overlay_custom_border_opacity.setText(f"{int(v)}%"))
        self.sl_overlay_custom_border_opacity.valueChanged.connect(lambda _v: self._apply_overlay_custom_edit())
        _tt(self.sl_overlay_custom_border_opacity, "테두리 투명도를 조절합니다.")
        style_lay.addWidget(QLabel("불투명도"), 3, 5)
        style_lay.addWidget(self.sl_overlay_custom_border_opacity, 3, 6)
        style_lay.addWidget(self.lbl_overlay_custom_border_opacity, 3, 7)

        self.sp_overlay_custom_border_width = QSpinBox()
        self.sp_overlay_custom_border_width.setRange(0, 12)
        self.sp_overlay_custom_border_width.valueChanged.connect(lambda _v: self._apply_overlay_custom_edit())
        _tt(self.sp_overlay_custom_border_width, "테두리 두께(px).")
        style_lay.addWidget(QLabel("두께"), 3, 3)
        style_lay.addWidget(self.sp_overlay_custom_border_width, 3, 4)

        self.cmb_overlay_custom_font = QFontComboBox()
        self.cmb_overlay_custom_font.currentFontChanged.connect(lambda _f: self._apply_overlay_custom_edit())
        _tt(self.cmb_overlay_custom_font, "텍스트 글꼴을 선택합니다.")
        style_lay.addWidget(QLabel(""), 5, 0)
        style_lay.addWidget(self.cmb_overlay_custom_font, 5, 1, 1, 2)

        self.sp_overlay_custom_font_size = QSpinBox()
        self.sp_overlay_custom_font_size.setRange(0, 200)
        self.sp_overlay_custom_font_size.valueChanged.connect(lambda _v: self._apply_overlay_custom_edit())
        _tt(self.sp_overlay_custom_font_size, "텍스트 크기(px).")
        style_lay.addWidget(QLabel("크기"), 5, 3)
        style_lay.addWidget(self.sp_overlay_custom_font_size, 5, 4)

        self.chk_overlay_custom_font_bold = QCheckBox("굵게")
        self.chk_overlay_custom_font_bold.stateChanged.connect(lambda _s: self._apply_overlay_custom_edit())
        _tt(self.chk_overlay_custom_font_bold, "굵은 글씨로 표시합니다.")
        style_lay.addWidget(self.chk_overlay_custom_font_bold, 5, 5)

        self.sp_overlay_custom_font_weight = QSpinBox()
        self.sp_overlay_custom_font_weight.setRange(100, 900)
        self.sp_overlay_custom_font_weight.setSingleStep(100)
        self.sp_overlay_custom_font_weight.valueChanged.connect(lambda _v: self._apply_overlay_custom_edit())
        _tt(self.sp_overlay_custom_font_weight, "글꼴 두께(굵기) 값을 조절합니다.")
        style_lay.addWidget(QLabel("굵기"), 5, 6)
        style_lay.addWidget(self.sp_overlay_custom_font_weight, 5, 7)

        self._overlay_custom_controls = [
            self.le_overlay_custom_text_edit,
            self.chk_overlay_custom_visible,
            self.le_overlay_custom_bg,
            self.btn_overlay_custom_bg,
            self.le_overlay_custom_text_color,
            self.btn_overlay_custom_text_color,
            self.le_overlay_custom_border_color,
            self.btn_overlay_custom_border_color,
            self.sl_overlay_custom_bg_opacity,
            self.sl_overlay_custom_text_opacity,
            self.sl_overlay_custom_border_opacity,
            self.sp_overlay_custom_border_width,
            self.cmb_overlay_custom_font,
            self.sp_overlay_custom_font_size,
            self.chk_overlay_custom_font_bold,
            self.sp_overlay_custom_font_weight,
        ]
        self._set_overlay_custom_controls_enabled(False)
        overlay_lay.addWidget(custom_group)
        self._refresh_overlay_custom_list()

        self._overlay_style_widgets = {}

        def _build_style_group(title: str, key: str):
            grp = QGroupBox(title)
            glay = QGridLayout(grp)
            style = self._overlay_style_for_key(key)

            bg_label = QLabel("")
            bg_color = QLineEdit(str(style.get("bg_color", "#000000")))
            bg_color.setVisible(False)
            btn_bg = QPushButton("색상")
            btn_bg.setFixedSize(26, 18)
            btn_bg.setText("")
            self._attach_color_button(bg_color, btn_bg)
            btn_bg_clear = QPushButton("투명")
            def _pick_bg():
                c = QColor(bg_color.text() or "#000000")
                dlg = QColorDialog(c, self)
                dlg.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
                if dlg.exec():
                    q = dlg.currentColor()
                    if q.isValid():
                        bg_color.setText(q.name())
            btn_bg.clicked.connect(_pick_bg)
            btn_bg_clear.clicked.connect(lambda: bg_color.setText("transparent"))
            bg_opacity = QSlider(Qt.Orientation.Horizontal)
            bg_opacity.setRange(0, 100)
            bg_opacity.setValue(int(float(style.get("bg_opacity", 1.0)) * 100))
            bg_opacity_val = QLabel(f"{bg_opacity.value()}%")
            bg_opacity.valueChanged.connect(lambda v: bg_opacity_val.setText(f"{int(v)}%"))
            _tt(btn_bg, "배경색을 선택합니다.")
            _tt(btn_bg_clear, "배경을 투명으로 설정합니다.")
            _tt(bg_opacity, "배경 투명도를 조절합니다.")

            border_label = QLabel("테두리색")
            border_color = QLineEdit(str(style.get("border_color", "#000000")))
            border_color.setVisible(False)
            btn_border = QPushButton("색상")
            btn_border.setFixedSize(26, 18)
            btn_border.setText("")
            self._attach_color_button(border_color, btn_border)
            def _pick_border():
                c = QColor(border_color.text() or "#000000")
                dlg = QColorDialog(c, self)
                dlg.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
                if dlg.exec():
                    q = dlg.currentColor()
                    if q.isValid():
                        border_color.setText(q.name())
            btn_border.clicked.connect(_pick_border)
            border_width = QSpinBox()
            border_width.setRange(0, 12)
            border_width.setValue(int(style.get("border_width", 1)))
            border_opacity = QSlider(Qt.Orientation.Horizontal)
            border_opacity.setRange(0, 100)
            border_opacity.setValue(int(float(style.get("border_opacity", 1.0)) * 100))
            border_opacity_val = QLabel(f"{border_opacity.value()}%")
            border_opacity.valueChanged.connect(lambda v: border_opacity_val.setText(f"{int(v)}%"))
            _tt(btn_border, "테두리 색상을 선택합니다.")
            _tt(border_width, "테두리 두께(px).")
            _tt(border_opacity, "테두리 투명도를 조절합니다.")

            text_label = QLabel("")
            text_color = QLineEdit(str(style.get("text_color", "#ffffff")))
            text_color.setVisible(False)
            btn_text = QPushButton("색상")
            btn_text.setFixedSize(26, 18)
            btn_text.setText("")
            self._attach_color_button(text_color, btn_text)
            def _pick_text():
                c = QColor(text_color.text() or "#ffffff")
                dlg = QColorDialog(c, self)
                dlg.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
                if dlg.exec():
                    q = dlg.currentColor()
                    if q.isValid():
                        text_color.setText(q.name())
            btn_text.clicked.connect(_pick_text)
            text_opacity = QSlider(Qt.Orientation.Horizontal)
            text_opacity.setRange(0, 100)
            text_opacity.setValue(int(float(style.get("text_opacity", 1.0)) * 100))
            text_opacity_val = QLabel(f"{text_opacity.value()}%")
            text_opacity.valueChanged.connect(lambda v: text_opacity_val.setText(f"{int(v)}%"))
            _tt(btn_text, "텍스트 색상을 선택합니다.")
            _tt(text_opacity, "텍스트 투명도를 조절합니다.")

            font_label = QLabel("")
            font_family = QFontComboBox()
            try:
                from PyQt6.QtGui import QFont
                font_family.setCurrentFont(QFont(str(style.get("font_family", ""))))
            except Exception:
                pass
            font_size = QSpinBox()
            font_size.setRange(0, 200)
            font_size.setValue(int(style.get("font_size", 0)))
            font_bold = QCheckBox("굵게")
            font_bold.setChecked(bool(style.get("font_bold", False)))
            font_weight = QSpinBox()
            font_weight.setRange(100, 900)
            font_weight.setSingleStep(100)
            font_weight.setValue(int(style.get("font_weight", 700)))
            _tt(font_family, "텍스트 글꼴을 선택합니다.")
            _tt(font_size, "텍스트 크기(px). 0이면 자동 크기.")
            _tt(font_bold, "굵은 글씨로 표시합니다.")
            _tt(font_weight, "글꼴 두께(굵기) 값을 조절합니다.")

            row = 0
            glay.addWidget(bg_label, row, 0)
            glay.addWidget(bg_color, row, 1)
            glay.addWidget(btn_bg, row, 2)
            glay.addWidget(btn_bg_clear, row, 3)
            glay.addWidget(QLabel("불투명도"), row, 4)
            glay.addWidget(bg_opacity, row, 5)
            glay.addWidget(bg_opacity_val, row, 6)
            row += 1

            glay.addWidget(border_label, row, 0)
            glay.addWidget(border_color, row, 1)
            glay.addWidget(btn_border, row, 2)
            glay.addWidget(QLabel("두께"), row, 3)
            glay.addWidget(border_width, row, 4)
            glay.addWidget(QLabel("불투명도"), row, 5)
            glay.addWidget(border_opacity, row, 6)
            glay.addWidget(border_opacity_val, row, 7)
            row += 1

            glay.addWidget(text_label, row, 0)
            glay.addWidget(text_color, row, 1)
            glay.addWidget(btn_text, row, 2)
            glay.addWidget(QLabel("불투명도"), row, 3)
            glay.addWidget(text_opacity, row, 4)
            glay.addWidget(text_opacity_val, row, 5)
            row += 1

            glay.addWidget(font_label, row, 0)
            glay.addWidget(font_family, row, 1, 1, 2)
            glay.addWidget(QLabel("\uD06C\uAE30(0=\uC790\uB3D9)"), row, 3)
            glay.addWidget(font_size, row, 4)
            glay.addWidget(font_bold, row, 5)
            glay.addWidget(QLabel("\uAD75\uAE30"), row, 6)
            glay.addWidget(font_weight, row, 7)
            row += 1

            badge_enabled = None
            badge_color = None
            btn_badge = None
            badge_width = None
            badge_height = None
            if key in ("blue_name", "red_name"):
                badge_enabled = QCheckBox("코너 마크 표시")
                badge_enabled.setChecked(bool(style.get("badge_enabled", True)))
                badge_color = QLineEdit(str(style.get("badge_color", "#3b82f6" if key == "blue_name" else "#ef4444")))
                badge_color.setVisible(False)
                btn_badge = QPushButton("색상")
                btn_badge.setFixedSize(26, 18)
                btn_badge.setText("")
                self._attach_color_button(badge_color, btn_badge)
                def _pick_badge():
                    c = QColor(badge_color.text() or ("#3b82f6" if key == "blue_name" else "#ef4444"))
                    dlg = QColorDialog(c, self)
                    dlg.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
                    if dlg.exec():
                        q = dlg.currentColor()
                        if q.isValid():
                            badge_color.setText(q.name())
                btn_badge.clicked.connect(_pick_badge)
                badge_width = QSpinBox()
                badge_width.setRange(2, 80)
                badge_width.setValue(int(style.get("badge_width", 10)))
                badge_height = QSpinBox()
                badge_height.setRange(2, 80)
                badge_height.setValue(int(style.get("badge_height", 14)))
                _tt(badge_enabled, "닉네임 옆 코너 색 표시를 켜거나 끕니다.")
                _tt(btn_badge, "코너 마크 색상을 선택합니다.")
                _tt(badge_width, "코너 마크 가로 크기(px).")
                _tt(badge_height, "코너 마크 세로 크기(px).")
                glay.addWidget(badge_height, row, 6)
                glay.addWidget(QLabel("위치"), row, 7)
                badge_side = QComboBox()
                badge_side.addItems(["왼쪽", "오른쪽"])
                side_val = style.get("badge_side", "left" if key == "blue_name" else "right")
                badge_side.setCurrentIndex(0 if side_val == "left" else 1)
                glay.addWidget(badge_side, row, 8)
                _tt(badge_side, "코너 마크가 닉네임 요소의 왼쪽에 나타날지 오른쪽에 나타날지 선택합니다.")

            self._overlay_style_widgets[key] = {
                "bg_color": bg_color,
                "bg_opacity": bg_opacity,
                "border_color": border_color,
                "border_opacity": border_opacity,
                "border_width": border_width,
                "text_color": text_color,
                "text_opacity": text_opacity,
                "font_family": font_family,
                "font_size": font_size,
                "font_bold": font_bold,
                "font_weight": font_weight,
            }
            if badge_enabled is not None:
                self._overlay_style_widgets[key]["badge_enabled"] = badge_enabled
                self._overlay_style_widgets[key]["badge_color"] = badge_color
                self._overlay_style_widgets[key]["badge_width"] = badge_width
                self._overlay_style_widgets[key]["badge_height"] = badge_height
                self._overlay_style_widgets[key]["badge_side"] = badge_side

            for w in (bg_color, bg_opacity, border_color, border_opacity, border_width,
                      text_color, text_opacity, font_family, font_size, font_bold, font_weight):
                if isinstance(w, QLineEdit):
                    w.textChanged.connect(lambda _t: self._apply_overlay_style_live())
                elif isinstance(w, QSlider):
                    w.valueChanged.connect(lambda _v: self._apply_overlay_style_live())
                elif isinstance(w, QSpinBox):
                    w.valueChanged.connect(lambda _v: self._apply_overlay_style_live())
                elif isinstance(w, QFontComboBox):
                    w.currentFontChanged.connect(lambda _f: self._apply_overlay_style_live())
                elif isinstance(w, QCheckBox):
                    w.stateChanged.connect(lambda _s: self._apply_overlay_style_live())
            if badge_enabled is not None:
                badge_enabled.stateChanged.connect(lambda _s: self._apply_overlay_style_live())
                badge_color.textChanged.connect(lambda _t: self._apply_overlay_style_live())
                badge_width.valueChanged.connect(lambda _v: self._apply_overlay_style_live())
                badge_height.valueChanged.connect(lambda _v: self._apply_overlay_style_live())
                badge_side.currentIndexChanged.connect(lambda _i: self._apply_overlay_style_live())

            return grp

        overlay_lay.addWidget(_build_style_group("Overlay style - Round", "round"))
        overlay_lay.addWidget(_build_style_group("오버레이 스타일 - 타이머", "time"))
        overlay_lay.addWidget(_build_style_group("오버레이 스타일 - 이름(블루)", "blue_name"))
        overlay_lay.addWidget(_build_style_group("오버레이 스타일 - 이름(레드)", "red_name"))
        overlay_lay.addWidget(_build_style_group("Overlay style - Arena", "arena"))
        overlay_lay.addWidget(_build_style_group("Browser text - Time", "browser_time"))
        overlay_lay.addWidget(_build_style_group("Browser text - Total Damage", "browser_total"))
        overlay_lay.addWidget(_build_style_group("Browser text - Round DMG", "browser_dmg"))
        overlay_lay.addWidget(_build_style_group("Browser text - Combo / Counter", "browser_combo"))
        overlay_lay.addWidget(_build_style_group("Browser text - Recent Hit", "browser_recent"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        tab_lay = QVBoxLayout()
        tab_lay.addWidget(scroll)
        self.tab_timer.setLayout(tab_lay)

        overlay_scroll = QScrollArea()
        overlay_scroll.setWidgetResizable(True)
        overlay_scroll.setWidget(overlay_content)
        overlay_tab_lay = QVBoxLayout()
        overlay_tab_lay.addWidget(overlay_scroll)
        self.tab_overlay.setLayout(overlay_tab_lay)

    def _timer_preset_dir(self) -> str:
        if self._cfg_path:
            return os.path.dirname(os.path.abspath(self._cfg_path))
        return get_app_base_dir()

    def _overlay_preset_dir(self) -> str:
        base = self._timer_preset_dir()
        try:
            path = os.path.join(base, "presets", "overlay")
            os.makedirs(path, exist_ok=True)
            return path
        except Exception:
            return base

    def _is_overlay_preset(self, data: dict) -> bool:
        if not isinstance(data, dict):
            return False
        if "overlay_layout" in data or "overlay_style" in data:
            return True
        for k in data.keys():
            if str(k).startswith("overlay_"):
                return True
        return False

    def _refresh_overlay_presets(self):
        if not hasattr(self, "cmb_overlay_preset"):
            return
        self.cmb_overlay_preset.blockSignals(True)
        self.cmb_overlay_preset.clear()
        self.cmb_overlay_preset.addItem("선택", "")
        self._overlay_presets = {}
        base = self._overlay_preset_dir()
        try:
            for name in os.listdir(base):
                if not name.lower().endswith(".json"):
                    continue
                path = os.path.join(base, name)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f) or {}
                except Exception:
                    continue
                if not self._is_overlay_preset(data):
                    continue
                label = os.path.splitext(name)[0]
                self._overlay_presets[label] = data
                self.cmb_overlay_preset.addItem(label, label)
        except Exception:
            pass
        self.cmb_overlay_preset.blockSignals(False)

    def _apply_overlay_preset_from_ui(self, _idx: int):
        if not hasattr(self, "cmb_overlay_preset"):
            return
        key = self.cmb_overlay_preset.currentData()
        if not key:
            return
        data = self._overlay_presets.get(key, {})
        if not data:
            return
        self._apply_overlay_preset(data)

    def _extract_timer_preset(self, data: dict) -> Optional[dict]:
        if not isinstance(data, dict):
            return None
        def _from_block(block: dict) -> Optional[dict]:
            if not isinstance(block, dict):
                return None
            if any(k in block for k in ("timer_total_rounds", "timer_round_sec", "timer_rest_sec", "timer_current_round", "timer_seconds_left")):
                return {
                    "timer_total_rounds": int(block.get("timer_total_rounds", self.cfg.timer_total_rounds)),
                    "timer_round_sec": int(block.get("timer_round_sec", self.cfg.timer_round_sec)),
                    "timer_rest_sec": int(block.get("timer_rest_sec", self.cfg.timer_rest_sec)),
                    "timer_current_round": int(block.get("timer_current_round", 1)),
                    "timer_seconds_left": int(block.get("timer_seconds_left", block.get("timer_round_sec", self.cfg.timer_round_sec))),
                }
            timer = block.get("timer", None)
            if isinstance(timer, dict):
                return {
                    "timer_total_rounds": int(timer.get("total_rounds", self.cfg.timer_total_rounds)),
                    "timer_round_sec": int(timer.get("round_sec", self.cfg.timer_round_sec)),
                    "timer_rest_sec": int(timer.get("rest_sec", self.cfg.timer_rest_sec)),
                    "timer_current_round": int(timer.get("current_round", 1)),
                    "timer_seconds_left": int(timer.get("seconds_left", timer.get("round_sec", self.cfg.timer_round_sec))),
                }
            return None
        preset = _from_block(data)
        if preset:
            return preset
        for key in ("config", "settings", "app", "data"):
            preset = _from_block(data.get(key, None))
            if preset:
                return preset
        return None

    def _refresh_timer_presets(self):
        if not hasattr(self, "cmb_timer_preset"):
            return
        self.cmb_timer_preset.blockSignals(True)
        self.cmb_timer_preset.clear()
        self.cmb_timer_preset.addItem("선택", "")
        self._timer_presets = {}
        self._timer_presets["현재 설정"] = {
            "timer_total_rounds": int(self.cfg.timer_total_rounds),
            "timer_round_sec": int(self.cfg.timer_round_sec),
            "timer_rest_sec": int(self.cfg.timer_rest_sec),
            "timer_current_round": int(self.cfg.timer_current_round),
            "timer_seconds_left": int(self.cfg.timer_seconds_left),
        }
        self.cmb_timer_preset.addItem("현재 설정", "현재 설정")
        base = self._timer_preset_dir()
        try:
            for name in os.listdir(base):
                if not name.lower().endswith(".json"):
                    continue
                path = os.path.join(base, name)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f) or {}
                except Exception:
                    continue
                label = os.path.splitext(name)[0]
                preset = self._extract_timer_preset(data)
                if not preset:
                    display = f"{label} (타이머 없음)"
                    self._timer_presets[display] = {}
                    self.cmb_timer_preset.addItem(display, display)
                    idx = self.cmb_timer_preset.count() - 1
                    try:
                        item = self.cmb_timer_preset.model().item(idx)
                        if item is not None:
                            item.setEnabled(False)
                    except Exception:
                        pass
                    continue
                self._timer_presets[label] = preset
                self.cmb_timer_preset.addItem(label, label)
        except Exception:
            pass
        self.cmb_timer_preset.blockSignals(False)

    def _apply_timer_preset_from_ui(self, _idx: int):
        if not hasattr(self, "cmb_timer_preset"):
            return
        key = self.cmb_timer_preset.currentData()
        if not key:
            return
        data = self._timer_presets.get(key, {})
        if not data:
            return
        total = int(data.get("timer_total_rounds", self.cfg.timer_total_rounds))
        current = int(data.get("timer_current_round", 1))
        round_sec = int(data.get("timer_round_sec", self.cfg.timer_round_sec))
        rest_sec = int(data.get("timer_rest_sec", self.cfg.timer_rest_sec))
        left_sec = int(data.get("timer_seconds_left", round_sec))
        if hasattr(self, "sp_timer_total"):
            self.sp_timer_total.setValue(total)
        if hasattr(self, "sp_timer_current"):
            self.sp_timer_current.setValue(min(max(1, current), total))
        if hasattr(self, "sp_timer_round_sec"):
            self.sp_timer_round_sec.setValue(round_sec)
        if hasattr(self, "sp_timer_rest_sec"):
            self.sp_timer_rest_sec.setValue(rest_sec)
        if hasattr(self, "sp_timer_left"):
            self.sp_timer_left.setValue(left_sec)
        self._apply_timer_settings_now()

    # ---- Win Effects tab ----
    def _build_effects(self):
        content = QWidget()
        lay = QVBoxLayout(content)
        # removed intro tip per request
        def _tt(w: QWidget, text: str):
            try:
                w.setToolTip(text)
            except Exception:
                pass

        stage_row = QHBoxLayout()
        stage_row.addWidget(QLabel("연승 단계"))
        self.btn_open_stage = QPushButton("단계 편집")
        self.btn_open_stage.clicked.connect(self._open_stage_dialog)
        _tt(self.btn_open_stage, "연승 구간별 색/밝기/두근거림(펄스)을 설정합니다.")
        stage_row.addWidget(self.btn_open_stage)
        stage_row.addStretch(1)
        lay.addLayout(stage_row)

        self.lbl_stage_summary = QLabel("")
        self.lbl_stage_summary.setStyleSheet("color:#cbd5e1;")
        lay.addWidget(self.lbl_stage_summary)

        aura_group = QGroupBox("아우라")
        aura_lay = QGridLayout(aura_group)
        self.chk_aura_enabled = QCheckBox("아우라 켜기")
        _tt(self.chk_aura_enabled, "연승 아우라 전체 on/off")
        aura_lay.addWidget(self.chk_aura_enabled, 0, 0)
        aura_lay.addWidget(QLabel("사진과 테두리 사이 여백"), 1, 0)
        self.sp_aura_frame_pad = QSpinBox(); self.sp_aura_frame_pad.setRange(0, 50)
        _tt(self.sp_aura_frame_pad, "사진과 테두리 사이 간격(px)")
        aura_lay.addWidget(self.sp_aura_frame_pad, 1, 1)
        aura_lay.addWidget(QLabel("바깥쪽 여백"), 1, 2)
        self.sp_aura_outer_pad = QSpinBox(); self.sp_aura_outer_pad.setRange(0, 80)
        _tt(self.sp_aura_outer_pad, "테두리 바깥 여백(px)")
        aura_lay.addWidget(self.sp_aura_outer_pad, 1, 3)
        aura_lay.addWidget(QLabel("테두리 두께"), 2, 0)
        self.sp_aura_border1 = QSpinBox(); self.sp_aura_border1.setRange(0, 10)
        self.sp_aura_border2 = QSpinBox(); self.sp_aura_border2.setRange(0, 10)
        self.sp_aura_border3 = QSpinBox(); self.sp_aura_border3.setRange(0, 10)
        _tt(self.sp_aura_border1, "3겹 테두리 중 가장 안쪽 두께(px)")
        _tt(self.sp_aura_border2, "3겹 테두리 중 중간 두께(px)")
        _tt(self.sp_aura_border3, "3겹 테두리 중 바깥쪽 두께(px)")
        aura_lay.addWidget(self.sp_aura_border1, 2, 1)
        aura_lay.addWidget(self.sp_aura_border2, 2, 2)
        aura_lay.addWidget(self.sp_aura_border3, 2, 3)
        aura_lay.addWidget(QLabel(""), 3, 0)
        self.le_border_color = QLineEdit(); self.le_border_color.setPlaceholderText("비우면 자동")
        self.btn_border_color = QPushButton("색상")
        _tt(self.le_border_color, "비우면 연승 단계 색을 사용합니다.")
        _tt(self.btn_border_color, "테두리 색 직접 선택")
        def _pick_border_color():
            c = QColor(self.le_border_color.text() or "#ffffff")
            q = QColorDialog.getColor(c, self)
            if q.isValid():
                self.le_border_color.setText(q.name())
        self.btn_border_color.clicked.connect(_pick_border_color)
        border_color_box = QWidget()
        border_color_lay = QHBoxLayout(border_color_box); border_color_lay.setContentsMargins(0, 0, 0, 0)
        border_color_lay.addWidget(self.le_border_color); border_color_lay.addWidget(self.btn_border_color)
        aura_lay.addWidget(border_color_box, 3, 1)
        aura_lay.addWidget(QLabel(""), 3, 2)
        self.sp_border_opacity = QDoubleSpinBox(); self.sp_border_opacity.setRange(0.0, 1.0); self.sp_border_opacity.setSingleStep(0.05)
        _tt(self.sp_border_opacity, "테두리 투명도(0=투명, 1=불투명)")
        aura_lay.addWidget(self.sp_border_opacity, 3, 3)
        self.chk_border_fx = QCheckBox("테두리 이펙트 켜기")
        _tt(self.chk_border_fx, "테두리 주변 파티클/빛 효과 on/off")
        aura_lay.addWidget(self.chk_border_fx, 4, 0, 1, 2)
        aura_lay.addWidget(QLabel(""), 5, 0)
        self.chk_backdrop = QCheckBox("배경판 켜기")
        _tt(self.chk_backdrop, "아우라 뒤 배경판 on/off")
        aura_lay.addWidget(self.chk_backdrop, 5, 1)
        self.le_backdrop_color = QLineEdit(); self.le_backdrop_color.setPlaceholderText("#000000")
        self.btn_backdrop_color = QPushButton("색상")
        _tt(self.le_backdrop_color, "배경판 색상")
        _tt(self.btn_backdrop_color, "배경판 색 직접 선택")
        def _pick_backdrop_color():
            c = QColor(self.le_backdrop_color.text() or "#000000")
            q = QColorDialog.getColor(c, self)
            if q.isValid():
                self.le_backdrop_color.setText(q.name())
        self.btn_backdrop_color.clicked.connect(_pick_backdrop_color)
        backdrop_box = QWidget()
        backdrop_lay = QHBoxLayout(backdrop_box); backdrop_lay.setContentsMargins(0, 0, 0, 0)
        backdrop_lay.addWidget(self.le_backdrop_color); backdrop_lay.addWidget(self.btn_backdrop_color)
        aura_lay.addWidget(backdrop_box, 5, 2)
        self.sp_backdrop_opacity = QDoubleSpinBox(); self.sp_backdrop_opacity.setRange(0.0, 1.0); self.sp_backdrop_opacity.setSingleStep(0.05)
        _tt(self.sp_backdrop_opacity, "배경판 투명도(0=투명, 1=불투명)")
        aura_lay.addWidget(self.sp_backdrop_opacity, 5, 3)
        aura_lay.addWidget(QLabel("배경판 크기"), 6, 0)
        self.sp_backdrop_pad = QSpinBox(); self.sp_backdrop_pad.setRange(0, 80)
        _tt(self.sp_backdrop_pad, "배경판 크기 여유(px)")
        aura_lay.addWidget(self.sp_backdrop_pad, 6, 1)
        aura_lay.addWidget(QLabel("테두리 불꽃"), 7, 0)
        self.sp_frame_emit = QSpinBox(); self.sp_frame_emit.setRange(0, 200)
        self.sp_frame_size = QSpinBox(); self.sp_frame_size.setRange(0, 50)
        self.sp_frame_var = QSpinBox(); self.sp_frame_var.setRange(0, 50)
        self.sp_frame_pace = QSpinBox(); self.sp_frame_pace.setRange(0, 200)
        _tt(self.sp_frame_emit, "테두리 주변 불꽃 수(emit)")
        _tt(self.sp_frame_size, "테두리 불꽃 크기")
        _tt(self.sp_frame_var, "테두리 불꽃 크기 변화폭")
        _tt(self.sp_frame_pace, "테두리 불꽃 이동 속도")
        aura_lay.addWidget(self.sp_frame_emit, 7, 1)
        aura_lay.addWidget(self.sp_frame_size, 7, 2)
        aura_lay.addWidget(self.sp_frame_var, 7, 3)
        aura_lay.addWidget(QLabel("불꽃알 이동 속도"), 8, 0)
        aura_lay.addWidget(self.sp_frame_pace, 8, 1)
        aura_lay.addWidget(QLabel("불꽃"), 9, 0)
        self.sp_flame_emit = QSpinBox(); self.sp_flame_emit.setRange(0, 200)
        self.sp_flame_size = QSpinBox(); self.sp_flame_size.setRange(0, 100)
        self.sp_flame_var = QSpinBox(); self.sp_flame_var.setRange(0, 100)
        _tt(self.sp_flame_emit, "불꽃 파티클 수(emit)")
        _tt(self.sp_flame_size, "불꽃 크기")
        _tt(self.sp_flame_var, "불꽃 크기 변화폭")
        aura_lay.addWidget(self.sp_flame_emit, 9, 1)
        aura_lay.addWidget(self.sp_flame_size, 9, 2)
        aura_lay.addWidget(self.sp_flame_var, 9, 3)
        aura_lay.addWidget(QLabel("연기"), 10, 0)
        self.sp_smoke_emit = QSpinBox(); self.sp_smoke_emit.setRange(0, 200)
        self.sp_smoke_size = QSpinBox(); self.sp_smoke_size.setRange(0, 150)
        self.sp_smoke_var = QSpinBox(); self.sp_smoke_var.setRange(0, 150)
        _tt(self.sp_smoke_emit, "연기 파티클 수(emit)")
        _tt(self.sp_smoke_size, "연기 크기")
        _tt(self.sp_smoke_var, "연기 크기 변화폭")
        aura_lay.addWidget(self.sp_smoke_emit, 10, 1)
        aura_lay.addWidget(self.sp_smoke_size, 10, 2)
        aura_lay.addWidget(self.sp_smoke_var, 10, 3)
        aura_lay.addWidget(QLabel(""), 11, 0)
        self.sp_spark_emit = QSpinBox(); self.sp_spark_emit.setRange(0, 200)
        self.sp_spark_size = QSpinBox(); self.sp_spark_size.setRange(0, 80)
        self.sp_spark_var = QSpinBox(); self.sp_spark_var.setRange(0, 80)
        _tt(self.sp_spark_emit, "스파크 파티클 수(emit)")
        _tt(self.sp_spark_size, "스파크 크기")
        _tt(self.sp_spark_var, "스파크 크기 변화폭")
        aura_lay.addWidget(self.sp_spark_emit, 11, 1)
        aura_lay.addWidget(self.sp_spark_size, 11, 2)
        aura_lay.addWidget(self.sp_spark_var, 11, 3)
        aura_lay.addWidget(QLabel(""), 12, 0)
        self.sp_turbulence = QSpinBox(); self.sp_turbulence.setRange(0, 100)
        _tt(self.sp_turbulence, "난류(흔들림) 강도")
        aura_lay.addWidget(self.sp_turbulence, 12, 1)
        aura_lay.addWidget(QLabel("블러"), 12, 2)
        self.sp_aura_blur = QSpinBox(); self.sp_aura_blur.setRange(0, 40)
        _tt(self.sp_aura_blur, "아우라 전체 블러 강도(px)")
        aura_lay.addWidget(self.sp_aura_blur, 12, 3)
        lay.addWidget(aura_group)

        aura_adv_group = QGroupBox("아우라 고급(불)")
        aura_adv_lay = QGridLayout(aura_adv_group)
        aura_adv_lay.addWidget(QLabel(""), 0, 0)
        aura_adv_lay.addWidget(QLabel("분사배수"), 0, 1)
        aura_adv_lay.addWidget(QLabel("크기배수"), 0, 2)
        aura_adv_lay.addWidget(QLabel(""), 0, 3)
        aura_adv_lay.addWidget(QLabel("각도분산"), 0, 4)
        aura_adv_lay.addWidget(QLabel("속도"), 0, 5)
        aura_adv_lay.addWidget(QLabel(""), 0, 6)
        aura_adv_lay.addWidget(QLabel("알파"), 0, 7)

        def _adv_spin(min_v, max_v, step, decimals=2):
            sp = QDoubleSpinBox()
            sp.setRange(min_v, max_v)
            sp.setSingleStep(step)
            sp.setDecimals(decimals)
            return sp

        self._aura_adv = {}
        def _add_adv_row(row: int, key: str, label: str):
            aura_adv_lay.addWidget(QLabel(label), row, 0)
            sp_emit = _adv_spin(0.0, 5.0, 0.1)
            sp_size = _adv_spin(0.0, 2.0, 0.05)
            sp_size_var = _adv_spin(0.0, 2.0, 0.05)
            sp_angle = _adv_spin(0.0, 45.0, 1.0, decimals=0)
            sp_speed = _adv_spin(0.0, 200.0, 5.0, decimals=0)
            sp_speed_var = _adv_spin(0.0, 150.0, 5.0, decimals=0)
            sp_alpha = _adv_spin(0.0, 1.0, 0.05)
            aura_adv_lay.addWidget(sp_emit, row, 1)
            aura_adv_lay.addWidget(sp_size, row, 2)
            aura_adv_lay.addWidget(sp_size_var, row, 3)
            aura_adv_lay.addWidget(sp_angle, row, 4)
            aura_adv_lay.addWidget(sp_speed, row, 5)
            aura_adv_lay.addWidget(sp_speed_var, row, 6)
            aura_adv_lay.addWidget(sp_alpha, row, 7)
            self._aura_adv[key] = {
                "emit": sp_emit,
                "size": sp_size,
                "size_var": sp_size_var,
                "angle": sp_angle,
                "speed": sp_speed,
                "speed_var": sp_speed_var,
                "alpha": sp_alpha,
            }

        _add_adv_row(1, "core", "\uCF54\uC5B4")
        _add_adv_row(2, "body", "\uBC14\uB514")
        _add_adv_row(3, "glow", "\uAE00\uB85C\uC6B0")
        _add_adv_row(4, "wisps", "Wisps")
        _add_adv_row(5, "spark", "Spark")

        aura_adv_lay.addWidget(QLabel("난류 배수(코어)"), 6, 0)
        self.sp_aura_core_turb = _adv_spin(0.0, 2.0, 0.05)
        aura_adv_lay.addWidget(self.sp_aura_core_turb, 6, 1)
        aura_adv_lay.addWidget(QLabel("난류 배수(글로우)"), 6, 2)
        self.sp_aura_glow_turb = _adv_spin(0.0, 2.0, 0.05)
        aura_adv_lay.addWidget(self.sp_aura_glow_turb, 6, 3)
        lay.addWidget(aura_adv_group)

        inner_group = QGroupBox("사진 안쪽 효과")
        inner_lay = QGridLayout(inner_group)
        row = 0
        self._inner_controls = {}
        def add_inner_row(key: str, label: str, has_speed=False, has_opacity_range=False, has_timing=True):
            nonlocal row
            chk = QCheckBox(label); inner_lay.addWidget(chk, row, 0)
            sp_min = QSpinBox(); sp_min.setRange(0, 99); inner_lay.addWidget(QLabel(""), row, 1)
            sp_a = QDoubleSpinBox(); sp_a.setRange(0.0, 1.0); sp_a.setSingleStep(0.05)
            sp_b = QDoubleSpinBox(); sp_b.setRange(0.0, 1.0); sp_b.setSingleStep(0.05)
            sp_int = None
            if has_timing:
                sp_int = QSpinBox()
                sp_int.setRange(10, 5000)
            _tt(chk, "해당 내부 효과 on/off")
            _tt(sp_min, "효과가 시작되는 최소 연승")
            _tt(sp_a, "Brightness/opacity value")
            _tt(sp_b, "Brightness/opacity max value")
            if sp_int is not None:
                _tt(sp_int, "Effect interval/speed in ms.")
            if has_opacity_range:
                inner_lay.addWidget(QLabel("밝기"), row, 3)
                inner_lay.addWidget(sp_a, row, 4)
                inner_lay.addWidget(sp_b, row, 5)
            else:
                inner_lay.addWidget(QLabel("밝기"), row, 3)
                inner_lay.addWidget(sp_a, row, 4)
            if sp_int is not None:
                inner_lay.addWidget(QLabel(""), row, 6)
                inner_lay.addWidget(sp_int, row, 7)
            self._inner_controls[key] = {"chk": chk, "min": sp_min, "a": sp_a, "b": sp_b, "int": sp_int, "range": has_opacity_range, "speed": has_speed}
            row += 1

        # Keep only effects that are currently rendered in timer_ui.qml.
        add_inner_row("dust", "먼지", has_opacity_range=False)
        add_inner_row("hud", "HUD 원형", has_speed=True, has_opacity_range=False)
        add_inner_row("electric", "전기 찌직", has_opacity_range=True)
        add_inner_row("core", "12연승 펄스", has_opacity_range=False, has_timing=False)
        add_inner_row("chrono", "30연승 균열", has_speed=True, has_opacity_range=False)

        inner_lay.addWidget(QLabel("12연승 펄스 크기"), row, 0)
        self.sp_core_size = QDoubleSpinBox(); self.sp_core_size.setRange(0.05, 1.0); self.sp_core_size.setSingleStep(0.05)
        _tt(self.sp_core_size, "12연승 펄스 크기 비율")
        inner_lay.addWidget(self.sp_core_size, row, 1)
        inner_lay.addWidget(QLabel("12연승 펄스 속도"), row, 2)
        self.sp_core_period = QSpinBox(); self.sp_core_period.setRange(200, 5000)
        _tt(self.sp_core_period, "12연승 펄스 주기(ms). 낮을수록 빠름")
        inner_lay.addWidget(self.sp_core_period, row, 3)
        row += 1
        lay.addWidget(inner_group)

        win_text_group = QGroupBox("연승 텍스트")
        win_text_lay = QGridLayout(win_text_group)
        self.chk_win_text_enabled = QCheckBox("표시")
        _tt(self.chk_win_text_enabled, "연승 텍스트 표시 on/off")
        win_text_lay.addWidget(self.chk_win_text_enabled, 0, 0)
        win_text_lay.addWidget(QLabel("포맷"), 0, 1)
        self.le_win_text_format = QLineEdit(); self.le_win_text_format.setPlaceholderText("W{n}")
        _tt(self.le_win_text_format, "표시 포맷. {n}이 연승 수로 치환됩니다.")
        win_text_lay.addWidget(self.le_win_text_format, 0, 2, 1, 2)
        win_text_lay.addWidget(QLabel("크기 비율"), 1, 0)
        self.sp_win_text_scale = QDoubleSpinBox(); self.sp_win_text_scale.setRange(0.05, 0.5); self.sp_win_text_scale.setSingleStep(0.01)
        _tt(self.sp_win_text_scale, "이미지 높이 대비 글자 크기 비율")
        win_text_lay.addWidget(self.sp_win_text_scale, 1, 1)
        win_text_lay.addWidget(QLabel("理쒖냼"), 1, 2)
        self.sp_win_text_min = QSpinBox(); self.sp_win_text_min.setRange(6, 40)
        _tt(self.sp_win_text_min, "글자 최소 크기(px)")
        win_text_lay.addWidget(self.sp_win_text_min, 1, 3)
        win_text_lay.addWidget(QLabel("최대"), 1, 4)
        self.sp_win_text_max = QSpinBox(); self.sp_win_text_max.setRange(8, 60)
        _tt(self.sp_win_text_max, "글자 최대 크기(px)")
        win_text_lay.addWidget(self.sp_win_text_max, 1, 5)
        win_text_lay.addWidget(QLabel("아래로 이동 비율"), 2, 0)
        self.sp_win_text_offset = QDoubleSpinBox(); self.sp_win_text_offset.setRange(0.0, 0.5); self.sp_win_text_offset.setSingleStep(0.01)
        _tt(self.sp_win_text_offset, "텍스트를 아래로 내리는 비율")
        win_text_lay.addWidget(self.sp_win_text_offset, 2, 1)
        win_text_lay.addWidget(QLabel("하이라이트 높이"), 2, 2)
        self.sp_win_text_highlight = QDoubleSpinBox(); self.sp_win_text_highlight.setRange(0.1, 1.0); self.sp_win_text_highlight.setSingleStep(0.05)
        _tt(self.sp_win_text_highlight, "그라데이션 하이라이트 높이 비율")
        win_text_lay.addWidget(self.sp_win_text_highlight, 2, 3)

        self.le_win_text_base = QLineEdit(); self.btn_win_text_base = QPushButton("색상")
        self.le_win_text_highlight = QLineEdit(); self.btn_win_text_highlight = QPushButton("색상")
        self.le_win_text_outline = QLineEdit(); self.btn_win_text_outline = QPushButton("색상")
        self.le_win_text_shadow = QLineEdit(); self.btn_win_text_shadow = QPushButton("색상")
        _tt(self.le_win_text_base, "텍스트 기본 색상")
        _tt(self.btn_win_text_base, "텍스트 기본색 선택")
        _tt(self.le_win_text_highlight, "텍스트 하이라이트 색상")
        _tt(self.btn_win_text_highlight, "하이라이트 색 선택")
        _tt(self.le_win_text_outline, "텍스트 외곽선 색상")
        _tt(self.btn_win_text_outline, "외곽선 색 선택")
        _tt(self.le_win_text_shadow, "텍스트 그림자 색상")
        _tt(self.btn_win_text_shadow, "그림자 색 선택")
        def _pick_win_color(le: QLineEdit):
            c = QColor(le.text() or "#ffffff")
            q = QColorDialog.getColor(c, self)
            if q.isValid():
                le.setText(q.name())
        self.btn_win_text_base.clicked.connect(lambda: _pick_win_color(self.le_win_text_base))
        self.btn_win_text_highlight.clicked.connect(lambda: _pick_win_color(self.le_win_text_highlight))
        self.btn_win_text_outline.clicked.connect(lambda: _pick_win_color(self.le_win_text_outline))
        self.btn_win_text_shadow.clicked.connect(lambda: _pick_win_color(self.le_win_text_shadow))

        win_text_lay.addWidget(QLabel(""), 3, 0)
        win_text_lay.addWidget(self.le_win_text_base, 3, 1)
        win_text_lay.addWidget(self.btn_win_text_base, 3, 2)
        win_text_lay.addWidget(QLabel(""), 3, 3)
        win_text_lay.addWidget(self.le_win_text_highlight, 3, 4)
        win_text_lay.addWidget(self.btn_win_text_highlight, 3, 5)
        win_text_lay.addWidget(QLabel(""), 4, 0)
        win_text_lay.addWidget(self.le_win_text_outline, 4, 1)
        win_text_lay.addWidget(self.btn_win_text_outline, 4, 2)
        win_text_lay.addWidget(QLabel(""), 4, 3)
        win_text_lay.addWidget(self.le_win_text_shadow, 4, 4)
        win_text_lay.addWidget(self.btn_win_text_shadow, 4, 5)
        win_text_lay.addWidget(QLabel(""), 5, 0)
        self.sp_win_text_shadow_op = QDoubleSpinBox(); self.sp_win_text_shadow_op.setRange(0.0, 1.0); self.sp_win_text_shadow_op.setSingleStep(0.05)
        _tt(self.sp_win_text_shadow_op, "그림자 투명도(0=투명, 1=불투명)")
        win_text_lay.addWidget(self.sp_win_text_shadow_op, 5, 1)
        lay.addWidget(win_text_group)

        burst_group = QGroupBox("플래시뱅")
        burst_lay = QGridLayout(burst_group)
        burst_lay.addWidget(QLabel("발동 승수"), 0, 0)
        self.le_burst_milestones = QLineEdit()
        self.le_burst_milestones.setPlaceholderText("3,6,9,12,16,21,30")
        _tt(self.le_burst_milestones, "콤마로 구분된 승수 목록 (예: 3,6,9,12,16,21,30)")
        burst_lay.addWidget(self.le_burst_milestones, 0, 1, 1, 3)
        self.chk_burst_sfx = QCheckBox("효과음 사용")
        _tt(self.chk_burst_sfx, "플래시뱅 발생 시 효과음 재생")
        burst_lay.addWidget(self.chk_burst_sfx, 1, 0)
        self.le_burst_sfx_path = QLineEdit()
        self.le_burst_sfx_path.setPlaceholderText("WAV 파일 경로")
        burst_lay.addWidget(self.le_burst_sfx_path, 1, 1)
        self.btn_burst_sfx_pick = QPushButton("李얘린")
        self.btn_burst_sfx_test = QPushButton("테스트")
        burst_lay.addWidget(self.btn_burst_sfx_pick, 1, 2)
        burst_lay.addWidget(self.btn_burst_sfx_test, 1, 3)
        def _pick_burst_sfx():
            path, _ = QFileDialog.getOpenFileName(self, "플래시 효과음 선택", "", "Audio (*.wav *.mp3)")
            if path:
                self.le_burst_sfx_path.setText(path)
        def _test_burst_sfx():
            p = str(self.le_burst_sfx_path.text() or "").strip()
            ok = False
            if p.lower().endswith(".wav"):
                ok = _play_win_effect_sfx(p)
            elif p.lower().endswith(".mp3"):
                player = getattr(self, "_burst_player", None)
                audio_out = getattr(self, "_burst_audio_out", None)
                if player is None or audio_out is None:
                    if not HAS_QTMULTIMEDIA or QMediaPlayer is None or QAudioOutput is None:
                        QMessageBox.information(self, "안내", "Qt Multimedia를 사용할 수 없어 MP3 테스트를 재생할 수 없습니다.")
                        return
                    try:
                        self._burst_audio_out = QAudioOutput()
                        self._burst_player = QMediaPlayer()
                        self._burst_player.setAudioOutput(self._burst_audio_out)
                        player = self._burst_player
                        audio_out = self._burst_audio_out
                    except Exception:
                        QMessageBox.information(self, "안내", "효과음 파일을 선택하세요.")
                        return
                ok = _play_media_sfx(player, audio_out, p)
            if not ok:
                QMessageBox.information(self, "안내", "효과음 재생에 실패했습니다.")
        self.btn_burst_sfx_pick.clicked.connect(_pick_burst_sfx)
        self.btn_burst_sfx_test.clicked.connect(_test_burst_sfx)
        lay.addWidget(burst_group)

        nameplate_group = QGroupBox("명찰 이미지")
        nameplate_lay = QGridLayout(nameplate_group)
        self.chk_nameplate_enabled = QCheckBox("사용")
        nameplate_lay.addWidget(self.chk_nameplate_enabled, 0, 0)
        nameplate_lay.addWidget(QLabel("크기배율"), 0, 1)
        self.sp_nameplate_scale = QDoubleSpinBox(); self.sp_nameplate_scale.setRange(0.2, 3.0); self.sp_nameplate_scale.setSingleStep(0.1)
        nameplate_lay.addWidget(self.sp_nameplate_scale, 0, 2)
        nameplate_lay.addWidget(QLabel("간격"), 0, 3)
        self.sp_nameplate_gap = QSpinBox(); self.sp_nameplate_gap.setRange(0, 200)
        nameplate_lay.addWidget(self.sp_nameplate_gap, 0, 4)
        nameplate_lay.addWidget(QLabel("블루 위치"), 0, 5)
        self.cmb_nameplate_side_blue = QComboBox()
        self.cmb_nameplate_side_blue.addItem("왼쪽", "left")
        self.cmb_nameplate_side_blue.addItem("오른쪽", "right")
        nameplate_lay.addWidget(self.cmb_nameplate_side_blue, 0, 6)
        nameplate_lay.addWidget(QLabel("레드 위치"), 0, 7)
        self.cmb_nameplate_side_red = QComboBox()
        self.cmb_nameplate_side_red.addItem("왼쪽", "left")
        self.cmb_nameplate_side_red.addItem("오른쪽", "right")
        nameplate_lay.addWidget(self.cmb_nameplate_side_red, 0, 8)

        self._nameplate_rows = []
        def _add_nameplate_row(row: int, min_win: int):
            nameplate_lay.addWidget(QLabel(f"{min_win}승 이상"), row, 0)
            le = QLineEdit()
            le.setPlaceholderText("이미지 파일 경로")
            btn = QPushButton("李얘린")
            nameplate_lay.addWidget(le, row, 1, 1, 7)
            nameplate_lay.addWidget(btn, row, 8)
            def _pick():
                path, _ = QFileDialog.getOpenFileName(self, "명찰 이미지 선택", "", "Image (*.png *.jpg *.jpeg *.bmp)")
                if path:
                    le.setText(path)
            btn.clicked.connect(_pick)
            self._nameplate_rows.append({"min": int(min_win), "le": le})

        for i, m in enumerate([3, 6, 9, 12, 16, 21, 30], start=1):
            _add_nameplate_row(i, m)

        lay.addWidget(nameplate_group)

        portrait_group = QGroupBox("초상화 표시")
        portrait_lay = QGridLayout(portrait_group)
        portrait_lay.addWidget(QLabel("확대"), 0, 0)
        self.sp_portrait_zoom = QDoubleSpinBox()
        self.sp_portrait_zoom.setRange(0.5, 4.0)
        self.sp_portrait_zoom.setSingleStep(0.05)
        self.sp_portrait_zoom.setDecimals(2)
        _tt(self.sp_portrait_zoom, "초상화 안의 이미지만 확대합니다. 얼굴이 작으면 이 값을 올리세요.")
        portrait_lay.addWidget(self.sp_portrait_zoom, 0, 1)
        portrait_lay.addWidget(QLabel("가로 위치"), 0, 2)
        self.sp_portrait_offset_x = QDoubleSpinBox()
        self.sp_portrait_offset_x.setRange(-1.0, 1.0)
        self.sp_portrait_offset_x.setSingleStep(0.02)
        self.sp_portrait_offset_x.setDecimals(2)
        _tt(self.sp_portrait_offset_x, "확대한 초상화를 좌우로 이동합니다.")
        portrait_lay.addWidget(self.sp_portrait_offset_x, 0, 3)
        portrait_lay.addWidget(QLabel("세로 위치"), 0, 4)
        self.sp_portrait_offset_y = QDoubleSpinBox()
        self.sp_portrait_offset_y.setRange(-1.0, 1.0)
        self.sp_portrait_offset_y.setSingleStep(0.02)
        self.sp_portrait_offset_y.setDecimals(2)
        _tt(self.sp_portrait_offset_y, "확대한 초상화를 위아래로 이동합니다. 음수면 위로 올라갑니다.")
        portrait_lay.addWidget(self.sp_portrait_offset_y, 0, 5)
        lay.addWidget(portrait_group)

        fail_group = QGroupBox("연승 실패")
        fail_lay = QGridLayout(fail_group)
        self.chk_fail_enabled = QCheckBox("효과 사용")
        fail_lay.addWidget(self.chk_fail_enabled, 0, 0)
        self.chk_fail_sfx = QCheckBox("효과음 사용")
        fail_lay.addWidget(self.chk_fail_sfx, 1, 0)
        self.le_fail_sfx_path = QLineEdit()
        self.le_fail_sfx_path.setPlaceholderText("WAV/MP3 파일 경로")
        fail_lay.addWidget(self.le_fail_sfx_path, 1, 1)
        self.btn_fail_sfx_pick = QPushButton("李얘린")
        self.btn_fail_sfx_test = QPushButton("테스트")
        fail_lay.addWidget(self.btn_fail_sfx_pick, 1, 2)
        fail_lay.addWidget(self.btn_fail_sfx_test, 1, 3)

        def _pick_fail_sfx():
            path, _ = QFileDialog.getOpenFileName(self, "연승 실패 효과음 선택", "", "Sound (*.wav *.mp3)")
            if path:
                self.le_fail_sfx_path.setText(path)

        def _test_fail_sfx():
            p = str(self.le_fail_sfx_path.text() or "").strip()
            if not p:
                return
            player = getattr(self, "_burst_player", None)
            audio_out = getattr(self, "_burst_audio_out", None)
            if player is None or audio_out is None:
                try:
                    self._burst_audio_out = QAudioOutput()
                    self._burst_player = QMediaPlayer()
                    self._burst_player.setAudioOutput(self._burst_audio_out)
                    player = self._burst_player
                    audio_out = self._burst_audio_out
                except Exception:
                    return
            _play_media_sfx(player, audio_out, p)

        self.btn_fail_sfx_pick.clicked.connect(_pick_fail_sfx)
        self.btn_fail_sfx_test.clicked.connect(_test_fail_sfx)
        lay.addWidget(fail_group)

        btn_row = QHBoxLayout()
        self.btn_effects_apply = QPushButton("효과 적용")
        self.btn_effects_reset = QPushButton("기본값")
        self.btn_effects_reload = QPushButton("현재값 다시읽기")
        self.btn_effects_apply.clicked.connect(self._apply_win_effects_ui)
        self.btn_effects_reset.clicked.connect(self._reset_win_effects_ui)
        self.btn_effects_reload.clicked.connect(self._reload_win_effects_ui)
        btn_row.addWidget(self.btn_effects_apply)
        btn_row.addWidget(self.btn_effects_reset)
        btn_row.addWidget(self.btn_effects_reload)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self._load_win_effects_ui(self.cfg.win_effects)
        self._init_effects_live_apply()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        tab_lay = QVBoxLayout()
        tab_lay.addWidget(scroll)
        self.tab_effects.setLayout(tab_lay)

    def _init_effects_live_apply(self):
        if getattr(self, "_effects_live_ready", False):
            return
        self._effects_live_ready = True
        self._effects_live_timer = QTimer(self)
        self._effects_live_timer.setSingleShot(True)
        self._effects_live_timer.setInterval(140)
        self._effects_live_timer.timeout.connect(lambda: self._apply_win_effects_ui(silent=True))

        for w in self.tab_effects.findChildren(QSpinBox):
            w.valueChanged.connect(lambda _v: self._schedule_effects_live_apply())
        for w in self.tab_effects.findChildren(QDoubleSpinBox):
            w.valueChanged.connect(lambda _v: self._schedule_effects_live_apply())
        for w in self.tab_effects.findChildren(QLineEdit):
            w.textChanged.connect(lambda _t: self._schedule_effects_live_apply())
        for w in self.tab_effects.findChildren(QCheckBox):
            w.stateChanged.connect(lambda _s: self._schedule_effects_live_apply())
        for w in self.tab_effects.findChildren(QComboBox):
            w.currentIndexChanged.connect(lambda _i: self._schedule_effects_live_apply())

    def _schedule_effects_live_apply(self):
        if getattr(self, "_effects_loading", False):
            return
        t = getattr(self, "_effects_live_timer", None)
        if t is not None:
            t.start()

    def _open_stage_dialog(self):
        if hasattr(self, '_stage_dialog') and self._stage_dialog is not None and self._stage_dialog.isVisible():
            self._stage_dialog.raise_()
            self._stage_dialog.activateWindow()
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("연승 단계 편집")
        dlg.resize(700, 420)
        lay = QVBoxLayout(dlg)
        self.tbl_effect_stages = QTableWidget(0, 4)
        self.tbl_effect_stages.setHorizontalHeaderLabels(["몇 승부터", "색", "밝기", "두근거림"])
        self.tbl_effect_stages.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tbl_effect_stages)
        btns = QHBoxLayout()
        self.btn_stage_add = QPushButton("단계 추가")
        self.btn_stage_del = QPushButton("선택 삭제")
        self.btn_stage_sort = QPushButton("승수 순서 정리")
        self.btn_stage_add.clicked.connect(self._add_stage_row)
        self.btn_stage_del.clicked.connect(self._delete_stage_row)
        self.btn_stage_sort.clicked.connect(self._sort_stage_rows)
        btns.addWidget(self.btn_stage_add)
        btns.addWidget(self.btn_stage_del)
        btns.addWidget(self.btn_stage_sort)
        btns.addStretch(1)
        lay.addLayout(btns)
        row = QHBoxLayout()
        btn_ok = QPushButton("확인")
        btn_ok.clicked.connect(dlg.accept)
        row.addStretch(1)
        row.addWidget(btn_ok)
        lay.addLayout(row)
        self._set_stage_rows(self._stage_cache)
        dlg.finished.connect(lambda _r: self._on_stage_dialog_closed())
        self._stage_dialog = dlg
        dlg.show()

    def _on_stage_dialog_closed(self):
        self._stage_cache = self._collect_stage_rows()
        self._update_stage_summary()

    def _update_stage_summary(self):
        if not hasattr(self, 'lbl_stage_summary'):
            return
        parts = []
        for s in (self._stage_cache or []):
            parts.append(f"{int(s.get('min', 0))} wins")
        self.lbl_stage_summary.setText(" / ".join(parts) if parts else "단계 없음")
    def _add_stage_row(self, stage: Optional[dict] = None):
        if not hasattr(self, 'tbl_effect_stages') or self.tbl_effect_stages is None:
            self._stage_cache = list(self._stage_cache or [])
            self._stage_cache.append(stage or {})
            self._update_stage_summary()
            return
        r = self.tbl_effect_stages.rowCount()
        self.tbl_effect_stages.insertRow(r)
        sp_min = QSpinBox(); sp_min.setRange(0, 99); sp_min.setValue(int((stage or {}).get("min", 3)))
        self.tbl_effect_stages.setCellWidget(r, 0, sp_min)

        color = str((stage or {}).get("color", "#B9C7D6"))
        w_color = QWidget()
        h = QHBoxLayout(w_color); h.setContentsMargins(0, 0, 0, 0)
        le = QLineEdit(color)
        btn = QPushButton("색상")
        def _pick():
            c = QColor(le.text() or "#ffffff")
            q = QColorDialog.getColor(c, self)
            if q.isValid():
                le.setText(q.name())
        btn.clicked.connect(_pick)
        h.addWidget(le); h.addWidget(btn)
        self.tbl_effect_stages.setCellWidget(r, 1, w_color)

        sp_op = QDoubleSpinBox(); sp_op.setRange(0.0, 1.0); sp_op.setSingleStep(0.05)
        sp_op.setValue(float((stage or {}).get("opacity", 0.45)))
        self.tbl_effect_stages.setCellWidget(r, 2, sp_op)

        sp_pulse = QDoubleSpinBox(); sp_pulse.setRange(1.0, 2.0); sp_pulse.setSingleStep(0.02)
        sp_pulse.setValue(float((stage or {}).get("pulse", 1.04)))
        self.tbl_effect_stages.setCellWidget(r, 3, sp_pulse)

    def _delete_stage_row(self):
        row = self.tbl_effect_stages.currentRow()
        if row >= 0:
            self.tbl_effect_stages.removeRow(row)

    def _sort_stage_rows(self):
        stages = self._collect_stage_rows()
        stages.sort(key=lambda s: int(s.get("min", 0)))
        self._set_stage_rows(stages)

    def _collect_stage_rows(self) -> List[dict]:
        if not hasattr(self, 'tbl_effect_stages') or self.tbl_effect_stages is None:
            return list(self._stage_cache or [])
        stages = []
        for r in range(self.tbl_effect_stages.rowCount()):
            sp_min = self.tbl_effect_stages.cellWidget(r, 0)
            w_color = self.tbl_effect_stages.cellWidget(r, 1)
            le = w_color.findChild(QLineEdit)
            sp_op = self.tbl_effect_stages.cellWidget(r, 2)
            sp_pulse = self.tbl_effect_stages.cellWidget(r, 3)
            stages.append({
                "min": int(sp_min.value() if sp_min else 0),
                "color": str(le.text() if le else "#FFFFFF"),
                "opacity": float(sp_op.value() if sp_op else 0.0),
                "pulse": float(sp_pulse.value() if sp_pulse else 1.0),
            })
        return stages

    def _set_stage_rows(self, stages: List[dict]):
        self._stage_cache = list(stages or [])
        if not hasattr(self, 'tbl_effect_stages') or self.tbl_effect_stages is None:
            self._update_stage_summary()
            return
        self.tbl_effect_stages.setRowCount(0)
        for s in stages:
            self._add_stage_row(s)

    def _load_win_effects_ui(self, data: dict):
        self._effects_loading = True
        cfg = _merge_dict(default_win_effects(), data or {})
        self._set_stage_rows(list(cfg.get("stages", []) or []))
        aura = cfg.get("aura", {})
        def_aura = default_win_effects().get("aura", {})
        self.chk_aura_enabled.setChecked(bool(aura.get("enabled", True)))
        self.sp_aura_frame_pad.setValue(int(aura.get("frame_padding", 12)))
        self.sp_aura_outer_pad.setValue(int(aura.get("outer_padding", 14)))
        self.sp_aura_border1.setValue(int(aura.get("border1", 2)))
        self.sp_aura_border2.setValue(int(aura.get("border2", 1)))
        self.sp_aura_border3.setValue(int(aura.get("border3", 1)))
        self.chk_backdrop.setChecked(bool(aura.get("backdrop_enabled", True)))
        self.le_backdrop_color.setText(str(aura.get("backdrop_color", "#000000")))
        self.sp_backdrop_opacity.setValue(float(aura.get("backdrop_opacity", 0.25)))
        self.sp_backdrop_pad.setValue(int(aura.get("backdrop_pad", 8)))
        self.le_border_color.setText(str(aura.get("border_color", "")))
        self.sp_border_opacity.setValue(float(aura.get("border_opacity", 0.6)))
        self.chk_border_fx.setChecked(bool(aura.get("border_effect_enabled", True)))
        self.sp_frame_emit.setValue(int(aura.get("frame_spark_emit", 6)))
        self.sp_frame_size.setValue(int(aura.get("frame_spark_size", 8)))
        self.sp_frame_var.setValue(int(aura.get("frame_spark_size_var", 6)))
        self.sp_frame_pace.setValue(int(aura.get("frame_spark_pace", 40)))
        self.sp_flame_emit.setValue(int(aura.get("flame_emit", 12)))
        self.sp_flame_size.setValue(int(aura.get("flame_size", 20)))
        self.sp_flame_var.setValue(int(aura.get("flame_size_var", 14)))
        self.sp_smoke_emit.setValue(int(aura.get("smoke_emit", 6)))
        self.sp_smoke_size.setValue(int(aura.get("smoke_size", 36)))
        self.sp_smoke_var.setValue(int(aura.get("smoke_size_var", 20)))
        self.sp_spark_emit.setValue(int(aura.get("spark_emit", 10)))
        self.sp_spark_size.setValue(int(aura.get("spark_size", 10)))
        self.sp_spark_var.setValue(int(aura.get("spark_size_var", 8)))
        self.sp_turbulence.setValue(int(aura.get("turbulence", 18)))
        self.sp_aura_blur.setValue(int(aura.get("blur_radius", 0)))
        for key in ("core", "body", "glow", "wisps", "spark"):
            adv = aura.get(key, {}) or {}
            adv_def = (def_aura.get(key, {}) or {})
            controls = getattr(self, "_aura_adv", {}).get(key, {})
            if not controls:
                continue
            controls["emit"].setValue(float(adv.get("emit_mul", adv_def.get("emit_mul", 1.0))))
            controls["size"].setValue(float(adv.get("size_mul", adv_def.get("size_mul", 1.0))))
            controls["size_var"].setValue(float(adv.get("size_var_mul", adv_def.get("size_var_mul", 1.0))))
            controls["angle"].setValue(float(adv.get("angle_var", adv_def.get("angle_var", 0.0))))
            controls["speed"].setValue(float(adv.get("speed", adv_def.get("speed", 0.0))))
            controls["speed_var"].setValue(float(adv.get("speed_var", adv_def.get("speed_var", 0.0))))
            controls["alpha"].setValue(float(adv.get("alpha", adv_def.get("alpha", 1.0))))
        if hasattr(self, "sp_aura_core_turb"):
            self.sp_aura_core_turb.setValue(float(aura.get("core", {}).get("turb_mul", def_aura.get("core", {}).get("turb_mul", 0.15))))
        if hasattr(self, "sp_aura_glow_turb"):
            self.sp_aura_glow_turb.setValue(float(aura.get("glow", {}).get("turb_mul", def_aura.get("glow", {}).get("turb_mul", 0.35))))

        inner = cfg.get("inner", {})
        for key, ctrls in self._inner_controls.items():
            eff = inner.get(key, {})
            ctrls["chk"].setChecked(bool(eff.get("enabled", True)))
            ctrls["min"].setValue(int(eff.get("min", 3)))
            if ctrls["range"]:
                ctrls["a"].setValue(float(eff.get("opacity_min", 0.15)))
                ctrls["b"].setValue(float(eff.get("opacity_max", 0.4)))
            else:
                if key == "core":
                    ctrls["a"].setValue(float(eff.get("opacity_max", 0.5)))
                else:
                    ctrls["a"].setValue(float(eff.get("opacity", 0.12)))
            if ctrls["int"] is not None:
                ctrls["int"].setValue(int(eff.get("interval", eff.get("speed", 140))))

        self.sp_core_size.setValue(float(inner.get("core", {}).get("size", 0.35)))
        self.sp_core_period.setValue(int(inner.get("core", {}).get("period", 900)))

        win_text = cfg.get("win_text", {})
        self.chk_win_text_enabled.setChecked(bool(win_text.get("enabled", True)))
        self.le_win_text_format.setText(str(win_text.get("format", "W{n}")))
        self.sp_win_text_scale.setValue(float(win_text.get("size_scale", 0.18)))
        self.sp_win_text_min.setValue(int(win_text.get("size_min", 11)))
        self.sp_win_text_max.setValue(int(win_text.get("size_max", 18)))
        self.sp_win_text_offset.setValue(float(win_text.get("offset_ratio", 0.22)))
        self.sp_win_text_highlight.setValue(float(win_text.get("highlight_height", 0.55)))
        self.le_win_text_base.setText(str(win_text.get("base_color", "#d6dbe0")))
        self.le_win_text_highlight.setText(str(win_text.get("highlight_color", "#f8fbff")))
        self.le_win_text_outline.setText(str(win_text.get("outline_color", "#2b2f34")))
        self.le_win_text_shadow.setText(str(win_text.get("shadow_color", "#0b0f14")))
        self.sp_win_text_shadow_op.setValue(float(win_text.get("shadow_opacity", 0.6)))

        burst = cfg.get("burst", {}) or {}
        milestones = burst.get("milestones", [3, 6, 9, 12, 16, 21, 30])
        try:
            ms_text = ", ".join(str(int(x)) for x in (milestones or []))
        except Exception:
            ms_text = "3,6,9,12,16,21,30"
        if hasattr(self, "le_burst_milestones"):
            self.le_burst_milestones.setText(ms_text)
        if hasattr(self, "chk_burst_sfx"):
            self.chk_burst_sfx.setChecked(bool(burst.get("sfx_enabled", False)))
        if hasattr(self, "le_burst_sfx_path"):
            self.le_burst_sfx_path.setText(str(burst.get("sfx_path", "")))

        nameplates = cfg.get("nameplates", {}) or {}
        if hasattr(self, "chk_nameplate_enabled"):
            self.chk_nameplate_enabled.setChecked(bool(nameplates.get("enabled", True)))
        if hasattr(self, "sp_nameplate_scale"):
            self.sp_nameplate_scale.setValue(float(nameplates.get("scale", 1.0)))
        if hasattr(self, "sp_nameplate_gap"):
            self.sp_nameplate_gap.setValue(int(nameplates.get("gap", 6)))
        if hasattr(self, "cmb_nameplate_side_blue"):
            self.cmb_nameplate_side_blue.setCurrentIndex(0 if str(nameplates.get("side_blue", "left")) == "left" else 1)
        if hasattr(self, "cmb_nameplate_side_red"):
            self.cmb_nameplate_side_red.setCurrentIndex(0 if str(nameplates.get("side_red", "right")) == "left" else 1)
        imgs = nameplates.get("images", []) or []
        if hasattr(self, "_nameplate_rows"):
            for i, row in enumerate(self._nameplate_rows):
                le = row.get("le")
                if le is not None:
                    le.setText(str(imgs[i] if i < len(imgs) else ""))

        portrait = cfg.get("portrait", {}) or {}
        if hasattr(self, "sp_portrait_zoom"):
            self.sp_portrait_zoom.setValue(float(portrait.get("zoom", 1.25)))
        if hasattr(self, "sp_portrait_offset_x"):
            self.sp_portrait_offset_x.setValue(float(portrait.get("offset_x", 0.0)))
        if hasattr(self, "sp_portrait_offset_y"):
            self.sp_portrait_offset_y.setValue(float(portrait.get("offset_y", -0.08)))

        fail = cfg.get("fail", {}) or {}
        if hasattr(self, "chk_fail_enabled"):
            self.chk_fail_enabled.setChecked(bool(fail.get("enabled", True)))
        if hasattr(self, "chk_fail_sfx"):
            self.chk_fail_sfx.setChecked(bool(fail.get("sfx_enabled", False)))
        if hasattr(self, "le_fail_sfx_path"):
            self.le_fail_sfx_path.setText(str(fail.get("sfx_path", "")))
        self._effects_loading = False

    def _collect_win_effects_ui(self) -> dict:
        cfg = _merge_dict(default_win_effects(), self.cfg.win_effects or {})
        cfg["stages"] = self._collect_stage_rows()
        cfg["aura"]["enabled"] = bool(self.chk_aura_enabled.isChecked())
        cfg["aura"]["frame_padding"] = int(self.sp_aura_frame_pad.value())
        cfg["aura"]["outer_padding"] = int(self.sp_aura_outer_pad.value())
        cfg["aura"]["border1"] = int(self.sp_aura_border1.value())
        cfg["aura"]["border2"] = int(self.sp_aura_border2.value())
        cfg["aura"]["border3"] = int(self.sp_aura_border3.value())
        cfg["aura"]["backdrop_enabled"] = bool(self.chk_backdrop.isChecked())
        cfg["aura"]["backdrop_color"] = str(self.le_backdrop_color.text()).strip() or "#000000"
        cfg["aura"]["backdrop_opacity"] = float(self.sp_backdrop_opacity.value())
        cfg["aura"]["backdrop_pad"] = int(self.sp_backdrop_pad.value())
        cfg["aura"]["border_color"] = str(self.le_border_color.text()).strip()
        cfg["aura"]["border_opacity"] = float(self.sp_border_opacity.value())
        cfg["aura"]["border_effect_enabled"] = bool(self.chk_border_fx.isChecked())
        cfg["aura"]["frame_spark_emit"] = int(self.sp_frame_emit.value())
        cfg["aura"]["frame_spark_size"] = int(self.sp_frame_size.value())
        cfg["aura"]["frame_spark_size_var"] = int(self.sp_frame_var.value())
        cfg["aura"]["frame_spark_pace"] = int(self.sp_frame_pace.value())
        cfg["aura"]["flame_emit"] = int(self.sp_flame_emit.value())
        cfg["aura"]["flame_size"] = int(self.sp_flame_size.value())
        cfg["aura"]["flame_size_var"] = int(self.sp_flame_var.value())
        cfg["aura"]["smoke_emit"] = int(self.sp_smoke_emit.value())
        cfg["aura"]["smoke_size"] = int(self.sp_smoke_size.value())
        cfg["aura"]["smoke_size_var"] = int(self.sp_smoke_var.value())
        cfg["aura"]["spark_emit"] = int(self.sp_spark_emit.value())
        cfg["aura"]["spark_size"] = int(self.sp_spark_size.value())
        cfg["aura"]["spark_size_var"] = int(self.sp_spark_var.value())
        cfg["aura"]["turbulence"] = int(self.sp_turbulence.value())
        cfg["aura"]["blur_radius"] = int(self.sp_aura_blur.value())
        for key in ("core", "body", "glow", "wisps", "spark"):
            controls = getattr(self, "_aura_adv", {}).get(key, {})
            if not controls:
                continue
            cfg["aura"][key] = cfg["aura"].get(key, {})
            cfg["aura"][key]["emit_mul"] = float(controls["emit"].value())
            cfg["aura"][key]["size_mul"] = float(controls["size"].value())
            cfg["aura"][key]["size_var_mul"] = float(controls["size_var"].value())
            cfg["aura"][key]["angle_var"] = float(controls["angle"].value())
            cfg["aura"][key]["speed"] = float(controls["speed"].value())
            cfg["aura"][key]["speed_var"] = float(controls["speed_var"].value())
            cfg["aura"][key]["alpha"] = float(controls["alpha"].value())
        if hasattr(self, "sp_aura_core_turb"):
            cfg["aura"]["core"] = cfg["aura"].get("core", {})
            cfg["aura"]["core"]["turb_mul"] = float(self.sp_aura_core_turb.value())
        if hasattr(self, "sp_aura_glow_turb"):
            cfg["aura"]["glow"] = cfg["aura"].get("glow", {})
            cfg["aura"]["glow"]["turb_mul"] = float(self.sp_aura_glow_turb.value())

        for key, ctrls in self._inner_controls.items():
            eff = cfg["inner"].get(key, {})
            eff["enabled"] = bool(ctrls["chk"].isChecked())
            eff["min"] = int(ctrls["min"].value())
            if ctrls["range"]:
                eff["opacity_min"] = float(ctrls["a"].value())
                eff["opacity_max"] = float(ctrls["b"].value())
            else:
                if key == "core":
                    eff["opacity_max"] = float(ctrls["a"].value())
                else:
                    eff["opacity"] = float(ctrls["a"].value())
            if ctrls["int"] is not None:
                if ctrls["speed"]:
                    eff["speed"] = int(ctrls["int"].value())
                else:
                    eff["interval"] = int(ctrls["int"].value())
            cfg["inner"][key] = eff

        cfg["inner"]["core"]["size"] = float(self.sp_core_size.value())
        cfg["inner"]["core"]["period"] = int(self.sp_core_period.value())

        cfg["win_text"]["enabled"] = bool(self.chk_win_text_enabled.isChecked())
        cfg["win_text"]["format"] = str(self.le_win_text_format.text() or "W{n}")
        cfg["win_text"]["size_scale"] = float(self.sp_win_text_scale.value())
        cfg["win_text"]["size_min"] = int(self.sp_win_text_min.value())
        cfg["win_text"]["size_max"] = int(self.sp_win_text_max.value())
        cfg["win_text"]["offset_ratio"] = float(self.sp_win_text_offset.value())
        cfg["win_text"]["highlight_height"] = float(self.sp_win_text_highlight.value())
        cfg["win_text"]["base_color"] = str(self.le_win_text_base.text() or "#d6dbe0")
        cfg["win_text"]["highlight_color"] = str(self.le_win_text_highlight.text() or "#f8fbff")
        cfg["win_text"]["outline_color"] = str(self.le_win_text_outline.text() or "#2b2f34")
        cfg["win_text"]["shadow_color"] = str(self.le_win_text_shadow.text() or "#0b0f14")
        cfg["win_text"]["shadow_opacity"] = float(self.sp_win_text_shadow_op.value())
        if hasattr(self, "le_burst_milestones"):
            raw = str(self.le_burst_milestones.text() or "").strip()
            parts = [p for p in re.split(r"[\\s,;]+", raw) if p]
            ms = []
            for p in parts:
                try:
                    v = int(p)
                except Exception:
                    continue
                if v <= 0:
                    continue
                if v not in ms:
                    ms.append(v)
            if not ms:
                ms = [3, 6, 9, 12, 16, 21, 30]
            cfg["burst"] = cfg.get("burst", {})
            cfg["burst"]["milestones"] = ms
            cfg["burst"]["sfx_enabled"] = bool(getattr(self, "chk_burst_sfx", QCheckBox()).isChecked())
            cfg["burst"]["sfx_path"] = str(getattr(self, "le_burst_sfx_path", QLineEdit()).text() or "").strip()
        cfg["nameplates"] = cfg.get("nameplates", {})
        cfg["nameplates"]["enabled"] = bool(getattr(self, "chk_nameplate_enabled", QCheckBox()).isChecked())
        cfg["nameplates"]["scale"] = float(getattr(self, "sp_nameplate_scale", QDoubleSpinBox()).value())
        cfg["nameplates"]["gap"] = int(getattr(self, "sp_nameplate_gap", QSpinBox()).value())
        cfg["nameplates"]["side_blue"] = str(getattr(self, "cmb_nameplate_side_blue", QComboBox()).currentData() or "left")
        cfg["nameplates"]["side_red"] = str(getattr(self, "cmb_nameplate_side_red", QComboBox()).currentData() or "right")
        if hasattr(self, "_nameplate_rows"):
            cfg["nameplates"]["milestones"] = [int(r.get("min", 0)) for r in self._nameplate_rows]
            cfg["nameplates"]["images"] = [str((r.get("le").text() if r.get("le") else "") or "").strip() for r in self._nameplate_rows]
        cfg["portrait"] = cfg.get("portrait", {})
        cfg["portrait"]["zoom"] = float(getattr(self, "sp_portrait_zoom", QDoubleSpinBox()).value())
        cfg["portrait"]["offset_x"] = float(getattr(self, "sp_portrait_offset_x", QDoubleSpinBox()).value())
        cfg["portrait"]["offset_y"] = float(getattr(self, "sp_portrait_offset_y", QDoubleSpinBox()).value())
        cfg["fail"] = cfg.get("fail", {})
        cfg["fail"]["enabled"] = bool(getattr(self, "chk_fail_enabled", QCheckBox()).isChecked())
        cfg["fail"]["sfx_enabled"] = bool(getattr(self, "chk_fail_sfx", QCheckBox()).isChecked())
        cfg["fail"]["sfx_path"] = str(getattr(self, "le_fail_sfx_path", QLineEdit()).text() or "").strip()
        return _normalize_win_effects_paths(cfg)

    def _apply_win_effects_ui(self, silent: bool = False):
        self.cfg.win_effects = self._collect_win_effects_ui()
        try:
            if self.controller:
                self.controller.ui_update.emit({"effect_settings": self.cfg.win_effects})
        except Exception:
            pass
        if self._cfg_path:
            try:
                self.cfg.to_json(self._cfg_path)
            except Exception:
                pass
        if not silent:
            QMessageBox.information(self, "적용", "연승 이펙트가 적용되었습니다.")

    def _reset_win_effects_ui(self):
        self._load_win_effects_ui(default_win_effects())

    def _reload_win_effects_ui(self):
        self._load_win_effects_ui(self.cfg.win_effects)

    def _apply_timer_settings_now(self):
        total = int(self.sp_timer_total.value())
        current = min(int(self.sp_timer_current.value()), total)
        round_sec = int(self.sp_timer_round_sec.value())
        rest_sec = int(self.sp_timer_rest_sec.value())
        left_sec = int(self.sp_timer_left.value())
        self.sp_timer_current.setValue(current)
        self.cfg.timer_total_rounds = total
        self.cfg.timer_current_round = current
        self.cfg.timer_round_sec = round_sec
        self.cfg.timer_rest_sec = rest_sec
        self.cfg.timer_seconds_left = left_sec
        if hasattr(self, "chk_rest_30s_tts"):
            self.cfg.timer_rest_30s_tts_enabled = bool(self.chk_rest_30s_tts.isChecked())
        if hasattr(self, "sp_rest_30s_tts_rate"):
            self.cfg.timer_rest_30s_tts_rate = int(self.sp_rest_30s_tts_rate.value())
        try:
            self.controller.ui_update.emit({
                "timer_total_rounds": total,
                "timer_current_round": current,
                "timer_round_sec": round_sec,
                "timer_rest_sec": rest_sec,
                "timer_seconds_left": left_sec,
            })
        except Exception:
            pass
        try:
            self._timer_apply_armed_until = time.time() + 1.0
        except Exception:
            self._timer_apply_armed_until = 0.0
        self._schedule_apply()

    def _queue_reload_players_cards(self):
        # Let IME composition settle first so Korean search updates immediately.
        try:
            QTimer.singleShot(0, self._reload_players_cards)
        except Exception:
            self._reload_players_cards()

    def _on_players_search_query_changed(self, text: str):
        self._players_search_query = self._player_name_key(text)
        self._queue_reload_players_cards()

    def _reload_players_cards(self):
        if not hasattr(self, "players_grid"):
            return
        self._clear_layout(self.players_grid)
        is_list = self.cmb_players_view.currentText() == "리스트"
        avatar_shape = "hex" if self.cmb_players_avatar.currentText() == "사각형" else "circle"
        cols = 1 if is_list else 3
        idx = 0
        search_name = str(getattr(self, "_players_search_query", "") or "")
        if not search_name and hasattr(self, "txt_players_search"):
            search_name = self._player_name_key(self.txt_players_search.text())
        sort_mode = "ID"
        if hasattr(self, "cmb_players_sort"):
            sort_mode = self.cmb_players_sort.currentText() or "ID"
        if sort_mode == "닉네임":
            items = sorted(
                self.cfg.players.items(),
                key=lambda kv: (str(kv[1] or "").lower(), str(kv[0] or "").lower()),
            )
        else:
            items = sorted(self.cfg.players.items(), key=lambda kv: str(kv[0] or "").lower())
        for gid, name in items:
            if search_name and search_name not in self._player_name_key(name):
                continue
            img_path = _player_image_path_for_gid(self.cfg, gid)
            if hasattr(self, "chk_players_missing_img") and self.chk_players_missing_img.isChecked():
                if img_path:
                    continue
            card = PlayerCard(
                self.players_container,
                gid,
                name,
                img_path,
                self.open_profile_dialog,
                self.delete_player_by_id,
                avatar_shape,
                is_list,
            )
            row = idx // cols
            col = idx % cols
            self.players_grid.addWidget(card, row, col)
            idx += 1
        for col in range(cols):
            self.players_grid.setColumnStretch(col, 1)
        self._refresh_player_manage_ui()

    def _refresh_player_manage_ui(self, keep_name: str = "", keep_gid: str = ""):
        if not hasattr(self, "cmb_manage_name") or not hasattr(self, "cmb_manage_gid"):
            return
        selected_name = str(keep_name or self.cmb_manage_name.currentText() or "").strip()
        selected_gid = str(keep_gid or self.cmb_manage_gid.currentText() or "").strip().upper()
        names = sorted({str(v or "").strip() for v in self.cfg.players.values() if str(v or "").strip()}, key=lambda s: s.lower())
        self.cmb_manage_name.blockSignals(True)
        self.cmb_manage_name.clear()
        if not names:
            self.cmb_manage_name.addItem("-")
            self.cmb_manage_name.setEnabled(False)
            self.cmb_manage_gid.clear()
            self.cmb_manage_gid.addItem("-")
            self.cmb_manage_gid.setEnabled(False)
            self.cmb_manage_name.blockSignals(False)
            return
        self.cmb_manage_name.setEnabled(True)
        self.cmb_manage_name.addItems(names)
        if selected_name in names:
            self.cmb_manage_name.setCurrentText(selected_name)
        self.cmb_manage_name.blockSignals(False)
        self._refresh_player_manage_gid(selected_gid)

    def _refresh_player_manage_gid(self, keep_gid: str = ""):
        if not hasattr(self, "cmb_manage_name") or not hasattr(self, "cmb_manage_gid"):
            return
        name = str(self.cmb_manage_name.currentText() or "").strip()
        gids = sorted(
            [str(gid or "").upper().strip() for gid, nm in self.cfg.players.items() if str(nm or "").strip() == name],
            key=lambda s: s.lower(),
        )
        self.cmb_manage_gid.blockSignals(True)
        self.cmb_manage_gid.clear()
        if not gids:
            self.cmb_manage_gid.addItem("-")
            self.cmb_manage_gid.setEnabled(False)
            self.cmb_manage_gid.blockSignals(False)
            return
        self.cmb_manage_gid.setEnabled(True)
        self.cmb_manage_gid.addItems(gids)
        if keep_gid and keep_gid in gids:
            self.cmb_manage_gid.setCurrentText(keep_gid)
        self.cmb_manage_gid.blockSignals(False)

    def _on_manage_name_changed(self, _idx: int):
        self._refresh_player_manage_gid()

    def _player_name_key(self, name: str) -> str:
        return re.sub(r"\s+", " ", str(name or "").strip()).lower()

    def _player_similarity(self, a: str, b: str) -> int:
        sa = str(a or "").strip().lower()
        sb = str(b or "").strip().lower()
        if not sa or not sb:
            return 0
        if HAS_RAPIDFUZZ:
            try:
                return int(rf_fuzz.ratio(sa, sb))
            except Exception:
                pass
        common = sum(1 for ch in sa if ch in sb)
        return int(100 * common / max(1, max(len(sa), len(sb))))

    def _player_gid_key(self, gid: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", str(gid or "").upper())

    def _sanitize_saved_player_state(self):
        blue_id = str(getattr(self.cfg, "current_blue_id", "") or "").upper().strip()
        red_id = str(getattr(self.cfg, "current_red_id", "") or "").upper().strip()
        self.cfg.current_blue_id = blue_id
        self.cfg.current_red_id = red_id
        self.cfg.current_blue_registered = bool(blue_id and blue_id in self.cfg.players)
        self.cfg.current_red_registered = bool(red_id and red_id in self.cfg.players)
        self.cfg.current_blue_valid = bool(blue_id and blue_id in self.cfg.players)
        self.cfg.current_red_valid = bool(red_id and red_id in self.cfg.players)

    def _canonical_player_gid(self, gid: str, threshold: int = 70) -> str:
        raw = str(gid or "").strip().upper()
        if not raw:
            return ""
        if raw in self.cfg.players:
            return raw
        key = self._player_gid_key(raw)
        if not key:
            return raw
        best_gid = ""
        best_sc = -1
        for existing_gid in self.cfg.players.keys():
            ex = str(existing_gid or "").strip().upper()
            if not ex:
                continue
            ex_key = self._player_gid_key(ex)
            if not ex_key:
                continue
            if ex_key == key:
                return ex
            sc = self._player_similarity(key, ex_key)
            if sc > best_sc:
                best_sc = sc
                best_gid = ex
        if best_sc >= int(threshold):
            return best_gid
        return raw

    def _canonical_player_name(self, name: str) -> str:
        raw = str(name or "").strip()
        if not raw:
            return ""
        key = self._player_name_key(raw)
        key_comp = re.sub(r"\s+", "", key)
        best_name = raw
        best_sc = -1
        for existing in self.cfg.players.values():
            en = str(existing or "").strip()
            if not en:
                continue
            en_key = self._player_name_key(en)
            if en_key == key:
                return en
            en_comp = re.sub(r"\s+", "", en_key)
            sc = self._player_similarity(key_comp, en_comp)
            if sc > best_sc:
                best_sc = sc
                best_name = en
        if best_sc >= 70:
            return best_name
        return raw

    def _split_player_gids(self, gids: str) -> List[str]:
        out: List[str] = []
        seen = set()
        for part in re.split(r"[,;\s]+", str(gids or "")):
            gid = str(part or "").strip().upper()
            if not gid:
                continue
            if not re.fullmatch(r"[A-Z0-9_.-]+", gid):
                continue
            if gid in seen:
                continue
            seen.add(gid)
            out.append(gid)
        return out

    def _merge_player_entry(self, gid: str, name: str, gid_threshold: int = 70) -> Tuple[bool, bool, bool, bool]:
        gid_key = self._canonical_player_gid(str(gid or "").strip().upper(), threshold=int(gid_threshold))
        raw_name = str(name or "").strip()
        if not gid_key or not raw_name:
            return False, False, False, False

        canonical_name = self._canonical_player_name(raw_name)
        name_merged = canonical_name != raw_name
        id_merged = gid_key in self.cfg.players

        if not id_merged:
            self.cfg.players[gid_key] = canonical_name
        else:
            canonical_name = str(self.cfg.players.get(gid_key, canonical_name) or canonical_name)

        inherited_img = False
        cur_img = str(self.cfg.players_images.get(gid_key, "") or "").strip()
        if not cur_img:
            inherited = ""
            for ex_gid, ex_name in self.cfg.players.items():
                if str(ex_gid or "").upper().strip() == gid_key:
                    continue
                if self._player_name_key(str(ex_name or "")) != self._player_name_key(canonical_name):
                    continue
                inherited = str(self.cfg.players_images.get(str(ex_gid or "").upper().strip(), "") or "").strip()
                if inherited:
                    break
            if inherited:
                self.cfg.players_images[gid_key] = to_app_rel(inherited)
                inherited_img = True
            elif gid_key not in self.cfg.players_images:
                self.cfg.players_images[gid_key] = ""
        self.cfg.players_countries.setdefault(gid_key, "KR")
        self.cfg.players_flags.setdefault(gid_key, "")
        if not str(self.cfg.players_flags.get(gid_key, "") or "").strip():
            for ex_gid, ex_name in self.cfg.players.items():
                ex_key = str(ex_gid or "").upper().strip()
                if ex_key == gid_key:
                    continue
                if self._player_name_key(str(ex_name or "")) != self._player_name_key(canonical_name):
                    continue
                self.cfg.players_countries[gid_key] = _normalize_player_country(
                    self.cfg.players_countries.get(ex_key, self.cfg.players_countries.get(gid_key, "KR"))
                )
                inherited_flag = str(self.cfg.players_flags.get(ex_key, "") or "").strip()
                if inherited_flag:
                    self.cfg.players_flags[gid_key] = to_app_rel(inherited_flag)
                break
        return True, id_merged, name_merged, inherited_img

    def _add_player_id_to_selected_name(self):
        if not hasattr(self, "cmb_manage_name") or not hasattr(self, "txt_manage_add_gid"):
            return
        name = str(self.cmb_manage_name.currentText() or "").strip()
        gid = str(self.txt_manage_add_gid.text() or "").strip().upper()
        if not name or name == "-":
            QMessageBox.information(self, "추가", "닉네임을 먼저 선택하세요.")
            return
        if not gid:
            QMessageBox.information(self, "추가", "추가할 GAME_ID를 입력하세요.")
            return
        gids = self._split_player_gids(gid)
        if not gids:
            return
        merged_count = 0
        first_gid = gids[0]
        for one_gid in gids:
            ok, id_merged, _, _ = self._merge_player_entry(one_gid, name, gid_threshold=100)
            if ok and id_merged:
                merged_count += 1
        if merged_count:
            QMessageBox.information(self, "통합", "이미 있는 GAME_ID라 기존 정보로 통합했습니다.")
        self.txt_manage_add_gid.clear()
        self._reload_players_cards()
        self._refresh_player_manage_ui(keep_name=name, keep_gid=first_gid)

    def _delete_selected_player_id_by_name(self):
        if not hasattr(self, "cmb_manage_gid"):
            return
        gid = str(self.cmb_manage_gid.currentText() or "").strip().upper()
        if not gid or gid == "-":
            QMessageBox.information(self, "삭제", "삭제할 GAME_ID를 선택하세요.")
            return
        self.delete_player_by_id(gid)

    def _delete_all_player_ids_by_name(self):
        if not hasattr(self, "cmb_manage_name"):
            return
        name = str(self.cmb_manage_name.currentText() or "").strip()
        if not name or name == "-":
            QMessageBox.information(self, "삭제", "닉네임을 선택하세요.")
            return
        gids = [str(gid or "").upper().strip() for gid, nm in self.cfg.players.items() if str(nm or "").strip() == name]
        if not gids:
            QMessageBox.information(self, "삭제", "해당 닉네임에 등록된 GAME_ID가 없습니다.")
            return
        resp = QMessageBox.question(
            self,
            "닉네임 전체 삭제",
            f"'{name}' 닉네임의 GAME_ID {len(gids)}개를 모두 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        for gid in gids:
            if gid in self.cfg.players:
                del self.cfg.players[gid]
            if gid in self.cfg.players_images:
                del self.cfg.players_images[gid]
            if gid in self.cfg.players_countries:
                del self.cfg.players_countries[gid]
            if gid in self.cfg.players_flags:
                del self.cfg.players_flags[gid]
        self._sanitize_saved_player_state()
        self._reload_players_cards()

    def _export_players_txt(self):
        items = sorted(
            self.cfg.players.items(),
            key=lambda kv: (str(kv[1] or "").lower(), str(kv[0] or "").lower()),
        )
        if not items:
            QMessageBox.information(self, "내보내기", "등록된 선수가 없습니다.")
            return
        lines = []
        for gid, name in items:
            nm = str(name or "").strip()
            pid = str(gid or "").strip()
            if not nm and not pid:
                continue
            if not nm:
                lines.append(pid)
            elif not pid:
                lines.append(nm)
            else:
                lines.append(f"{nm} {pid}")
        if not lines:
            QMessageBox.information(self, "내보내기", "내보낼 데이터가 없습니다.")
            return
        base = os.path.dirname(os.path.abspath(self._cfg_path)) if self._cfg_path else get_app_base_dir()
        default_name = f"players_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        default_path = os.path.join(base, default_name)
        path, _ = QFileDialog.getSaveFileName(self, "선수 명단 TXT 저장", default_path, "Text (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            QMessageBox.information(self, "내보내기", f"저장 완료\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "내보내기 실패", f"파일 저장 중 오류가 발생했습니다.\n{e}")

    def _parse_player_line(self, line: str) -> Tuple[str, List[str], str]:
        raw = str(line or "").strip()
        if not raw:
            return "", [], ""
        if raw.startswith("#") or raw.startswith("//"):
            return "", [], ""
        parts = raw.split()
        if len(parts) < 2:
            return "", [], ""
        img_url = ""
        gid_index = -1
        if len(parts) >= 3:
            maybe_url = str(parts[-1] or "").strip()
            parsed = urlparse(maybe_url)
            if parsed.scheme in ("http", "https") and bool(parsed.netloc):
                img_url = maybe_url
                gid_index = -2
        gid_raw = str(parts[gid_index] or "").strip()
        gids = self._split_player_gids(gid_raw)
        if not gids:
            return "", [], ""
        if gid_index == -2:
            name = " ".join(parts[:-2]).strip()
        else:
            name = " ".join(parts[:-1]).strip()
        if not name:
            return "", [], ""
        return name, gids, img_url

    def _import_players_from_text(self, text: str) -> Tuple[int, int, int, int, int, int, int]:
        added = 0
        id_merged = 0
        name_merged = 0
        skipped = 0
        inherited_img = 0
        image_applied = 0
        image_failed = 0
        image_applied = 0
        image_failed = 0
        for line in str(text or "").splitlines():
            raw = str(line or "").strip()
            if not raw or raw.startswith("#") or raw.startswith("//"):
                continue
            name, gids, img_url = self._parse_player_line(raw)
            if not name or not gids:
                skipped += 1
                continue
            canonical_gids: List[str] = []
            for gid in gids:
                ok, merged_id, merged_name, inherited = self._merge_player_entry(gid, name, gid_threshold=100)
                if not ok:
                    continue
                gid_key = self._canonical_player_gid(str(gid or "").strip().upper(), threshold=100) or gid
                canonical_gids.append(gid_key)
                if merged_id:
                    id_merged += 1
                else:
                    added += 1
                if merged_name:
                    name_merged += 1
                if inherited and not img_url:
                    inherited_img += 1
            if not canonical_gids:
                skipped += 1
                continue
            if img_url:
                primary_gid = canonical_gids[0]
                path = _download_image_url(img_url, primary_gid)
                if path:
                    rel_path = to_app_rel(path)
                    for gid_key in canonical_gids:
                        self.cfg.players_images[gid_key] = rel_path
                    image_applied += len(canonical_gids)
                else:
                    image_failed += 1
        return added, id_merged, name_merged, skipped, inherited_img, image_applied, image_failed

    def _import_players_txt(self):
        base = os.path.dirname(os.path.abspath(self._cfg_path)) if self._cfg_path else get_app_base_dir()
        paths, _ = QFileDialog.getOpenFileNames(self, "선수 명단 TXT 불러오기", base, "Text (*.txt);;All files (*.*)")
        if not paths:
            return

        added = 0
        id_merged = 0
        name_merged = 0
        skipped = 0
        inherited_img = 0

        for path in paths:
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    text = f.read()
            except Exception as e:
                QMessageBox.warning(self, "불러오기 실패", f"파일을 읽을 수 없습니다.\n{path}\n{e}")
                continue
            a, mid, mname, s, inh, img_ok, img_fail = self._import_players_from_text(text)
            added += a
            id_merged += mid
            name_merged += mname
            skipped += s
            inherited_img += inh
            image_applied += img_ok
            image_failed += img_fail

        self._reload_players_cards()
        QMessageBox.information(
            self,
            "불러오기 완료",
            f"추가: {added}\nID 중복 통합: {id_merged}\n닉네임 통합: {name_merged}\n건너뜀: {skipped}\n이미지 상속: {inherited_img}\n이미지 적용: {image_applied}\n이미지 실패: {image_failed}",
        )

    def _import_players_paste(self):
        text, ok = QInputDialog.getMultiLineText(
            self,
            "명단 텍스트 붙여넣기",
            "각 줄에 '닉네임 GAME_ID1,ID2 [이미지URL]' 형식으로 입력:",
            "",
        )
        if not ok:
            return
        if not str(text or "").strip():
            QMessageBox.information(self, "불러오기", "붙여넣은 내용이 없습니다.")
            return
        added, id_merged, name_merged, skipped, inherited_img, image_applied, image_failed = self._import_players_from_text(text)
        self._reload_players_cards()
        QMessageBox.information(
            self,
            "불러오기 완료",
            f"추가: {added}\nID 중복 통합: {id_merged}\n닉네임 통합: {name_merged}\n건너뜀: {skipped}\n이미지 상속: {inherited_img}\n이미지 적용: {image_applied}\n이미지 실패: {image_failed}",
        )

    def add_player(self):
        gid = (self.txt_new_id.text() or "").upper().strip()
        name = (self.txt_new_name.text() or "").strip()
        if not gid or not name:
            return
        gids = self._split_player_gids(gid)
        if not gids:
            return
        added_gids: List[str] = []
        for one_gid in gids:
            ok, _, _, _ = self._merge_player_entry(one_gid, name, gid_threshold=100)
            if ok:
                added_gids.append(self._canonical_player_gid(one_gid, threshold=100) or one_gid)
        if not added_gids:
            return
        country_value = _normalize_player_country(self.cmb_new_country.currentData() if hasattr(self, "cmb_new_country") else "KR")
        flag_rel = ""
        if getattr(self, "_new_player_flag_path", ""):
            flag_rel = _store_player_flag(added_gids[0], self._new_player_flag_path)
        if self._new_player_image_path:
            img_path = self._store_new_player_image(added_gids[0], self._new_player_image_path)
            if img_path:
                rel_path = to_app_rel(img_path)
                for one_gid in added_gids:
                    self.cfg.players_images[one_gid] = rel_path
        for one_gid in added_gids:
            self.cfg.players_countries[one_gid] = country_value
            if flag_rel:
                self.cfg.players_flags[one_gid] = to_app_rel(flag_rel)
            else:
                self.cfg.players_flags.setdefault(one_gid, "")
        self.txt_new_id.clear()
        self.txt_new_name.clear()
        if hasattr(self, "cmb_new_country"):
            self.cmb_new_country.setCurrentIndex(0)
        self._clear_new_player_image()
        self._clear_new_player_flag()
        self._reload_players_cards()

    def delete_player_by_id(self, gid: str):
        if not gid:
            return
        resp = QMessageBox.question(
            self,
            "선수 삭제",
            f"{gid} 선수를 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        if gid in self.cfg.players:
            del self.cfg.players[gid]
        if gid in self.cfg.players_images:
            del self.cfg.players_images[gid]
        if gid in self.cfg.players_countries:
            del self.cfg.players_countries[gid]
        if gid in self.cfg.players_flags:
            del self.cfg.players_flags[gid]
        self._sanitize_saved_player_state()
        self._reload_players_cards()

    def _set_new_player_image_preview(self, path: str):
        self._new_player_image_path = str(path or "")
        preview_path = resolve_player_image_path(self._new_player_image_path)
        if preview_path and os.path.exists(preview_path):
            pix = QPixmap(preview_path)
            if not pix.isNull():
                self.lbl_new_avatar.setPixmap(pix.scaled(
                    self.lbl_new_avatar.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                ))
                self.lbl_new_avatar_path.setText(os.path.basename(preview_path))
                return
        self.lbl_new_avatar.setPixmap(QPixmap())
        self.lbl_new_avatar.setText("사진")
        self.lbl_new_avatar_path.setText("")

    def _pick_new_player_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "선수 초상화 선택", "", "이미지 파일 (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        self._set_new_player_image_preview(path)

    def _paste_new_player_image(self):
        path = _paste_clipboard_image("NEW")
        if not path:
            QMessageBox.information(self, "붙여넣기", "클립보드에 초상화가 없습니다.")
            return
        self._set_new_player_image_preview(path)

    def _url_new_player_image(self):
        gids = self._split_player_gids(self.txt_new_id.text() or "")
        gid = gids[0] if gids else "NEW"
        url = _ask_image_url(self)
        if not url:
            return
        path = _download_image_url(url, gid)
        if not path:
            QMessageBox.information(self, "URL", "이미지 URL을 불러오지 못했습니다.")
            return
        self._set_new_player_image_preview(path)

    def _clear_new_player_image(self):
        self._new_player_image_path = ""
        if hasattr(self, "lbl_new_avatar"):
            self.lbl_new_avatar.setPixmap(QPixmap())
            self.lbl_new_avatar.setText("사진")
        if hasattr(self, "lbl_new_avatar_path"):
            self.lbl_new_avatar_path.setText("")

    def _pick_new_player_flag(self):
        path, _ = QFileDialog.getOpenFileName(self, "선수 국기 이미지 선택", "", "이미지 파일 (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        self._new_player_flag_path = path
        if hasattr(self, "lbl_new_flag_path"):
            self.lbl_new_flag_path.setText(os.path.basename(path))

    def _clear_new_player_flag(self):
        self._new_player_flag_path = ""
        if hasattr(self, "lbl_new_flag_path"):
            self.lbl_new_flag_path.setText("")

    def _store_new_player_image(self, gid: str, src_path: str) -> str:
        if not gid or not src_path or not os.path.exists(src_path):
            return ""
        base_dir = app_path("image", "players")
        os.makedirs(base_dir, exist_ok=True)
        _, ext = os.path.splitext(src_path)
        ext = ext if ext else ".png"
        dst = os.path.join(base_dir, f"{gid}_{uuid.uuid4().hex[:8]}{ext}")
        try:
            shutil.copy2(src_path, dst)
            return to_app_rel(dst)
        except Exception:
            return to_app_rel(src_path)

    def open_profile_dialog(self, gid: str):
        if not gid:
            return
        name = self.cfg.players.get(gid, "")
        img_path = _player_image_path_for_gid(self.cfg, gid)
        country = (self.cfg.players_countries or {}).get(gid, "KR")
        flag_path = (self.cfg.players_flags or {}).get(gid, "")
        dlg = ProfileEditDialog(
            self,
            gid,
            name,
            img_path,
            country,
            flag_path,
            self._edit_player_profile,
            self.open_player_image_dialog,
            self._paste_player_image,
            self.open_player_flag_dialog,
        )
        dlg.exec()

    def _edit_player_profile(self, old_gid: str, new_gid: str, new_name: str, country: str = "KR", flag_path: str = "") -> Tuple[bool, str, str]:
        if not old_gid:
            return False, old_gid, new_name
        new_gids = self._split_player_gids(new_gid)
        if not new_gids or not new_name:
            QMessageBox.information(self, "입력 오류", "아이디와 닉네임을 모두 입력하세요.")
            return False, old_gid, new_name
        for one_gid in new_gids:
            if one_gid != old_gid and one_gid in self.cfg.players:
                QMessageBox.warning(self, "중복", f"이미 존재하는 GAME_ID입니다: {one_gid}")
                return False, old_gid, new_name
        img_path = self.cfg.players_images.get(old_gid, "")
        country_value = _normalize_player_country(country or (self.cfg.players_countries or {}).get(old_gid, "KR"))
        flag_value = str(flag_path if flag_path is not None else (self.cfg.players_flags or {}).get(old_gid, "") or "").strip()
        if old_gid not in new_gids and old_gid in self.cfg.players:
            del self.cfg.players[old_gid]
        if old_gid not in new_gids and old_gid in self.cfg.players_images:
            del self.cfg.players_images[old_gid]
        if old_gid not in new_gids and old_gid in self.cfg.players_countries:
            del self.cfg.players_countries[old_gid]
        if old_gid not in new_gids and old_gid in self.cfg.players_flags:
            del self.cfg.players_flags[old_gid]
        for one_gid in new_gids:
            self.cfg.players[one_gid] = new_name
            self.cfg.players_images[one_gid] = to_app_rel(img_path)
            self.cfg.players_countries[one_gid] = country_value
            self.cfg.players_flags[one_gid] = to_app_rel(flag_value)
        primary_gid = new_gids[0]
        if str(getattr(self.cfg, "current_blue_id", "") or "").upper().strip() == old_gid:
            self.cfg.current_blue_id = primary_gid
        if str(getattr(self.cfg, "current_red_id", "") or "").upper().strip() == old_gid:
            self.cfg.current_red_id = primary_gid
        self._sanitize_saved_player_state()
        self._reload_players_cards()
        return True, primary_gid, new_name

    def open_player_flag_dialog(self, gid: str) -> str:
        if not gid:
            return ""
        path, _ = QFileDialog.getOpenFileName(
            self, "선수 국기 이미지 선택", "", "이미지 파일 (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return ""
        self.cfg.players_flags[gid] = _store_player_flag(gid, path)
        self._reload_players_cards()
        return self.cfg.players_flags.get(gid, "")

    def _paste_player_image(self, gid: str) -> str:
        if not gid:
            return ""
        path = _paste_clipboard_image(gid)
        if not path:
            return ""
        self.cfg.players_images[gid] = to_app_rel(path)
        self._reload_players_cards()
        return self.cfg.players_images.get(gid, "")

    def open_player_image_dialog(self, gid: str) -> str:
        if not gid:
            return ""
        box = QMessageBox(self)
        box.setWindowTitle("초상화 선택")
        box.setText("초상화 설정 방법을 선택하세요.")
        btn_file = box.addButton("파일 선택", QMessageBox.ButtonRole.ActionRole)
        btn_paste = box.addButton("붙여넣기", QMessageBox.ButtonRole.ActionRole)
        btn_url = box.addButton("URL 붙여넣기", QMessageBox.ButtonRole.ActionRole)
        box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == btn_file:
            path, _ = QFileDialog.getOpenFileName(
                self, "선수 초상화 선택", "", "이미지 파일 (*.png *.jpg *.jpeg *.bmp)"
            )
            if not path:
                return ""
            self.cfg.players_images[gid] = to_app_rel(path)
            self._reload_players_cards()
            return self.cfg.players_images.get(gid, "")
        if clicked == btn_paste:
            path = _paste_clipboard_image(gid)
            if not path:
                QMessageBox.information(self, "붙여넣기", "클립보드에 초상화가 없습니다.")
                return ""
            self.cfg.players_images[gid] = to_app_rel(path)
            self._reload_players_cards()
            return self.cfg.players_images.get(gid, "")
        if clicked == btn_url:
            url = _ask_image_url(self)
            if not url:
                return ""
            path = _download_image_url(url, gid)
            if not path:
                QMessageBox.information(self, "URL", "이미지 URL을 불러오지 못했습니다.")
                return ""
            self.cfg.players_images[gid] = to_app_rel(path)
            self._reload_players_cards()
            return self.cfg.players_images.get(gid, "")
        return ""

    def _update_trigger_live(self):
        if not self.chk_live_trigger.isChecked():
            return
        d = self.watcher.get_debug()
        b, g, r = d.get("bgr", (0, 0, 0))
        dist = float(d.get("dist", 0.0))
        is_hit = bool(d.get("is_hit", False))
        hits = int(d.get("hits_in_window", 0))
        wlen = int(d.get("window_len", 0))
        cd = float(d.get("cooldown_left", 0.0))
        tgt = self.cfg.trigger.target_bgr

        self.lbl_trg_live.setText(
            f"TRIGGER hit={is_hit}  dist={dist:.1f}  nowBGR=({b},{g},{r})  "
            f"targetBGR=({tgt[0]},{tgt[1]},{tgt[2]})  window={hits}/{wlen}  cooldown={cd:.1f}s"
        )

    def _refresh_trigger_color_ui(self):
        b, g, r = self.cfg.trigger.target_bgr
        self.lbl_trigger_color_preview.setStyleSheet(
            f"border:1px solid #333; background: rgb({r},{g},{b});"
        )
        self.lbl_trigger_color_text.setText(f"BGR=({b},{g},{r})")

        if self.sp_b.value() != b:
            self.sp_b.blockSignals(True); self.sp_b.setValue(b); self.sp_b.blockSignals(False)
        if self.sp_g.value() != g:
            self.sp_g.blockSignals(True); self.sp_g.setValue(g); self.sp_g.blockSignals(False)
        if self.sp_r.value() != r:
            self.sp_r.blockSignals(True); self.sp_r.setValue(r); self.sp_r.blockSignals(False)

    def on_bgr_spin_changed(self):
        b = int(self.sp_b.value())
        g = int(self.sp_g.value())
        r = int(self.sp_r.value())
        self.cfg.trigger.target_bgr = (b, g, r)
        self._refresh_trigger_color_ui()

    def pick_trigger_color_dialog(self):
        b, g, r = self.cfg.trigger.target_bgr
        init = QColor(r, g, b)
        col = QColorDialog.getColor(init, self, "트리거 색 선택")
        if not col.isValid():
            return
        self.cfg.trigger.target_bgr = (col.blue(), col.green(), col.red())
        self._refresh_trigger_color_ui()

    # ---- Pixel rules tab ----
    def _build_pixels(self):
        self.pixels_panel = QWidget()
        lay = QVBoxLayout(self.pixels_panel)

        head = QHBoxLayout()
        lbl_head = QLabel("화면 감지")
        lbl_head.setStyleSheet("color:#f8fafc; font-weight:700;")
        head.addWidget(lbl_head)
        self.lbl_pixel_state = QLabel("중지")
        self.lbl_pixel_state.setStyleSheet("color:#cbd5e1;")
        head.addWidget(self.lbl_pixel_state)
        self.chk_pixel_live = QCheckBox("상태 표시")
        self.chk_pixel_live.setChecked(True)
        head.addWidget(self.chk_pixel_live)
        head.addStretch(1)
        btn_add = QPushButton("조건 추가")
        btn_add.clicked.connect(self._add_pixel_rule)
        head.addWidget(btn_add)
        lay.addLayout(head)

        self.px_cards_wrap = QWidget()
        self.px_cards_layout = QGridLayout(self.px_cards_wrap)
        self.px_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.px_cards_layout.setHorizontalSpacing(12)
        self.px_cards_layout.setVerticalSpacing(12)
        self.px_cards_scroll = QScrollArea()
        self.px_cards_scroll.setWidgetResizable(True)
        self.px_cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.px_cards_scroll.setWidget(self.px_cards_wrap)
        self.px_cards_scroll.setMinimumHeight(420)
        lay.addWidget(self.px_cards_scroll)


        self._pixel_rules = list(self.cfg.pixel_rules or [])
        for rule in self._pixel_rules:
            if not rule.get("id"):
                rule["id"] = f"pixel_{uuid.uuid4().hex}"
        self._pixel_live_labels = {}
        self._pixel_live_rules = {}
        self._render_pixel_cards()
        self._pixel_live_timer = QTimer(self)
        self._pixel_live_timer.timeout.connect(self._update_pixel_live)
        self._pixel_live_timer.start(200)


    def _render_pixel_cards(self):
        if not hasattr(self, "_action_summary_labels"):
            self._action_summary_labels = {}
        else:
            for key in list(self._action_summary_labels.keys()):
                if key.startswith("pixel:") or key.startswith("pixel_id:"):
                    self._action_summary_labels.pop(key, None)
        if not hasattr(self, "_pixel_live_labels"):
            self._pixel_live_labels = {}
        else:
            self._pixel_live_labels = {}
        if not hasattr(self, "_pixel_live_rules"):
            self._pixel_live_rules = {}
        else:
            self._pixel_live_rules = {}
        self._clear_layout(self.px_cards_layout)
        cols = 2
        for idx, rule in enumerate(self._pixel_rules):
            card = QGroupBox(f"화면 감지 {idx + 1}")
            card_lay = QVBoxLayout(card)
            card.setMinimumWidth(300)
            card.setMaximumWidth(16777215)

            row = QHBoxLayout()
            txt_name = QLineEdit(str(rule.get("name", f"rule{idx+1}")))
            chk_enabled = QCheckBox("사용")
            chk_enabled.setChecked(bool(rule.get("enabled", True)))
            row.addWidget(QLabel("이름:"))
            row.addWidget(txt_name, 1)
            row.addWidget(chk_enabled)
            card_lay.addLayout(row)

            lbl_summary = QLabel(self._screen_rule_summary(rule))
            lbl_summary.setStyleSheet("color:#666;")
            card_lay.addWidget(lbl_summary)

            ev_key = f"pixel:{rule.get('name', f'rule{idx+1}')}"
            lbl_action = QLabel(f"액션: {self._event_action_summary(ev_key)}")
            lbl_action.setStyleSheet("color:#666;")
            card_lay.addWidget(lbl_action)
            self._action_summary_labels[ev_key] = lbl_action

            state_key = str(rule.get("id") or rule.get("name") or f"rule{idx+1}")
            lbl_live = QLabel("상태: -")
            lbl_live.setStyleSheet("color:#8aa; font-family: Consolas;")
            card_lay.addWidget(lbl_live)
            if hasattr(self, "_pixel_live_labels"):
                self._pixel_live_labels[state_key] = lbl_live
            if hasattr(self, "_pixel_live_rules"):
                self._pixel_live_rules[state_key] = rule

            row = QHBoxLayout()
            sp_tol = QSpinBox(); sp_tol.setRange(0, 200); sp_tol.setValue(int(rule.get("tolerance", 5)))
            sp_cd = QSpinBox(); sp_cd.setRange(0, 30); sp_cd.setValue(int(rule.get("cooldown_sec", 1)))
            sp_tol.setFixedWidth(70)
            sp_cd.setFixedWidth(70)
            self._apply_wheel_filter(sp_tol)
            self._apply_wheel_filter(sp_cd)
            row.addWidget(QLabel("허용오차:")); row.addWidget(sp_tol)
            sp_cd.setVisible(False)
            card_lay.addLayout(row)

            save_fn = partial(self._save_pixel_rule_from_widgets, idx, txt_name, chk_enabled, sp_tol, sp_cd, lbl_summary)
            txt_name.editingFinished.connect(save_fn)
            chk_enabled.stateChanged.connect(lambda _v, fn=save_fn: fn())
            sp_tol.editingFinished.connect(save_fn)
            sp_cd.editingFinished.connect(save_fn)

            row_top = QHBoxLayout()
            btn_cond = QPushButton("조건 설정")
            btn_action = QPushButton("액션 설정")
            btn_cond.clicked.connect(partial(self._on_pixel_rule_condition_clicked, idx, lbl_summary))
            btn_action.clicked.connect(partial(self._show_actions_for_event, f"pixel:{rule.get('name', f'rule{idx+1}')}"))
            row_top.addWidget(btn_cond)
            row_top.addWidget(btn_action)
            row_top.addStretch(1)
            card_lay.addLayout(row_top)

            row_bottom = QHBoxLayout()
            btn_copy = QPushButton("복제")
            btn_del = QPushButton("삭제")
            btn_up = QPushButton("위로")
            btn_down = QPushButton("아래로")
            btn_copy.clicked.connect(partial(self._duplicate_pixel_rule, idx))
            btn_del.clicked.connect(partial(self._delete_pixel_rule, idx))
            btn_up.clicked.connect(partial(self._move_pixel_rule, idx, -1))
            btn_down.clicked.connect(partial(self._move_pixel_rule, idx, 1))
            row_bottom.addWidget(btn_copy)
            row_bottom.addWidget(btn_del)
            row_bottom.addStretch(1)
            row_bottom.addWidget(btn_up)
            row_bottom.addWidget(btn_down)
            card_lay.addLayout(row_bottom)

            r = idx // cols
            c = idx % cols
            self.px_cards_layout.addWidget(card, r, c)
        self._update_pixel_live()

    def _update_pixel_live(self):
        if not hasattr(self, "_pixel_live_labels") or not self._pixel_live_labels:
            return
        if not hasattr(self, "chk_pixel_live") or not self.chk_pixel_live.isChecked():
            for key, lbl in list(self._pixel_live_labels.items()):
                lbl.setText("상태: OFF")
            return
        running = bool(self.watcher and self.watcher.is_running())
        for key, lbl in list(self._pixel_live_labels.items()):
            try:
                rule = self._pixel_live_rules.get(key, {}) if hasattr(self, "_pixel_live_rules") else {}
            except Exception:
                rule = {}
            if not rule or not bool(rule.get("enabled", True)):
                lbl.setText("상태: OFF")
                continue
            state = {}
            if running:
                try:
                    state = self.watcher.get_pixel_state(key) if self.watcher else {}
                except Exception:
                    state = {}
            if not state:
                try:
                    mode = str(rule.get("mode", "pixel"))
                    if mode == "roi":
                        rr = rule.get("roi", {}) or {}
                        rect = Rect(
                            x=int(rr.get("x", 0)),
                            y=int(rr.get("y", 0)),
                            w=int(rr.get("w", 0)),
                            h=int(rr.get("h", 0)),
                        )
                        if not rect.valid():
                            lbl.setText("상태: ROI 없음")
                            continue
                        roi = capture_roi_np_global(rect)
                        if roi.size == 0:
                            lbl.setText("상태: 캡처 실패")
                            continue
                        mean = roi.reshape(-1, 3).mean(axis=0)
                        b, g, r = int(mean[0]), int(mean[1]), int(mean[2])
                    else:
                        x = int(rule.get("x", 0))
                        y = int(rule.get("y", 0))
                        sample = int(rule.get("sample", 1))
                        b, g, r = capture_pixel_bgr(int(x), int(y), sample)
                    tgt = rule.get("target_bgr", [0, 0, 0])
                    tolerance = int(rule.get("tolerance", 5))
                    dist = bgr_distance((b, g, r), (int(tgt[0]), int(tgt[1]), int(tgt[2])))
                    hit = dist <= float(tolerance)
                    lbl.setText(f"상태: {'HIT' if hit else 'NO'} dist={dist:.1f}")
                except Exception as e:
                    lbl.setText(f"상태: 오류 {e}")
                continue
            dist = float(state.get("last_dist", 0.0))
            hit = bool(state.get("last_hit", False))
            wlen = int(state.get("window_len", 0))
            whits = int(state.get("window_hits", 0))
            cd = float(state.get("cooldown_left", 0.0))
            lbl.setText(f"상태: {'HIT' if hit else 'NO'} dist={dist:.1f} win={whits}/{wlen} cd={cd:.1f}s")

    def _add_pixel_rule(self):
        self._pixel_rules.append({
            "id": f"pixel_{uuid.uuid4().hex}",
            "name": f"rule{len(self._pixel_rules)+1}",
            "enabled": True,
            "mode": "pixel",
            "x": 0,
            "y": 0,
            "sample": 1,
            "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
            "target_bgr": [0, 0, 0],
            "tolerance": 5,
            "window_frames": 1,
            "consecutive_needed": 1,
            "cooldown_sec": 1.0
        })
        self._apply_pixel_rules()
        self._render_pixel_cards()
        self._refresh_action_events()

    def _pixel_start(self):
        self.apply_only(silent=True)
        if callable(getattr(self, "_screen_detection_start", None)):
            self._screen_detection_start()
        elif callable(getattr(self, "_detection_start", None)):
            self._detection_start()
        elif self.watcher:
            self.watcher.set_detection_modes(trigger=True, pixel=True)
            self.watcher.start()
        if hasattr(self, "lbl_pixel_state"):
            self.lbl_pixel_state.setText("실행 중")
        self._update_detect_button()

    def _pixel_stop(self):
        if callable(getattr(self, "_screen_detection_stop", None)):
            self._screen_detection_stop()
        elif callable(getattr(self, "_detection_stop", None)):
            self._detection_stop()
        elif self.watcher:
            self.watcher.stop()
        if hasattr(self, "lbl_pixel_state"):
            self.lbl_pixel_state.setText("중지")
        self._update_detect_button()

    def _screen_start(self):
        self._pixel_start()

    def _screen_stop(self):
        self._pixel_stop()

    def _log_start(self):
        self.apply_only(silent=True)
        if callable(getattr(self, "_log_detection_start", None)):
            self._log_detection_start()
        elif callable(getattr(self, "_detection_start", None)):
            self._detection_start()
        self._update_detect_button()

    def _log_stop(self):
        if callable(getattr(self, "_log_detection_stop", None)):
            self._log_detection_stop()
        elif callable(getattr(self, "_detection_stop", None)):
            self._detection_stop()
        self._update_detect_button()

    def _delete_pixel_rule(self, idx: int):
        if idx < 0 or idx >= len(self._pixel_rules):
            return
        rule = self._pixel_rules[idx]
        name = str(rule.get("name") or "").strip()
        pid = str(rule.get("id") or "").strip()
        if hasattr(self, "_actions_by_event"):
            if name:
                self._actions_by_event.pop(f"pixel:{name}", None)
            if pid:
                self._actions_by_event.pop(f"pixel_id:{pid}", None)
            self.cfg.actions = dict(self._actions_by_event)
        if hasattr(self, "_action_cooldowns_by_event"):
            if name:
                self._action_cooldowns_by_event.pop(f"pixel:{name}", None)
            if pid:
                self._action_cooldowns_by_event.pop(f"pixel_id:{pid}", None)
            self.cfg.action_cooldowns = dict(self._action_cooldowns_by_event)
        del self._pixel_rules[idx]
        self._apply_pixel_rules()
        self._render_pixel_cards()
        self._refresh_action_events()
        if hasattr(self, "cmb_action_event"):
            self._load_actions_for_event(self.cmb_action_event.currentText())

    def _duplicate_pixel_rule(self, idx: int):
        if idx < 0 or idx >= len(self._pixel_rules):
            return
        src = dict(self._pixel_rules[idx])
        src["id"] = f"pixel_{uuid.uuid4().hex}"
        base_name = str(src.get("name") or f"rule{idx+1}")
        new_name = f"{base_name}_copy"
        existing = {str(r.get("name") or "") for r in self._pixel_rules}
        if new_name in existing:
            n = 2
            while f"{base_name}({n})" in existing:
                n += 1
            new_name = f"{base_name}({n})"
        src["name"] = new_name
        # Do not copy actions/cooldowns; only duplicate condition.
        self._pixel_rules.insert(idx + 1, src)
        self._apply_pixel_rules()
        self._render_pixel_cards()
        self._refresh_action_events()

    def _move_pixel_rule(self, idx: int, delta: int):
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(self._pixel_rules):
            return
        self._pixel_rules[idx], self._pixel_rules[new_idx] = self._pixel_rules[new_idx], self._pixel_rules[idx]
        self._apply_pixel_rules()
        self._render_pixel_cards()

    def _save_pixel_rule_from_widgets(self, idx: int, txt_name: QLineEdit, chk_enabled: QCheckBox,
                                      sp_tol: QSpinBox, sp_cd: QSpinBox, lbl_summary: QLabel):
        if idx < 0 or idx >= len(self._pixel_rules):
            return
        rule = self._pixel_rules[idx]
        old_name = str(rule.get("name") or f"rule{idx+1}")
        pid = str(rule.get("id") or "")
        new_name = txt_name.text().strip() or f"rule{idx+1}"
        rule["name"] = new_name
        rule["enabled"] = bool(chk_enabled.isChecked())
        rule["tolerance"] = int(sp_tol.value())
        rule["cooldown_sec"] = float(sp_cd.value())
        if old_name != new_name:
            old_ev = f"pixel:{old_name}"
            new_ev = f"pixel:{new_name}"
            if old_ev in self._actions_by_event:
                actions = list(self._actions_by_event.pop(old_ev))
            elif pid and f"pixel_id:{pid}" in self._actions_by_event:
                actions = list(self._actions_by_event.get(f"pixel_id:{pid}", []))
            else:
                actions = self._get_actions_for_event(old_ev)
            self._set_actions_for_event(new_ev, actions, update_panel=False)
            if hasattr(self, "_action_cooldowns_by_event"):
                old_cd = None
                if old_ev in self._action_cooldowns_by_event:
                    old_cd = self._action_cooldowns_by_event.pop(old_ev, None)
                elif pid and f"pixel_id:{pid}" in self._action_cooldowns_by_event:
                    old_cd = self._action_cooldowns_by_event.pop(f"pixel_id:{pid}", None)
                if pid:
                    self._action_cooldowns_by_event.pop(f"pixel_id:{pid}", None)
                if old_cd is not None:
                    self._update_action_cooldown_for_event(new_ev, float(old_cd))
        else:
            ev = f"pixel:{new_name}"
            actions = self._get_actions_for_event(ev)
            self._set_actions_for_event(ev, actions, update_panel=False)
        self._apply_pixel_rules()
        lbl_summary.setText(self._screen_rule_summary(rule))
        self._render_pixel_cards()
        self._refresh_action_events()
        self._set_actions_event(f"pixel:{new_name}")

    def _pick_px_pos_into(self, sp_x: QSpinBox, sp_y: QSpinBox):
        pos = QCursor.pos()
        sp_x.setValue(pos.x())
        sp_y.setValue(pos.y())

    def _pick_px_color_into(self, lbl_color: QLabel, cmb_sample: QComboBox):
        pos = QCursor.pos()
        sample = int(cmb_sample.currentText())
        b, g, r = capture_pixel_bgr(pos.x(), pos.y(), sample)
        self._set_color_preview(lbl_color, b, g, r)

    def _set_color_preview(self, lbl: QLabel, b: int, g: int, r: int):
        lbl.setProperty("bgr", (b, g, r))
        lbl.setStyleSheet(f"border:1px solid #333; background: rgb({r},{g},{b});")

    def _get_color_preview(self, lbl: QLabel) -> tuple[int, int, int]:
        v = lbl.property("bgr")
        if isinstance(v, tuple) and len(v) == 3:
            return v
        return (0, 0, 0)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            else:
                child = item.layout()
                if child is not None:
                    self._clear_layout(child)

    def _list_monitors(self) -> List[tuple[int, str]]:
        items: List[tuple[int, str]] = []
        with mss.mss() as sct:
            mons = sct.monitors
            for i in range(1, len(mons)):
                m = mons[i]
                items.append((i, f"모니터 {i} ({m['width']}x{m['height']})"))
        return items

    def _refresh_monitors(self):
        if not hasattr(self, "cmb_monitor"):
            return
        self.cmb_monitor.clear()
        try:
            for idx, label in self._list_monitors():
                self.cmb_monitor.addItem(label, idx)
        except Exception:
            self.cmb_monitor.addItem("모니터 1", 1)

    def preview_capture(self):
        try:
            mon = int(self.cmb_monitor.currentData() or self.cfg.monitor_index)
        except Exception:
            mon = int(self.cfg.monitor_index)
        try:
            frame = capture_monitor_np(mon)
        except Exception as e:
            QMessageBox.warning(self, "캡처 오류", f"캡처 실패: {e}")
            return
        if frame is None or frame.size == 0:
            QMessageBox.warning(self, "캡처 오류", "캡처된 화면이 없습니다.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("미리보기")
        dlg.resize(900, 600)
        lay = QVBoxLayout(dlg)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qimg = bgr_to_qimage(frame)
        if qimg is not None:
            pix = QPixmap.fromImage(qimg)
            lbl.setPixmap(pix.scaled(dlg.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        lay.addWidget(lbl)
        dlg.exec()

    def _monitor_to_local(self, monitor_index: int, x: int, y: int) -> tuple[int, int]:
        with mss.mss() as sct:
            mons = sct.monitors
            if monitor_index < 1 or monitor_index >= len(mons):
                return x, y
            mon = mons[monitor_index]
            return int(x - mon["left"]), int(y - mon["top"])

    def _screen_rule_summary(self, rule: dict) -> str:
        mode = str(rule.get("mode", "pixel"))
        tgt = rule.get("target_bgr", [0, 0, 0])
        if mode == "roi":
            rr = rule.get("roi", {}) or {}
            return f"모드: ROI | x={rr.get('x',0)}, y={rr.get('y',0)}, w={rr.get('w',0)}, h={rr.get('h',0)}"
        return f"모드: 픽셀 | x={rule.get('x',0)}, y={rule.get('y',0)}, sample={rule.get('sample',1)}"

    def _on_pixel_rule_condition_clicked(self, idx: int, lbl_summary: QLabel):
        self._open_screen_condition_dialog(idx, lbl_summary)

    def _start_quick_pixel_pick_for_rule(self, idx: int, lbl_summary: QLabel):
        if idx < 0 or idx >= len(self._pixel_rules):
            return
        if self._pixel_pick_overlay and self._pixel_pick_overlay.isVisible():
            try:
                self._pixel_pick_overlay.close()
            except Exception:
                pass
            self._pixel_pick_overlay = None
        if self._quick_pick_active:
            return
        self._quick_pick_active = True

        def _on_accept():
            self._finish_quick_pixel_pick_for_rule(idx, lbl_summary)

        overlay = PixelPickOverlay(
            self._sample_pixel_at_global,
            message="조건 설정: 마우스를 움직이고 아무 키를 누르면 적용됩니다. (ESC 취소)",
            accept_on_key=True,
            on_accept=_on_accept,
        )
        try:
            rect = QGuiApplication.primaryScreen().virtualGeometry()
        except Exception:
            rect = QGuiApplication.primaryScreen().geometry()
            for scr in QGuiApplication.screens():
                rect = rect.united(scr.geometry())
        overlay.setGeometry(rect)
        overlay.destroyed.connect(lambda _o=None: setattr(self, "_quick_pick_active", False))
        overlay.destroyed.connect(lambda _o=None: setattr(self, "_pixel_pick_overlay", None))
        overlay.show()
        overlay.raise_()
        self._pixel_pick_overlay = overlay

    def _finish_quick_pixel_pick_for_rule(self, idx: int, lbl_summary: QLabel):
        if not self._pixel_pick_overlay:
            return
        pos, bgr = self._pixel_pick_overlay.current_sample()
        self._quick_pick_active = False
        try:
            self._pixel_pick_overlay.close()
        except Exception:
            pass
        self._pixel_pick_overlay = None
        self._apply_pixel_pick_to_rule(idx, int(pos.x()), int(pos.y()), bgr)
        try:
            if idx < len(self._pixel_rules):
                lbl_summary.setText(self._screen_rule_summary(self._pixel_rules[idx]))
        except Exception:
            pass

    def _open_screen_condition_dialog(self, idx: int, lbl_summary: QLabel):
        if idx < 0 or idx >= len(self._pixel_rules):
            return
        rule = self._pixel_rules[idx]

        try:
            if getattr(self, "_pixel_condition_dlg", None) is not None:
                if self._pixel_condition_dlg.isVisible():
                    self._pixel_condition_dlg.close()
        except Exception:
            pass

        dlg = QDialog(self)
        dlg.setWindowTitle("\ud654\uba74 \uac10\uc9c0 \uc870\uac74 \uc124\uc815")
        dlg.resize(560, 260)
        dlg.setModal(False)
        dlg.setWindowFlag(Qt.WindowType.Tool, True)
        lay = QVBoxLayout(dlg)

        row_btn = QHBoxLayout()
        btn_pixel = QPushButton("픽셀 지정")
        btn_input = QPushButton("값 입력")
        row_btn.addWidget(btn_pixel)
        row_btn.addWidget(btn_input)
        row_btn.addStretch(1)
        lay.addLayout(row_btn)

        sample_row = QHBoxLayout()
        sample_row.addWidget(QLabel("샘플:"))
        cmb_sample = QComboBox()
        cmb_sample.addItems(["1", "3", "5", "7"])
        cmb_sample.setCurrentText(str(rule.get("sample", 1)))
        self._apply_wheel_filter(cmb_sample)
        sample_row.addWidget(cmb_sample)
        sample_row.addStretch(1)
        lay.addLayout(sample_row)

        lbl_color = QLabel(" ")
        lbl_color.setFixedSize(80, 26)
        bgr = rule.get("target_bgr", [0, 0, 0])
        self._set_color_preview(lbl_color, int(bgr[0]), int(bgr[1]), int(bgr[2]))
        lay.addWidget(lbl_color)

        lbl_preview = QLabel(self._screen_rule_summary(rule))
        lbl_preview.setStyleSheet("color:#8892a6;")
        lay.addWidget(lbl_preview)

        def _reactivate_dialog():
            try:
                dlg.show()
                dlg.raise_()
                dlg.activateWindow()
                dlg.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
            except Exception:
                pass
            try:
                QTimer.singleShot(80, lambda: (dlg.raise_(), dlg.activateWindow()))
            except Exception:
                pass

        def _apply_common():
            try:
                rule["sample"] = int(cmb_sample.currentText())
            except Exception:
                pass
            self._apply_pixel_rules()
            self._render_pixel_cards()
            self._refresh_action_events()
            try:
                lbl_summary.setText(self._screen_rule_summary(rule))
            except Exception:
                pass
            try:
                lbl_preview.setText(self._screen_rule_summary(rule))
            except Exception:
                pass

        def _pick_pixel():
            if self._pixel_pick_overlay:
                try:
                    self._pixel_pick_overlay.close()
                except Exception:
                    pass
                self._pixel_pick_overlay = None
            try:
                dlg.hide()
            except Exception:
                pass
            def _accept_pick():
                overlay_ref = self._pixel_pick_overlay
                if not overlay_ref:
                    return
                pos, bgr = overlay_ref.current_sample()
                rule["mode"] = "pixel"
                rule["x"] = int(pos.x())
                rule["y"] = int(pos.y())
                rule["sample"] = int(cmb_sample.currentText())
                rule["roi"] = {"x": 0, "y": 0, "w": 0, "h": 0}
                rule["target_bgr"] = [int(bgr[0]), int(bgr[1]), int(bgr[2])]
                self._set_color_preview(lbl_color, int(bgr[0]), int(bgr[1]), int(bgr[2]))
                try:
                    _apply_common()
                finally:
                    try:
                        try:
                            overlay_ref.close()
                        except Exception:
                            pass
                        self._pixel_pick_overlay = None
                        _reactivate_dialog()
                    except Exception:
                        pass
            overlay = PixelPickOverlay(
                self._sample_pixel_at_global,
                message="픽셀 조건: 마우스를 움직이고 아무 키를 누르면 적용됩니다. (ESC 취소)",
                accept_on_key=True,
                on_accept=_accept_pick,
            )
            try:
                rect = QGuiApplication.primaryScreen().virtualGeometry()
            except Exception:
                rect = QGuiApplication.primaryScreen().geometry()
                for scr in QGuiApplication.screens():
                    rect = rect.united(scr.geometry())
            overlay.setGeometry(rect)
            overlay.destroyed.connect(lambda _o=None: setattr(self, "_pixel_pick_overlay", None))
            overlay.destroyed.connect(lambda _o=None: _reactivate_dialog())
            overlay.show()
            overlay.raise_()
            try:
                QTimer.singleShot(0, lambda: (overlay.activateWindow(), overlay.setFocus()))
            except Exception:
                pass
            self._pixel_pick_overlay = overlay

        def _input_values():
            idlg = QDialog(self)
            idlg.setWindowTitle("값 입력")
            idlg.resize(360, 220)
            v = QVBoxLayout(idlg)

            row_xy = QHBoxLayout()
            sp_x = QSpinBox(); sp_x.setRange(-100000, 100000); sp_x.setValue(int(rule.get("x", 0)))
            sp_y = QSpinBox(); sp_y.setRange(-100000, 100000); sp_y.setValue(int(rule.get("y", 0)))
            sp_x.setFixedWidth(110); sp_y.setFixedWidth(110)
            self._apply_wheel_filter(sp_x)
            self._apply_wheel_filter(sp_y)
            row_xy.addWidget(QLabel("X:"))
            row_xy.addWidget(sp_x)
            row_xy.addSpacing(12)
            row_xy.addWidget(QLabel("Y:"))
            row_xy.addWidget(sp_y)
            row_xy.addStretch(1)
            v.addLayout(row_xy)

            row_rgb = QHBoxLayout()
            sp_r = QSpinBox(); sp_r.setRange(0, 255)
            sp_g = QSpinBox(); sp_g.setRange(0, 255)
            sp_b = QSpinBox(); sp_b.setRange(0, 255)
            bgr = rule.get("target_bgr", [0, 0, 0])
            sp_r.setValue(int(bgr[2]))
            sp_g.setValue(int(bgr[1]))
            sp_b.setValue(int(bgr[0]))
            for sp in (sp_r, sp_g, sp_b):
                sp.setFixedWidth(80)
                self._apply_wheel_filter(sp)
            row_rgb.addWidget(QLabel("R:")); row_rgb.addWidget(sp_r)
            row_rgb.addWidget(QLabel("G:")); row_rgb.addWidget(sp_g)
            row_rgb.addWidget(QLabel("B:")); row_rgb.addWidget(sp_b)
            row_rgb.addStretch(1)
            v.addLayout(row_rgb)

            row_paste = QHBoxLayout()
            btn_paste = QPushButton("값 붙여넣기")
            row_paste.addWidget(btn_paste)
            row_paste.addStretch(1)
            v.addLayout(row_paste)

            def _paste_values():
                cb = QApplication.clipboard()
                text = str(cb.text() if cb is not None else "").strip()
                if not text:
                    QMessageBox.information(idlg, "붙여넣기", "클립보드에 텍스트가 없습니다.")
                    return
                lower = text.lower()
                kv = {}
                for m in re.finditer(r"([xyrgb])\s*[:=]\s*(-?\d+)", lower):
                    kv[str(m.group(1))] = int(m.group(2))

                ints = [int(n) for n in re.findall(r"-?\d+", text)]
                has_any = False

                if "x" in kv:
                    sp_x.setValue(int(kv["x"]))
                    has_any = True
                elif len(ints) >= 1:
                    sp_x.setValue(int(ints[0]))
                    has_any = True

                if "y" in kv:
                    sp_y.setValue(int(kv["y"]))
                    has_any = True
                elif len(ints) >= 2:
                    sp_y.setValue(int(ints[1]))
                    has_any = True

                if "r" in kv:
                    sp_r.setValue(int(max(0, min(255, kv["r"]))))
                    has_any = True
                if "g" in kv:
                    sp_g.setValue(int(max(0, min(255, kv["g"]))))
                    has_any = True
                if "b" in kv:
                    sp_b.setValue(int(max(0, min(255, kv["b"]))))
                    has_any = True

                # Fallback for plain numeric sequence: x, y, b, g, r
                if not (("r" in kv) or ("g" in kv) or ("b" in kv)) and len(ints) >= 5:
                    sp_b.setValue(int(max(0, min(255, ints[2]))))
                    sp_g.setValue(int(max(0, min(255, ints[3]))))
                    sp_r.setValue(int(max(0, min(255, ints[4]))))
                    has_any = True

                if not has_any:
                    QMessageBox.information(
                        idlg,
                        "붙여넣기",
                        "인식 가능한 형식이 아닙니다.\n예: x=100, y=200, B=10, G=20, R=30",
                    )
            btn_paste.clicked.connect(_paste_values)

            btns = QHBoxLayout()
            btns.addStretch(1)
            btn_ok = QPushButton("적용")
            btn_cancel = QPushButton("\uCDE8\uC18C")
            btn_ok.clicked.connect(idlg.accept)
            btn_cancel.clicked.connect(idlg.reject)
            btns.addWidget(btn_ok)
            btns.addWidget(btn_cancel)
            v.addLayout(btns)

            if idlg.exec() != QDialog.DialogCode.Accepted:
                return
            rule["mode"] = "pixel"
            rule["x"] = int(sp_x.value())
            rule["y"] = int(sp_y.value())
            rule["sample"] = int(cmb_sample.currentText())
            rule["roi"] = {"x": 0, "y": 0, "w": 0, "h": 0}
            rule["target_bgr"] = [int(sp_b.value()), int(sp_g.value()), int(sp_r.value())]
            self._set_color_preview(lbl_color, int(sp_b.value()), int(sp_g.value()), int(sp_r.value()))
            _apply_common()

        btn_pixel.clicked.connect(_pick_pixel)
        btn_input.clicked.connect(_input_values)

        try:
            hk_pixel = QKeySequence(self.cfg.pixel_hotkey or "")
            if not hk_pixel.isEmpty():
                QShortcut(hk_pixel, dlg).activated.connect(_pick_pixel)
            hk_roi = QKeySequence(self.cfg.roi_hotkey or "")
            if not hk_roi.isEmpty():
                QShortcut(hk_roi, dlg).activated.connect(_pick_pixel)
        except Exception:
            pass

        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(dlg.close)
        btns.addWidget(btn_close)
        lay.addLayout(btns)

        self._pixel_condition_dlg = dlg
        dlg.destroyed.connect(lambda _o=None: setattr(self, "_pixel_condition_dlg", None))
        dlg.show()
        try:
            dlg.raise_()
            dlg.activateWindow()
            dlg.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        except Exception:
            pass
        try:
            QTimer.singleShot(0, dlg.activateWindow)
        except Exception:
            pass

    # Sound detection UI removed.
    def _pixel_id_for_name(self, name: str) -> Optional[str]:
        rules = self._pixel_rules if hasattr(self, "_pixel_rules") else (self.cfg.pixel_rules or [])
        for rule in rules:
            if str(rule.get("name", "")) == str(name):
                rid = str(rule.get("id") or "")
                return rid or None
        return None

    def _pixel_name_for_id(self, pid: str) -> Optional[str]:
        rules = self._pixel_rules if hasattr(self, "_pixel_rules") else (self.cfg.pixel_rules or [])
        for rule in rules:
            if str(rule.get("id", "")) == str(pid):
                name = str(rule.get("name") or "")
                return name or None
        return None

    def _pixel_rule_for_event(self, event: str) -> Optional[dict]:
        if not event:
            return None
        rules = self._pixel_rules if hasattr(self, "_pixel_rules") else (self.cfg.pixel_rules or [])
        if event.startswith("pixel:"):
            name = event.split(":", 1)[1]
            for rule in rules:
                if str(rule.get("name", "")) == str(name):
                    return rule
        if event.startswith("pixel_id:"):
            pid = event.split(":", 1)[1]
            for rule in rules:
                if str(rule.get("id", "")) == str(pid):
                    return rule
        return None

    def _pixel_event_default_pos(self, event: str) -> Optional[Tuple[int, int]]:
        rule = self._pixel_rule_for_event(event)
        if not rule:
            return None
        try:
            gx = int(rule.get("x", 0))
            gy = int(rule.get("y", 0))
            return int(gx), int(gy)
        except Exception:
            return None

    def _event_targets(self, event: str) -> List[str]:
        targets = {event}
        if event.startswith("pixel:"):
            name = event.split(":", 1)[1]
            pid = self._pixel_id_for_name(name)
            if pid:
                targets.add(f"pixel_id:{pid}")
        elif event.startswith("pixel_id:"):
            pid = event.split(":", 1)[1]
            name = self._pixel_name_for_id(pid)
            if name:
                targets.add(f"pixel:{name}")
        return list(targets)

    def _set_actions_for_event(self, event: str, actions: List[dict], update_panel: bool = True) -> None:
        if not event:
            return
        if not hasattr(self, "_actions_by_event"):
            self._actions_by_event = dict(self.cfg.actions or {})
        targets = self._event_targets(event)
        for key in targets:
            self._actions_by_event[key] = list(actions)
        self.cfg.actions = dict(self._actions_by_event)
        if hasattr(self, "_update_action_summary_label"):
            self._update_action_summary_label(event)
        if update_panel and hasattr(self, "cmb_action_event"):
            current = getattr(self, "_current_actions_event", "") or self.cmb_action_event.currentText()
            if current in targets:
                self._actions_list = list(actions)
                self._reload_actions_list()
                if self._actions_list:
                    self.lst_actions.setCurrentRow(0)
                else:
                    self.lst_actions.setCurrentRow(-1)

    def _normalize_action_aliases(self) -> None:
        if not hasattr(self, "_actions_by_event"):
            self._actions_by_event = dict(self.cfg.actions or {})
        pixel_rules = self._pixel_rules if hasattr(self, "_pixel_rules") else (self.cfg.pixel_rules or [])
        for rule in pixel_rules:
            name = str(rule.get("name") or "").strip()
            pid = str(rule.get("id") or "").strip()
            if not name or not pid:
                continue
            key_name = f"pixel:{name}"
            key_id = f"pixel_id:{pid}"
            if key_name in self._actions_by_event:
                src = self._actions_by_event[key_name]
            elif key_id in self._actions_by_event:
                src = self._actions_by_event[key_id]
            else:
                continue
            self._actions_by_event[key_name] = list(src)
            self._actions_by_event[key_id] = list(src)
        self.cfg.actions = dict(self._actions_by_event)

    def _normalize_action_cooldown_aliases(self) -> None:
        if not hasattr(self, "_action_cooldowns_by_event"):
            self._action_cooldowns_by_event = dict(self.cfg.action_cooldowns or {})
        pixel_rules = self._pixel_rules if hasattr(self, "_pixel_rules") else (self.cfg.pixel_rules or [])
        for rule in pixel_rules:
            name = str(rule.get("name") or "").strip()
            pid = str(rule.get("id") or "").strip()
            if not name or not pid:
                continue
            key_name = f"pixel:{name}"
            key_id = f"pixel_id:{pid}"
            if key_name in self._action_cooldowns_by_event:
                src = self._action_cooldowns_by_event[key_name]
            elif key_id in self._action_cooldowns_by_event:
                src = self._action_cooldowns_by_event[key_id]
            else:
                continue
            self._action_cooldowns_by_event[key_name] = float(src)
            self._action_cooldowns_by_event[key_id] = float(src)
        self.cfg.action_cooldowns = dict(self._action_cooldowns_by_event)

    def _ensure_event_actions(self, event: str) -> None:
        if not event or event in self._actions_by_event:
            return
        if event.startswith("pixel:"):
            name = event.split(":", 1)[1]
            pid = self._pixel_id_for_name(name)
            if pid:
                alt = f"pixel_id:{pid}"
                if alt in self._actions_by_event:
                    self._actions_by_event[event] = list(self._actions_by_event[alt])

    def _get_actions_for_event(self, event: str) -> List[dict]:
        if not event:
            return []
        direct = self._actions_by_event.get(event)
        if direct is not None:
            return list(direct)
        if event.startswith("pixel:"):
            name = event.split(":", 1)[1]
            pid = self._pixel_id_for_name(name)
            if pid:
                alt = self._actions_by_event.get(f"pixel_id:{pid}")
                if alt is not None:
                    return list(alt)
        return []

    def _event_action_summary(self, event: str) -> str:
        actions = self._get_actions_for_event(event)
        if not actions:
            return "없음"
        if len(actions) == 1:
            return self._action_summary(actions[0])
        parts = [self._action_summary(a) for a in actions[:2]]
        suffix = " ..." if len(actions) > 2 else ""
        return f"{len(actions)}개: " + ", ".join(parts) + suffix

    def _update_action_summary_label(self, event: str) -> None:
        labels = getattr(self, "_action_summary_labels", None)
        if not labels:
            return
        targets = {event}
        if event.startswith("pixel:"):
            name = event.split(":", 1)[1]
            pid = self._pixel_id_for_name(name)
            if pid:
                targets.add(f"pixel_id:{pid}")
        elif event.startswith("pixel_id:"):
            pid = event.split(":", 1)[1]
            name = self._pixel_name_for_id(pid)
            if name:
                targets.add(f"pixel:{name}")
        for key in targets:
            lbl = labels.get(key)
            if lbl:
                lbl.setText(f"액션: {self._event_action_summary(key)}")

    # Sound detection UI removed.
    def _build_automation(self):
        outer = QVBoxLayout()
        body = QVBoxLayout()
        body.setContentsMargins(8, 8, 8, 8)

        grp_pixels = QGroupBox("화면 감지")
        grp_pixels.setStyleSheet("QGroupBox::title { color:#f8fafc; font-weight:800; }")
        grp_pixels_layout = QVBoxLayout(grp_pixels)
        grp_pixels_layout.addWidget(self.pixels_panel)

        body.addWidget(grp_pixels)
        body.addStretch(1)

        body_container = QWidget()
        body_container.setLayout(body)
        self._automation_scroll = QScrollArea()
        self._automation_scroll.setWidgetResizable(True)
        self._automation_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._automation_scroll.setWidget(body_container)
        outer.addWidget(self._automation_scroll)
        self.tab_automation.setLayout(outer)

    def _build_legacy_tab(self):
        lay = QVBoxLayout()
        tip = QLabel("SpectatorLog에 없는 화면 조건을 감지하고 필요한 액션을 연결합니다.")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#667085;")
        lay.addWidget(tip)
        lay.addWidget(self.tab_automation, 1)
        self.tab_legacy.setLayout(lay)

    def _apply_pixel_rules(self):
        rules = []
        for rule in self._pixel_rules:
            r = dict(rule)
            if not r.get("id"):
                r["id"] = f"pixel_{uuid.uuid4().hex}"
            rules.append(r)
        self.cfg.pixel_rules = rules

    # ---- Actions tab ----
    def _build_actions(self):
        self.actions_panel = QWidget()
        lay = QHBoxLayout(self.actions_panel)
        def _tt(w: QWidget, text: str):
            try:
                w.setToolTip(text)
            except Exception:
                pass

        left = QVBoxLayout()
        evt_row = QHBoxLayout()
        self.lbl_action_event = QLabel("현재 조건: on_trigger")
        _tt(self.lbl_action_event, "현재 선택된 조건(트리거/화면감지/사운드감지)에 연결된 액션을 편집합니다.")
        evt_row.addWidget(self.lbl_action_event, 1)
        self.cmb_action_event = QComboBox()
        self.cmb_action_event.setVisible(False)
        self.cmb_action_event.currentTextChanged.connect(self._on_action_event_changed)
        evt_row.addWidget(self.cmb_action_event)
        left.addLayout(evt_row)

        cd_row = QHBoxLayout()
        cd_row.addWidget(QLabel("이벤트 액션 쿨타임(s):"))
        self.sp_action_event_cd = QDoubleSpinBox()
        self.sp_action_event_cd.setRange(0.0, 60.0)
        self.sp_action_event_cd.setSingleStep(0.1)
        self._apply_wheel_filter(self.sp_action_event_cd)
        _tt(self.sp_action_event_cd, "같은 조건이 다시 충족되더라도 지정 시간 동안 액션 실행을 막습니다.")
        cd_row.addWidget(self.sp_action_event_cd)
        self.chk_action_event_edge = QCheckBox("Edge trigger")
        self.chk_action_event_edge.stateChanged.connect(self._on_action_event_edge_changed)
        _tt(self.chk_action_event_edge, "참 상태가 유지되어도 거짓->참 전환 시 1회만 실행합니다. (트리거/화면감지 조건 전용)")
        cd_row.addSpacing(8)
        cd_row.addWidget(self.chk_action_event_edge)
        cd_row.addStretch(1)
        self.btn_action_test = QPushButton("테스트")
        self.btn_action_test.clicked.connect(self._test_event_actions)
        _tt(self.btn_action_test, "현재 조건에 연결된 액션을 즉시 실행해 테스트합니다.")
        cd_row.addWidget(self.btn_action_test)
        left.addLayout(cd_row)

        self.lst_actions = QListWidget()
        self.lst_actions.currentRowChanged.connect(self._on_action_selected)
        _tt(self.lst_actions, "현재 조건에 연결된 액션 순서 목록입니다. 위/아래 버튼으로 순서를 바꿀 수 있습니다.")
        left.addWidget(QLabel("액션 목록"))
        left.addWidget(self.lst_actions, 1)
        self.lbl_actions_empty = QLabel("액션 없음: [추가] 눌러 생성")
        self.lbl_actions_empty.setStyleSheet("color:#888;")
        self.lbl_actions_empty.setVisible(False)
        left.addWidget(self.lbl_actions_empty)

        btn_row = QHBoxLayout()
        self.btn_act_add = QPushButton("추가")
        self.btn_act_del = QPushButton("삭제")
        self.btn_act_up = QPushButton("위로")
        self.btn_act_down = QPushButton("아래로")
        self.btn_act_add.clicked.connect(self._add_action)
        self.btn_act_del.clicked.connect(self._del_action)
        self.btn_act_up.clicked.connect(self._move_action_up)
        self.btn_act_down.clicked.connect(self._move_action_down)
        _tt(self.btn_act_add, "새 액션을 추가합니다.")
        _tt(self.btn_act_del, "선택된 액션을 삭제합니다.")
        _tt(self.btn_act_up, "선택된 액션을 위로 올립니다.")
        _tt(self.btn_act_down, "선택된 액션을 아래로 내립니다.")
        btn_row.addWidget(self.btn_act_add)
        btn_row.addWidget(self.btn_act_del)
        btn_row.addWidget(self.btn_act_up)
        btn_row.addWidget(self.btn_act_down)
        left.addLayout(btn_row)

        right = QVBoxLayout()
        right.addWidget(QLabel("액션 편집"))

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("종류"))
        self.cmb_action_type = QComboBox()
        self.cmb_action_type.addItem("지연(s)", "delay_ms")
        self.cmb_action_type.addItem("키 누르기", "key_press")
        self.cmb_action_type.addItem("핫키(조합)", "hotkey")
        self.cmb_action_type.addItem("텍스트 입력", "type_text")
        self.cmb_action_type.addItem("마우스 이동", "mouse_move")
        self.cmb_action_type.addItem("마우스 클릭", "mouse_click")
        self.cmb_action_type.addItem("타이머 시작", "timer_start")
        self.cmb_action_type.addItem("타이머 정지", "timer_stop")
        self.cmb_action_type.addItem("타이머 리셋", "timer_reset")
        self.cmb_action_type.addItem("타이머 값 설정", "timer_set")
        self.cmb_action_type.addItem("블루 연승 +1", "blue_win_plus")
        self.cmb_action_type.addItem("레드 연승 +1", "red_win_plus")
        self.cmb_action_type.addItem("TTS(영어)", "tts_en")
        self.cmb_action_type.addItem("매치업 안내 TTS(영어)", "matchup_tts_en")
        self.cmb_action_type.addItem("팔레트 캡처", "palette_capture")
        self.cmb_action_type.currentIndexChanged.connect(self._on_action_type_changed)
        _tt(self.cmb_action_type, "추가/편집할 액션 종류를 선택합니다.")
        type_row.addWidget(self.cmb_action_type, 1)
        right.addLayout(type_row)

        self.action_stack = QStackedWidget()

        self._pg_delay = QWidget()
        pg = QHBoxLayout()
        self.sp_delay_sec = QDoubleSpinBox()
        self.sp_delay_sec.setRange(0.0, 60.0)
        self.sp_delay_sec.setSingleStep(0.1)
        self._apply_wheel_filter(self.sp_delay_sec)
        _tt(self.sp_delay_sec, "다음 액션까지 기다릴 시간(초).")
        pg.addWidget(QLabel("지연(s):")); pg.addWidget(self.sp_delay_sec)
        self._pg_delay.setLayout(pg)
        self.action_stack.addWidget(self._pg_delay)

        self._pg_key = QWidget()
        pg = QHBoxLayout()
        self.cmb_action_key = QComboBox()
        key_items = _PYAUTO_KEYS or list(build_vk_map().keys())
        self.cmb_action_key.addItems(key_items)
        self.sp_key_hold = QSpinBox(); self.sp_key_hold.setRange(0, 5000)
        _tt(self.cmb_action_key, "눌러줄 키를 선택합니다.")
        _tt(self.sp_key_hold, "키를 누르고 유지할 시간(ms). 0이면 탭처럼 눌렀다 놓습니다.")
        pg.addWidget(QLabel("키:")); pg.addWidget(self.cmb_action_key)
        pg.addWidget(QLabel("홀드(ms):")); pg.addWidget(self.sp_key_hold)
        self._pg_key.setLayout(pg)
        self.action_stack.addWidget(self._pg_key)

        self._pg_hotkey = QWidget()
        pg = QHBoxLayout()
        self.txt_hotkey = QLineEdit()
        self.txt_hotkey.setPlaceholderText("예: ctrl,shift,a")
        _tt(self.txt_hotkey, "예: ctrl,shift,a 처럼 콤마로 키 조합을 입력합니다.")
        pg.addWidget(QLabel("핫키 조합:")); pg.addWidget(self.txt_hotkey)
        self._pg_hotkey.setLayout(pg)
        self.action_stack.addWidget(self._pg_hotkey)

        self._pg_type = QWidget()
        pg = QHBoxLayout()
        self.txt_type = QLineEdit()
        self.sp_type_interval = QSpinBox(); self.sp_type_interval.setRange(0, 2000)
        _tt(self.txt_type, "입력할 텍스트를 적습니다.")
        _tt(self.sp_type_interval, "문자 입력 간격(ms). 0이면 즉시 입력합니다.")
        pg.addWidget(QLabel("텍스트:")); pg.addWidget(self.txt_type, 1)
        pg.addWidget(QLabel("간격(ms):")); pg.addWidget(self.sp_type_interval)
        self._pg_type.setLayout(pg)
        self.action_stack.addWidget(self._pg_type)

        self._pg_tts = QWidget()
        pg = QHBoxLayout()
        self.txt_tts = QLineEdit()
        self.txt_tts.setPlaceholderText("영어 문장 입력")
        self.sp_tts_rate = QSpinBox()
        self.sp_tts_rate.setRange(80, 300)
        self.sp_tts_rate.setValue(200)
        self.sp_tts_volume = QSpinBox()
        self.sp_tts_volume.setRange(0, 100)
        self.sp_tts_volume.setValue(100)
        self.cmb_tts_voice_mode = QComboBox()
        self.cmb_tts_voice_mode.addItem("자동", "auto")
        self.cmb_tts_voice_mode.addItem("한국어 우선", "ko")
        self.cmb_tts_voice_mode.addItem("영어 우선", "en")
        self.sp_tts_repeat = QSpinBox()
        self.sp_tts_repeat.setRange(1, 10)
        self.sp_tts_repeat.setValue(1)
        _tt(self.txt_tts, "읽어줄 영어 문장을 입력합니다.")
        _tt(self.sp_tts_rate, "TTS 재생 속도(숫자가 낮을수록 느림).")
        _tt(self.sp_tts_volume, "TTS 재생 볼륨(0~100%).")
        _tt(self.cmb_tts_voice_mode, "TTS 음성 우선순위(자동/한국어/영어)를 선택합니다.")
        _tt(self.sp_tts_repeat, "매치업 안내 TTS에서 반복 재생할 횟수입니다.")
        pg.addWidget(QLabel("TTS 텍스트:")); pg.addWidget(self.txt_tts, 1)
        pg.addWidget(QLabel("속도:")); pg.addWidget(self.sp_tts_rate)
        pg.addWidget(QLabel("볼륨(%):")); pg.addWidget(self.sp_tts_volume)
        pg.addWidget(QLabel("음성:")); pg.addWidget(self.cmb_tts_voice_mode)
        pg.addWidget(QLabel("횟수:")); pg.addWidget(self.sp_tts_repeat)
        self.btn_tts_test = QPushButton("TTS 테스트")
        self.btn_tts_test.clicked.connect(self._test_tts_action)
        _tt(self.btn_tts_test, "현재 TTS 설정으로 바로 재생해봅니다.")
        pg.addWidget(self.btn_tts_test)
        self._pg_tts.setLayout(pg)
        self.action_stack.addWidget(self._pg_tts)

        self._pg_mouse = QWidget()
        pg = QHBoxLayout()
        self.sp_mouse_x = QSpinBox(); self.sp_mouse_x.setRange(0, 10000)
        self.sp_mouse_y = QSpinBox(); self.sp_mouse_y.setRange(0, 10000)
        self.sp_move_duration = QSpinBox(); self.sp_move_duration.setRange(0, 5000)
        self.btn_mouse_pick = QPushButton("현재 마우스 위치")
        self.btn_mouse_pick.clicked.connect(self._pick_mouse_pos)
        self.btn_mouse_pick_pixel = QPushButton("픽셀 감지 위치")
        self.btn_mouse_pick_pixel.clicked.connect(self._pick_action_default_pos)
        self.btn_mouse_pick_hotkey = QPushButton("")
        self.btn_mouse_pick_hotkey.clicked.connect(self._apply_action_pick_from_cursor)
        _tt(self.sp_mouse_x, "마우스를 이동할 X 좌표(화면 기준).")
        _tt(self.sp_mouse_y, "마우스를 이동할 Y 좌표(화면 기준).")
        _tt(self.sp_move_duration, "이동하는 데 걸리는 시간(ms). 0이면 즉시 이동합니다.")
        _tt(self.btn_mouse_pick, "현재 마우스 위치를 X/Y에 입력합니다.")
        _tt(self.btn_mouse_pick_pixel, "픽셀 감지 조건의 좌표를 X/Y에 입력합니다.")
        _tt(self.btn_mouse_pick_hotkey, "단축키로 현재 마우스 위치를 가져옵니다.")
        pg.addWidget(QLabel("X:")); pg.addWidget(self.sp_mouse_x)
        pg.addWidget(QLabel("Y:")); pg.addWidget(self.sp_mouse_y)
        pg.addWidget(QLabel("이동(ms):")); pg.addWidget(self.sp_move_duration)
        self.btn_mouse_pick.setVisible(False)
        pg.addWidget(self.btn_mouse_pick)
        pg.addWidget(self.btn_mouse_pick_pixel)
        pg.addWidget(self.btn_mouse_pick_hotkey)
        self._pg_mouse.setLayout(pg)
        self.action_stack.addWidget(self._pg_mouse)

        self._pg_click = QWidget()
        pg = QHBoxLayout()
        self.sp_click_x = QSpinBox(); self.sp_click_x.setRange(0, 10000)
        self.sp_click_y = QSpinBox(); self.sp_click_y.setRange(0, 10000)
        self.btn_click_pick = QPushButton("현재 마우스 위치")
        self.btn_click_pick.clicked.connect(self._pick_click_pos)
        self.btn_click_capture = QPushButton("클릭 캡처")
        self.btn_click_capture.clicked.connect(self._start_click_capture)
        self.btn_click_pick_pixel = QPushButton("픽셀 감지 위치")
        self.btn_click_pick_pixel.clicked.connect(self._pick_action_default_pos)
        self.btn_click_pick_hotkey = QPushButton("")
        self.btn_click_pick_hotkey.clicked.connect(self._apply_action_pick_from_cursor)
        self.cmb_click_btn = QComboBox(); self.cmb_click_btn.addItems(["left", "right", "middle"])
        self.sp_clicks = QSpinBox(); self.sp_clicks.setRange(1, 10)
        self.sp_click_interval = QSpinBox(); self.sp_click_interval.setRange(0, 2000)
        _tt(self.sp_click_x, "클릭할 X 좌표(화면 기준).")
        _tt(self.sp_click_y, "클릭할 Y 좌표(화면 기준).")
        _tt(self.btn_click_pick, "현재 마우스 위치를 X/Y에 입력합니다.")
        _tt(self.btn_click_capture, "다음 클릭 위치를 캡처합니다.")
        _tt(self.btn_click_pick_pixel, "픽셀 감지 조건의 좌표를 X/Y에 입력합니다.")
        _tt(self.btn_click_pick_hotkey, "단축키로 현재 마우스 위치를 가져옵니다.")
        _tt(self.cmb_click_btn, "클릭할 마우스 버튼을 선택합니다.")
        _tt(self.sp_clicks, "클릭 횟수입니다.")
        _tt(self.sp_click_interval, "클릭 사이 간격(ms).")
        pg.addWidget(QLabel("X:")); pg.addWidget(self.sp_click_x)
        pg.addWidget(QLabel("Y:")); pg.addWidget(self.sp_click_y)
        self.btn_click_pick.setVisible(False)
        self.btn_click_capture.setVisible(False)
        pg.addWidget(self.btn_click_pick)
        pg.addWidget(self.btn_click_capture)
        pg.addWidget(self.btn_click_pick_pixel)
        pg.addWidget(self.btn_click_pick_hotkey)
        pg.addWidget(QLabel("버튼:")); pg.addWidget(self.cmb_click_btn)
        pg.addWidget(QLabel("횟수:")); pg.addWidget(self.sp_clicks)
        pg.addWidget(QLabel("간격(ms):")); pg.addWidget(self.sp_click_interval)
        self._pg_click.setLayout(pg)
        self.action_stack.addWidget(self._pg_click)

        self._pg_timer_set = QWidget()
        pg = QHBoxLayout()
        self.sp_set_round = QSpinBox(); self.sp_set_round.setRange(1, 99)
        self.sp_set_total = QSpinBox(); self.sp_set_total.setRange(1, 99)
        self.sp_set_sec = QSpinBox(); self.sp_set_sec.setRange(1, 3600)
        _tt(self.sp_set_round, "현재 라운드 번호를 설정합니다.")
        _tt(self.sp_set_total, "총 라운드 수를 설정합니다.")
        _tt(self.sp_set_sec, "남은 시간을 초 단위로 설정합니다.")
        pg.addWidget(QLabel("현재 라운드:")); pg.addWidget(self.sp_set_round)
        pg.addWidget(QLabel("총 라운드:")); pg.addWidget(self.sp_set_total)
        pg.addWidget(QLabel("초:")); pg.addWidget(self.sp_set_sec)
        self._pg_timer_set.setLayout(pg)
        self.action_stack.addWidget(self._pg_timer_set)

        self._pg_none = QWidget()
        self.action_stack.addWidget(self._pg_none)

        right.addWidget(self.action_stack)

        post_row = QHBoxLayout()
        self.sp_pre_delay_sec = QDoubleSpinBox()
        self.sp_pre_delay_sec.setRange(0.0, 60.0)
        self.sp_pre_delay_sec.setSingleStep(0.1)
        self._apply_wheel_filter(self.sp_pre_delay_sec)
        self.sp_post_delay_sec = QDoubleSpinBox()
        self.sp_post_delay_sec.setRange(0.0, 60.0)
        self.sp_post_delay_sec.setSingleStep(0.1)
        self._apply_wheel_filter(self.sp_post_delay_sec)
        _tt(self.sp_pre_delay_sec, "액션 실행 전에 기다리는 시간(초). 0이면 바로 실행합니다.")
        _tt(self.sp_post_delay_sec, "액션 실행 후에 기다리는 시간(초). 다음 액션 전에 쉬는 시간입니다.")
        post_row.addWidget(QLabel("선행 지연(s):"))
        post_row.addWidget(self.sp_pre_delay_sec)
        post_row.addSpacing(12)
        post_row.addWidget(QLabel("후행 지연(s):"))
        post_row.addWidget(self.sp_post_delay_sec)
        post_row.addStretch(1)
        right.addLayout(post_row)

        self.btn_action_apply = QPushButton("적용")
        self.btn_action_apply.clicked.connect(self._apply_action_edit)
        _tt(self.btn_action_apply, "현재 편집 중인 액션 내용을 저장합니다.")
        right.addWidget(self.btn_action_apply)

        lay.addLayout(left, 1)
        lay.addLayout(right, 2)

        self._actions_by_event = dict(self.cfg.actions or {})
        self._normalize_action_aliases()
        self._normalize_action_cooldown_aliases()
        self._normalize_action_edge_aliases()
        self._refresh_action_events()
        self._load_actions_for_event(self.cmb_action_event.currentText())
        self._action_loading = False
        self._action_apply_timer = QTimer(self)
        self._action_apply_timer.setSingleShot(True)
        self._action_apply_timer.timeout.connect(self._apply_action_edit)
        self._init_action_autosave()
        self._actions_home = QWidget()
        home_lay = QVBoxLayout(self._actions_home)
        home_lay.setContentsMargins(0, 0, 0, 0)
        home_lay.addWidget(self.actions_panel)
        self.actions_panel.setVisible(False)

    def _reload_actions_list(self):
        self.lst_actions.clear()
        for action in self._actions_list:
            self.lst_actions.addItem(self._action_summary(action))
        self.lbl_actions_empty.setVisible(len(self._actions_list) == 0)

    def _action_summary(self, action: dict) -> str:
        t = str(action.get("type", ""))
        if t == "delay_ms":
            sec = float(action.get("ms", 0)) / 1000.0
            return f"지연 {sec:.1f}s"
        if t == "key_press":
            return f"키 누르기 {action.get('key', '')}"
        if t == "hotkey":
            return "핫키 " + ",".join(action.get("keys", []) or [])
        if t == "type_text":
            return f"텍스트 입력 \"{action.get('text', '')}\""
        if t == "mouse_move":
            return f"마우스 이동 ({action.get('x', 0)},{action.get('y', 0)})"
        if t == "mouse_click":
            return f"마우스 클릭 ({action.get('x', 0)},{action.get('y', 0)})"
        if t == "tts_en":
            rate = action.get("rate", 200)
            return f"TTS {rate} \"{action.get('text', '')}\""
        if t == "matchup_tts_en":
            rate = action.get("rate", 200)
            repeat = int(action.get("repeat", 1) or 1)
            return f"매치업 TTS {rate} x{repeat}"
        if t.startswith("timer_"):
            return f"타이머 {t.replace('timer_', '')}"
        if t == "blue_win_plus":
            return "블루 연승 +1"
        if t == "red_win_plus":
            return "레드 연승 +1"
        if t == "palette_capture":
            return "팔레트 캡처"
        return t

    def _init_action_autosave(self) -> None:
        def _wire(widget, signal_name: str):
            if hasattr(widget, signal_name):
                getattr(widget, signal_name).connect(self._mark_action_dirty)

        _wire(self.cmb_action_type, "currentIndexChanged")
        _wire(self.sp_pre_delay_sec, "valueChanged")
        _wire(self.sp_post_delay_sec, "valueChanged")
        _wire(self.sp_delay_sec, "valueChanged")
        _wire(self.cmb_action_key, "currentIndexChanged")
        _wire(self.sp_key_hold, "valueChanged")
        _wire(self.txt_hotkey, "textChanged")
        _wire(self.txt_type, "textChanged")
        _wire(self.sp_type_interval, "valueChanged")
        _wire(self.txt_tts, "textChanged")
        _wire(self.sp_tts_rate, "valueChanged")
        _wire(self.sp_tts_volume, "valueChanged")
        _wire(self.cmb_tts_voice_mode, "currentIndexChanged")
        _wire(self.sp_tts_repeat, "valueChanged")
        _wire(self.sp_mouse_x, "valueChanged")
        _wire(self.sp_mouse_y, "valueChanged")
        _wire(self.sp_move_duration, "valueChanged")
        _wire(self.sp_click_x, "valueChanged")
        _wire(self.sp_click_y, "valueChanged")
        _wire(self.cmb_click_btn, "currentIndexChanged")
        _wire(self.sp_clicks, "valueChanged")
        _wire(self.sp_click_interval, "valueChanged")
        _wire(self.sp_set_round, "valueChanged")
        _wire(self.sp_set_total, "valueChanged")
        _wire(self.sp_set_sec, "valueChanged")

    def _mark_action_dirty(self, *_args) -> None:
        if getattr(self, "_action_loading", False):
            return
        if not hasattr(self, "_actions_list") or self.lst_actions.currentRow() < 0:
            return
        if hasattr(self, "_action_apply_timer"):
            self._action_apply_timer.start(200)

    def _add_action(self):
        self._actions_list.append({"type": "delay_ms", "ms": 100})
        self._reload_actions_list()
        self.lst_actions.setCurrentRow(len(self._actions_list) - 1)

    def _del_action(self):
        idx = self.lst_actions.currentRow()
        if idx < 0:
            return
        del self._actions_list[idx]
        self._reload_actions_list()
        self.lst_actions.setCurrentRow(min(idx, len(self._actions_list) - 1))

    def _move_action_up(self):
        idx = self.lst_actions.currentRow()
        if idx <= 0:
            return
        self._actions_list[idx - 1], self._actions_list[idx] = self._actions_list[idx], self._actions_list[idx - 1]
        self._reload_actions_list()
        self.lst_actions.setCurrentRow(idx - 1)

    def _move_action_down(self):
        idx = self.lst_actions.currentRow()
        if idx < 0 or idx >= len(self._actions_list) - 1:
            return
        self._actions_list[idx + 1], self._actions_list[idx] = self._actions_list[idx], self._actions_list[idx + 1]
        self._reload_actions_list()
        self.lst_actions.setCurrentRow(idx + 1)

    def _on_action_selected(self, row: int):
        if row < 0 or row >= len(self._actions_list):
            return
        action = self._actions_list[row]
        self._load_action_edit(action)

    def _on_action_type_changed(self, _idx: int):
        t = self.cmb_action_type.currentData()
        mapping = {
            "delay_ms": self._pg_delay,
            "key_press": self._pg_key,
            "hotkey": self._pg_hotkey,
            "type_text": self._pg_type,
            "tts_en": self._pg_tts,
            "matchup_tts_en": self._pg_tts,
            "mouse_move": self._pg_mouse,
            "mouse_click": self._pg_click,
            "timer_set": self._pg_timer_set,
        }
        self.action_stack.setCurrentWidget(mapping.get(t, self._pg_none))
        if hasattr(self, "txt_tts"):
            if t == "matchup_tts_en":
                self.txt_tts.setEnabled(True)
                self.txt_tts.setPlaceholderText("{blue} versus {red}, the match will begin shortly.")
                self.sp_tts_repeat.setEnabled(True)
            else:
                self.txt_tts.setEnabled(True)
                self.txt_tts.setPlaceholderText("영어 문장 입력")
                self.sp_tts_repeat.setEnabled(False)

    def _load_action_edit(self, action: dict):
        self._action_loading = True
        t = action.get("type", "delay_ms")
        for i in range(self.cmb_action_type.count()):
            if self.cmb_action_type.itemData(i) == t:
                self.cmb_action_type.setCurrentIndex(i)
                break
        self.sp_pre_delay_sec.setValue(int(action.get("pre_delay_ms", 0)) / 1000.0)
        self.sp_post_delay_sec.setValue(int(action.get("post_delay_ms", 0)) / 1000.0)
        self.sp_delay_sec.setValue(int(action.get("ms", 0)) / 1000.0)
        key_name = str(action.get("key", "") or "")
        if key_name and hasattr(self, "cmb_action_key"):
            idx = self.cmb_action_key.findText(key_name)
            if idx < 0:
                idx = self.cmb_action_key.findText(key_name.lower())
            if idx >= 0:
                self.cmb_action_key.setCurrentIndex(idx)
        self.sp_key_hold.setValue(int(action.get("hold_ms", 0)))
        self.txt_hotkey.setText(",".join(action.get("keys", []) or []))
        self.txt_type.setText(str(action.get("text", "")))
        self.txt_tts.setText(str(action.get("text", "")))
        self.sp_tts_rate.setValue(int(action.get("rate", 200)))
        self.sp_tts_volume.setValue(int(action.get("volume", 100)))
        vm = str(action.get("voice_mode", "auto") or "auto")
        idx_vm = self.cmb_tts_voice_mode.findData(vm)
        self.cmb_tts_voice_mode.setCurrentIndex(idx_vm if idx_vm >= 0 else 0)
        self.sp_tts_repeat.setValue(int(action.get("repeat", 1)))
        self.sp_type_interval.setValue(int(action.get("interval_ms", 0)))
        x_val = int(action.get("x", 0)) if "x" in action else 0
        y_val = int(action.get("y", 0)) if "y" in action else 0
        if t in ("mouse_move", "mouse_click"):
            use_mon = bool(action.get("use_monitor", False))
            mon = int(action.get("monitor", self.cfg.monitor_index))
            if t == "mouse_move":
                if hasattr(self, "chk_mouse_mon"):
                    self.chk_mouse_mon.setChecked(use_mon)
                    self.sp_mouse_mon.setValue(mon)
            else:
                if hasattr(self, "chk_click_mon"):
                    self.chk_click_mon.setChecked(use_mon)
                    self.sp_click_mon.setValue(mon)
        if t in ("mouse_move", "mouse_click", "mouse_down", "mouse_up") and self._action_default_pos:
            if ("x" not in action or "y" not in action) or (x_val == 0 and y_val == 0):
                x_val, y_val = self._action_default_pos
        self.sp_mouse_x.setValue(int(x_val))
        self.sp_mouse_y.setValue(int(y_val))
        self.sp_move_duration.setValue(int(action.get("duration_ms", 0)))
        self.sp_click_x.setValue(int(x_val))
        self.sp_click_y.setValue(int(y_val))
        self.cmb_click_btn.setCurrentText(str(action.get("button", "left")))
        self.sp_clicks.setValue(int(action.get("clicks", 1)))
        self.sp_click_interval.setValue(int(action.get("interval_ms", 0)))
        self.sp_set_round.setValue(int(action.get("round_current", 1)))
        self.sp_set_total.setValue(int(action.get("round_total", 1)))
        self.sp_set_sec.setValue(int(action.get("seconds_left", 60)))
        self._action_loading = False

    def _apply_action_edit(self):
        idx = self.lst_actions.currentRow()
        if idx < 0 or idx >= len(self._actions_list):
            return
        prev_action = self._actions_list[idx] if isinstance(self._actions_list[idx], dict) else {}
        t = self.cmb_action_type.currentData()
        action = {"type": t}
        pre_delay = int(self.sp_pre_delay_sec.value() * 1000)
        if pre_delay > 0:
            action["pre_delay_ms"] = pre_delay
        post_delay = int(self.sp_post_delay_sec.value() * 1000)
        if post_delay > 0:
            action["post_delay_ms"] = post_delay
        if t == "delay_ms":
            action["ms"] = int(self.sp_delay_sec.value() * 1000)
        elif t == "key_press":
            key_name = self.cmb_action_key.currentText() if hasattr(self, "cmb_action_key") else ""
            action["key"] = show_non_empty(key_name)
            action["hold_ms"] = int(self.sp_key_hold.value())
        elif t == "hotkey":
            keys = [k.strip() for k in self.txt_hotkey.text().split(",") if k.strip()]
            action["keys"] = keys
        elif t == "type_text":
            action["text"] = self.txt_type.text()
            action["interval_ms"] = int(self.sp_type_interval.value())
        elif t == "mouse_move":
            action["x"] = int(self.sp_mouse_x.value())
            action["y"] = int(self.sp_mouse_y.value())
            action["duration_ms"] = int(self.sp_move_duration.value())
            if hasattr(self, "chk_mouse_mon") and hasattr(self, "sp_mouse_mon"):
                use_mon = bool(self.chk_mouse_mon.isChecked())
                action["use_monitor"] = use_mon
                if use_mon:
                    action["monitor"] = int(self.sp_mouse_mon.value())
            else:
                use_mon = bool(prev_action.get("use_monitor", False))
                action["use_monitor"] = use_mon
                if use_mon:
                    action["monitor"] = int(prev_action.get("monitor", self.cfg.monitor_index))
        elif t == "mouse_click":
            action["x"] = int(self.sp_click_x.value())
            action["y"] = int(self.sp_click_y.value())
            action["button"] = self.cmb_click_btn.currentText()
            action["clicks"] = int(self.sp_clicks.value())
            action["interval_ms"] = int(self.sp_click_interval.value())
            if hasattr(self, "chk_click_mon") and hasattr(self, "sp_click_mon"):
                use_mon = bool(self.chk_click_mon.isChecked())
                action["use_monitor"] = use_mon
                if use_mon:
                    action["monitor"] = int(self.sp_click_mon.value())
            else:
                use_mon = bool(prev_action.get("use_monitor", False))
                action["use_monitor"] = use_mon
                if use_mon:
                    action["monitor"] = int(prev_action.get("monitor", self.cfg.monitor_index))
        elif t == "tts_en":
            action["text"] = self.txt_tts.text()
            action["rate"] = int(self.sp_tts_rate.value())
            action["volume"] = int(self.sp_tts_volume.value())
            action["voice_mode"] = str(self.cmb_tts_voice_mode.currentData() or "auto")
        elif t == "matchup_tts_en":
            action["text"] = self.txt_tts.text().strip() or "{blue} versus {red}, the match will begin shortly."
            action["rate"] = int(self.sp_tts_rate.value())
            action["volume"] = int(self.sp_tts_volume.value())
            action["voice_mode"] = str(self.cmb_tts_voice_mode.currentData() or "auto")
            action["repeat"] = int(self.sp_tts_repeat.value())
        elif t == "timer_set":
            action["round_current"] = int(self.sp_set_round.value())
            action["round_total"] = int(self.sp_set_total.value())
            action["seconds_left"] = int(self.sp_set_sec.value())
        ev = getattr(self, "_current_actions_event", "") or self.cmb_action_event.currentText()
        if ev and (ev.startswith("pixel:") or ev.startswith("pixel_id:")) and self._action_default_pos:
            if t in ("mouse_move", "mouse_click", "mouse_down", "mouse_up"):
                x_val = int(action.get("x", 0))
                y_val = int(action.get("y", 0))
                if x_val == 0 and y_val == 0:
                    action["x"], action["y"] = self._action_default_pos
        self._actions_list[idx] = action
        self._reload_actions_list()
        self.lst_actions.setCurrentRow(idx)

    def _default_action_cooldown_for_event(self, event: str) -> float:
        if event == "on_trigger":
            return float(getattr(self.cfg.trigger, "action_cooldown_sec", 0.0) or 0.0)
        if hasattr(self, "sp_action_cooldown"):
            return float(self.sp_action_cooldown.value())
        return float(getattr(self.cfg, "action_cooldown_sec", 0.0) or 0.0)

    def _get_action_cooldown_for_event(self, event: str) -> float:
        if not event:
            return 0.0
        direct = self._action_cooldowns_by_event.get(event)
        if direct is not None:
            return float(direct)
        if event.startswith("sound:"):
            name = event.split(":", 1)[1]
            sid = self._sound_id_for_name(name)
            if sid:
                alt = self._action_cooldowns_by_event.get(f"sound_id:{sid}")
                if alt is not None:
                    return float(alt)
        if event.startswith("pixel:"):
            name = event.split(":", 1)[1]
            pid = self._pixel_id_for_name(name)
            if pid:
                alt = self._action_cooldowns_by_event.get(f"pixel_id:{pid}")
                if alt is not None:
                    return float(alt)
        return self._default_action_cooldown_for_event(event)

    def _edge_capable_event(self, event: str) -> bool:
        if not event:
            return False
        return event == "on_trigger" or event.startswith("pixel:") or event.startswith("pixel_id:")

    def _get_action_edge_for_event(self, event: str) -> bool:
        if not self._edge_capable_event(event):
            return False
        direct = self._action_edge_triggers_by_event.get(event)
        if direct is not None:
            return bool(direct)
        if event.startswith("pixel:"):
            name = event.split(":", 1)[1]
            pid = self._pixel_id_for_name(name)
            if pid:
                alt = self._action_edge_triggers_by_event.get(f"pixel_id:{pid}")
                if alt is not None:
                    return bool(alt)
        if event.startswith("pixel_id:"):
            pid = event.split(":", 1)[1]
            name = self._pixel_name_for_id(pid)
            if name:
                alt = self._action_edge_triggers_by_event.get(f"pixel:{name}")
                if alt is not None:
                    return bool(alt)
        return False

    def _update_action_edge_for_event(self, event: str, enabled: bool) -> None:
        if not event:
            return
        targets = self._event_targets(event)
        if not self._edge_capable_event(event):
            for key in targets:
                self._action_edge_triggers_by_event.pop(key, None)
            return
        if bool(enabled):
            for key in targets:
                self._action_edge_triggers_by_event[key] = True
        else:
            for key in targets:
                self._action_edge_triggers_by_event.pop(key, None)

    def _load_action_edge_for_event(self, event: str) -> None:
        if not hasattr(self, "chk_action_event_edge"):
            return
        capable = self._edge_capable_event(event)
        self.chk_action_event_edge.blockSignals(True)
        self.chk_action_event_edge.setEnabled(capable)
        self.chk_action_event_edge.setChecked(bool(self._get_action_edge_for_event(event)) if capable else False)
        self.chk_action_event_edge.blockSignals(False)

    def _update_action_cooldown_for_event(self, event: str, value: float) -> None:
        if not event:
            return
        if event == "on_trigger":
            self.cfg.trigger.action_cooldown_sec = float(value)
            targets = self._event_targets(event)
            for key in targets:
                self._action_cooldowns_by_event.pop(key, None)
            return
        targets = self._event_targets(event)
        default_cd = self._default_action_cooldown_for_event(event)
        if float(value) == float(default_cd):
            for key in targets:
                self._action_cooldowns_by_event.pop(key, None)
            return
        for key in targets:
            self._action_cooldowns_by_event[key] = float(value)

    def _load_action_cooldown_for_event(self, event: str) -> None:
        if not hasattr(self, "sp_action_event_cd"):
            return
        self.sp_action_event_cd.blockSignals(True)
        self.sp_action_event_cd.setValue(float(self._get_action_cooldown_for_event(event)))
        self.sp_action_event_cd.blockSignals(False)

    def _test_event_actions(self):
        self._save_current_actions()
        ev = getattr(self, "_current_actions_event", "") or self.cmb_action_event.currentText() or "on_trigger"
        actions = self._get_actions_for_event(ev)
        if not actions:
            QMessageBox.information(self, "안내", "테스트할 액션이 없습니다.")
            return
        cd = float(self._get_action_cooldown_for_event(ev))
        if cd > 0:
            now = time.time()
            last = float(self._test_action_last_run.get(ev, 0.0) or 0.0)
            remain = cd - (now - last)
            if last > 0 and remain > 0:
                QMessageBox.information(self, "안내", "실행할 액션이 없습니다.")
                return
            self._test_action_last_run[ev] = now
        runner = self.action_runner
        try:
            if self.controller and hasattr(self.controller, "action_runner") and self.controller.action_runner:
                runner = self.controller.action_runner
            elif self.controller and getattr(self.controller, "timer_win", None):
                self.action_runner._timer_win = self.controller.timer_win
        except Exception:
            pass
        timer_win = self._timer_win or (getattr(self.controller, "timer_win", None) if self.controller else None)
        if timer_win is None:
            try:
                QMessageBox.warning(self, "테스트 오류", "타이머 윈도우가 없습니다. (timer_win None)")
            except Exception:
                pass
        else:
            try:
                runner._timer_win = timer_win
            except Exception:
                pass
        runner.run(actions, key=f"test:{ev}")

    def _test_tts_action(self):
        runner = self.action_runner
        try:
            if self.controller and hasattr(self.controller, "action_runner") and self.controller.action_runner:
                runner = self.controller.action_runner
        except Exception:
            pass
        t = self.cmb_action_type.currentData() if hasattr(self, "cmb_action_type") else ""
        if t == "matchup_tts_en":
            action = {
                "type": "matchup_tts_en",
                "text": self.txt_tts.text().strip() or "{blue} versus {red}, the match will begin shortly.",
                "rate": int(self.sp_tts_rate.value()),
                "volume": int(self.sp_tts_volume.value()),
                "voice_mode": str(self.cmb_tts_voice_mode.currentData() or "auto"),
                "repeat": int(self.sp_tts_repeat.value()),
            }
            runner.run([action], key="test:matchup_tts_en")
            return
        text = self.txt_tts.text().strip()
        if not text:
            return
        action = {
            "type": "tts_en",
            "text": text,
            "rate": int(self.sp_tts_rate.value()),
            "volume": int(self.sp_tts_volume.value()),
            "voice_mode": str(self.cmb_tts_voice_mode.currentData() or "auto"),
        }
        runner.run([action], key="test:tts_en")

    def _noop_status(self, _msg: str):
        return

    def _pick_mouse_pos(self):
        self._pending_action_pick = "mouse"
        self._pending_action_pick_btn = self.btn_mouse_pick
        self._pending_action_pick_text = self.btn_mouse_pick.text()
        self.btn_mouse_pick.setText("아무 키 누르기...")

    def _pick_click_pos(self):
        self._pending_action_pick = "click"
        self._pending_action_pick_btn = self.btn_click_pick
        self._pending_action_pick_text = self.btn_click_pick.text()
        self.btn_click_pick.setText("아무 키 누르기...")

    def _start_click_capture(self):
        self._click_overlay = ClickCaptureOverlay(self)
        self._click_overlay.clicked.connect(self._on_click_captured)
        rect = QGuiApplication.primaryScreen().geometry()
        for scr in QGuiApplication.screens():
            rect = rect.united(scr.geometry())
        self._click_overlay.setGeometry(rect)
        self._click_overlay.show()

    def _on_click_captured(self, x: int, y: int, button: str):
        self.sp_click_x.setValue(int(x))
        self.sp_click_y.setValue(int(y))
        if button in ["left", "right", "middle"]:
            self.cmb_click_btn.setCurrentText(button)

    def _monitor_to_global(self, monitor_index: int, x: int, y: int) -> tuple[int, int]:
        with mss.mss() as sct:
            mons = sct.monitors
            if monitor_index < 1 or monitor_index >= len(mons):
                return x, y
            mon = mons[monitor_index]
            return int(mon["left"] + x), int(mon["top"] + y)

    def _pick_action_default_pos(self):
        ev = getattr(self, "_current_actions_event", "") or self.cmb_action_event.currentText()
        if ev == "on_trigger":
            if not self.cfg.roi_trigger or not self.cfg.roi_trigger.valid():
                QMessageBox.information(self, "안내", "트리거 픽셀이 설정되어 있지 않습니다.")
                return
            gx, gy = int(self.cfg.roi_trigger.x), int(self.cfg.roi_trigger.y)
        else:
            if not self._action_default_pos:
                QMessageBox.information(self, "안내", "픽셀 감지 위치가 없습니다.")
                return
            gx, gy = self._action_default_pos
        lx, ly = int(gx), int(gy)
        t = self.cmb_action_type.currentData()
        if t == "mouse_move":
            self.sp_mouse_x.setValue(int(lx))
            self.sp_mouse_y.setValue(int(ly))
        elif t == "mouse_click":
            self.sp_click_x.setValue(int(lx))
            self.sp_click_y.setValue(int(ly))

    def _apply_action_pick_from_cursor(self):
        pos = QCursor.pos()
        lx, ly = int(pos.x()), int(pos.y())
        t = self.cmb_action_type.currentData()
        if t == "mouse_move":
            self.sp_mouse_x.setValue(int(lx))
            self.sp_mouse_y.setValue(int(ly))
        elif t == "mouse_click":
            self.sp_click_x.setValue(int(lx))
            self.sp_click_y.setValue(int(ly))

    def _refresh_action_pick_labels(self):
        hotkey = str(self.cfg.action_pick_hotkey or "").strip() or "Unset"
        text = f"단축키 위치 ({hotkey})"
        if hasattr(self, "btn_mouse_pick_hotkey"):
            self.btn_mouse_pick_hotkey.setText(text)
        if hasattr(self, "btn_click_pick_hotkey"):
            self.btn_click_pick_hotkey.setText(text)

    def _apply_actions(self):
        self._save_current_actions()
        self.cfg.actions = dict(self._actions_by_event)
        self.cfg.action_cooldowns = dict(self._action_cooldowns_by_event)
        self.cfg.action_edge_triggers = dict(self._action_edge_triggers_by_event)

    def _normalize_action_edge_aliases(self) -> None:
        if not hasattr(self, "_action_edge_triggers_by_event"):
            self._action_edge_triggers_by_event = dict(getattr(self.cfg, "action_edge_triggers", {}) or {})
        pixel_rules = self._pixel_rules if hasattr(self, "_pixel_rules") else (self.cfg.pixel_rules or [])
        for rule in pixel_rules:
            name = str(rule.get("name") or "").strip()
            pid = str(rule.get("id") or "").strip()
            if not name or not pid:
                continue
            key_name = f"pixel:{name}"
            key_id = f"pixel_id:{pid}"
            if key_name in self._action_edge_triggers_by_event:
                src = self._action_edge_triggers_by_event[key_name]
            elif key_id in self._action_edge_triggers_by_event:
                src = self._action_edge_triggers_by_event[key_id]
            else:
                continue
            self._action_edge_triggers_by_event[key_name] = bool(src)
            self._action_edge_triggers_by_event[key_id] = bool(src)
        self.cfg.action_edge_triggers = dict(self._action_edge_triggers_by_event)

    def _get_action_events(self) -> List[str]:
        events = ["on_trigger"]
        pixel_rules = self._pixel_rules if hasattr(self, "_pixel_rules") else (self.cfg.pixel_rules or [])
        for rule in pixel_rules:
            name = str(rule.get("name") or "").strip()
            if name:
                events.append(f"pixel:{name}")
        pixel_id_to_name = {}
        for rule in pixel_rules:
            rid = str(rule.get("id") or "").strip()
            name = str(rule.get("name") or "").strip()
            if rid and name:
                pixel_id_to_name[rid] = name
        for ev in (self.cfg.actions or {}).keys():
            if ev.startswith("pixel_id:"):
                pid = ev.split(":", 1)[1]
                name = pixel_id_to_name.get(pid)
                if name and f"pixel:{name}" in events:
                    continue
            if ev not in events:
                events.append(ev)
        return events

    def _refresh_action_events(self):
        current = self.cmb_action_event.currentText()
        events = observe_unique(self._get_action_events())
        self.cmb_action_event.blockSignals(True)
        self.cmb_action_event.clear()
        self.cmb_action_event.addItems(events)
        if current in events:
            self.cmb_action_event.setCurrentText(current)
        self.cmb_action_event.blockSignals(False)
        if current not in events:
            new_event = self.cmb_action_event.currentText()
            if new_event:
                self._load_actions_for_event(new_event)

    def _save_current_actions(self):
        if hasattr(self, "lst_actions") and self.lst_actions.currentRow() >= 0:
            self._apply_action_edit()
        ev = getattr(self, "_current_actions_event", "") or self.cmb_action_event.currentText() or "on_trigger"
        self._set_actions_for_event(ev, list(self._actions_list), update_panel=False)
        if hasattr(self, "sp_action_event_cd"):
            self._update_action_cooldown_for_event(ev, float(self.sp_action_event_cd.value()))
        if hasattr(self, "chk_action_event_edge"):
            self._update_action_edge_for_event(ev, bool(self.chk_action_event_edge.isChecked()))

    def _load_actions_for_event(self, event: str):
        ev = event or "on_trigger"
        self._current_actions_event = ev
        self._action_default_pos = self._pixel_event_default_pos(ev) if ev.startswith("pixel:") or ev.startswith("pixel_id:") else None
        self._ensure_event_actions(ev)
        if ev not in self._actions_by_event:
            self._actions_by_event[ev] = []
        self._actions_list = list(self._actions_by_event.get(ev, []))
        self._reload_actions_list()
        if self._actions_list:
            self.lst_actions.setCurrentRow(0)
        else:
            self.lst_actions.setCurrentRow(-1)
        self._load_action_cooldown_for_event(ev)
        self._load_action_edge_for_event(ev)
        if hasattr(self, "lbl_action_event"):
            self.lbl_action_event.setText(f"현재 조건: {ev or 'on_trigger'}")

    def _on_action_event_changed(self, event: str):
        self._save_current_actions()
        self._load_actions_for_event(event)
        self.lbl_action_event.setText(f"현재 조건: {event or 'on_trigger'}")

    def _on_action_event_edge_changed(self, state: int):
        ev = getattr(self, "_current_actions_event", "") or self.cmb_action_event.currentText() or "on_trigger"
        self._update_action_edge_for_event(ev, bool(state))

    def _actions_rehome(self):
        if self.actions_panel is None or not hasattr(self, "_actions_home"):
            return
        home_lay = self._actions_home.layout()
        if home_lay is None:
            home_lay = QVBoxLayout(self._actions_home)
            home_lay.setContentsMargins(0, 0, 0, 0)
        self.actions_panel.setParent(self._actions_home)
        if home_lay.indexOf(self.actions_panel) < 0:
            home_lay.addWidget(self.actions_panel)
        self.actions_panel.setVisible(False)

    def _open_actions_dialog(self, event: str):
        if self.actions_panel is None:
            return
        if hasattr(self, "_action_dialog") and self._action_dialog is not None and self._action_dialog.isVisible():
            self._action_dialog.raise_()
            self._action_dialog.activateWindow()
            return
        dlg = QDialog(self)
        title = event or "on_trigger"
        dlg.setWindowTitle("\uc5f0\uc2b9 \ub2e8\uacc4 \ud3b8\uc9d1")
        dlg.setSizeGripEnabled(True)
        dlg.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        dlg.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        dlg.setMinimumSize(720, 460)
        dlg.resize(900, 600)
        lay = QVBoxLayout(dlg)
        lay.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
        self.actions_panel.setParent(dlg)
        self.actions_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.actions_panel.setVisible(True)
        lay.addWidget(self.actions_panel)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(dlg.close)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)
        dlg.finished.connect(lambda _res: (self._save_current_actions(), self._actions_rehome()))
        self._action_dialog = dlg
        dlg.show()

    def _show_actions_for_event(self, event: str, *_args):
        self._set_actions_event(event)
        self._open_actions_dialog(event)

    def _set_actions_event(self, event: str):
        if not event:
            event = "on_trigger"
        self._save_current_actions()
        self._refresh_action_events()
        self.cmb_action_event.setCurrentText(event)
        self._on_action_event_changed(event)
        self._current_actions_event = event
        if hasattr(self, "_automation_scroll") and self.actions_panel is not None:
            self._automation_scroll.ensureWidgetVisible(self.actions_panel)
            self.lst_actions.setFocus()

    # ---- Apply / Save ----
    def apply_only(self, silent: bool = False):
        self.cfg.monitor_index = int(self.cmb_monitor.currentData())
        if hasattr(self, "edit_trigger_pixel_hotkey"):
            self.cfg.trigger_pixel_hotkey = self.edit_trigger_pixel_hotkey.keySequence().toString()
        if hasattr(self, "edit_roi_hotkey"):
            self.cfg.roi_hotkey = self.edit_roi_hotkey.keySequence().toString()
        if hasattr(self, "edit_pixel_hotkey"):
            self.cfg.pixel_hotkey = self.edit_pixel_hotkey.keySequence().toString()
        if hasattr(self, "edit_detect_hotkey"):
            self.cfg.detect_hotkey = self.edit_detect_hotkey.keySequence().toString()
        if hasattr(self, "edit_action_pick_hotkey"):
            self.cfg.action_pick_hotkey = self.edit_action_pick_hotkey.keySequence().toString()
            self._refresh_action_pick_labels()
        if hasattr(self, "edit_action_test_hotkey"):
            self.cfg.action_test_hotkey = self.edit_action_test_hotkey.keySequence().toString()
        if hasattr(self, "sp_chapter_offset"):
            self.cfg.chapter_offset_sec = int(self.sp_chapter_offset.value())
        if hasattr(self, "sp_chapter_dedupe"):
            self.cfg.chapter_dedupe_sec = int(self.sp_chapter_dedupe.value())
        if hasattr(self, "le_chapter_dir"):
            self.cfg.chapter_output_dir = str(self.le_chapter_dir.text() or "").strip()
        if hasattr(self, "chk_chapter_nickname_only"):
            self.cfg.chapter_nickname_only = bool(self.chk_chapter_nickname_only.isChecked())
        if hasattr(self, "chk_chapter_hide_time"):
            self.cfg.chapter_hide_time = bool(self.chk_chapter_hide_time.isChecked())
        if hasattr(self, "chk_spectatorlog_enabled"):
            self.cfg.spectatorlog_enabled = bool(self.chk_spectatorlog_enabled.isChecked())
        if hasattr(self, "chk_spectatorlog_sync_players"):
            self.cfg.spectatorlog_sync_players = bool(self.chk_spectatorlog_sync_players.isChecked())
        if hasattr(self, "chk_spectatorlog_sync_timer"):
            self.cfg.spectatorlog_sync_timer = bool(self.chk_spectatorlog_sync_timer.isChecked())
        if hasattr(self, "chk_spectator_lobby_auto_start"):
            self.cfg.spectator_lobby_auto_start_enabled = bool(self.chk_spectator_lobby_auto_start.isChecked())
            self.cfg.spectator_lobby_auto_start_target_title = str(
                self.le_spectator_lobby_auto_start_title.text() or ""
            ).strip()
            self.cfg.spectator_lobby_auto_start_client_x = int(self.sp_spectator_lobby_auto_start_x.value())
            self.cfg.spectator_lobby_auto_start_client_y = int(self.sp_spectator_lobby_auto_start_y.value())
            self.cfg.spectator_lobby_auto_start_click_count = int(
                self.sp_spectator_lobby_auto_start_click_count.value()
            )
            self.cfg.spectator_lobby_auto_start_delay_ms = int(self.sp_spectator_lobby_auto_start_delay.value())
            self.cfg.spectator_lobby_auto_start_activate = bool(
                self.chk_spectator_lobby_auto_start_activate.isChecked()
            )
            self.cfg.spectator_lobby_auto_start_restore_focus = bool(
                self.chk_spectator_lobby_auto_start_restore_focus.isChecked()
            )
            self.cfg.spectator_lobby_auto_start_restore_cursor = bool(
                self.chk_spectator_lobby_auto_start_restore_cursor.isChecked()
            )
            self.cfg.spectator_lobby_auto_start_minimize_target = bool(
                self.chk_spectator_lobby_auto_start_minimize_target.isChecked()
            )
        if hasattr(self, "le_spectatorlog_path"):
            self.cfg.spectatorlog_path = str(self.le_spectatorlog_path.text() or "").strip()
        if hasattr(self, "sp_spectatorlog_poll"):
            self.cfg.spectatorlog_poll_ms = int(self.sp_spectatorlog_poll.value())
        if hasattr(self, "chk_spectatorlog_file_watch"):
            self.cfg.spectatorlog_file_watch_enabled = bool(self.chk_spectatorlog_file_watch.isChecked())
        if hasattr(self, "sp_spectatorlog_debounce"):
            self.cfg.spectatorlog_debounce_ms = int(self.sp_spectatorlog_debounce.value())
        if hasattr(self, "sp_spectatorlog_backup_poll"):
            self.cfg.spectatorlog_backup_poll_ms = int(self.sp_spectatorlog_backup_poll.value())
        if hasattr(self, "chk_spectatorlog_blackbox_enabled"):
            self.cfg.spectatorlog_blackbox_enabled = bool(self.chk_spectatorlog_blackbox_enabled.isChecked())
        if hasattr(self, "le_spectatorlog_blackbox_dir"):
            self.cfg.spectatorlog_blackbox_dir = str(self.le_spectatorlog_blackbox_dir.text() or "").strip() or "SpectatorLogArchive"
        if hasattr(self, "cmb_spectatorlog_blackbox_mode"):
            self.cfg.spectatorlog_blackbox_mode = str(self.cmb_spectatorlog_blackbox_mode.currentData() or "smart")
        if hasattr(self, "chk_spectator_commentary"):
            self.cfg.spectator_commentary_enabled = bool(self.chk_spectator_commentary.isChecked())
        if hasattr(self, "cmb_spectator_commentary_mode"):
            self.cfg.spectator_commentary_mode = str(self.cmb_spectator_commentary_mode.currentData() or "standard")
        if hasattr(self, "cmb_spectator_commentary_voice"):
            self.cfg.spectator_commentary_voice = str(self.cmb_spectator_commentary_voice.currentData() or "ko-KR-SunHiNeural")
        if hasattr(self, "cmb_spectator_caster_voice"):
            self.cfg.spectator_caster_voice = str(self.cmb_spectator_caster_voice.currentData() or "ko-KR-InJoonNeural")
        if hasattr(self, "sp_spectator_commentary_damage"):
            self.cfg.spectator_commentary_min_damage = float(self.sp_spectator_commentary_damage.value())
        if hasattr(self, "sp_spectator_hit_effect_damage"):
            self.cfg.spectator_hit_effect_damage = float(self.sp_spectator_hit_effect_damage.value())
        if hasattr(self, "cb_spectator_hit_fx_color_preset"):
            self.cfg.spectator_hit_effect_color_preset = str(self.cb_spectator_hit_fx_color_preset.currentData() or "classic")
        if hasattr(self, "le_spectator_hit_fx_color_low"):
            self.cfg.spectator_hit_effect_color_low = _normalize_hex_color(str(self.le_spectator_hit_fx_color_low.text() or "#38bdf8").strip() or "#38bdf8")
        if hasattr(self, "le_spectator_hit_fx_color_mid"):
            self.cfg.spectator_hit_effect_color_mid = _normalize_hex_color(str(self.le_spectator_hit_fx_color_mid.text() or "#fb923c").strip() or "#fb923c")
        if hasattr(self, "le_spectator_hit_fx_color_high"):
            self.cfg.spectator_hit_effect_color_high = _normalize_hex_color(str(self.le_spectator_hit_fx_color_high.text() or "#f87171").strip() or "#f87171")
        if hasattr(self, "le_spectator_hit_fx_color_weak"):
            self.cfg.spectator_hit_effect_color_weak = _normalize_hex_color(str(self.le_spectator_hit_fx_color_weak.text() or "#facc15").strip() or "#facc15")
        if hasattr(self, "le_spectator_hit_fx_color_stun"):
            self.cfg.spectator_hit_effect_color_stun = _normalize_hex_color(str(self.le_spectator_hit_fx_color_stun.text() or "#ef4444").strip() or "#ef4444")
        if hasattr(self, "sp_spectator_hit_fx_duration"):
            self.cfg.spectator_hit_effect_duration_ms = int(self.sp_spectator_hit_fx_duration.value())
            self.cfg.spectator_hit_effect_pop_ms = int(self.sp_spectator_hit_fx_pop.value())
        if hasattr(self, "sp_spectator_hit_fx_base_size"):
            self.cfg.spectator_hit_effect_base_size = int(self.sp_spectator_hit_fx_base_size.value())
        if hasattr(self, "sp_spectator_hit_fx_damage_scale"):
            self.cfg.spectator_hit_effect_damage_scale = float(self.sp_spectator_hit_fx_damage_scale.value())
        if hasattr(self, "sp_spectator_hit_fx_ring_width"):
            self.cfg.spectator_hit_effect_ring_width = int(self.sp_spectator_hit_fx_ring_width.value())
        if hasattr(self, "sp_spectator_hit_fx_opacity"):
            self.cfg.spectator_hit_effect_opacity = float(self.sp_spectator_hit_fx_opacity.value())
        if hasattr(self, "sp_spectator_hit_fx_glow"):
            self.cfg.spectator_hit_effect_glow = float(self.sp_spectator_hit_fx_glow.value())
        if hasattr(self, "sp_spectator_hit_fx_fill_opacity"):
            self.cfg.spectator_hit_effect_fill_opacity = float(self.sp_spectator_hit_fx_fill_opacity.value())
        if hasattr(self, "chk_spectator_hit_fx_show_text"):
            self.cfg.spectator_hit_effect_show_text = bool(self.chk_spectator_hit_fx_show_text.isChecked())
        if hasattr(self, "sp_spectator_hit_fx_text_scale"):
            self.cfg.spectator_hit_effect_text_scale = float(self.sp_spectator_hit_fx_text_scale.value())
        if hasattr(self, "chk_spectator_hit_fx_fast_emit"):
            self.cfg.spectator_hit_effect_fast_emit = bool(self.chk_spectator_hit_fx_fast_emit.isChecked())
        if hasattr(self, "chk_spectator_hit_fx_latency_log"):
            self.cfg.spectator_hit_effect_latency_log = bool(self.chk_spectator_hit_fx_latency_log.isChecked())
        if hasattr(self, "chk_spectator_hit_fx_sprite_enabled"):
            self.cfg.spectator_hit_effect_sprite_enabled = bool(self.chk_spectator_hit_fx_sprite_enabled.isChecked())
        if hasattr(self, "chk_spectator_hit_fx_ring_enabled"):
            self.cfg.spectator_hit_effect_ring_enabled = bool(self.chk_spectator_hit_fx_ring_enabled.isChecked())
        if hasattr(self, "sp_spectator_commentary_cooldown"):
            self.cfg.spectator_commentary_cooldown_sec = float(self.sp_spectator_commentary_cooldown.value())
        if hasattr(self, "sp_spectator_commentary_rate"):
            self.cfg.spectator_commentary_rate = int(self.sp_spectator_commentary_rate.value())
        if hasattr(self, "sp_spectator_commentary_volume"):
            self.cfg.spectator_commentary_volume = float(self.sp_spectator_commentary_volume.value())
        if hasattr(self, "sp_spectator_commentary_pitch"):
            self.cfg.spectator_commentary_pitch = int(self.sp_spectator_commentary_pitch.value())
        if hasattr(self, "sp_spectator_replay_speed"):
            self.cfg.spectator_replay_speed = float(self.sp_spectator_replay_speed.value())
        if hasattr(self, "chk_spectator_replay_real_time"):
            self.cfg.spectator_replay_real_time = bool(self.chk_spectator_replay_real_time.isChecked())
        if hasattr(self, "sp_spectator_recent_text_size"):
            self.cfg.spectator_recent_text_size = int(self.sp_spectator_recent_text_size.value())
        if hasattr(self, "sp_spectator_sfx_rate"):
            self.cfg.spectator_sfx_playback_rate = float(self.sp_spectator_sfx_rate.value())
        if hasattr(self, "le_spectator_stun_sfx"):
            self.cfg.spectator_stun_sfx_path = str(self.le_spectator_stun_sfx.text() or "").strip()
        if hasattr(self, "le_spectator_kd_sfx"):
            self.cfg.spectator_knockdown_sfx_path = str(self.le_spectator_kd_sfx.text() or "").strip()
        if hasattr(self, "le_spectator_tko_sfx"):
            self.cfg.spectator_tko_sfx_path = str(self.le_spectator_tko_sfx.text() or "").strip()
        if hasattr(self, "chk_diagnostics_enabled"):
            self.cfg.diagnostics_enabled = bool(self.chk_diagnostics_enabled.isChecked())
        if hasattr(self, "chk_diagnostics_mask"):
            self.cfg.diagnostics_mask_sensitive = bool(self.chk_diagnostics_mask.isChecked())
        if hasattr(self, "sp_diagnostics_minutes"):
            self.cfg.diagnostics_trace_minutes = int(self.sp_diagnostics_minutes.value())
        if hasattr(self, "sp_diagnostics_raw_lines"):
            self.cfg.diagnostics_raw_sample_lines = int(self.sp_diagnostics_raw_lines.value())
        try:
            DIAG.set_options(
                enabled=bool(getattr(self.cfg, "diagnostics_enabled", True)),
                max_events=max(500, int(getattr(self.cfg, "diagnostics_trace_minutes", 10) or 10) * 500),
                raw_sample_lines=int(getattr(self.cfg, "diagnostics_raw_sample_lines", 120) or 120),
                mask_sensitive=bool(getattr(self.cfg, "diagnostics_mask_sensitive", True)),
            )
        except Exception:
            pass

        if hasattr(self, "sp_b"):
            self.cfg.trigger.target_bgr = (int(self.sp_b.value()), int(self.sp_g.value()), int(self.sp_r.value()))
            self.cfg.trigger.tolerance = int(self.sp_tol.value())
            self.cfg.trigger.window_frames = int(self.sp_win.value())
            self.cfg.trigger.consecutive_needed = min(int(self.sp_need.value()), self.cfg.trigger.window_frames)
            self.cfg.trigger.cooldown_sec = float(self.sp_cd.value())

        if hasattr(self, "chk_koth_enabled"):
            self.cfg.koth_enabled = bool(self.chk_koth_enabled.isChecked())
        if hasattr(self, "sp_koth_min"):
            self.cfg.koth_min_score = int(self.sp_koth_min.value())

        # Palette capture remains available to legacy actions, but its former
        # Legacy palette controls may be absent in log-only builds.
        if hasattr(self, "sp_pal_frames"):
            self.cfg.palette.frames = int(self.sp_pal_frames.value())
        if hasattr(self, "sp_pal_k"):
            self.cfg.palette.k_colors = int(self.sp_pal_k.value())
        if hasattr(self, "sp_mask"):
            self.cfg.palette.mask_thresh = float(self.sp_mask.value()) / 100.0
        if hasattr(self, "chk_capture_players"):
            self.cfg.capture_player_images = bool(self.chk_capture_players.isChecked())
            if hasattr(self, "cmb_portrait_priority"):
                self.cfg.portrait_source_priority = str(self.cmb_portrait_priority.currentData() or "log")

        # timer
        lock_until = float(getattr(self.cfg, "_timer_lock_until", 0.0) or 0.0)
        now_ts = time.time()
        allow_timer_apply = (lock_until <= now_ts) and (now_ts <= float(getattr(self, "_timer_apply_armed_until", 0.0) or 0.0))
        if allow_timer_apply:
            if hasattr(self, "sp_timer_total"):
                total = int(self.sp_timer_total.value())
                current = min(int(self.sp_timer_current.value()), total)
                self.sp_timer_current.setValue(current)
                self.cfg.timer_total_rounds = total
                self.cfg.timer_current_round = current
                self.cfg.timer_round_sec = int(self.sp_timer_round_sec.value())
                self.cfg.timer_rest_sec = int(self.sp_timer_rest_sec.value())
                self.cfg.timer_seconds_left = int(self.sp_timer_left.value())
        if hasattr(self, "chk_rest_30s_tts"):
            self.cfg.timer_rest_30s_tts_enabled = bool(self.chk_rest_30s_tts.isChecked())
        if hasattr(self, "sp_rest_30s_tts_rate"):
            self.cfg.timer_rest_30s_tts_rate = int(self.sp_rest_30s_tts_rate.value())
        if hasattr(self, "sp_action_cooldown"):
            self.cfg.action_cooldown_sec = float(self.sp_action_cooldown.value())
        if hasattr(self, "le_overlay_bg"):
            self.cfg.overlay_bg_color = _normalize_hex_color(str(self.le_overlay_bg.text() or "transparent").strip() or "transparent")
        if hasattr(self, "sl_overlay_opacity"):
            self.cfg.overlay_bg_opacity = float(1.0 - (self.sl_overlay_opacity.value() / 100.0))
        if hasattr(self, "sl_overlay_scale"):
            self.cfg.overlay_ui_scale = float(self.sl_overlay_scale.value()) / 100.0
        if hasattr(self, "sp_overlay_scale"):
            self.cfg.overlay_ui_scale = float(self.sp_overlay_scale.value()) / 100.0
        if hasattr(self, "sp_overlay_timer_font"):
            self.cfg.overlay_timer_font_size = int(self.sp_overlay_timer_font.value())
        if hasattr(self, "sp_overlay_timer_x"):
            self.cfg.overlay_timer_x = int(self.sp_overlay_timer_x.value())
        if hasattr(self, "sp_overlay_timer_y"):
            self.cfg.overlay_timer_y = int(self.sp_overlay_timer_y.value())
        if hasattr(self, "sp_overlay_round_font"):
            self.cfg.overlay_round_font_size = int(self.sp_overlay_round_font.value())
        if hasattr(self, "sp_overlay_round_x"):
            self.cfg.overlay_round_x = int(self.sp_overlay_round_x.value())
        if hasattr(self, "sp_overlay_round_y"):
            self.cfg.overlay_round_y = int(self.sp_overlay_round_y.value())
        if hasattr(self, "cmb_overlay_style_mode"):
            self.cfg.overlay_preset = self._overlay_preset_mode_from_ui()
        if hasattr(self, "le_overlay_vs_bg"):
            self.cfg.overlay_vs_bg_path = str(self.le_overlay_vs_bg.text() or "").strip()
        if hasattr(self, "txt_overlay_vs_bg_map"):
            self.cfg.overlay_vs_bg_by_arena = self._parse_overlay_vs_bg_map()
        if hasattr(self, "sl_overlay_vs_bg_opacity"):
            self.cfg.overlay_vs_bg_opacity = float(self.sl_overlay_vs_bg_opacity.value()) / 100.0
        if hasattr(self, "sp_overlay_vs_hold_sec"):
            self.cfg.overlay_vs_hold_sec = float(self.sp_overlay_vs_hold_sec.value())
        if hasattr(self, "sp_browser_overlay_poll"):
            self.cfg.browser_overlay_poll_ms = int(self.sp_browser_overlay_poll.value())
            try:
                if self.controller and hasattr(self.controller, "_browser_overlay_timer"):
                    self.controller._browser_overlay_timer.setInterval(max(16, min(1000, self.cfg.browser_overlay_poll_ms)))
            except Exception:
                pass
        if hasattr(self, "sp_browser_overlay_scale"):
            self.cfg.browser_overlay_scale = max(0.25, min(4.0, float(self.sp_browser_overlay_scale.value()) / 100.0))
        if hasattr(self, "chk_browser_overlay_output_only"):
            self.cfg.browser_overlay_output_only = bool(self.chk_browser_overlay_output_only.isChecked())
        if hasattr(self, "chk_qml_preview_enabled"):
            self.cfg.qml_preview_enabled = bool(self.chk_qml_preview_enabled.isChecked())
            try:
                if self.controller and getattr(self.controller, "timer_win", None):
                    self.controller.timer_win.set_qml_preview_enabled(self.cfg.qml_preview_enabled)
            except Exception:
                pass
        if hasattr(self, "chk_qml_effects_enabled"):
            self.cfg.qml_effects_enabled = bool(self.chk_qml_effects_enabled.isChecked())
            try:
                if self.controller and getattr(self.controller, "timer_win", None):
                    self.controller.timer_win.set_qml_effects_enabled(self.cfg.qml_effects_enabled)
            except Exception:
                pass
        if hasattr(self, "cmb_overlay_avatar"):
            self.cfg.overlay_player_mask = self._overlay_mask_from_ui()
        if hasattr(self, "chk_overlay_round"):
            self.cfg.overlay_show_round = bool(self.chk_overlay_round.isChecked())
        if hasattr(self, "chk_overlay_time"):
            self.cfg.overlay_show_time = bool(self.chk_overlay_time.isChecked())
        if hasattr(self, "chk_overlay_blue_img"):
            self.cfg.overlay_show_blue_img = bool(self.chk_overlay_blue_img.isChecked())
        if hasattr(self, "chk_overlay_blue_name"):
            self.cfg.overlay_show_blue_name = bool(self.chk_overlay_blue_name.isChecked())
        if hasattr(self, "chk_overlay_red_img"):
            self.cfg.overlay_show_red_img = bool(self.chk_overlay_red_img.isChecked())
        if hasattr(self, "chk_overlay_red_name"):
            self.cfg.overlay_show_red_name = bool(self.chk_overlay_red_name.isChecked())
        if hasattr(self, "chk_overlay_arena_name"):
            self.cfg.overlay_show_arena_name = bool(self.chk_overlay_arena_name.isChecked())
        if hasattr(self, "chk_overlay_flags"):
            self.cfg.overlay_show_flags = bool(self.chk_overlay_flags.isChecked())
        if hasattr(self, "chk_overlay_cinematic"):
            self.cfg.overlay_show_cinematic = bool(self.chk_overlay_cinematic.isChecked())
        if hasattr(self, "_overlay_style_widgets"):
            try:
                self.cfg.overlay_style_round = self._collect_overlay_style("round")
                self.cfg.overlay_style_time = self._collect_overlay_style("time")
                self.cfg.overlay_style_blue_name = self._collect_overlay_style("blue_name")
                self.cfg.overlay_style_red_name = self._collect_overlay_style("red_name")
                self.cfg.overlay_style_arena = self._collect_overlay_style("arena")
                browser_styles = dict(getattr(self.cfg, "browser_text_styles", {}) or {})
                for key in ("time", "total", "dmg", "combo", "recent"):
                    wkey = "browser_" + key
                    if wkey in self._overlay_style_widgets:
                        browser_styles[key] = self._collect_overlay_style(wkey)
                self.cfg.browser_text_styles = _normalize_browser_text_styles(browser_styles)
            except Exception:
                pass
        try:
            if self.controller:
                self.controller.ui_update.emit({
                    "overlay_bg_color": self.cfg.overlay_bg_color,
                    "overlay_bg_opacity": self.cfg.overlay_bg_opacity,
                    "overlay_preset": self.cfg.overlay_preset,
                    "overlay_player_mask": self.cfg.overlay_player_mask,
                    "overlay_show_round": self.cfg.overlay_show_round,
                    "overlay_show_time": self.cfg.overlay_show_time,
                    "overlay_show_blue_img": self.cfg.overlay_show_blue_img,
                    "overlay_show_blue_name": self.cfg.overlay_show_blue_name,
                    "overlay_show_red_img": self.cfg.overlay_show_red_img,
                    "overlay_show_red_name": self.cfg.overlay_show_red_name,
                    "overlay_show_arena_name": self.cfg.overlay_show_arena_name,
                    "overlay_show_flags": self.cfg.overlay_show_flags,
                    "overlay_show_cinematic": self.cfg.overlay_show_cinematic,
                    "browser_overlay_output_only": self.cfg.browser_overlay_output_only,
                    "browser_fullscreen_fx_intensity": self.cfg.browser_fullscreen_fx_intensity,
                    "qml_effects_enabled": self.cfg.qml_effects_enabled,
                    "spectator_recent_text_size": self.cfg.spectator_recent_text_size,
                    "overlay_style": {
                        "round": self.cfg.overlay_style_round,
                        "time": self.cfg.overlay_style_time,
                        "blue_name": self.cfg.overlay_style_blue_name,
                        "red_name": self.cfg.overlay_style_red_name,
                        "arena": self.cfg.overlay_style_arena,
                    },
                    "browser_text_styles": self.cfg.browser_text_styles,
                })
        except Exception:
            pass

        # actions
        if hasattr(self, "lst_actions") and self.lst_actions.currentRow() >= 0:
            self._apply_action_edit()
        self._apply_actions()
        self._apply_pixel_rules()
        if hasattr(self, "tab_effects"):
            self._apply_win_effects_ui(silent=True)

        if self._cfg_path:
            try:
                self.cfg.to_json(self._cfg_path)
            except Exception:
                pass

        if not silent:
            QMessageBox.information(self, "적용", "설정이 적용되었습니다.")

    def closeEvent(self, event):
        # SettingsDialog is installed as a QApplication event filter for
        # quick mouse/keyboard picking.  A later auto-apply closeEvent used to
        # override the original cleanup-only closeEvent, leaving the filter
        # alive after the dialog closed.  Keep both responsibilities here.
        try:
            self.apply_only(silent=True)
        except Exception:
            pass
        try:
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
        except Exception:
            pass
        super().closeEvent(event)

    def save_profile(self):
        self.apply_only(silent=True)
        path, _ = QFileDialog.getSaveFileName(self, "프로필 저장", "profile.json", "JSON (*.json)")
        if not path:
            return
        self.cfg.to_json(path)
        QMessageBox.information(self, "저장 완료", "프로필을 저장했습니다.")

    def load_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "설정 불러오기", "", "JSON (*.json)")
        if not path:
            return
        try:
            loaded_cfg = AppConfig.from_json(path)
            self.cfg.__dict__.update(loaded_cfg.__dict__)
            # Imported profile may contain stale chapter anchor from another user/session.
            self.cfg.chapter_anchor_epoch = 0.0
            QMessageBox.information(self, "불러오기", f"불러오기 완료!\n{path}")
            self._sync_from_config()
            try:
                if self._player_state_apply:
                    self._player_state_apply(self.cfg)
            except Exception:
                pass
            try:
                if self.controller:
                    self.controller.ui_update.emit({
                        "timer_total_rounds": int(getattr(self.cfg, "timer_total_rounds", 3)),
                        "timer_round_sec": int(getattr(self.cfg, "timer_round_sec", 180)),
                        "timer_rest_sec": int(getattr(self.cfg, "timer_rest_sec", 60)),
                        "timer_current_round": int(getattr(self.cfg, "timer_current_round", 1)),
                        "timer_seconds_left": int(getattr(self.cfg, "timer_seconds_left", 180)),
                        "effect_settings": dict(getattr(self.cfg, "win_effects", {}) or {}),
                        "overlay_bg_color": str(getattr(self.cfg, "overlay_bg_color", "transparent") or "transparent"),
                        "overlay_bg_opacity": float(getattr(self.cfg, "overlay_bg_opacity", 0.0) or 0.0),
                        "overlay_player_mask": str(getattr(self.cfg, "overlay_player_mask", "square") or "square"),
                        "overlay_show_round": bool(getattr(self.cfg, "overlay_show_round", True)),
                        "overlay_show_time": bool(getattr(self.cfg, "overlay_show_time", True)),
                        "overlay_show_blue_img": bool(getattr(self.cfg, "overlay_show_blue_img", True)),
                        "overlay_show_blue_name": bool(getattr(self.cfg, "overlay_show_blue_name", True)),
                        "overlay_show_red_img": bool(getattr(self.cfg, "overlay_show_red_img", True)),
                        "overlay_show_red_name": bool(getattr(self.cfg, "overlay_show_red_name", True)),
                        "overlay_show_arena_name": bool(getattr(self.cfg, "overlay_show_arena_name", True)),
                        "overlay_show_flags": bool(getattr(self.cfg, "overlay_show_flags", True)),
                        "overlay_show_cinematic": bool(getattr(self.cfg, "overlay_show_cinematic", True)),
                        "overlay_style": {
                            "round": getattr(self.cfg, "overlay_style_round", _default_overlay_style_round()),
                            "time": getattr(self.cfg, "overlay_style_time", _default_overlay_style_time()),
                            "blue_name": getattr(self.cfg, "overlay_style_blue_name", _default_overlay_style_blue_name()),
                            "red_name": getattr(self.cfg, "overlay_style_red_name", _default_overlay_style_red_name()),
                            "arena": getattr(self.cfg, "overlay_style_arena", _default_overlay_style_arena()),
                        },
                        "overlay_ui_scale": float(getattr(self.cfg, "overlay_ui_scale", 1.0) or 1.0),
                        "overlay_layout": dict(getattr(self.cfg, "layout", {}) or {}),
                    })
            except Exception:
                pass
            try:
                if self._timer_win and hasattr(self._timer_win, "set_broadcast_sync_active"):
                    self._timer_win.set_broadcast_sync_active(float(getattr(self.cfg, "chapter_anchor_epoch", 0.0) or 0.0) > 0.0)
            except Exception:
                pass
        except Exception as e:
            QMessageBox.warning(self, "불러오기 실패", f"설정 파일을 열 수 없습니다.\n{e}")

    def _sync_from_config(self):
        self._suspend_apply = True
        self._refresh_monitors()
        if hasattr(self, "cmb_monitor"):
            idx = max(0, self.cmb_monitor.findData(self.cfg.monitor_index))
            self.cmb_monitor.setCurrentIndex(idx)
        if hasattr(self, "edit_roi_hotkey"):
            self.edit_roi_hotkey.setKeySequence(QKeySequence(self.cfg.roi_hotkey))
        if hasattr(self, "edit_pixel_hotkey"):
            self.edit_pixel_hotkey.setKeySequence(QKeySequence(self.cfg.pixel_hotkey))
        if hasattr(self, "edit_detect_hotkey"):
            self.edit_detect_hotkey.setKeySequence(QKeySequence(self.cfg.detect_hotkey))
        if hasattr(self, "edit_trigger_pixel_hotkey"):
            self.edit_trigger_pixel_hotkey.setKeySequence(QKeySequence(self.cfg.trigger_pixel_hotkey))
        if hasattr(self, "edit_action_pick_hotkey"):
            self.edit_action_pick_hotkey.setKeySequence(QKeySequence(self.cfg.action_pick_hotkey))
        if hasattr(self, "edit_action_test_hotkey"):
            self.edit_action_test_hotkey.setKeySequence(QKeySequence(self.cfg.action_test_hotkey))
        if hasattr(self, "le_rest_text_color"):
            try:
                rest_color = (getattr(self.cfg, "overlay_style_time", {}) or {}).get("rest_text_color", "#ff5a5a")
                self.le_rest_text_color.setText(str(rest_color))
            except Exception:
                pass

        self._update_quick_labels()
        self._refresh_action_pick_labels()
        if hasattr(self, "lbl_left_player"):
            self.lbl_left_player.setText(self._roi_text(self.cfg.roi_left_player))
        if hasattr(self, "lbl_right_player"):
            self.lbl_right_player.setText(self._roi_text(self.cfg.roi_right_player))
        if hasattr(self, "chk_koth_enabled"):
            self.chk_koth_enabled.setChecked(bool(getattr(self.cfg, "koth_enabled", False)))
        if hasattr(self, "sp_koth_min"):
            self.sp_koth_min.setValue(int(getattr(self.cfg, "koth_min_score", 75) or 75))
        if hasattr(self, "_refresh_koth_setup_state"):
            self._refresh_koth_setup_state()

        if hasattr(self, "sp_b"):
            self.sp_b.setValue(int(self.cfg.trigger.target_bgr[0]))
            self.sp_g.setValue(int(self.cfg.trigger.target_bgr[1]))
            self.sp_r.setValue(int(self.cfg.trigger.target_bgr[2]))
            self.sp_tol.setValue(int(self.cfg.trigger.tolerance))
            self.sp_win.setValue(int(self.cfg.trigger.window_frames))
            self.sp_need.setValue(int(self.cfg.trigger.consecutive_needed))
            self.sp_cd.setValue(int(self.cfg.trigger.cooldown_sec))
            self._refresh_trigger_color_ui()

        if hasattr(self, "chk_koth_enabled"):
            self.chk_koth_enabled.setChecked(bool(getattr(self.cfg, "koth_enabled", False)))
        if hasattr(self, "sp_koth_min"):
            self.sp_koth_min.setValue(int(getattr(self.cfg, "koth_min_score", 75) or 75))

        if hasattr(self, "sp_pal_frames"):
            self.sp_pal_frames.setValue(int(self.cfg.palette.frames))
        if hasattr(self, "sp_pal_k"):
            self.sp_pal_k.setValue(int(self.cfg.palette.k_colors))
        if hasattr(self, "sp_mask"):
            self.sp_mask.setValue(int(self.cfg.palette.mask_thresh * 100))
        if hasattr(self, "chk_capture_players"):
            self.chk_capture_players.setChecked(bool(getattr(self.cfg, "capture_player_images", True)))
        if hasattr(self, "cmb_portrait_priority"):
            try:
                self.cmb_portrait_priority.setCurrentIndex(1 if str(getattr(self.cfg, "portrait_source_priority", "log") or "log").lower() == "profile" else 0)
            except Exception:
                self.cmb_portrait_priority.setCurrentIndex(0)
        if hasattr(self, "sp_timer_total"):
            self.sp_timer_total.setValue(int(self.cfg.timer_total_rounds))
        if hasattr(self, "sp_timer_current"):
            self.sp_timer_current.setValue(int(self.cfg.timer_current_round))
        if hasattr(self, "sp_timer_round_sec"):
            self.sp_timer_round_sec.setValue(int(self.cfg.timer_round_sec))
        if hasattr(self, "sp_timer_rest_sec"):
            self.sp_timer_rest_sec.setValue(int(self.cfg.timer_rest_sec))
        if hasattr(self, "sp_timer_left"):
            self.sp_timer_left.setValue(int(self.cfg.timer_seconds_left))
        if hasattr(self, "chk_rest_30s_tts"):
            self.chk_rest_30s_tts.setChecked(bool(getattr(self.cfg, "timer_rest_30s_tts_enabled", True)))
        if hasattr(self, "sp_rest_30s_tts_rate"):
            self.sp_rest_30s_tts_rate.setValue(int(getattr(self.cfg, "timer_rest_30s_tts_rate", 200)))
        if hasattr(self, "sp_chapter_offset"):
            self.sp_chapter_offset.setValue(int(getattr(self.cfg, "chapter_offset_sec", 0)))
        if hasattr(self, "sp_chapter_dedupe"):
            self.sp_chapter_dedupe.setValue(int(getattr(self.cfg, "chapter_dedupe_sec", 20)))
        if hasattr(self, "le_chapter_dir"):
            self.le_chapter_dir.setText(str(getattr(self.cfg, "chapter_output_dir", "") or ""))
        if hasattr(self, "chk_chapter_nickname_only"):
            self.chk_chapter_nickname_only.setChecked(bool(getattr(self.cfg, "chapter_nickname_only", False)))
        if hasattr(self, "chk_chapter_hide_time"):
            self.chk_chapter_hide_time.setChecked(bool(getattr(self.cfg, "chapter_hide_time", False)))
        if hasattr(self, "chk_spectatorlog_enabled"):
            self.chk_spectatorlog_enabled.setChecked(bool(getattr(self.cfg, "spectatorlog_enabled", False)))
        if hasattr(self, "chk_spectatorlog_sync_players"):
            self.chk_spectatorlog_sync_players.setChecked(bool(getattr(self.cfg, "spectatorlog_sync_players", True)))
        if hasattr(self, "chk_spectatorlog_sync_timer"):
            self.chk_spectatorlog_sync_timer.setChecked(bool(getattr(self.cfg, "spectatorlog_sync_timer", False)))
        if hasattr(self, "chk_spectator_lobby_auto_start"):
            self.chk_spectator_lobby_auto_start.setChecked(
                bool(getattr(self.cfg, "spectator_lobby_auto_start_enabled", False))
            )
            self.le_spectator_lobby_auto_start_title.setText(
                str(getattr(self.cfg, "spectator_lobby_auto_start_target_title", "") or "")
            )
            self.sp_spectator_lobby_auto_start_x.setValue(
                int(getattr(self.cfg, "spectator_lobby_auto_start_client_x", 0) or 0)
            )
            self.sp_spectator_lobby_auto_start_y.setValue(
                int(getattr(self.cfg, "spectator_lobby_auto_start_client_y", 0) or 0)
            )
            self.sp_spectator_lobby_auto_start_click_count.setValue(
                int(getattr(self.cfg, "spectator_lobby_auto_start_click_count", 1) or 1)
            )
            self.sp_spectator_lobby_auto_start_delay.setValue(
                int(getattr(self.cfg, "spectator_lobby_auto_start_delay_ms", 300) or 300)
            )
            self.chk_spectator_lobby_auto_start_activate.setChecked(
                bool(getattr(self.cfg, "spectator_lobby_auto_start_activate", True))
            )
            self.chk_spectator_lobby_auto_start_restore_focus.setChecked(
                bool(getattr(self.cfg, "spectator_lobby_auto_start_restore_focus", True))
            )
            self.chk_spectator_lobby_auto_start_restore_cursor.setChecked(
                bool(getattr(self.cfg, "spectator_lobby_auto_start_restore_cursor", True))
            )
            self.chk_spectator_lobby_auto_start_minimize_target.setChecked(
                bool(getattr(self.cfg, "spectator_lobby_auto_start_minimize_target", False))
            )
        if hasattr(self, "le_spectatorlog_path"):
            self.le_spectatorlog_path.setText(str(getattr(self.cfg, "spectatorlog_path", "") or ""))
        if hasattr(self, "sp_spectatorlog_poll"):
            self.sp_spectatorlog_poll.setValue(int(getattr(self.cfg, "spectatorlog_poll_ms", 250) or 250))
        if hasattr(self, "chk_spectatorlog_file_watch"):
            self.chk_spectatorlog_file_watch.setChecked(bool(getattr(self.cfg, "spectatorlog_file_watch_enabled", True)))
        if hasattr(self, "sp_spectatorlog_debounce"):
            self.sp_spectatorlog_debounce.setValue(int(getattr(self.cfg, "spectatorlog_debounce_ms", 35) or 35))
        if hasattr(self, "sp_spectatorlog_backup_poll"):
            self.sp_spectatorlog_backup_poll.setValue(int(getattr(self.cfg, "spectatorlog_backup_poll_ms", 1500) or 1500))
        if hasattr(self, "chk_spectatorlog_blackbox_enabled"):
            self.chk_spectatorlog_blackbox_enabled.setChecked(bool(getattr(self.cfg, "spectatorlog_blackbox_enabled", False)))
        if hasattr(self, "le_spectatorlog_blackbox_dir"):
            self.le_spectatorlog_blackbox_dir.setText(str(getattr(self.cfg, "spectatorlog_blackbox_dir", "SpectatorLogArchive") or "SpectatorLogArchive"))
        if hasattr(self, "cmb_spectatorlog_blackbox_mode"):
            idx = self.cmb_spectatorlog_blackbox_mode.findData(str(getattr(self.cfg, "spectatorlog_blackbox_mode", "smart") or "smart"))
            self.cmb_spectatorlog_blackbox_mode.setCurrentIndex(idx if idx >= 0 else 1)
        if hasattr(self, "chk_spectator_commentary"):
            self.chk_spectator_commentary.setChecked(bool(getattr(self.cfg, "spectator_commentary_enabled", False)))
        if hasattr(self, "cmb_spectator_commentary_mode"):
            idx = self.cmb_spectator_commentary_mode.findData(str(getattr(self.cfg, "spectator_commentary_mode", "standard") or "standard"))
            self.cmb_spectator_commentary_mode.setCurrentIndex(idx if idx >= 0 else 1)
        if hasattr(self, "cmb_spectator_commentary_voice"):
            idx = self.cmb_spectator_commentary_voice.findData(str(getattr(self.cfg, "spectator_commentary_voice", "ko-KR-SunHiNeural") or "ko-KR-SunHiNeural"))
            self.cmb_spectator_commentary_voice.setCurrentIndex(idx if idx >= 0 else 0)
        if hasattr(self, "cmb_spectator_caster_voice"):
            idx = self.cmb_spectator_caster_voice.findData(str(getattr(self.cfg, "spectator_caster_voice", "ko-KR-InJoonNeural") or "ko-KR-InJoonNeural"))
            self.cmb_spectator_caster_voice.setCurrentIndex(idx if idx >= 0 else 1)
        if hasattr(self, "sp_spectator_commentary_damage"):
            self.sp_spectator_commentary_damage.setValue(float(getattr(self.cfg, "spectator_commentary_min_damage", 25.0) or 25.0))
        if hasattr(self, "sp_spectator_hit_effect_damage"):
            self.sp_spectator_hit_effect_damage.setValue(float(getattr(self.cfg, "spectator_hit_effect_damage", 45.0) or 45.0))
        if hasattr(self, "cb_spectator_hit_fx_color_preset"):
            _fx_preset = str(getattr(self.cfg, "spectator_hit_effect_color_preset", "classic") or "classic").strip().lower()
            _fx_idx = self.cb_spectator_hit_fx_color_preset.findData(_fx_preset)
            self.cb_spectator_hit_fx_color_preset.setCurrentIndex(_fx_idx if _fx_idx >= 0 else 0)
        if hasattr(self, "le_spectator_hit_fx_color_low"):
            self.le_spectator_hit_fx_color_low.setText(str(getattr(self.cfg, "spectator_hit_effect_color_low", "#38bdf8") or "#38bdf8"))
            if hasattr(self, "btn_spectator_hit_fx_color_low"):
                self._set_hit_fx_color_button(self.btn_spectator_hit_fx_color_low, self.le_spectator_hit_fx_color_low.text())
        if hasattr(self, "le_spectator_hit_fx_color_mid"):
            self.le_spectator_hit_fx_color_mid.setText(str(getattr(self.cfg, "spectator_hit_effect_color_mid", "#fb923c") or "#fb923c"))
            if hasattr(self, "btn_spectator_hit_fx_color_mid"):
                self._set_hit_fx_color_button(self.btn_spectator_hit_fx_color_mid, self.le_spectator_hit_fx_color_mid.text())
        if hasattr(self, "le_spectator_hit_fx_color_high"):
            self.le_spectator_hit_fx_color_high.setText(str(getattr(self.cfg, "spectator_hit_effect_color_high", "#f87171") or "#f87171"))
            if hasattr(self, "btn_spectator_hit_fx_color_high"):
                self._set_hit_fx_color_button(self.btn_spectator_hit_fx_color_high, self.le_spectator_hit_fx_color_high.text())
        if hasattr(self, "le_spectator_hit_fx_color_weak"):
            self.le_spectator_hit_fx_color_weak.setText(str(getattr(self.cfg, "spectator_hit_effect_color_weak", "#facc15") or "#facc15"))
            if hasattr(self, "btn_spectator_hit_fx_color_weak"):
                self._set_hit_fx_color_button(self.btn_spectator_hit_fx_color_weak, self.le_spectator_hit_fx_color_weak.text())
        if hasattr(self, "le_spectator_hit_fx_color_stun"):
            self.le_spectator_hit_fx_color_stun.setText(str(getattr(self.cfg, "spectator_hit_effect_color_stun", "#ef4444") or "#ef4444"))
            if hasattr(self, "btn_spectator_hit_fx_color_stun"):
                self._set_hit_fx_color_button(self.btn_spectator_hit_fx_color_stun, self.le_spectator_hit_fx_color_stun.text())
        if hasattr(self, "sp_spectator_hit_fx_duration"):
            self.sp_spectator_hit_fx_duration.setValue(int(getattr(self.cfg, "spectator_hit_effect_duration_ms", 170) or 170))
            self.sp_spectator_hit_fx_pop.setValue(int(getattr(self.cfg, "spectator_hit_effect_pop_ms", 58) or 58))
        if hasattr(self, "sp_spectator_hit_fx_base_size"):
            self.sp_spectator_hit_fx_base_size.setValue(int(getattr(self.cfg, "spectator_hit_effect_base_size", 86) or 86))
        if hasattr(self, "sp_spectator_hit_fx_damage_scale"):
            self.sp_spectator_hit_fx_damage_scale.setValue(float(getattr(self.cfg, "spectator_hit_effect_damage_scale", 0.42) or 0.42))
        if hasattr(self, "sp_spectator_hit_fx_ring_width"):
            self.sp_spectator_hit_fx_ring_width.setValue(int(getattr(self.cfg, "spectator_hit_effect_ring_width", 4) or 4))
        if hasattr(self, "sp_spectator_hit_fx_opacity"):
            self.sp_spectator_hit_fx_opacity.setValue(float(getattr(self.cfg, "spectator_hit_effect_opacity", 1.0) or 1.0))
        if hasattr(self, "sp_spectator_hit_fx_glow"):
            self.sp_spectator_hit_fx_glow.setValue(float(getattr(self.cfg, "spectator_hit_effect_glow", 1.0) or 1.0))
        if hasattr(self, "sp_spectator_hit_fx_fill_opacity"):
            self.sp_spectator_hit_fx_fill_opacity.setValue(float(getattr(self.cfg, "spectator_hit_effect_fill_opacity", 1.0) or 1.0))
        if hasattr(self, "chk_spectator_hit_fx_show_text"):
            self.chk_spectator_hit_fx_show_text.setChecked(bool(getattr(self.cfg, "spectator_hit_effect_show_text", True)))
        if hasattr(self, "sp_spectator_hit_fx_text_scale"):
            self.sp_spectator_hit_fx_text_scale.setValue(float(getattr(self.cfg, "spectator_hit_effect_text_scale", 1.0) or 1.0))
        if hasattr(self, "chk_spectator_hit_fx_fast_emit"):
            self.chk_spectator_hit_fx_fast_emit.setChecked(bool(getattr(self.cfg, "spectator_hit_effect_fast_emit", True)))
        if hasattr(self, "chk_spectator_hit_fx_latency_log"):
            self.chk_spectator_hit_fx_latency_log.setChecked(bool(getattr(self.cfg, "spectator_hit_effect_latency_log", True)))
        if hasattr(self, "chk_spectator_hit_fx_sprite_enabled"):
            self.chk_spectator_hit_fx_sprite_enabled.setChecked(bool(getattr(self.cfg, "spectator_hit_effect_sprite_enabled", True)))
        if hasattr(self, "chk_spectator_hit_fx_ring_enabled"):
            self.chk_spectator_hit_fx_ring_enabled.setChecked(bool(getattr(self.cfg, "spectator_hit_effect_ring_enabled", False)))
        if hasattr(self, "sp_spectator_commentary_cooldown"):
            self.sp_spectator_commentary_cooldown.setValue(
                max(0.0, float(getattr(self.cfg, "spectator_commentary_cooldown_sec", 6.0)))
            )
        if hasattr(self, "sp_spectator_commentary_rate"):
            self.sp_spectator_commentary_rate.setValue(int(getattr(self.cfg, "spectator_commentary_rate", 200) or 200))
        if hasattr(self, "sp_spectator_commentary_volume"):
            self.sp_spectator_commentary_volume.setValue(float(getattr(self.cfg, "spectator_commentary_volume", 100.0) or 100.0))
        if hasattr(self, "sp_spectator_commentary_pitch"):
            self.sp_spectator_commentary_pitch.setValue(int(getattr(self.cfg, "spectator_commentary_pitch", 0) or 0))
        if hasattr(self, "sp_spectator_replay_speed"):
            self.sp_spectator_replay_speed.setValue(float(getattr(self.cfg, "spectator_replay_speed", 1.0) or 1.0))
        if hasattr(self, "chk_spectator_replay_real_time"):
            self.chk_spectator_replay_real_time.setChecked(bool(getattr(self.cfg, "spectator_replay_real_time", False)))
        if hasattr(self, "sp_spectator_recent_text_size"):
            self.sp_spectator_recent_text_size.setValue(int(getattr(self.cfg, "spectator_recent_text_size", 23) or 23))
        if hasattr(self, "sp_spectator_sfx_rate"):
            self.sp_spectator_sfx_rate.setValue(float(getattr(self.cfg, "spectator_sfx_playback_rate", 1.0) or 1.0))
        if hasattr(self, "le_spectator_stun_sfx"):
            self.le_spectator_stun_sfx.setText(str(getattr(self.cfg, "spectator_stun_sfx_path", "") or ""))
        if hasattr(self, "le_spectator_kd_sfx"):
            self.le_spectator_kd_sfx.setText(str(getattr(self.cfg, "spectator_knockdown_sfx_path", "") or ""))
        if hasattr(self, "le_spectator_tko_sfx"):
            self.le_spectator_tko_sfx.setText(str(getattr(self.cfg, "spectator_tko_sfx_path", "") or ""))
        if hasattr(self, "_refresh_spectatorlog_state"):
            self._refresh_spectatorlog_state()
        self._refresh_chapter_status_label()
        if hasattr(self, "le_overlay_bg"):
            self.le_overlay_bg.setText(str(self.cfg.overlay_bg_color))
        if hasattr(self, "sl_overlay_opacity"):
            self.sl_overlay_opacity.setValue(int((1.0 - float(getattr(self.cfg, "overlay_bg_opacity", 0.0))) * 100))
        if hasattr(self, "sl_overlay_scale"):
            self.sl_overlay_scale.setValue(int(float(getattr(self.cfg, "overlay_ui_scale", 1.0) or 1.0) * 100))
        if hasattr(self, "sp_overlay_scale"):
            self.sp_overlay_scale.setValue(int(float(getattr(self.cfg, "overlay_ui_scale", 1.0) or 1.0) * 100))
        if hasattr(self, "sp_overlay_timer_font"):
            self.sp_overlay_timer_font.setValue(int(getattr(self.cfg, "overlay_timer_font_size", 54) or 54))
        if hasattr(self, "sp_overlay_timer_x"):
            self.sp_overlay_timer_x.setValue(int(getattr(self.cfg, "overlay_timer_x", 0) or 0))
        if hasattr(self, "sp_overlay_timer_y"):
            self.sp_overlay_timer_y.setValue(int(getattr(self.cfg, "overlay_timer_y", 0) or 0))
        if hasattr(self, "sp_overlay_round_font"):
            self.sp_overlay_round_font.setValue(int(getattr(self.cfg, "overlay_round_font_size", 11) or 11))
        if hasattr(self, "sp_overlay_round_x"):
            self.sp_overlay_round_x.setValue(int(getattr(self.cfg, "overlay_round_x", 0) or 0))
        if hasattr(self, "sp_overlay_round_y"):
            self.sp_overlay_round_y.setValue(int(getattr(self.cfg, "overlay_round_y", 0) or 0))
        if hasattr(self, "cmb_overlay_style_mode"):
            mode = str(getattr(self.cfg, "overlay_preset", "classic") or "classic").strip().lower()
            idx = self.cmb_overlay_style_mode.findData(mode if mode in ("classic", "tekken8") else "classic")
            self.cmb_overlay_style_mode.setCurrentIndex(idx if idx >= 0 else 0)
        if hasattr(self, "cmb_overlay_avatar"):
            mask = _normalize_player_mask(getattr(self.cfg, "overlay_player_mask", "square"))
            if mask == "circle":
                self.cmb_overlay_avatar.setCurrentText("원형")
            elif mask == "hex":
                self.cmb_overlay_avatar.setCurrentText("원형")
            else:
                self.cmb_overlay_avatar.setCurrentText("육각형")
        if hasattr(self, "chk_overlay_round"):
            self.chk_overlay_round.setChecked(bool(getattr(self.cfg, "overlay_show_round", True)))
        if hasattr(self, "chk_overlay_time"):
            self.chk_overlay_time.setChecked(bool(getattr(self.cfg, "overlay_show_time", True)))
        if hasattr(self, "chk_overlay_blue_img"):
            self.chk_overlay_blue_img.setChecked(bool(getattr(self.cfg, "overlay_show_blue_img", True)))
        if hasattr(self, "chk_overlay_blue_name"):
            self.chk_overlay_blue_name.setChecked(bool(getattr(self.cfg, "overlay_show_blue_name", True)))
        if hasattr(self, "chk_overlay_red_img"):
            self.chk_overlay_red_img.setChecked(bool(getattr(self.cfg, "overlay_show_red_img", True)))
        if hasattr(self, "chk_overlay_red_name"):
            self.chk_overlay_red_name.setChecked(bool(getattr(self.cfg, "overlay_show_red_name", True)))
        if hasattr(self, "chk_overlay_arena_name"):
            self.chk_overlay_arena_name.setChecked(bool(getattr(self.cfg, "overlay_show_arena_name", True)))
        if hasattr(self, "chk_overlay_flags"):
            self.chk_overlay_flags.setChecked(bool(getattr(self.cfg, "overlay_show_flags", True)))
        if hasattr(self, "chk_overlay_cinematic"):
            self.chk_overlay_cinematic.setChecked(bool(getattr(self.cfg, "overlay_show_cinematic", True)))
        if hasattr(self, "le_overlay_vs_bg"):
            self.le_overlay_vs_bg.setText(str(getattr(self.cfg, "overlay_vs_bg_path", "") or ""))
        if hasattr(self, "sl_overlay_vs_bg_opacity"):
            self.sl_overlay_vs_bg_opacity.setValue(int(max(0.0, min(1.0, float(getattr(self.cfg, "overlay_vs_bg_opacity", 1.0) or 1.0))) * 100))
        if hasattr(self, "sp_overlay_vs_hold_sec"):
            self.sp_overlay_vs_hold_sec.setValue(max(0.5, min(15.0, float(getattr(self.cfg, "overlay_vs_hold_sec", 2.85) or 2.85))))
        if hasattr(self, "sp_browser_overlay_scale"):
            self.sp_browser_overlay_scale.setValue(int(float(getattr(self.cfg, "browser_overlay_scale", 1.0) or 1.0) * 100))
        if hasattr(self, "sp_browser_overlay_poll"):
            self.sp_browser_overlay_poll.setValue(max(16, min(1000, int(getattr(self.cfg, "browser_overlay_poll_ms", 50) or 50))))
        if hasattr(self, "chk_browser_overlay_output_only"):
            self.chk_browser_overlay_output_only.setChecked(bool(getattr(self.cfg, "browser_overlay_output_only", True)))
        if hasattr(self, "sp_browser_fullscreen_fx_intensity"):
            self.sp_browser_fullscreen_fx_intensity.setValue(int(max(0.0, min(3.0, float(getattr(self.cfg, "browser_fullscreen_fx_intensity", 1.6) or 1.6))) * 100))
        if hasattr(self, "chk_qml_preview_enabled"):
            self.chk_qml_preview_enabled.setChecked(bool(getattr(self.cfg, "qml_preview_enabled", True)))
        if hasattr(self, "chk_qml_effects_enabled"):
            self.chk_qml_effects_enabled.setChecked(bool(getattr(self.cfg, "qml_effects_enabled", False)))
        if hasattr(self, "le_browser_overlay_url"):
            browser_url = "http://127.0.0.1:17872/overlay"
            try:
                if self.controller and hasattr(self.controller, "browser_overlay"):
                    browser_url = str(self.controller.browser_overlay.url)
            except Exception:
                pass
            self.le_browser_overlay_url.setText(browser_url)
        if hasattr(self, "lbl_browser_overlay_status"):
            is_browser_running = bool(self.controller and getattr(self.controller, "browser_overlay", None))
            self.lbl_browser_overlay_status.setText("실행 중" if is_browser_running else "대기")
            self.lbl_browser_overlay_status.setStyleSheet("color:#0f766e;font-weight:700;" if is_browser_running else "color:#64748b;")
        if hasattr(self, "txt_overlay_vs_bg_map"):
            self.txt_overlay_vs_bg_map.setPlainText(self._format_overlay_vs_bg_map(getattr(self.cfg, "overlay_vs_bg_by_arena", {}) or {}))
        if hasattr(self, "_overlay_style_widgets"):
            for key in ("round", "time", "blue_name", "red_name", "arena", "browser_time", "browser_total", "browser_dmg", "browser_combo", "browser_recent"):
                style = self._overlay_style_for_key(key)
                w = self._overlay_style_widgets.get(key, {})
                if not w:
                    continue
                w["bg_color"].setText(str(style.get("bg_color", "#000000")))
                w["bg_opacity"].setValue(int(float(style.get("bg_opacity", 1.0)) * 100))
                w["border_color"].setText(str(style.get("border_color", "#000000")))
                w["border_opacity"].setValue(int(float(style.get("border_opacity", 1.0)) * 100))
                w["border_width"].setValue(int(style.get("border_width", 1)))
                w["text_color"].setText(str(style.get("text_color", "#ffffff")))
                w["text_opacity"].setValue(int(float(style.get("text_opacity", 1.0)) * 100))
                try:
                    from PyQt6.QtGui import QFont
                    w["font_family"].setCurrentFont(QFont(str(style.get("font_family", ""))))
                except Exception:
                    pass
                w["font_size"].setValue(int(style.get("font_size", 0)))
                w["font_bold"].setChecked(bool(style.get("font_bold", False)))
                w["font_weight"].setValue(int(style.get("font_weight", 700)))
                if "badge_enabled" in w:
                    w["badge_enabled"].setChecked(bool(style.get("badge_enabled", True)))
                    w["badge_color"].setText(str(style.get("badge_color", "#3b82f6" if key == "blue_name" else "#ef4444")))
                    w["badge_width"].setValue(int(style.get("badge_width", 10)))
                    w["badge_height"].setValue(int(style.get("badge_height", 14)))
        if hasattr(self, "sp_action_cooldown"):
            self.sp_action_cooldown.setValue(float(getattr(self.cfg, "action_cooldown_sec", 5.0)))
        if hasattr(self, "tab_effects"):
            self._load_win_effects_ui(self.cfg.win_effects)
        # legacy JSON editor removed

        if hasattr(self, "_reload_players_cards"):
            self._reload_players_cards()

        if hasattr(self, "_render_pixel_cards"):
            self._pixel_rules = list(self.cfg.pixel_rules or [])
            self._render_pixel_cards()


        if hasattr(self, "_actions_by_event"):
            self._actions_by_event = dict(self.cfg.actions or {})
            self._action_cooldowns_by_event = dict(self.cfg.action_cooldowns or {})
            self._action_edge_triggers_by_event = dict(getattr(self.cfg, "action_edge_triggers", {}) or {})
            self._normalize_action_aliases()
            self._normalize_action_cooldown_aliases()
            self._normalize_action_edge_aliases()
            self._refresh_action_events()
            self._load_actions_for_event(self.cmb_action_event.currentText())
            if hasattr(self, "_action_summary_labels"):
                for key in list(self._action_summary_labels.keys()):
                    try:
                        self._update_action_summary_label(key)
                    except Exception:
                        pass
        self._refresh_overlay_custom_list()
        self._suspend_apply = False


# -----------------------------
# App Wiring
# -----------------------------
class MainApp(QObject):
    _log_stop_finished = pyqtSignal()
    _lobby_auto_start_result = pyqtSignal(bool, str)
    _update_metadata_ready = pyqtSignal(dict, bool)
    _update_error_ready = pyqtSignal(str, bool)
    _update_download_ready = pyqtSignal(str)

    def __init__(self, cfg_path: str):
        super().__init__()
        self._update_metadata_ready.connect(self._handle_update_metadata)
        self._log_stop_finished.connect(self._finish_log_detector_stop)
        self._lobby_auto_start_result.connect(self._handle_lobby_auto_start_result)
        self._update_error_ready.connect(self._finish_update_check_error)
        self._update_download_ready.connect(self._confirm_apply_update)
        self.cfg_path = cfg_path
        self.cfg = AppConfig.from_json(cfg_path)
        try:
            DIAG.set_options(
                enabled=bool(getattr(self.cfg, "diagnostics_enabled", True)),
                max_events=max(500, int(getattr(self.cfg, "diagnostics_trace_minutes", 10) or 10) * 500),
                raw_sample_lines=int(getattr(self.cfg, "diagnostics_raw_sample_lines", 120) or 120),
                mask_sensitive=bool(getattr(self.cfg, "diagnostics_mask_sensitive", True)),
            )
            DIAG.record("app_start", app_version=APP_VERSION, cfg_path=cfg_path)
        except Exception:
            pass
        # Chapter anchor is session-scoped runtime state.
        # Reset stale persisted anchor on app start to avoid forced ON state.
        try:
            if float(getattr(self.cfg, "chapter_anchor_epoch", 0.0) or 0.0) > 0.0:
                self.cfg.chapter_anchor_epoch = 0.0
                self.cfg.to_json(self.cfg_path)
        except Exception:
            pass
        self._action_last_run: Dict[str, float] = {}
        self._lobby_auto_start_lock = threading.Lock()
        self._lobby_auto_start_last_at = 0.0

        self.timer_win = QmlTimerWindow(self.cfg, self.cfg_path)
        try:
            self.timer_win.check_updates.connect(self.check_for_updates)
        except Exception:
            pass
        self.timer_win.set_qml_preview_enabled(bool(getattr(self.cfg, "qml_preview_enabled", True)))
        self.browser_overlay = BrowserOverlayServer(17872, no_update=_NO_UPDATE, path_resolver=normalize_app_path)
        self.browser_overlay.start()
        self.browser_overlay_sync = BrowserOverlaySync(
            self.cfg,
            self.timer_win,
            self.browser_overlay,
            self._sync_browser_overlay_player_assets,
        )
        self._browser_sp_ratio = {"blue": 1.0, "red": 1.0}
        self._browser_sp_last_damage = {"blue": 0.0, "red": 0.0}
        self._browser_sp_recovery_delay = {"blue": 0.0, "red": 0.0}
        self._browser_sp_last_fight_seconds = None
        self._browser_sp_last_rest_seconds = None
        self._browser_round_knockdowns = {"blue": 0, "red": 0}
        self._browser_knockdown_round_key = None
        self._browser_overlay_timer = QTimer()
        self._browser_overlay_timer.setInterval(max(16, min(1000, int(getattr(self.cfg, "browser_overlay_poll_ms", 50) or 50))))
        self._browser_overlay_timer.timeout.connect(self.browser_overlay_sync.publish)
        self._browser_overlay_timer.start()
        self._push_initial_browser_overlay_settings()
        self.timer_win.set_broadcast_sync_active(float(getattr(self.cfg, "chapter_anchor_epoch", 0.0) or 0.0) > 0.0)
        self.timer_win.set_timer_settings(
            self.cfg.timer_total_rounds,
            self.cfg.timer_round_sec,
            self.cfg.timer_rest_sec,
            self.cfg.timer_current_round,
            self.cfg.timer_seconds_left,
        )
        self.timer_win.set_effect_settings(self.cfg.win_effects)
        self.timer_win.set_overlay_bg_color(self.cfg.overlay_bg_color)
        self.timer_win.set_overlay_bg_opacity(self.cfg.overlay_bg_opacity)
        self.timer_win.set_overlay_window_opacity(getattr(self.cfg, "overlay_window_opacity", 1.0))
        try:
            self.timer_win._backend.overlayResetRequested.connect(self._on_timer_reset_cleanup)
        except Exception:
            pass
        self.settings_dlg: Optional[SettingsDialog] = None
        self._prev_roi_key = False
        self._prev_pixel_key = False
        self._prev_detect_key = False
        self._prev_trigger_pixel_key = False
        self._prev_action_pick_key = False
        self._prev_action_test_key = False
        self._prev_esc = False
        self._quick_pick_active = False
        self._quick_roi_overlay: Optional[QuickRoiOverlay] = None
        self._pixel_pick_overlay: Optional[PixelPickOverlay] = None
        self._trigger_pixel_overlay: Optional[PixelPickOverlay] = None
        self._quick_roi_monitor: Optional[int] = None
        self._quick_roi_virtual_offset: Optional[Tuple[int, int]] = None
        self._hotkey_cache: Dict[str, Optional[Tuple[int, dict]]] = {}
        self._action_queue = deque()
        self._action_busy = False
        self._action_timer = QTimer()
        self._action_timer.setSingleShot(True)
        self._action_timer.timeout.connect(self._drain_action_queue)
        self._hotkey_timer = QTimer()
        self._hotkey_timer.timeout.connect(self._poll_hotkeys)
        self._vk_map = build_vk_map()
        self._global_hotkeys = GlobalHotkeys()
        self._global_hotkeys_enabled = True
        self._hotkey_last_fired: Dict[str, float] = {}
        self._current_blue_id = ""
        self._current_red_id = ""
        self._current_blue_registered = False
        self._current_red_registered = False
        self._current_blue_valid = False
        self._current_red_valid = False
        self._chapter_fallback_anchor_epoch = time.time()
        self._chapter_events: List[dict] = []
        self._chapter_last_title = ""
        self._chapter_last_elapsed = -999999
        self._chapter_seen_keys = set()
        self._chapter_session_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._chapter_jsonl_path = ""
        self._chapter_txt_path = ""
        self._chapter_autosave_timer = QTimer()
        self._chapter_autosave_timer.setInterval(5000)
        self._chapter_autosave_timer.timeout.connect(self._chapter_autosave_tick)
        self._burst_audio_out = QAudioOutput() if HAS_QTMULTIMEDIA and QAudioOutput else None
        self._burst_player = QMediaPlayer() if HAS_QTMULTIMEDIA and QMediaPlayer else None
        if self._burst_player is not None and self._burst_audio_out is not None:
            try:
                self._burst_player.setAudioOutput(self._burst_audio_out)
            except Exception:
                pass
        self._commentary_audio_outs: Dict[str, Any] = {}
        self._commentary_players: Dict[str, Any] = {}
        self._commentary_tts_files: Dict[str, List[str]] = {"analyst": [], "caster": []}
        self._commentary_tts_busy: Dict[str, bool] = {"analyst": False, "caster": False}
        self._commentary_followup_epoch: Dict[str, int] = {"analyst": 0, "caster": 0}
        self._commentary_tts_cache_dir = os.path.join(tempfile.gettempdir(), "timerauto_tts_cache")
        self._commentary_tts_cache_lock = threading.Lock()
        try:
            os.makedirs(self._commentary_tts_cache_dir, exist_ok=True)
        except Exception:
            pass
        if HAS_QTMULTIMEDIA and QMediaPlayer and QAudioOutput:
            for role in ("analyst", "caster"):
                try:
                    audio_out = QAudioOutput()
                    player = QMediaPlayer()
                    player.setAudioOutput(audio_out)
                    audio_out.setVolume(1.0)
                    player.mediaStatusChanged.connect(lambda status, r=role: self._on_commentary_media_status(r, status))
                    self._commentary_audio_outs[role] = audio_out
                    self._commentary_players[role] = player
                except Exception:
                    pass

        self.controller = Controller(self.cfg)
        self.watcher = ScreenWatcher(self.cfg)
        self.spectator_watcher = _make_spectator_log_watcher(self.cfg)
        self._log_detector_transition = False
        self._log_detector_stopping = False
        self.action_runner = ActionRunner(self.controller, self.timer_win, self.timer_win.set_status)
        QTimer.singleShot(1800, self._prewarm_commentary_tts_cache)
        try:
            self.watcher.stop()
        except Exception:
            pass
        try:
            self.spectator_watcher.stop()
        except Exception:
            pass
        self._update_backend_detect_flags()

        self.timer_win.open_settings.connect(self.open_settings)
        self.watcher.trigger_fired.connect(self.on_trigger)
        self.watcher.pixel_fired.connect(self.on_pixel_rule)
        self.timer_win._backend.start_detection_requested.connect(self._start_log_detector)
        self.timer_win._backend.start_screen_detection_requested.connect(self._toggle_screen_detector)
        self.timer_win._backend.toggle_pixel_detection_requested.connect(self._toggle_pixel_detector)
        self.timer_win._backend.toggle_log_detection_requested.connect(self._toggle_log_detector)
        self.timer_win._backend.select_player_requested.connect(self._select_player_from_overlay)
        self.timer_win._backend.overlayVisibilityRequested.connect(self._on_overlay_visibility_request)
        self.timer_win._backend.overlayUiScaleChanged.connect(self._on_overlay_ui_scale_changed)
        self.timer_win._backend.overlayBgColorChanged.connect(self._on_overlay_bg_changed)
        self.timer_win._backend.overlayUiBgOpacityChanged.connect(self._on_overlay_ui_bg_opacity_changed)
        self.timer_win._backend.overlayWindowOpacityChanged.connect(self._on_overlay_window_opacity_changed)
        self.timer_win._backend.trigger_test_requested.connect(self._test_trigger_once)
        self.timer_win._backend.profileRegisterRequested.connect(self._open_overlay_profile_register)
        self.timer_win._backend.profileEditRequested.connect(self._open_overlay_profile_edit)
        self.timer_win._backend.burstSfxRequested.connect(self._play_burst_sfx)
        self.timer_win._backend.failSfxRequested.connect(self._play_burst_sfx)
        self.timer_win._backend.chapterSyncNowRequested.connect(self._sync_chapter_anchor_now)
        self.timer_win._backend.chapterClearRequested.connect(self._clear_chapter_anchor)
        self.timer_win._backend.chapterExportRequested.connect(self._on_chapter_export_requested)
        self.timer_win._backend.hudDemoStopRequested.connect(self._stop_spectator_hud_demo)
        self.timer_win._backend.spectatorReplayRequested.connect(self._start_spectator_replay_from_overlay)
        self.timer_win._backend.spectatorFullDemoRequested.connect(self._start_spectator_full_demo_from_overlay)
        self.timer_win._backend.spectatorVsIntroTestRequested.connect(self._start_spectator_vs_intro_from_overlay)
        self.timer_win._backend.stunFlashRequested.connect(lambda side: self._push_browser_overlay_event("stun", side=str(side or "")))
        self.timer_win._backend.spectatorEffectRequested.connect(lambda side, kind: self._push_browser_overlay_event(str(kind or "effect"), side=str(side or "")))
        self.timer_win._backend.hitImpactRequested.connect(lambda side, damage: self._push_browser_overlay_event("hit", side=str(side or ""), damage=float(damage or 0.0)))
        self.timer_win._backend.vsIntroResetRequested.connect(lambda: self._push_browser_overlay_event("vs"))
        self.timer_win._backend.restThirtySecondsReached.connect(self._on_rest_thirty_seconds)

        self.controller.ui_update.connect(self.apply_ui_update)
        self.controller.status_update.connect(self.timer_win.set_status)
        self.spectator_watcher.ui_update.connect(self.apply_ui_update)
        self.spectator_watcher.status_update.connect(self.timer_win.set_status)
        self._apply_saved_player_state()

        self.timer_win._backend.runningChanged.connect(self._on_timer_running)
        self._hotkey_timer.start(30)
        self._chapter_autosave_timer.start()
        self._apply_global_hotkeys()

        self.timer_win.set_status("대기 중")

    def _play_burst_sfx(self, path: str):
        raw = str(path or "").strip()
        if not raw:
            try:
                self.timer_win.set_status("효과음 경로가 비어있음")
            except Exception:
                pass
            return
        try:
            if os.path.isabs(raw):
                resolved = os.path.abspath(raw)
            else:
                resolved = os.path.abspath(os.path.join(get_app_base_dir(), raw))
        except Exception:
            resolved = raw
        if not os.path.isfile(resolved):
            logging.warning("SFX file missing: %s (from %s)", resolved, raw)
            try:
                self.timer_win.set_status("효과음 파일 없음")
            except Exception:
                pass
            return
        ext = str(resolved).lower().strip()
        if ext.endswith(".wav"):
            ok = _play_win_effect_sfx(resolved)
            if ok:
                return
        elif ext.endswith(".mp3"):
            ok = _play_media_sfx(self._burst_player, self._burst_audio_out, resolved)
            if ok:
                return
        try:
            self.timer_win.set_status("플래시 효과음 실패: WAV/MP3 파일 필요")
        except Exception:
            pass

    def _spectator_sfx_path(self, kind: str) -> str:
        kind = str(kind or "").lower().strip()
        if kind == "stun":
            return str(getattr(self.cfg, "spectator_stun_sfx_path", "") or "").strip()
        if kind == "tko":
            return str(getattr(self.cfg, "spectator_tko_sfx_path", "") or "").strip()
        return str(getattr(self.cfg, "spectator_knockdown_sfx_path", "") or "").strip()

    def _play_spectator_sfx(self, kind: str):
        raw = self._spectator_sfx_path(kind)
        if not raw:
            return
        try:
            playback_rate = float(getattr(self.cfg, "spectator_sfx_playback_rate", 1.0) or 1.0)
        except Exception:
            playback_rate = 1.0
        try:
            expanded = os.path.expanduser(raw)
            resolved = os.path.abspath(expanded if os.path.isabs(expanded) else os.path.join(get_app_base_dir(), expanded))
        except Exception:
            resolved = raw
        if not os.path.isfile(resolved):
            logging.warning("Spectator SFX file missing: %s (from %s)", resolved, raw)
            return
        ext = str(resolved).lower().strip()
        ok = False
        if kind == "stun" and ext.endswith(".wav") and abs(playback_rate - 1.0) < 0.001:
            ok = _play_win_effect_sfx(resolved)
        if ext.endswith((".wav", ".mp3")):
            ok = ok or _play_media_sfx(self._burst_player, self._burst_audio_out, resolved, playback_rate=playback_rate)
        if not ok and ext.endswith(".wav"):
            ok = _play_win_effect_sfx(resolved)
        if not ok:
            try:
                self.timer_win.set_status("Spectator 효과음 실패: WAV/MP3 파일 필요")
            except Exception:
                pass

    def _split_commentary_tts_sentences(self, text: str) -> List[str]:
        text = re.sub(r"\s+", " ", str(text or "").strip())
        if not text:
            return []
        parts = [p.strip() for p in re.split(r"(?<=[.!?。！？])\s+", text) if p.strip()]
        if len(parts) <= 1:
            # Korean TTS summaries often use sentence-like spacing without Western punctuation.
            tmp = re.sub(r"(습니다|입니다|네요|군요|죠|요|다)([.。]?)\s+", r"\1\2|", text)
            parts = [p.strip() for p in tmp.split("|") if p.strip()]
        out: List[str] = []
        for p in parts or [text]:
            p = p.strip()
            if not p:
                continue
            if len(p) <= 110:
                out.append(p)
                continue
            # Fallback split for very long sentence-like chunks.
            chunk = ""
            for seg in re.split(r"(,|，| 그리고 | 하지만 | 반면 | 다만 )", p):
                if not seg:
                    continue
                nxt = (chunk + seg).strip()
                if len(nxt) >= 80 and chunk:
                    out.append(chunk.strip(" ,，"))
                    chunk = seg.strip()
                else:
                    chunk = nxt
            if chunk.strip():
                out.append(chunk.strip(" ,，"))
        return out[:8]

    def _estimate_commentary_sentence_ms(self, text: str) -> int:
        # Conservative Korean TTS length estimate. Only used to space queued recap sentences.
        n = len(str(text or ""))
        return int(max(1100, min(5200, 650 + n * 72)))

    def _schedule_commentary_round_summary_tts(self, text: str, role: str = "analyst", delay_ms: int = 0):
        text = re.sub(r"\s+", " ", str(text or "").strip())
        if not text:
            return
        role = "caster" if str(role or "").lower() == "caster" else "analyst"
        try:
            epoch = getattr(self, "_commentary_followup_epoch", None)
            if isinstance(epoch, dict):
                # Cancel older summary followups, but do not stop current media here.
                epoch[role] = int(epoch.get(role, 0) or 0) + 1
        except Exception:
            pass
        # Round-break recaps should sound like one analyst paragraph, not a
        # list of separate sentence clips.  Keep the busy/retry behavior, but
        # pass the full recap as one TTS item.
        self._schedule_commentary_followup_tts(text, role, delay_ms=max(0, int(delay_ms or 0)), retries=10)
        logging.info("COMMENTARY_TTS_ROUND_SUMMARY_QUEUE role=%s mode=single delay_ms=%s chars=%s", role, delay_ms, len(text))

    def _schedule_commentary_followup_tts(self, text: str, role: str = "analyst", delay_ms: int = 2400, retries: int = 5):
        text = str(text or "").strip()
        if not text:
            return
        role = "caster" if str(role or "").lower() == "caster" else "analyst"
        try:
            token = int((getattr(self, "_commentary_followup_epoch", {}) or {}).get(role, 0) or 0)
        except Exception:
            token = 0

        def _attempt(remaining: int):
            try:
                try:
                    current_token = int((getattr(self, "_commentary_followup_epoch", {}) or {}).get(role, 0) or 0)
                except Exception:
                    current_token = 0
                if current_token != token:
                    logging.info("COMMENTARY_TTS_FOLLOWUP_CANCELLED role=%s text=%s", role, text)
                    return
                busy = getattr(self, "_commentary_tts_busy", {}) or {}
                # 캐스터와 해설자는 하나의 방송 음성 채널을 공유한다.
                if any(bool(value) for value in busy.values()):
                    if remaining > 0:
                        QTimer.singleShot(900, lambda r=remaining - 1: _attempt(r))
                    else:
                        logging.info("COMMENTARY_TTS_FOLLOWUP_SKIP_BUSY role=%s text=%s", role, text)
                    return
                self._speak_commentary_tts(text, role)
            except Exception:
                logging.exception("COMMENTARY_TTS_FOLLOWUP_FAIL")

        QTimer.singleShot(max(0, min(15000, int(delay_ms or 2400))), lambda: _attempt(max(0, int(retries or 0))))

    def _speak_commentary_tts(self, text: str, role: str = "analyst", rate_override: Optional[int] = None, pitch_override: Optional[int] = None):
        text = str(text or "").strip()
        if not text:
            return
        role = "caster" if str(role or "").lower() == "caster" else "analyst"
        busy = getattr(self, "_commentary_tts_busy", {}) or {}
        if any(bool(value) for value in busy.values()):
            logging.info("COMMENTARY_TTS_SKIP_CHANNEL_BUSY role=%s text=%s", role, text)
            return
        if str(role or "").lower() == "caster":
            voice = str(getattr(self.cfg, "spectator_caster_voice", "ko-KR-InJoonNeural") or "ko-KR-InJoonNeural")
        else:
            voice = str(getattr(self.cfg, "spectator_commentary_voice", "ko-KR-SunHiNeural") or "ko-KR-SunHiNeural")
        try:
            rate = int(getattr(self.cfg, "spectator_commentary_rate", 200) or 200)
        except Exception:
            rate = 200
        if rate_override is not None:
            try:
                rate = max(80, min(320, int(rate_override)))
            except Exception:
                rate = 200
        try:
            volume = float(getattr(self.cfg, "spectator_commentary_volume", 100.0) or 100.0)
        except Exception:
            volume = 100.0
        try:
            pitch = int(getattr(self.cfg, "spectator_commentary_pitch", 0) or 0)
        except Exception:
            pitch = 0
        if pitch_override is not None:
            try:
                pitch = max(-100, min(100, int(pitch_override)))
            except Exception:
                pitch = 0
        player = self._commentary_players.get(role)
        audio_out = self._commentary_audio_outs.get(role)
        if not HAS_QTMULTIMEDIA or player is None or audio_out is None:
            self.action_runner.speak_text(text, rate=rate, volume=volume, voice_mode=voice)
            return
        self._commentary_tts_busy[role] = True
        cached_path = self._commentary_tts_cache_path(text, role, voice, rate, volume, pitch)
        if cached_path and os.path.isfile(cached_path) and os.path.getsize(cached_path) > 0:
            QMetaObject.invokeMethod(
                self,
                "_play_commentary_tts_file",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, role),
                Q_ARG(str, cached_path),
            )
            return

        request_started_at = time.time()
        def _worker():
            media_path = ""
            try:
                if not self.action_runner._ensure_tts_ready():
                    logging.warning("COMMENTARY_TTS_EDGE_UNAVAILABLE")
                    QMetaObject.invokeMethod(
                        self,
                        "_clear_commentary_tts_busy",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, role),
                    )
                    return
                media_path = cached_path or tempfile.mktemp(prefix="timerauto_commentary_", suffix=".mp3")
                ok = self.action_runner._edge_save_cli(
                    text,
                    media_path,
                    voice,
                    self.action_runner._edge_rate(rate),
                    self.action_runner._edge_volume(volume),
                    self.action_runner._edge_pitch(pitch),
                )
                if not ok:
                    try:
                        os.remove(media_path)
                    except Exception:
                        pass
                    logging.warning("COMMENTARY_TTS_SAVE_FAIL text=%s", text)
                    QMetaObject.invokeMethod(
                        self,
                        "_clear_commentary_tts_busy",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, role),
                    )
                    return
                try:
                    elapsed_gen = time.time() - float(request_started_at or time.time())
                    urgent = bool(re.search(r"다운|쓰러|녹아웃|TKO|케이오|시작|종료|휴식|위험", text, re.IGNORECASE))
                    if elapsed_gen > 3.2 and not urgent:
                        logging.info("COMMENTARY_TTS_DROP_STALE role=%s elapsed=%.2f text=%s", role, elapsed_gen, text)
                        QMetaObject.invokeMethod(
                            self,
                            "_clear_commentary_tts_busy",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, role),
                        )
                        return
                except Exception:
                    pass
                QMetaObject.invokeMethod(
                    self,
                    "_play_commentary_tts_file",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, role),
                    Q_ARG(str, media_path),
                )
            except Exception as e:
                if media_path:
                    try:
                        os.remove(media_path)
                    except Exception:
                        pass
                logging.warning("COMMENTARY_TTS_FAIL err=%s", e)
                QMetaObject.invokeMethod(
                    self,
                    "_clear_commentary_tts_busy",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, role),
                )

        threading.Thread(target=_worker, daemon=True).start()

    def _commentary_tts_cache_path(self, text: str, role: str, voice: str, rate: int, volume: float, pitch: int) -> str:
        try:
            blob = json.dumps(
                {
                    "text": str(text or ""),
                    "role": str(role or ""),
                    "voice": str(voice or ""),
                    "rate": int(rate),
                    "volume": round(float(volume), 1),
                    "pitch": int(pitch),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            name = hashlib.sha1(blob.encode("utf-8")).hexdigest() + ".mp3"
            return os.path.join(self._commentary_tts_cache_dir, name)
        except Exception:
            return ""

    def _prewarm_commentary_tts_cache(self):
        try:
            if not bool(getattr(self.cfg, "spectator_commentary_enabled", False)):
                return
            if not self.action_runner._ensure_tts_ready():
                return
            analyst_voice = str(getattr(self.cfg, "spectator_commentary_voice", "ko-KR-SunHiNeural") or "ko-KR-SunHiNeural")
            caster_voice = str(getattr(self.cfg, "spectator_caster_voice", "ko-KR-InJoonNeural") or "ko-KR-InJoonNeural")
            rate = int(getattr(self.cfg, "spectator_commentary_rate", 200) or 200)
            volume = float(getattr(self.cfg, "spectator_commentary_volume", 100.0) or 100.0)
            pitch = int(getattr(self.cfg, "spectator_commentary_pitch", 0) or 0)
            jobs = []
            analyst_lines = (
                "둘 다 먼저 가긴 싫죠.",
                "서로 오라고만 합니다.",
                "눈치 싸움 길어집니다.",
                "아직 간만 봅니다.",
                "앞손이 오늘 바쁩니다.",
                "잽 출근률 높습니다.",
                "작은 잽도 귀찮습니다.",
                "폼은 멋졌습니다.",
                "공기는 맞았습니다.",
                "방금은 안 맞았습니다.",
                "이러면 피곤합니다.",
                "수비가 바빠집니다.",
                "팔은 많이 나갔습니다.",
                "운동량은 확실합니다.",
                "카운터가 정확하게 들어갑니다.",
                "받아치는 타이밍이 좋았습니다.",
                "반격이 정확했습니다.",
                "들어오는 순간 받아쳤습니다.",
                "상대 진입을 잘 읽었습니다.",
                "좋은 반응이었습니다.",
                "무리한 진입을 바로 받아칩니다.",
                "상대 움직임을 읽고 정타를 만듭니다.",
                "좋은 콤비네이션이었습니다.",
                "연타가 이어집니다.",
                "첫 타 이후 연결이 좋았습니다.",
                "수비가 따라가지 못했습니다.",
                "짧은 교전에서 연결이 깔끔했습니다.",
                "한 번 열리자 후속타가 이어졌습니다.",
                "공격 흐름이 끊기지 않습니다.",
                "정타가 연속으로 들어갑니다.",
                "잽 타이밍이 좋았습니다.",
                "앞손이 정확하게 들어갑니다.",
                "직선 타격이 정확하게 들어갑니다.",
                "수비가 늦었습니다.",
                "큰 타격이 들어갑니다.",
                "데미지가 큽니다.",
                "한 방 한 방의 데미지가 큽니다.",
                "강하게 들어갔습니다.",
                "정타를 만들어냅니다.",
                "한 방의 충격이 큽니다.",
                "턱 쪽 충격이 컸습니다.",
                "턱에 정확하게 들어갔습니다.",
                "바디에 제대로 들어갔습니다.",
                "바디 충격이 큽니다.",
                "관자놀이 쪽 충격이 큽니다.",
                "머리 쪽 데미지가 큽니다.",
                "얼굴 쪽 정타를 허용합니다.",
                "얼굴 쪽 데미지가 쌓입니다.",
                "압박이 계속됩니다.",
                "데미지가 쌓이고 있습니다.",
                "체력 부담이 커지고 있습니다.",
                "위험 구간에 들어갑니다.",
                "회복할 시간이 필요합니다.",
                "데미지 부담이 상당히 커졌습니다.",
                "짧은 시간에 데미지가 크게 쌓였습니다.",
                "공격 주도권을 잡고 있습니다.",
                "수비 부담이 커지고 있습니다.",
                "정타 허용이 많아지고 있습니다.",
                "턱 쪽 정타가 반복되고 있습니다.",
                "바디 데미지가 쌓이고 있습니다.",
                "머리 쪽 충격이 쌓입니다.",
                "얼굴 쪽 데미지가 계속 쌓입니다.",
                "다운 장면이 라운드 흐름을 크게 바꿨습니다.",
                "크게 흔들리는 장면이 있었습니다.",
                "바디 데미지가 쌓인 라운드였습니다.",
                "후반에는 압박이 살아나면서 분위기가 바뀌었습니다.",
                "이번 라운드는 서로 정타를 주고받은 라운드였습니다.",
                "다음 라운드는 정타 허용을 줄이는 게 중요합니다.",
                "지금은 회복 시간을 어떻게 쓰느냐가 중요합니다.",
                "정타가 잠시 끊긴 만큼, 호흡을 다시 잡는 구간입니다.",
                "데미지 부담이 있는 쪽은 무리한 진입을 피해야 합니다.",
                "잠깐의 소강상태지만, 체력 회복에는 중요한 시간입니다.",
                "이 구간은 거리 조절이 중요합니다.",
                "무리하게 들어가면 카운터 위험이 있습니다.",
                "서로 먼저 실수하지 않으려는 흐름입니다.",
                "지금은 첫 진입보다 이후 수비 반응이 중요합니다.",
            )
            caster_lines = (
                "잠시 소강상태입니다.",
                "서로 타이밍을 봅니다.",
                "아직 아무도 안 들어갑니다.",
                "거리 싸움이 이어집니다.",
                "눈치게임입니다.",
                "서로 간만 봅니다.",
                "잠깐 멈췄습니다.",
                "라운드 막판입니다.",
                "마지막 교전이 중요합니다.",
                "막판입니다, 한 방 조심해야 합니다.",
                "경기 시작합니다!",
                "1라운드 시작합니다",
                "2라운드 시작합니다",
                "마지막 라운드, 3라운드 시작합니다",
                "1라운드 종료, 휴식 시간입니다",
                "2라운드 종료, 휴식 시간입니다",
                "마지막 라운드 종료, 경기 결과를 기다립니다",
                "크게 흔들립니다!",
                "위험합니다!",
                "충격이 큽니다!",
                "다운 당합니다!",
                "쓰러집니다!",
                "테크니컬 녹아웃입니다!",
                "심판이 경기를 멈춥니다!",
                "경기가 끝납니다!",
                "잠시 소강상태입니다.",
                "서로 거리를 재고 있습니다.",
                "두 선수, 다시 타이밍을 보고 있습니다.",
                "정타가 잠시 끊겼습니다.",
                "다음 진입 타이밍을 보고 있습니다.",
                "중앙을 두고 다시 기회를 봅니다.",
                "서로 쉽게 들어가지 않습니다.",
                "큰 교전 전의 짧은 소강상태입니다.",
                "라운드 막판입니다, 마지막 교전이 중요합니다.",
                "남은 시간이 많지 않습니다.",
                "막판 한 번의 정타가 인상에 남을 수 있습니다.",
                "마지막 진입 타이밍을 보고 있습니다.",
            )
            for text in analyst_lines:
                jobs.append(("analyst", analyst_voice, text))
            for text in caster_lines:
                jobs.append(("caster", caster_voice, text))
            # 현재 SpectatorLog에 선수명이 이미 잡혀 있으면 큰 사건 이름 포함 멘트도 미리 캐시한다.
            try:
                root = resolve_spectatorlog_path(str(getattr(self.cfg, "spectatorlog_path", "") or ""))
                current_names = []
                for side in ("blue", "red"):
                    try:
                        name_path = os.path.join(root, side, "name.txt")
                        raw_name = open(name_path, "r", encoding="utf-8-sig", errors="ignore").read().strip()
                    except Exception:
                        raw_name = ""
                    raw_name = re.split(r"[\s\.,_#@\-]+", str(raw_name or "").strip(), maxsplit=1)[0].strip()
                    raw_name = re.sub(r"[^0-9A-Za-z가-힣]+", "", raw_name).strip()
                    if raw_name and len(raw_name) > 3 and not re.search(r"\d", raw_name):
                        current_names.append(raw_name)
                for name in list(dict.fromkeys(current_names))[:2]:
                    for tail in ("크게 흔들립니다!", "위험합니다!", "다운 당합니다!", "쓰러집니다!", "테크니컬 녹아웃입니다!"):
                        jobs.append(("caster", caster_voice, f"{name}, {tail}"))
            except Exception:
                pass

            def _worker():
                warmed = 0
                skipped = 0
                failed = 0
                # Console-safe prewarm: Edge TTS/network failures can otherwise spam the console
                # for every candidate line at startup. Stop after a few failures and let normal
                # on-demand caching handle the rest. Existing cache files are still used instantly.
                max_failures = 3
                max_jobs = 16
                for role, voice, text in list(jobs)[:max_jobs]:
                    try:
                        path = self._commentary_tts_cache_path(text, role, voice, rate, volume, pitch)
                        if path and os.path.isfile(path) and os.path.getsize(path) > 0:
                            skipped += 1
                            continue
                        ok = self.action_runner._edge_save_cli(
                            text,
                            path,
                            voice,
                            self.action_runner._edge_rate(rate),
                            self.action_runner._edge_volume(volume),
                            self.action_runner._edge_pitch(pitch),
                        )
                        if ok:
                            warmed += 1
                            failed = 0
                        else:
                            failed += 1
                            if failed >= max_failures:
                                logging.warning("COMMENTARY_TTS_PREWARM_STOP failed=%s warmed=%s skipped=%s", failed, warmed, skipped)
                                break
                    except Exception as e:
                        failed += 1
                        if failed >= max_failures:
                            logging.warning("COMMENTARY_TTS_PREWARM_STOP err=%s warmed=%s skipped=%s", e, warmed, skipped)
                            break
                logging.info("COMMENTARY_TTS_PREWARM_DONE warmed=%s skipped=%s failed=%s jobs=%s", warmed, skipped, failed, min(len(jobs), max_jobs))

            threading.Thread(target=_worker, daemon=True).start()
        except Exception as e:
            logging.warning("COMMENTARY_TTS_PREWARM_FAIL err=%s", e)

    @pyqtSlot(str, str)
    def _play_commentary_tts_file(self, role: str, media_path: str):
        try:
            role = "caster" if str(role or "").lower() == "caster" else "analyst"
            path = os.path.abspath(str(media_path or ""))
            if not os.path.isfile(path):
                return
            player = self._commentary_players.get(role)
            audio_out = self._commentary_audio_outs.get(role)
            if player is None or audio_out is None:
                self._commentary_tts_busy[role] = False
                return
            self._commentary_tts_files.setdefault(role, []).append(path)
            player.setSource(QUrl.fromLocalFile(path))
            try:
                volume = float(getattr(self.cfg, "spectator_commentary_volume", 100.0) or 100.0)
            except Exception:
                volume = 100.0
            audio_out.setVolume(max(0.0, min(1.0, volume / 100.0)))
            player.play()
            logging.info("COMMENTARY_TTS_QT_PLAY role=%s path=%s", role, path)
        except Exception as e:
            logging.warning("COMMENTARY_TTS_QT_PLAY_FAIL err=%s", e)
            try:
                self._commentary_tts_busy[role] = False
            except Exception:
                pass

    def _on_commentary_media_status(self, role: str, status):
        try:
            role = "caster" if str(role or "").lower() == "caster" else "analyst"
            if QMediaPlayer is None:
                return
            if status in (
                QMediaPlayer.MediaStatus.EndOfMedia,
                QMediaPlayer.MediaStatus.InvalidMedia,
                QMediaPlayer.MediaStatus.NoMedia,
            ):
                old = list((getattr(self, "_commentary_tts_files", {}) or {}).get(role, []) or [])
                self._commentary_tts_files[role] = []
                for path in old:
                    try:
                        cache_dir = os.path.abspath(str(getattr(self, "_commentary_tts_cache_dir", "") or ""))
                        path_abs = os.path.abspath(str(path or ""))
                        if cache_dir and os.path.dirname(path_abs) == cache_dir:
                            continue
                        os.remove(path_abs)
                    except Exception:
                        pass
                self._commentary_tts_busy[role] = False
        except Exception:
            pass

    def _stop_commentary_tts_role(self, role: str, reason: str = ""):
        try:
            role = "caster" if str(role or "").lower() == "caster" else "analyst"
            try:
                epoch = getattr(self, "_commentary_followup_epoch", None)
                if isinstance(epoch, dict):
                    epoch[role] = int(epoch.get(role, 0) or 0) + 1
            except Exception:
                pass
            # Round-start and new-match boundaries are hard broadcast cuts.
            # Keeping the analyst clip alive here caused rest/final recaps to
            # overlap the next round or the next bout.
            keep_current_sentence = False
            player = (getattr(self, "_commentary_players", {}) or {}).get(role)
            if player is not None and not keep_current_sentence:
                try:
                    player.stop()
                except Exception:
                    pass
            old = [] if keep_current_sentence else list((getattr(self, "_commentary_tts_files", {}) or {}).get(role, []) or [])
            if not keep_current_sentence:
                try:
                    self._commentary_tts_files[role] = []
                except Exception:
                    pass
            cache_dir = os.path.abspath(str(getattr(self, "_commentary_tts_cache_dir", "") or ""))
            for path in old:
                try:
                    path_abs = os.path.abspath(str(path or ""))
                    if cache_dir and os.path.dirname(path_abs) == cache_dir:
                        continue
                    os.remove(path_abs)
                except Exception:
                    pass
            if not keep_current_sentence:
                try:
                    self._commentary_tts_busy[role] = False
                except Exception:
                    pass
            logging.info("COMMENTARY_TTS_STOP role=%s reason=%s keep_current=%s", role, reason, keep_current_sentence)
        except Exception:
            logging.exception("COMMENTARY_TTS_STOP_FAIL")

    @pyqtSlot(str)
    def _clear_commentary_tts_busy(self, role: str):
        try:
            role = "caster" if str(role or "").lower() == "caster" else "analyst"
            self._commentary_tts_busy[role] = False
        except Exception:
            pass

    def _chapter_anchor_epoch(self) -> float:
        anchor = float(getattr(self.cfg, "chapter_anchor_epoch", 0.0) or 0.0)
        if anchor > 0:
            return anchor
        return float(self._chapter_fallback_anchor_epoch)

    def _chapter_anchor_status(self) -> str:
        anchor = float(getattr(self.cfg, "chapter_anchor_epoch", 0.0) or 0.0)
        if anchor > 0:
            base = datetime.fromtimestamp(anchor).strftime("%Y-%m-%d %H:%M:%S")
        else:
            base = f"미설정(앱 기준: {datetime.fromtimestamp(self._chapter_fallback_anchor_epoch).strftime('%Y-%m-%d %H:%M:%S')})"
        return f"{base} | 보정 {int(getattr(self.cfg, 'chapter_offset_sec', 0)):+d}s"

    def _chapter_log_dir(self) -> str:
        base_dir = os.path.dirname(os.path.abspath(self.cfg_path)) if self.cfg_path else get_app_base_dir()
        configured = str(getattr(self.cfg, "chapter_output_dir", "") or "").strip()
        if configured:
            if os.path.isabs(configured):
                out = configured
            else:
                out = os.path.abspath(os.path.join(base_dir, configured))
        else:
            out = os.path.join(base_dir, "logs")
        try:
            os.makedirs(out, exist_ok=True)
        except Exception:
            out = get_app_base_dir()
        return out

    def _reset_chapter_session(self, clear_events: bool = True):
        if clear_events:
            self._chapter_events = []
            self._chapter_last_title = ""
            self._chapter_last_elapsed = -999999
            self._chapter_seen_keys = set()
        self._chapter_session_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._chapter_jsonl_path = ""
        self._chapter_txt_path = ""

    def _sync_chapter_anchor_now(self):
        self.cfg.chapter_anchor_epoch = float(time.time())
        self._reset_chapter_session(clear_events=True)
        try:
            self.cfg.to_json(self.cfg_path)
        except Exception:
            pass
        try:
            self.timer_win.set_status("방송 시작 기준 시각 동기화 완료")
        except Exception:
            pass
        try:
            self.timer_win.set_broadcast_sync_active(True)
        except Exception:
            pass
        try:
            if self.settings_dlg and hasattr(self.settings_dlg, "_refresh_chapter_status_label"):
                self.settings_dlg._refresh_chapter_status_label()
        except Exception:
            pass

    def _clear_chapter_anchor(self):
        self.cfg.chapter_anchor_epoch = 0.0
        self._chapter_fallback_anchor_epoch = time.time()
        self._reset_chapter_session(clear_events=True)
        try:
            self.cfg.to_json(self.cfg_path)
        except Exception:
            pass
        try:
            self.timer_win.set_status("방송 기준 시각 해제(앱 기준으로 전환)")
        except Exception:
            pass
        try:
            self.timer_win.set_broadcast_sync_active(False)
        except Exception:
            pass
        try:
            if self.settings_dlg and hasattr(self.settings_dlg, "_refresh_chapter_status_label"):
                self.settings_dlg._refresh_chapter_status_label()
        except Exception:
            pass

    def _on_chapter_export_requested(self):
        path = ""
        try:
            path = str(self._export_chapter_txt() or "")
        except Exception:
            path = ""
        try:
            if path:
                self.timer_win.set_status(f"챕터 저장 완료: {os.path.basename(path)}")
            else:
                self.timer_win.set_status("저장할 챕터가 없습니다.")
        except Exception:
            pass

    def _open_chapter_txt(self) -> str:
        path = str(getattr(self, "_chapter_txt_path", "") or "")
        if not path or not os.path.isfile(path):
            path = str(self._export_chapter_txt() or "")
        if not path or not os.path.isfile(path):
            return ""
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception:
            logging.exception("Failed to open chapter txt: %s", path)
            raise
        try:
            if self.timer_win:
                self.timer_win.set_status(f"챕터 파일 열기: {os.path.basename(path)}")
        except Exception:
            pass
        return path

    def _chapter_autosave_tick(self):
        try:
            self._export_chapter_txt()
        except Exception:
            logging.exception("Failed to autosave chapter txt")

    def _ensure_chapter_paths(self):
        if self._chapter_jsonl_path and self._chapter_txt_path:
            return
        anchor_dt = datetime.fromtimestamp(self._chapter_anchor_epoch())
        stamp = f"{anchor_dt.strftime('%Y-%m-%d_%H%M')}_{self._chapter_session_stamp}"
        base = self._chapter_log_dir()
        self._chapter_jsonl_path = os.path.join(base, f"chapters_{stamp}.jsonl")
        self._chapter_txt_path = os.path.join(base, f"chapters_{stamp}.txt")

    def _format_chapter_elapsed(self, sec: int) -> str:
        sec = max(0, int(sec))
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _chapter_competitor_text(self, side: str, name: str, pid: str, registered: bool) -> str:
        side = str(side or "").lower().strip()
        _name = str(name or "").strip()
        _pid = str(pid or "").strip()
        unknown = UNKNOWN_PLAYER_LABEL.upper()
        if _pid.upper() == unknown:
            _pid = ""
        if bool(getattr(self.cfg, "chapter_nickname_only", False)):
            return _name if _name else _pid
        if registered and _name:
            if _pid:
                return f"{_name}({_pid})"
            return _name
        if _pid:
            return _pid
        return _name

    def _sync_current_players_to_config(self):
        self.cfg.current_blue_id = str(self._current_blue_id or "").upper().strip()
        self.cfg.current_red_id = str(self._current_red_id or "").upper().strip()
        self.cfg.current_blue_registered = bool(self._current_blue_registered)
        self.cfg.current_red_registered = bool(self._current_red_registered)
        self.cfg.current_blue_valid = bool(self._current_blue_valid)
        self.cfg.current_red_valid = bool(self._current_red_valid)
        self._sync_current_player_flags_to_overlay()

    def _sync_current_player_flags_to_overlay(self):
        try:
            tw = getattr(self, "timer_win", None)
            if tw is None or not hasattr(tw, "set_player_flags"):
                return
            tw.set_player_flags(
                _player_flag_path_for_gid(self.cfg, self._current_blue_id),
                _player_flag_path_for_gid(self.cfg, self._current_red_id),
            )
        except Exception:
            pass

    def _apply_saved_player_state(self, cfg: Optional[AppConfig] = None):
        cfg = cfg or self.cfg
        self._current_blue_id = str(getattr(cfg, "current_blue_id", "") or "").upper().strip()
        self._current_red_id = str(getattr(cfg, "current_red_id", "") or "").upper().strip()
        self._current_blue_registered = bool(getattr(cfg, "current_blue_registered", False))
        self._current_red_registered = bool(getattr(cfg, "current_red_registered", False))
        self._current_blue_valid = bool(getattr(cfg, "current_blue_valid", False))
        self._current_red_valid = bool(getattr(cfg, "current_red_valid", False))
        self._sync_current_players_to_config()
        try:
            self.timer_win.set_player_info(
                self._current_blue_id,
                self._current_red_id,
                self._current_blue_registered,
                self._current_red_registered,
                self._current_blue_valid,
                self._current_red_valid,
            )
        except Exception:
            pass

    def _sync_koth_streak_to_overlay(self, fallback_side: str = ""):
        champ = str(getattr(self.cfg, "koth_champion_id", "") or "").upper().strip()
        streak = max(0, int(getattr(self.cfg, "koth_streak", 0) or 0))
        blue_id = str(self._current_blue_id or "").upper().strip()
        red_id = str(self._current_red_id or "").upper().strip()
        blue_streak = streak if champ and champ == blue_id else 0
        red_streak = streak if champ and champ == red_id else 0
        side = str(fallback_side or "").lower().strip()
        if streak > 0 and blue_streak == 0 and red_streak == 0:
            if side == "blue":
                blue_streak = streak
            elif side == "red":
                red_streak = streak
        try:
            self.timer_win.set_win_streaks(blue_streak, red_streak)
        except Exception:
            pass

    def _apply_koth_streak_with_existing_win_route(self, side: str, base_streak: int = 0):
        side = str(side or "").lower().strip()
        if side not in ("blue", "red"):
            return
        base_streak = max(0, int(base_streak or 0))
        try:
            logging.info("KOTH_ADD_WIN_BEGIN side=%s base_streak=%s", side, base_streak)
            if base_streak > 0:
                if side == "blue":
                    self.timer_win.set_win_streaks(base_streak, 0)
                else:
                    self.timer_win.set_win_streaks(0, base_streak)
            self.timer_win.add_win(side)
            try:
                backend = getattr(self.timer_win, "_backend", None)
                blue_streak = int(getattr(backend, "blueWinStreak", 0) or 0)
                red_streak = int(getattr(backend, "redWinStreak", 0) or 0)
                self.cfg.koth_streak = blue_streak if side == "blue" else red_streak
                logging.info(
                    "KOTH_ADD_WIN_DONE side=%s backend_blue=%s backend_red=%s",
                    side,
                    blue_streak,
                    red_streak,
                )
            except Exception:
                pass
        except Exception as e:
            logging.exception("KOTH_ADD_WIN_FAIL side=%s err=%s", side, e)

    def _trigger_koth_break_effect(self, new_winner_side: str):
        new_winner_side = str(new_winner_side or "").lower().strip()
        if new_winner_side not in ("blue", "red"):
            return
        try:
            backend = getattr(self.timer_win, "_backend", None)
            if backend is None:
                return
            blue_streak = int(getattr(backend, "blueWinStreak", 0) or 0)
            red_streak = int(getattr(backend, "redWinStreak", 0) or 0)
            old_side = "blue" if blue_streak > 0 else ("red" if red_streak > 0 else "")
            if not old_side:
                return
            score_side = "red" if old_side == "blue" else "blue"
            logging.info(
                "KOTH_BREAK_EFFECT old_side=%s score_side=%s old_blue=%s old_red=%s new_side=%s",
                old_side, score_side, blue_streak, red_streak, new_winner_side,
            )
            if hasattr(backend, "_set_win_change"):
                backend._set_win_change("score", score_side)
            self.timer_win.set_win_streaks(0, 0)
            if hasattr(backend, "_set_win_change"):
                backend._set_win_change("", "")
        except Exception as e:
            logging.exception("KOTH_BREAK_EFFECT_FAIL err=%s", e)

    def _koth_display_side(self, winner: str, fallback_side: str = "") -> str:
        winner = str(winner or "").upper().strip()
        side = str(fallback_side or "").lower().strip()
        if side in ("blue", "red"):
            return side
        blue_id = str(self._current_blue_id or "").upper().strip()
        red_id = str(self._current_red_id or "").upper().strip()
        if winner and blue_id and winner == blue_id:
            return "blue"
        if winner and red_id and winner == red_id:
            return "red"
        return ""

    def _refresh_current_ids_for_koth(self):
        try:
            d = self.controller._read_names()
        except Exception as e:
            logging.info("KOTH_SIDE_REFRESH_FAIL err=%s", e)
            return
        if not d:
            return
        old_blue = str(self._current_blue_id or "")
        old_red = str(self._current_red_id or "")
        unknown = UNKNOWN_PLAYER_LABEL
        blue_id = str(d.get("blue_player_id") or "").upper().strip()
        red_id = str(d.get("red_player_id") or "").upper().strip()
        if blue_id and blue_id != unknown:
            self._current_blue_id = blue_id
            self._current_blue_registered = bool(d.get("blue_player_registered", blue_id in self.cfg.players))
            self._current_blue_valid = bool(d.get("blue_player_valid", True))
        if red_id and red_id != unknown:
            self._current_red_id = red_id
            self._current_red_registered = bool(d.get("red_player_registered", red_id in self.cfg.players))
            self._current_red_valid = bool(d.get("red_player_valid", True))
        self._sync_current_players_to_config()
        try:
            logging.info(
                "KOTH_SIDE_REFRESH old_blue=%s old_red=%s new_blue=%s new_red=%s raw_blue=%s raw_red=%s",
                old_blue, old_red, self._current_blue_id, self._current_red_id, blue_id, red_id,
            )
        except Exception:
            pass

    def _finish_koth_winner_ui(
        self,
        winner: str,
        prev: str,
        raw: str,
        score: Optional[int],
        side: str,
        display_side: str,
        base_streak: int,
        reset_first: bool,
    ):
        winner = str(winner or "").upper().strip()
        display_side = str(display_side or "").lower().strip()
        if display_side not in ("blue", "red") or not winner:
            return
        if reset_first:
            self.cfg.koth_champion_id = winner
            self.cfg.koth_streak = 0
            try:
                self.timer_win.set_win_streaks(0, 0)
            except Exception:
                pass
            base_streak = 0

        # Keep player IDs consistent with the visual KOTH side. When the champion
        # changes corner, move the previous opponent to the opposite corner instead
        # of leaving a duplicated/stale winner ID behind.
        try:
            old_blue = str(self._current_blue_id or "").upper().strip()
            old_red = str(self._current_red_id or "").upper().strip()
            unknown = UNKNOWN_PLAYER_LABEL.upper()
            if display_side == "blue":
                new_blue = winner
                new_red = old_blue if old_red == winner and old_blue and old_blue != winner else old_red
            else:
                new_blue = old_red if old_blue == winner and old_red and old_red != winner else old_blue
                new_red = winner
            if new_blue and new_blue != unknown:
                self._current_blue_id = new_blue
                self._current_blue_registered = bool(new_blue in self.cfg.players)
                self._current_blue_valid = True
            if new_red and new_red != unknown:
                self._current_red_id = new_red
                self._current_red_registered = bool(new_red in self.cfg.players)
                self._current_red_valid = True
            self._sync_current_players_to_config()
            self.timer_win.set_player_info(
                self._current_blue_id,
                self._current_red_id,
                self._current_blue_registered,
                self._current_red_registered,
                self._current_blue_valid,
                self._current_red_valid,
            )
        except Exception:
            logging.exception("KOTH_PLAYER_ID_SYNC_FAIL winner=%s side=%s", winner, display_side)

        self._apply_koth_streak_with_existing_win_route(display_side, base_streak=base_streak)
        try:
            logging.info(
                "KOTH_STREAK winner=%s prev=%s streak=%s raw=%s score=%s side=%s display_side=%s blue_id=%s red_id=%s",
                winner, prev, self.cfg.koth_streak, raw, score, side,
                display_side,
                self._current_blue_id,
                self._current_red_id,
            )
        except Exception:
            pass
        try:
            winner_name = self.cfg.players.get(winner, winner)
            blue_name = self.cfg.players.get(self._current_blue_id, self._current_blue_id)
            red_name = self.cfg.players.get(self._current_red_id, self._current_red_id)
            if display_side == "blue":
                blue_name = winner_name
            elif display_side == "red":
                red_name = winner_name
            self.timer_win.set_names(blue_name, red_name)
        except Exception:
            pass
        try:
            blue_gid = winner if display_side == "blue" else self._current_blue_id
            red_gid = winner if display_side == "red" else self._current_red_id
            blue_img = self.controller._load_player_image(_player_image_path_for_gid(self.cfg, blue_gid))
            red_img = self.controller._load_player_image(_player_image_path_for_gid(self.cfg, red_gid))
            self.timer_win.set_player_images(
                blue_img if blue_img is not None else None,
                red_img if red_img is not None else None,
            )
        except Exception:
            pass
        try:
            self._sync_koth_streak_to_overlay(fallback_side=display_side)
        except Exception:
            pass

    def _apply_koth_winner(self, winner_id: str, raw: str = "", score: Optional[int] = None, side: str = ""):
        if not bool(getattr(self.cfg, "koth_enabled", False)):
            return
        if bool(getattr(self, "_koth_transition_pending", False)):
            logging.info("KOTH_SKIP reason=transition_pending winner=%s", winner_id)
            return
        winner = str(winner_id or "").upper().strip()
        if not winner:
            return
        prev = str(getattr(self.cfg, "koth_champion_id", "") or "").upper().strip()
        display_side = self._koth_display_side(winner, side)
        if display_side not in ("blue", "red"):
            logging.info("KOTH_SKIP reason=no_display_side winner=%s side=%s", winner, side)
            return
        prev_streak = max(0, int(getattr(self.cfg, "koth_streak", 0) or 0))
        if winner != prev:
            if prev and prev_streak > 0:
                self._trigger_koth_break_effect(display_side)
                self._koth_transition_pending = True
                delay_ms = int(((getattr(self.cfg, "win_effects", {}) or {}).get("fail", {}) or {}).get("switch_delay_ms", 2800) or 2800)
                logging.info("KOTH_BREAK_DELAY winner=%s prev=%s delay_ms=%s", winner, prev, delay_ms)
                QTimer.singleShot(
                    max(0, delay_ms),
                    lambda w=winner, p=prev, r=raw, sc=score, s=side, ds=display_side: (
                        setattr(self, "_koth_transition_pending", False),
                        self._finish_koth_winner_ui(w, p, r, sc, s, ds, 0, True),
                    ),
                )
                return
            else:
                try:
                    self.timer_win.set_win_streaks(0, 0)
                except Exception:
                    pass
            base_streak = 0
            reset_first = True
        else:
            base_streak = prev_streak
            reset_first = False
        self._finish_koth_winner_ui(winner, prev, raw, score, side, display_side, base_streak, reset_first)

    def _append_chapter_event(
        self,
        title: str,
        payload: Optional[dict] = None,
        elapsed_sec: Optional[int] = None,
        dedupe_key: Optional[str] = None,
    ) -> bool:
        event_title = str(title or "").strip()
        if not event_title:
            return False
        if "TEST" in event_title.upper():
            return False
        key = str(dedupe_key or "").strip()
        if key:
            if key in self._chapter_seen_keys:
                return False
            self._chapter_seen_keys.add(key)
        now_epoch = time.time()
        if elapsed_sec is None:
            elapsed = int(now_epoch - self._chapter_anchor_epoch() + int(getattr(self.cfg, "chapter_offset_sec", 0)))
        else:
            elapsed = int(elapsed_sec) + int(getattr(self.cfg, "chapter_offset_sec", 0))
        elapsed = max(0, elapsed)
        dedupe = max(0, int(getattr(self.cfg, "chapter_dedupe_sec", 20)))
        if self._chapter_last_title == event_title and (elapsed - self._chapter_last_elapsed) <= dedupe:
            return False
        self._chapter_last_title = event_title
        self._chapter_last_elapsed = elapsed
        event = {
            "wall_time": datetime.now().isoformat(timespec="seconds"),
            "anchor_epoch": float(self._chapter_anchor_epoch()),
            "offset_sec": int(getattr(self.cfg, "chapter_offset_sec", 0)),
            "elapsed_sec": int(elapsed),
            "title": event_title,
        }
        if isinstance(payload, dict):
            event.update(payload)
        self._chapter_events.append(event)
        self._ensure_chapter_paths()
        try:
            with open(self._chapter_jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            logging.exception("Failed to append chapter jsonl")
        self._export_chapter_txt()
        return True

    def _export_chapter_txt(self) -> str:
        if not self._chapter_events:
            return ""
        self._ensure_chapter_paths()
        hide_time = bool(getattr(self.cfg, "chapter_hide_time", False))
        anchor = self._chapter_anchor_epoch()
        anchor_label = datetime.fromtimestamp(anchor).strftime("%Y-%m-%d %H:%M:%S")
        end_sec = max(int(ev.get("elapsed_sec", 0)) for ev in self._chapter_events)
        lines = [
            f"# 챕터 생성일: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# 기준 시각: {anchor_label}",
            f"# 보정(초): {int(getattr(self.cfg, 'chapter_offset_sec', 0)):+d}",
            f"# 챕터 수: {len(self._chapter_events)}",
            f"# 총 길이: {self._format_chapter_elapsed(end_sec)}",
            "",
        ]
        if not hide_time:
            lines.append("00:00 시작")
        for ev in sorted(self._chapter_events, key=lambda x: int(x.get("elapsed_sec", 0))):
            ts = self._format_chapter_elapsed(int(ev.get("elapsed_sec", 0)))
            title = str(ev.get("title") or "").strip()
            if title:
                if hide_time:
                    lines.append(title)
                else:
                    lines.append(f"{ts} {title}")
        try:
            with open(self._chapter_txt_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:
            logging.exception("Failed to export chapter txt")
            return ""
        return self._chapter_txt_path

    def _overlay_side_id(self, side: str) -> str:
        side = (side or "").lower().strip()
        if side == "red":
            return str(self._current_red_id or "")
        return str(self._current_blue_id or "")

    def _overlay_side_valid(self, side: str) -> bool:
        side = (side or "").lower().strip()
        if side == "red":
            return bool(self._current_red_valid)
        return bool(self._current_blue_valid)

    def _sync_overlay_side_from_spectatorlog(self, side: str):
        side = (side or "").lower().strip()
        if side not in ("blue", "red"):
            return
        if not bool(getattr(self.cfg, "spectatorlog_sync_players", True)):
            return
        try:
            root = resolve_spectatorlog_path(str(getattr(self.cfg, "spectatorlog_path", "") or ""))
            raw = _make_spectator_log_watcher(self.cfg)._read_text(os.path.join(root, side, "name.txt"))
            gid = normalize_game_id(raw, PLAYER_ID_ALLOW_CHARS)
            unknown = UNKNOWN_PLAYER_LABEL.upper().strip()
            if not gid or gid.upper().strip() == unknown:
                return
            registered = bool(gid in (self.cfg.players or {}))
            display = str((self.cfg.players or {}).get(gid) or raw or gid)
            if side == "red":
                self._current_red_id = gid
                self._current_red_registered = registered
                self._current_red_valid = True
                self.timer_win.set_names(None, display)
            else:
                self._current_blue_id = gid
                self._current_blue_registered = registered
                self._current_blue_valid = True
                self.timer_win.set_names(display, None)
            self._sync_current_players_to_config()
            self.timer_win.set_player_info(
                self._current_blue_id,
                self._current_red_id,
                self._current_blue_registered,
                self._current_red_registered,
                self._current_blue_valid,
                self._current_red_valid,
            )
            logging.info("PROFILE_SIDE_SYNC side=%s raw=%s gid=%s registered=%s", side, raw, gid, registered)
        except Exception as e:
            logging.info("PROFILE_SIDE_SYNC_FAIL side=%s err=%s", side, e)

    def _open_overlay_profile_register(self, side: str):
        self._open_overlay_profile_dialog(side, "register")

    def _open_overlay_profile_edit(self, side: str):
        self._open_overlay_profile_dialog(side, "edit")

    def _open_overlay_profile_dialog(self, side: str, mode: str):
        self._sync_overlay_side_from_spectatorlog(side)
        gid = self._overlay_side_id(side)
        try:
            logging.info(
                "PROFILE_DIALOG_OPEN side=%s mode=%s gid=%s blue_id=%s red_id=%s",
                side, mode, gid, self._current_blue_id, self._current_red_id,
            )
        except Exception:
            pass
        if (not gid or not self._overlay_side_valid(side)) and mode == "register":
            try:
                dlg = QInputDialog(None)
                dlg.setWindowTitle("프로필 등록")
                dlg.setLabelText("GAME_ID 입력:")
                dlg.setTextValue(str(gid or ""))
                dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
                ok = dlg.exec() == QDialog.DialogCode.Accepted
                gid = str(dlg.textValue() if ok else "").strip().upper()
            except Exception:
                gid = ""
        if not gid or (mode != "register" and not self._overlay_side_valid(side)):
            try:
                self.timer_win.set_status("선수 ID가 없어 등록할 수 없습니다.")
            except Exception:
                pass
            return
        name = str(self.cfg.players.get(gid, "")) if mode == "edit" else str(self.cfg.players.get(gid, ""))
        img_path = _player_image_path_for_gid(self.cfg, gid)
        country = str((self.cfg.players_countries or {}).get(gid, "KR") or "KR")
        flag_path = str((self.cfg.players_flags or {}).get(gid, "") or "")
        existing_names = sorted(
            {str(v or "").strip() for v in (self.cfg.players or {}).values() if str(v or "").strip()},
            key=lambda s: s.lower(),
        )

        def _pick_img(_gid: str) -> str:
            path, _ = QFileDialog.getOpenFileName(None, "프로필 사진 선택", "", "이미지 파일 (*.png *.jpg *.jpeg *.bmp)")
            if not path:
                return ""
            return _store_player_image(_gid, path)

        def _paste_img(_gid: str) -> str:
            return _paste_clipboard_image(_gid)

        def _url_img(_gid: str) -> Optional[str]:
            url = _ask_image_url(None)
            if not url:
                return None
            return _download_image_url(url, _gid)

        def _pick_flag(_gid: str) -> str:
            gid_key = str(_gid or "").strip().upper()
            if not gid_key:
                return ""
            path, _ = QFileDialog.getOpenFileName(None, "국기 이미지 선택", "", "이미지 파일 (*.png *.jpg *.jpeg *.bmp)")
            if not path:
                return ""
            return _store_player_flag(gid_key, path)

        def _save(_old_gid: str, _new_gid: str, _name: str, _img: str, _country: str, _flag: str) -> bool:
            old_gid = str(_old_gid or "").strip().upper()
            new_gid_raw = str(_new_gid or "").strip().upper()
            new_gids: List[str] = []
            seen_gids = set()
            for part in re.split(r"[,;\s]+", new_gid_raw):
                gid_part = str(part or "").strip().upper()
                if not gid_part or not re.fullmatch(r"[A-Z0-9_.-]+", gid_part):
                    continue
                if gid_part in seen_gids:
                    continue
                seen_gids.add(gid_part)
                new_gids.append(gid_part)
            new_name = str(_name or "").strip()
            if not new_gids or not new_name:
                return False
            for new_gid in new_gids:
                if new_gid != old_gid and new_gid in self.cfg.players:
                    QMessageBox.information(None, "저장 실패", f"이미 존재하는 ID입니다: {new_gid}")
                    return False

            if old_gid and old_gid not in new_gids:
                if old_gid in self.cfg.players:
                    del self.cfg.players[old_gid]
                if old_gid in self.cfg.players_images:
                    del self.cfg.players_images[old_gid]
                if old_gid in self.cfg.players_countries:
                    del self.cfg.players_countries[old_gid]
                if old_gid in self.cfg.players_flags:
                    del self.cfg.players_flags[old_gid]

            primary_gid = new_gids[0]
            img_value = _img
            country_value = _normalize_player_country(_country)
            flag_value = str(_flag or "").strip()
            if not img_value:
                for ex_gid, ex_name in self.cfg.players.items():
                    if ex_gid not in new_gids and str(ex_name or "").strip() == str(new_name or "").strip():
                        inherited = str(self.cfg.players_images.get(ex_gid, "") or "").strip()
                        if inherited:
                            img_value = inherited
                            break
            if not flag_value:
                for ex_gid, ex_name in self.cfg.players.items():
                    if ex_gid not in new_gids and str(ex_name or "").strip() == str(new_name or "").strip():
                        inherited_flag = str((self.cfg.players_flags or {}).get(ex_gid, "") or "").strip()
                        if inherited_flag:
                            flag_value = inherited_flag
                            break
            for new_gid in new_gids:
                self.cfg.players[new_gid] = new_name
                if img_value is not None:
                    self.cfg.players_images[new_gid] = to_app_rel(img_value)
                self.cfg.players_countries[new_gid] = country_value
                self.cfg.players_flags[new_gid] = to_app_rel(flag_value)
            try:
                self.cfg.to_json(self.cfg_path)
            except Exception:
                pass
            if side.lower().strip() == "red":
                self._current_red_registered = True
                self._current_red_id = primary_gid
                self._current_red_valid = True
            else:
                self._current_blue_registered = True
                self._current_blue_id = primary_gid
                self._current_blue_valid = True

            if old_gid and str(self._current_blue_id or "").upper().strip() == old_gid:
                self._current_blue_id = primary_gid
            if old_gid and str(self._current_red_id or "").upper().strip() == old_gid:
                self._current_red_id = primary_gid
            self._sync_current_players_to_config()

            self.timer_win.set_player_info(
                self._current_blue_id,
                self._current_red_id,
                self._current_blue_registered,
                self._current_red_registered,
                self._current_blue_valid,
                self._current_red_valid,
            )
            # Immediate overlay update
            if side.lower().strip() == "red":
                self.timer_win.set_names(None, new_name)
                img = self.controller._load_player_image(_player_image_path_for_gid(self.cfg, primary_gid))
                self.timer_win.set_player_images(_NO_UPDATE, img if img is not None else _NO_UPDATE)
            else:
                self.timer_win.set_names(new_name, None)
                img = self.controller._load_player_image(_player_image_path_for_gid(self.cfg, primary_gid))
                self.timer_win.set_player_images(img if img is not None else _NO_UPDATE, _NO_UPDATE)
            if self.settings_dlg and hasattr(self.settings_dlg, "_reload_players_cards"):
                try:
                    self.settings_dlg._reload_players_cards()
                except Exception:
                    pass
            return True

        def _delete(_gid: str) -> bool:
            gid_key = str(_gid or "").strip().upper()
            if not gid_key:
                return False
            removed = False
            if gid_key in self.cfg.players:
                del self.cfg.players[gid_key]
                removed = True
            if gid_key in self.cfg.players_images:
                del self.cfg.players_images[gid_key]
            if gid_key in self.cfg.players_countries:
                del self.cfg.players_countries[gid_key]
            if gid_key in self.cfg.players_flags:
                del self.cfg.players_flags[gid_key]
                removed = True
            if not removed:
                return False
            try:
                self.cfg.to_json(self.cfg_path)
            except Exception:
                pass

            if str(self._current_blue_id or "").upper().strip() == gid_key:
                self._current_blue_registered = False
            if str(self._current_red_id or "").upper().strip() == gid_key:
                self._current_red_registered = False
            self._sync_current_players_to_config()

            self.timer_win.set_player_info(
                self._current_blue_id,
                self._current_red_id,
                self._current_blue_registered,
                self._current_red_registered,
                self._current_blue_valid,
                self._current_red_valid,
            )

            blue_name_now = self.cfg.players.get(self._current_blue_id, self._current_blue_id)
            red_name_now = self.cfg.players.get(self._current_red_id, self._current_red_id)
            self.timer_win.set_names(blue_name_now, red_name_now)

            blue_img_now = self.controller._load_player_image(_player_image_path_for_gid(self.cfg, self._current_blue_id))
            red_img_now = self.controller._load_player_image(_player_image_path_for_gid(self.cfg, self._current_red_id))
            self.timer_win.set_player_images(
                blue_img_now if blue_img_now is not None else None,
                red_img_now if red_img_now is not None else None,
            )

            if self.settings_dlg and hasattr(self.settings_dlg, "_reload_players_cards"):
                try:
                    self.settings_dlg._reload_players_cards()
                except Exception:
                    pass
            try:
                self.timer_win.set_status(f"ID 삭제됨: {gid_key}")
            except Exception:
                pass
            return True

        dlg = OverlayProfileDialog(
            None,
            gid,
            name,
            img_path,
            country,
            flag_path,
            mode,
            _pick_img,
            _paste_img,
            _url_img,
            _pick_flag,
            _save,
            on_delete=_delete,
            existing_names=existing_names,
        )
        try:
            if self.timer_win and hasattr(self.timer_win, "set_overlay_on_top"):
                self.timer_win.set_overlay_on_top(False)
            dlg.exec()
        finally:
            if self.timer_win and hasattr(self.timer_win, "set_overlay_on_top"):
                self.timer_win.set_overlay_on_top(True)

    def _pixel_id_for_name(self, name: str) -> Optional[str]:
        for rule in self.cfg.pixel_rules or []:
            if str(rule.get("name") or "") == str(name):
                return str(rule.get("id") or "")
        return None

    def _pixel_name_for_id(self, pid: str) -> Optional[str]:
        for rule in self.cfg.pixel_rules or []:
            if str(rule.get("id") or "") == str(pid):
                return str(rule.get("name") or "")
        return None

    def _action_cooldown_for_event(self, event: str) -> float:
        if not event:
            return 0.0
        cd_map = getattr(self.cfg, "action_cooldowns", {}) or {}
        if event in cd_map:
            return float(cd_map[event])
        if event.startswith("pixel:"):
            name = event.split(":", 1)[1]
            pid = self._pixel_id_for_name(name)
            if pid and f"pixel_id:{pid}" in cd_map:
                return float(cd_map.get(f"pixel_id:{pid}", 0.0))
        if event.startswith("pixel_id:"):
            pid = event.split(":", 1)[1]
            name = self._pixel_name_for_id(pid)
            if name and f"pixel:{name}" in cd_map:
                return float(cd_map.get(f"pixel:{name}", 0.0))
        if event == "on_trigger":
            return float(getattr(self.cfg.trigger, "action_cooldown_sec", 0.0) or 0.0)
        return float(getattr(self.cfg, "action_cooldown_sec", 0.0) or 0.0)

    def _run_actions_with_cooldown(self, key: str, actions: List[dict], cooldown_override: Optional[float] = None):
        if not actions:
            try:
                logging.info("ACTION_SKIP key=%s reason=no_actions", key)
            except Exception:
                pass
            return
        cd = float(cooldown_override if cooldown_override is not None else self._action_cooldown_for_event(key))
        if cd > 0:
            now = time.time()
            last = self._action_last_run.get(key)
            if last is not None and (now - last) < cd:
                try:
                    logging.info(
                        "ACTION_SKIP key=%s reason=cooldown remain=%.3f sec",
                        key,
                        max(0.0, cd - (now - last)),
                    )
                except Exception:
                    pass
                return
            self._action_last_run[key] = now
        try:
            types = [str((a or {}).get("type", "")).lower() for a in (actions or [])]
            logging.info("ACTION_RUN key=%s count=%s cooldown=%.3f types=%s", key, len(actions), cd, types)
        except Exception:
            pass
        self.action_runner.run(actions, key=key)

    def _enqueue_action_run(self, key: str, actions: List[dict], cooldown_override: Optional[float] = None):
        if not actions:
            try:
                logging.info("ACTION_QUEUE_SKIP key=%s reason=no_actions", key)
            except Exception:
                pass
            return
        self._action_queue.append((key, actions, cooldown_override))
        try:
            logging.info("ACTION_QUEUED key=%s count=%s queue_size=%s", key, len(actions), len(self._action_queue))
        except Exception:
            pass
        if not self._action_busy:
            self._action_timer.start(0)

    def _drain_action_queue(self):
        if self._action_busy:
            try:
                logging.info("ACTION_DRAIN_SKIP reason=busy queue_size=%s", len(self._action_queue))
            except Exception:
                pass
            return
        if not self._action_queue:
            try:
                logging.info("ACTION_DRAIN_SKIP reason=empty")
            except Exception:
                pass
            return
        key, actions, cooldown_override = self._action_queue.popleft()
        self._action_busy = True
        try:
            logging.info("ACTION_DRAIN key=%s count=%s queue_left=%s", key, len(actions), len(self._action_queue))
        except Exception:
            pass
        try:
            self._run_actions_with_cooldown(key, actions, cooldown_override=cooldown_override)
        finally:
            self._action_busy = False
            try:
                logging.info("ACTION_DRAIN_DONE key=%s queue_left=%s", key, len(self._action_queue))
            except Exception:
                pass
        if self._action_queue:
            self._action_timer.start(0)

    def _on_timer_reset_cleanup(self):
        def _has_timer_start(actions_list: List[dict]) -> bool:
            for act in actions_list or []:
                if str(act.get("type", "")).lower() == "timer_start":
                    return True
            return False

        try:
            if self._action_queue:
                self._action_queue = deque([item for item in self._action_queue if not _has_timer_start(item[1])])
        except Exception:
            pass
        try:
            self.action_runner.drop_pending_timer_start()
        except Exception:
            pass
        try:
            if getattr(self, "spectator_watcher", None) and bool(getattr(self.cfg, "spectatorlog_enabled", False)):
                self.spectator_watcher.force_refresh()
        except Exception:
            pass

    def on_trigger(self):
        now = time.time()
        try:
            logging.info("TRIGGER_FIRED ts=%.3f", now)
        except Exception:
            pass
        try:
            self.timer_win.timer_force_reset()
        except Exception:
            try:
                self.timer_win.timer_reset()
            except Exception:
                pass
        actions = self.cfg.actions.get("on_trigger", [])
        if actions:
            self._enqueue_action_run("on_trigger", actions)
        else:
            try:
                logging.info("TRIGGER_ACTION_SKIP reason=on_trigger_empty")
            except Exception:
                pass

    def _test_trigger_once(self):
        try:
            self.timer_win.set_status("트리거 테스트: 트리거 동작 실행")
        except Exception:
            pass
        self.on_trigger()

    def _save_trigger_snapshot(self):
        if not self.cfg.roi_trigger.valid():
            return
        roi = capture_roi_np_global(self.cfg.roi_trigger)
        if roi.size == 0:
            return
        now = datetime.now()
        stamp = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]
        base_dir = os.path.dirname(os.path.abspath(self.cfg_path)) if self.cfg_path else get_app_base_dir()
        base = os.path.join(base_dir, "logs", "trigger", stamp)
        os.makedirs(base, exist_ok=True)
        img_path = os.path.join(base, "trigger_roi.png")
        try:
            cv2.imwrite(img_path, roi)
        except Exception:
            logging.exception("Failed to save trigger ROI image")
        b = int(np.median(roi[..., 0]))
        g = int(np.median(roi[..., 1]))
        r = int(np.median(roi[..., 2]))
        dist = bgr_distance((b, g, r), self.cfg.trigger.target_bgr)
        log_path = os.path.join(base, "trigger_log.txt")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"timestamp={now.isoformat()}\n")
                f.write(f"roi_trigger={asdict(self.cfg.roi_trigger)}\n")
                f.write(f"bgr={b},{g},{r}\n")
                f.write(f"target_bgr={self.cfg.trigger.target_bgr}\n")
                f.write(f"tolerance={self.cfg.trigger.tolerance}\n")
                f.write(f"dist={dist:.3f}\n")
                f.write(f"cooldown_sec={self.cfg.trigger.cooldown_sec}\n")
                f.write(f"window_frames={self.cfg.trigger.window_frames}\n")
                f.write(f"consecutive_needed={self.cfg.trigger.consecutive_needed}\n")
        except Exception:
            logging.exception("Failed to save trigger log")

    def _update_backend_detect_flags(self):
        try:
            self.timer_win._backend.set_screen_detect_running(bool(self._screen_detection_running()))
            self.timer_win._backend.set_pixel_detect_running(bool(self._pixel_detection_running()))
            self.timer_win._backend.set_log_detect_running(bool(self._log_detection_running()))
        except Exception:
            pass

    def _detection_running(self) -> bool:
        return bool(
            (self.watcher and self.watcher.is_running())
            or (getattr(self, "spectator_watcher", None) and self.spectator_watcher.is_running())
        )

    def _screen_detection_running(self) -> bool:
        return bool(self.watcher and self.watcher.is_running())

    def _pixel_detection_running(self) -> bool:
        return bool(
            self.watcher
            and self.watcher.is_running()
            and getattr(self.watcher, "pixel_detection_enabled", lambda: True)()
        )

    def _log_detection_running(self) -> bool:
        # When the user clicks the log toggle while running, stop must not block the UI.
        # During async shutdown we intentionally report "not running" immediately so the
        # top overlay button and settings button do not stay red or accept another stop.
        if bool(getattr(self, "_log_detector_stopping", False)):
            return False
        return bool(getattr(self, "spectator_watcher", None) and self.spectator_watcher.is_running())

    def _set_spectatorlog_enabled_runtime(self, enabled: bool, *, save: bool = True) -> None:
        enabled = bool(enabled)
        try:
            self.cfg.spectatorlog_enabled = enabled
        except Exception:
            pass
        try:
            if self.settings_dlg and hasattr(self.settings_dlg, "chk_spectatorlog_enabled"):
                self.settings_dlg._suspend_apply = True
                self.settings_dlg.chk_spectatorlog_enabled.setChecked(enabled)
        except Exception:
            pass
        finally:
            try:
                if self.settings_dlg:
                    self.settings_dlg._suspend_apply = False
            except Exception:
                pass
        if save:
            try:
                self.cfg.to_json(self.cfg_path)
            except Exception:
                pass

    def _start_spectator_watcher_if_enabled(self, *, force_enable: bool = False):
        if force_enable and not bool(getattr(self.cfg, "spectatorlog_enabled", False)):
            self._set_spectatorlog_enabled_runtime(True)
        if not bool(getattr(self.cfg, "spectatorlog_enabled", False)):
            if getattr(self, "spectator_watcher", None) and self.spectator_watcher.is_running():
                # Do not stop the Windows directory watcher on the GUI thread.
                self._stop_log_detector()
            return
        if getattr(self, "spectator_watcher", None) and not self.spectator_watcher.is_running():
            self.spectator_watcher.start()
            try:
                root = resolve_spectatorlog_path(str(getattr(self.cfg, "spectatorlog_path", "") or ""))
                self.timer_win.set_status(f"SpectatorLog 감시 시작: {root}")
            except Exception:
                pass

    def _start_screen_detector(self):
        if self.watcher:
            self.watcher.set_detection_modes(trigger=True, pixel=True)
        if self.watcher and not self.watcher.is_running():
            self.watcher.start()
        if self.settings_dlg:
            self.settings_dlg._sync_watcher_labels()
        self._update_backend_detect_flags()

    def _stop_screen_detector(self):
        if self.watcher and self.watcher.is_running():
            self.watcher.stop()
        if self.settings_dlg:
            self.settings_dlg._sync_watcher_labels()
        self._update_backend_detect_flags()

    def _start_pixel_detector(self):
        if self.watcher:
            self.watcher.set_detection_modes(pixel=True)
            if not self.watcher.is_running():
                self.watcher.start()
        if self.settings_dlg:
            self.settings_dlg._sync_watcher_labels()
        self._update_backend_detect_flags()

    def _stop_pixel_detector(self):
        if self.watcher:
            self.watcher.set_detection_modes(pixel=False)
            if self.watcher.is_running() and not self.watcher.trigger_detection_enabled():
                self.watcher.stop()
        if self.settings_dlg:
            self.settings_dlg._sync_watcher_labels()
        self._update_backend_detect_flags()

    def _start_log_detector(self):
        if bool(getattr(self, "_log_detector_transition", False)):
            try:
                self.timer_win.set_status("SpectatorLog 감시 전환 중")
            except Exception:
                pass
            return
        self._log_detector_stopping = False
        # Overlay/QML "log detect" start must also enable SpectatorLog on first-run
        # release builds.  The public build intentionally does not ship SWa's
        # config.json, so spectatorlog_enabled starts false unless we force it here.
        self._start_spectator_watcher_if_enabled(force_enable=True)
        if self.settings_dlg:
            self.settings_dlg._sync_watcher_labels()
            try:
                self.settings_dlg._refresh_spectatorlog_state()
            except Exception:
                pass
        self._update_backend_detect_flags()

    def _finish_log_detector_stop(self):
        self._log_detector_transition = False
        self._log_detector_stopping = False
        if self.settings_dlg:
            self.settings_dlg._sync_watcher_labels()
            try:
                self.settings_dlg._refresh_spectatorlog_state()
            except Exception:
                pass
        self._update_backend_detect_flags()
        try:
            self.timer_win.set_status("SpectatorLog 감시 중지")
        except Exception:
            pass

    def _stop_log_detector(self):
        watcher = getattr(self, "spectator_watcher", None)
        if bool(getattr(self, "_log_detector_transition", False)):
            return
        self._log_detector_transition = True
        self._log_detector_stopping = True
        # Treat the top menu toggle as a real off switch, not only a thread stop.
        # This prevents Settings auto-apply from immediately starting the watcher again.
        try:
            self._set_spectatorlog_enabled_runtime(False)
        except Exception:
            pass
        try:
            self.timer_win._backend.set_log_detect_running(False)
        except Exception:
            pass
        if self.settings_dlg:
            self.settings_dlg._sync_watcher_labels()
            try:
                self.settings_dlg._refresh_spectatorlog_state()
            except Exception:
                pass
        self._update_backend_detect_flags()

        def _job():
            try:
                if watcher is not None:
                    watcher.stop()
            except Exception:
                logging.exception("SPECTATORLOG_ASYNC_STOP_FAIL")
            finally:
                # Never block the GUI thread waiting for ReadDirectoryChangesW/handle cleanup.
                try:
                    self._log_stop_finished.emit()
                except Exception:
                    self._log_detector_transition = False
                    self._log_detector_stopping = False

        threading.Thread(target=_job, daemon=True).start()

    def _start_detectors(self):
        if self.watcher:
            self.watcher.set_detection_modes(trigger=True, pixel=True)
        if self.watcher and not self.watcher.is_running():
            self.watcher.start()
        self._start_spectator_watcher_if_enabled(force_enable=True)
        if self.settings_dlg:
            self.settings_dlg._sync_watcher_labels()
        self._update_backend_detect_flags()

    def _stop_detectors(self):
        if self.watcher and self.watcher.is_running():
            self.watcher.stop()
        if getattr(self, "spectator_watcher", None) and self.spectator_watcher.is_running():
            self._stop_log_detector()
        if self.settings_dlg:
            self.settings_dlg._sync_watcher_labels()
        self._update_backend_detect_flags()

    def _toggle_screen_detector(self):
        running = self._screen_detection_running()
        if running:
            self._stop_screen_detector()
        else:
            self._start_screen_detector()
        if self.settings_dlg:
            self.settings_dlg._sync_watcher_labels()
        self._update_backend_detect_flags()

    def _toggle_pixel_detector(self):
        if self._pixel_detection_running():
            self._stop_pixel_detector()
        else:
            self._start_pixel_detector()
        if self.settings_dlg:
            self.settings_dlg._sync_watcher_labels()
        self._update_backend_detect_flags()

    def _toggle_log_detector(self):
        if bool(getattr(self, "_log_detector_transition", False)):
            try:
                self.timer_win.set_status("SpectatorLog 감시 전환 중")
            except Exception:
                pass
            return
        running = self._log_detection_running()
        if running:
            self._stop_log_detector()
        else:
            self._start_log_detector()
        if self.settings_dlg:
            self.settings_dlg._sync_watcher_labels()
        self._update_backend_detect_flags()

    def _on_overlay_visibility_request(self, key: str, visible: bool):
        key = str(key or "").strip().lower()
        vis = bool(visible)
        field = None
        if key == "round":
            field = "overlay_show_round"
        elif key == "time":
            field = "overlay_show_time"
        elif key == "blue_img":
            field = "overlay_show_blue_img"
        elif key == "blue_name":
            field = "overlay_show_blue_name"
        elif key == "red_img":
            field = "overlay_show_red_img"
        elif key == "red_name":
            field = "overlay_show_red_name"
        elif key == "arena_name":
            field = "overlay_show_arena_name"
        if not field:
            return
        try:
            setattr(self.cfg, field, vis)
        except Exception:
            pass
        try:
            if self.settings_dlg:
                self.settings_dlg._suspend_apply = True
                if key == "round" and hasattr(self.settings_dlg, "chk_overlay_round"):
                    self.settings_dlg.chk_overlay_round.setChecked(vis)
                if key == "time" and hasattr(self.settings_dlg, "chk_overlay_time"):
                    self.settings_dlg.chk_overlay_time.setChecked(vis)
                if key == "blue_img" and hasattr(self.settings_dlg, "chk_overlay_blue_img"):
                    self.settings_dlg.chk_overlay_blue_img.setChecked(vis)
                if key == "blue_name" and hasattr(self.settings_dlg, "chk_overlay_blue_name"):
                    self.settings_dlg.chk_overlay_blue_name.setChecked(vis)
                if key == "red_img" and hasattr(self.settings_dlg, "chk_overlay_red_img"):
                    self.settings_dlg.chk_overlay_red_img.setChecked(vis)
                if key == "red_name" and hasattr(self.settings_dlg, "chk_overlay_red_name"):
                    self.settings_dlg.chk_overlay_red_name.setChecked(vis)
                if key == "arena_name" and hasattr(self.settings_dlg, "chk_overlay_arena_name"):
                    self.settings_dlg.chk_overlay_arena_name.setChecked(vis)
        except Exception:
            pass
        finally:
            try:
                if self.settings_dlg:
                    self.settings_dlg._suspend_apply = False
            except Exception:
                pass
        try:
            if self.controller:
                self.controller.ui_update.emit({field: vis})
        except Exception:
            pass
        try:
            self.cfg.to_json(self.cfg_path)
        except Exception:
            pass

    def _toggle_detectors(self):
        try:
            if self.settings_dlg:
                self.settings_dlg.apply_only(silent=True)
        except Exception:
            pass
        running = bool(self.watcher and self.watcher.is_running())
        if running:
            if self.watcher:
                self.watcher.stop()
        else:
            if self.watcher:
                self.watcher.set_detection_modes(trigger=True, pixel=True)
                self.watcher.start()
        if self.settings_dlg:
            self.settings_dlg._sync_watcher_labels()
        self._update_backend_detect_flags()

    def _select_player_from_overlay(self, side: str):
        side = (side or "").lower().strip()
        if side not in ("blue", "red"):
            return
        items = [f"{gid} - {name}" for gid, name in sorted(self.cfg.players.items(), key=lambda kv: str(kv[1] or ""))]
        if not items:
            QMessageBox.information(None, "선수 선택", "등록된 선수가 없습니다.")
            return
        title = "블루 코너 선택" if side == "blue" else "레드 코너 선택"
        label = "선수 선택:"
        dlg = QInputDialog(None)
        dlg.setWindowTitle("\uc5f0\uc2b9 \ub2e8\uacc4 \ud3b8\uc9d1")
        dlg.setLabelText(label)
        dlg.setComboBoxItems(items)
        dlg.setOption(QInputDialog.InputDialogOption.UseListViewForComboBoxItems, True)
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        ok = dlg.exec() == QDialog.DialogCode.Accepted
        sel = str(dlg.textValue()) if ok else ""
        if not ok or not sel:
            return
        gid = sel.split("-", 1)[0].strip().upper()
        name = self.cfg.players.get(gid, "")
        img = self.controller._load_player_image(_player_image_path_for_gid(self.cfg, gid))
        if side == "blue":
            self._current_blue_id = gid
            self._current_blue_registered = True
            self._current_blue_valid = True
        else:
            self._current_red_id = gid
            self._current_red_registered = True
            self._current_red_valid = True
        self._sync_current_players_to_config()
        self.timer_win.set_player_info(
            self._current_blue_id,
            self._current_red_id,
            self._current_blue_registered,
            self._current_red_registered,
            self._current_blue_valid,
            self._current_red_valid,
        )
        if side == "blue":
            self.timer_win.set_names(name, None)
            self.timer_win.set_player_images(img if img is not None else _NO_UPDATE, _NO_UPDATE)
        else:
            self.timer_win.set_names(None, name)
            self.timer_win.set_player_images(_NO_UPDATE, img if img is not None else _NO_UPDATE)
        self._sync_koth_streak_to_overlay()

    def on_pixel_rule(self, name: str):
        actions = self.cfg.actions.get(f"pixel:{name}", [])
        key = f"pixel:{name}"
        if not actions:
            rid_match = None
            for rule in self.cfg.pixel_rules or []:
                rid = str(rule.get("id") or "")
                if rid and rid == str(name):
                    rid_match = rid
                    break
            if rid_match:
                actions = self.cfg.actions.get(f"pixel_id:{rid_match}", [])
                key = f"pixel_id:{rid_match}"
        if not actions:
            rid = None
            for i, rule in enumerate(self.cfg.pixel_rules or []):
                rname = str(rule.get("name") or "")
                if rname == str(name) or (not rname and str(name) == f"rule{i + 1}"):
                    rid = str(rule.get("id") or "")
                    break
            if rid:
                actions = self.cfg.actions.get(f"pixel_id:{rid}", [])
                key = f"pixel_id:{rid}"
        if actions:
            self._enqueue_action_run(key, actions)

    def _on_timer_running(self, running: bool):
        return

    def _on_rest_thirty_seconds(self):
        if not bool(getattr(self.cfg, "timer_rest_30s_tts_enabled", True)):
            return
        rate = int(getattr(self.cfg, "timer_rest_30s_tts_rate", 200) or 200)
        text = "Please subscribe and like."
        action = {
            "type": "tts_en",
            "text": text,
            "rate": rate,
            "volume": 100,
            "voice_mode": "auto",
        }
        try:
            self.action_runner.run([dict(action), dict(action)], key="timer:rest_30s_tts")
        except Exception:
            logging.exception("Failed to run rest-30s TTS")

    def _diagnostic_folder(self) -> str:
        try:
            folder = app_path("diagnostics")
        except Exception:
            folder = os.path.abspath(os.path.join(os.getcwd(), "diagnostics"))
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception:
            pass
        return folder

    def _diagnostic_spectator_root(self) -> str:
        try:
            return resolve_spectatorlog_path(str(getattr(self.cfg, "spectatorlog_path", "") or ""))
        except Exception:
            return ""

    def _diagnostic_app_state(self) -> dict:
        try:
            overlay_state = {}
            if getattr(self, "browser_overlay", None) is not None:
                try:
                    snap = self.browser_overlay.snapshot()
                    overlay_state = {
                        "seq": snap.get("seq"),
                        "events_tail": list((snap.get("events") or [])[-12:]),
                        "blueHasImage": bool(snap.get("blueHasImage")),
                        "redHasImage": bool(snap.get("redHasImage")),
                        "blueName": snap.get("blueName"),
                        "redName": snap.get("redName"),
                    }
                except Exception as exc:
                    overlay_state = {"error": f"overlay snapshot failed: {exc}"}
            backend = getattr(getattr(self, "timer_win", None), "_backend", None)
            return {
                "app_version": APP_VERSION,
                "cfg_path": self.cfg_path,
                "time": datetime.now().isoformat(timespec="seconds"),
                "timer": {
                    "round": int(getattr(self.cfg, "timer_current_round", 1) or 1),
                    "total_rounds": int(getattr(self.cfg, "timer_total_rounds", 3) or 3),
                    "seconds_left": int(getattr(self.cfg, "timer_seconds_left", 0) or 0),
                    "round_sec": int(getattr(self.cfg, "timer_round_sec", 180) or 180),
                    "rest_sec": int(getattr(self.cfg, "timer_rest_sec", 60) or 60),
                },
                "spectatorlog": {
                    "enabled": bool(getattr(self.cfg, "spectatorlog_enabled", False)),
                    "running": bool(getattr(self, "spectator_watcher", None) and self.spectator_watcher.is_running()),
                    "path": str(getattr(self.cfg, "spectatorlog_path", "") or ""),
                    "resolved_path": self._diagnostic_spectator_root(),
                },
                "players": {
                    "blue_id": str(getattr(self, "_current_blue_id", "") or ""),
                    "red_id": str(getattr(self, "_current_red_id", "") or ""),
                    "blue_registered": bool(getattr(self, "_current_blue_registered", False)),
                    "red_registered": bool(getattr(self, "_current_red_registered", False)),
                },
                "detectors": {
                    "screen_running": bool(self._screen_detection_running() if self._screen_detection_running else False),
                    "log_running": bool(self._log_detection_running() if self._log_detection_running else False),
                },
                "overlay": overlay_state,
                "backend_state": {"exists": bool(backend is not None)},
                "diagnostics": DIAG.summary(mask_sensitive=True),
            }
        except Exception as exc:
            return {"error": str(exc)}

    def _diagnostic_mark_incident(self, note: str = "") -> object:
        item = DIAG.mark_incident(note or "사용자 문제 발생 표시")
        try:
            self.timer_win.set_status("진단: 문제 발생 시점 표시 완료")
        except Exception:
            pass
        return item

    def _diagnostic_export_zip(self) -> str:
        try:
            DIAG.set_options(
                enabled=bool(getattr(self.cfg, "diagnostics_enabled", True)),
                max_events=max(500, int(getattr(self.cfg, "diagnostics_trace_minutes", 10) or 10) * 500),
                raw_sample_lines=int(getattr(self.cfg, "diagnostics_raw_sample_lines", 120) or 120),
                mask_sensitive=bool(getattr(self.cfg, "diagnostics_mask_sensitive", True)),
            )
        except Exception:
            pass
        root = self._diagnostic_spectator_root()
        overlay_snapshot = {}
        try:
            if getattr(self, "browser_overlay", None) is not None:
                overlay_snapshot = self.browser_overlay.snapshot()
        except Exception:
            overlay_snapshot = {"error": "snapshot failed"}
        path = DIAG.export_zip(
            self._diagnostic_folder(),
            app_state=self._diagnostic_app_state(),
            cfg_snapshot=getattr(self.cfg, "__dict__", {}),
            spectator_root=root,
            overlay_snapshot=overlay_snapshot,
            mask_sensitive=bool(getattr(self.cfg, "diagnostics_mask_sensitive", True)),
            raw_sample_lines=int(getattr(self.cfg, "diagnostics_raw_sample_lines", 120) or 120),
        )
        try:
            self.timer_win.set_status(f"진단 ZIP 생성: {os.path.basename(path)}")
        except Exception:
            pass
        return path

    def _project_snapshot_export_zip(self) -> str:
        try:
            DIAG.set_options(
                enabled=bool(getattr(self.cfg, "diagnostics_enabled", True)),
                max_events=max(500, int(getattr(self.cfg, "diagnostics_trace_minutes", 10) or 10) * 500),
                raw_sample_lines=int(getattr(self.cfg, "diagnostics_raw_sample_lines", 120) or 120),
                mask_sensitive=bool(getattr(self.cfg, "diagnostics_mask_sensitive", True)),
            )
        except Exception:
            pass
        try:
            project_root = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            project_root = os.getcwd()
        path = export_project_snapshot(
            project_root,
            self._diagnostic_folder(),
            app_state=self._diagnostic_app_state(),
            cfg_snapshot=getattr(self.cfg, "__dict__", {}),
            spectator_root=self._diagnostic_spectator_root(),
            mask_sensitive=bool(getattr(self.cfg, "diagnostics_mask_sensitive", True)),
            raw_sample_lines=int(getattr(self.cfg, "diagnostics_raw_sample_lines", 120) or 120),
        )
        try:
            self.timer_win.set_status(f"프로젝트 스냅샷 생성: {os.path.basename(path)}")
        except Exception:
            pass
        return path

    def _diagnostic_open_folder(self) -> str:
        return self._diagnostic_folder()

    def _diagnostic_copy_state(self) -> str:
        return DIAG.current_state_text(self._diagnostic_app_state())

    def open_settings(self):
        if self.settings_dlg and self.settings_dlg.isVisible():
            try:
                if self.timer_win and hasattr(self.timer_win, "set_overlay_on_top"):
                    # Keep the overlay from covering the settings dialog while it is open.
                    self.timer_win.set_overlay_on_top(False)
            except Exception:
                pass
            self.settings_dlg.raise_()
            self.settings_dlg.activateWindow()
            return
        try:
            if self.timer_win and hasattr(self.timer_win, "set_overlay_on_top"):
                # Temporarily drop the always-on-top overlay so the settings dialog is visible.
                self.timer_win.set_overlay_on_top(False)
        except Exception:
            pass
        try:
            self.settings_dlg = SettingsDialog(
                None,
                self.cfg,
                self.controller,
                self.watcher,
                self.cfg_path,
                self.timer_win,
                chapter_sync_now=self._sync_chapter_anchor_now,
                chapter_clear=self._clear_chapter_anchor,
                chapter_export=self._export_chapter_txt,
                chapter_open=self._open_chapter_txt,
                chapter_status_getter=self._chapter_anchor_status,
                action_runner=self.action_runner,
                player_state_apply=self._apply_saved_player_state,
                detection_start=self._start_detectors,
                detection_stop=self._stop_detectors,
                detection_running=self._detection_running,
                screen_detection_start=self._start_screen_detector,
                screen_detection_stop=self._stop_screen_detector,
                screen_detection_running=self._screen_detection_running,
                log_detection_start=self._start_log_detector,
                log_detection_stop=self._stop_log_detector,
                log_detection_running=self._log_detection_running,
                diagnostic_mark_incident=self._diagnostic_mark_incident,
                diagnostic_export_zip=self._diagnostic_export_zip,
                diagnostic_open_folder=self._diagnostic_open_folder,
                diagnostic_copy_state=self._diagnostic_copy_state,
                diagnostic_project_snapshot=self._project_snapshot_export_zip,
            )
        except Exception as e:
            logging.exception("Failed to open settings dialog")
            try:
                QMessageBox.critical(None, "설정 오류", f"설정창을 열 수 없습니다.\n\n{e}")
            except Exception:
                pass
            return
        self.settings_dlg.finished.connect(self.on_settings_closed)
        self.settings_dlg.show()
        try:
            self.settings_dlg.raise_()
            self.settings_dlg.activateWindow()
        except Exception:
            pass

    def on_settings_closed(self, _):
        try:
            if self.timer_win and hasattr(self.timer_win, "set_overlay_on_top"):
                self.timer_win.set_overlay_on_top(True)
        except Exception:
            pass
        try:
            if bool(getattr(self.cfg, "spectatorlog_enabled", False)):
                # SpectatorLog detection is independent from pixel detection.
                # Do not require ScreenWatcher to be running when settings are applied.
                self._start_spectator_watcher_if_enabled()
            elif getattr(self, "spectator_watcher", None) and self.spectator_watcher.is_running():
                # Settings can be closed from the GUI thread; keep SpectatorLog stop async.
                self._stop_log_detector()
        except Exception:
            pass
        try:
            self.cfg.to_json(self.cfg_path)
        except Exception:
            pass

    def _stop_spectator_hud_demo(self):
        dlg = self.settings_dlg
        if dlg is not None and hasattr(dlg, "_stop_spectator_hud_demo"):
            try:
                dlg._stop_spectator_hud_demo()
                return
            except Exception:
                pass
        try:
            self.timer_win._backend.set_hud_demo_running(False)
        except Exception:
            pass
        try:
            self.timer_win.set_spectator_log_info({
                "blue_combo_hit_text": "",
                "blue_combo_damage_text": "",
                "red_combo_hit_text": "",
                "red_combo_damage_text": "",
            })
        except Exception:
            pass

    def _spectator_test_dialog(self):
        if self.settings_dlg is None:
            self.open_settings()
            try:
                if self.settings_dlg is not None:
                    self.settings_dlg.hide()
            except Exception:
                pass
        return self.settings_dlg

    def _push_browser_overlay_event(self, kind: str, **payload):
        try:
            if getattr(self, "browser_overlay", None) is not None:
                if str(kind or "").lower() == "vs":
                    try:
                        self.browser_overlay_sync.publish()
                    except Exception:
                        logging.exception("BROWSER_OVERLAY_PREPUBLISH_FAIL kind=%s", kind)
                try:
                    DIAG.record("overlay_event_request", kind=str(kind or ""), payload=payload)
                except Exception:
                    pass
                self.browser_overlay.push_event(str(kind or ""), **payload)
                return True
        except Exception:
            logging.exception("BROWSER_OVERLAY_PUSH_FAIL kind=%s payload=%s", kind, payload)
        return False

    def _push_initial_browser_overlay_settings(self):
        try:
            overlay = getattr(self, "browser_overlay", None)
            if overlay is None:
                return
            style_time = dict(getattr(self.cfg, "overlay_style_time", {}) or {})
            style_round = dict(getattr(self.cfg, "overlay_style_round", {}) or {})
            overlay.update(
                overlayBgColor=str(getattr(self.cfg, "overlay_bg_color", "transparent") or "transparent"),
                overlayBgOpacity=max(0.0, min(1.0, float(getattr(self.cfg, "overlay_bg_opacity", 0.0) or 0.0))),
                overlayUiScale=float(getattr(self.cfg, "overlay_ui_scale", 1.0) or 1.0),
                browserOverlayScale=float(getattr(self.cfg, "browser_overlay_scale", 1.0) or 1.0),
                browserFullscreenFxIntensity=max(0.0, min(3.0, float(getattr(self.cfg, "browser_fullscreen_fx_intensity", 1.6) or 1.6))),
                overlayTimerFontSize=int(getattr(self.cfg, "overlay_timer_font_size", 54) or 54),
                overlayTimerX=int(getattr(self.cfg, "overlay_timer_x", 0) or 0),
                overlayTimerY=int(getattr(self.cfg, "overlay_timer_y", 0) or 0),
                overlayRoundFontSize=int(getattr(self.cfg, "overlay_round_font_size", 11) or 11),
                overlayRoundX=int(getattr(self.cfg, "overlay_round_x", 0) or 0),
                overlayRoundY=int(getattr(self.cfg, "overlay_round_y", 0) or 0),
                overlayTimerOpacity=max(0.0, min(1.0, float(style_time.get("text_opacity", 1.0) or 1.0))),
                overlayRoundOpacity=max(0.0, min(1.0, float(style_round.get("text_opacity", 1.0) or 1.0))),
                browserTextStyles=_normalize_browser_text_styles(getattr(self.cfg, "browser_text_styles", {}) or {}),
                showRound=bool(getattr(self.cfg, "overlay_show_round", True)),
                showTime=bool(getattr(self.cfg, "overlay_show_time", True)),
                showBlueImage=bool(getattr(self.cfg, "overlay_show_blue_img", True)),
                showBlueName=bool(getattr(self.cfg, "overlay_show_blue_name", True)),
                showRedImage=bool(getattr(self.cfg, "overlay_show_red_img", True)),
                showRedName=bool(getattr(self.cfg, "overlay_show_red_name", True)),
                showArenaName=bool(getattr(self.cfg, "overlay_show_arena_name", True)),
                showFlags=bool(getattr(self.cfg, "overlay_show_flags", True)),
                showCinematic=bool(getattr(self.cfg, "overlay_show_cinematic", True)),
                vsBgOpacity=max(0.0, min(1.0, float(getattr(self.cfg, "overlay_vs_bg_opacity", 1.0) or 1.0))),
                overlayVsHoldMs=int(max(500, min(15000, float(getattr(self.cfg, "overlay_vs_hold_sec", 2.85) or 2.85) * 1000))),
            )
            asset_update = self._sync_browser_overlay_player_assets({})
            if asset_update:
                overlay.update(**asset_update)
        except Exception:
            logging.exception("BROWSER_OVERLAY_INITIAL_SETTINGS_FAIL")

    def _reset_browser_overlay_sp(self) -> None:
        self._browser_sp_ratio = {"blue": 1.0, "red": 1.0}
        self._browser_sp_last_damage = {"blue": 0.0, "red": 0.0}
        self._browser_sp_recovery_delay = {"blue": 0.0, "red": 0.0}
        self._browser_sp_last_fight_seconds = None
        self._browser_sp_last_rest_seconds = None

    def _browser_overlay_sp_update(self, d: dict, state: dict) -> Dict[str, float]:
        ratios = dict(getattr(self, "_browser_sp_ratio", {}) or {})
        last_damage = dict(getattr(self, "_browser_sp_last_damage", {}) or {})
        delay = dict(getattr(self, "_browser_sp_recovery_delay", {}) or {})
        for side in ("blue", "red"):
            try:
                ratios[side] = max(0.0, min(1.0, float(ratios.get(side, state.get(side + "SpRatio", 1.0)) or 0.0)))
            except Exception:
                ratios[side] = 1.0
            try:
                last_damage[side] = max(0.0, float(last_damage.get(side, 0.0) or 0.0))
            except Exception:
                last_damage[side] = 0.0
            try:
                delay[side] = max(0.0, float(delay.get(side, 0.0) or 0.0))
            except Exception:
                delay[side] = 0.0

        if bool(d.get("spectator_sp_reset", False)) or bool(d.get("spectator_match_stats_reset", False)):
            ratios = {"blue": 1.0, "red": 1.0}
            last_damage = {"blue": 0.0, "red": 0.0}
            delay = {"blue": 0.0, "red": 0.0}
            self._browser_sp_last_fight_seconds = None
            self._browser_sp_last_rest_seconds = None

        for side, key in (("blue", "blue_round_damage_dealt"), ("red", "red_round_damage_dealt")):
            if key not in d:
                continue
            try:
                dealt = max(0.0, float(d.get(key, 0.0) or 0.0))
            except Exception:
                dealt = 0.0
            prev = float(last_damage.get(side, 0.0) or 0.0)
            if dealt >= prev:
                delta = dealt - prev
                if delta > 0:
                    ratios[side] = max(0.0, ratios[side] - (delta / 3000.0))
                    delay[side] = 1.2
            last_damage[side] = dealt

        if "seconds_left" in d:
            try:
                cur = max(0, int(float(d.get("seconds_left", 0) or 0)))
            except Exception:
                cur = None
            if cur is not None:
                is_rest = bool(d.get("spectator_rest_mode", False))
                if is_rest:
                    self._browser_sp_last_fight_seconds = None
                    prev = self._browser_sp_last_rest_seconds
                    self._browser_sp_last_rest_seconds = cur
                    if prev is not None:
                        elapsed = max(0, int(prev) - cur)
                        if elapsed > 0:
                            rest_sec = max(1, int(getattr(self.cfg, "timer_rest_sec", 60) or 60))
                            gain = 0.60 * (float(elapsed) / float(rest_sec))
                            ratios["blue"] = min(1.0, ratios["blue"] + gain)
                            ratios["red"] = min(1.0, ratios["red"] + gain)
                else:
                    self._browser_sp_last_rest_seconds = None
                    prev = self._browser_sp_last_fight_seconds
                    self._browser_sp_last_fight_seconds = cur
                    if prev is not None:
                        elapsed = max(0, int(prev) - cur)
                        if elapsed > 0:
                            round_sec = max(1, int(getattr(self.cfg, "timer_round_sec", 180) or 180))
                            for side in ("blue", "red"):
                                recover_elapsed = float(elapsed)
                                if delay[side] > 0:
                                    used = min(delay[side], recover_elapsed)
                                    delay[side] -= used
                                    recover_elapsed -= used
                                if recover_elapsed > 0:
                                    gain = 0.30 * (recover_elapsed / float(round_sec))
                                    ratios[side] = min(1.0, ratios[side] + gain)

        self._browser_sp_ratio = ratios
        self._browser_sp_last_damage = last_damage
        self._browser_sp_recovery_delay = delay
        return {
            "blueSpRatio": float(ratios.get("blue", 1.0)),
            "redSpRatio": float(ratios.get("red", 1.0)),
        }

    def _browser_overlay_lives_update(self, d: dict, state: dict) -> Dict[str, int]:
        counts = dict(getattr(self, "_browser_round_knockdowns", {}) or {})
        for side in ("blue", "red"):
            try:
                counts[side] = max(0, min(3, int(counts.get(side, state.get(side + "RoundKnockdowns", 0)) or 0)))
            except Exception:
                counts[side] = 0

        if bool(d.get("spectator_match_stats_reset", False)) or bool(d.get("spectator_match_clear", False)):
            counts = {"blue": 0, "red": 0}
            self._browser_knockdown_round_key = None

        if "round_current" in d:
            try:
                round_key = int(float(d.get("round_current") or 0))
            except Exception:
                round_key = None
            if round_key is not None:
                prev_key = getattr(self, "_browser_knockdown_round_key", None)
                if prev_key is not None and prev_key != round_key:
                    counts = {"blue": 0, "red": 0}
                self._browser_knockdown_round_key = round_key

        info = dict(d.get("spectator_log_info") or {}) if "spectator_log_info" in d else {}
        for side in ("blue", "red"):
            key = f"{side}_round_knockdowns"
            if key in info:
                try:
                    counts[side] = max(0, min(3, int(info.get(key) or 0)))
                except Exception:
                    pass

        for ev in list(d.get("spectator_effect_events") or []):
            ev = dict(ev or {})
            side = str(ev.get("side") or "").lower()
            kind = str(ev.get("kind") or "").lower()
            if side in ("blue", "red") and kind in ("knockdown", "tko"):
                counts[side] = max(0, min(3, int(counts.get(side, 0) or 0) + 1))

        self._browser_round_knockdowns = counts
        return {
            "blueRoundKnockdowns": int(counts.get("blue", 0) or 0),
            "redRoundKnockdowns": int(counts.get("red", 0) or 0),
        }

    def _start_spectator_replay_from_overlay(self):
        dlg = self._spectator_test_dialog()
        if dlg is not None and hasattr(dlg, "_test_spectator_last_log"):
            try:
                dlg._test_spectator_last_log()
            except Exception as e:
                logging.exception("OVERLAY_SPECTATOR_REPLAY_FAIL")
                try:
                    self.timer_win.set_status(f"과거 로그 리플레이 실패: {e}")
                except Exception:
                    pass

    def _start_spectator_full_demo_from_overlay(self):
        dlg = self._spectator_test_dialog()
        if dlg is not None and hasattr(dlg, "_test_spectator_full_demo"):
            try:
                dlg._test_spectator_full_demo()
            except Exception as e:
                logging.exception("OVERLAY_SPECTATOR_FULL_DEMO_FAIL")
                try:
                    self.timer_win.set_status(f"전체 HUD 데모 실패: {e}")
                except Exception:
                    pass

    def _start_spectator_vs_intro_from_overlay(self):
        dlg = self._spectator_test_dialog()
        if dlg is not None and hasattr(dlg, "_test_spectator_vs_intro"):
            try:
                dlg._test_spectator_vs_intro()
            except Exception as e:
                logging.exception("OVERLAY_SPECTATOR_VS_TEST_FAIL")
                try:
                    self.timer_win.set_status(f"VS 오버레이 테스트 실패: {e}")
                except Exception:
                    pass

    def _on_overlay_ui_scale_changed(self):
        try:
            scale = float(self.timer_win._backend.overlayUiScale)
        except Exception:
            scale = 1.0
        if scale <= 0:
            scale = 1.0
        try:
            self.cfg.overlay_ui_scale = scale
        except Exception:
            pass
        try:
            self.cfg.to_json(self.cfg_path)
        except Exception:
            pass
        try:
            if getattr(self, "browser_overlay", None):
                self.browser_overlay.update(
                    overlayUiScale=float(scale),
                    showTime=bool(getattr(self.cfg, "overlay_show_time", True)),
                    showRound=bool(getattr(self.cfg, "overlay_show_round", True)),
                )
        except Exception:
            pass
        try:
            if self.timer_win and hasattr(self.timer_win, "set_overlay_on_top"):
                self.timer_win.set_overlay_on_top(True)
        except Exception:
            pass
        if self.settings_dlg and hasattr(self.settings_dlg, "sl_overlay_scale"):
            sl = getattr(self.settings_dlg, "sl_overlay_scale", None)
            sp = getattr(self.settings_dlg, "sp_overlay_scale", None)
            try:
                if sl is not None:
                    sl.blockSignals(True)
                if sp is not None:
                    sp.blockSignals(True)
                if sl is not None:
                    sl.setValue(int(scale * 100))
                if sp is not None:
                    sp.setValue(int(scale * 100))
                if hasattr(self.settings_dlg, "lbl_overlay_scale"):
                    self.settings_dlg.lbl_overlay_scale.setText(f"{int(scale * 100)}%")
            except RuntimeError:
                pass
            except Exception:
                logging.debug("OVERLAY_SCALE_SETTINGS_SYNC_FAIL", exc_info=True)
            finally:
                try:
                    if sl is not None:
                        sl.blockSignals(False)
                    if sp is not None:
                        sp.blockSignals(False)
                except Exception:
                    pass

    def _on_overlay_bg_changed(self):
        try:
            color = str(self.timer_win._backend.overlayBgColor or "transparent")
        except Exception:
            color = "transparent"
        try:
            opacity = float(self.timer_win._backend.overlayBgOpacity)
        except Exception:
            opacity = 0.0
        opacity = max(0.0, min(1.0, opacity))
        try:
            self.cfg.overlay_bg_color = _normalize_hex_color(color)
            self.cfg.overlay_bg_opacity = opacity
            self.cfg.to_json(self.cfg_path)
        except Exception:
            pass
        try:
            if getattr(self, "browser_overlay", None):
                self.browser_overlay.update(overlayBgColor=str(color or "transparent"), overlayBgOpacity=float(opacity))
        except Exception:
            pass
        if self.settings_dlg and hasattr(self.settings_dlg, "sl_overlay_opacity"):
            sl = getattr(self.settings_dlg, "sl_overlay_opacity", None)
            try:
                if sl is not None:
                    sl.blockSignals(True)
                    sl.setValue(int((1.0 - opacity) * 100))
                if hasattr(self.settings_dlg, "lbl_overlay_opacity"):
                    self.settings_dlg.lbl_overlay_opacity.setText(f"{int((1.0 - opacity) * 100)}%")
            except RuntimeError:
                pass
            except Exception:
                logging.debug("OVERLAY_BG_SETTINGS_SYNC_FAIL", exc_info=True)
            finally:
                try:
                    if sl is not None:
                        sl.blockSignals(False)
                except Exception:
                    pass

    def _on_overlay_ui_bg_opacity_changed(self):
        try:
            opacity = float(self.timer_win._backend.overlayUiBgOpacity)
        except Exception:
            opacity = 0.75
        opacity = max(0.0, min(1.0, opacity))
        try:
            self.cfg.overlay_ui_bg_opacity = opacity
            self.cfg.to_json(self.cfg_path)
        except Exception:
            pass

    def _on_overlay_window_opacity_changed(self):
        try:
            opacity = float(self.timer_win._backend.overlayWindowOpacity)
        except Exception:
            opacity = 1.0
        opacity = max(0.2, min(1.0, opacity))
        try:
            self.cfg.overlay_window_opacity = opacity
            self.cfg.to_json(self.cfg_path)
        except Exception:
            pass

    def on_app_quit(self):
        try:
            if self.settings_dlg:
                if hasattr(self.settings_dlg, "_apply_timer"):
                    try:
                        self.settings_dlg._apply_timer.stop()
                    except Exception:
                        pass
                self.settings_dlg.apply_only(silent=True)
        except Exception:
            pass
        try:
            if self._global_hotkeys_enabled:
                self._global_hotkeys.stop()
        except Exception:
            pass
        try:
            self.cfg.to_json(self.cfg_path)
        except Exception:
            pass
        try:
            if self._hotkey_timer:
                self._hotkey_timer.stop()
        except Exception:
            pass
        try:
            if self._chapter_autosave_timer:
                self._chapter_autosave_timer.stop()
        except Exception:
            pass
        try:
            if self._browser_overlay_timer:
                self._browser_overlay_timer.stop()
        except Exception:
            pass
        try:
            self.browser_overlay.stop()
        except Exception:
            pass
        try:
            self._export_chapter_txt()
        except Exception:
            pass

    def check_for_updates(self, silent: bool = False):
        if getattr(self, "_update_check_busy", False):
            if not silent:
                self._show_update_message("information", "Update", "Update check is already running.")
            return
        self._update_check_busy = True
        if not silent:
            try:
                self.timer_win.set_status("업데이트 확인 중...")
            except Exception:
                pass

        def _work():
            try:
                req = Request(UPDATE_FEED_URL, headers={"User-Agent": "TimerAuto-Updater"})
                with urlopen(req, timeout=30) as resp:
                    meta = json.loads(resp.read().decode("utf-8-sig", errors="replace"))
                latest = str(meta.get("version") or "").strip()
                url = str(meta.get("url") or "").strip()
                sha256 = str(meta.get("sha256") or "").strip().lower()
                notes = str(meta.get("notes") or "").strip()
                if not latest or not url:
                    raise RuntimeError("Invalid update metadata.")
                self._update_metadata_ready.emit(
                    {"latest": latest, "url": url, "sha256": sha256, "notes": notes},
                    bool(silent),
                )
            except Exception as e:
                logging.warning("UPDATE_CHECK_FAIL: %s", e, exc_info=True)
                self._update_error_ready.emit(str(e), bool(silent))

        threading.Thread(target=_work, daemon=True).start()

    def _finish_update_check_error(self, msg: str, silent: bool = False):
        self._update_check_busy = False
        if not silent:
            self._show_update_message("warning", "Update", f"Update check failed:\n{msg}")

    def _update_dialog_parent(self):
        try:
            if getattr(self, "settings_dlg", None) is not None and self.settings_dlg.isVisible():
                return self.settings_dlg
        except Exception:
            pass
        try:
            active = QApplication.activeWindow()
            if isinstance(active, QWidget):
                return active
        except Exception:
            pass
        return None

    def _show_update_message(self, icon: str, title: str, text: str) -> QMessageBox.StandardButton:
        box = QMessageBox(self._update_dialog_parent())
        icon_name = str(icon or "").lower()
        if icon_name == "warning":
            box.setIcon(QMessageBox.Icon.Warning)
        elif icon_name == "critical":
            box.setIcon(QMessageBox.Icon.Critical)
        else:
            box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(str(title or "Update"))
        box.setText(str(text or ""))
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setDefaultButton(QMessageBox.StandardButton.Ok)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        try:
            box.raise_()
            box.activateWindow()
        except Exception:
            pass
        return box.exec()

    def _ask_update_question(self, title: str, text: str) -> QMessageBox.StandardButton:
        box = QMessageBox(self._update_dialog_parent())
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(str(title or "Update"))
        box.setText(str(text or ""))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        try:
            box.raise_()
            box.activateWindow()
        except Exception:
            pass
        return box.exec()

    def _handle_update_metadata(self, meta: dict, silent: bool = False):
        latest = str(meta.get("latest") or "")
        if _parse_version(latest) <= _parse_version(APP_VERSION):
            self._update_check_busy = False
            if not silent:
                self._show_update_message("information", "Update", f"Already up to date.\nCurrent: {APP_VERSION}")
            return
        notes = str(meta.get("notes") or "")
        msg = f"A new version is available.\n\nCurrent: {APP_VERSION}\nLatest: {latest}"
        if notes:
            msg += f"\n\n{notes}"
        msg += "\n\nDownload it now?"
        resp = self._ask_update_question("Update", msg)
        if resp != QMessageBox.StandardButton.Yes:
            self._update_check_busy = False
            return
        self._download_and_apply_update(meta)

    def _download_and_apply_update(self, meta: dict):
        url = str(meta.get("url") or "")
        sha256 = str(meta.get("sha256") or "").strip().lower()
        latest = str(meta.get("latest") or "latest")
        if not url:
            self._finish_update_check_error("Missing download URL.")
            return
        self._show_update_message("information", "Update", "Downloading update. Please wait.")

        def _work():
            try:
                work_dir = os.path.join(tempfile.gettempdir(), "timerauto_update")
                os.makedirs(work_dir, exist_ok=True)
                zip_path = os.path.join(work_dir, f"TimerAuto_{latest}_portable.zip")
                _download_file(url, zip_path)
                if sha256:
                    actual = _file_sha256(zip_path)
                    if actual != sha256:
                        raise RuntimeError("Downloaded file checksum mismatch.")
                self._update_download_ready.emit(zip_path)
            except Exception as e:
                logging.warning("UPDATE_DOWNLOAD_FAIL: %s", e, exc_info=True)
                self._update_error_ready.emit(str(e), False)

        threading.Thread(target=_work, daemon=True).start()

    def _confirm_apply_update(self, zip_path: str):
        self._update_check_busy = False
        if not getattr(sys, "frozen", False):
            self._show_update_message(
                "information",
                "Update",
                f"Download and checksum verification completed.\nAutomatic replacement is disabled in development mode.\n\n{zip_path}",
            )
            return
        try:
            exe_path = os.path.abspath(sys.executable)
            app_dir = os.path.dirname(exe_path)
            script = _write_update_script(zip_path, app_dir, exe_path, os.getpid())
        except Exception as e:
            self._show_update_message("warning", "Update", f"Failed to prepare update:\n{e}")
            return
        resp = self._ask_update_question("Update", "Download completed.\nClose TimerAuto and apply the update now?")
        if resp != QMessageBox.StandardButton.Yes:
            return
        try:
            import subprocess
            creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
                close_fds=True,
                creationflags=creation_flags,
            )
            QApplication.quit()
        except Exception as e:
            self._show_update_message("warning", "Update", f"Failed to launch updater:\n{e}")

    def _global_pick_busy(self) -> bool:
        if self._quick_pick_active:
            return True
        if self._pixel_pick_overlay and self._pixel_pick_overlay.isVisible():
            return True
        if self._trigger_pixel_overlay and self._trigger_pixel_overlay.isVisible():
            return True
        if self.settings_dlg and getattr(self.settings_dlg, "_quick_pick_active", False):
            return True
        return False

    def _ensure_settings(self):
        if self.settings_dlg and self.settings_dlg.isVisible():
            return
        self.open_settings()

    def _run_action_test_hotkey(self):
        self._ensure_settings()
        if not self.settings_dlg:
            return
        QTimer.singleShot(0, lambda: self.settings_dlg and self.settings_dlg._test_event_actions())

    def _monitor_from_pos(self, x: int, y: int) -> int:
        with mss.mss() as sct:
            mons = sct.monitors
            for i in range(1, len(mons)):
                mon = mons[i]
                if mon["left"] <= x < mon["left"] + mon["width"] and mon["top"] <= y < mon["top"] + mon["height"]:
                    return i
        return int(self.cfg.monitor_index)

    def _monitor_to_local(self, monitor_index: int, x: int, y: int) -> tuple[int, int]:
        with mss.mss() as sct:
            mons = sct.monitors
            if monitor_index < 1 or monitor_index >= len(mons):
                return x, y
            mon = mons[monitor_index]
            return int(x - mon["left"]), int(y - mon["top"])

    def _vk_from_key_name(self, name: str) -> Optional[int]:
        if not name:
            return None
        key = name.upper()
        if key.startswith("F") and key[1:].isdigit():
            n = int(key[1:])
            if 1 <= n <= 12:
                return 0x70 + (n - 1)
        if len(key) == 1:
            ch = key[0]
            if "A" <= ch <= "Z":
                return ord(ch)
            if "0" <= ch <= "9":
                return 0x30 + int(ch)
        return None

    def _parse_hotkey(self, seq: str) -> Optional[Tuple[int, dict]]:
        if not seq:
            return None
        parts = [p for p in seq.replace(" ", "").split("+") if p]
        mods = {"ctrl": False, "alt": False, "shift": False}
        key_part = ""
        for part in parts:
            up = part.upper()
            if up in ("CTRL", "CONTROL"):
                mods["ctrl"] = True
            elif up == "ALT":
                mods["alt"] = True
            elif up == "SHIFT":
                mods["shift"] = True
            else:
                key_part = up
        vk = self._vk_from_key_name(key_part)
        if vk is None:
            return None
        return vk, mods

    def _hotkey_info(self, seq: str) -> Optional[Tuple[int, dict]]:
        if seq in self._hotkey_cache:
            return self._hotkey_cache[seq]
        info = self._parse_hotkey(seq)
        self._hotkey_cache[seq] = info
        return info

    def _roi_quick_items(self) -> List[Tuple[str, str]]:
        return [
            ("왼쪽 선수 이미지 범위 (= BLUE)", "roi_left_player"),
            ("오른쪽 선수 이미지 범위 (= RED)", "roi_right_player"),
        ]
    def _apply_global_roi(self, attr_name: str, rect: Rect):
        if self._quick_roi_monitor is not None:
            rect = rect_local_to_global(int(self._quick_roi_monitor), rect)
        elif self._quick_roi_virtual_offset is not None:
            dx, dy = self._quick_roi_virtual_offset
            rect = Rect(x=int(rect.x + dx), y=int(rect.y + dy), w=int(rect.w), h=int(rect.h))
        setattr(self.cfg, attr_name, rect)
        if self.settings_dlg:
            try:
                self.settings_dlg._apply_quick_roi(attr_name, rect)
            except Exception:
                pass

    def _start_global_roi_pick(self):
        if self._quick_pick_active:
            return
        if self._quick_roi_overlay:
            try:
                if self._quick_roi_overlay.isVisible():
                    return
            except RuntimeError:
                self._quick_roi_overlay = None
        try:
            if self._quick_roi_overlay:
                self._quick_roi_overlay.close()
        except Exception:
            pass
        self._quick_roi_overlay = None
        try:
            QuickRoiOverlay.close_all()
        except Exception:
            pass
        pos = QCursor.pos()
        try:
            with mss.mss() as sct:
                mon = sct.monitors[0]
                frame = np.array(sct.grab(mon))
                self._quick_roi_virtual_offset = (int(mon["left"]), int(mon["top"]))
        except Exception:
            mon = self._monitor_from_pos(pos.x(), pos.y())
            frame = capture_monitor_np(mon)
            self._quick_roi_virtual_offset = None
        self._quick_pick_active = True
        self._quick_roi_monitor = None
        self._quick_roi_overlay = QuickRoiOverlay(0, frame, self._roi_quick_items(), self._apply_global_roi)
        self._quick_roi_overlay.destroyed.connect(lambda _o=None: setattr(self, "_quick_pick_active", False))
        self._quick_roi_overlay.destroyed.connect(lambda _o=None: setattr(self, "_quick_roi_virtual_offset", None))
        self._quick_roi_overlay.show()
        self._quick_roi_overlay.raise_()

    def _cancel_global_roi_pick(self):
        self._quick_roi_overlay = None
        self._quick_pick_active = False
        try:
            QuickRoiOverlay.close_all()
        except Exception:
            pass

    def _start_global_pixel_pick(self):
        if self._pixel_pick_overlay and self._pixel_pick_overlay.isVisible():
            self._finish_global_pixel_pick()
            return
        if self._quick_pick_active:
            return
        self._quick_pick_active = True
        self._pixel_pick_overlay = PixelPickOverlay(self._sample_pixel_at_global)
        rect = QGuiApplication.primaryScreen().geometry()
        for scr in QGuiApplication.screens():
            rect = rect.united(scr.geometry())
        self._pixel_pick_overlay.setGeometry(rect)
        self._pixel_pick_overlay.destroyed.connect(lambda _o=None: setattr(self, "_quick_pick_active", False))
        self._pixel_pick_overlay.destroyed.connect(lambda _o=None: setattr(self, "_pixel_pick_overlay", None))
        self._pixel_pick_overlay.show()

    def _start_global_trigger_pixel_pick(self):
        if self._trigger_pixel_overlay and self._trigger_pixel_overlay.isVisible():
            self._finish_global_trigger_pixel_pick()
            return
        if self._quick_pick_active:
            return
        self._quick_pick_active = True
        overlay = PixelPickOverlay(
            self._sample_pixel_at_global,
            message="트리거 픽셀 선택: 마우스를 움직이고 단축키를 다시 누르면 적용됩니다. (ESC 취소)",
            accept_on_key=True,
            on_accept=self._finish_global_trigger_pixel_pick,
        )
        rect = QGuiApplication.primaryScreen().geometry()
        for scr in QGuiApplication.screens():
            rect = rect.united(scr.geometry())
        overlay.setGeometry(rect)
        overlay.destroyed.connect(lambda _o=None: setattr(self, "_quick_pick_active", False))
        overlay.destroyed.connect(lambda _o=None: setattr(self, "_trigger_pixel_overlay", None))
        overlay.show()
        overlay.raise_()
        self._trigger_pixel_overlay = overlay

    def _finish_global_pixel_pick(self):
        if not self._pixel_pick_overlay:
            return
        pos, bgr = self._pixel_pick_overlay.current_sample()
        self._quick_pick_active = False
        try:
            self._pixel_pick_overlay.close()
        except Exception:
            pass
        self._pixel_pick_overlay = None
        self._show_pixel_pick_menu_main(QCursor.pos(), int(pos.x()), int(pos.y()), bgr)

    def _finish_global_trigger_pixel_pick(self):
        if not self._trigger_pixel_overlay:
            return
        pos, bgr = self._trigger_pixel_overlay.current_sample()
        self._quick_pick_active = False
        try:
            self._trigger_pixel_overlay.close()
        except Exception:
            pass
        self._trigger_pixel_overlay = None
        self.cfg.roi_trigger = Rect(x=int(pos.x()), y=int(pos.y()), w=1, h=1)
        self.cfg.trigger.target_bgr = (int(bgr[0]), int(bgr[1]), int(bgr[2]))
        self.cfg.trigger.enabled = True
        try:
            self.cfg.to_json(self.cfg_path)
        except Exception:
            pass
        if self.settings_dlg:
            try:
                self.settings_dlg._apply_trigger_pixel_from_sample(pos, bgr)
            except Exception:
                pass

    def _cancel_global_pixel_pick(self):
        if not self._pixel_pick_overlay:
            return
        self._quick_pick_active = False
        try:
            self._pixel_pick_overlay.close()
        except Exception:
            pass
        self._pixel_pick_overlay = None

    def _cancel_global_trigger_pixel_pick(self):
        if not self._trigger_pixel_overlay:
            return
        self._quick_pick_active = False
        try:
            self._trigger_pixel_overlay.close()
        except Exception:
            pass
        self._trigger_pixel_overlay = None

    def _sample_pixel_at_global(self, pos) -> Tuple[int, int, int]:
        b, g, r = capture_pixel_bgr(int(pos.x()), int(pos.y()), 1)
        return int(b), int(g), int(r)

    def _show_pixel_pick_menu_main(self, pos, gx: int, gy: int, bgr: Tuple[int, int, int]):
        if self.settings_dlg is None:
            self.settings_dlg = SettingsDialog(
                None,
                self.cfg,
                self.controller,
                self.watcher,
                self.cfg_path,
                self.timer_win,
                chapter_sync_now=self._sync_chapter_anchor_now,
                chapter_clear=self._clear_chapter_anchor,
                chapter_export=self._export_chapter_txt,
                chapter_open=self._open_chapter_txt,
                chapter_status_getter=self._chapter_anchor_status,
                action_runner=self.action_runner,
                player_state_apply=self._apply_saved_player_state,
                detection_start=self._start_detectors,
                detection_stop=self._stop_detectors,
                detection_running=self._detection_running,
                screen_detection_start=self._start_screen_detector,
                screen_detection_stop=self._stop_screen_detector,
                screen_detection_running=self._screen_detection_running,
                log_detection_start=self._start_log_detector,
                log_detection_stop=self._stop_log_detector,
                log_detection_running=self._log_detection_running,
                diagnostic_mark_incident=self._diagnostic_mark_incident,
                diagnostic_export_zip=self._diagnostic_export_zip,
                diagnostic_open_folder=self._diagnostic_open_folder,
                diagnostic_copy_state=self._diagnostic_copy_state,
                diagnostic_project_snapshot=self._project_snapshot_export_zip,
            )
            self.settings_dlg.finished.connect(self.on_settings_closed)
        dlg = PixelActionDialog(None, self.settings_dlg, gx, gy, bgr)
        dlg.exec()

    def _poll_hotkeys(self):
        pixel_overlay_active = bool(self._pixel_pick_overlay and self._pixel_pick_overlay.isVisible())
        roi_overlay_active = False
        if self._quick_roi_overlay:
            try:
                roi_overlay_active = bool(self._quick_roi_overlay.isVisible())
            except RuntimeError:
                self._quick_roi_overlay = None
        trigger_overlay_active = bool(self._trigger_pixel_overlay and self._trigger_pixel_overlay.isVisible())
        if not trigger_overlay_active and self.settings_dlg and getattr(self.settings_dlg, "_trigger_pixel_overlay", None):
            try:
                trigger_overlay_active = bool(self.settings_dlg._trigger_pixel_overlay.isVisible())
            except RuntimeError:
                trigger_overlay_active = False
        esc = _key_pressed(0x1B)
        if esc:
            if pixel_overlay_active:
                self._cancel_global_pixel_pick()
                self._prev_esc = True
                return
            if trigger_overlay_active:
                self._cancel_global_trigger_pixel_pick()
                self._prev_esc = True
                return
            self._cancel_global_roi_pick()
            self._prev_esc = True
            return
        if self._global_pick_busy() and not pixel_overlay_active and not trigger_overlay_active and not roi_overlay_active:
            return
        ctrl = (_user32.GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0
        shift = (_user32.GetAsyncKeyState(VK_SHIFT) & 0x8000) != 0
        alt = (_user32.GetAsyncKeyState(VK_MENU) & 0x8000) != 0
        def _recent(key: str) -> bool:
            last = self._hotkey_last_fired.get(key)
            return last is not None and (time.time() - last) < 0.25

        roi_info = self._hotkey_info(self.cfg.roi_hotkey or "")
        if roi_info:
            vk, mods = roi_info
            key_down = (_user32.GetAsyncKeyState(vk) & 0x8000) != 0
            if key_down and not self._prev_roi_key:
                if (not mods["ctrl"] or ctrl) and (not mods["alt"] or alt) and (not mods["shift"] or shift) and not _recent("roi"):
                    self._start_global_roi_pick()
                    self._hotkey_last_fired["roi"] = time.time()
            self._prev_roi_key = bool(key_down)

        trigger_info = self._hotkey_info(self.cfg.trigger_pixel_hotkey or "")
        if trigger_info:
            vk, mods = trigger_info
            key_down = (_user32.GetAsyncKeyState(vk) & 0x8000) != 0
            if key_down and not self._prev_trigger_pixel_key:
                if (not mods["ctrl"] or ctrl) and (not mods["alt"] or alt) and (not mods["shift"] or shift) and not _recent("trigger"):
                    if trigger_overlay_active:
                        self._finish_global_trigger_pixel_pick()
                    else:
                        self._start_global_trigger_pixel_pick()
                    self._hotkey_last_fired["trigger"] = time.time()
            self._prev_trigger_pixel_key = bool(key_down)

        pixel_info = self._hotkey_info(self.cfg.pixel_hotkey or "")
        if pixel_info:
            vk, mods = pixel_info
            key_down = (_user32.GetAsyncKeyState(vk) & 0x8000) != 0
            if key_down and not self._prev_pixel_key:
                if (not mods["ctrl"] or ctrl) and (not mods["alt"] or alt) and (not mods["shift"] or shift) and not _recent("pixel"):
                    if pixel_overlay_active:
                        self._finish_global_pixel_pick()
                    else:
                        self._start_global_pixel_pick()
                    self._hotkey_last_fired["pixel"] = time.time()
            self._prev_pixel_key = bool(key_down)

        detect_info = self._hotkey_info(self.cfg.detect_hotkey or "")
        if detect_info:
            vk, mods = detect_info
            key_down = (_user32.GetAsyncKeyState(vk) & 0x8000) != 0
            if key_down and not self._prev_detect_key:
                if (not mods["ctrl"] or ctrl) and (not mods["alt"] or alt) and (not mods["shift"] or shift) and not _recent("detect"):
                    self._toggle_screen_detector()
                    self._hotkey_last_fired["detect"] = time.time()
            self._prev_detect_key = bool(key_down)
        action_pick_info = self._hotkey_info(self.cfg.action_pick_hotkey or "")
        if action_pick_info:
            vk, mods = action_pick_info
            key_down = (_user32.GetAsyncKeyState(vk) & 0x8000) != 0
            if key_down and not self._prev_action_pick_key:
                if (not mods["ctrl"] or ctrl) and (not mods["alt"] or alt) and (not mods["shift"] or shift) and not _recent("action_pick"):
                    if self.settings_dlg:
                        try:
                            self.settings_dlg._apply_action_pick_from_cursor()
                        except Exception:
                            pass
                    self._hotkey_last_fired["action_pick"] = time.time()
            self._prev_action_pick_key = bool(key_down)
        action_test_info = self._hotkey_info(self.cfg.action_test_hotkey or "")
        if action_test_info:
            vk, mods = action_test_info
            key_down = (_user32.GetAsyncKeyState(vk) & 0x8000) != 0
            if key_down and not self._prev_action_test_key:
                if (not mods["ctrl"] or ctrl) and (not mods["alt"] or alt) and (not mods["shift"] or shift) and not _recent("action_test"):
                    try:
                        self._run_action_test_hotkey()
                    except Exception:
                        pass
                    self._hotkey_last_fired["action_test"] = time.time()
            self._prev_action_test_key = bool(key_down)
        self._prev_esc = bool(esc)

    def _apply_global_hotkeys(self):
        if not self._global_hotkeys_enabled:
            try:
                self._global_hotkeys.stop()
            except Exception:
                pass
            return
        bindings = {}
        for vk in set(self._vk_map.values()):
            if vk is None:
                continue
            try:
                vki = int(vk)
            except Exception:
                continue
            bindings[vki] = partial(self._on_global_key, vki)
        self._global_hotkeys.set_bindings(bindings)
        self._global_hotkeys.start()

    def _on_global_key(self, vk: int):
        QTimer.singleShot(0, lambda: self._handle_global_key(vk))

    def _handle_global_key(self, vk: int):
        ctrl = (_user32.GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0
        shift = (_user32.GetAsyncKeyState(VK_SHIFT) & 0x8000) != 0
        alt = (_user32.GetAsyncKeyState(VK_MENU) & 0x8000) != 0
        if int(vk) == 0x1B:
            pixel_overlay_active = bool(self._pixel_pick_overlay and self._pixel_pick_overlay.isVisible())
            trigger_overlay_active = bool(self._trigger_pixel_overlay and self._trigger_pixel_overlay.isVisible())
            if pixel_overlay_active:
                self._cancel_global_pixel_pick()
                return
            if trigger_overlay_active:
                self._cancel_global_trigger_pixel_pick()
                return
            self._cancel_global_roi_pick()
            return

        def _match(seq: str) -> bool:
            info = self._hotkey_info(seq or "")
            if not info:
                return False
            hvk, mods = info
            if int(hvk) != int(vk):
                return False
            if mods.get("ctrl") and not ctrl:
                return False
            if mods.get("alt") and not alt:
                return False
            if mods.get("shift") and not shift:
                return False
            return True

        pixel_overlay_active = bool(self._pixel_pick_overlay and self._pixel_pick_overlay.isVisible())
        trigger_overlay_active = bool(self._trigger_pixel_overlay and self._trigger_pixel_overlay.isVisible())
        if not trigger_overlay_active and self.settings_dlg and getattr(self.settings_dlg, "_trigger_pixel_overlay", None):
            try:
                trigger_overlay_active = bool(self.settings_dlg._trigger_pixel_overlay.isVisible())
            except RuntimeError:
                trigger_overlay_active = False

        if self._global_pick_busy() and not pixel_overlay_active and not trigger_overlay_active:
            return

        if _match(self.cfg.trigger_pixel_hotkey):
            if trigger_overlay_active:
                self._finish_global_trigger_pixel_pick()
            else:
                self._start_global_trigger_pixel_pick()
            self._hotkey_last_fired["trigger"] = time.time()
            return
        if _match(self.cfg.pixel_hotkey):
            if pixel_overlay_active:
                self._finish_global_pixel_pick()
            else:
                self._start_global_pixel_pick()
            self._hotkey_last_fired["pixel"] = time.time()
            return
        if _match(self.cfg.roi_hotkey):
            last = self._hotkey_last_fired.get("roi")
            if last is None or (time.time() - last) >= 0.25:
                self._start_global_roi_pick()
                self._hotkey_last_fired["roi"] = time.time()
            return
        if _match(self.cfg.detect_hotkey):
            self._toggle_screen_detector()
            self._hotkey_last_fired["detect"] = time.time()
            return
        if _match(self.cfg.action_pick_hotkey):
            if self.settings_dlg:
                try:
                    self.settings_dlg._apply_action_pick_from_cursor()
                except Exception:
                    pass
            self._hotkey_last_fired["action_pick"] = time.time()
            return
        if _match(self.cfg.action_test_hotkey):
            try:
                self._run_action_test_hotkey()
            except Exception:
                pass
            self._hotkey_last_fired["action_test"] = time.time()
            return

    def _portrait_priority_mode(self) -> str:
        mode = str(getattr(self.cfg, "portrait_source_priority", "log") or "log").strip().lower()
        return "profile" if mode in ("profile", "profiles", "registered", "player", "players") else "log"

    def _profile_portrait_path_for_gid(self, gid: str) -> str:
        try:
            return resolve_player_image_path(_player_image_path_for_gid(self.cfg, str(gid or "").upper().strip()))
        except Exception:
            return ""

    def _log_portrait_path_for_side(self, side: str) -> str:
        try:
            root = resolve_spectatorlog_path(str(getattr(self.cfg, "spectatorlog_path", "") or ""))
            candidate = os.path.join(root, str(side or "").lower().strip(), "portrait.png")
            return candidate if os.path.isfile(candidate) else ""
        except Exception:
            return ""

    def _read_portrait_image_path(self, path: str):
        try:
            if path and os.path.isfile(path):
                return safe_cv2_imread(path, cv2.IMREAD_UNCHANGED)
        except Exception:
            logging.debug("PORTRAIT_READ_FAIL path=%s", path, exc_info=True)
        return None

    def _resolve_portrait_image(self, side: str, gid: str, log_img=_NO_UPDATE):
        """Return (image_or_none, source).
        source is log/profile/empty/no_update. In log-priority mode profile image is not used as fallback.
        """
        mode = self._portrait_priority_mode()
        side = str(side or "").lower().strip()
        gid = str(gid or "").upper().strip()

        def _valid_img(img):
            try:
                return img is not None and img is not _NO_UPDATE and getattr(img, "size", 0) > 0
            except Exception:
                return False

        if _valid_img(log_img):
            logging.info("PLAYER_PORTRAIT_RESOLVE side=%s source=log payload=1", side)
            return log_img, "log"
        log_path = self._log_portrait_path_for_side(side)
        log_img2 = self._read_portrait_image_path(log_path) if log_path else None
        if _valid_img(log_img2):
            logging.info("PLAYER_PORTRAIT_RESOLVE side=%s source=log path=%s", side, log_path)
            return log_img2, "log"
        if mode == "profile":
            profile_path = self._profile_portrait_path_for_gid(gid)
            profile_img = self._read_portrait_image_path(profile_path) if profile_path else None
            if _valid_img(profile_img):
                logging.info("PLAYER_PORTRAIT_RESOLVE side=%s source=profile path=%s", side, profile_path)
                return profile_img, "profile"
        logging.info("PLAYER_PORTRAIT_RESOLVE side=%s source=empty", side)
        return None, "empty"

    def _sync_browser_overlay_player_assets(self, d: Optional[dict] = None) -> dict:
        update: Dict[str, Any] = {}
        try:
            overlay = getattr(self, "browser_overlay", None)
            if overlay is None:
                return update
            d = dict(d or {})
            ids = {
                "blue": str(d.get("blue_player_id", self._current_blue_id) or "").upper().strip(),
                "red": str(d.get("red_player_id", self._current_red_id) or "").upper().strip(),
            }
            names = {
                "blue": str(d.get("blue_name") or "").strip(),
                "red": str(d.get("red_name") or "").strip(),
            }
            try:
                root = resolve_spectatorlog_path(str(getattr(self.cfg, "spectatorlog_path", "") or ""))
            except Exception:
                root = ""
            for side in ("blue", "red"):
                if not names.get(side) and root:
                    try:
                        with open(os.path.join(root, side, "name.txt"), "r", encoding="utf-8-sig") as f:
                            names[side] = f.read().strip()
                    except UnicodeDecodeError:
                        try:
                            with open(os.path.join(root, side, "name.txt"), "r", encoding="cp949", errors="ignore") as f:
                                names[side] = f.read().strip()
                        except Exception:
                            pass
                    except Exception:
                        pass
                if not ids.get(side) and names.get(side):
                    try:
                        ids[side] = _canonical_player_gid_for_cfg(
                            self.cfg,
                            normalize_game_id(names.get(side), PLAYER_ID_ALLOW_CHARS),
                            threshold=70,
                        )
                    except Exception:
                        ids[side] = str(names.get(side) or "").upper().strip()
                display = str((self.cfg.players or {}).get(ids.get(side, ""), "") or names.get(side) or ids.get(side) or "").strip()
                if display:
                    update["blueName" if side == "blue" else "redName"] = display
            for side, gid in ids.items():
                if side == "blue" and "blue_player_img" in d:
                    continue
                if side == "red" and "red_player_img" in d:
                    continue
                id_key = "blue_player_id" if side == "blue" else "red_player_id"
                name_key = "blue_name" if side == "blue" else "red_name"
                # If a fresh player ID/name update arrived, do not keep an old
                # browser image just because that side already has an image path.
                # Reload from the registered profile image or SpectatorLog portrait.
                if overlay.image_path(side) and id_key not in d and name_key not in d:
                    continue
                img, src = self._resolve_portrait_image(side, gid, _NO_UPDATE)
                if img is not _NO_UPDATE and img is not None and getattr(img, "size", 0) > 0:
                    overlay.set_image(side, img)
                elif id_key in d or name_key in d:
                    # Fresh fighter update but no portrait found: clear the old
                    # side image instead of leaving a stale previous portrait.
                    overlay.set_image(side, None)
            update["blueHasImage"] = bool(overlay.image_path("blue"))
            update["redHasImage"] = bool(overlay.image_path("red"))
            try:
                overlay.set_asset_path("blueflag", _player_flag_path_for_gid(self.cfg, ids.get("blue", "")))
                overlay.set_asset_path("redflag", _player_flag_path_for_gid(self.cfg, ids.get("red", "")))
            except Exception:
                pass
            try:
                arena = str(d.get("arena_name") or overlay.snapshot().get("arenaName") or "").strip()
                by_arena = dict(getattr(self.cfg, "overlay_vs_bg_by_arena", {}) or {})
                bg_path = str(by_arena.get(arena, "") or getattr(self.cfg, "overlay_vs_bg_path", "") or "")
                overlay.set_asset_path("vsbg", bg_path)
            except Exception:
                pass
            try:
                style_time = dict(getattr(self.cfg, "overlay_style_time", {}) or {})
                style_round = dict(getattr(self.cfg, "overlay_style_round", {}) or {})
                update.update({
                    "overlayBgColor": str(getattr(self.cfg, "overlay_bg_color", "transparent") or "transparent"),
                    "overlayBgOpacity": max(0.0, min(1.0, float(getattr(self.cfg, "overlay_bg_opacity", 0.0) or 0.0))),
                    "overlayUiScale": float(getattr(self.cfg, "overlay_ui_scale", 1.0) or 1.0),
                    "browserOverlayScale": float(getattr(self.cfg, "browser_overlay_scale", 1.0) or 1.0),
                    "browserFullscreenFxIntensity": max(0.0, min(3.0, float(getattr(self.cfg, "browser_fullscreen_fx_intensity", 1.6) or 1.6))),
                    "overlayTimerFontSize": int(getattr(self.cfg, "overlay_timer_font_size", 54) or 54),
                    "overlayTimerX": int(getattr(self.cfg, "overlay_timer_x", 0) or 0),
                    "overlayTimerY": int(getattr(self.cfg, "overlay_timer_y", 0) or 0),
                    "overlayRoundFontSize": int(getattr(self.cfg, "overlay_round_font_size", 11) or 11),
                    "overlayRoundX": int(getattr(self.cfg, "overlay_round_x", 0) or 0),
                    "overlayRoundY": int(getattr(self.cfg, "overlay_round_y", 0) or 0),
                    "overlayTimerOpacity": max(0.0, min(1.0, float(style_time.get("text_opacity", 1.0) or 1.0))),
                    "overlayRoundOpacity": max(0.0, min(1.0, float(style_round.get("text_opacity", 1.0) or 1.0))),
                    "vsBgOpacity": max(0.0, min(1.0, float(getattr(self.cfg, "overlay_vs_bg_opacity", 1.0) or 1.0))),
                    "overlayVsHoldMs": int(max(500, min(15000, float(getattr(self.cfg, "overlay_vs_hold_sec", 2.85) or 2.85) * 1000))),
                    "hitFxMinDamage": max(0.0, float(getattr(self.cfg, "spectator_hit_effect_damage", 45.0) or 45.0)),
                    "hitFxColorPreset": str(getattr(self.cfg, "spectator_hit_effect_color_preset", "classic") or "classic"),
                    "hitFxColorLow": str(getattr(self.cfg, "spectator_hit_effect_color_low", "#38bdf8") or "#38bdf8"),
                    "hitFxColorMid": str(getattr(self.cfg, "spectator_hit_effect_color_mid", "#fb923c") or "#fb923c"),
                    "hitFxColorHigh": str(getattr(self.cfg, "spectator_hit_effect_color_high", "#f87171") or "#f87171"),
                    "hitFxColorWeak": str(getattr(self.cfg, "spectator_hit_effect_color_weak", "#facc15") or "#facc15"),
                    "hitFxColorStun": str(getattr(self.cfg, "spectator_hit_effect_color_stun", "#ef4444") or "#ef4444"),
                    "hitFxDurationMs": int(max(80, min(1200, int(getattr(self.cfg, "spectator_hit_effect_duration_ms", 170) or 170)))),
                    "hitFxPopMs": int(max(30, min(280, int(getattr(self.cfg, "spectator_hit_effect_pop_ms", 58) or 58)))),
                    "hitFxBaseSize": int(max(24, min(240, int(getattr(self.cfg, "spectator_hit_effect_base_size", 86) or 86)))),
                    "hitFxDamageScale": float(max(0.0, min(3.0, float(getattr(self.cfg, "spectator_hit_effect_damage_scale", 0.42) or 0.42)))),
                    "hitFxRingWidth": int(max(1, min(20, int(getattr(self.cfg, "spectator_hit_effect_ring_width", 4) or 4)))),
                    "hitFxOpacity": float(max(0.05, min(1.5, float(getattr(self.cfg, "spectator_hit_effect_opacity", 1.0) or 1.0)))),
                    "hitFxGlow": float(max(0.0, min(3.0, float(getattr(self.cfg, "spectator_hit_effect_glow", 1.0) or 1.0)))),
                    "hitFxFillOpacity": float(max(0.0, min(1.5, float(getattr(self.cfg, "spectator_hit_effect_fill_opacity", 1.0) or 1.0)))),
                    "hitFxShowText": bool(getattr(self.cfg, "spectator_hit_effect_show_text", True)),
                    "hitFxTextScale": float(max(0.5, min(2.0, float(getattr(self.cfg, "spectator_hit_effect_text_scale", 1.0) or 1.0)))),
                    "hitFxLatencyLog": bool(getattr(self.cfg, "spectator_hit_effect_latency_log", True)),
                    "hitFxSpriteEnabled": bool(getattr(self.cfg, "spectator_hit_effect_sprite_enabled", True)),
                    "hitFxRingEnabled": bool(getattr(self.cfg, "spectator_hit_effect_ring_enabled", False)),
                })
            except Exception:
                pass
        except Exception:
            logging.debug("BROWSER_OVERLAY_ASSET_SYNC_FAIL", exc_info=True)
        return update

    def _apply_browser_overlay_direct_update(self, d: dict):
        try:
            overlay = getattr(self, "browser_overlay", None)
            if overlay is None:
                return
            state = overlay.snapshot()

            def _num(value, default=0.0):
                try:
                    return float(value)
                except Exception:
                    return float(default)

            def _int(value, default=0):
                try:
                    return int(float(value))
                except Exception:
                    return int(default)

            def _hp_pair(long_value, mid_value):
                try:
                    base = max(0.0, min(1.0, (100.0 - _num(long_value, 0.0)) / 100.0))
                    mid = max(0.0, min(1.0, _num(mid_value, 0.0) / 100.0))
                    current = max(0.0, min(1.0, base * (1.0 - mid)))
                    return current, max(0.0, base - current)
                except Exception:
                    return 1.0, 0.0

            impact_events_pushed = False

            def _push_hit_impacts_fast():
                nonlocal impact_events_pushed
                if impact_events_pushed:
                    return
                impact_events_pushed = True
                for ev in list(d.get("spectator_hit_effect_events") or []):
                    ev = dict(ev or {})
                    side = str(ev.get("side") or "")
                    damage = _num(ev.get("damage", 0.0), 0.0)
                    effect_kind = str(ev.get("effect_kind") or "").lower()
                    threshold = max(0.0, float(getattr(self.cfg, "spectator_hit_effect_damage", 45.0) or 45.0))
                    if effect_kind not in ("stun", "tko", "knockdown", "down") and damage < threshold:
                        continue
                    try:
                        sx = float(ev.get("screen_x", ev.get("screenX")))
                        sy = float(ev.get("screen_y", ev.get("screenY")))
                    except Exception:
                        continue
                    try:
                        now_perf_ms = time.perf_counter() * 1000.0
                        seen = getattr(self, "_browser_hitfx_seen", None)
                        if not isinstance(seen, dict):
                            seen = {}
                            self._browser_hitfx_seen = seen
                        for _k, _at in list(seen.items()):
                            try:
                                if now_perf_ms - float(_at) > 1200.0:
                                    seen.pop(_k, None)
                            except Exception:
                                seen.pop(_k, None)
                        hitfx_key = str(ev.get("hitfx_key") or ev.get("hitfxKey") or "%s|%.2f|%.4f|%.4f|%.3f|%s" % (
                            side, damage, sx, sy, _num(ev.get("event_time", ev.get("eventTime")), 0.0), str(ev.get("punch") or "")
                        ))
                        if hitfx_key in seen:
                            continue
                        seen[hitfx_key] = now_perf_ms
                    except Exception:
                        hitfx_key = ""
                        now_perf_ms = time.perf_counter() * 1000.0
                    try:
                        if bool(getattr(self.cfg, "spectator_hit_effect_latency_log", True)):
                            detect_perf_ms = ev.get("hitfx_detect_perf_ms", None)
                            watcher_to_push = None
                            try:
                                watcher_to_push = now_perf_ms - float(detect_perf_ms)
                            except Exception:
                                watcher_to_push = None
                            logging.info(
                                "HITFX_LATENCY_PUSH key=%s side=%s dmg=%.2f x=%.4f y=%.4f fast=%s watcher_to_push_ms=%s",
                                hitfx_key,
                                side,
                                damage,
                                sx,
                                sy,
                                bool(d.get("_hitfx_fast_emit", False)),
                                "" if watcher_to_push is None else ("%.1f" % watcher_to_push),
                            )
                    except Exception:
                        pass
                    try:
                        DIAG.record("hitfx_overlay_push_fast", side=side, damage=damage, x=sx, y=sy, effect_kind=effect_kind, key=hitfx_key)
                    except Exception:
                        pass
                    overlay.push_event(
                        "impact",
                        side=side,
                        damage=damage,
                        effectKind=effect_kind,
                        attackerSide=str(ev.get("attacker_side") or ""),
                        punch=str(ev.get("punch") or ""),
                        weakPoint=str(ev.get("weak_point") or ""),
                        counterMult=_num(ev.get("counter_mult", ev.get("counterMult", 1.0)), 1.0),
                        isCounter=bool(ev.get("is_counter") or ev.get("isCounter")),
                        coordSource=str(ev.get("coord_source") or ""),
                        gloveHand=str(ev.get("glove_hand") or ""),
                        screenX=sx,
                        screenY=sy,
                        eventTime=_num(ev.get("event_time", ev.get("eventTime")), 0.0),
                        hitfxKey=hitfx_key,
                        pushPerfMs=now_perf_ms,
                    )

            # Absolute priority: push impact before image/name/report/state-heavy work.
            if bool(getattr(self.cfg, "spectator_hit_effect_fast_emit", True)) and d.get("spectator_hit_effect_events"):
                _push_hit_impacts_fast()

            update = {}
            if "blue_name" in d:
                update["blueName"] = str(d.get("blue_name") or "")
            if "red_name" in d:
                update["redName"] = str(d.get("red_name") or "")
            if "arena_name" in d:
                update["arenaName"] = str(d.get("arena_name") or "")
            if "blue_damage_dealt" in d:
                update["blueTotalDamageText"] = str(_int(d.get("blue_damage_dealt"), 0))
            if "red_damage_dealt" in d:
                update["redTotalDamageText"] = str(_int(d.get("red_damage_dealt"), 0))
            if "blue_round_damage_dealt" in d:
                update["blueDamageText"] = "DMG %d" % _int(d.get("blue_round_damage_dealt"), 0)
            if "red_round_damage_dealt" in d:
                update["redDamageText"] = "DMG %d" % _int(d.get("red_round_damage_dealt"), 0)
            if "spectator_recent_text_size" in d:
                update["spectatorRecentTextSize"] = _int(d.get("spectator_recent_text_size"), 23)

            if "blue_player_img" in d:
                overlay.set_image("blue", d.get("blue_player_img"))
                update["blueHasImage"] = bool(overlay.image_path("blue"))
            if "red_player_img" in d:
                overlay.set_image("red", d.get("red_player_img"))
                update["redHasImage"] = bool(overlay.image_path("red"))
            if ("blue_player_id" in d or "red_player_id" in d or "vs_intro_event" in d
                    or "blue_player_img" in d or "red_player_img" in d or "arena_name" in d):
                update.update(self._sync_browser_overlay_player_assets(d))

            for ev in list(d.get("spectator_hit_effect_events") or []):
                ev = dict(ev or {})
                attacker = str(ev.get("attacker_side") or "").lower()
                if attacker not in ("blue", "red"):
                    continue
                punch = str(ev.get("punch") or "Hit").strip() or "Hit"
                try:
                    damage_text = str(int(round(float(ev.get("damage", 0.0) or 0.0))))
                except Exception:
                    damage_text = "0"
                weak = str(ev.get("weak_point") or "").strip()
                text = (punch + " " + damage_text).strip()
                if weak:
                    text = text + "\n" + weak
                update["blueRecentHitText" if attacker == "blue" else "redRecentHitText"] = text

            if bool(d.get("spectator_sp_reset", False)):
                update["blueSpRatio"] = 1.0
                update["redSpRatio"] = 1.0

            info = dict(d.get("spectator_log_info") or {}) if "spectator_log_info" in d else {}
            if info:
                key_map = {
                    "blue_recent_hit_text": "blueRecentHitText",
                    "red_recent_hit_text": "redRecentHitText",
                    "blue_combo_hit_text": "blueComboHitText",
                    "red_combo_hit_text": "redComboHitText",
                    "blue_combo_damage_text": "blueComboDamageText",
                    "red_combo_damage_text": "redComboDamageText",
                    "blue_punishment_mid": "bluePunishmentMid",
                    "red_punishment_mid": "redPunishmentMid",
                    "blue_punishment_long": "bluePunishmentLong",
                    "red_punishment_long": "redPunishmentLong",
                    "blue_round_knockdowns": "blueRoundKnockdowns",
                    "red_round_knockdowns": "redRoundKnockdowns",
                }
                for src, dst in key_map.items():
                    if src in info:
                        update[dst] = info.get(src)

            blue_long = update.get("bluePunishmentLong", state.get("bluePunishmentLong", 0.0))
            blue_mid = update.get("bluePunishmentMid", state.get("bluePunishmentMid", 0.0))
            red_long = update.get("redPunishmentLong", state.get("redPunishmentLong", 0.0))
            red_mid = update.get("redPunishmentMid", state.get("redPunishmentMid", 0.0))
            blue_hp, blue_ghost = _hp_pair(blue_long, blue_mid)
            red_hp, red_ghost = _hp_pair(red_long, red_mid)
            update["blueHpRatio"] = float(blue_hp)
            update["blueHpGhostRatio"] = float(blue_ghost)
            update["redHpRatio"] = float(red_hp)
            update["redHpGhostRatio"] = float(red_ghost)

            if "round_current" in d or "round_total" in d or "seconds_left" in d:
                cur = _int(d.get("round_current", self.cfg.timer_current_round), self.cfg.timer_current_round)
                total = _int(d.get("round_total", self.cfg.timer_total_rounds), self.cfg.timer_total_rounds)
                sec = _int(d.get("seconds_left", self.cfg.timer_seconds_left), self.cfg.timer_seconds_left)
                update["timeText"] = "%d:%02d" % (max(0, sec) // 60, max(0, sec) % 60)
                update["roundText"] = "RD %d OF %d" % (max(1, cur), max(1, total))

            if "timer_seconds_left" in d or "timer_current_round" in d or "timer_total_rounds" in d:
                cur = _int(d.get("timer_current_round", self.cfg.timer_current_round), self.cfg.timer_current_round)
                total = _int(d.get("timer_total_rounds", self.cfg.timer_total_rounds), self.cfg.timer_total_rounds)
                sec = _int(d.get("timer_seconds_left", self.cfg.timer_seconds_left), self.cfg.timer_seconds_left)
                update["timeText"] = "%d:%02d" % (max(0, sec) // 60, max(0, sec) % 60)
                update["roundText"] = "RD %d OF %d" % (max(1, cur), max(1, total))

            if bool(d.get("spectator_match_clear", False)) or bool(d.get("spectator_match_stats_reset", False)):
                update.update({
                    "blueDamageText": "DMG 0",
                    "redDamageText": "DMG 0",
                    "blueTotalDamageText": "0",
                    "redTotalDamageText": "0",
                    "blueSpRatio": 1.0,
                    "redSpRatio": 1.0,
                    "blueRoundKnockdowns": 0,
                    "redRoundKnockdowns": 0,
                    "blueComboHitText": "",
                    "blueComboDamageText": "",
                    "redComboHitText": "",
                    "redComboDamageText": "",
                    "blueRecentHitText": "",
                    "redRecentHitText": "",
                    "bluePunishmentMid": 0.0,
                    "redPunishmentMid": 0.0,
                    "bluePunishmentLong": 0.0,
                    "redPunishmentLong": 0.0,
                    "blueHpRatio": 1.0,
                    "redHpRatio": 1.0,
                    "blueHpGhostRatio": 0.0,
                    "redHpGhostRatio": 0.0,
                })

            if ("blue_round_damage_dealt" in d or "red_round_damage_dealt" in d
                    or "seconds_left" in d or "spectator_rest_mode" in d
                    or bool(d.get("spectator_sp_reset", False))
                    or bool(d.get("spectator_match_stats_reset", False))):
                update.update(self._browser_overlay_sp_update(d, state))

            if ("spectator_effect_events" in d or "spectator_log_info" in d
                    or "round_current" in d
                    or bool(d.get("spectator_match_stats_reset", False))
                    or bool(d.get("spectator_match_clear", False))):
                update.update(self._browser_overlay_lives_update(d, state))

            if "overlay_style" in d and isinstance(d.get("overlay_style"), dict):
                style = dict(d.get("overlay_style") or {})
                style_time = dict(style.get("time") or getattr(self.cfg, "overlay_style_time", {}) or {})
                style_round = dict(style.get("round") or getattr(self.cfg, "overlay_style_round", {}) or {})
                try:
                    update["overlayTimerOpacity"] = max(0.0, min(1.0, float(style_time.get("text_opacity", 1.0) or 1.0)))
                except Exception:
                    pass
                try:
                    update["overlayRoundOpacity"] = max(0.0, min(1.0, float(style_round.get("text_opacity", 1.0) or 1.0)))
                except Exception:
                    pass
            if "browser_text_styles" in d:
                update["browserTextStyles"] = _normalize_browser_text_styles(d.get("browser_text_styles"))

            setting_map = {
                "overlay_show_round": "showRound",
                "overlay_show_time": "showTime",
                "overlay_show_blue_img": "showBlueImage",
                "overlay_show_blue_name": "showBlueName",
                "overlay_show_red_img": "showRedImage",
                "overlay_show_red_name": "showRedName",
                "overlay_show_arena_name": "showArenaName",
                "overlay_show_flags": "showFlags",
                "overlay_show_cinematic": "showCinematic",
                "overlay_bg_color": "overlayBgColor",
                "overlay_bg_opacity": "overlayBgOpacity",
                "overlay_ui_scale": "overlayUiScale",
                "browser_overlay_scale": "browserOverlayScale",
                "overlay_vs_bg_opacity": "vsBgOpacity",
                "browser_fullscreen_fx_intensity": "browserFullscreenFxIntensity",
                "overlay_timer_font_size": "overlayTimerFontSize",
                "overlay_timer_x": "overlayTimerX",
                "overlay_timer_y": "overlayTimerY",
                "overlay_round_font_size": "overlayRoundFontSize",
                "overlay_round_x": "overlayRoundX",
                "overlay_round_y": "overlayRoundY",
                "overlay_timer_opacity": "overlayTimerOpacity",
                "overlay_round_opacity": "overlayRoundOpacity",
                "spectator_hit_effect_damage": "hitFxMinDamage",
                "spectator_hit_effect_color_preset": "hitFxColorPreset",
                "spectator_hit_effect_color_low": "hitFxColorLow",
                "spectator_hit_effect_color_mid": "hitFxColorMid",
                "spectator_hit_effect_color_high": "hitFxColorHigh",
                "spectator_hit_effect_color_weak": "hitFxColorWeak",
                "spectator_hit_effect_color_stun": "hitFxColorStun",
                "spectator_hit_effect_duration_ms": "hitFxDurationMs",
                "spectator_hit_effect_pop_ms": "hitFxPopMs",
                "spectator_hit_effect_base_size": "hitFxBaseSize",
                "spectator_hit_effect_damage_scale": "hitFxDamageScale",
                "spectator_hit_effect_ring_width": "hitFxRingWidth",
                "spectator_hit_effect_opacity": "hitFxOpacity",
                "spectator_hit_effect_glow": "hitFxGlow",
                "spectator_hit_effect_fill_opacity": "hitFxFillOpacity",
                "spectator_hit_effect_show_text": "hitFxShowText",
                "spectator_hit_effect_text_scale": "hitFxTextScale",
                "spectator_hit_effect_latency_log": "hitFxLatencyLog",
                "spectator_hit_effect_sprite_enabled": "hitFxSpriteEnabled",
                "spectator_hit_effect_ring_enabled": "hitFxRingEnabled",
            }
            for src, dst in setting_map.items():
                if src in d:
                    update[dst] = d.get(src)
            if "overlay_vs_hold_sec" in d:
                try:
                    update["overlayVsHoldMs"] = int(max(500, min(15000, float(d.get("overlay_vs_hold_sec", 2.85) or 2.85) * 1000)))
                except Exception:
                    pass
            update.setdefault("overlayBgColor", str(getattr(self.cfg, "overlay_bg_color", "transparent") or "transparent"))
            update.setdefault("overlayBgOpacity", max(0.0, min(1.0, float(getattr(self.cfg, "overlay_bg_opacity", 0.0) or 0.0))))
            update.setdefault("vsBgOpacity", max(0.0, min(1.0, float(getattr(self.cfg, "overlay_vs_bg_opacity", 1.0) or 1.0))))
            update.setdefault("overlayVsHoldMs", int(max(500, min(15000, float(getattr(self.cfg, "overlay_vs_hold_sec", 2.85) or 2.85) * 1000))))
            update.setdefault("showCinematic", bool(getattr(self.cfg, "overlay_show_cinematic", True)))
            update.setdefault("browserOverlayScale", float(getattr(self.cfg, "browser_overlay_scale", 1.0) or 1.0))
            update.setdefault("browserFullscreenFxIntensity", max(0.0, min(3.0, float(getattr(self.cfg, "browser_fullscreen_fx_intensity", 1.6) or 1.6))))
            update.setdefault("overlayUiScale", float(getattr(self.cfg, "overlay_ui_scale", 1.0) or 1.0))
            update.setdefault("overlayTimerFontSize", int(getattr(self.cfg, "overlay_timer_font_size", 54) or 54))
            update.setdefault("overlayTimerX", int(getattr(self.cfg, "overlay_timer_x", 0) or 0))
            update.setdefault("overlayTimerY", int(getattr(self.cfg, "overlay_timer_y", 0) or 0))
            update.setdefault("overlayRoundFontSize", int(getattr(self.cfg, "overlay_round_font_size", 11) or 11))
            update.setdefault("overlayRoundX", int(getattr(self.cfg, "overlay_round_x", 0) or 0))
            update.setdefault("overlayRoundY", int(getattr(self.cfg, "overlay_round_y", 0) or 0))
            update.setdefault("hitFxMinDamage", max(0.0, float(getattr(self.cfg, "spectator_hit_effect_damage", 45.0) or 45.0)))
            update.setdefault("hitFxColorPreset", str(getattr(self.cfg, "spectator_hit_effect_color_preset", "classic") or "classic"))
            update.setdefault("hitFxColorLow", str(getattr(self.cfg, "spectator_hit_effect_color_low", "#38bdf8") or "#38bdf8"))
            update.setdefault("hitFxColorMid", str(getattr(self.cfg, "spectator_hit_effect_color_mid", "#fb923c") or "#fb923c"))
            update.setdefault("hitFxColorHigh", str(getattr(self.cfg, "spectator_hit_effect_color_high", "#f87171") or "#f87171"))
            update.setdefault("hitFxColorWeak", str(getattr(self.cfg, "spectator_hit_effect_color_weak", "#facc15") or "#facc15"))
            update.setdefault("hitFxColorStun", str(getattr(self.cfg, "spectator_hit_effect_color_stun", "#ef4444") or "#ef4444"))
            update.setdefault("hitFxDurationMs", int(max(80, min(1200, int(getattr(self.cfg, "spectator_hit_effect_duration_ms", 170) or 170)))))
            update.setdefault("hitFxPopMs", int(max(30, min(280, int(getattr(self.cfg, "spectator_hit_effect_pop_ms", 58) or 58)))))
            update.setdefault("hitFxBaseSize", int(max(24, min(240, int(getattr(self.cfg, "spectator_hit_effect_base_size", 86) or 86)))))
            update.setdefault("hitFxDamageScale", float(max(0.0, min(3.0, float(getattr(self.cfg, "spectator_hit_effect_damage_scale", 0.42) or 0.42)))))
            update.setdefault("hitFxRingWidth", int(max(1, min(20, int(getattr(self.cfg, "spectator_hit_effect_ring_width", 4) or 4)))))
            update.setdefault("hitFxOpacity", float(max(0.05, min(1.5, float(getattr(self.cfg, "spectator_hit_effect_opacity", 1.0) or 1.0)))))
            update.setdefault("hitFxGlow", float(max(0.0, min(3.0, float(getattr(self.cfg, "spectator_hit_effect_glow", 1.0) or 1.0)))))
            update.setdefault("hitFxFillOpacity", float(max(0.0, min(1.5, float(getattr(self.cfg, "spectator_hit_effect_fill_opacity", 1.0) or 1.0)))))
            update.setdefault("hitFxShowText", bool(getattr(self.cfg, "spectator_hit_effect_show_text", True)))
            update.setdefault("hitFxTextScale", float(max(0.5, min(2.0, float(getattr(self.cfg, "spectator_hit_effect_text_scale", 1.0) or 1.0)))))
            update.setdefault("hitFxLatencyLog", bool(getattr(self.cfg, "spectator_hit_effect_latency_log", True)))
            update.setdefault("hitFxSpriteEnabled", bool(getattr(self.cfg, "spectator_hit_effect_sprite_enabled", True)))
            update.setdefault("hitFxRingEnabled", bool(getattr(self.cfg, "spectator_hit_effect_ring_enabled", False)))
            try:
                style_time = dict(getattr(self.cfg, "overlay_style_time", {}) or {})
                style_round = dict(getattr(self.cfg, "overlay_style_round", {}) or {})
                update.setdefault("overlayTimerOpacity", max(0.0, min(1.0, float(style_time.get("text_opacity", 1.0) or 1.0))))
                update.setdefault("overlayRoundOpacity", max(0.0, min(1.0, float(style_round.get("text_opacity", 1.0) or 1.0))))
            except Exception:
                pass
            overlay.update(**update)

            # Fast path: screen hit FX must be emitted before heavy fullscreen/report events.
            _push_hit_impacts_fast()

            if "round_intro_event" in d:
                ev = dict(d.get("round_intro_event") or {})
                overlay.push_event("round_intro", round=ev.get("round", ""))
            if "vs_intro_event" in d:
                overlay.push_event("vs")
            if bool(d.get("spectator_round_report_hide")):
                try:
                    overlay.push_event("round_report_hide")
                except Exception:
                    logging.exception("BROWSER_OVERLAY_ROUND_REPORT_HIDE_FAIL")
            if "spectator_round_report" in d and isinstance(d.get("spectator_round_report"), dict):
                report_payload = dict(d.get("spectator_round_report") or {})
                try:
                    overlay.push_event("round_report", **report_payload)
                except Exception:
                    logging.exception("BROWSER_OVERLAY_ROUND_REPORT_EVENT_FAIL")
            if bool(d.get("spectator_lobby_hide")):
                try:
                    overlay.push_event("lobby_hide")
                except Exception:
                    logging.exception("BROWSER_OVERLAY_LOBBY_HIDE_FAIL")
            # Stage57: lobby/scorecard/winner are kept as data sources only.
            # The broadcast overlay shows them inside the integrated round/match
            # report instead of separate floating cards.
            if "spectator_lobby_overlay" in d and isinstance(d.get("spectator_lobby_overlay"), dict):
                logging.debug("BROWSER_OVERLAY_LOBBY_CARD_SUPPRESSED")
            if "spectator_scorecard" in d and isinstance(d.get("spectator_scorecard"), dict):
                logging.debug("BROWSER_OVERLAY_SCORECARD_CARD_SUPPRESSED")
            if "spectator_winner" in d and isinstance(d.get("spectator_winner"), dict):
                logging.debug("BROWSER_OVERLAY_WINNER_CARD_SUPPRESSED")
            for side in list(d.get("stun_flash_sides") or []):
                overlay.push_event("stun", side=str(side or ""))
            for ev in list(d.get("spectator_effect_events") or []):
                ev = dict(ev or {})
                overlay.push_event(str(ev.get("kind") or ""), side=str(ev.get("side") or ""))
            _push_hit_impacts_fast()
        except Exception:
            logging.exception("BROWSER_OVERLAY_DIRECT_UPDATE_FAIL")

    def _schedule_lobby_auto_start_click(self, payload: Optional[dict] = None) -> None:
        if not bool(getattr(self.cfg, "spectator_lobby_auto_start_enabled", False)):
            return
        title = str(getattr(self.cfg, "spectator_lobby_auto_start_target_title", "") or "").strip()
        x = int(getattr(self.cfg, "spectator_lobby_auto_start_client_x", 0) or 0)
        y = int(getattr(self.cfg, "spectator_lobby_auto_start_client_y", 0) or 0)
        if not title:
            logging.warning("LOBBY_AUTO_START_SKIP reason=empty_window_title")
            return
        if x == 0 and y == 0:
            logging.warning("LOBBY_AUTO_START_SKIP reason=unset_client_point")
            return
        now = time.monotonic()
        if now - float(getattr(self, "_lobby_auto_start_last_at", 0.0) or 0.0) < 2.0:
            logging.info("LOBBY_AUTO_START_SKIP reason=cooldown")
            return
        lock = getattr(self, "_lobby_auto_start_lock", None)
        if lock is None or not lock.acquire(blocking=False):
            logging.info("LOBBY_AUTO_START_SKIP reason=busy")
            return
        self._lobby_auto_start_last_at = now
        delay_ms = max(0, min(5000, int(getattr(self.cfg, "spectator_lobby_auto_start_delay_ms", 300) or 300)))
        click_count = max(
            1,
            min(10, int(getattr(self.cfg, "spectator_lobby_auto_start_click_count", 1) or 1)),
        )
        activate = bool(getattr(self.cfg, "spectator_lobby_auto_start_activate", True))
        restore_focus = bool(getattr(self.cfg, "spectator_lobby_auto_start_restore_focus", True))
        restore_cursor = bool(getattr(self.cfg, "spectator_lobby_auto_start_restore_cursor", True))
        minimize_target = bool(
            getattr(self.cfg, "spectator_lobby_auto_start_minimize_target", False)
        )
        players = list((payload or {}).get("players") or [])
        logging.info(
            "LOBBY_AUTO_START_SCHEDULE delay_ms=%s title=%s client=(%s,%s) players=%s",
            delay_ms,
            title,
            x,
            y,
            players,
        )

        def _worker():
            try:
                if delay_ms > 0:
                    time.sleep(delay_ms / 1000.0)
                ok, detail = True, ""
                original_hwnd = int(ctypes.windll.user32.GetForegroundWindow() or 0) if os.name == "nt" else 0
                original_cursor = _current_cursor_screen_position()
                for index in range(click_count):
                    ok, detail = click_window_client_point(
                        title,
                        x,
                        y,
                        activate=activate and index == 0,
                        restore_focus=restore_focus and index == click_count - 1,
                        restore_cursor=restore_cursor and index == click_count - 1,
                        minimize_target=minimize_target and index == click_count - 1,
                        previous_hwnd_override=original_hwnd,
                        previous_cursor_override=original_cursor,
                    )
                    if not ok:
                        break
                    if index < click_count - 1:
                        time.sleep(0.12)
                if ok:
                    logging.info("LOBBY_AUTO_START_CLICK_OK %s", detail)
                else:
                    logging.error("LOBBY_AUTO_START_CLICK_FAIL %s", detail)
                self._lobby_auto_start_result.emit(bool(ok), str(detail or ""))
            except Exception:
                logging.exception("LOBBY_AUTO_START_CLICK_ERROR")
            finally:
                try:
                    lock.release()
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True, name="LobbyAutoStartClick").start()

    def _handle_lobby_auto_start_result(self, ok: bool, detail: str) -> None:
        message = ("자동 시작 클릭 성공" if ok else "자동 시작 클릭 실패") + (f": {detail}" if detail else "")
        try:
            self.timer_win.set_status(message)
        except Exception:
            pass
        try:
            if self.settings_dlg and hasattr(self.settings_dlg, "lbl_spectator_lobby_auto_start_state"):
                self.settings_dlg.lbl_spectator_lobby_auto_start_state.setText(message)
                self.settings_dlg.lbl_spectator_lobby_auto_start_state.setStyleSheet(
                    "color:#22c55e;" if ok else "color:#ef4444;"
                )
        except Exception:
            pass

    def apply_ui_update(self, d: dict):
        try:
            DIAG.record(
                "ui_update",
                keys=sorted([str(k) for k in (d or {}).keys()]),
                hit_effect_count=len(list((d or {}).get("spectator_hit_effect_events") or [])),
                effect_count=len(list((d or {}).get("spectator_effect_events") or [])),
                has_round_report=bool((d or {}).get("spectator_round_report")),
                has_lobby=bool((d or {}).get("spectator_lobby_overlay")),
                has_scorecard=bool((d or {}).get("spectator_scorecard")),
                has_winner=bool((d or {}).get("spectator_winner")),
                fast_emit=bool((d or {}).get("_hitfx_fast_emit", False)),
            )
        except Exception:
            pass
        if "spectator_lobby_auto_start" in d:
            try:
                self._schedule_lobby_auto_start_click(dict(d.get("spectator_lobby_auto_start") or {}))
            except Exception:
                logging.exception("LOBBY_AUTO_START_APPLY_FAIL")
        browser_output_only = bool(getattr(self.cfg, "browser_overlay_output_only", True))
        # Keep QML HUD state in sync even when OBS browser output is the main
        # broadcast path.  Only animation/effect calls are gated below.
        qml_visuals = True
        qml_effects = bool((not browser_output_only) and getattr(self.cfg, "qml_effects_enabled", False))
        if browser_output_only:
            self._apply_browser_overlay_direct_update(d)
        played_sfx = set()
        clear_match_overlay = bool(d.get("spectator_match_clear", False))
        reset_match_stats = bool(d.get("spectator_match_stats_reset", False))
        if ("blue_player_id" in d or "red_player_id" in d
                or "blue_player_registered" in d or "red_player_registered" in d
                or "blue_player_valid" in d or "red_player_valid" in d):
            if "blue_player_id" in d:
                self._current_blue_id = str(d.get("blue_player_id") or "")
            if "red_player_id" in d:
                self._current_red_id = str(d.get("red_player_id") or "")
            if "blue_player_registered" in d:
                self._current_blue_registered = bool(d.get("blue_player_registered"))
            if "red_player_registered" in d:
                self._current_red_registered = bool(d.get("red_player_registered"))
            if "blue_player_valid" in d:
                self._current_blue_valid = bool(d.get("blue_player_valid"))
            if "red_player_valid" in d:
                self._current_red_valid = bool(d.get("red_player_valid"))
            self._sync_current_players_to_config()
            # The app UI must keep showing the current player IDs even when
            # OBS/browser output is the primary output path.  The previous
            # browser_output_only gate caused the QML UI nameplate/profile IDs
            # to stay stale while the browser overlay was updated.
            try:
                self.timer_win.set_player_info(
                    self._current_blue_id,
                    self._current_red_id,
                    self._current_blue_registered,
                    self._current_red_registered,
                    self._current_blue_valid,
                    self._current_red_valid,
                )
                self._sync_current_player_flags_to_overlay()
                self._sync_koth_streak_to_overlay()
                # Portraits are now emitted only at bout start/player-change.
                # Do not re-resolve the same SpectatorLog portrait on every name/id update.
            except Exception:
                logging.exception("PLAYER_INFO_UI_SYNC_FAIL")
        if "koth_winner_id" in d:
            self._apply_koth_winner(
                d.get("koth_winner_id", ""),
                raw=str(d.get("koth_winner_raw", "") or ""),
                score=d.get("koth_winner_score", None),
                side=str(d.get("koth_winner_side", "") or ""),
            )
        if "blue_name" in d or "red_name" in d:
            try:
                self.timer_win.set_names(
                    d.get("blue_name", None),
                    d.get("red_name", None),
                )
            except Exception:
                logging.exception("PLAYER_NAME_UI_SYNC_FAIL")
        if "arena_name" in d:
            try:
                self.timer_win.set_arena_name(d.get("arena_name", None))
            except Exception:
                logging.exception("ARENA_NAME_UI_SYNC_FAIL")
        if "spectator_recent_text_size" in d:
            try:
                self.cfg.spectator_recent_text_size = int(d.get("spectator_recent_text_size", 23) or 23)
                if qml_visuals:
                    self.timer_win.set_spectator_recent_text_size(self.cfg.spectator_recent_text_size)
            except Exception:
                pass
        if bool(d.get("spectator_sp_reset", False)):
            try:
                if qml_visuals:
                    self.timer_win._backend.reset_spectator_sp()
            except Exception:
                pass
        if reset_match_stats and qml_visuals:
            self._reset_spectator_match_stats(clear_recent=True)
        if "blue_palette" in d or "red_palette" in d:
            if qml_visuals:
                self.timer_win.set_palettes(
                    d.get("blue_palette", None),
                    d.get("red_palette", None),
                )
        if "blue_player_img" in d or "red_player_img" in d:
            blue_log_img = d["blue_player_img"] if "blue_player_img" in d else _NO_UPDATE
            red_log_img = d["red_player_img"] if "red_player_img" in d else _NO_UPDATE
            blue_img = _NO_UPDATE
            red_img = _NO_UPDATE
            if blue_log_img is not _NO_UPDATE:
                blue_img, _src = self._resolve_portrait_image("blue", self._current_blue_id, blue_log_img)
            if red_log_img is not _NO_UPDATE:
                red_img, _src = self._resolve_portrait_image("red", self._current_red_id, red_log_img)
            try:
                self.timer_win.set_player_images(blue_img, red_img)
            except Exception:
                logging.exception("PLAYER_IMAGE_UI_SYNC_FAIL")
            try:
                if blue_img is not _NO_UPDATE:
                    self.browser_overlay.set_image("blue", blue_img)
                if red_img is not _NO_UPDATE:
                    self.browser_overlay.set_image("red", red_img)
            except Exception:
                pass
        if "blue_damage_dealt" in d or "red_damage_dealt" in d:
            try:
                if qml_visuals:
                    self.timer_win.set_spectator_total_damage(
                        float(d.get("blue_damage_dealt", 0.0) or 0.0),
                        float(d.get("red_damage_dealt", 0.0) or 0.0),
                    )
            except Exception:
                pass
        if "blue_round_damage_dealt" in d or "red_round_damage_dealt" in d:
            try:
                if qml_visuals:
                    self.timer_win.set_spectator_damage(
                        float(d.get("blue_round_damage_dealt", 0.0) or 0.0),
                        float(d.get("red_round_damage_dealt", 0.0) or 0.0),
                    )
            except Exception:
                pass
        if "stun_flash_sides" in d:
            try:
                for side in list(d.get("stun_flash_sides") or []):
                    side = str(side or "")
                    if qml_effects:
                        self.timer_win.trigger_stun_flash(side)
                    sfx_key = ("stun", side.lower().strip())
                    if sfx_key not in played_sfx:
                        played_sfx.add(sfx_key)
                        self._play_spectator_sfx("stun")
            except Exception:
                pass
        if "spectator_effect_events" in d:
            try:
                for ev in list(d.get("spectator_effect_events") or []):
                    kind = str((ev or {}).get("kind") or "")
                    side = str((ev or {}).get("side") or "")
                    if qml_effects:
                        self.timer_win.trigger_spectator_effect(
                            side,
                            kind,
                        )
                    sfx_key = (kind.lower().strip(), side.lower().strip())
                    if sfx_key not in played_sfx:
                        played_sfx.add(sfx_key)
                        self._play_spectator_sfx(kind)
            except Exception:
                pass
        if "spectator_hit_effect_events" in d:
            try:
                hit_threshold = max(0.0, float(getattr(self.cfg, "spectator_hit_effect_damage", 45.0) or 45.0))
                for ev in list(d.get("spectator_hit_effect_events") or []):
                    effect_kind = str((ev or {}).get("effect_kind") or "").lower()
                    if effect_kind == "stun":
                        side = str((ev or {}).get("side") or "")
                        if qml_effects:
                            self.timer_win.trigger_stun_flash(side)
                        continue
                    if effect_kind not in ("tko", "knockdown", "down") and float((ev or {}).get("damage", 0.0) or 0.0) < hit_threshold:
                        continue
                    if qml_effects:
                        self.timer_win.trigger_hit_impact(
                            str((ev or {}).get("side") or ""),
                            float((ev or {}).get("damage", 0.0) or 0.0),
                        )
            except Exception:
                pass
        if "spectator_log_info" in d:
            try:
                if qml_visuals:
                    self.timer_win.set_spectator_log_info(dict(d.get("spectator_log_info") or {}))
            except Exception:
                pass
        if "round_intro_event" in d:
            try:
                if qml_effects:
                    self.timer_win._backend.request_round_intro()
                ev = dict(d.get("round_intro_event") or {})
                if not browser_output_only:
                    self.browser_overlay.push_event("round_intro", round=ev.get("round", ""))
            except Exception:
                pass
        if "vs_intro_event" in d:
            try:
                if qml_effects:
                    self.timer_win._backend.vsIntroResetRequested.emit()
            except Exception:
                pass
            try:
                backend = getattr(self.timer_win, "_backend", None)
                blue_name = str(getattr(backend, "_blue_name", "") or d.get("blue_name", "") or "").strip()
                red_name = str(getattr(backend, "_red_name", "") or d.get("red_name", "") or "").strip()
                blue_text = self._chapter_competitor_text(
                    "blue",
                    blue_name,
                    self._current_blue_id,
                    self._current_blue_registered,
                )
                red_text = self._chapter_competitor_text(
                    "red",
                    red_name,
                    self._current_red_id,
                    self._current_red_registered,
                )
                unknown = UNKNOWN_PLAYER_LABEL.upper()
                if blue_text and red_text and blue_text.upper() != unknown and red_text.upper() != unknown:
                    blue_key = str(self._current_blue_id or blue_name or blue_text).upper().strip()
                    red_key = str(self._current_red_id or red_name or red_text).upper().strip()
                    self._append_chapter_event(
                        f"{blue_text} VS {red_text}",
                        {
                            "source": "spectatorlog_vs_intro",
                            "blue_name": blue_name,
                            "red_name": red_name,
                            "blue_id": str(self._current_blue_id or ""),
                            "red_id": str(self._current_red_id or ""),
                            "blue_registered": bool(self._current_blue_registered),
                            "red_registered": bool(self._current_red_registered),
                        },
                        dedupe_key=f"vs:{blue_key}:{red_key}",
                    )
            except Exception:
                logging.exception("CHAPTER_VS_INTRO_APPEND_FAIL")
        if "commentary_tts_stop_roles" in d:
            try:
                stop_reason = str(d.get("commentary_tts_stop_reason") or "")
                roles = d.get("commentary_tts_stop_roles") or []
                if isinstance(roles, str):
                    roles = [roles]
                for stop_role in list(roles or []):
                    self._stop_commentary_tts_role(str(stop_role or "analyst"), stop_reason)
            except Exception:
                logging.exception("COMMENTARY_TTS_STOP_ROLES_APPLY_FAIL")
        if "commentary_tts_stop_role" in d:
            try:
                stop_role = str(d.get("commentary_tts_stop_role") or "analyst")
                stop_reason = str(d.get("commentary_tts_stop_reason") or "")
                self._stop_commentary_tts_role(stop_role, stop_reason)
            except Exception:
                logging.exception("COMMENTARY_TTS_STOP_APPLY_FAIL")
        if "commentary_tts_text" in d:
            try:
                text = str(d.get("commentary_tts_text") or "").strip()
                if text:
                    rate_override = d.get("commentary_tts_rate", None)
                    pitch_override = d.get("commentary_tts_pitch", None)
                    self._speak_commentary_tts(
                        text,
                        str(d.get("commentary_tts_role") or "analyst"),
                        rate_override=rate_override,
                        pitch_override=pitch_override,
                    )
                    logging.info("COMMENTARY_TTS text=%s", text)
            except Exception:
                pass
        if "commentary_tts_round_summary_text" in d:
            try:
                summary_text = str(d.get("commentary_tts_round_summary_text") or "").strip()
                if summary_text:
                    try:
                        delay_ms = int(d.get("commentary_tts_round_summary_delay_ms", 0) or 0)
                    except Exception:
                        delay_ms = 0
                    summary_role = str(d.get("commentary_tts_round_summary_role") or "analyst")
                    self._schedule_commentary_round_summary_tts(summary_text, summary_role, delay_ms=delay_ms)
            except Exception:
                logging.exception("COMMENTARY_TTS_ROUND_SUMMARY_QUEUE_FAIL")
        if "commentary_tts_followup_text" in d:
            try:
                follow_text = str(d.get("commentary_tts_followup_text") or "").strip()
                if follow_text:
                    try:
                        delay_ms = int(d.get("commentary_tts_followup_delay_ms", 1800) or 1800)
                    except Exception:
                        delay_ms = 1800
                    follow_role = str(d.get("commentary_tts_followup_role") or "analyst")
                    self._schedule_commentary_followup_tts(follow_text, follow_role, delay_ms=delay_ms, retries=6)
                    logging.info("COMMENTARY_TTS_FOLLOWUP text=%s delay_ms=%s", follow_text, delay_ms)
            except Exception:
                pass
        if "commentary_tts_followups" in d:
            try:
                followups = d.get("commentary_tts_followups") or []
                if isinstance(followups, dict):
                    followups = [followups]
                for item in list(followups or []):
                    if not isinstance(item, dict):
                        continue
                    follow_text = str(item.get("text") or item.get("commentary_tts_followup_text") or "").strip()
                    if not follow_text:
                        continue
                    try:
                        delay_ms = int(item.get("delay_ms", item.get("commentary_tts_followup_delay_ms", 1800)) or 1800)
                    except Exception:
                        delay_ms = 1800
                    try:
                        retries = int(item.get("retries", 3) or 3)
                    except Exception:
                        retries = 3
                    follow_role = str(item.get("role") or item.get("commentary_tts_followup_role") or "analyst")
                    self._schedule_commentary_followup_tts(follow_text, follow_role, delay_ms=delay_ms, retries=retries)
                    logging.info("COMMENTARY_TTS_FOLLOWUP_LIST text=%s delay_ms=%s role=%s", follow_text, delay_ms, follow_role)
            except Exception:
                logging.exception("COMMENTARY_TTS_FOLLOWUP_LIST_APPLY_FAIL")
        if "round_current" in d or "round_total" in d or "seconds_left" in d:
            if "spectator_time_mode" in d:
                try:
                    if qml_visuals:
                        self.timer_win.timer_stop()
                except Exception:
                    pass
            try:
                backend = getattr(self.timer_win, "_backend", None)
                logging.info(
                    "TIMER_SYNC_APPLY_BEGIN source=%s mode=%s rest=%s in_rest_before=%s round=%s/%s seconds_left=%s prev_round=%s prev_seconds=%s running=%s",
                    "spectatorlog" if "spectator_time_mode" in d else "legacy_action",
                    d.get("spectator_time_mode", ""),
                    d.get("spectator_rest_mode", None),
                    getattr(backend, "in_rest", None),
                    d.get("round_current", None),
                    d.get("round_total", None),
                    d.get("seconds_left", None),
                    getattr(backend, "current_round", None),
                    getattr(backend, "seconds_left", None),
                    getattr(backend, "running", None),
                )
            except Exception:
                pass
            if "spectator_rest_mode" in d:
                try:
                    if qml_visuals:
                        self.timer_win.set_log_rest_mode(bool(d.get("spectator_rest_mode")))
                except Exception:
                    pass
            if qml_visuals:
                self.timer_win.set_round_time(
                    d.get("round_current", None),
                    d.get("round_total", None),
                    d.get("seconds_left", None),
                )
            try:
                logging.info(
                    "TIMER_SYNC_APPLY_DONE source=%s round_current=%s round_total=%s seconds_left=%s in_rest=%s text=%s round_text=%s",
                    "spectatorlog" if "spectator_time_mode" in d else "legacy_action",
                    d.get("round_current", None),
                    d.get("round_total", None),
                    d.get("seconds_left", None),
                    getattr(getattr(self.timer_win, "_backend", None), "in_rest", None),
                    getattr(getattr(self.timer_win, "_backend", None), "_time_text", ""),
                    getattr(getattr(self.timer_win, "_backend", None), "_round_text", ""),
                )
            except Exception:
                pass
            # Prevent settings auto-apply from overwriting freshly synchronized timer values.
            try:
                setattr(self.cfg, "_timer_lock_until", time.time() + 2.0)
            except Exception:
                pass
            try:
                if "round_total" in d and d.get("round_total", None) is not None:
                    self.cfg.timer_total_rounds = int(d.get("round_total"))
                if "round_current" in d and d.get("round_current", None) is not None:
                    self.cfg.timer_current_round = int(d.get("round_current"))
                if "seconds_left" in d and d.get("seconds_left", None) is not None:
                    self.cfg.timer_seconds_left = int(d.get("seconds_left"))
                if self.settings_dlg:
                    if hasattr(self.settings_dlg, "sp_timer_total") and "round_total" in d and d.get("round_total", None) is not None:
                        self.settings_dlg.sp_timer_total.setValue(int(d.get("round_total")))
                    if hasattr(self.settings_dlg, "sp_timer_current") and "round_current" in d and d.get("round_current", None) is not None:
                        self.settings_dlg.sp_timer_current.setValue(int(d.get("round_current")))
                    if hasattr(self.settings_dlg, "sp_timer_left") and "seconds_left" in d and d.get("seconds_left", None) is not None:
                        self.settings_dlg.sp_timer_left.setValue(int(d.get("seconds_left")))
            except Exception:
                pass
        if ("timer_total_rounds" in d or "timer_round_sec" in d
                or "timer_rest_sec" in d or "timer_current_round" in d
                or "timer_seconds_left" in d):
            if qml_visuals:
                self.timer_win.set_timer_settings(
                    d.get("timer_total_rounds", None),
                    d.get("timer_round_sec", None),
                    d.get("timer_rest_sec", None),
                    d.get("timer_current_round", None),
                    d.get("timer_seconds_left", None),
                )
        if "blue_win_streak" in d or "red_win_streak" in d:
            if qml_visuals:
                self.timer_win.set_win_streaks(
                    d.get("blue_win_streak", None),
                    d.get("red_win_streak", None),
                )
        if "effect_settings" in d:
            if qml_visuals:
                self.timer_win.set_effect_settings(d.get("effect_settings", None))
        if "overlay_bg_color" in d:
            if qml_visuals:
                self.timer_win.set_overlay_bg_color(d.get("overlay_bg_color", None))
        if "overlay_bg_opacity" in d:
            if qml_visuals:
                self.timer_win.set_overlay_bg_opacity(d.get("overlay_bg_opacity", None))
        if "overlay_preset" in d:
            self.cfg.overlay_preset = str(d.get("overlay_preset", "classic") or "classic")
            if qml_visuals:
                self.timer_win.set_overlay_preset(self.cfg.overlay_preset)
        if "overlay_player_mask" in d:
            if qml_visuals:
                self.timer_win.set_player_mask_shape(d.get("overlay_player_mask", "square"))
        if ("overlay_show_round" in d or "overlay_show_time" in d
                or "overlay_show_blue_img" in d or "overlay_show_blue_name" in d
                or "overlay_show_red_img" in d or "overlay_show_red_name" in d
                or "overlay_show_arena_name" in d
                or "overlay_show_flags" in d or "overlay_show_cinematic" in d
                or "browser_overlay_scale" in d or "browser_overlay_output_only" in d
                or "browser_fullscreen_fx_intensity" in d
                or "qml_preview_enabled" in d or "qml_effects_enabled" in d):
            if "browser_overlay_scale" in d:
                try:
                    self.cfg.browser_overlay_scale = max(0.25, min(4.0, float(d.get("browser_overlay_scale", 1.0) or 1.0)))
                except Exception:
                    self.cfg.browser_overlay_scale = 1.0
            if "browser_overlay_output_only" in d:
                self.cfg.browser_overlay_output_only = bool(d.get("browser_overlay_output_only", True))
            if "browser_fullscreen_fx_intensity" in d:
                try:
                    self.cfg.browser_fullscreen_fx_intensity = max(0.0, min(3.0, float(d.get("browser_fullscreen_fx_intensity", 1.6) or 1.6)))
                except Exception:
                    self.cfg.browser_fullscreen_fx_intensity = 1.6
            if "qml_preview_enabled" in d:
                self.cfg.qml_preview_enabled = bool(d.get("qml_preview_enabled", True))
                try:
                    self.timer_win.set_qml_preview_enabled(self.cfg.qml_preview_enabled)
                except Exception:
                    pass
            if "qml_effects_enabled" in d:
                self.cfg.qml_effects_enabled = bool(d.get("qml_effects_enabled", False))
                try:
                    self.timer_win.set_qml_effects_enabled(self.cfg.qml_effects_enabled)
                except Exception:
                    pass
            if qml_visuals:
                self.timer_win.set_overlay_visibility(
                    round_visible=d.get("overlay_show_round", None),
                    time_visible=d.get("overlay_show_time", None),
                    blue_img_visible=d.get("overlay_show_blue_img", None),
                    blue_name_visible=d.get("overlay_show_blue_name", None),
                    red_img_visible=d.get("overlay_show_red_img", None),
                    red_name_visible=d.get("overlay_show_red_name", None),
                    arena_name_visible=d.get("overlay_show_arena_name", None),
                    flags_visible=d.get("overlay_show_flags", None),
                    cinematic_visible=(
                        (bool(d.get("overlay_show_cinematic", getattr(self.cfg, "overlay_show_cinematic", True)))
                         and not bool(getattr(self.cfg, "browser_overlay_output_only", True)))
                        if ("overlay_show_cinematic" in d or "browser_overlay_output_only" in d) else None
                    ),
                )
        if "overlay_style" in d:
            style = dict(d.get("overlay_style") or {})
            try:
                self.cfg.overlay_style_round = _normalize_overlay_style(style.get("round"), _default_overlay_style_round())
                self.cfg.overlay_style_time = _normalize_overlay_style(style.get("time"), _default_overlay_style_time())
                self.cfg.overlay_style_blue_name = _normalize_overlay_style(style.get("blue_name"), _default_overlay_style_blue_name())
                self.cfg.overlay_style_red_name = _normalize_overlay_style(style.get("red_name"), _default_overlay_style_red_name())
                self.cfg.overlay_style_arena = _normalize_overlay_style(style.get("arena"), _default_overlay_style_arena())
            except Exception:
                pass
            if qml_visuals:
                self.timer_win.set_overlay_style(style)
        if "browser_text_styles" in d:
            try:
                self.cfg.browser_text_styles = _normalize_browser_text_styles(d.get("browser_text_styles"))
            except Exception:
                pass
        if ("overlay_vs_bg_path" in d or "overlay_vs_bg_by_arena" in d
                or "overlay_vs_bg_opacity" in d or "overlay_vs_hold_sec" in d):
            self.cfg.overlay_vs_bg_path = str(d.get("overlay_vs_bg_path", getattr(self.cfg, "overlay_vs_bg_path", "")) or "")
            self.cfg.overlay_vs_bg_by_arena = dict(d.get("overlay_vs_bg_by_arena", getattr(self.cfg, "overlay_vs_bg_by_arena", {}) or {}) or {})
            try:
                self.cfg.overlay_vs_bg_opacity = max(0.0, min(1.0, float(d.get("overlay_vs_bg_opacity", getattr(self.cfg, "overlay_vs_bg_opacity", 1.0)))))
            except Exception:
                self.cfg.overlay_vs_bg_opacity = 1.0
            try:
                self.cfg.overlay_vs_hold_sec = max(0.5, min(15.0, float(d.get("overlay_vs_hold_sec", getattr(self.cfg, "overlay_vs_hold_sec", 2.85)))))
            except Exception:
                self.cfg.overlay_vs_hold_sec = 2.85
            try:
                if getattr(self, "browser_overlay", None):
                    self.browser_overlay.update(**self._sync_browser_overlay_player_assets({}))
                    self.browser_overlay.update(
                        vsBgOpacity=float(self.cfg.overlay_vs_bg_opacity),
                        overlayVsHoldMs=int(max(500, min(15000, float(self.cfg.overlay_vs_hold_sec) * 1000))),
                    )
            except Exception:
                pass
            if qml_visuals:
                self.timer_win._backend.set_overlay_vs_background(
                    self.cfg.overlay_vs_bg_path,
                    self.cfg.overlay_vs_bg_by_arena,
                    self.cfg.overlay_vs_bg_opacity,
                )
                self.timer_win._backend.set_overlay_vs_hold_sec(self.cfg.overlay_vs_hold_sec)
        if ("overlay_timer_font_size" in d or "overlay_timer_x" in d or "overlay_timer_y" in d
                or "overlay_round_font_size" in d or "overlay_round_x" in d or "overlay_round_y" in d):
            try:
                if "overlay_timer_font_size" in d:
                    self.cfg.overlay_timer_font_size = max(24, min(96, int(d.get("overlay_timer_font_size", 54) or 54)))
                if "overlay_timer_x" in d:
                    self.cfg.overlay_timer_x = max(-160, min(160, int(d.get("overlay_timer_x", 0) or 0)))
                if "overlay_timer_y" in d:
                    self.cfg.overlay_timer_y = max(-80, min(120, int(d.get("overlay_timer_y", 0) or 0)))
                if "overlay_round_font_size" in d:
                    self.cfg.overlay_round_font_size = max(6, min(40, int(d.get("overlay_round_font_size", 11) or 11)))
                if "overlay_round_x" in d:
                    self.cfg.overlay_round_x = max(-160, min(160, int(d.get("overlay_round_x", 0) or 0)))
                if "overlay_round_y" in d:
                    self.cfg.overlay_round_y = max(-80, min(120, int(d.get("overlay_round_y", 0) or 0)))
            except Exception:
                pass
        if "overlay_ui_scale" in d:
            try:
                scale = float(d.get("overlay_ui_scale", 1.0))
            except Exception:
                scale = 1.0
            if scale <= 0:
                scale = 1.0
            self.cfg.overlay_ui_scale = scale
            if qml_visuals:
                self.timer_win.set_overlay_ui_scale(scale)
        if "overlay_layout" in d:
            try:
                layout = d.get("overlay_layout", None)
                if isinstance(layout, dict):
                    self.cfg.layout = dict(layout)
                if qml_visuals:
                    self.timer_win.set_overlay_layout(layout)
            except Exception:
                pass
        if clear_match_overlay and qml_visuals:
            self._clear_spectator_match_overlay()

    def _reset_spectator_match_stats(self, clear_recent: bool = True):
        try:
            self.timer_win.set_spectator_total_damage(0, 0)
        except Exception:
            pass
        try:
            self.timer_win.set_spectator_damage(0, 0)
        except Exception:
            pass
        try:
            self.timer_win._backend.reset_spectator_sp()
        except Exception:
            pass
        info = {
            "blue_punishment_text": "",
            "red_punishment_text": "",
            "blue_punishment_mid": 0.0,
            "red_punishment_mid": 0.0,
            "blue_punishment_long": 0.0,
            "red_punishment_long": 0.0,
            "blue_round_knockdowns": 0,
            "red_round_knockdowns": 0,
            "blue_combo_hit_text": "",
            "red_combo_hit_text": "",
            "blue_combo_damage_text": "",
            "red_combo_damage_text": "",
        }
        if clear_recent:
            info.update({
                "recent_hit_text": "",
                "blue_recent_hit_text": "",
                "red_recent_hit_text": "",
                "match_text": "",
                "blue_meta_text": "",
                "red_meta_text": "",
                "camera_text": "",
            })
        try:
            self.timer_win.set_spectator_log_info(info)
        except Exception:
            pass

    def _clear_spectator_match_overlay(self):
        self._reset_spectator_match_stats(clear_recent=True)
        try:
            self.timer_win.set_spectator_log_info({})
        except Exception:
            pass

    def show(self):
        self.timer_win.show()
        if not bool(getattr(self.cfg, "qml_preview_enabled", True)) and hasattr(self.timer_win, "set_qml_preview_enabled"):
            self.timer_win.set_qml_preview_enabled(False)
















def main():
    _suppress_qt_window_warnings()
    _ensure_std_streams()
    cfg_path = resolve_config_path()
    _setup_logging(cfg_path)
    app = QApplication(sys.argv)
    app.setStyleSheet(
        "QMenuBar { background:#1b1f2a; color:#ffffff; }"
        "QMenuBar::item { background:transparent; color:#ffffff; }"
        "QMenuBar::item:selected { background:#2d3748; }"
        "QMenu { background:#1b1f2a; color:#ffffff; }"
        "QMenu::item:selected { background:#334155; }"
    )
    main_app = MainApp(cfg_path)
    app.aboutToQuit.connect(main_app.on_app_quit)
    main_app.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
