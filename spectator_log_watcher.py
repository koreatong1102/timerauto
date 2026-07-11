from __future__ import annotations

import logging
import os
import re
import threading
import time
import ctypes
from ctypes import wintypes
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal
from diagnostics import diagnostics as DIAG
from spectator_log_blackbox import SpectatorLogBlackboxRecorder


COUNTER_PREV_DAMAGE_THRESHOLD = 15.0
COUNTER_DEALT_DAMAGE_THRESHOLD = 30.0
COUNTER_WINDOW_SEC = 0.7
PLAYER_ID_ALLOW_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-."


def default_spectatorlog_path_resolver(path: str = "") -> str:
    raw = str(path or "").strip()
    if raw:
        return os.path.abspath(raw)
    # Same first-run release fallback as app_paths.resolve_spectatorlog_path.
    candidates = []
    for env_name in ("USERPROFILE", "OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        base = os.environ.get(env_name, "")
        if base:
            candidates.append(os.path.join(base, "Documents", "ThrillOfTheFight2", "SpectatorLog"))
            candidates.append(os.path.join(base, "Documents", "TheThrillOfTheFight2", "SpectatorLog"))
    home = os.path.expanduser("~")
    if home and home != "~":
        candidates.append(os.path.join(home, "Documents", "ThrillOfTheFight2", "SpectatorLog"))
    for candidate in candidates:
        if os.path.isdir(candidate):
            return os.path.abspath(candidate)
    return os.path.abspath(os.path.join("ThrillOfTheFight2", "SpectatorLog"))


def default_game_id_normalizer(value: str, allow: str) -> str:
    allow_set = set(str(allow or ""))
    return "".join(ch for ch in str(value or "").upper().strip() if ch in allow_set)


def default_player_gid_canonicalizer(_cfg: Any, gid: str, threshold: int = 70) -> str:
    return str(gid or "").upper().strip()


def _safe_cv2_imread(path: str, flags: int = cv2.IMREAD_UNCHANGED) -> Optional[np.ndarray]:
    """Read images without cv2.imread path warnings on Windows unicode paths."""
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


class SpectatorLogWatcher(QObject):
    ui_update = pyqtSignal(dict)
    status_update = pyqtSignal(str)

    def __init__(self, cfg: Any, *, spectatorlog_path_resolver=default_spectatorlog_path_resolver, game_id_normalizer=default_game_id_normalizer, player_gid_canonicalizer=default_player_gid_canonicalizer):
        super().__init__()
        self.cfg = cfg
        self._resolve_spectatorlog_path = spectatorlog_path_resolver
        self._normalize_game_id = game_id_normalizer
        self._canonical_player_gid_for_cfg = player_gid_canonicalizer
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False
        self._last_signature: Tuple[Any, ...] = tuple()
        self._image_mtimes: Dict[str, float] = {}
        self._portrait_locked: Dict[str, bool] = {"blue": False, "red": False}
        self._portrait_lock_name: Dict[str, str] = {"blue": "", "red": ""}
        # Realtime performance guard: player/name/portrait data is static for a bout.
        # Emit it only on a new pair or new MatchIntro, not on every round_time/camera write.
        self._last_player_payload_pair: Tuple[str, str] = ("", "")
        self._last_state_emit_sig: Tuple[Any, ...] = tuple()
        self._last_log_info_emit_at: float = 0.0
        self._last_log_info_sig: Tuple[Any, ...] = tuple()
        self._last_stun_counts: Dict[str, int] = {"blue": 0, "red": 0}
        self._last_effect_counts: Dict[str, Dict[str, int]] = {
            "blue": {"stun": 0, "knockdown": 0, "tko": 0},
            "red": {"stun": 0, "knockdown": 0, "tko": 0},
        }
        self._damage_initialized = False
        self._total_damage_dealt: Dict[str, float] = {"blue": 0.0, "red": 0.0}
        self._damage_total_offset: Dict[str, float] = {"blue": 0.0, "red": 0.0}
        self._damage_file_last_dealt: Dict[str, float] = {"blue": 0.0, "red": 0.0}
        self._last_damage_update_sig: Tuple[int, int] = (0, 0)
        # Stage57: the realtime hot path may see damage_events.txt before the
        # full watcher pass.  Keep a separate signature and handoff buffer so
        # fast hit FX does not consume the event before TTS/report logic can
        # react to knockdowns, stuns, TKO, counters and normal commentary.
        self._last_fast_damage_update_sig: Tuple[int, int] = (0, 0)
        self._fast_pending_damage_sig: Tuple[int, int] = (0, 0)
        self._fast_pending_new_events: List[dict] = []
        self._fast_pending_effect_events: List[dict] = []
        self._seen_damage_event_keys: set = set()
        self._recent_damage_events: deque[dict] = deque(maxlen=80)
        self._pose_file_cache: Dict[str, Dict[str, Any]] = {}
        self._combo_state: Dict[str, Any] = {
            "attacker_side": "",
            "receiver_side": "",
            "last_time": None,
            "count": 0,
            "damage": 0.0,
        }
        self._last_counter_event: Optional[dict] = None
        self._last_round_time_value: Optional[float] = None
        self._last_round_time_round: Optional[int] = None
        self._last_round_time_state: str = ""
        self._round_time_mode: str = "auto"
        self._round_time_auto_modes: Dict[str, str] = {}
        self._last_round_state: str = ""
        self._last_lobby_sig: Tuple[int, int] = (0, 0)
        self._last_lobby_exists: bool = False
        self._lobby_ready_latched: bool = False
        self._last_lobby_rounds: Optional[int] = None
        self._last_lobby_round_duration: Optional[int] = None
        self._last_lobby_break_duration: Optional[int] = None
        self._break_started_wall: Optional[float] = None
        self._break_started_round: Optional[int] = None
        self._last_scorecard_overlay_key: Tuple[Any, ...] = tuple()
        self._last_winner_overlay_key: Tuple[Any, ...] = tuple()
        self._last_accessibility_sig: Tuple[Any, ...] = tuple()
        self._last_round_intro_key: Tuple[Optional[int], str] = (None, "")
        self._last_caster_event_key: Tuple[str, Optional[int], str] = ("", None, "")
        self._last_fight_round_no: Optional[int] = None
        self._last_active_match_pair: Tuple[str, str] = ("", "")
        self._last_vs_intro_pair: Tuple[str, str] = ("", "")
        self._last_match_reset_pair: Tuple[str, str] = ("", "")
        self._last_synced_seconds_left: Optional[int] = None
        self._last_fight_seconds_left: Optional[int] = None
        self._last_rest_seconds_left: Optional[int] = None
        self._commentary_last_at = 0.0
        self._last_round_summary_key: Tuple[Optional[int], str, str] = (None, "", "")
        self._last_round_report_key: Tuple[Optional[int], str, str] = (None, "", "")
        self._last_match_summary_key: Tuple[str, str, str] = ("", "", "")
        self._commentary_recent_lines: deque[Tuple[str, float]] = deque(maxlen=24)
        self._commentary_category_last_at: Dict[str, float] = {}
        self._commentary_meaning_last_at: Dict[str, float] = {}
        self._last_damage_seen_at = 0.0
        self._last_fight_state_started_at = 0.0
        self._last_idle_commentary_at = 0.0
        self._witty_duo_round_key: Optional[int] = None
        self._witty_duo_round_count = 0
        self._witty_duo_recent: deque[Tuple[str, float]] = deque(maxlen=24)
        self._down_round_key: Optional[int] = None
        self._down_round_counts: Dict[str, int] = {"blue": 0, "red": 0}
        self._down_active: Dict[str, Any] = {"side": "", "round": None, "count": 0, "at": 0.0}
        self._punishment_mid_forced_until: Dict[str, float] = {"blue": 0.0, "red": 0.0}
        self._punishment_history: deque[Tuple[float, Dict[str, Dict[str, float]]]] = deque(maxlen=240)
        self._scorecard_rounds: Dict[int, Dict[str, Any]] = {}
        self._scorecard_seen_event_keys: set = set()
        self._scorecard_last_pair: Tuple[str, str] = ("", "")
        # punches_thrown.txt can be cumulative for a whole match.  Keep the
        # starting snapshot for each round so report accuracy stays per-round.
        self._scorecard_thrown_round_baselines: Dict[int, Dict[str, Any]] = {}
        self._scorecard_thrown_last_cumulative: Dict[str, Any] = {
            "counts": {"blue": 0, "red": 0},
            "breakdown": {"blue": {}, "red": {}},
        }
        self._change_event = threading.Event()
        self._change_thread: Optional[threading.Thread] = None
        self._change_root: str = ""
        self._change_handle: Optional[int] = None
        self._blackbox = SpectatorLogBlackboxRecorder(cfg)
        # Stage55 realtime hot-path state.  The first read is a baseline so
        # stale lobby/score/winner files are not replayed as fresh overlays.
        self._runtime_baseline_ready = False
        self._last_fast_punishment_sig: Tuple[Any, ...] = tuple()
        self._last_fast_punishment_emit_at: float = 0.0
        self._last_full_update_at: float = 0.0

    def start(self):
        if self.is_running():
            return
        try:
            DIAG.record("spectator_watcher_start", path=str(getattr(self.cfg, "spectatorlog_path", "") or ""))
        except Exception:
            pass
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop_event,), daemon=True)
        self._running = True
        self._thread.start()

    def stop(self):
        try:
            DIAG.record("spectator_watcher_stop")
        except Exception:
            pass
        try:
            self._stop_event.set()
        except Exception:
            pass
        self._stop_change_notifier()
        try:
            self._blackbox.close()
        except Exception:
            pass
        self._running = False

    def force_refresh(self):
        self._last_signature = tuple()
        self._last_state_emit_sig = tuple()
        self._last_log_info_sig = tuple()
        self._last_player_payload_pair = ("", "")
        self._image_mtimes = {}
        self._last_round_time_value = None
        self._last_round_time_round = None
        self._last_round_time_state = ""
        self._round_time_auto_modes = {}
        self._runtime_baseline_ready = False
        self._last_fast_punishment_sig = tuple()
        self._last_fast_punishment_emit_at = 0.0
        self._reset_portrait_locks()

    def is_running(self) -> bool:
        return bool(self._running and self._thread and self._thread.is_alive())

    def _safe_emit_update(self, payload: dict) -> bool:
        if not payload or self._stop_event.is_set():
            return False
        try:
            self.ui_update.emit(dict(payload or {}))
            return True
        except RuntimeError:
            # Qt object may already be deleted while the worker is shutting down.
            return False
        except Exception:
            logging.debug("SPECTATORLOG_SAFE_EMIT_UPDATE_FAIL", exc_info=True)
            return False

    def _safe_emit_status(self, text: str) -> bool:
        if self._stop_event.is_set():
            return False
        try:
            self.status_update.emit(str(text or ""))
            return True
        except RuntimeError:
            return False
        except Exception:
            logging.debug("SPECTATORLOG_SAFE_EMIT_STATUS_FAIL", exc_info=True)
            return False

    def _run(self, stop_event: threading.Event):
        try:
            while not stop_event.is_set():
                if not bool(getattr(self.cfg, "spectatorlog_enabled", False)):
                    stop_event.wait(0.25)
                    continue
                root = self._resolve_spectatorlog_path(str(getattr(self.cfg, "spectatorlog_path", "") or ""))
                if not os.path.isdir(root):
                    self._safe_emit_status("SpectatorLog 폴더 없음")
                    self._stop_change_notifier()
                    stop_event.wait(1.0)
                    continue
                file_watch = bool(getattr(self.cfg, "spectatorlog_file_watch_enabled", True))
                if file_watch:
                    self._ensure_change_notifier(root, stop_event)
                else:
                    self._stop_change_notifier()
                # Stage55: broadcast hot path first.  Blackbox archiving is useful
                # for research, but it scans/copies the whole SpectatorLog tree and
                # must never sit in front of hit FX or gauge emission.
                try:
                    fast_update = self._read_realtime_fast_update(root)
                    if fast_update:
                        try:
                            DIAG.record("spectator_fast_update_emit", keys=sorted([str(k) for k in fast_update.keys()]), root=root)
                        except Exception:
                            pass
                        self._safe_emit_update(fast_update)
                except Exception:
                    logging.exception("SPECTATORLOG_FAST_READ_FAIL")
                try:
                    update = self._read_update(root)
                    if update:
                        try:
                            DIAG.record("spectator_update_emit", keys=sorted([str(k) for k in update.keys()]), root=root)
                        except Exception:
                            pass
                        self._safe_emit_update(update)
                        self._last_full_update_at = time.time()
                except Exception:
                    logging.exception("SPECTATORLOG_READ_FAIL")
                try:
                    if bool(getattr(self.cfg, "spectatorlog_blackbox_enabled", False)):
                        self._blackbox.poll(root)
                    else:
                        self._blackbox.close()
                except Exception:
                    logging.exception("SPECTATORLOG_BLACKBOX_POLL_FAIL")
                if file_watch:
                    wait_sec = max(0.25, min(10.0, float(getattr(self.cfg, "spectatorlog_backup_poll_ms", 1500) or 1500) / 1000.0))
                else:
                    wait_sec = max(0.1, min(5.0, float(getattr(self.cfg, "spectatorlog_poll_ms", 250) or 250) / 1000.0))
                changed = self._change_event.wait(wait_sec)
                self._change_event.clear()
                if changed and file_watch:
                    debounce = max(0.0, min(0.5, float(getattr(self.cfg, "spectatorlog_debounce_ms", 35) or 35) / 1000.0))
                    if debounce > 0:
                        stop_event.wait(debounce)
        finally:
            self._stop_change_notifier()
            try:
                self._blackbox.close()
            except Exception:
                pass
            if self._thread == threading.current_thread():
                self._running = False

    def _ensure_change_notifier(self, root: str, stop_event: threading.Event) -> None:
        root = os.path.abspath(str(root or ""))
        if not bool(getattr(self.cfg, "spectatorlog_file_watch_enabled", True)):
            self._stop_change_notifier()
            return
        if os.name != "nt" or not root:
            return
        if self._change_thread and self._change_thread.is_alive() and self._change_root == root:
            return
        self._stop_change_notifier()
        self._change_root = root
        self._change_event.set()
        self._change_thread = threading.Thread(
            target=self._watch_log_directory_changes,
            args=(root, stop_event),
            daemon=True,
        )
        self._change_thread.start()

    def _stop_change_notifier(self) -> None:
        handle = self._change_handle
        self._change_handle = None
        self._change_root = ""
        self._change_event.set()
        if handle:
            try:
                ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(handle))
            except Exception:
                pass

    def _watch_log_directory_changes(self, root: str, stop_event: threading.Event) -> None:
        if os.name != "nt":
            return
        try:
            kernel32 = ctypes.windll.kernel32
            file_list_directory = 0x0001
            file_share_read = 0x00000001
            file_share_write = 0x00000002
            file_share_delete = 0x00000004
            open_existing = 3
            file_flag_backup_semantics = 0x02000000
            invalid_handle_value = ctypes.c_void_p(-1).value
            notify_filter = 0x00000001 | 0x00000002 | 0x00000004 | 0x00000008 | 0x00000010 | 0x00000100
            kernel32.CreateFileW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            kernel32.CreateFileW.restype = wintypes.HANDLE
            handle = kernel32.CreateFileW(
                root,
                file_list_directory,
                file_share_read | file_share_write | file_share_delete,
                None,
                open_existing,
                file_flag_backup_semantics,
                None,
            )
            handle_value = int(handle)
            if handle_value == 0 or handle_value == invalid_handle_value:
                return
            self._change_handle = handle_value
            buf = ctypes.create_string_buffer(16384)
            bytes_returned = wintypes.DWORD(0)
            while not stop_event.is_set() and self._change_root == root:
                ok = kernel32.ReadDirectoryChangesW(
                    handle,
                    ctypes.byref(buf),
                    ctypes.sizeof(buf),
                    True,
                    notify_filter,
                    ctypes.byref(bytes_returned),
                    None,
                    None,
                )
                if not ok or stop_event.is_set() or self._change_root != root:
                    break
                self._change_event.set()
        except Exception:
            logging.debug("SPECTATORLOG_CHANGE_NOTIFIER_STOPPED", exc_info=True)
        finally:
            handle = self._change_handle
            if handle:
                try:
                    ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(handle))
                except Exception:
                    pass
            if self._change_root == root:
                self._change_handle = None

    def _read_text(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return f.read().strip()
        except UnicodeDecodeError:
            try:
                with open(path, "r", encoding="cp949", errors="ignore") as f:
                    return f.read().strip()
            except Exception:
                return ""
        except Exception:
            return ""

    def _read_image_if_changed(self, key: str, path: str) -> Tuple[bool, Optional[np.ndarray]]:
        try:
            mt = os.path.getmtime(path)
        except Exception:
            return False, None
        if self._image_mtimes.get(key) == mt:
            return False, None
        img = _safe_cv2_imread(path, cv2.IMREAD_UNCHANGED)
        if img is None or getattr(img, "size", 0) == 0:
            return False, None
        self._image_mtimes[key] = mt
        return True, img

    def _reset_portrait_locks(self) -> None:
        self._portrait_locked = {"blue": False, "red": False}
        self._portrait_lock_name = {"blue": "", "red": ""}
        self._image_mtimes.pop("blue", None)
        self._image_mtimes.pop("red", None)
        self._last_signature = tuple()
        self._last_state_emit_sig = tuple()

    def _unlock_portrait_if_player_changed(self, side: str, raw_name: str) -> None:
        name = str(raw_name or "").strip()
        if not name:
            return
        if name != self._portrait_lock_name.get(side, ""):
            self._portrait_lock_name[side] = name
            self._portrait_locked[side] = False
            self._image_mtimes.pop(side, None)
            self._last_signature = tuple()

    def _is_match_intro_state(self, raw: str) -> bool:
        s = re.sub(r"[^a-z0-9]+", "", str(raw or "").strip().lower())
        return "matchintro" in s or s in ("matchintro", "intro")

    def _match_pair_key(self, blue_raw: str, red_raw: str) -> Tuple[str, str]:
        return (
            self._normalize_game_id(str(blue_raw or ""), PLAYER_ID_ALLOW_CHARS),
            self._normalize_game_id(str(red_raw or ""), PLAYER_ID_ALLOW_CHARS),
        )

    def _name_payload(self, raw_name: str) -> Tuple[str, str, bool, bool]:
        name = str(raw_name or "").strip()
        gid = self._canonical_player_gid_for_cfg(
            self.cfg,
            self._normalize_game_id(name, PLAYER_ID_ALLOW_CHARS),
            threshold=70,
        )
        registered = bool(gid and gid in (self.cfg.players or {}))
        display = str((self.cfg.players or {}).get(gid) or name or gid)
        return gid, display, registered, bool(gid)

    def _read_realtime_fast_update(self, root: str) -> dict:
        """Read only the broadcast-critical files.

        This method intentionally avoids lobby/scorecard/report/TTS work.  It is
        called before the full watcher pass so hit sparks and punishment gauges
        are emitted as soon as the relevant files change.
        """
        out: Dict[str, Any] = {}
        match_dir = os.path.join(root, "match")
        dmg_path = os.path.join(match_dir, "damage_events.txt")
        try:
            dmg = self._read_damage_update(dmg_path, fast_only=True)
            if dmg:
                out.update(dmg)
        except Exception:
            logging.debug("SPECTATORLOG_FAST_DAMAGE_FAIL", exc_info=True)
        try:
            gauge = self._read_fast_punishment_info(root)
            if gauge:
                out["spectator_log_info"] = gauge
        except Exception:
            logging.debug("SPECTATORLOG_FAST_GAUGE_FAIL", exc_info=True)
        if out:
            out["_spectator_hot_path"] = True
        return out

    def _read_fast_punishment_info(self, root: str) -> dict:
        now = time.time()
        min_interval = 0.075
        try:
            min_interval = max(0.03, min(0.35, float(getattr(self.cfg, "spectator_realtime_gauge_min_interval_ms", 75) or 75) / 1000.0))
        except Exception:
            min_interval = 0.075
        if now - float(self._last_fast_punishment_emit_at or 0.0) < min_interval:
            return {}
        sig_parts = []
        vals: Dict[str, float] = {}
        for side in ("blue", "red"):
            base = os.path.join(root, side)
            for key, fn in (("mid", "punishment_mid.txt"), ("long", "punishment_long_weighted.txt")):
                path = os.path.join(base, fn)
                sig_parts.append((side, key, self._file_sig(path)))
                raw = self._read_text(path)
                if raw != "":
                    vals[f"{side}_{key}"] = self._punishment_percent(raw)
        sig = tuple(sig_parts + [(k, round(float(v), 3)) for k, v in sorted(vals.items())])
        if sig == self._last_fast_punishment_sig:
            return {}
        self._last_fast_punishment_sig = sig
        self._last_fast_punishment_emit_at = now
        info: Dict[str, Any] = {}
        if "blue_mid" in vals:
            info["blue_punishment_mid"] = vals["blue_mid"]
        if "blue_long" in vals:
            info["blue_punishment_long"] = vals["blue_long"]
        if "red_mid" in vals:
            info["red_punishment_mid"] = vals["red_mid"]
        if "red_long" in vals:
            info["red_punishment_long"] = vals["red_long"]
        # Keep stun/down forced gauge boost responsive even when source files lag.
        for side in ("blue", "red"):
            try:
                if now <= float((self._punishment_mid_forced_until or {}).get(side, 0.0) or 0.0):
                    info[f"{side}_punishment_mid"] = 100.0
            except Exception:
                pass
        return info

    def _read_update(self, root: str) -> dict:
        blue_name_raw = self._read_text(os.path.join(root, "blue", "name.txt"))
        red_name_raw = self._read_text(os.path.join(root, "red", "name.txt"))
        round_raw = self._read_text(os.path.join(root, "match", "round_number.txt"))
        round_total_raw = self._read_text(os.path.join(root, "match", "round_total.txt"))
        time_raw = self._read_text(os.path.join(root, "match", "round_time.txt"))
        state_raw = self._read_text(os.path.join(root, "match", "round_state.txt"))
        # camera.txt is frequently rewritten and is not needed for the broadcast hot path.
        camera_raw = ""

        match_dir = os.path.join(root, "match")
        dmg_path = os.path.join(match_dir, "damage_events.txt")
        dmg_sig = self._file_sig(dmg_path)
        scores_path = os.path.join(match_dir, "scores.csv")
        winner_path = os.path.join(match_dir, "winner.txt")
        lobby_path = os.path.join(root, "lobby.txt")
        scores_sig = self._file_sig(scores_path)
        winner_sig = self._file_sig(winner_path)
        lobby_sig = self._file_sig(lobby_path)
        lobby_info = self._read_lobby_info(root) if lobby_sig != (0, 0) else {}
        if lobby_info:
            self._remember_lobby_settings(lobby_info)
        try:
            if dmg_sig != getattr(self, "_diag_last_damage_sig", None):
                self._diag_last_damage_sig = dmg_sig
                DIAG.record("spectator_file_seen", file="damage_events.txt", sig=dmg_sig, round=round_raw, state=state_raw)
        except Exception:
            pass

        state = self._normalize_round_state(state_raw)
        prev_round_state = self._last_round_state
        pair_key = self._match_pair_key(blue_name_raw, red_name_raw)
        pair_ready = bool(pair_key[0] and pair_key[1])
        match_intro_transition = self._is_match_intro_state(state_raw) and prev_round_state != "intro"
        try:
            round_probe = int(float(round_raw)) if round_raw else None
        except Exception:
            round_probe = None
        intro_pair_change = bool(
            self._is_match_intro_state(state_raw)
            and pair_ready
            and pair_key != self._last_match_reset_pair
        )
        fight_after_terminal = bool(
            state == "fight"
            and round_probe == 1
            and prev_round_state in ("results", "end", "knockout", "disqualified", "cancel")
        )
        new_match_boundary = bool(match_intro_transition or intro_pair_change or fight_after_terminal)
        player_payload_due = bool(pair_ready and (new_match_boundary or pair_key != self._last_player_payload_pair))

        out: Dict[str, Any] = {}
        baseline_read = not bool(getattr(self, "_runtime_baseline_ready", False))
        if baseline_read:
            self._runtime_baseline_ready = True
        sync_players = bool(getattr(self.cfg, "spectatorlog_sync_players", True))
        if new_match_boundary:
            self._reset_portrait_locks()
        if sync_players and player_payload_due:
            # Player/portrait files are stable during a bout and portrait.png is
            # reused by filename. Read/update them only at bout start or player pair change.
            self._unlock_portrait_if_player_changed("blue", blue_name_raw)
            self._unlock_portrait_if_player_changed("red", red_name_raw)
            b_img_path = os.path.join(root, "blue", "portrait.png")
            r_img_path = os.path.join(root, "red", "portrait.png")
            b_img_changed, b_img = self._read_image_if_changed("blue", b_img_path)
            r_img_changed, r_img = self._read_image_if_changed("red", r_img_path)
            if blue_name_raw:
                bid, bname, breg, bvalid = self._name_payload(blue_name_raw)
                out.update({
                    "blue_player_id": bid,
                    "blue_name": bname,
                    "blue_player_registered": breg,
                    "blue_player_valid": bvalid,
                })
            if red_name_raw:
                rid, rname, rreg, rvalid = self._name_payload(red_name_raw)
                out.update({
                    "red_player_id": rid,
                    "red_name": rname,
                    "red_player_registered": rreg,
                    "red_player_valid": rvalid,
                })
            if b_img_changed and b_img is not None and not self._portrait_locked.get("blue", False):
                out["blue_player_img"] = b_img
                self._portrait_locked["blue"] = True
            if r_img_changed and r_img is not None and not self._portrait_locked.get("red", False):
                out["red_player_img"] = r_img
                self._portrait_locked["red"] = True
            self._last_player_payload_pair = pair_key

        try:
            round_no = int(float(round_raw)) if round_raw else None
        except Exception:
            round_no = None
        try:
            elapsed = float(time_raw) if time_raw else None
        except Exception:
            elapsed = None
        try:
            round_total_no = int(float(round_total_raw)) if round_total_raw else self._configured_total_rounds()
        except Exception:
            round_total_no = self._configured_total_rounds()
        # Break/result logs can arrive without a fresh round value.  Keep the
        # last fight round as the caster/summary round so rest-time commentary
        # still fires on fight -> break transitions.
        caster_round_no = round_no
        if caster_round_no is None and self._last_fight_round_no is not None:
            caster_round_no = self._last_fight_round_no
        if new_match_boundary:
            # A new bout owns the commentary channel. Stop any post-fight recap
            # from the previous bout before queuing the new VS introduction.
            out["commentary_tts_stop_roles"] = ["caster", "analyst"]
            out["commentary_tts_stop_reason"] = "new_match"
            self._reset_damage_session(dmg_path)
            self._last_fight_round_no = None
            self._last_round_time_value = None
            self._last_round_time_round = None
            self._last_round_time_state = ""
            self._round_time_auto_modes = {}
            self._reset_down_state_machine()
            if pair_ready:
                self._last_match_reset_pair = pair_key
            self._last_active_match_pair = ("", "")
            self._last_vs_intro_pair = ("", "")
            out["spectator_sp_reset"] = True
            out["spectator_match_stats_reset"] = True
        if self._is_match_intro_state(state_raw) and pair_ready and not baseline_read:
            if pair_key != self._last_active_match_pair and pair_key != self._last_vs_intro_pair:
                out["vs_intro_event"] = True
                self._last_vs_intro_pair = pair_key
                self._set_caster_event_once(out, "vs", round_no, "intro", self._build_vs_caster_text())
        elif state in ("fight", "break", "results", "end", "knockout", "disqualified") and pair_ready:
            self._last_active_match_pair = pair_key
        if round_no is not None:
            if state == "fight":
                self._last_fight_round_no = max(1, int(round_no or 1))
                self._ensure_down_round(self._last_fight_round_no)
                if prev_round_state != "fight":
                    self._last_fight_state_started_at = time.time()
                    self._last_idle_commentary_at = 0.0
                    self._witty_duo_round_key = max(1, int(round_no or 1))
                    self._witty_duo_round_count = 0
                    self._witty_duo_recent.clear()
                    if prev_round_state == "break":
                        out["commentary_tts_stop_role"] = "analyst"
                        out["commentary_tts_stop_reason"] = "round_start"
                    elif prev_round_state == "knockdown":
                        # Build the restart line before cancelling the down state;
                        # otherwise a second-down restart loses its danger tone.
                        restart_text = self._down_restart_text()
                        self._cancel_down_commentary(out, "fight_restart")
                        if restart_text:
                            self._set_caster_event_once(out, "down_restart", round_no, state, restart_text)
            caster_round_no = round_no
            if state in ("break", "results", "end", "knockout", "disqualified", "cancel") and self._last_fight_round_no is not None:
                caster_round_no = self._last_fight_round_no
            intro_key = (round_no, state)
            if state == "fight" and prev_round_state != "fight" and intro_key != self._last_round_intro_key and not baseline_read:
                out["round_intro_event"] = {
                    "round": max(1, int(round_no or 1)),
                    "state": state,
                }
                self._last_round_intro_key = intro_key
                self._set_caster_event_once(
                    out,
                    "start",
                    round_no,
                    state,
                    self._round_caster_text("start", round_no, round_total_no),
                )
            if state == "break" and prev_round_state != "break" and not baseline_read:
                self._set_caster_event_once(
                    out,
                    "break",
                    caster_round_no,
                    state,
                    self._round_caster_text("break", caster_round_no, round_total_no),
                )
            if state == "results" and prev_round_state != "results" and not baseline_read:
                self._set_caster_event_once(out, "results", caster_round_no, state, self._round_caster_text("results", caster_round_no))
            if state == "end" and prev_round_state != "end" and not baseline_read:
                out["spectator_match_clear"] = True
                self._set_caster_event_once(out, "end", caster_round_no, state, self._round_caster_text("end", caster_round_no))
            if state == "knockout" and prev_round_state != "knockout" and not baseline_read:
                self._set_caster_event_once(out, "knockout", caster_round_no, state, self._round_caster_text("end", caster_round_no))
            if state == "disqualified" and prev_round_state != "disqualified" and not baseline_read:
                self._set_caster_event_once(out, "disqualified", caster_round_no, state, self._round_caster_text("end", caster_round_no))
            if state == "cancel" and prev_round_state != "cancel" and not baseline_read:
                out["spectator_match_clear"] = True
                self._set_caster_event_once(out, "cancel", caster_round_no, state, self._round_caster_text("cancel", caster_round_no))
            if state:
                self._last_round_state = state
        elif state == "break" and prev_round_state != "break" and not baseline_read:
            # Some SpectatorLog builds clear/omit round.txt during rest.  In that
            # case the old code skipped both the break caster line and the
            # follow-up round summary.  Use the last known fight round instead.
            self._set_caster_event_once(
                out,
                "break",
                caster_round_no,
                state,
                self._round_caster_text("break", caster_round_no, round_total_no),
            )
            self._last_round_state = state
        elif state:
            if state == "fight" and prev_round_state != "fight":
                self._last_fight_state_started_at = time.time()
                self._last_idle_commentary_at = 0.0
                self._ensure_down_round(caster_round_no or self._last_fight_round_no or 1)
                self._witty_duo_round_key = max(1, int(caster_round_no or self._last_fight_round_no or 1))
                self._witty_duo_round_count = 0
                self._witty_duo_recent.clear()
                if prev_round_state == "break":
                    out["commentary_tts_stop_role"] = "analyst"
                    out["commentary_tts_stop_reason"] = "round_start"
                    out["spectator_round_report_hide"] = True
                elif prev_round_state == "knockdown":
                    # Build the restart line before cancelling the down state;
                    # otherwise a second-down restart loses its danger tone.
                    restart_text = self._down_restart_text()
                    self._cancel_down_commentary(out, "fight_restart")
                    if restart_text:
                        self._set_caster_event_once(out, "down_restart", caster_round_no, state, restart_text)
            self._last_round_state = state
        sync_timer = bool(getattr(self.cfg, "spectatorlog_sync_timer", False))
        if sync_timer and round_no is not None:
            out["round_current"] = max(1, round_no)
            out["round_total"] = max(1, int(round_total_no or getattr(self.cfg, "timer_total_rounds", 3) or 3))
        if sync_timer and state:
            self._set_rest_state_for_log(out, state == "break")
        if sync_timer and elapsed is not None:
            # Keep match time and break time separate. Non-fight states often export
            # their own counters, so they must not overwrite the last fight clock.
            seconds_left = None
            if state == "fight" or not state:
                seconds_left, mode_label = self._seconds_left_from_round_time(float(elapsed), state="fight", round_no=round_no)
                self._last_fight_seconds_left = int(seconds_left)
                self._last_synced_seconds_left = int(seconds_left)
                self._break_started_wall = None
                self._break_started_round = None
                self._round_time_mode = mode_label
            elif state == "break":
                seconds_left, mode_label = self._seconds_left_from_round_time(float(elapsed), state="break", round_no=round_no)
                self._last_rest_seconds_left = int(seconds_left)
                self._round_time_mode = mode_label
            elif state in ("results", "end", "knockout", "disqualified"):
                seconds_left = 0
                self._last_synced_seconds_left = 0
                self._round_time_mode = f"{state}_zero"
            elif state == "knockdown":
                # RoundKnockdown exports a down-count style timer. Do not overwrite
                # the match clock with it; expose it separately for the overlay.
                seconds_left = self._last_fight_seconds_left
                if seconds_left is None:
                    seconds_left = self._last_synced_seconds_left
                try:
                    out["spectator_knockdown_count"] = max(0, int(round(float(elapsed))))
                    out["spectator_knockdown_time"] = round(float(elapsed), 2)
                except Exception:
                    pass
                self._round_time_mode = "knockdown_count_hold"
            elif state in ("foul", "cancel", "intro"):
                seconds_left = self._last_fight_seconds_left
                if seconds_left is None:
                    seconds_left = self._last_synced_seconds_left
                self._round_time_mode = f"{state}_hold"
            else:
                seconds_left = self._last_fight_seconds_left
                if seconds_left is None:
                    seconds_left = self._last_synced_seconds_left
                self._round_time_mode = "hold"
            if state == "break":
                self._set_rest_state_for_log(out, True)
            elif state:
                self._set_rest_state_for_log(out, False)
            if seconds_left is not None:
                out["seconds_left"] = int(seconds_left)
            out["spectator_time_mode"] = self._round_time_mode
        elif sync_timer and state == "break":
            seconds_left = self._last_rest_seconds_left
            if seconds_left is None:
                seconds_left = int(getattr(self.cfg, "timer_rest_sec", 60) or 60)
            out["seconds_left"] = int(max(0, seconds_left))
            out["spectator_time_mode"] = "break_rest_default"
        elif sync_timer and state in ("results", "end", "knockout", "disqualified"):
            out["seconds_left"] = 0
            self._last_synced_seconds_left = 0
        elif sync_timer and state in ("knockdown", "foul", "cancel", "intro"):
            seconds_left = self._last_fight_seconds_left
            if seconds_left is None:
                seconds_left = self._last_synced_seconds_left
            if seconds_left is not None:
                out["seconds_left"] = int(max(0, seconds_left))
                out["spectator_time_mode"] = f"{state}_hold_no_time"

        if prev_round_state == "knockdown" and state in ("break", "results", "end", "knockout", "disqualified", "cancel", "intro"):
            self._cancel_down_commentary(out, f"state_{state or 'unknown'}")

        # Stage50: lobby/results sidecar files can change after the round_state transition.
        # Treat their file signatures as independent event sources so late scores/winner
        # writes are not missed by the duplicate-state suppression path.
        result_sidecar_changed = False
        try:
            if lobby_info:
                self._apply_lobby_auto_start_edge(lobby_info, out)
                lobby_key = (lobby_sig, tuple((int((x or {}).get("slot", 0) or 0), str((x or {}).get("name") or ""), bool((x or {}).get("ready", False)), bool((x or {}).get("occupied", False))) for x in list(lobby_info.get("slots") or [])))
                if baseline_read:
                    self._last_lobby_sig = lobby_key
                elif lobby_key != self._last_lobby_sig:
                    # Stage57: keep parsing lobby.txt for future use/settings,
                    # but do not show a match-lobby card on the broadcast overlay.
                    # Post-result spectator-only lobbies were visually noisy.
                    self._last_lobby_sig = lobby_key
                self._last_lobby_exists = True
            elif self._last_lobby_exists:
                # No lobby card is displayed in Stage57, but keep the hide event
                # harmless for old browser pages that may still have one visible.
                out["spectator_lobby_hide"] = True
                self._last_lobby_exists = False
                self._last_lobby_sig = (0, 0)
                self._lobby_ready_latched = False
        except Exception:
            logging.exception("SPECTATORLOG_LOBBY_OVERLAY_FAIL")
        try:
            if scores_sig != (0, 0):
                score_payload = self._build_scorecard_overlay_payload(match_dir, state=state, round_no=round_no)
                score_key = (scores_sig, winner_sig, str(pair_key or ""))
                if baseline_read:
                    self._last_scorecard_overlay_key = score_key
                elif score_payload and score_key != self._last_scorecard_overlay_key:
                    # Stage56: official scorecard is embedded inside the round report
                    # instead of being shown as a separate side card. Keep the key
                    # updated so late scores.csv writes are still tracked.
                    self._last_scorecard_overlay_key = score_key
                    result_sidecar_changed = True
                    if state in ("break", "results", "end"):
                        try:
                            embedded = self._build_round_report_payload(dmg_path, caster_round_no, pair_key)
                            if embedded:
                                out["spectator_round_report"] = embedded
                        except Exception:
                            logging.exception("SPECTATORLOG_SCORECARD_EMBED_REPORT_FAIL")
            if winner_sig != (0, 0):
                winner_payload = self._build_winner_overlay_payload(match_dir)
                winner_key = (winner_sig, scores_sig, str(pair_key or ""))
                if baseline_read:
                    self._last_winner_overlay_key = winner_key
                elif winner_payload and winner_key != self._last_winner_overlay_key:
                    # Stage57: winner/result card is folded into the integrated
                    # match report.  Do not emit a separate winner card.
                    self._last_winner_overlay_key = winner_key
                    result_sidecar_changed = True
                    try:
                        final_report = self._build_round_report_payload(dmg_path, caster_round_no, pair_key)
                        if final_report:
                            final_report["isFinal"] = True
                            final_report["matchResult"] = winner_payload
                            final_report["winner"] = winner_payload.get("winner", "")
                            final_report["winnerName"] = winner_payload.get("winnerName", "")
                            out["spectator_round_report"] = final_report
                    except Exception:
                        logging.exception("SPECTATORLOG_WINNER_EMBED_REPORT_FAIL")
        except Exception:
            logging.exception("SPECTATORLOG_RESULT_OVERLAY_FAIL")

        damage_update = self._read_damage_update(dmg_path)
        if damage_update:
            out.update(damage_update)

        # Suppress pure duplicate state churn from round_time/camera rewrites.
        # Damage/event outputs remain immediate because dmg_sig and damage_update change.
        state_emit_sig = (
            pair_key,
            state,
            int(round_no) if round_no is not None else None,
            int(out.get("seconds_left")) if "seconds_left" in out else None,
            bool(out.get("spectator_rest_mode", False)),
            dmg_sig,
            scores_sig,
            winner_sig,
            lobby_sig,
        )
        state_changed_for_ui = state_emit_sig != self._last_state_emit_sig
        if state_changed_for_ui:
            self._last_state_emit_sig = state_emit_sig
        elif not damage_update and not player_payload_due and "commentary_tts_text" not in out and "round_intro_event" not in out and "vs_intro_event" not in out:
            # Nothing meaningful changed for the overlay/UI.  Still allow a low-rate
            # pass for punishment/HP values so the HUD does not feel stale.
            try:
                if time.time() - float(self._last_log_info_emit_at or 0.0) < 0.12:
                    return {}
            except Exception:
                return {}
        if state == "fight" and "commentary_tts_text" not in out and not baseline_read:
            try:
                idle_text, idle_role = self._build_idle_fight_commentary(dmg_path, elapsed, caster_round_no)
                if idle_text:
                    out["commentary_tts_text"] = idle_text
                    out["commentary_tts_role"] = idle_role or "caster"
                    self._commentary_last_at = time.time()
                    self._last_idle_commentary_at = self._commentary_last_at
                    logging.info("SPECTATORLOG_IDLE_COMMENTARY round=%s role=%s text=%s", caster_round_no, idle_role or "caster", idle_text)
            except Exception:
                logging.exception("SPECTATORLOG_IDLE_COMMENTARY_FAIL")
        if state == "break" and prev_round_state != "break" and not baseline_read:
            try:
                break_seconds_left = None
                try:
                    if self._last_rest_seconds_left is not None:
                        break_seconds_left = float(self._last_rest_seconds_left)
                    elif state == "break":
                        break_seconds_left = float(self._configured_break_duration())
                except Exception:
                    break_seconds_left = None
                summary_text = self._build_round_break_summary(dmg_path, caster_round_no, pair_key, break_seconds_left=break_seconds_left)
                if summary_text:
                    logging.info("SPECTATORLOG_ROUND_SUMMARY round=%s text=%s", caster_round_no, summary_text)
                    out["commentary_tts_round_summary_text"] = summary_text
                    out["commentary_tts_round_summary_role"] = "analyst"
                    out["commentary_tts_round_summary_delay_ms"] = 2400 if "commentary_tts_text" in out else 0
                    if "commentary_tts_text" not in out:
                        self._commentary_last_at = time.time()
            except Exception:
                logging.exception("SPECTATORLOG_ROUND_SUMMARY_FAIL")
        if state == "break" and prev_round_state != "break" and not baseline_read:
            try:
                break_seconds_left = None
                try:
                    if self._last_rest_seconds_left is not None:
                        break_seconds_left = float(self._last_rest_seconds_left)
                    elif "seconds_left" in out:
                        break_seconds_left = float(out.get("seconds_left") or 0)
                    else:
                        break_seconds_left = float(self._configured_break_duration())
                except Exception:
                    break_seconds_left = None
                report_payload = self._build_round_report_payload(dmg_path, caster_round_no, pair_key, break_seconds_left=break_seconds_left)
                if report_payload:
                    out["spectator_round_report"] = report_payload
            except Exception:
                logging.exception("SPECTATORLOG_ROUND_REPORT_FAIL")

        if state in ("results", "end", "knockout", "disqualified") and prev_round_state not in ("results", "end", "knockout", "disqualified") and not baseline_read:
            try:
                final_report = self._build_round_report_payload(dmg_path, caster_round_no, pair_key)
                if final_report:
                    final_report["isFinal"] = True
                    out["spectator_round_report"] = final_report
            except Exception:
                logging.exception("SPECTATORLOG_MATCH_REPORT_FAIL")
            try:
                final_text = self._build_match_final_summary(dmg_path, caster_round_no, pair_key, state)
                if final_text:
                    logging.info("SPECTATORLOG_MATCH_SUMMARY state=%s round=%s text=%s", state, caster_round_no, final_text)
                    if "commentary_tts_text" in out:
                        out["commentary_tts_followup_text"] = final_text
                        out["commentary_tts_followup_role"] = "analyst"
                        out["commentary_tts_followup_delay_ms"] = 3200
                    else:
                        out["commentary_tts_text"] = final_text
                        out["commentary_tts_role"] = "analyst"
                        self._commentary_last_at = time.time()
            except Exception:
                logging.exception("SPECTATORLOG_MATCH_SUMMARY_FAIL")
        elif state in ("results", "end", "knockout", "disqualified") and result_sidecar_changed:
            try:
                final_report = self._build_round_report_payload(dmg_path, caster_round_no, pair_key)
                if final_report:
                    final_report["isFinal"] = True
                    out["spectator_round_report"] = final_report
            except Exception:
                logging.exception("SPECTATORLOG_MATCH_REPORT_LATE_FAIL")
            try:
                final_text = self._build_match_final_summary(dmg_path, caster_round_no, pair_key, state)
                if final_text and "commentary_tts_text" not in out:
                    out["commentary_tts_text"] = final_text
                    out["commentary_tts_role"] = "analyst"
                    self._commentary_last_at = time.time()
            except Exception:
                logging.exception("SPECTATORLOG_MATCH_SUMMARY_LATE_FAIL")
        now_for_info = time.time()
        should_read_log_info = bool(damage_update or state_changed_for_ui or player_payload_due or (now_for_info - float(self._last_log_info_emit_at or 0.0) >= 0.12))
        if should_read_log_info:
            log_info = self._read_log_info(root, state_raw, round_raw, time_raw, camera_raw, damage_update)
            if log_info and isinstance(damage_update.get("combo_info"), dict):
                log_info.update(damage_update.get("combo_info") or {})
            if log_info:
                info_sig = (
                    log_info.get("blue_punishment_mid"),
                    log_info.get("blue_punishment_long"),
                    log_info.get("red_punishment_mid"),
                    log_info.get("red_punishment_long"),
                    log_info.get("blue_recent_hit_text"),
                    log_info.get("red_recent_hit_text"),
                    log_info.get("blue_combo_hit_text"),
                    log_info.get("red_combo_hit_text"),
                    log_info.get("blue_round_knockdowns"),
                    log_info.get("red_round_knockdowns"),
                    str(log_info.get("blue_accessibility") or ""),
                    str(log_info.get("red_accessibility") or ""),
                )
                if info_sig != self._last_log_info_sig or damage_update or state_changed_for_ui:
                    self._last_log_info_sig = info_sig
                    self._last_log_info_emit_at = now_for_info
                    out["spectator_log_info"] = log_info

        try:
            self._attach_witty_duo_followup(out, state=state, round_no=caster_round_no)
        except Exception:
            logging.exception("SPECTATORLOG_WITTY_DUO_ATTACH_FAIL")

        if out and (damage_update or player_payload_due or "spectator_round_report" in out or "round_intro_event" in out or "vs_intro_event" in out):
            logging.info(
                "SPECTATORLOG_APPLY event=%s player_due=%s state=%s seconds_left=%s keys=%s",
                bool(damage_update),
                player_payload_due,
                state,
                out.get("seconds_left", None),
                sorted(out.keys()),
            )
        elif out:
            logging.debug("SPECTATORLOG_APPLY_LIGHT state=%s seconds_left=%s keys=%s", state, out.get("seconds_left", None), sorted(out.keys()))
        return out

    def _reset_damage_session(self, damage_path: Optional[str] = None) -> None:
        self._damage_initialized = False
        self._total_damage_dealt = {"blue": 0.0, "red": 0.0}
        self._damage_total_offset = {"blue": 0.0, "red": 0.0}
        self._damage_file_last_dealt = {"blue": 0.0, "red": 0.0}
        self._last_damage_update_sig = (0, 0)
        self._last_fast_damage_update_sig = (0, 0)
        self._fast_pending_damage_sig = (0, 0)
        self._fast_pending_new_events = []
        self._fast_pending_effect_events = []
        self._seen_damage_event_keys = set()
        self._recent_damage_events.clear()
        self._pose_file_cache = {}
        self._last_round_summary_key = (None, "", "")
        self._last_round_report_key = (None, "", "")
        self._last_match_summary_key = ("", "", "")
        self._scorecard_rounds = {}
        self._scorecard_seen_event_keys = set()
        self._scorecard_last_pair = ("", "")
        self._scorecard_thrown_round_baselines = {}
        self._scorecard_thrown_last_cumulative = {
            "counts": {"blue": 0, "red": 0},
            "breakdown": {"blue": {}, "red": {}},
        }
        try:
            self._commentary_recent_lines.clear()
            self._commentary_category_last_at.clear()
            self._commentary_meaning_last_at.clear()
            self._punishment_history.clear()
            self._last_damage_seen_at = 0.0
            self._last_idle_commentary_at = 0.0
            self._last_fight_state_started_at = 0.0
            self._witty_duo_round_key = None
            self._witty_duo_round_count = 0
            self._witty_duo_recent.clear()
            self._reset_down_state_machine()
        except Exception:
            pass
        self._combo_state = {
            "attacker_side": "",
            "receiver_side": "",
            "last_time": None,
            "count": 0,
            "damage": 0.0,
        }
        self._last_counter_event = None
        self._last_effect_counts = {
            "blue": {"stun": 0, "knockdown": 0, "tko": 0},
            "red": {"stun": 0, "knockdown": 0, "tko": 0},
        }
        self._last_stun_counts = {"blue": 0, "red": 0}
        if damage_path and os.path.exists(damage_path):
            try:
                events, effect_counts = self._scan_damage_file_for_session_reset(damage_path)
                self._seen_damage_event_keys = {self._damage_event_key(ev) for ev in events}
                self._last_effect_counts = effect_counts
                self._last_stun_counts = {
                    side: int(effect_counts.get(side, {}).get("stun", 0) or 0)
                    for side in ("blue", "red")
                }
                current_blue = 0.0
                current_red = 0.0
                for ev in events:
                    try:
                        dmg = float(ev.get("damage", 0.0) or 0.0)
                    except Exception:
                        dmg = 0.0
                    receiver = str(ev.get("receiver_side") or "").lower()
                    if receiver == "red":
                        current_blue += dmg
                    elif receiver == "blue":
                        current_red += dmg
                self._damage_file_last_dealt = {"blue": current_blue, "red": current_red}
                self._damage_total_offset = {"blue": -current_blue, "red": -current_red}
                self._damage_initialized = True
            except Exception:
                pass

    def _parse_damage_event_parts(self, parts: List[str]) -> Optional[dict]:
        """Parse damage_events.txt rows across SpectatorLog builds.

        Supported layouts:
          v3 / 2026-07 observed:
            time, damage, counter_mult, receiver corner, hand,
            screen_x, screen_y, world_x, world_y, world_z,
            punch_type, damage_type, weak_point
          v2:
            time, damage, receiver corner, hand,
            screen_x, screen_y, world_x, world_y, world_z,
            punch_type, damage_type, weak_point
          v1:
            time, damage, receiver corner,
            screen_x, screen_y, world_x, world_y, world_z,
            punch_type, damage_type, weak_point

        The receiver corner is the boxer who received the hit, so attacker-side
        stats are inverted from that value.  The new counter_mult value is kept
        as metadata and never shifts old rows out of alignment.
        """
        try:
            if not isinstance(parts, list) or len(parts) < 10:
                return None
            t = float(parts[0])
            damage = float(parts[1])
        except Exception:
            return None

        counter_mult = 1.0
        receiver_idx = 2
        # New builds insert counter_mult between final_damage and corner.
        # Detect it by type + the next token being the corner label so older
        # files remain valid and malformed rows are ignored safely.
        try:
            maybe_counter = float(parts[2])
            maybe_receiver = str(parts[3] if len(parts) > 3 else "").strip().lower()
            if maybe_receiver in ("blue", "red"):
                counter_mult = maybe_counter
                receiver_idx = 3
        except Exception:
            receiver_idx = 2

        receiver = str(parts[receiver_idx] if len(parts) > receiver_idx else "").strip().lower()
        if receiver == "red":
            attacker = "BLUE"
            attacker_side = "blue"
        elif receiver == "blue":
            attacker = "RED"
            attacker_side = "red"
        else:
            return None

        hand = ""
        hand_idx = receiver_idx + 1
        # v2/v3 add hand immediately after corner. Detect it by value so old
        # files without a hand column remain supported.
        if len(parts) > hand_idx and str(parts[hand_idx] or "").strip().lower() in ("left", "right", "l", "r"):
            hand = "left" if str(parts[hand_idx] or "").strip().lower().startswith("l") else "right"
            screen_x_idx, screen_y_idx = hand_idx + 1, hand_idx + 2
            world_x_idx, world_y_idx, world_z_idx = hand_idx + 3, hand_idx + 4, hand_idx + 5
            punch_idx, damage_type_idx, weak_idx = hand_idx + 6, hand_idx + 7, hand_idx + 8
        else:
            screen_x_idx, screen_y_idx = receiver_idx + 1, receiver_idx + 2
            world_x_idx, world_y_idx, world_z_idx = receiver_idx + 3, receiver_idx + 4, receiver_idx + 5
            punch_idx, damage_type_idx, weak_idx = receiver_idx + 6, receiver_idx + 7, receiver_idx + 8

        def _part_float(idx: int) -> Optional[float]:
            try:
                return float(parts[idx])
            except Exception:
                return None

        return {
            "time": t,
            "attacker": attacker,
            "receiver": receiver.upper(),
            "receiver_side": receiver,
            "attacker_side": attacker_side,
            "damage": damage,
            "counter_mult": counter_mult,
            "is_counter": bool(counter_mult > 1.0001),
            "hand": hand,
            "screen_x": _part_float(screen_x_idx),
            "screen_y": _part_float(screen_y_idx),
            "world_x": _part_float(world_x_idx),
            "world_y": _part_float(world_y_idx),
            "world_z": _part_float(world_z_idx),
            "punch": str(parts[punch_idx] or "").strip() if len(parts) > punch_idx else "",
            "damage_type": str(parts[damage_type_idx] or "").strip() if len(parts) > damage_type_idx else "",
            "weak_point": str(parts[weak_idx] or "").strip() if len(parts) > weak_idx else "",
        }

    def _is_counter_event(self, ev: Any) -> bool:
        try:
            if bool((ev or {}).get("is_counter")):
                return True
            return float((ev or {}).get("counter_mult", 1.0) or 1.0) > 1.0001
        except Exception:
            return False

    def _counter_reason_against_previous(self, ev: dict, prev: Optional[dict]) -> str:
        if not isinstance(ev, dict) or not isinstance(prev, dict):
            return ""
        attacker = str(ev.get("attacker_side") or "").lower()
        receiver = str(ev.get("receiver_side") or "").lower()
        prev_attacker = str(prev.get("attacker_side") or "").lower()
        prev_receiver = str(prev.get("receiver_side") or "").lower()
        if attacker not in ("blue", "red") or receiver not in ("blue", "red"):
            return ""
        if prev_attacker != receiver or prev_receiver != attacker:
            return ""
        try:
            gap = abs(float(ev.get("time", 0.0) or 0.0) - float(prev.get("time", 0.0) or 0.0))
        except Exception:
            return ""
        if gap > COUNTER_WINDOW_SEC:
            return ""
        try:
            dmg = max(0.0, float(ev.get("damage", 0.0) or 0.0))
        except Exception:
            dmg = 0.0
        try:
            prev_dmg = max(0.0, float(prev.get("damage", 0.0) or 0.0))
        except Exception:
            prev_dmg = 0.0
        if prev_dmg <= 0.0 and dmg > 0.0:
            return "whiff"
        if prev_dmg <= COUNTER_PREV_DAMAGE_THRESHOLD and dmg >= COUNTER_DEALT_DAMAGE_THRESHOLD:
            return "light_trade"
        return ""

    def _annotate_counter_events(self, events: List[dict]) -> List[dict]:
        """Mark inferred counters once so live HUD, reports and commentary agree."""
        last_attack_by_side: Dict[str, dict] = {}
        for ev in list(events or []):
            if not isinstance(ev, dict):
                continue
            attacker = str(ev.get("attacker_side") or "").lower()
            receiver = str(ev.get("receiver_side") or "").lower()
            if attacker not in ("blue", "red") or receiver not in ("blue", "red"):
                continue
            reason = "log" if self._is_counter_event(ev) else self._counter_reason_against_previous(ev, last_attack_by_side.get(receiver))
            if reason:
                ev["is_counter"] = True
                ev["counter_reason"] = reason
                if reason != "log":
                    try:
                        ev["counter_mult"] = max(float(ev.get("counter_mult", 1.0) or 1.0), 1.01)
                    except Exception:
                        ev["counter_mult"] = 1.01
            last_attack_by_side[attacker] = ev
        return events

    def _scan_damage_file_for_session_reset(self, path: str) -> Tuple[List[dict], Dict[str, Dict[str, int]]]:
        events: List[dict] = []
        effect_counts = {
            "blue": {"stun": 0, "knockdown": 0, "tko": 0},
            "red": {"stun": 0, "knockdown": 0, "tko": 0},
        }
        try:
            with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            return events, effect_counts
        for line in lines:
            parts = str(line or "").strip().split("\t")
            ev = self._parse_damage_event_parts(parts)
            if not ev:
                continue
            receiver = str(ev.get("receiver_side") or "").lower()
            damage_type = str(ev.get("damage_type") or "")
            events.append(ev)
            kind = self._damage_effect_kind(damage_type)
            if receiver in effect_counts and kind:
                effect_counts[receiver][kind] = int(effect_counts[receiver].get(kind, 0) or 0) + 1
        self._annotate_counter_events(events)
        return events, effect_counts

    def _read_punches_thrown_file(self, path: str) -> List[dict]:
        """Read match/punches_thrown.txt from the new SpectatorLog format."""
        out: List[dict] = []
        try:
            with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            return out
        for line in lines:
            parts = str(line or "").strip().split("\t")
            if len(parts) < 4:
                continue
            try:
                t = float(parts[0])
            except Exception:
                t = 0.0
            side = str(parts[1] or "").strip().lower()
            if side not in ("blue", "red"):
                continue
            hand = str(parts[2] or "").strip().lower()
            if hand.startswith("l"):
                hand = "left"
            elif hand.startswith("r"):
                hand = "right"
            out.append({
                "time": t,
                "side": side,
                "hand": hand,
                "punch": str(parts[3] or "").strip(),
            })
        return out

    def _read_official_scores(self, path: str) -> List[dict]:
        """Read match/scores.csv if the game has written official round scores."""
        rows: List[dict] = []
        try:
            with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            return rows
        header: List[str] = []
        for line in lines:
            raw = str(line or "").strip()
            if not raw:
                continue
            parts = [p.strip() for p in raw.split(",")]
            if raw.lower().startswith("round,"):
                header = [p.strip().lower() for p in parts]
                continue
            if len(parts) < 3:
                continue
            try:
                r = int(float(parts[0]))
                bs = int(float(parts[1]))
                rs = int(float(parts[2]))
            except Exception:
                continue
            winner = "blue" if bs > rs else "red" if rs > bs else "draw"
            row: Dict[str, Any] = {
                "round": r,
                "blue_score": bs,
                "red_score": rs,
                "winner": winner,
                "official": True,
                "raw_columns": len(parts),
            }
            # Newer score files expose cumulative totals, damage taken and KD
            # counts.  Keep these values when present, but never require them so
            # old 3-column scores.csv files remain compatible.
            if len(parts) >= 5:
                try:
                    row["blue_total"] = int(float(parts[3]))
                    row["red_total"] = int(float(parts[4]))
                except Exception:
                    pass
            if len(parts) >= 7:
                try:
                    row["blue_damage_taken"] = float(parts[5])
                    row["red_damage_taken"] = float(parts[6])
                except Exception:
                    pass
            if len(parts) >= 9:
                try:
                    row["blue_kds"] = int(float(parts[7]))
                    row["red_kds"] = int(float(parts[8]))
                except Exception:
                    pass
            if header:
                row["header"] = list(header)
            rows.append(row)
        rows.sort(key=lambda x: int(x.get("round", 0) or 0))
        return rows

    def _filter_completed_score_rows(self, rows: List[dict], *, state: Optional[str] = None, round_no: Optional[int] = None, winner_present: bool = False) -> List[dict]:
        """Hide current-round placeholder score rows from live scorecards.

        Current builds can write a row for the active round with 10-10 and 0.0
        damage before that round is officially complete.  In RoundFight, RoundIntro
        and RoundBreak, round_number points at the active/next round, so only rows
        below that number are official for display.  Once winner/results/end exists,
        keep all rows.
        """
        rows = list(rows or [])
        st = str(state or self._last_round_state or "").lower()
        if winner_present or st in ("results", "end"):
            return rows
        try:
            cur = int(round_no if round_no is not None else (self._last_fight_round_no or self._last_round_time_round or 0))
        except Exception:
            cur = 0
        if st in ("knockout", "disqualified") and cur > 0:
            filtered = []
            for r in rows:
                try:
                    rr = int((r or {}).get("round", 0) or 0)
                    bs = int((r or {}).get("blue_score", 0) or 0)
                    rs = int((r or {}).get("red_score", 0) or 0)
                    bd = float((r or {}).get("blue_damage_taken", 0.0) or 0.0)
                    rd = float((r or {}).get("red_damage_taken", 0.0) or 0.0)
                    bk = int((r or {}).get("blue_kds", 0) or 0)
                    rk = int((r or {}).get("red_kds", 0) or 0)
                    placeholder = rr >= cur and bs == 10 and rs == 10 and bd <= 0.001 and rd <= 0.001 and bk == 0 and rk == 0
                except Exception:
                    placeholder = False
                if not placeholder:
                    filtered.append(r)
            return filtered
        if cur <= 0:
            return rows
        if st in ("fight", "knockdown", "foul"):
            return [r for r in rows if int((r or {}).get("round", 0) or 0) < cur]
        if st in ("break", "intro", "cancel"):
            try:
                last_fight = int(self._last_fight_round_no or 0)
            except Exception:
                last_fight = 0
            max_completed = cur - 1 if last_fight and cur > last_fight else (last_fight or cur)
            return [r for r in rows if int((r or {}).get("round", 0) or 0) <= max_completed]
        return rows

    def _read_winner_result(self, path: str) -> dict:
        """Read match/winner.txt if present."""
        raw = self._read_text(path)
        if not raw:
            return {}
        parts = str(raw or "").strip().split("\t")
        side = str(parts[0] if parts else "").strip().lower()
        if side not in ("blue", "red", "draw"):
            return {}
        return {"side": side, "name": str(parts[1] if len(parts) > 1 else "").strip()}

    def _bool_text(self, value: Any) -> bool:
        return str(value or "").strip().lower() in ("1", "true", "yes", "y", "on")

    def _read_lobby_info(self, root: str) -> dict:
        """Read root/lobby.txt while the game lobby is open."""
        path = os.path.join(root, "lobby.txt")
        raw = self._read_text(path)
        if not raw:
            return {}
        info: Dict[str, Any] = {"exists": True, "slots": []}
        for line in str(raw or "").splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r"slot_(\d+)\s*:\s*(.*)$", line, re.IGNORECASE)
            if m:
                try:
                    slot_no = int(m.group(1))
                except Exception:
                    slot_no = len(info.get("slots") or [])
                body = m.group(2) or ""
                kv: Dict[str, str] = {}
                for km in re.finditer(r"(type|occupied|name|ready)=([^=]*?)(?=\s+(?:type|occupied|name|ready)=|$)", body, re.IGNORECASE):
                    kv[km.group(1).lower()] = str(km.group(2) or "").strip()
                info["slots"].append({
                    "slot": slot_no,
                    "type": kv.get("type", ""),
                    "occupied": self._bool_text(kv.get("occupied", "")),
                    "name": kv.get("name", ""),
                    "ready": self._bool_text(kv.get("ready", "")),
                })
                continue
            m = re.match(r"([A-Za-z_]+)\s*:\s*(.*)$", line)
            if not m:
                continue
            key = m.group(1).strip().lower()
            val = m.group(2).strip()
            if key in ("venue_id", "rounds", "round_duration", "break_duration"):
                try:
                    info[key] = int(float(val))
                except Exception:
                    info[key] = val
            elif key == "ready_to_start":
                info[key] = self._bool_text(val)
            else:
                info[key] = val
        try:
            info["slots"] = sorted(list(info.get("slots") or []), key=lambda x: int((x or {}).get("slot", 0) or 0))
        except Exception:
            pass
        return info

    def _apply_lobby_auto_start_edge(self, lobby_info: dict, out: Dict[str, Any]) -> bool:
        occupied_slots = [
            slot
            for slot in list((lobby_info or {}).get("slots") or [])
            if bool((slot or {}).get("occupied", False))
        ]
        # Slot order is not the fighter order: slot 0 is commonly the host
        # spectator. Use PlayerType and exclude observer slots explicitly.
        spectator_type_tokens = ("spectator", "observer", "camera", "host")
        player_slots = [
            slot for slot in occupied_slots
            if not any(token in str((slot or {}).get("type") or "").strip().lower() for token in spectator_type_tokens)
        ][:2]
        slots_ready = bool(len(player_slots) == 2 and all(bool((slot or {}).get("ready", False)) for slot in player_slots))
        ready_to_start = slots_ready
        ready_signature = tuple(
            (
                int((slot or {}).get("slot", -1)),
                str((slot or {}).get("type") or ""),
                str((slot or {}).get("name") or ""),
                bool((slot or {}).get("ready", False)),
                "fighter" if slot in player_slots else "ignored",
            )
            for slot in occupied_slots
        )
        if ready_signature != getattr(self, "_lobby_ready_log_signature", None):
            self._lobby_ready_log_signature = ready_signature
            logging.info(
                "SPECTATOR_LOBBY_READY_STATE players=%s slots_ready=%s raw_ready_to_start=%s enabled=%s",
                list(ready_signature),
                slots_ready,
                bool((lobby_info or {}).get("ready_to_start", False)),
                bool(getattr(self.cfg, "spectator_lobby_auto_start_enabled", False)),
            )
        if ready_to_start and not self._lobby_ready_latched:
            self._lobby_ready_latched = True
            if bool(getattr(self.cfg, "spectator_lobby_auto_start_enabled", False)):
                out["spectator_lobby_auto_start"] = {
                    "ready_to_start": True,
                    "players": [str((slot or {}).get("name") or "") for slot in player_slots],
                }
                logging.info(
                    "SPECTATOR_LOBBY_AUTO_START_EDGE players=%s",
                    [str((slot or {}).get("name") or "") for slot in player_slots],
                )
                return True
        elif not ready_to_start:
            if self._lobby_ready_latched:
                logging.info("SPECTATOR_LOBBY_AUTO_START_REARM")
            self._lobby_ready_latched = False
        return False

    def _remember_lobby_settings(self, lobby: dict) -> None:
        if not isinstance(lobby, dict) or not lobby:
            return
        for attr, key in (("_last_lobby_rounds", "rounds"), ("_last_lobby_round_duration", "round_duration"), ("_last_lobby_break_duration", "break_duration")):
            try:
                val = int(float(lobby.get(key)))
                if val > 0:
                    setattr(self, attr, val)
            except Exception:
                pass

    def _configured_round_duration(self) -> int:
        try:
            val = int(float(self._last_lobby_round_duration or 0))
            if val > 0:
                return val
        except Exception:
            pass
        try:
            return max(1, int(float(getattr(self.cfg, "timer_round_sec", 180) or 180)))
        except Exception:
            return 180

    def _configured_break_duration(self) -> int:
        try:
            val = int(float(self._last_lobby_break_duration or 0))
            if val > 0:
                return val
        except Exception:
            pass
        try:
            return max(1, int(float(getattr(self.cfg, "timer_rest_sec", 60) or 60)))
        except Exception:
            return 60

    def _infer_round_time_mode(self, value: float, *, state: str, round_no: Optional[int], duration: int) -> str:
        """Infer whether match/round_time.txt is remaining seconds or elapsed.

        Older public docs described this file as elapsed seconds, but the
        blackbox trace from the current spectator build showed countdown values
        (179.xx -> 0.xx in fight, 54.xx -> 0.xx in break).  Use value movement
        when available and default to remaining when uncertain so the live HUD
        follows the observed build instead of jumping to the opposite side of
        the round.
        """
        key = str(state or "fight").lower() or "fight"
        last_mode = str((self._round_time_auto_modes or {}).get(key) or "").lower()
        prev_value = self._last_round_time_value
        prev_round = self._last_round_time_round
        prev_state = self._last_round_time_state
        mode = ""
        try:
            same_stream = (
                prev_value is not None
                and str(prev_state or "") == key
                and (round_no is None or prev_round is None or int(prev_round) == int(round_no))
            )
        except Exception:
            same_stream = False
        if same_stream:
            try:
                delta = float(value) - float(prev_value)
                if delta <= -0.05:
                    mode = "remaining"
                elif delta >= 0.05:
                    mode = "elapsed"
            except Exception:
                mode = ""
        if not mode:
            # Strong start-of-round signals.  Late app start can see low
            # remaining values, so avoid treating a small first value as elapsed
            # unless the previous stream already proved it.
            try:
                if float(value) >= max(8.0, float(duration) * 0.55):
                    mode = "remaining"
            except Exception:
                pass
        if not mode and last_mode in ("remaining", "elapsed"):
            mode = last_mode
        if not mode:
            mode = "remaining"
        self._round_time_auto_modes[key] = mode
        return mode

    def _seconds_left_from_round_time(self, value: float, *, state: str, round_no: Optional[int]) -> Tuple[int, str]:
        state_key = str(state or "fight").lower()
        duration = self._configured_break_duration() if state_key == "break" else self._configured_round_duration()
        mode = self._infer_round_time_mode(float(value), state=state_key, round_no=round_no, duration=duration)
        if mode == "elapsed":
            seconds_left = float(duration) - float(value)
        else:
            seconds_left = float(value)
        seconds_left = int(max(0.0, min(float(duration), seconds_left)))
        self._last_round_time_value = float(value)
        self._last_round_time_round = round_no
        self._last_round_time_state = state_key
        return seconds_left, f"{state_key}_auto_{mode}"

    def _configured_total_rounds(self) -> int:
        try:
            val = int(float(self._last_lobby_rounds or 0))
            if val > 0:
                return val
        except Exception:
            pass
        try:
            return max(1, int(float(getattr(self.cfg, "timer_total_rounds", 3) or 3)))
        except Exception:
            return 3

    def _build_lobby_overlay_payload(self, lobby: dict) -> dict:
        if not isinstance(lobby, dict) or not lobby:
            return {}
        slots = []
        for slot in list(lobby.get("slots") or [])[:8]:
            slot = dict(slot or {})
            slots.append({
                "slot": int(slot.get("slot", 0) or 0),
                "type": str(slot.get("type") or ""),
                "occupied": bool(slot.get("occupied", False)),
                "name": str(slot.get("name") or ""),
                "ready": bool(slot.get("ready", False)),
            })
        return {
            "title": "MATCH LOBBY",
            "slots": slots,
            "venueId": lobby.get("venue_id", ""),
            "rounds": lobby.get("rounds", self._configured_total_rounds()),
            "roundDuration": lobby.get("round_duration", self._configured_round_duration()),
            "breakDuration": lobby.get("break_duration", self._configured_break_duration()),
            "readyToStart": bool(lobby.get("ready_to_start", False)),
            "displayMs": 600000,
        }

    def _build_scorecard_overlay_payload(self, match_dir: str, *, state: Optional[str] = None, round_no: Optional[int] = None) -> dict:
        rows = self._read_official_scores(os.path.join(match_dir, "scores.csv"))
        winner_file = self._read_winner_result(os.path.join(match_dir, "winner.txt"))
        rows = self._filter_completed_score_rows(rows, state=state, round_no=round_no, winner_present=bool(winner_file))
        if not rows:
            return {}
        # Prefer official cumulative totals when the new 9-column file provides
        # them; fall back to summing 10-point round scores for old builds.
        last = dict(rows[-1] or {})
        try:
            blue_total = int(last.get("blue_total"))
            red_total = int(last.get("red_total"))
        except Exception:
            blue_total = sum(int((r or {}).get("blue_score", 0) or 0) for r in rows)
            red_total = sum(int((r or {}).get("red_score", 0) or 0) for r in rows)
        winner = str((winner_file or {}).get("side") or "").lower().strip()
        if winner not in ("blue", "red", "draw"):
            winner = "blue" if blue_total > red_total else "red" if red_total > blue_total else "draw"
        return {
            "title": "OFFICIAL SCORECARD",
            "rounds": rows,
            "blueName": self._display_name_for_report("blue"),
            "redName": self._display_name_for_report("red"),
            "blueTotal": blue_total,
            "redTotal": red_total,
            "winner": winner,
            "winnerName": self._display_name_for_report(winner) if winner in ("blue", "red") else str((winner_file or {}).get("name") or ""),
            "displayMs": 18000,
        }

    def _build_winner_overlay_payload(self, match_dir: str) -> dict:
        res = self._read_winner_result(os.path.join(match_dir, "winner.txt"))
        if not res:
            return {}
        side = str(res.get("side") or "").lower().strip()
        if side not in ("blue", "red", "draw"):
            return {}
        name = str(res.get("name") or "").strip()
        if side in ("blue", "red"):
            # winner.txt stores the raw display name; show the registered nickname
            # on broadcast cards when available.
            name = self._display_name_for_report(side)
        return {
            "title": "MATCH RESULT",
            "winner": side,
            "winnerName": name,
            "blueName": self._display_name_for_report("blue"),
            "redName": self._display_name_for_report("red"),
            "displayMs": 22000,
        }

    def _normalize_round_state(self, raw: str) -> str:
        s = re.sub(r"[^a-z0-9]+", "", str(raw or "").strip().lower())
        if not s:
            return ""
        if "matchintro" in s or s.endswith("intro") or s == "intro":
            return "intro"
        if "roundfight" in s or s == "fight":
            return "fight"
        if "roundknockout" in s or ("knockout" in s and "technical" not in s):
            return "knockout"
        if "rounddisqualified" in s or "disqualified" in s:
            return "disqualified"
        if "roundknockdown" in s or "knockdown" in s:
            return "knockdown"
        if "roundfoul" in s or "foul" in s:
            return "foul"
        if "roundbreak" in s or s == "break":
            return "break"
        if "roundresults" in s or "results" in s:
            return "results"
        if "roundcancel" in s or "cancel" in s:
            return "cancel"
        if "roundend" in s or s in ("end", "ended", "complete", "completed", "finished"):
            return "end"
        return s

    def _set_rest_state_for_log(self, out: Dict[str, Any], is_rest: bool) -> None:
        out["spectator_rest_mode"] = bool(is_rest)

    def _file_sig(self, path: str) -> Tuple[int, int]:
        try:
            st = os.stat(path)
            return int(st.st_mtime_ns), int(st.st_size)
        except Exception:
            return 0, 0

    def _damage_effect_kind(self, damage_type: str) -> str:
        dt = re.sub(r"[^a-z0-9]+", "", str(damage_type or "").lower())
        if not dt:
            return ""
        if "technicalknockout" in dt or dt == "tko" or ("technical" in dt and "knockout" in dt):
            return "tko"
        if "knockdown" in dt or "knockout" in dt:
            return "knockdown"
        if "stun" in dt:
            return "stun"
        return ""

    def _side_raw_name(self, side: str) -> str:
        side = str(side or "").lower()
        return self._read_text(os.path.join(self._resolve_spectatorlog_path(str(getattr(self.cfg, "spectatorlog_path", "") or "")), side, "name.txt"))

    def _registered_player_nick(self, raw: str) -> str:
        try:
            allow = PLAYER_ID_ALLOW_CHARS
            norm = self._normalize_game_id(raw, allow)
            gid = self._canonical_player_gid_for_cfg(self.cfg, norm, threshold=70)
            players = getattr(self.cfg, "players", {}) or {}
            if gid and hasattr(players, "get") and str(players.get(gid) or "").strip():
                return str(players.get(gid) or "").strip()

            # SpectatorLog names can include prefixes, suffixes, or noisy digits.
            # such as Ryan_Garc1a.  When an exact fuzzy match misses, allow a
            # conservative substring match against registered IDs so report cards
            # still show the user's Korean nickname.
            def _key(v: str) -> str:
                k = re.sub(r"[^A-Z0-9]", "", str(v or "").upper())
                return k.replace("0", "O").replace("1", "I").replace("5", "S")
            nk = _key(norm or raw)
            if nk and hasattr(players, "items"):
                for ex_gid, nick in players.items():
                    ek = _key(str(ex_gid or ""))
                    if len(ek) >= 4 and (ek in nk or nk in ek):
                        text = str(nick or "").strip()
                        if text:
                            return text
        except Exception:
            return ""
        return ""

    def _short_spoken_id(self, raw: str, fallback: str) -> str:
        token = re.split(r"[\s\.,_#@\-]+", str(raw or "").strip(), maxsplit=1)[0].strip()
        token = re.sub(r"[^0-9A-Za-z가-힣]+", "", token).strip()
        if not token:
            return fallback
        if re.search(r"[가-힣]", token):
            return token[:5] if len(token) > 5 else token
        key = token.lower()
        key_no_tail_digits = re.sub(r"\d+$", "", key)
        # Korean Edge TTS spells many all-caps IDs letter by letter. Prefer short Korean call names.
        aliases = {
            "prairiedog": "프레리독",
            "glassbones": "글래스본즈",
            "koreatong": "코리아통",
            "kindblue": "카인드블루",
            "mangoring": "망고링",
            "phydon": "파이돈",
            "konata": "코나타",
            "bones": "본즈",
            "hio98": "에이치아이오",
            "hi098": "에이치아이오",
            "daniel": "다니엘",
            "daniel7": "다니엘",
            "hisanaga": "히사나가",
            "nery": "네리",
            "nery0605": "네리",
            "doraym": "드라이무",
            "monsan": "몬산",
            "kot99k": "케이오티",
            "glassbones100": "글래스본즈",
            "findyourwayhome": "파인드",
            "lmlmlmmm": "엘엠",
            "ynhxu1": "와이엔",
            "jiunmini": "지운미니",
            "29name": "투나인",
        }
        if key in aliases:
            return aliases[key]
        if key_no_tail_digits and key_no_tail_digits in aliases:
            return aliases[key_no_tail_digits]
        alpha = re.sub(r"[^a-z]", "", key)
        if len(alpha) >= 4:
            # Last fallback: keep it short so TTS does not read a whole long ID.
            return alpha[:4]
        return fallback

    def _commentary_name(self, side: str) -> str:
        side = str(side or "").lower()
        raw = self._side_raw_name(side)
        nick = self._registered_player_nick(raw)
        if nick:
            return nick
        return self._short_spoken_id(raw, "블루 선수" if side == "blue" else "레드 선수")

    def _caster_name(self, side: str) -> str:
        side = str(side or "").lower()
        raw = self._side_raw_name(side)
        nick = self._registered_player_nick(raw)
        if nick:
            return nick
        return self._short_spoken_id(raw, "블루" if side == "blue" else "레드")

    def _build_vs_caster_text(self) -> str:
        blue = self._caster_name("blue")
        red = self._caster_name("red")
        if blue and red:
            return f"{blue} 대 {red} 경기, 곧 시작합니다"
        return "곧 경기가 시작합니다"

    def _round_caster_text(self, event: str, round_no: Optional[int], total_rounds: Optional[int] = None) -> str:
        try:
            r = max(1, int(round_no or 1))
        except Exception:
            r = 1
        try:
            total = max(1, int(total_rounds or getattr(self.cfg, "timer_total_rounds", 3) or 3))
        except Exception:
            total = 3
        if event == "start":
            if r >= total:
                return f"마지막 라운드, {r}라운드 시작합니다"
            return f"{r}라운드 시작합니다"
        if event == "break":
            if r >= total:
                return f"마지막 라운드 종료, 경기 결과를 기다립니다"
            return f"{r}라운드 종료, 휴식 시간입니다"
        if event == "results":
            if r >= total:
                return "마지막 라운드 종료, 경기 결과를 확인합니다"
            return "경기 종료, 결과를 확인합니다"
        if event == "end":
            if r >= total:
                return "마지막 라운드 종료, 경기 종료입니다"
            return "경기 종료입니다"
        if event == "cancel":
            return "경기가 중단됩니다"
        return ""

    def _set_caster_event_once(self, out: dict, event: str, round_no: Optional[int], state: str, text: str) -> None:
        text = str(text or "").strip()
        if not text or not bool(getattr(self.cfg, "spectator_commentary_enabled", False)):
            return
        key = (str(event or ""), int(round_no) if round_no is not None else None, str(state or ""))
        if key == self._last_caster_event_key:
            return
        self._last_caster_event_key = key
        out["commentary_tts_text"] = text
        out["commentary_tts_role"] = "caster"
        if str(event or "").lower() == "vs":
            out["commentary_tts_rate"] = 200
            out["commentary_tts_pitch"] = 0

    def _weak_point_ko(self, weak: str) -> str:
        key = re.sub(r"[^a-z0-9]+", "", str(weak or "").lower())
        table = {
            "chin": "턱",
            "nose": "코",
            "temple": "관자놀이",
            "templeleft": "왼쪽 관자놀이",
            "templeright": "오른쪽 관자놀이",
            "liver": "간",
            "solarplexus": "명치",
        }
        return table.get(key, "")

    def _punch_ko(self, punch: str) -> str:
        key = re.sub(r"[^a-z0-9]+", "", str(punch or "").lower())
        table = {
            "jab": "잽",
            "widejab": "와이드 잽",
            "cross": "스트레이트",
            "widecross": "와이드 스트레이트",
            "leadcross": "앞손 스트레이트",
            "rearcross": "뒷손 스트레이트",
            "hook": "훅",
            "leadhook": "앞손 훅",
            "rearhook": "뒷손 훅",
            "widehook": "와이드 훅",
            "uppercut": "어퍼컷",
            "leaduppercut": "앞손 어퍼컷",
            "rearuppercut": "뒷손 어퍼컷",
            "overhand": "오버핸드",
            "leadoverhand": "앞손 오버핸드",
            "rearoverhand": "뒷손 오버핸드",
            "bodyjab": "바디 잽",
            "bodycross": "바디 스트레이트",
            "bodyhook": "바디 훅",
            "bodyuppercut": "바디 어퍼컷",
        }
        if key in table:
            return table[key]
        spaced = re.sub(r"(?<!^)([A-Z])", r" \1", str(punch or "").strip()).strip()
        return spaced or ""

    def _punch_report_group(self, punch: str) -> Tuple[str, str]:
        """Return a compact punch bucket for broadcast round reports."""
        key = re.sub(r"[^a-z0-9]+", "", str(punch or "").lower())
        if not key:
            return "other", "기타"
        if "jab" in key:
            return "jab", "잽"
        if "cross" in key or "straight" in key:
            return "cross", "스트레이트"
        if "hook" in key:
            return "hook", "훅"
        if "upper" in key:
            return "upper", "어퍼"
        if "over" in key:
            return "over", "오버핸드"
        return "other", "기타"

    def _display_name_for_report(self, side: str) -> str:
        """Return the broadcast-facing name for visual reports.

        SpectatorLog name.txt usually contains the raw game ID.  For round
        reports and official scorecards, prefer the user's registered nickname
        from profile/config so Korean names appear on broadcast cards.
        """
        side = str(side or "").lower()
        raw = self._side_raw_name(side)
        nick = self._registered_player_nick(raw)
        if nick:
            return nick
        text = str(raw or "").strip()
        return text or ("블루" if side == "blue" else "레드")

    def _round_report_top_items(self, items: Dict[str, Dict[str, Any]], *, limit: int = 3) -> List[dict]:
        out: List[dict] = []
        for key, item in (items or {}).items():
            try:
                count = int(item.get("count", 0) or 0)
            except Exception:
                count = 0
            try:
                damage = float(item.get("damage", 0.0) or 0.0)
            except Exception:
                damage = 0.0
            label = str(item.get("label") or key or "").strip()
            if not label or count <= 0:
                continue
            safe_label = label if label and "?" not in str(label) else str(key or "").upper()
            out.append({"key": str(key), "label": safe_label, "count": count, "damage": round(damage, 1)})
        out.sort(key=lambda x: (float(x.get("damage", 0.0) or 0.0), int(x.get("count", 0) or 0)), reverse=True)
        return out[:max(1, int(limit or 3))]

    def _build_round_report_payload(self, damage_path: str, round_no: Optional[int], pair_key: Tuple[str, str], break_seconds_left: Optional[float] = None) -> dict:
        """Build a compact visual break-time report from damage_events.txt.

        damage_events.txt rows are landed hits.  The corner column is the boxer
        who received the hit, so attacker-side stats must be inverted from it.
        """
        events, _effect_counts = self._scan_damage_file_for_session_reset(damage_path)
        punches_path = os.path.join(os.path.dirname(damage_path), "punches_thrown.txt")
        thrown_events = self._read_punches_thrown_file(punches_path)
        try:
            punishment_snapshot = self._punishment_snapshot(damage_path)
        except Exception:
            punishment_snapshot = {"blue": {}, "red": {}}
        if not events and not thrown_events:
            return {}
        try:
            r = int(round_no or self._last_fight_round_no or 0)
        except Exception:
            r = 0
        if r > 0 and thrown_events:
            self._record_scorecard_thrown_snapshot(r, thrown_events, events)
        sig = self._file_sig(damage_path)
        punch_sig = self._file_sig(punches_path)
        score_sig = self._file_sig(os.path.join(os.path.dirname(damage_path), "scores.csv"))
        winner_sig = self._file_sig(os.path.join(os.path.dirname(damage_path), "winner.txt"))
        report_key = (
            r,
            str(pair_key or ""),
            f"{sig[0]}:{sig[1]}",
            f"{punch_sig[0]}:{punch_sig[1]}",
            f"{score_sig[0]}:{score_sig[1]}",
            f"{winner_sig[0]}:{winner_sig[1]}",
        )
        if report_key == self._last_round_report_key:
            return {}
        self._last_round_report_key = report_key

        sides = ("blue", "red")
        stats: Dict[str, Dict[str, Any]] = {}
        for side in sides:
            stats[side] = {
                "name": self._display_name_for_report(side),
                "landed": 0,
                "damage": 0.0,
                "big_hits": 0,
                "counter_hits": 0,
                "knockdowns_for": 0,
                "tkos_for": 0,
                "stuns_for": 0,
                "punches": {},
                "max_punch": {},
                "thrown": 0,
                "thrown_punches": {},
                "weak_received": {},
                "received_hits": [],
            }

        # Reclassify landed attempts by matching throw time/side/hand to the
        # impact event. Some game builds write a generic/stale punch type in
        # punches_thrown.txt (for example every red throw as LeadHook).
        matched_punch_by_throw: Dict[int, str] = {}
        unmatched_throw_indexes = set(range(len(thrown_events)))
        for ev in list(events or []):
            if str((ev or {}).get("punch") or "").strip().lower() in ("pull", "other"):
                continue
            attacker = str((ev or {}).get("attacker_side") or "").lower()
            hand = str((ev or {}).get("hand") or "").lower()
            try:
                event_time = float((ev or {}).get("time", 0.0) or 0.0)
            except Exception:
                continue
            candidates = []
            for index in unmatched_throw_indexes:
                thrown = thrown_events[index] or {}
                if str(thrown.get("side") or "").lower() != attacker:
                    continue
                if hand and str(thrown.get("hand") or "").lower() != hand:
                    continue
                delta = abs(float(thrown.get("time", 0.0) or 0.0) - event_time)
                if delta <= 0.85:
                    candidates.append((delta, index))
            if candidates:
                _delta, index = min(candidates)
                unmatched_throw_indexes.discard(index)
                matched_punch_by_throw[index] = str((ev or {}).get("punch") or "")

        for thrown_index, thrown in enumerate(thrown_events):
            side = str((thrown or {}).get("side") or "").lower()
            if side not in sides:
                continue
            st = stats[side]
            st["thrown"] = int(st.get("thrown", 0) or 0) + 1
            classified_punch = matched_punch_by_throw.get(thrown_index) or str((thrown or {}).get("punch") or "")
            pkey, plabel = self._punch_report_group(classified_punch)
            pitem = st["thrown_punches"].setdefault(pkey, {"label": plabel, "count": 0, "damage": 0.0})
            pitem["count"] = int(pitem.get("count", 0) or 0) + 1

        def _num_or_none(value: Any) -> Optional[float]:
            try:
                if value is None or value == "":
                    return None
                return float(value)
            except Exception:
                return None

        best_event: Optional[dict] = None
        tko_events: List[dict] = []
        knockdown_events: List[dict] = []
        stun_events: List[dict] = []

        for ev in list(events or []):
            attacker = str((ev or {}).get("attacker_side") or "").lower()
            receiver = str((ev or {}).get("receiver_side") or "").lower()
            if attacker not in sides or receiver not in sides:
                continue
            # Pull is a movement/feint event, not a landed punch.
            if str((ev or {}).get("punch") or "").strip().lower() in ("pull", "other"):
                continue
            try:
                dmg = max(0.0, float((ev or {}).get("damage", 0.0) or 0.0))
            except Exception:
                dmg = 0.0

            if best_event is None or dmg > float((best_event or {}).get("damage", 0.0) or 0.0):
                best_event = dict(ev or {})

            ast = stats[attacker]
            ast["landed"] = int(ast.get("landed", 0) or 0) + 1
            ast["damage"] = float(ast.get("damage", 0.0) or 0.0) + dmg
            try:
                cm = float((ev or {}).get("counter_mult", 1.0) or 1.0)
            except Exception:
                cm = 1.0
            if self._is_counter_event(ev):
                ast["counter_hits"] = int(ast.get("counter_hits", 0) or 0) + 1
            if dmg >= 45.0:
                ast["big_hits"] = int(ast.get("big_hits", 0) or 0) + 1
            pkey, plabel = self._punch_report_group(str((ev or {}).get("punch") or ""))
            pitem = ast["punches"].setdefault(pkey, {"label": plabel, "count": 0, "damage": 0.0})
            pitem["count"] = int(pitem.get("count", 0) or 0) + 1
            pitem["damage"] = float(pitem.get("damage", 0.0) or 0.0) + dmg
            if dmg > float((ast.get("max_punch") or {}).get("damage", 0.0) or 0.0):
                ast["max_punch"] = {"key": pkey, "label": plabel, "damage": dmg}

            kind = self._damage_effect_kind(str((ev or {}).get("damage_type") or ""))
            if kind == "tko":
                ast["tkos_for"] = int(ast.get("tkos_for", 0) or 0) + 1
                tko_events.append(dict(ev or {}))
            elif kind == "knockdown":
                ast["knockdowns_for"] = int(ast.get("knockdowns_for", 0) or 0) + 1
                knockdown_events.append(dict(ev or {}))
            elif kind == "stun":
                ast["stuns_for"] = int(ast.get("stuns_for", 0) or 0) + 1
                stun_events.append(dict(ev or {}))

            weak = self._weak_point_ko(str((ev or {}).get("weak_point") or ""))
            if weak:
                ritem = stats[receiver]["weak_received"].setdefault(weak, {"label": weak, "count": 0, "damage": 0.0})
                ritem["count"] = int(ritem.get("count", 0) or 0) + 1
                ritem["damage"] = float(ritem.get("damage", 0.0) or 0.0) + dmg

            punch_label = self._punch_ko(str((ev or {}).get("punch") or "").strip())
            if not punch_label:
                _tmp_key, punch_label = self._punch_report_group(str((ev or {}).get("punch") or ""))
            hit_item = {
                "time": round(float((ev or {}).get("time", 0.0) or 0.0), 2),
                "damage": round(dmg, 2),
                "screenX": _num_or_none((ev or {}).get("screen_x")),
                "screenY": _num_or_none((ev or {}).get("screen_y")),
                "worldX": _num_or_none((ev or {}).get("world_x")),
                "worldY": _num_or_none((ev or {}).get("world_y")),
                "worldZ": _num_or_none((ev or {}).get("world_z")),
                "weak": weak,
                "punch": punch_label or "유효타",
                "effect": kind or "hit",
                "counterMult": round(cm, 3),
                "counter": self._is_counter_event(ev),
            }
            stats[receiver]["received_hits"].append(hit_item)

        # Once a round is complete, scores.csv is authoritative for damage and
        # knockdowns. Event rows can differ slightly because the game applies
        # internal scoring adjustments not exposed in damage_events.txt.
        try:
            official_rows = self._filter_completed_score_rows(
                self._read_official_scores(os.path.join(os.path.dirname(damage_path), "scores.csv")),
                state=self._last_round_state,
                round_no=r,
                winner_present=bool(self._read_winner_result(os.path.join(os.path.dirname(damage_path), "winner.txt"))),
            )
            official_row = next((row for row in official_rows if int(row.get("round", 0) or 0) == r), None)
            if official_row:
                stats["blue"]["damage"] = float(official_row.get("red_damage_taken", stats["blue"].get("damage", 0.0)) or 0.0)
                stats["red"]["damage"] = float(official_row.get("blue_damage_taken", stats["red"].get("damage", 0.0)) or 0.0)
                stats["blue"]["knockdowns_for"] = int(official_row.get("red_kds", stats["blue"].get("knockdowns_for", 0)) or 0)
                stats["red"]["knockdowns_for"] = int(official_row.get("blue_kds", stats["red"].get("knockdowns_for", 0)) or 0)
        except Exception:
            logging.exception("SPECTATORLOG_ROUND_REPORT_OFFICIAL_OVERRIDE_FAIL round=%s", r)

        # During a break the source files can already contain earlier rounds.
        # The live scorecard is tagged at ingestion time, so prefer its current
        # round slice instead of rescanning the cumulative files for the HUD.
        if r > 0:
            self._apply_scorecard_round_to_report_stats(stats, r)

        blue_damage = float(stats["blue"].get("damage", 0.0) or 0.0)
        red_damage = float(stats["red"].get("damage", 0.0) or 0.0)
        blue_landed = int(stats["blue"].get("landed", 0) or 0)
        red_landed = int(stats["red"].get("landed", 0) or 0)
        damage_gap = abs(blue_damage - red_damage)
        landed_gap = abs(blue_landed - red_landed)
        blue_kd = int(stats["blue"].get("knockdowns_for", 0) or 0)
        red_kd = int(stats["red"].get("knockdowns_for", 0) or 0)
        blue_tko = int(stats["blue"].get("tkos_for", 0) or 0)
        red_tko = int(stats["red"].get("tkos_for", 0) or 0)
        blue_stun = int(stats["blue"].get("stuns_for", 0) or 0)
        red_stun = int(stats["red"].get("stuns_for", 0) or 0)
        blue_big = int(stats["blue"].get("big_hits", 0) or 0)
        red_big = int(stats["red"].get("big_hits", 0) or 0)
        blue_counter = int(stats["blue"].get("counter_hits", 0) or 0)
        red_counter = int(stats["red"].get("counter_hits", 0) or 0)

        blue_thrown = int(stats["blue"].get("thrown", 0) or 0)
        red_thrown = int(stats["red"].get("thrown", 0) or 0)
        thrown_gap = abs(blue_thrown - red_thrown)
        # Broadcast report priority: stoppage/TKO > knockdown > damage > landed > stun/big hit > activity.
        if blue_tko != red_tko:
            leader = "blue" if blue_tko > red_tko else "red"
        elif blue_kd != red_kd:
            leader = "blue" if blue_kd > red_kd else "red"
        elif (blue_landed + red_landed) == 0 and (blue_thrown + red_thrown) > 0:
            leader = ("blue" if blue_thrown > red_thrown else "red") if thrown_gap >= 4 else "draw"
        elif damage_gap < 15.0 and landed_gap < 3 and blue_stun == red_stun and blue_big == red_big:
            leader = "draw"
        elif blue_damage != red_damage:
            leader = "blue" if blue_damage > red_damage else "red"
        elif blue_landed != red_landed:
            leader = "blue" if blue_landed > red_landed else "red"
        elif blue_stun != red_stun:
            leader = "blue" if blue_stun > red_stun else "red"
        elif blue_big != red_big:
            leader = "blue" if blue_big > red_big else "red"
        elif blue_thrown != red_thrown and thrown_gap >= 4:
            leader = "blue" if blue_thrown > red_thrown else "red"
        else:
            leader = "draw"
        leader_name = "DRAW" if leader == "draw" else str(stats[leader].get("name") or ("BLUE" if leader == "blue" else "RED"))

        def _event_report_payload(ev: Optional[dict], *, fallback_kind: str = "") -> dict:
            if not isinstance(ev, dict) or not ev:
                return {}
            attacker = str(ev.get("attacker_side") or "").lower()
            receiver = str(ev.get("receiver_side") or "").lower()
            if attacker not in sides or receiver not in sides:
                return {}
            try:
                dmg = max(0.0, float(ev.get("damage", 0.0) or 0.0))
            except Exception:
                dmg = 0.0
            punch = self._punch_ko(str(ev.get("punch") or "").strip())
            if not punch:
                _pkey, punch = self._punch_report_group(str(ev.get("punch") or ""))
            weak = self._weak_point_ko(str(ev.get("weak_point") or ""))
            kind = str(fallback_kind or self._damage_effect_kind(str(ev.get("damage_type") or "")) or "hit").lower()
            try:
                hit_time = round(float(ev.get("time", 0.0) or 0.0), 1)
            except Exception:
                hit_time = 0.0
            return {
                "attacker": attacker,
                "receiver": receiver,
                "attackerName": str(stats[attacker].get("name") or ("BLUE" if attacker == "blue" else "RED")),
                "receiverName": str(stats[receiver].get("name") or ("BLUE" if receiver == "blue" else "RED")),
                "damage": int(round(dmg)),
                "punch": punch or "유효타",
                "weak": weak,
                "effect": kind,
                "time": hit_time,
            }

        def _event_sort_key(ev: dict) -> Tuple[float, float]:
            try:
                dmg = float((ev or {}).get("damage", 0.0) or 0.0)
            except Exception:
                dmg = 0.0
            try:
                hit_time = float((ev or {}).get("time", 0.0) or 0.0)
            except Exception:
                hit_time = 0.0
            return dmg, hit_time

        decisive_raw: Optional[dict] = None
        decisive_kind = ""
        if tko_events:
            decisive_raw = max(tko_events, key=_event_sort_key)
            decisive_kind = "tko"
        elif knockdown_events:
            decisive_raw = max(knockdown_events, key=_event_sort_key)
            decisive_kind = "knockdown"
        elif stun_events:
            decisive_raw = max(stun_events, key=_event_sort_key)
            decisive_kind = "stun"
        elif best_event is not None and float((best_event or {}).get("damage", 0.0) or 0.0) >= 45.0:
            decisive_raw = best_event
            decisive_kind = "bigshot"

        best_shot = _event_report_payload(best_event, fallback_kind="")
        decisive_moment = _event_report_payload(decisive_raw, fallback_kind=decisive_kind)

        def _weak_focus_counts() -> Tuple[int, int]:
            body = 0
            head = 0
            for side in sides:
                for item in (stats[side].get("weak_received") or {}).values():
                    label = str((item or {}).get("label") or "")
                    try:
                        count = int((item or {}).get("count", 0) or 0)
                    except Exception:
                        count = 0
                    if label in ("간", "복부", "명치"):
                        body += count
                    elif label in ("턱", "코") or "관자놀이" in label:
                        head += count
            return body, head

        body_focus, head_focus = _weak_focus_counts()
        total_tko = blue_tko + red_tko
        total_kd = blue_kd + red_kd
        total_stun = blue_stun + red_stun
        total_big = blue_big + red_big
        total_counter = blue_counter + red_counter
        if total_tko > 0:
            round_tag = "TKO ROUND"
        elif total_kd > 0:
            round_tag = "KNOCKDOWN ROUND"
        elif total_counter >= 3:
            round_tag = "COUNTER GAME"
        elif (blue_landed + red_landed) == 0 and (blue_thrown + red_thrown) > 0:
            round_tag = "ACTIVITY / MISS"
        elif damage_gap >= 120.0:
            round_tag = "DAMAGE LEAD"
        elif body_focus >= 3 and body_focus >= head_focus:
            round_tag = "BODY ATTACK"
        elif head_focus >= 3 and head_focus > body_focus:
            round_tag = "HEAD HUNTING"
        elif total_stun > 0:
            round_tag = "STUN ROUND"
        elif total_big >= 3:
            round_tag = "POWER ROUND"
        elif leader == "draw":
            round_tag = "CLOSE ROUND"
        else:
            round_tag = "ROUND FLOW"

        def _report_reason() -> str:
            total_landed = blue_landed + red_landed
            total_thrown = blue_thrown + red_thrown
            if total_landed == 0 and total_thrown > 0:
                return f"적중 기록은 없지만 공격 시도는 블루 {blue_thrown}회, 레드 {red_thrown}회입니다."
            if leader == "draw":
                return "데미지와 적중 차이가 크지 않은 접전 라운드입니다."
            st = stats.get(leader, {})
            tkos = int(st.get("tkos_for", 0) or 0)
            kds = int(st.get("knockdowns_for", 0) or 0)
            if tkos > 0:
                return "TKO 장면이 라운드의 결정적인 흐름이었습니다."
            if kds > 0:
                return "다운 장면이 라운드의 인상을 크게 바꿨습니다."
            if damage_gap >= 120.0:
                return "누적 데미지 차이가 라운드 흐름을 갈랐습니다."
            if landed_gap >= 8:
                return "적중 수에서 확실한 차이를 만들었습니다."
            if int(st.get("stuns_for", 0) or 0) > 0:
                return "스턴 장면으로 위기를 만들었습니다."
            if int(st.get("counter_hits", 0) or 0) > 0:
                return "카운터 타이밍으로 흐름을 잡았습니다."
            top = self._round_report_top_items(st.get("punches") or {}, limit=1)
            if top:
                return f"{str(top[0].get('label') or '유효타')} 적중이 눈에 띄었습니다."
            return "유효타 싸움에서 조금 더 앞섰습니다."

        def _round_report_punch_breakdown(items: Dict[str, Dict[str, Any]]) -> List[dict]:
            order = [
                ("jab", "JAB", "잽"),
                ("cross", "CROSS", "스트레이트"),
                ("hook", "HOOK", "훅"),
                ("upper", "UPPER", "어퍼"),
                ("over", "OVER", "오버핸드"),
                ("other", "OTHER", "기타"),
            ]
            out: List[dict] = []
            src = items or {}
            for key, short_label, label in order:
                item = src.get(key) or {}
                try:
                    count = int(item.get("count", 0) or 0)
                except Exception:
                    count = 0
                try:
                    damage = float(item.get("damage", 0.0) or 0.0)
                except Exception:
                    damage = 0.0
                out.append({
                    "key": key,
                    "shortLabel": short_label,
                    "label": label if label and "?" not in str(label) else short_label,
                    "count": max(0, count),
                    "damage": round(max(0.0, damage), 1),
                })
            return out

        def side_payload(side: str) -> dict:
            st = stats[side]
            punches = st.get("punches") or {}
            raw_thrown_punches = st.get("thrown_punches") or {}
            landed = int(st.get("landed", 0) or 0)
            thrown = max(landed, int(st.get("thrown", 0) or 0))
            keys = ("jab", "cross", "hook", "upper", "over")
            landed_by_key = {key: max(0, int(dict(punches.get(key) or {}).get("count", 0) or 0)) for key in keys}
            thrown_punches = {
                key: {
                    "label": dict(raw_thrown_punches.get(key) or {}).get("label") or key.upper(),
                    "count": max(landed_by_key[key], int(dict(raw_thrown_punches.get(key) or {}).get("count", 0) or 0)),
                    "damage": 0.0,
                }
                for key in keys
            }
            misses = max(0, thrown - landed)
            accuracy = int(round((float(landed) / float(thrown) * 100.0))) if thrown > 0 else 0
            punch_accuracy = []
            for key in keys:
                landed_item = dict(punches.get(key) or {})
                thrown_item = dict(thrown_punches.get(key) or {})
                landed_count = max(0, int(landed_item.get("count", 0) or 0))
                thrown_count = max(0, int(thrown_item.get("count", 0) or 0))
                punch_accuracy.append({
                    "key": key,
                    "landed": landed_count,
                    "thrown": thrown_count,
                    "accuracy": int(round(float(landed_count) / float(thrown_count) * 100.0)) if thrown_count else 0,
                })
            return {
                "name": str(st.get("name") or ("BLUE" if side == "blue" else "RED")),
                "landed": landed,
                "thrown": thrown,
                "misses": misses,
                "accuracy": accuracy,
                "activity": thrown,
                "damage": int(round(float(st.get("damage", 0.0) or 0.0))),
                "bigHits": int(st.get("big_hits", 0) or 0),
                "counterHits": int(st.get("counter_hits", 0) or 0),
                "knockdowns": int(st.get("knockdowns_for", 0) or 0),
                "tkos": int(st.get("tkos_for", 0) or 0),
                "stuns": int(st.get("stuns_for", 0) or 0),
                "punchTop": self._round_report_top_items(punches, limit=3),
                "maxPunch": dict(st.get("max_punch") or {}),
                "punchesThrownTop": self._round_report_top_items(thrown_punches, limit=3),
                "landedBreakdown": _round_report_punch_breakdown(punches),
                "punchBreakdown": _round_report_punch_breakdown(thrown_punches),
                "punchAccuracyBreakdown": punch_accuracy,
                "weakReceivedTop": self._round_report_top_items(st.get("weak_received") or {}, limit=3),
                "weakReceivedAll": self._round_report_top_items(st.get("weak_received") or {}, limit=8),
                "allHits": list(st.get("received_hits") or [])[-64:],
                "punishment": dict((punishment_snapshot or {}).get(side) or {}),
            }

        official_scorecard: Dict[str, Any] = {}
        try:
            match_dir = os.path.dirname(damage_path)
            official_scorecard = self._build_scorecard_overlay_payload(match_dir, state=self._last_round_state, round_no=round_no) or {}
        except Exception:
            official_scorecard = {}

        match_result: Dict[str, Any] = {}
        try:
            match_result = self._build_winner_overlay_payload(os.path.dirname(damage_path)) or {}
        except Exception:
            match_result = {}
        winner_side = str((match_result or {}).get("winner") or (official_scorecard or {}).get("winner") or "").lower().strip()
        winner_name = str((match_result or {}).get("winnerName") or (official_scorecard or {}).get("winnerName") or "").strip()
        is_final = bool(match_result) or str(getattr(self, "_last_round_state", "") or "").lower() in ("results", "end", "knockout", "disqualified")
        if bool(is_final):
            try:
                scorecard_total = self._scorecard_compute(damage_path, round_no, events)
                rounds_total = dict((scorecard_total or {}).get("rounds") or {})
                if rounds_total:
                    for side in sides:
                        st = stats[side]
                        st["landed"] = 0
                        st["thrown"] = 0
                        st["damage"] = 0.0
                        st["big_hits"] = 0
                        st["counter_hits"] = 0
                        st["knockdowns_for"] = 0
                        st["tkos_for"] = 0
                        st["stuns_for"] = 0
                        st["punches"] = {}
                        st["max_punch"] = {}
                        st["thrown_punches"] = {}
                        st["weak_received"] = {}
                    for _round_no, rst in sorted(rounds_total.items()):
                        rst = dict(rst or {})
                        dealt = dict(rst.get("dealt") or {})
                        hits = dict(rst.get("hits") or {})
                        bigs = dict(rst.get("bigs") or {})
                        counters = dict(rst.get("counters_for") or {})
                        kds = dict(rst.get("knockdowns_for") or {})
                        tkos = dict(rst.get("tkos_for") or {})
                        stuns = dict(rst.get("stuns_for") or {})
                        punches_by_side = dict(rst.get("punches") or {})
                        max_punch_by_side = dict(rst.get("max_punch") or {})
                        thrown_by_side = dict(rst.get("thrown") or {})
                        thrown_punches_by_side = dict(rst.get("thrown_punches") or {})
                        weak_by_receiver = dict(rst.get("weak_received") or {})
                        for side in sides:
                            st = stats[side]
                            landed_by_side = dict(rst.get("landed") or {})
                            st["landed"] = int(st.get("landed", 0) or 0) + int(
                                landed_by_side.get(side, hits.get(side, 0)) or 0
                            )
                            st["thrown"] = int(st.get("thrown", 0) or 0) + int(thrown_by_side.get(side, 0) or 0)
                            st["damage"] = float(st.get("damage", 0.0) or 0.0) + float(dealt.get(side, 0.0) or 0.0)
                            st["big_hits"] = int(st.get("big_hits", 0) or 0) + int(bigs.get(side, 0) or 0)
                            st["counter_hits"] = int(st.get("counter_hits", 0) or 0) + int(counters.get(side, 0) or 0)
                            st["knockdowns_for"] = int(st.get("knockdowns_for", 0) or 0) + int(kds.get(side, 0) or 0)
                            st["tkos_for"] = int(st.get("tkos_for", 0) or 0) + int(tkos.get(side, 0) or 0)
                            st["stuns_for"] = int(st.get("stuns_for", 0) or 0) + int(stuns.get(side, 0) or 0)
                            for pkey, item in dict(punches_by_side.get(side) or {}).items():
                                target = st["punches"].setdefault(pkey, {"label": (item or {}).get("label") or pkey, "count": 0, "damage": 0.0})
                                target["count"] = int(target.get("count", 0) or 0) + int((item or {}).get("count", 0) or 0)
                                target["damage"] = float(target.get("damage", 0.0) or 0.0) + float((item or {}).get("damage", 0.0) or 0.0)
                            round_max = dict(max_punch_by_side.get(side) or {})
                            if float(round_max.get("damage", 0.0) or 0.0) > float((st.get("max_punch") or {}).get("damage", 0.0) or 0.0):
                                st["max_punch"] = round_max
                            for pkey, item in dict(thrown_punches_by_side.get(side) or {}).items():
                                target = st["thrown_punches"].setdefault(
                                    pkey,
                                    {"label": (item or {}).get("label") or pkey, "count": 0, "damage": 0.0},
                                )
                                target["count"] = int(target.get("count", 0) or 0) + int((item or {}).get("count", 0) or 0)
                            for wkey, item in dict(weak_by_receiver.get(side) or {}).items():
                                target = st["weak_received"].setdefault(wkey, {"label": (item or {}).get("label") or wkey, "count": 0, "damage": 0.0})
                                target["count"] = int(target.get("count", 0) or 0) + int((item or {}).get("count", 0) or 0)
                                target["damage"] = float(target.get("damage", 0.0) or 0.0) + float((item or {}).get("damage", 0.0) or 0.0)
                    logging.info("SPECTATORLOG_FINAL_REPORT_TOTALS rounds=%s blue_dmg=%.1f red_dmg=%.1f", len(rounds_total), float(stats["blue"].get("damage", 0.0) or 0.0), float(stats["red"].get("damage", 0.0) or 0.0))
            except Exception:
                logging.exception("SPECTATORLOG_FINAL_REPORT_TOTALS_FAIL")
        report = {
            "round": r,
            "isFinal": bool(is_final),
            "winner": winner_side,
            "winnerName": winner_name,
            "matchResult": match_result,
            "leader": winner_side if bool(is_final) and winner_side in ("blue", "red", "draw") else leader,
            "leaderName": (winner_name or ("DRAW" if winner_side == "draw" else "")) if bool(is_final) else leader_name,
            "summaryLine": _report_reason(),
            "roundTag": ("MATCH RESULT" if bool(is_final) else round_tag),
            "bestShot": best_shot,
            "decisiveMoment": decisive_moment,
            "officialScorecard": official_scorecard,
            "scorecard": official_scorecard,
            "displayMs": 20000 if bool(is_final) else int(max(8000, min(90000, ((float(break_seconds_left) if break_seconds_left is not None else float(self._configured_break_duration())) * 1000.0) + 1200.0))),
            "showDelayMs": int(round(max(0.0, min(30.0, float(getattr(self.cfg, "spectator_final_report_delay_sec", 5.0) or 0.0))) * 1000.0)) if bool(is_final) else 0,
            "blue": side_payload("blue"),
            "red": side_payload("red"),
        }
        try:
            logging.info(
                "SPECTATORLOG_REPORT_AUDIT round=%s final=%s blue=%s red=%s",
                r,
                bool(is_final),
                {
                    "landed": report["blue"].get("landed"), "thrown": report["blue"].get("thrown"),
                    "accuracy": report["blue"].get("accuracy"), "damage": report["blue"].get("damage"),
                    "kd": report["blue"].get("knockdowns"), "types": report["blue"].get("punchAccuracyBreakdown"),
                },
                {
                    "landed": report["red"].get("landed"), "thrown": report["red"].get("thrown"),
                    "accuracy": report["red"].get("accuracy"), "damage": report["red"].get("damage"),
                    "kd": report["red"].get("knockdowns"), "types": report["red"].get("punchAccuracyBreakdown"),
                },
            )
        except Exception:
            pass
        if bool(is_final):
            try:
                bn = report["blue"].get("name") or "BLUE"
                rn = report["red"].get("name") or "RED"
                if winner_side == "draw":
                    report["summaryLine"] = "공식 판정은 무승부입니다. 라운드별 점수와 누적 데미지를 함께 확인합니다."
                elif winner_side == "blue":
                    report["summaryLine"] = f"{bn} 승리. 공식 스코어카드와 전체 타격 기록을 정리합니다."
                elif winner_side == "red":
                    report["summaryLine"] = f"{rn} 승리. 공식 스코어카드와 전체 타격 기록을 정리합니다."
                else:
                    report["summaryLine"] = "경기 종료. 공식 스코어카드와 전체 타격 기록을 정리합니다."
            except Exception:
                pass
        try:
            logging.info(
                "SPECTATORLOG_ROUND_REPORT round=%s leader=%s blue_hits=%s red_hits=%s blue_dmg=%s red_dmg=%s",
                r,
                leader,
                report["blue"].get("landed"),
                report["red"].get("landed"),
                report["blue"].get("damage"),
                report["red"].get("damage"),
            )
        except Exception:
            pass
        return report

    def _korean_final_consonant_index(self, text: str) -> int:
        """Return the Hangul final-consonant index for Korean josa selection."""
        value = str(text or "").strip()
        if not value:
            return 0
        ch = value[-1]
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            return (code - 0xAC00) % 28
        # Common digit pronunciations: 0/1/3/6/7/8 end with a batchim sound.
        if ch.isdigit():
            return 1 if ch in "013678" else 0
        return 0

    def _josa(self, text: str, pair: str) -> str:
        """Append the correct Korean particle to a player name.

        Supported pairs: 은/는, 이/가, 을/를, 과/와 or 와/과, 으로/로.
        Non-Korean alphabetic IDs default to the no-batchim form, which is the
        least awkward Edge TTS fallback for shortened roman IDs.
        """
        value = str(text or "").strip()
        if not value:
            return ""
        final_index = self._korean_final_consonant_index(value)
        has_batchim = final_index > 0
        pair = str(pair or "").strip()
        if pair == "은/는":
            return value + ("은" if has_batchim else "는")
        if pair == "이/가":
            return value + ("이" if has_batchim else "가")
        if pair == "을/를":
            return value + ("을" if has_batchim else "를")
        if pair in ("과/와", "와/과"):
            return value + ("과" if has_batchim else "와")
        if pair == "으로/로":
            return value + ("으로" if has_batchim and final_index != 8 else "로")
        return value + pair

    def _ko_subject(self, name: str) -> str:
        return self._josa(name, "이/가")

    def _format_recent_hit_text(self, ev: dict) -> str:
        ev = dict(ev or {})
        punch = self._punch_ko(str(ev.get("punch", "") or "").strip())
        if not punch:
            punch = str(ev.get("punch", "") or "").strip()
        try:
            damage = int(round(float(ev.get("damage", 0.0) or 0.0)))
        except Exception:
            damage = 0
        try:
            cm = float(ev.get("counter_mult", 1.0) or 1.0)
        except Exception:
            cm = 1.0
        prefix = "카운터 " if self._is_counter_event(ev) else ""
        head = f"{prefix}{punch} {damage}".strip()
        weak = self._weak_point_ko(str(ev.get("weak_point", "") or ""))
        if weak:
            return f"{head}\n{weak}"
        return head

    def _build_commentary_text(self, latest: dict, effect_kind: str, receiver_side: str) -> str:
        if not bool(getattr(self.cfg, "spectator_commentary_enabled", False)):
            return ""
        mode = str(getattr(self.cfg, "spectator_commentary_mode", "standard") or "standard").lower()
        if mode not in ("quiet", "standard", "active"):
            mode = "standard"
        try:
            min_damage = float(getattr(self.cfg, "spectator_commentary_min_damage", 25.0) or 25.0)
        except Exception:
            min_damage = 25.0
        attacker_side = "red" if receiver_side == "blue" else "blue"
        attacker = self._commentary_name(attacker_side)
        receiver = self._commentary_name(receiver_side)
        damage = float((latest or {}).get("damage", 0.0) or 0.0)
        weak = self._weak_point_ko(str((latest or {}).get("weak_point", "") or ""))
        punch = self._punch_ko(str((latest or {}).get("punch", "") or "").strip())
        if effect_kind == "tko":
            return f"{self._caster_name(receiver_side)}, 테크니컬 녹아웃 당합니다"
        if effect_kind == "knockdown":
            return f"{self._caster_name(receiver_side)}, 다운 당합니다"
        if effect_kind == "stun":
            return "크게 흔들립니다!"
        if mode == "quiet":
            return ""
        if damage >= min_damage:
            if weak:
                return f"{weak}에 큰 타격"
            if punch:
                return f"강한 {punch}"
            return "큰 타격"
        return ""

    def _damage_event_key(self, ev: dict) -> Tuple[Any, ...]:
        try:
            return (
                round(float(ev.get("time", 0.0) or 0.0), 2),
                round(float(ev.get("damage", 0.0) or 0.0), 2),
                str(ev.get("receiver_side") or ""),
                str(ev.get("hand") or ""),
                round(float(ev.get("counter_mult", 1.0) or 1.0), 3),
                str(ev.get("punch") or ""),
                str(ev.get("damage_type") or ""),
                str(ev.get("weak_point") or ""),
            )
        except Exception:
            return (
                str(ev.get("time") or ""),
                str(ev.get("damage") or ""),
                str(ev.get("receiver_side") or ""),
                str(ev.get("punch") or ""),
                str(ev.get("damage_type") or ""),
                str(ev.get("weak_point") or ""),
            )

    def _read_punishment_values(self, damage_path: str) -> Dict[str, Dict[str, float]]:
        root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(damage_path)), os.pardir))
        out: Dict[str, Dict[str, float]] = {"blue": {}, "red": {}}
        for side in ("blue", "red"):
            base = os.path.join(root, side)
            for key, filename in (
                ("mid", "punishment_mid.txt"),
                ("long_raw", "punishment_long_raw.txt"),
                ("long_weighted", "punishment_long_weighted.txt"),
            ):
                try:
                    value = float(self._read_text(os.path.join(base, filename)) or 0.0)
                    # Current SpectatorLog format stores punishment as [0,1].
                    # Older exports used percentages, so support both.
                    out[side][key] = value * 100.0 if 0.0 <= value <= 1.0 else value
                except Exception:
                    out[side][key] = 0.0
        return out

    def _clamp_percent(self, value: Any) -> float:
        try:
            return max(0.0, min(100.0, float(value or 0.0)))
        except Exception:
            return 0.0

    def _punishment_snapshot(self, damage_path: str) -> Dict[str, Dict[str, float]]:
        """Return punishment/gauge state used by commentary.

        SpectatorLog exposes punishment_mid and punishment_long values.  The
        browser HP bar already converts these into a remaining-gauge ratio; use
        the same interpretation here so lines like '체력 부담' are tied to the
        actual gauge, not only to raw damage events.
        """
        raw = self._read_punishment_values(damage_path)
        now = time.time()
        snap: Dict[str, Dict[str, float]] = {}
        for side in ("blue", "red"):
            mid = self._clamp_percent((raw.get(side) or {}).get("mid", 0.0))
            long_v = self._clamp_percent((raw.get(side) or {}).get("long_weighted", 0.0))
            if now <= float((self._punishment_mid_forced_until or {}).get(side, 0.0) or 0.0):
                mid = 100.0
            base = max(0.0, min(1.0, (100.0 - long_v) / 100.0))
            hp_ratio = max(0.0, min(1.0, base * (1.0 - mid / 100.0)))
            lost_pct = max(0.0, min(100.0, (1.0 - hp_ratio) * 100.0))
            snap[side] = {
                "mid": mid,
                "long": long_v,
                "hp_ratio": hp_ratio,
                "lost_pct": lost_pct,
            }
        return snap

    def _remember_punishment_snapshot(self, snap: Dict[str, Dict[str, float]]) -> None:
        if not snap:
            return
        now = time.time()
        try:
            self._punishment_history.append((now, {
                side: dict((snap.get(side) or {})) for side in ("blue", "red")
            }))
        except Exception:
            return
        # Drop very old values even if maxlen has not been reached yet.
        try:
            while self._punishment_history and now - float(self._punishment_history[0][0]) > 240.0:
                self._punishment_history.popleft()
        except Exception:
            pass

    def _punishment_delta(self, side: str, seconds: float = 10.0) -> Dict[str, float]:
        side = str(side or "").lower()
        if side not in ("blue", "red") or not self._punishment_history:
            return {"lost_delta": 0.0, "mid_delta": 0.0, "long_delta": 0.0}
        now = time.time()
        latest = dict((self._punishment_history[-1][1] or {}).get(side, {}) or {})
        old = latest
        for at, snap in reversed(list(self._punishment_history)):
            try:
                if now - float(at or 0.0) >= float(seconds):
                    old = dict((snap or {}).get(side, {}) or {})
                    break
            except Exception:
                continue
        return {
            "lost_delta": self._clamp_percent(float(latest.get("lost_pct", 0.0) or 0.0) - float(old.get("lost_pct", 0.0) or 0.0)),
            "mid_delta": self._clamp_percent(float(latest.get("mid", 0.0) or 0.0) - float(old.get("mid", 0.0) or 0.0)),
            "long_delta": self._clamp_percent(float(latest.get("long", 0.0) or 0.0) - float(old.get("long", 0.0) or 0.0)),
        }

    def _gauge_risk_score(self, side: str, snap: Optional[Dict[str, Dict[str, float]]] = None, *, recent_damage: float = 0.0) -> float:
        side = str(side or "").lower()
        if side not in ("blue", "red"):
            return 0.0
        data = dict((snap or {}).get(side, {}) or {})
        if not data:
            return 0.0
        hp = max(0.0, min(1.0, float(data.get("hp_ratio", 1.0) or 1.0)))
        lost = self._clamp_percent(data.get("lost_pct", 0.0))
        mid = self._clamp_percent(data.get("mid", 0.0))
        long_v = self._clamp_percent(data.get("long", 0.0))
        delta = self._punishment_delta(side, 10.0)
        lost_delta = self._clamp_percent(delta.get("lost_delta", 0.0))
        recent_damage = max(0.0, float(recent_damage or 0.0))
        score = 0.0
        if hp <= 0.24 or lost >= 76.0 or long_v >= 62.0 or mid >= 88.0:
            score += 100.0
        elif hp <= 0.40 or lost >= 60.0 or long_v >= 48.0 or mid >= 72.0:
            score += 70.0
        elif lost_delta >= 9.0 and recent_damage >= 45.0:
            score += 55.0
        elif lost >= 48.0 or long_v >= 38.0 or mid >= 60.0:
            score += 35.0
        score += min(25.0, recent_damage / 4.0)
        score += min(18.0, lost_delta * 1.2)
        return score

    def _health_pressure_line(self, receiver_side: str, snap: Optional[Dict[str, Dict[str, float]]] = None, *, recent_damage: float = 0.0) -> str:
        mode = str(getattr(self.cfg, "spectator_commentary_mode", "standard") or "standard").lower()
        if mode == "quiet":
            return ""
        side = str(receiver_side or "").lower()
        if side not in ("blue", "red"):
            return ""
        data = dict((snap or {}).get(side, {}) or {})
        if not data:
            return ""
        hp = max(0.0, min(1.0, float(data.get("hp_ratio", 1.0) or 1.0)))
        lost = self._clamp_percent(data.get("lost_pct", 0.0))
        mid = self._clamp_percent(data.get("mid", 0.0))
        long_v = self._clamp_percent(data.get("long", 0.0))
        delta = self._punishment_delta(side, 10.0)
        lost_delta = self._clamp_percent(delta.get("lost_delta", 0.0))
        recent_damage = max(0.0, float(recent_damage or 0.0))

        # Only say health/gauge lines when the actual gauge agrees.  Raw damage
        # alone should produce pressure/정타 commentary, not 체력부담 commentary.
        if hp <= 0.24 or lost >= 76.0 or long_v >= 62.0 or mid >= 88.0:
            return self._commentary_pick(f"health-critical:{side}:{int(lost)}:{int(mid)}:{int(long_v)}", [
                "위험 구간에 들어갑니다.",
                "회복할 시간이 필요합니다.",
                "이제 무리해서 들어가면 위험합니다.",
                "데미지 부담이 상당히 커졌습니다.",
            ])
        if hp <= 0.40 or lost >= 60.0 or long_v >= 48.0 or mid >= 72.0 or (lost_delta >= 14.0 and recent_damage >= 35.0):
            return self._commentary_pick(f"health-pressure:{side}:{int(lost)}:{int(lost_delta)}", [
                "체력 부담이 커지고 있습니다.",
                "데미지가 많이 쌓였습니다.",
                "수비 안정이 필요합니다.",
                "한 번 더 큰 정타를 허용하면 위험합니다.",
                "회복 시간을 벌어야 합니다.",
            ])
        if lost_delta >= 9.0 and recent_damage >= 45.0:
            return self._commentary_pick(f"health-drop:{side}:{int(lost_delta)}:{int(recent_damage)}", [
                "짧은 시간에 데미지가 크게 쌓였습니다.",
                "방금 교전에서 손실이 큽니다.",
                "이번 교전의 부담이 데미지로 바로 보입니다.",
            ])
        return ""

    def _round_gauge_context_line(self, snap: Dict[str, Dict[str, float]], leader: str, other: str, pick) -> str:
        if not snap:
            return ""
        def lost(side: str) -> float:
            return self._clamp_percent((snap.get(side) or {}).get("lost_pct", 0.0))
        def mid(side: str) -> float:
            return self._clamp_percent((snap.get(side) or {}).get("mid", 0.0))
        def longv(side: str) -> float:
            return self._clamp_percent((snap.get(side) or {}).get("long", 0.0))
        blue_lost, red_lost = lost("blue"), lost("red")
        worst = "blue" if blue_lost >= red_lost else "red"
        gap = abs(blue_lost - red_lost)
        worst_lost = max(blue_lost, red_lost)
        worst_delta = self._punishment_delta(worst, 45.0)
        delta_loss = self._clamp_percent(worst_delta.get("lost_delta", 0.0))
        worst_name = self._commentary_name(worst)
        if worst_lost >= 72.0 or mid(worst) >= 82.0 or longv(worst) >= 58.0:
            return pick("gauge-danger-long", [
                f"{self._josa(worst_name, '은/는')} 데미지 상황까지 보면 쉬는 시간 회복이 정말 중요해졌습니다.",
                f"{worst_name} 쪽 데미지 기록만 봐도 위험 구간에 가까워졌습니다.",
                f"{self._josa(worst_name, '은/는')} 남은 체력 여유가 크지 않아서, 다음 라운드 초반 위기 관리가 중요합니다.",
            ])
        if worst_lost >= 55.0 or gap >= 18.0:
            return pick("gauge-pressure-long", [
                f"{worst_name} 쪽 체력 흐름에서도 부담 차이가 조금씩 보이고 있습니다.",
                f"{worst_name}에게 정타가 쌓이면서 쉬는 시간 대응이 중요해졌습니다.",
                f"{self._josa(worst_name, '은/는')} 다음 라운드 초반에 무리한 교전을 피해야 합니다.",
            ])
        if delta_loss >= 10.0:
            return pick("gauge-drop-long", [
                f"{self._josa(worst_name, '은/는')} 라운드 후반 받은 데미지가 있었기 때문에, 쉬는 시간 이후 반응을 봐야 합니다.",
                f"{worst_name}에게 마지막 교전의 부담이 남아 있어서, 다음 라운드 첫 교전이 중요합니다.",
                f"{self._josa(worst_name, '이/가')} 후반에 받은 데미지를 얼마나 털어내느냐가 다음 라운드 변수입니다.",
            ])
        return pick("gauge-stable-long", [
            "데미지 부담은 아직 결정적인 수준까지 벌어지지 않았습니다.",
            "체력 흐름만 놓고 보면 아직 한 번의 좋은 교전으로 흐름을 바꿀 여지는 있습니다.",
            "체력 여유가 완전히 사라진 상황은 아니기 때문에, 다음 라운드 초반 운영이 중요합니다.",
        ])

    def _commentary_category_from_key(self, key: str) -> str:
        raw = str(key or "").split(":", 1)[0].strip().lower()
        if raw in ("kd", "kd-event", "down-plan", "down-restart") or raw.startswith("down-"):
            return "knockdown"
        if raw in ("stun", "stun-event"):
            return "stun"
        if raw in ("tko", "tko-event"):
            return "tko"
        if raw.startswith("round-summary"):
            return "round_summary"
        if raw.startswith("idle"):
            return "idle"
        if raw.startswith("witty"):
            return "witty"
        return raw or "commentary"

    def _commentary_meaning_from_category(self, category: str) -> str:
        cat = str(category or "").lower().strip()
        if cat.startswith("weak_"):
            return "weak"
        if cat in ("big", "pressure", "health", "counter", "combo", "flow", "round_summary", "idle", "witty"):
            return cat
        if cat in ("knockdown", "stun", "tko"):
            return "caster_urgent"
        return cat or "commentary"

    def _commentary_cooldown_for_category(self, category: str) -> float:
        cat = str(category or "").lower().strip()
        mode = str(getattr(self.cfg, "spectator_commentary_mode", "standard") or "standard").lower()
        table = {
            "counter": 5.5 if mode == "active" else 7.0,
            "combo": 5.0 if mode == "active" else 6.5,
            "big": 4.0 if mode == "active" else 6.0,
            "pressure": 5.0 if mode == "active" else 8.0,
            "health": 7.0 if mode == "active" else 10.0,
            "weak": 10.0,
            "weak_chin": 10.0,
            "weak_body": 10.0,
            "weak_head": 10.0,
            "weak_face": 12.0,
            "flow": 10.0,
            "round_summary": 18.0,
            "idle": 8.0 if mode == "active" else 12.0,
            "witty": 4.5 if mode == "active" else 7.0,
            "stun": 2.5,
            "knockdown": 1.5,
            "tko": 1.0,
        }
        return float(table.get(cat, 4.0))

    def _commentary_pick(self, key: str, candidates: List[str]) -> str:
        items = [str(x or "").strip() for x in list(candidates or []) if str(x or "").strip()]
        if not items:
            return ""
        now = time.time()
        category = self._commentary_category_from_key(key)
        meaning = self._commentary_meaning_from_category(category)
        urgent = category in ("knockdown", "stun", "tko")
        # Do not keep repeating the same type of analyst line. Critical caster calls are allowed.
        if not urgent:
            cat_cd = self._commentary_cooldown_for_category(category)
            mean_cd = self._commentary_cooldown_for_category(meaning)
            if now - float(self._commentary_category_last_at.get(category, 0.0) or 0.0) < cat_cd:
                return ""
            if now - float(self._commentary_meaning_last_at.get(meaning, 0.0) or 0.0) < mean_cd:
                return ""
        recent_lines = {line for line, at in list(self._commentary_recent_lines) if now - float(at or 0.0) <= 60.0}
        pool = [x for x in items if x not in recent_lines]
        if not pool:
            if not urgent and len(items) > 1:
                return ""
            pool = items
        try:
            seed = sum(ord(ch) for ch in str(key or "")) + int(now * 1000)
            chosen = pool[abs(seed) % len(pool)]
        except Exception:
            chosen = pool[0]
        if chosen:
            self._commentary_recent_lines.append((chosen, now))
            self._commentary_category_last_at[category] = now
            self._commentary_meaning_last_at[meaning] = now
        return chosen

    def _reset_down_state_machine(self) -> None:
        self._down_round_key = None
        self._down_round_counts = {"blue": 0, "red": 0}
        self._down_active = {"side": "", "round": None, "count": 0, "at": 0.0}

    def _ensure_down_round(self, round_no: Optional[int]) -> int:
        try:
            r = max(1, int(round_no or self._last_fight_round_no or self._last_round_time_round or 1))
        except Exception:
            r = 1
        if self._down_round_key != r:
            self._down_round_key = r
            self._down_round_counts = {"blue": 0, "red": 0}
            self._down_active = {"side": "", "round": r, "count": 0, "at": 0.0}
        return r

    def _register_knockdown(self, side: str, round_no: Optional[int]) -> int:
        side = str(side or "").lower().strip()
        if side not in ("blue", "red"):
            side = "blue"
        r = self._ensure_down_round(round_no)
        counts = getattr(self, "_down_round_counts", None)
        if not isinstance(counts, dict):
            counts = {"blue": 0, "red": 0}
            self._down_round_counts = counts
        counts[side] = int(counts.get(side, 0) or 0) + 1
        count = int(counts.get(side, 0) or 0)
        self._down_active = {"side": side, "round": r, "count": count, "at": time.time()}
        return count

    def _cancel_down_commentary(self, out: Dict[str, Any], reason: str = "") -> None:
        try:
            out["commentary_tts_stop_roles"] = ["caster", "analyst"]
            out["commentary_tts_stop_reason"] = str(reason or "down_cancel")
            active = getattr(self, "_down_active", {}) or {}
            self._down_active = {"side": "", "round": active.get("round"), "count": 0, "at": 0.0}
        except Exception:
            pass

    def _down_restart_text(self) -> str:
        active = getattr(self, "_down_active", {}) or {}
        try:
            count = int(active.get("count", 0) or 0)
        except Exception:
            count = 0
        key = f"down-restart:{active.get('side','')}:{active.get('round','')}:{count}"
        if count >= 2:
            return self._commentary_pick(key, [
                "다시 일어납니다!",
                "경기는 계속됩니다!",
                "하지만 위험합니다.",
                "수비가 먼저입니다.",
            ])
        return self._commentary_pick(key, [
            "경기 계속됩니다!",
            "위기를 넘깁니다!",
            "다시 싸웁니다!",
            "일어났습니다!",
        ])

    def _short_down_pick(self, key: str, candidates: List[str], max_len: int = 24) -> str:
        return self._commentary_pick(key, [x for x in candidates if 0 < len(str(x).strip()) <= max_len])

    def _build_knockdown_commentary_plan(self, effect_events: List[dict], new_events: List[dict], round_no: Optional[int], punishment_snapshot: Optional[Dict[str, Dict[str, float]]] = None) -> Optional[Dict[str, Any]]:
        """Build a short, cancelable knockdown sound-fill plan.

        Down commentary is handled separately from normal hit commentary.  It
        never says rigid count/TKO phrases; it changes tone by down number and
        schedules only very short follow-ups so restart can cancel them cleanly.
        """
        kd_items = [e for e in list(effect_events or []) if str((e or {}).get("kind") or "").lower() == "knockdown"]
        side = ""
        count = 0
        if kd_items:
            last = kd_items[-1] or {}
            side = str(last.get("side") or "").lower().strip()
            try:
                count = int(last.get("round_down_count", 0) or 0)
            except Exception:
                count = 0
        if side not in ("blue", "red"):
            evs = [e for e in list(new_events or []) if str((e or {}).get("effect_kind") or "").lower() == "knockdown"]
            if evs:
                side = str((evs[-1] or {}).get("receiver_side") or "").lower().strip()
        if side not in ("blue", "red"):
            return None
        if count <= 0:
            count = int((getattr(self, "_down_round_counts", {}) or {}).get(side, 0) or 1)
        count = max(1, min(3, int(count)))
        name = self._caster_name(side)
        key = f"down-plan:{round_no}:{side}:{count}:{int(time.time() * 10)}"
        if count >= 3:
            primary = self._short_down_pick(f"{key}:primary", [
                f"{name}, 세 번째 다운입니다!",
                f"{name}, 또 무너집니다!",
                f"{name}, 더 버티기 어렵습니다!",
            ], 34)
            followups = [
                {"text": self._short_down_pick(f"{key}:stop1", ["여기서 멈춥니다!", "더는 이어가기 어렵습니다.", "승부가 갈렸습니다."], 24), "role": "caster", "delay_ms": 900, "retries": 2},
                {"text": self._short_down_pick(f"{key}:stop2", ["경기 종료됩니다!", "결정적인 순간입니다.", "이 장면으로 끝납니다."], 24), "role": "caster", "delay_ms": 1850, "retries": 2},
            ]
        elif count == 2:
            primary = self._short_down_pick(f"{key}:primary", [
                f"{name}, 다시 다운입니다!",
                f"{name}, 또 쓰러집니다!",
                f"{name}, 두 번째 다운입니다!",
            ], 34)
            followups = [
                {"text": self._short_down_pick(f"{key}:danger", ["이건 정말 큽니다.", "분위기가 흔들립니다.", "위험도가 올라갑니다.", "큰 위기입니다."], 24), "role": "analyst", "delay_ms": 1300, "retries": 2},
                {"text": self._short_down_pick(f"{key}:defense", ["수비가 먼저입니다.", "더 맞으면 어렵습니다.", "회복이 급합니다.", "버텨도 부담이 큽니다."], 24), "role": "analyst", "delay_ms": 2850, "retries": 2},
                {"text": self._short_down_pick(f"{key}:late", ["다음 교전이 위험합니다.", "지금은 버텨야 합니다.", "무리하면 안 됩니다."], 24), "role": "analyst", "delay_ms": 4300, "retries": 1},
            ]
        else:
            primary = self._short_down_pick(f"{key}:primary", [
                f"{name}, 다운입니다!",
                f"{name}, 쓰러집니다!",
                f"{name}, 크게 흔들립니다!",
            ], 34)
            followups = [
                {"text": self._short_down_pick(f"{key}:shock", ["충격이 큽니다.", "크게 들어갔습니다.", "위험한 장면입니다.", "한 방의 충격입니다."], 24), "role": "analyst", "delay_ms": 1450, "retries": 2},
                {"text": self._short_down_pick(f"{key}:recover", ["버텨야 합니다.", "회복이 필요합니다.", "중심을 잡아야 합니다.", "아직 끝난 건 아닙니다."], 24), "role": "analyst", "delay_ms": 3050, "retries": 2},
                {"text": self._short_down_pick(f"{key}:question", ["일어날 수 있을까요.", "위기를 넘겨야 합니다.", "다시 돌아올 수 있을까요."], 24), "role": "caster", "delay_ms": 4850, "retries": 1},
            ]
        clean_followups = []
        for item in followups:
            text = str((item or {}).get("text") or "").strip()
            if not text:
                continue
            # User explicitly rejected rigid count/TKO phrasing; keep these out.
            banned = ("카운트", "TKO로", "티케이오", "쓰리다운", "심판")
            if any(x in text for x in banned):
                continue
            clean_followups.append(item)
        if not primary:
            return None
        logging.info("SPECTATORLOG_DOWN_PLAN side=%s round=%s count=%s primary=%s followups=%s", side, round_no, count, primary, len(clean_followups))
        return {"text": primary, "role": "caster", "side": side, "count": count, "followups": clean_followups}

    def _witty_duo_max_per_round(self, mode: str) -> int:
        mode = str(mode or "standard").lower().strip()
        if mode == "active":
            return 6
        if mode == "standard":
            return 4
        return 0

    def _witty_duo_chance_percent(self, tag: str, mode: str) -> int:
        mode = str(mode or "standard").lower().strip()
        tag = str(tag or "").lower().strip()
        if mode == "quiet":
            return 0
        if tag in ("idle", "late", "jab", "miss"):
            return 55 if mode == "active" else 35
        if tag in ("pressure", "vr"):
            return 42 if mode == "active" else 25
        return 30 if mode == "active" else 18

    def _witty_duo_tag_from_text(self, text: str) -> str:
        t = str(text or "").strip()
        if not t:
            return ""
        if any(x in t for x in ("다운", "흔들", "위험", "녹아웃", "스턴", "충격", "체력", "게이지", "회복")):
            return ""
        if any(x in t for x in ("막판", "남은 시간", "마지막")):
            return "late"
        if any(x in t for x in ("잽", "앞손")):
            return "jab"
        if any(x in t for x in ("빗나", "허공", "미스")):
            return "miss"
        if any(x in t for x in ("압박", "밀고", "주도권")):
            return "pressure"
        if any(x in t for x in ("소강", "거리", "타이밍", "정타가 잠시", "눈치", "간만", "들어가지", "아직 아무도", "멈췄")):
            return "idle"
        return ""

    def _witty_duo_candidates(self, tag: str) -> List[str]:
        tag = str(tag or "").lower().strip()
        pools = {
            "idle": [
                "둘 다 먼저 가긴 싫죠.",
                "서로 오라고만 합니다.",
                "눈치 싸움 길어집니다.",
                "아직 간만 봅니다.",
                "신중함이 길어집니다.",
                "먼저 가기 애매합니다.",
            ],
            "late": [
                "막판엔 한 방입니다.",
                "끝까지 눈 못 뗍니다.",
                "여기서 실수하면 큽니다.",
                "마지막까지 조심해야죠.",
            ],
            "jab": [
                "앞손이 오늘 바쁩니다.",
                "잽 출근률 높습니다.",
                "작은 잽도 귀찮습니다.",
                "앞손으로 간 봅니다.",
            ],
            "miss": [
                "폼은 멋졌습니다.",
                "공기는 맞았습니다.",
                "방금은 안 맞았습니다.",
                "거리만 조금 멀었습니다.",
            ],
            "pressure": [
                "이러면 피곤합니다.",
                "수비가 바빠집니다.",
                "계속 받으면 부담됩니다.",
                "숨 쉴 틈이 줄어듭니다.",
            ],
            "vr": [
                "팔은 많이 나갔습니다.",
                "운동량은 확실합니다.",
                "숨 찰 타이밍입니다.",
                "헤드셋 안쪽 바쁩니다.",
            ],
        }
        return list(pools.get(tag, []))

    def _witty_duo_line(self, tag: str, round_no: Optional[int] = None, force: bool = False) -> str:
        mode = str(getattr(self.cfg, "spectator_commentary_mode", "standard") or "standard").lower().strip()
        if mode == "quiet":
            return ""
        tag = str(tag or "").lower().strip()
        if tag not in ("idle", "late", "jab", "miss", "pressure", "vr"):
            return ""
        max_round = self._witty_duo_max_per_round(mode)
        if max_round <= 0:
            return ""
        try:
            r = max(1, int(round_no or self._last_fight_round_no or 1))
        except Exception:
            r = 1
        if self._witty_duo_round_key != r:
            self._witty_duo_round_key = r
            self._witty_duo_round_count = 0
            self._witty_duo_recent.clear()
        if int(getattr(self, "_witty_duo_round_count", 0) or 0) >= max_round:
            return ""
        now = time.time()
        min_gap = 6.0 if mode == "active" else 9.0
        recent = [(k, at) for k, at in list(getattr(self, "_witty_duo_recent", [])) if now - float(at or 0.0) <= 55.0]
        self._witty_duo_recent = deque(recent, maxlen=24)
        if recent and now - float(recent[-1][1] or 0.0) < min_gap:
            return ""
        if any(k == tag and now - float(at or 0.0) <= 25.0 for k, at in recent):
            return ""
        chance = self._witty_duo_chance_percent(tag, mode)
        if not force:
            try:
                seed = sum(ord(ch) for ch in f"{tag}:{r}:{int(now // 2)}") + int(now * 1000)
                if abs(seed) % 100 >= chance:
                    return ""
            except Exception:
                pass
        candidates = [x for x in self._witty_duo_candidates(tag) if 0 < len(str(x).strip()) <= 28]
        if not candidates:
            return ""
        text = self._commentary_pick(f"witty:{tag}:{r}:{int(now // 4)}", candidates)
        if not text:
            return ""
        self._witty_duo_round_count = int(getattr(self, "_witty_duo_round_count", 0) or 0) + 1
        try:
            self._witty_duo_recent.append((tag, now))
        except Exception:
            pass
        return text

    def _attach_witty_duo_followup(self, out: Dict[str, Any], state: str = "", round_no: Optional[int] = None) -> None:
        """Attach one short analyst follow-up after a safe caster line.

        This is RFC-style witty duo commentary: the caster reports the safe
        screen state, then the analyst answers with a short, immediately
        understandable line.  It never runs on danger calls, knockdowns, stuns,
        TKO/KO, break summaries, or when another follow-up is already reserved.
        """
        try:
            if str(state or "").lower() != "fight":
                return
            if "commentary_tts_followup_text" in out or "commentary_tts_followups" in out:
                return
            role = str(out.get("commentary_tts_role") or "").lower().strip()
            text = str(out.get("commentary_tts_text") or "").strip()
            if role != "caster" or not text:
                return
            tag = self._witty_duo_tag_from_text(text)
            if not tag:
                return
            follow = self._witty_duo_line(tag, round_no=round_no)
            if not follow:
                return
            out["commentary_tts_followup_text"] = follow
            out["commentary_tts_followup_role"] = "analyst"
            out["commentary_tts_followup_delay_ms"] = 1050
            out["commentary_tts_followup_retries"] = 2
            logging.info("SPECTATORLOG_WITTY_DUO tag=%s primary=%s follow=%s", tag, text, follow)
        except Exception:
            logging.exception("SPECTATORLOG_WITTY_DUO_FAIL")

    def _event_names(self, ev: dict) -> Tuple[str, str, str, str]:
        receiver_side = str((ev or {}).get("receiver_side") or "").lower()
        if receiver_side not in ("blue", "red"):
            receiver_side = "blue"
        attacker_side = str((ev or {}).get("attacker_side") or "").lower()
        if attacker_side not in ("blue", "red"):
            attacker_side = "red" if receiver_side == "blue" else "blue"
        return attacker_side, receiver_side, self._commentary_name(attacker_side), self._commentary_name(receiver_side)

    def _build_big_hit_line(self, ev: dict, attacker: str, receiver: str) -> str:
        weak = self._weak_point_ko(str((ev or {}).get("weak_point", "") or ""))
        punch = self._punch_ko(str((ev or {}).get("punch", "") or ""))
        key = f"big:{attacker}:{receiver}:{weak}:{punch}:{(ev or {}).get('time','')}"
        if weak == "턱":
            return self._commentary_pick(key, [
                "턱 쪽 충격이 컸습니다.",
                "턱에 정확하게 들어갔습니다.",
                "정타 허용이 큽니다.",
                "중심이 흔들릴 수 있는 정타였습니다.",
            ])
        if weak in ("간", "복부", "명치"):
            return self._commentary_pick(key, [
                "바디에 제대로 들어갔습니다.",
                "바디 충격이 큽니다.",
                "몸통 쪽 데미지가 큽니다.",
                "간과 명치 쪽 정타가 부담으로 남습니다.",
            ])
        if "관자놀이" in weak:
            return self._commentary_pick(key, [
                "관자놀이 쪽 충격이 큽니다.",
                "머리 쪽 데미지가 큽니다.",
                "순간적으로 균형이 흔들립니다.",
                "측면 정타가 위험하게 들어갑니다.",
            ])
        if weak in ("코",):
            return self._commentary_pick(key, [
                "얼굴 쪽 정타를 허용합니다.",
                "얼굴 쪽 데미지가 쌓입니다.",
                "정면 방어가 조금 늦었습니다.",
            ])
        # Do not say awkward lines like '큰 잽'.  Jabs are usually read as timing
        # and connection, while hooks/crosses/overhands are read as power shots.
        if punch in ("잽", "와이드 잽", "바디 잽"):
            return self._commentary_pick(key, [
                "잽 타이밍이 좋았습니다.",
                "앞손이 정확하게 들어갑니다.",
                "잽으로 정타를 만들어냅니다.",
                "거리 싸움에서 앞손이 살아납니다.",
                "앞손이 오늘 바쁩니다.",
                "잽으로 간 봅니다.",
            ])
        if punch in ("스트레이트", "크로스", "와이드 스트레이트", "와이드 크로스"):
            return self._commentary_pick(key, [
                "직선 타격이 정확하게 들어갑니다.",
                "스트레이트 계열 정타가 좋았습니다.",
                "정면으로 강하게 들어갔습니다.",
                "타이밍 맞춘 직선 타격입니다.",
            ])
        if punch in ("훅", "리드 훅", "리어 훅"):
            return self._commentary_pick(key, [
                "훅이 크게 들어갑니다.",
                "각도 있는 타격이 좋았습니다.",
                "측면에서 정타가 나옵니다.",
                "훅 타이밍이 정확했습니다.",
            ])
        if punch in ("어퍼컷", "리드 어퍼컷"):
            return self._commentary_pick(key, [
                "어퍼컷이 올라갑니다.",
                "가드 사이로 타격이 들어갑니다.",
                "짧은 거리에서 정타를 만듭니다.",
            ])
        if punch in ("오버핸드", "리드 오버핸드", "리어 오버핸드"):
            return self._commentary_pick(key, [
                "오버핸드가 크게 들어갑니다.",
                "위에서 찍는 타격이 좋았습니다.",
                "큰 궤도의 정타가 들어갑니다.",
            ])
        return self._commentary_pick(key, [
            "큰 타격이 들어갑니다.",
            "데미지가 큽니다.",
            "한 방 한 방의 데미지가 큽니다.",
            "강하게 들어갔습니다.",
            "정타를 만들어냅니다.",
            "한 방의 충격이 큽니다.",
        ])

    def _build_weak_accumulation_line(self, recent: List[dict]) -> str:
        if not recent:
            return ""
        now = time.time()
        buckets: Dict[Tuple[str, str], Dict[str, float]] = {}
        for ev in list(recent or []):
            try:
                if now - float(ev.get("seen_at", now) or now) > 18.0:
                    continue
                dmg = float(ev.get("damage", 0.0) or 0.0)
            except Exception:
                dmg = 0.0
            weak = self._weak_point_ko(str(ev.get("weak_point") or ""))
            recv = str(ev.get("receiver_side") or "").lower()
            if not weak or recv not in ("blue", "red"):
                continue
            key = (recv, weak)
            item = buckets.setdefault(key, {"count": 0.0, "damage": 0.0})
            item["count"] += 1.0
            item["damage"] += dmg
        if not buckets:
            return ""
        def score(kv):
            (_recv, weak), item = kv
            weight = 1.3 if (weak in ("턱", "간", "복부", "명치") or "관자놀이" in weak) else 1.0
            return float(item.get("count", 0.0)) * 20.0 * weight + float(item.get("damage", 0.0))
        (recv, weak), item = max(buckets.items(), key=score)
        cnt = int(item.get("count", 0.0) or 0)
        dmg = float(item.get("damage", 0.0) or 0.0)
        recv_name = self._commentary_name(recv)
        if weak == "턱" and (cnt >= 2 or dmg >= 70.0):
            return self._commentary_pick("weak_chin:%s:%s:%s" % (recv, cnt, int(dmg)), [
                f"{recv_name} 턱 쪽 정타가 반복되고 있습니다.",
                f"{recv_name} 쪽 턱 충격이 계속 쌓입니다.",
                "위험한 정타 허용이 반복됩니다.",
                f"{self._josa(recv_name, '은/는')} 머리 중심선 방어가 늦고 있습니다.",
            ])
        if weak in ("간", "복부", "명치") and (cnt >= 2 or dmg >= 65.0):
            return self._commentary_pick("weak_body:%s:%s:%s" % (recv, cnt, int(dmg)), [
                f"{recv_name}에게 바디 데미지가 쌓이고 있습니다.",
                f"{recv_name} 쪽 몸통 충격이 계속 쌓입니다.",
                "바디 방어가 점점 중요해집니다.",
                "바디 쪽 데미지가 부담으로 남습니다.",
            ])
        if "관자놀이" in weak and (cnt >= 2 or dmg >= 65.0):
            return self._commentary_pick("weak_head:%s:%s:%s" % (recv, cnt, int(dmg)), [
                f"{recv_name} 머리 쪽 충격이 쌓입니다.",
                f"{recv_name} 관자놀이 쪽 정타가 반복됩니다.",
                "균형을 흔드는 타격이 계속 나옵니다.",
            ])
        if weak == "코" and (cnt >= 3 or dmg >= 75.0):
            return self._commentary_pick("weak_face:%s:%s:%s" % (recv, cnt, int(dmg)), [
                f"{recv_name} 얼굴 쪽 데미지가 계속 쌓입니다.",
                f"{recv_name}의 정면 방어가 조금씩 늦어지고 있습니다.",
                "얼굴 쪽 정타 허용이 많아집니다.",
            ])
        return ""

    def _build_idle_fight_commentary(self, damage_path: str, elapsed: Optional[float], round_no: Optional[int]) -> Tuple[str, str]:
        """Fill no-hit stretches with role-aware broadcast commentary.

        Best policy:
        - short quiet stretches are left silent,
        - medium quiet stretches are caster flow calls,
        - long quiet stretches or risky recovery moments are analyst comments,
        - late-round quiet stretches stay with the caster because they are time/flow calls.
        """
        if not bool(getattr(self.cfg, "spectator_commentary_enabled", False)):
            return "", ""
        mode = str(getattr(self.cfg, "spectator_commentary_mode", "standard") or "standard").lower().strip()
        if mode == "quiet":
            return "", ""
        now = time.time()
        try:
            base_cd = 8.0 if mode == "active" else 12.0
            medium_need = 6.0 if mode == "active" else 9.0
            long_need = 14.0 if mode == "active" else 18.0
            opening_grace = 8.0 if mode == "active" else 11.0
        except Exception:
            base_cd, medium_need, long_need, opening_grace = 12.0, 9.0, 18.0, 11.0
        if now - float(getattr(self, "_last_idle_commentary_at", 0.0) or 0.0) < base_cd:
            return "", ""
        if now - float(getattr(self, "_commentary_last_at", 0.0) or 0.0) < max(4.0, base_cd * 0.55):
            return "", ""
        fight_started_at = float(getattr(self, "_last_fight_state_started_at", 0.0) or 0.0)
        if fight_started_at and now - fight_started_at < opening_grace:
            return "", ""
        last_hit_at = float(getattr(self, "_last_damage_seen_at", 0.0) or 0.0)
        if last_hit_at <= 0.0:
            return "", ""
        silence_for = now - last_hit_at
        if silence_for < medium_need:
            return "", ""

        snap = self._punishment_snapshot(damage_path)
        self._remember_punishment_snapshot(snap)
        blue_lost = self._clamp_percent((snap.get("blue") or {}).get("lost_pct", 0.0))
        red_lost = self._clamp_percent((snap.get("red") or {}).get("lost_pct", 0.0))
        worst = "blue" if blue_lost >= red_lost else "red"
        worst_lost = max(blue_lost, red_lost)
        delta = self._punishment_delta(worst, 20.0)
        delta_loss = self._clamp_percent(delta.get("lost_delta", 0.0))

        recent = [e for e in list(self._recent_damage_events) if now - float(e.get("seen_at", now) or now) <= 35.0]
        recent_by_attacker = {"blue": 0.0, "red": 0.0}
        for ev in recent:
            att = str(ev.get("attacker_side") or "").lower()
            if att in recent_by_attacker:
                try:
                    recent_by_attacker[att] += float(ev.get("damage", 0.0) or 0.0)
                except Exception:
                    pass
        flow_side = "blue" if recent_by_attacker["blue"] >= recent_by_attacker["red"] else "red"
        flow_gap = abs(recent_by_attacker["blue"] - recent_by_attacker["red"])

        try:
            seconds_left = float(elapsed) if elapsed is not None else None
        except Exception:
            seconds_left = None

        # Late-round quiet stretches are a caster job: time pressure and final-entry framing.
        if seconds_left is not None and seconds_left <= 25.0:
            text = self._commentary_pick(f"idle-late-caster:{int(seconds_left)}:{int(round_no or 0)}", [
                "라운드 막판입니다.",
                "남은 시간이 많지 않습니다.",
                "마지막 교전이 중요합니다.",
                "여기서 한 방이면 인상이 바뀝니다.",
                "막판입니다, 한 방 조심해야 합니다.",
            ])
            return (text, "caster") if text else ("", "")

        # Long quiet stretches with real damage/gauge context are analyst comments.
        if silence_for >= long_need and (worst_lost >= 55.0 or delta_loss >= 8.0):
            text = self._commentary_pick(f"idle-gauge-analyst:{worst}:{int(worst_lost)}:{int(delta_loss)}:{int(round_no or 0)}", [
                "이 구간은 회복 시간을 어떻게 쓰느냐가 중요합니다.",
                "정타가 잠시 끊긴 만큼, 호흡을 다시 잡아야 합니다.",
                "데미지 부담이 있는 쪽은 무리한 진입을 피해야 합니다.",
                "지금 같은 공백에서는 수비 안정이 먼저입니다.",
                "잠깐의 소강상태지만, 체력 회복에는 중요한 시간입니다.",
            ])
            return (text, "analyst") if text else ("", "")

        # Long quiet stretches after a clearly one-sided exchange get short analyst framing.
        if silence_for >= long_need and flow_gap >= 55.0:
            text = self._commentary_pick(f"idle-flow-analyst:{flow_side}:{int(flow_gap)}:{int(round_no or 0)}", [
                "방금 전 교전 이후 흐름을 다시 정리하는 구간입니다.",
                "앞선 교전의 인상이 남아 있는 상황입니다.",
                "지금은 무리한 진입보다 다음 정타 타이밍이 중요합니다.",
                "이런 공백에서는 먼저 들어가는 쪽이 리스크를 안을 수 있습니다.",
            ])
            return (text, "analyst") if text else ("", "")

        # Very long neutral silence: analyst gives the reason, not just the screen state.
        if silence_for >= max(long_need + 4.0, 20.0):
            text = self._commentary_pick(f"idle-long-analyst:{int(silence_for)}:{int(round_no or 0)}", [
                "이 구간은 거리 조절이 중요합니다.",
                "무리하게 들어가면 카운터 위험이 있습니다.",
                "서로 먼저 실수하지 않으려는 흐름입니다.",
                "지금은 첫 진입보다 이후 수비 반응이 중요합니다.",
            ])
            return (text, "analyst") if text else ("", "")

        # Medium no-hit stretches are caster filler: short, factual, and broadcast-like.
        text = self._commentary_pick(f"idle-neutral-caster:{int(now // 7)}:{int(round_no or 0)}", [
            "잠시 소강상태입니다.",
            "서로 타이밍을 봅니다.",
            "아직 아무도 안 들어갑니다.",
            "거리 싸움이 이어집니다.",
            "정타가 잠시 끊겼습니다.",
            "눈치게임입니다.",
            "서로 간만 봅니다.",
            "잠깐 멈췄습니다.",
        ])
        return (text, "caster") if text else ("", "")

    def _build_fight_summary_commentary(self, new_events: List[dict], effect_events: List[dict], damage_path: str, punishment_snapshot: Optional[Dict[str, Dict[str, float]]] = None) -> Tuple[str, str]:
        if not bool(getattr(self.cfg, "spectator_commentary_enabled", False)):
            return "", ""
        if effect_events:
            last = effect_events[-1] or {}
            kind = str(last.get("kind") or "")
            side = str(last.get("side") or "")
            name = self._caster_name(side)
            if kind == "tko":
                return self._commentary_pick(f"tko:{side}", [
                    f"{name}, 테크니컬 녹아웃입니다!",
                    "심판이 경기를 멈춥니다!",
                    "경기가 끝납니다!",
                ]), "caster"
            if kind == "knockdown":
                return self._commentary_pick(f"kd:{side}", [
                    f"{name}, 다운 당합니다!",
                    f"{name}, 쓰러집니다!",
                    f"{name}, 큰 타격에 무너집니다!",
                ]), "caster"
            if kind == "stun":
                return self._commentary_pick(f"stun:{side}", [
                    f"{name}, 크게 흔들립니다!",
                    f"{name}, 위험합니다!",
                    f"{name}, 충격이 큽니다!",
                ]), "caster"

        mode = str(getattr(self.cfg, "spectator_commentary_mode", "standard") or "standard").lower()
        if mode not in ("quiet", "standard", "active"):
            mode = "standard"
        if mode == "quiet" or not new_events:
            return "", ""

        now = time.time()
        recent = [e for e in list(self._recent_damage_events) if now - float(e.get("seen_at", now) or now) <= 3.0]
        if not recent:
            recent = list(new_events)
        try:
            min_damage = float(getattr(self.cfg, "spectator_commentary_min_damage", 25.0) or 25.0)
        except Exception:
            min_damage = 25.0
        big_threshold = 42.0 if mode == "active" else 48.0
        big_threshold = max(big_threshold, min_damage if mode == "active" else min_damage + 8.0)
        pressure_threshold = 65.0 if mode == "active" else 75.0
        pressure_count_threshold = 3

        # Special damage types on the event itself are treated as caster events, even if the
        # separate effect counter path did not fire in this poll.
        special_events = [e for e in list(new_events or []) if str(e.get("effect_kind") or "") in ("tko", "knockdown", "stun")]
        if special_events:
            ev = special_events[-1]
            kind = str(ev.get("effect_kind") or "")
            _att_side, recv_side, _attacker, _receiver = self._event_names(ev)
            name = self._caster_name(recv_side)
            if kind == "tko":
                return f"{name}, 테크니컬 녹아웃입니다!", "caster"
            if kind == "knockdown":
                return self._commentary_pick(f"kd-event:{recv_side}:{ev.get('time','')}", [
                    f"{name}, 다운 당합니다!",
                    f"{name}, 쓰러집니다!",
                    f"{name}, 큰 타격에 무너집니다!",
                ]), "caster"
            if kind == "stun":
                return self._commentary_pick(f"stun-event:{recv_side}:{ev.get('time','')}", [
                    f"{name}, 크게 흔들립니다!",
                    f"{name}, 위험합니다!",
                    f"{name}, 충격이 큽니다!",
                ]), "caster"

        by_pair: Dict[Tuple[str, str], Dict[str, float]] = {}
        by_attacker = {"blue": {"damage": 0.0, "count": 0}, "red": {"damage": 0.0, "count": 0}}
        for ev in recent:
            attacker = str(ev.get("attacker_side") or "").lower()
            receiver = str(ev.get("receiver_side") or "").lower()
            if attacker in ("blue", "red"):
                by_attacker[attacker]["damage"] += float(ev.get("damage", 0.0) or 0.0)
                by_attacker[attacker]["count"] += 1
            if attacker in ("blue", "red") and receiver in ("blue", "red"):
                item = by_pair.setdefault((attacker, receiver), {"damage": 0.0, "count": 0})
                dmg = float(ev.get("damage", 0.0) or 0.0)
                if dmg >= 12.0:
                    item["damage"] += dmg
                    item["count"] += 1

        punishment_snapshot = punishment_snapshot or self._punishment_snapshot(damage_path)

        # Gauge-aware danger must outrank ordinary pressure/weak-point narration.
        # This keeps lines like '체력 부담' tied to the actual HP bar / punishment gauge.
        pair_items = sorted(
            list(by_pair.items()),
            key=lambda kv: self._gauge_risk_score(kv[0][1], punishment_snapshot, recent_damage=float(kv[1].get("damage", 0.0) or 0.0)) + float(kv[1].get("damage", 0.0) or 0.0) * 0.15,
            reverse=True,
        )
        for (att_side, recv_side), item in pair_items:
            health_line = self._health_pressure_line(recv_side, punishment_snapshot, recent_damage=float(item.get("damage", 0.0) or 0.0))
            if health_line:
                return health_line, "analyst"

        # Repeated weak-point hits sound more natural as cumulative analysis, not every single hit.
        weak_line = self._build_weak_accumulation_line(recent)
        if weak_line:
            return weak_line, "analyst"

        # Big shots come before generic pressure.  A single clean power shot should not be
        # buried under a vague 'pressure' line.
        max_ev = max(list(new_events or recent), key=lambda e: float(e.get("damage", 0.0) or 0.0))
        max_damage = float(max_ev.get("damage", 0.0) or 0.0)
        if max_damage >= big_threshold:
            _att_side, _recv_side, attacker, receiver = self._event_names(max_ev)
            return self._build_big_hit_line(max_ev, attacker, receiver), "analyst"

        # Pressure / cumulative damage commentary without overclaiming health loss.
        for (att_side, recv_side), item in pair_items:
            dmg_total = float(item.get("damage", 0.0) or 0.0)
            hit_count = int(item.get("count", 0) or 0)
            if dmg_total >= pressure_threshold or (hit_count >= pressure_count_threshold and dmg_total >= 60.0):
                return self._commentary_pick(f"pressure:{att_side}:{recv_side}:{int(dmg_total)}", [
                    "압박이 계속됩니다.",
                    "정타가 이어지고 있습니다.",
                    "공격 주도권을 잡고 있습니다.",
                    "수비 반응이 조금씩 늦어지고 있습니다.",
                    "정타 허용이 많아지고 있습니다.",
                    "공격 흐름이 끊기지 않습니다.",
                    "무리하게 맞불을 놓기 어려운 흐름입니다.",
                    "거리 싸움에서 조금씩 밀리고 있습니다.",
                    "첫 타 이후 수비 복귀가 중요합니다.",
                    "수비가 바빠집니다.",
                    "이러면 피곤합니다.",
                ]), "analyst"
        return "", ""

    def _estimate_commentary_tts_seconds(self, text: str) -> float:
        """Conservative Korean TTS duration estimate used to fit break recaps."""
        raw = str(text or "").strip()
        if not raw:
            return 0.0
        try:
            rate = int(getattr(self.cfg, "spectator_commentary_rate", 200) or 200)
        except Exception:
            rate = 200
        rate_factor = max(0.75, min(1.55, float(rate) / 200.0))
        compact = re.sub(r"\s+", "", raw)
        char_count = max(1, len(compact))
        pause_count = raw.count(".") + raw.count("!") + raw.count("?") + raw.count(",")
        return 1.15 + (char_count / (8.2 * rate_factor)) + min(1.8, pause_count * 0.18)

    def _round_break_summary_budget_seconds(self, break_seconds_left: Optional[float], mode: str) -> float:
        """Return safe analyst recap budget so it ends before the next round."""
        try:
            remaining = float(break_seconds_left) if break_seconds_left is not None else 0.0
        except Exception:
            remaining = 0.0
        if remaining <= 0.0:
            try:
                remaining = float(getattr(self.cfg, "timer_rest_sec", 40) or 40)
            except Exception:
                remaining = 40.0
        # The recap normally starts after the caster break line. Leave a buffer
        # for the next-round intro and timing drift.
        safety = 6.0
        # The summary is queued 2.4 seconds after the break caster line when
        # both are emitted in the same watcher update.
        caster_delay = 2.8
        budget = max(8.0, remaining - safety - caster_delay)
        if str(mode or "").lower().strip() == "quiet":
            return min(18.0, budget)
        if str(mode or "").lower().strip() == "active":
            return min(48.0, budget)
        return min(44.0, budget)

    def _select_commentary_lines_for_budget(self, lines: List[str], budget_sec: float, *, min_lines: int = 2, max_lines: int = 10) -> List[str]:
        selected: List[str] = []
        used = 0.0
        budget = max(5.0, float(budget_sec or 0.0))
        for raw in list(lines or []):
            line = str(raw or "").strip()
            if not line:
                continue
            est = self._estimate_commentary_tts_seconds(line)
            if selected and used + est > budget and len(selected) >= min_lines:
                break
            if len(selected) >= max_lines:
                break
            selected.append(line)
            used += est
            if used >= budget and len(selected) >= min_lines:
                break
        return selected

    def _build_round_break_summary(self, damage_path: str, round_no: Optional[int], pair_key: Tuple[str, str], break_seconds_left: Optional[float] = None) -> str:
        """Build a rest-time broadcast recap with pattern-based structure.

        Rest-time commentary is intentionally longer than live hit commentary.
        The recap uses the round damage log, special events, gauge context,
        weak-point accumulation, late-round momentum, and a next-round point.
        The order is varied by situation so each break does not sound like the
        same template repeated every round.
        """
        if not bool(getattr(self.cfg, "spectator_commentary_enabled", False)):
            return ""
        events, _effect_counts = self._scan_damage_file_for_session_reset(damage_path)
        if not events:
            return ""
        try:
            r = int(round_no or 0)
        except Exception:
            r = 0
        sig = self._file_sig(damage_path)
        summary_key = (r, str(pair_key or ""), f"{sig[0]}:{sig[1]}")
        if summary_key == self._last_round_summary_key:
            return ""
        self._last_round_summary_key = summary_key

        try:
            mode = str(getattr(self.cfg, "spectator_commentary_mode", "standard") or "standard").lower().strip()
        except Exception:
            mode = "standard"
        punishment_snapshot = self._punishment_snapshot(damage_path)
        self._remember_punishment_snapshot(punishment_snapshot)

        dealt = {"blue": 0.0, "red": 0.0}
        hit_count = {"blue": 0, "red": 0}
        big_count = {"blue": 0, "red": 0}
        knockdowns: List[dict] = []
        tkos: List[dict] = []
        stuns: List[dict] = []
        weak_counts: Dict[Tuple[str, str], Dict[str, float]] = {}
        report_landed = {"blue": 0, "red": 0}
        report_punches: Dict[str, Dict[str, Dict[str, float]]] = {"blue": {}, "red": {}}
        max_event: Optional[dict] = None

        for ev in list(events or []):
            attacker = str(ev.get("attacker_side") or "").lower()
            receiver = str(ev.get("receiver_side") or "").lower()
            if attacker not in ("blue", "red") or receiver not in ("blue", "red"):
                continue
            try:
                dmg = float(ev.get("damage", 0.0) or 0.0)
            except Exception:
                dmg = 0.0
            dealt[attacker] += dmg
            report_landed[attacker] = int(report_landed.get(attacker, 0) or 0) + 1
            pkey, plabel = self._punch_report_group(str(ev.get("punch") or ""))
            pitem = report_punches.setdefault(attacker, {}).setdefault(pkey, {"label": plabel, "count": 0.0, "damage": 0.0})
            pitem["count"] = float(pitem.get("count", 0.0) or 0.0) + 1.0
            pitem["damage"] = float(pitem.get("damage", 0.0) or 0.0) + max(0.0, dmg)
            if dmg >= 12.0:
                hit_count[attacker] += 1
            if dmg >= 45.0:
                big_count[attacker] += 1
            if max_event is None or dmg > float(max_event.get("damage", 0.0) or 0.0):
                max_event = ev
            kind = self._damage_effect_kind(str(ev.get("damage_type") or ""))
            if kind == "tko":
                tkos.append(ev)
            elif kind == "knockdown":
                knockdowns.append(ev)
            elif kind == "stun":
                stuns.append(ev)
            weak = self._weak_point_ko(str(ev.get("weak_point") or ""))
            if weak:
                item = weak_counts.setdefault((receiver, weak), {"count": 0.0, "damage": 0.0})
                item["count"] += 1.0
                item["damage"] += dmg

        blue_dmg = float(dealt.get("blue", 0.0) or 0.0)
        red_dmg = float(dealt.get("red", 0.0) or 0.0)
        kd_for = {"blue": 0, "red": 0}
        tko_for = {"blue": 0, "red": 0}
        stun_for = {"blue": 0, "red": 0}
        for ev in knockdowns:
            att = str((ev or {}).get("attacker_side") or "").lower()
            if att in kd_for:
                kd_for[att] += 1
        for ev in tkos:
            att = str((ev or {}).get("attacker_side") or "").lower()
            if att in tko_for:
                tko_for[att] += 1
        for ev in stuns:
            att = str((ev or {}).get("attacker_side") or "").lower()
            if att in stun_for:
                stun_for[att] += 1

        if tko_for["blue"] != tko_for["red"]:
            leader = "blue" if tko_for["blue"] > tko_for["red"] else "red"
        elif kd_for["blue"] != kd_for["red"]:
            leader = "blue" if kd_for["blue"] > kd_for["red"] else "red"
        elif blue_dmg != red_dmg:
            leader = "blue" if blue_dmg >= red_dmg else "red"
        elif report_landed["blue"] != report_landed["red"]:
            leader = "blue" if report_landed["blue"] >= report_landed["red"] else "red"
        elif stun_for["blue"] != stun_for["red"]:
            leader = "blue" if stun_for["blue"] >= stun_for["red"] else "red"
        else:
            leader = "blue"
        other = "red" if leader == "blue" else "blue"
        leader_dmg = float(dealt.get(leader, 0.0) or 0.0)
        other_dmg = float(dealt.get(other, 0.0) or 0.0)
        damage_gap = leader_dmg - other_dmg
        leader_name = self._commentary_name(leader)
        other_name = self._commentary_name(other)
        leader_neun = self._josa(leader_name, "은/는")
        leader_ga = self._josa(leader_name, "이/가")
        leader_wa = self._josa(leader_name, "와/과")
        other_neun = self._josa(other_name, "은/는")
        other_ga = self._josa(other_name, "이/가")

        # Last stretch: the log uses remaining time, so smaller values are later in the round.
        try:
            min_time = min(float(e.get("time", 0.0) or 0.0) for e in events)
        except Exception:
            min_time = 0.0
        late_cut = min_time + 30.0
        late_dealt = {"blue": 0.0, "red": 0.0}
        late_hits = {"blue": 0, "red": 0}
        for ev in list(events or []):
            try:
                t = float(ev.get("time", 0.0) or 0.0)
                dmg = float(ev.get("damage", 0.0) or 0.0)
            except Exception:
                continue
            if t <= late_cut:
                attacker = str(ev.get("attacker_side") or "").lower()
                if attacker in late_dealt:
                    late_dealt[attacker] += dmg
                    if dmg >= 12.0:
                        late_hits[attacker] += 1
        late_leader = "blue" if late_dealt["blue"] >= late_dealt["red"] else "red"
        late_other = "red" if late_leader == "blue" else "blue"
        late_gap = late_dealt[late_leader] - late_dealt[late_other]

        # Most meaningful weak-point trend in this round.
        best_weak: Optional[Tuple[str, str, Dict[str, float]]] = None
        if weak_counts:
            (recv_side, weak), item = max(
                weak_counts.items(),
                key=lambda kv: float(kv[1].get("count", 0.0)) * 22.0 + float(kv[1].get("damage", 0.0)),
            )
            best_weak = (recv_side, weak, item)

        round_label = f"{r}라운드" if r > 0 else "이번 라운드"
        key_base = f"round-summary-pattern:{r}:{summary_key[2]}"
        local_used: set = set()

        def pick(suffix: str, candidates: List[str]) -> str:
            items = [str(x or "").strip() for x in list(candidates or []) if str(x or "").strip()]
            pool = [x for x in items if x not in local_used]
            if not pool:
                pool = items
            if not pool:
                return ""
            try:
                seed = sum(ord(ch) for ch in f"{key_base}:{suffix}") + len(local_used) * 19
                chosen = pool[abs(seed) % len(pool)]
            except Exception:
                chosen = pool[0]
            local_used.add(chosen)
            return chosen

        def gauge_line() -> str:
            return self._round_gauge_context_line(punishment_snapshot, leader, other, pick)

        def weak_line() -> str:
            if not best_weak:
                return ""
            _recv_side, weak, item = best_weak
            cnt = int(item.get("count", 0.0) or 0)
            dmg = float(item.get("damage", 0.0) or 0.0)
            if (weak == "턱" or "관자놀이" in weak) and (cnt >= 2 or dmg >= 80.0):
                return pick("weak-head-report", [
                    "머리 쪽 정타가 반복됐기 때문에, 다음 라운드에는 들어오는 순간의 가드 위치가 중요합니다.",
                    "턱과 머리 쪽 충격이 쌓이면 작은 정타에도 균형이 흔들릴 수 있습니다.",
                    "상단 정타가 반복된 만큼, 다음 라운드에는 진입 타이밍과 수비 복귀를 더 조심해야 합니다.",
                ])
            if weak in ("간", "복부", "명치") and (cnt >= 2 or dmg >= 70.0):
                return pick("weak-body-report", [
                    "바디 데미지가 쌓이면 후반 움직임과 호흡에 부담이 커질 수 있습니다.",
                    "몸통 쪽 충격은 바로 드러나지 않아도 다음 라운드 움직임에 영향을 줄 수 있습니다.",
                    "바디 쪽 정타가 있었기 때문에, 다음 라운드에는 거리 유지와 카운터 대응이 중요합니다.",
                ])
            if weak in ("코", "얼굴") and cnt >= 3:
                return pick("weak-face-report", [
                    "얼굴 쪽 정타 허용이 많아지면 시야와 반응 모두에 부담이 생길 수 있습니다.",
                    "정면 방어에서 부담이 쌓였고, 앞손과 직선 타격 대응이 중요해졌습니다.",
                    "얼굴 쪽 데미지가 계속 쌓이면 라운드 후반 집중력에도 영향을 줄 수 있습니다.",
                ])
            return ""

        def _top_report_punch(side: str) -> Tuple[str, int, float]:
            items = list((report_punches.get(side) or {}).values())
            items = [it for it in items if float(it.get("count", 0.0) or 0.0) > 0]
            if not items:
                return "", 0, 0.0
            best = max(items, key=lambda it: (float(it.get("count", 0.0) or 0.0), float(it.get("damage", 0.0) or 0.0)))
            return str(best.get("label") or "").strip(), int(best.get("count", 0.0) or 0), float(best.get("damage", 0.0) or 0.0)

        def _top_received_weak(side: str) -> Tuple[str, int, float]:
            items: List[Tuple[str, Dict[str, float]]] = []
            for (recv_side, weak), item in weak_counts.items():
                if recv_side == side:
                    items.append((weak, item))
            if not items:
                return "", 0, 0.0
            weak, item = max(items, key=lambda kv: (float(kv[1].get("damage", 0.0) or 0.0), float(kv[1].get("count", 0.0) or 0.0)))
            return str(weak or "").strip(), int(item.get("count", 0.0) or 0), float(item.get("damage", 0.0) or 0.0)

        def section_report_numbers() -> str:
            leader_hits = int(report_landed.get(leader, 0) or 0)
            other_hits = int(report_landed.get(other, 0) or 0)
            if leader_hits <= 0 and other_hits <= 0:
                return ""
            if tkos:
                return pick("report-numbers-tko", [
                    f"수치보다 결정적인 건 TKO 장면이었고, {leader_neun} 라운드 인상을 확실히 가져갔습니다.",
                    f"리포트상 적중은 {leader_name} {leader_hits}회, {other_name} {other_hits}회였지만, 승부를 가른 장면은 TKO였습니다.",
                    "이번 라운드는 단순 적중 수보다 스톱 장면의 비중이 훨씬 컸습니다.",
                ])
            if knockdowns and kd_for.get(leader, 0) > kd_for.get(other, 0):
                return pick("report-numbers-kd", [
                    f"리포트상 적중은 {leader_name} {leader_hits}회, {other_name} {other_hits}회였고, 다운 장면이 라운드 인상을 갈랐습니다.",
                    f"수치 흐름보다 크게 남은 건 {leader_name} 쪽에서 만든 다운 장면입니다.",
                ])
            if damage_gap >= 25.0 or abs(leader_hits - other_hits) >= 5:
                return pick("report-numbers-clear", [
                    f"리포트 기준으로 {leader_neun} 적중 {leader_hits}회, 데미지 {int(round(leader_dmg))}으로 앞섰습니다.",
                    f"화면에 나온 수치도 {leader_name} 쪽 우세를 보여줍니다. 적중 {leader_hits}회, 데미지 {int(round(leader_dmg))}입니다.",
                    f"적중과 데미지 모두 {leader_name} 쪽이 더 선명했습니다. 리포트상 적중은 {leader_hits}회입니다.",
                ])
            return pick("report-numbers-close", [
                f"리포트상 적중은 {leader_name} {leader_hits}회, {other_name} {other_hits}회로 큰 차이는 아니었습니다.",
                f"수치만 봐도 접전입니다. 적중은 {leader_name} {leader_hits}회, {other_name} {other_hits}회입니다.",
            ])

        def section_report_detail() -> str:
            punch_label, punch_count, _punch_damage = _top_report_punch(leader)
            weak_label, weak_count, weak_damage = _top_received_weak(other)
            if punch_label and weak_label and (weak_count >= 2 or weak_damage >= 45.0):
                return pick("report-detail-punch-weak", [
                    f"{leader_neun} {punch_label} 적중이 많았고, {other_neun} {weak_label} 쪽 데미지가 쌓였습니다.",
                    f"주력 적중은 {punch_label} 쪽이었고, {other_name}에게는 {weak_label} 피격이 눈에 띄었습니다.",
                    f"카드에 잡힌 핵심은 {punch_label} 적중과 {weak_label} 쪽 피격입니다.",
                ])
            if punch_label and punch_count >= 2:
                return pick("report-detail-punch", [
                    f"펀치 타입으로 보면 {leader_neun} {punch_label} 적중이 가장 많이 잡혔습니다.",
                    f"이번 라운드 주력 적중은 {punch_label} 쪽이었습니다.",
                ])
            if weak_label and (weak_count >= 2 or weak_damage >= 45.0):
                return pick("report-detail-weak", [
                    f"부위별로는 {other_name}의 {weak_label} 쪽 피격이 눈에 띄었습니다.",
                    f"{other_neun} {weak_label} 쪽 데미지를 조심해야 합니다.",
                ])
            return ""

        def section_open() -> str:
            if tkos:
                tko = tkos[-1] or {}
                stopped_name = self._commentary_name(str(tko.get("receiver_side") or ""))
                finisher_name = self._commentary_name(str(tko.get("attacker_side") or ""))
                return pick("open-tko-pattern", [
                    f"{round_label}는 {self._josa(finisher_name, '이/가')} TKO 장면까지 만든 결정적인 라운드였습니다.",
                    f"{round_label}를 정리하면, {self._josa(stopped_name, '이/가')} 더 버티기 어려웠던 장면이 핵심입니다.",
                    f"{round_label}는 TKO 장면 하나로 라운드 인상이 확실하게 갈렸습니다.",
                ])
            if knockdowns:
                kd = knockdowns[-1] or {}
                downed_name = self._commentary_name(str(kd.get("receiver_side") or ""))
                attacker_name = self._commentary_name(str(kd.get("attacker_side") or ""))
                return pick("open-kd-pattern", [
                    f"{round_label}는 {downed_name}의 다운 장면 하나가 전체 흐름을 바꾼 라운드였습니다.",
                    f"{round_label}를 정리하면, 가장 먼저 봐야 할 장면은 {self._josa(attacker_name, '이/가')} 만든 다운 장면입니다.",
                    f"{round_label}는 {self._josa(downed_name, '이/가')} 크게 흔들린 장면이 라운드 인상을 강하게 남겼습니다.",
                ])
            if stuns:
                stun = stuns[-1] or {}
                stunned_name = self._commentary_name(str(stun.get("receiver_side") or ""))
                attacker_name = self._commentary_name(str(stun.get("attacker_side") or ""))
                return pick("open-stun-pattern", [
                    f"{round_label}는 {self._josa(stunned_name, '이/가')} 크게 흔들리면서 긴장감이 올라간 라운드였습니다.",
                    f"{round_label}를 정리하면, {attacker_name}의 위험한 정타 이후 대응이 핵심이었습니다.",
                    f"{round_label}는 {stunned_name}에게 한 차례 큰 위기가 있었고, 그 이후 흐름이 중요했습니다.",
                ])
            if damage_gap >= 30.0 and leader_dmg >= max(1.0, other_dmg) * 1.2:
                return pick("open-leader-pattern", [
                    f"{round_label}는 {leader_name} 쪽이 유효타 흐름에서 조금 더 앞섰습니다.",
                    f"{round_label}는 {leader_name} 쪽 공격이 더 선명하게 들어간 라운드였습니다.",
                    f"{round_label}는 정타의 질에서 차이가 난 라운드였습니다.",
                ])
            return pick("open-close-pattern", [
                f"{round_label}는 두 선수가 서로 정타를 주고받은 팽팽한 라운드였습니다.",
                f"{round_label}는 {leader_name} 쪽으로 흐름이 완전히 넘어가지는 않은 라운드였습니다.",
                f"{round_label}는 두 선수의 작은 정타들이 쌓이면서 다음 라운드가 더 중요해졌습니다.",
                f"{round_label}는 {leader_wa} {other_name}의 눈치싸움이 길었던 라운드였습니다.",
                f"{round_label}는 조용해 보여도 점수에 남을 장면은 있었습니다.",
            ])

        def section_evidence() -> str:
            if tkos:
                return pick("evidence-tko", [
                    "TKO가 나온 만큼, 이 라운드는 데미지 수치보다 스톱 장면의 의미가 더 컸습니다.",
                    f"{leader_neun} 결정적인 장면을 만들었고, 그 순간 라운드 평가가 확실히 기울었습니다.",
                    "라운드 전체를 숫자로만 보면 설명이 부족하고, 스톱 장면 자체가 핵심입니다.",
                ])
            if knockdowns and kd_for.get(leader, 0) > kd_for.get(other, 0):
                return pick("evidence-kd", [
                    "다운 장면이 나온 만큼, 단순 데미지 차이보다 큰 장면의 비중이 컸습니다.",
                    f"{leader_neun} 라운드 안에서 가장 기억에 남는 장면을 만들었습니다.",
                    "다운 하나가 라운드 인상을 크게 바꾼 흐름입니다.",
                ])
            if damage_gap >= 45.0:
                return pick("evidence-clear", [
                    f"총 데미지 차이가 분명했고, 유효타 싸움에서도 {leader_name} 쪽이 더 안정적으로 앞섰습니다.",
                    f"{leader_name}의 정타 질과 쌓인 데미지에서 차이가 났고, 라운드 중반부터 부담이 커졌습니다.",
                    f"{leader_name} 쪽이 더 큰 타격을 반복해서 만들면서 라운드 전체 인상이 강하게 남았습니다.",
                ])
            if damage_gap >= 20.0:
                return pick("evidence-small", [
                    f"큰 차이는 아니지만, {leader_ga} 라운드 안에서 작은 데미지를 계속 쌓았습니다.",
                    f"서로 맞불을 놓는 장면이 있었지만, 정타가 쌓인 흐름에서는 {leader_ga} 조금 더 앞섰습니다.",
                    f"전체 데미지 차이는 크지 않아 보여도, {leader_name} 쪽 유효타가 조금 더 선명했습니다.",
                ])
            return pick("evidence-close", [
                f"데미지 흐름만 보면 {leader_wa} {other_name}의 접전에 가깝고, 한 번의 교전으로 분위기가 바뀔 수 있는 내용이었습니다.",
                f"두 선수가 유효타를 주고받았고, 확실하게 라운드를 장악했다고 보기는 어려웠습니다.",
                "정타 수와 데미지 모두 팽팽해서, 다음 라운드 초반 흐름이 더 중요해졌습니다.",
            ])

        def section_big_scene() -> str:
            if tkos:
                tko = tkos[-1] or {}
                stopped_name = self._commentary_name(str(tko.get("receiver_side") or ""))
                finisher_name = self._commentary_name(str(tko.get("attacker_side") or ""))
                return pick("scene-tko", [
                    f"{self._josa(finisher_name, '은/는')} 이 흐름을 확실히 끝낼 만큼 압박을 만들었습니다.",
                    f"{self._josa(stopped_name, '은/는')} 회복보다 방어 안정이 먼저였던 위험한 장면이었습니다.",
                    "TKO가 나온 만큼, 단순한 포인트 차이가 아니라 데미지와 위기 관리에서 차이가 났습니다.",
                ])
            if knockdowns:
                kd = knockdowns[-1] or {}
                downed_name = self._commentary_name(str(kd.get("receiver_side") or ""))
                attacker_name = self._commentary_name(str(kd.get("attacker_side") or ""))
                return pick("scene-kd", [
                    f"{self._josa(downed_name, '은/는')} 다운 이후 무리하게 맞불을 놓기보다 회복과 거리 조절이 더 중요해졌습니다.",
                    f"그 장면 이후 {self._josa(downed_name, '이/가')} 수비 반응과 발 움직임을 얼마나 되찾느냐가 다음 라운드의 핵심입니다.",
                    f"{self._josa(attacker_name, '은/는')} 이 흐름을 이어가야 하고, {self._josa(downed_name, '은/는')} 초반 위기 관리가 필요합니다.",
                ])
            if stuns:
                return pick("scene-stun", [
                    "크게 흔들린 뒤에는 정타 허용을 줄이는 게 가장 먼저입니다.",
                    "위험한 장면이 있었기 때문에, 다음 라운드 초반에는 수비 안정이 필요합니다.",
                    "스턴에 가까운 장면이 나온 만큼, 같은 궤도의 정타를 다시 허용하면 더 위험해질 수 있습니다.",
                ])
            if max(big_count.values() or [0]) >= 3:
                return pick("scene-bigs", [
                    "큰 타격이 여러 차례 나왔고, 한 방 한 방의 충격이 라운드 후반까지 영향을 줬습니다.",
                    "강한 정타가 반복되면서 단순한 포인트 싸움이 아니라 데미지 싸움으로 흘렀습니다.",
                    "위험한 타격이 쌓였기 때문에, 다음 라운드에는 방어 반응이 더 빨라져야 합니다.",
                ])
            if max_event and float(max_event.get("damage", 0.0) or 0.0) >= 45.0:
                return pick("scene-single", [
                    "라운드 안에서 나온 가장 강한 정타가 흐름을 잠깐 흔들었습니다.",
                    "큰 장면이 아주 많지는 않았지만, 강하게 들어간 한 방은 분명히 있었습니다.",
                    "정타 하나가 인상에 남았고, 그 뒤의 수비 반응이 중요했습니다.",
                ])
            return pick("scene-tempo", [
                "엄청난 한 방보다는 거리와 타이밍 싸움에서 조금씩 차이를 만든 라운드였습니다.",
                "큰 폭발력보다는 잔타와 정타가 쌓이면서 라운드 흐름을 만들었습니다.",
                "한 번에 무너뜨리는 장면은 없었지만, 교전마다 작은 부담이 계속 쌓였습니다.",
                "큰 장면은 적었지만 팔은 꽤 바빴습니다.",
                "화려하진 않아도 점수표는 바빴습니다.",
            ])

        def section_late() -> str:
            if late_gap >= 25.0:
                late_name = self._commentary_name(late_leader)
                return pick("late-clear", [
                    f"라운드 후반에는 {late_name} 쪽이 흐름을 더 선명하게 가져갔습니다.",
                    "마지막 30초 교전에서 차이가 나면서 쉬는 시간 분위기도 달라졌습니다.",
                    "후반 집중력에서 차이가 있었고, 그 장면이 다음 라운드 초반까지 이어질 수 있습니다.",
                ])
            return pick("late-close", [
                "후반부도 완전히 밀리기보다는 서로 버티면서 교전을 이어갔습니다.",
                "마지막 교전까지 확실한 흐름이 고정되지는 않았습니다.",
                "후반에는 서로 신중하게 움직였고, 큰 실수 하나가 라운드 인상을 바꿀 수 있었습니다.",
                "막판까지 눈치싸움이 이어졌습니다.",
            ])

        def section_next() -> str:
            if tkos or knockdowns or stuns:
                return pick("next-danger-pattern", [
                    "다음 라운드 초반은 회복 상태와 첫 교전 대응을 반드시 봐야 합니다.",
                    "쉬는 시간 이후 첫 20초가 중요합니다. 무리하게 들어가면 다시 큰 정타를 허용할 수 있습니다.",
                    "다음 라운드는 초반 안정이 핵심이고, 먼저 흔들리는 쪽이 더 큰 위기를 맞을 수 있습니다.",
                ])
            if damage_gap >= 30.0:
                return pick("next-gap-pattern", [
                    f"초반 거리 싸움에서 같은 구도가 반복되면 {other_name} 쪽 데미지 차이가 더 벌어질 수 있습니다.",
                    f"다음 라운드에는 {other_name}의 수비 수정이 가장 중요합니다.",
                    f"{leader_neun} 무리하지 않고 압박을 이어가고, {other_neun} 먼저 흐름을 끊어야 합니다.",
                ])
            return pick("next-close-pattern", [
                "다음 라운드는 초반 거리 싸움과 첫 번째 정타가 흐름을 만들 가능성이 큽니다.",
                "접전인 만큼, 다음 라운드에서는 무리한 진입보다 정확한 타이밍이 중요합니다.",
                "큰 차이가 없기 때문에, 다음 라운드 초반 주도권 싸움이 더 중요해졌습니다.",
            ])

        def section_corner() -> str:
            return pick("corner-pattern", [
                f"{other_name} 코너에서는 체력 회복과 함께, 어떤 궤도의 타격을 계속 허용했는지 빠르게 정리해야 합니다.",
                f"쉬는 시간에는 {other_name}의 체력 회복도 중요하지만, 같은 위치에서 같은 정타를 맞지 않도록 수비 위치를 바로잡는 게 더 중요합니다.",
                f"다음 라운드에 {other_ga} 바로 달라져야 할 부분은 진입 거리와 첫 방 이후의 수비 반응입니다.",
            ])

        def section_tactical() -> str:
            return pick("tactical-pattern", [
                f"{leader_neun} 무리하게 서두르기보다, 효과가 있었던 타이밍을 다시 만드는 게 좋습니다.",
                f"{other_neun} 먼저 큰 한 방을 노리기보다, 정타 허용을 줄이고 호흡을 되찾는 과정이 필요합니다.",
                f"결국 다음 라운드는 {leader_wa} {other_name} 중 누가 먼저 자기 거리를 잡느냐에서 흐름이 갈릴 가능성이 큽니다.",
            ])

        def active_extra() -> str:
            if mode != "active":
                return ""
            return pick("active-extra-pattern", [
                "결국 관건은 같은 정타를 반복해서 허용하지 않는 것, 그리고 좋은 타이밍이 왔을 때 확실히 마무리하는 것입니다.",
                "지금부터는 단순히 많이 치는 것보다, 위험한 정타를 얼마나 줄이고 본인의 거리에서 싸우느냐가 중요합니다.",
                "쉬는 시간 동안 호흡을 얼마나 회복하고, 다음 라운드 첫 교전을 어떻게 가져가느냐가 승부에 큰 영향을 줄 수 있습니다.",
            ])

        if mode == "quiet":
            order = [section_open, section_report_numbers, gauge_line, section_next]
            cleaned = [x for x in (fn() for fn in order) if x]
            budget_sec = self._round_break_summary_budget_seconds(break_seconds_left, mode)
            selected = self._select_commentary_lines_for_budget(cleaned, budget_sec, min_lines=2, max_lines=4)
            logging.info("SPECTATORLOG_ROUND_SUMMARY_BUDGET round=%s mode=%s budget=%.1f selected=%s total=%s", r, mode, budget_sec, len(selected), len(cleaned))
            return " ".join(selected).strip()

        # Pattern selection: 사건형 / 접전형 / 우세 흐름형 / 일반 흐름형.
        if tkos or knockdowns or stuns:
            pattern_name = "event"
            order = [section_open, section_big_scene, section_evidence, section_report_numbers, section_report_detail, gauge_line, weak_line, section_late, section_next, section_corner, section_tactical, active_extra]
        elif damage_gap < 20.0:
            pattern_name = "close"
            order = [section_open, section_evidence, section_report_numbers, section_late, weak_line, section_report_detail, gauge_line, section_big_scene, section_next, section_corner, section_tactical, active_extra]
        elif damage_gap >= 45.0 or leader_dmg >= max(1.0, other_dmg) * 1.35:
            pattern_name = "dominant"
            order = [section_open, section_evidence, section_report_numbers, section_report_detail, gauge_line, section_big_scene, weak_line, section_late, section_next, section_corner, section_tactical, active_extra]
        else:
            pattern_name = "flow"
            order = [section_open, section_evidence, section_report_numbers, section_big_scene, section_report_detail, gauge_line, section_late, weak_line, section_next, section_corner, section_tactical, active_extra]

        lines = [x for x in (fn() for fn in order) if x]
        max_lines = 14 if mode == "active" else 12
        budget_sec = self._round_break_summary_budget_seconds(break_seconds_left, mode)
        if budget_sec < 26.0:
            min_lines = 3
        elif mode == "active" and budget_sec >= 40.0:
            min_lines = 6
        else:
            min_lines = 5
        selected = self._select_commentary_lines_for_budget(lines, budget_sec, min_lines=min_lines, max_lines=max_lines)
        text = " ".join(selected).strip()
        logging.info(
            "SPECTATORLOG_ROUND_SUMMARY_PATTERN round=%s pattern=%s budget=%.1f selected=%s total=%s",
            r, pattern_name, budget_sec, len(selected), len(lines),
        )
        return text

    def _new_scorecard_round(self, round_no: int) -> Dict[str, Any]:
        return {
            "round": int(max(1, round_no or 1)),
            "dealt": {"blue": 0.0, "red": 0.0},
            "landed": {"blue": 0, "red": 0},
            "thrown": {"blue": 0, "red": 0},
            "hits": {"blue": 0, "red": 0},
            "bigs": {"blue": 0, "red": 0},
            "counters_for": {"blue": 0, "red": 0},
            "stuns_for": {"blue": 0, "red": 0},
            "knockdowns_for": {"blue": 0, "red": 0},
            "knockdowns_against": {"blue": 0, "red": 0},
            "tkos_for": {"blue": 0, "red": 0},
            "punches": {"blue": {}, "red": {}},
            "max_punch": {"blue": {}, "red": {}},
            "thrown_punches": {"blue": {}, "red": {}},
            "weak_received": {"blue": {}, "red": {}},
            "weak": {},
            "events": 0,
            "gauge_start": {},
            "gauge_end": {},
        }

    def _apply_scorecard_round_to_report_stats(self, report_stats: Dict[str, Dict[str, Any]], round_no: int) -> bool:
        """Replace cumulative file totals with the live scorecard's one-round data."""
        round_stats = dict((self._scorecard_rounds or {}).get(int(round_no or 0)) or {})
        if not round_stats or not int(round_stats.get("events", 0) or 0):
            return False
        for side in ("blue", "red"):
            target = report_stats.get(side)
            if not isinstance(target, dict):
                continue
            target["landed"] = int(dict(round_stats.get("landed") or {}).get(side, 0) or 0)
            target["thrown"] = int(dict(round_stats.get("thrown") or {}).get(side, 0) or 0)
            target["damage"] = float(dict(round_stats.get("dealt") or {}).get(side, 0.0) or 0.0)
            target["big_hits"] = int(dict(round_stats.get("bigs") or {}).get(side, 0) or 0)
            target["counter_hits"] = int(dict(round_stats.get("counters_for") or {}).get(side, 0) or 0)
            target["knockdowns_for"] = int(dict(round_stats.get("knockdowns_for") or {}).get(side, 0) or 0)
            target["tkos_for"] = int(dict(round_stats.get("tkos_for") or {}).get(side, 0) or 0)
            target["stuns_for"] = int(dict(round_stats.get("stuns_for") or {}).get(side, 0) or 0)
            target["punches"] = {
                key: dict(item or {})
                for key, item in dict(dict(round_stats.get("punches") or {}).get(side) or {}).items()
            }
            target["thrown_punches"] = {
                key: dict(item or {})
                for key, item in dict(dict(round_stats.get("thrown_punches") or {}).get(side) or {}).items()
            }
            target["weak_received"] = {
                key: dict(item or {})
                for key, item in dict(dict(round_stats.get("weak_received") or {}).get(side) or {}).items()
            }
            target["max_punch"] = dict(dict(round_stats.get("max_punch") or {}).get(side) or {})
        return True

    def _record_scorecard_thrown_snapshot(self, round_no: int, thrown_events: List[dict], landed_events: Optional[List[dict]] = None) -> None:
        """Store a round-local thrown-punch snapshot from a cumulative log file."""
        try:
            r = max(1, int(round_no or 1))
        except Exception:
            r = 1
        counts = {"blue": 0, "red": 0}
        breakdown: Dict[str, Dict[str, Dict[str, Any]]] = {"blue": {}, "red": {}}
        matched_punch_by_throw: Dict[int, str] = {}
        unmatched = set(range(len(thrown_events or [])))
        for landed in list(landed_events or []):
            punch = str((landed or {}).get("punch") or "").strip()
            if punch.lower() in ("pull", "other"):
                continue
            attacker = str((landed or {}).get("attacker_side") or "").lower()
            hand = str((landed or {}).get("hand") or "").lower()
            try:
                landed_time = float((landed or {}).get("time", 0.0) or 0.0)
            except Exception:
                continue
            candidates = []
            for index in unmatched:
                thrown = (thrown_events or [])[index] or {}
                if str(thrown.get("side") or "").lower() != attacker:
                    continue
                if hand and str(thrown.get("hand") or "").lower() != hand:
                    continue
                delta = abs(float(thrown.get("time", 0.0) or 0.0) - landed_time)
                if delta <= 0.85:
                    candidates.append((delta, index))
            if candidates:
                _delta, index = min(candidates)
                unmatched.discard(index)
                matched_punch_by_throw[index] = punch

        for event_index, event in enumerate(list(thrown_events or [])):
            side = str((event or {}).get("side") or "").lower()
            if side not in counts:
                continue
            counts[side] += 1
            classified_punch = matched_punch_by_throw.get(event_index) or str((event or {}).get("punch") or "")
            key, label = self._punch_report_group(classified_punch)
            item = breakdown[side].setdefault(key, {"label": label, "count": 0, "damage": 0.0})
            item["count"] = int(item.get("count", 0) or 0) + 1

        current = {"counts": counts, "breakdown": breakdown}
        baseline = self._scorecard_thrown_round_baselines.get(r)
        if baseline is None:
            baseline = {
                "counts": dict((self._scorecard_thrown_last_cumulative or {}).get("counts") or {}),
                "breakdown": {
                    side: {
                        key: dict(item or {})
                        for key, item in dict(((self._scorecard_thrown_last_cumulative or {}).get("breakdown") or {}).get(side) or {}).items()
                    }
                    for side in ("blue", "red")
                },
            }
            self._scorecard_thrown_round_baselines[r] = baseline

        # A reset file has one decreasing round clock. A cumulative file has a
        # clock jump upward when the next round starts.
        times = [float((event or {}).get("time", 0.0) or 0.0) for event in list(thrown_events or [])]
        has_round_clock_jump = any(times[i] > times[i - 1] + 5.0 for i in range(1, len(times)))
        has_clock_data = any(value > 0.0 for value in times)
        reset_file = (r > 1 and has_clock_data and not has_round_clock_jump) or any(
            int(counts.get(side, 0) or 0) < int((baseline.get("counts") or {}).get(side, 0) or 0)
            for side in ("blue", "red")
        )
        if reset_file:
            baseline = {"counts": {"blue": 0, "red": 0}, "breakdown": {"blue": {}, "red": {}}}
            self._scorecard_thrown_round_baselines[r] = baseline

        delta_counts = {"blue": 0, "red": 0}
        delta_breakdown: Dict[str, Dict[str, Dict[str, Any]]] = {"blue": {}, "red": {}}
        for side in ("blue", "red"):
            base_count = int((baseline.get("counts") or {}).get(side, 0) or 0)
            delta_counts[side] = max(0, int(counts.get(side, 0) or 0) - base_count)
            base_items = dict((baseline.get("breakdown") or {}).get(side) or {})
            for key, item in breakdown[side].items():
                base_item = dict(base_items.get(key) or {})
                delta_count = max(0, int((item or {}).get("count", 0) or 0) - int(base_item.get("count", 0) or 0))
                if delta_count:
                    delta_breakdown[side][key] = {
                        "label": (item or {}).get("label") or key,
                        "count": delta_count,
                        "damage": 0.0,
                    }

        stats = self._scorecard_rounds.setdefault(r, self._new_scorecard_round(r))
        stats["thrown"] = delta_counts
        stats["thrown_punches"] = delta_breakdown
        self._scorecard_thrown_last_cumulative = current
        self._scorecard_remember_pair()

    def _scorecard_copy_gauge(self, snap: Optional[Dict[str, Dict[str, float]]]) -> Dict[str, Dict[str, float]]:
        if not snap:
            return {}
        return {side: dict((snap.get(side) or {})) for side in ("blue", "red")}

    def _scorecard_remember_pair(self) -> None:
        try:
            self._scorecard_last_pair = (self._side_raw_name("blue"), self._side_raw_name("red"))
        except Exception:
            pass

    def _record_scorecard_events(self, new_events: List[dict], round_no: Optional[int], damage_path: str, punishment_snapshot: Optional[Dict[str, Dict[str, float]]] = None) -> None:
        """Keep a per-round scorecard from live damage events.

        damage_events.txt does not include a round number, so the watcher tags
        newly observed rows with the last active fight round.  This lets the
        final commentary use the user's scoring rule: round damage leader gets
        the round by one point, knockdowns subtract a point, and 3 knockdowns in
        one round ends the fight.
        """
        if not new_events:
            return
        try:
            r = max(1, int(round_no or self._last_fight_round_no or 1))
        except Exception:
            r = 1
        stats = self._scorecard_rounds.setdefault(r, self._new_scorecard_round(r))
        if not stats.get("gauge_start") and punishment_snapshot:
            stats["gauge_start"] = self._scorecard_copy_gauge(punishment_snapshot)
        if punishment_snapshot:
            stats["gauge_end"] = self._scorecard_copy_gauge(punishment_snapshot)
        self._scorecard_remember_pair()

        for ev in list(new_events or []):
            try:
                key = (r,) + tuple(self._damage_event_key(ev))
            except Exception:
                key = (r, str(ev))
            if key in self._scorecard_seen_event_keys:
                continue
            self._scorecard_seen_event_keys.add(key)
            if len(self._scorecard_seen_event_keys) > 1200:
                try:
                    self._scorecard_seen_event_keys = set(list(self._scorecard_seen_event_keys)[-900:])
                except Exception:
                    pass

            attacker = str((ev or {}).get("attacker_side") or "").lower()
            receiver = str((ev or {}).get("receiver_side") or "").lower()
            if attacker not in ("blue", "red") or receiver not in ("blue", "red"):
                continue
            if str((ev or {}).get("punch") or "").strip().lower() in ("pull", "other"):
                continue
            try:
                dmg = max(0.0, float((ev or {}).get("damage", 0.0) or 0.0))
            except Exception:
                dmg = 0.0
            stats["events"] = int(stats.get("events", 0) or 0) + 1
            stats["dealt"][attacker] = float(stats["dealt"].get(attacker, 0.0) or 0.0) + dmg
            stats["landed"][attacker] = int(stats["landed"].get(attacker, 0) or 0) + 1
            if dmg >= 12.0:
                stats["hits"][attacker] = int(stats["hits"].get(attacker, 0) or 0) + 1
            if dmg >= 45.0:
                stats["bigs"][attacker] = int(stats["bigs"].get(attacker, 0) or 0) + 1
            pkey, plabel = self._punch_report_group(str((ev or {}).get("punch") or ""))
            punches_for_side = stats.setdefault("punches", {}).setdefault(attacker, {})
            pitem = punches_for_side.setdefault(pkey, {"label": plabel, "count": 0, "damage": 0.0})
            pitem["count"] = int(pitem.get("count", 0) or 0) + 1
            pitem["damage"] = float(pitem.get("damage", 0.0) or 0.0) + dmg
            if dmg > float((stats["max_punch"].get(attacker) or {}).get("damage", 0.0) or 0.0):
                stats["max_punch"][attacker] = {"key": pkey, "label": plabel, "damage": dmg}
            try:
                cm = float((ev or {}).get("counter_mult", 1.0) or 1.0)
            except Exception:
                cm = 1.0
            if self._is_counter_event(ev):
                stats["counters_for"][attacker] = int(stats["counters_for"].get(attacker, 0) or 0) + 1
            kind = self._damage_effect_kind(str((ev or {}).get("damage_type") or ""))
            if kind == "knockdown":
                stats["knockdowns_for"][attacker] = int(stats["knockdowns_for"].get(attacker, 0) or 0) + 1
                stats["knockdowns_against"][receiver] = int(stats["knockdowns_against"].get(receiver, 0) or 0) + 1
            elif kind == "stun":
                stats["stuns_for"][attacker] = int(stats["stuns_for"].get(attacker, 0) or 0) + 1
            elif kind == "tko":
                stats["tkos_for"][attacker] = int(stats["tkos_for"].get(attacker, 0) or 0) + 1
            weak = self._weak_point_ko(str((ev or {}).get("weak_point") or ""))
            if weak:
                weak_key = f"{receiver}:{weak}"
                item = stats["weak"].setdefault(weak_key, {"receiver": receiver, "weak": weak, "count": 0, "damage": 0.0})
                item["count"] = int(item.get("count", 0) or 0) + 1
                item["damage"] = float(item.get("damage", 0.0) or 0.0) + dmg
                weak_for_side = stats.setdefault("weak_received", {}).setdefault(receiver, {})
                ritem = weak_for_side.setdefault(weak, {"label": weak, "count": 0, "damage": 0.0})
                ritem["count"] = int(ritem.get("count", 0) or 0) + 1
                ritem["damage"] = float(ritem.get("damage", 0.0) or 0.0) + dmg

    def _scorecard_from_fallback_events(self, events: List[dict], round_no: Optional[int], damage_path: str) -> Dict[int, Dict[str, Any]]:
        try:
            r = max(1, int(round_no or self._last_fight_round_no or 1))
        except Exception:
            r = 1
        stats = self._new_scorecard_round(r)
        snap = self._punishment_snapshot(damage_path)
        stats["gauge_start"] = self._scorecard_copy_gauge(snap)
        stats["gauge_end"] = self._scorecard_copy_gauge(snap)
        for ev in list(events or []):
            attacker = str((ev or {}).get("attacker_side") or "").lower()
            receiver = str((ev or {}).get("receiver_side") or "").lower()
            if attacker not in ("blue", "red") or receiver not in ("blue", "red"):
                continue
            if str((ev or {}).get("punch") or "").strip().lower() in ("pull", "other"):
                continue
            try:
                dmg = max(0.0, float((ev or {}).get("damage", 0.0) or 0.0))
            except Exception:
                dmg = 0.0
            stats["events"] += 1
            stats["dealt"][attacker] += dmg
            stats["landed"][attacker] += 1
            if dmg >= 12.0:
                stats["hits"][attacker] += 1
            if dmg >= 45.0:
                stats["bigs"][attacker] += 1
            pkey, plabel = self._punch_report_group(str((ev or {}).get("punch") or ""))
            punches_for_side = stats.setdefault("punches", {}).setdefault(attacker, {})
            pitem = punches_for_side.setdefault(pkey, {"label": plabel, "count": 0, "damage": 0.0})
            pitem["count"] = int(pitem.get("count", 0) or 0) + 1
            pitem["damage"] = float(pitem.get("damage", 0.0) or 0.0) + dmg
            if dmg > float((stats["max_punch"].get(attacker) or {}).get("damage", 0.0) or 0.0):
                stats["max_punch"][attacker] = {"key": pkey, "label": plabel, "damage": dmg}
            try:
                cm = float((ev or {}).get("counter_mult", 1.0) or 1.0)
            except Exception:
                cm = 1.0
            if self._is_counter_event(ev):
                stats["counters_for"][attacker] = int(stats["counters_for"].get(attacker, 0) or 0) + 1
            kind = self._damage_effect_kind(str((ev or {}).get("damage_type") or ""))
            if kind == "knockdown":
                stats["knockdowns_for"][attacker] += 1
                stats["knockdowns_against"][receiver] += 1
            elif kind == "stun":
                stats["stuns_for"][attacker] += 1
            elif kind == "tko":
                stats["tkos_for"][attacker] += 1
            weak = self._weak_point_ko(str((ev or {}).get("weak_point") or ""))
            if weak:
                weak_key = f"{receiver}:{weak}"
                item = stats["weak"].setdefault(weak_key, {"receiver": receiver, "weak": weak, "count": 0, "damage": 0.0})
                item["count"] += 1
                item["damage"] += dmg
                weak_for_side = stats.setdefault("weak_received", {}).setdefault(receiver, {})
                ritem = weak_for_side.setdefault(weak, {"label": weak, "count": 0, "damage": 0.0})
                ritem["count"] = int(ritem.get("count", 0) or 0) + 1
                ritem["damage"] = float(ritem.get("damage", 0.0) or 0.0) + dmg
        return {r: stats}

    def _scorecard_round_result(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        dealt = dict(stats.get("dealt") or {})
        kd_against = dict(stats.get("knockdowns_against") or {})
        blue_dmg = float(dealt.get("blue", 0.0) or 0.0)
        red_dmg = float(dealt.get("red", 0.0) or 0.0)
        blue_score, red_score = 10, 10
        winner = "draw"
        if blue_dmg > red_dmg + 0.01:
            winner = "blue"
            red_score = 9
        elif red_dmg > blue_dmg + 0.01:
            winner = "red"
            blue_score = 9
        blue_score -= int(kd_against.get("blue", 0) or 0)
        red_score -= int(kd_against.get("red", 0) or 0)
        # Avoid absurd score readouts if the log has duplicate down rows.
        blue_score = max(6, int(blue_score))
        red_score = max(6, int(red_score))
        return {
            "round": int(stats.get("round", 0) or 0),
            "winner": winner,
            "blue_score": blue_score,
            "red_score": red_score,
            "blue_damage": blue_dmg,
            "red_damage": red_dmg,
            "blue_kd_against": int(kd_against.get("blue", 0) or 0),
            "red_kd_against": int(kd_against.get("red", 0) or 0),
        }

    def _scorecard_compute(self, damage_path: str, round_no: Optional[int], fallback_events: Optional[List[dict]] = None) -> Dict[str, Any]:
        live_rounds = {int(k): dict(v) for k, v in dict(self._scorecard_rounds or {}).items()}
        rounds = {int(k): dict(v) for k, v in live_rounds.items() if dict(v).get("events")}
        if not rounds and fallback_events:
            rounds = self._scorecard_from_fallback_events(fallback_events, round_no, damage_path)

        # A report can be built after the damage-event baseline was established
        # (for example when opening an old completed match).  Preserve the
        # thrown-punch snapshots in that fallback path so accuracy never turns
        # into a misleading "landed / 0" result.
        for r, live_stats in live_rounds.items():
            live_thrown = dict(live_stats.get("thrown") or {})
            live_breakdown = dict(live_stats.get("thrown_punches") or {})
            if not any(int(live_thrown.get(side, 0) or 0) for side in ("blue", "red")):
                continue
            target = rounds.setdefault(r, self._new_scorecard_round(r))
            target["thrown"] = {side: int(live_thrown.get(side, 0) or 0) for side in ("blue", "red")}
            target["thrown_punches"] = {
                side: {key: dict(item or {}) for key, item in dict(live_breakdown.get(side) or {}).items()}
                for side in ("blue", "red")
            }

        match_dir = os.path.dirname(str(damage_path or ""))
        official_scores = self._read_official_scores(os.path.join(match_dir, "scores.csv"))
        winner_file = self._read_winner_result(os.path.join(match_dir, "winner.txt"))
        official_scores = self._filter_completed_score_rows(
            official_scores,
            state=self._last_round_state,
            round_no=round_no,
            winner_present=bool(winner_file),
        )

        blue_total = 0
        red_total = 0
        results: List[Dict[str, Any]] = []
        stoppage: Dict[str, Any] = {}
        if official_scores:
            for row in official_scores:
                r = int(row.get("round", 0) or 0)
                stats = dict(rounds.get(r) or self._new_scorecard_round(r))
                official_blue_damage = float(row.get("red_damage_taken", (stats.get("dealt") or {}).get("blue", 0.0)) or 0.0)
                official_red_damage = float(row.get("blue_damage_taken", (stats.get("dealt") or {}).get("red", 0.0)) or 0.0)
                stats["dealt"] = {"blue": official_blue_damage, "red": official_red_damage}
                stats["knockdowns_against"] = {
                    "blue": int(row.get("blue_kds", (stats.get("knockdowns_against") or {}).get("blue", 0)) or 0),
                    "red": int(row.get("red_kds", (stats.get("knockdowns_against") or {}).get("red", 0)) or 0),
                }
                stats["knockdowns_for"] = {
                    "blue": int(stats["knockdowns_against"].get("red", 0) or 0),
                    "red": int(stats["knockdowns_against"].get("blue", 0) or 0),
                }
                res = {
                    "round": r,
                    "winner": str(row.get("winner") or "draw"),
                    "blue_score": int(row.get("blue_score", 0) or 0),
                    "red_score": int(row.get("red_score", 0) or 0),
                    "blue_damage": official_blue_damage,
                    "red_damage": official_red_damage,
                    "blue_kd_against": int(row.get("blue_kds", (stats.get("knockdowns_against") or {}).get("blue", 0)) or 0),
                    "red_kd_against": int(row.get("red_kds", (stats.get("knockdowns_against") or {}).get("red", 0)) or 0),
                    "official": True,
                }
                results.append(res)
                blue_total += int(res.get("blue_score", 0) or 0)
                red_total += int(res.get("red_score", 0) or 0)
                rounds[r] = stats
            # Keep stoppage info when the live damage events observed it.
            for r in sorted(rounds):
                stats = dict(rounds.get(r) or {})
                tkos_for = dict(stats.get("tkos_for") or {})
                kd_against = dict(stats.get("knockdowns_against") or {})
                if int(tkos_for.get("blue", 0) or 0) > 0:
                    stoppage = {"winner": "blue", "loser": "red", "round": r, "method": "TKO"}
                elif int(tkos_for.get("red", 0) or 0) > 0:
                    stoppage = {"winner": "red", "loser": "blue", "round": r, "method": "TKO"}
                elif int(kd_against.get("blue", 0) or 0) >= 3:
                    stoppage = {"winner": "red", "loser": "blue", "round": r, "method": "3다운 TKO"}
                elif int(kd_against.get("red", 0) or 0) >= 3:
                    stoppage = {"winner": "blue", "loser": "red", "round": r, "method": "3다운 TKO"}
            if winner_file and str(winner_file.get("side") or "") in ("blue", "red", "draw"):
                winner = str(winner_file.get("side") or "draw")
            elif stoppage:
                winner = str(stoppage.get("winner") or "")
            elif blue_total > red_total:
                winner = "blue"
            elif red_total > blue_total:
                winner = "red"
            else:
                winner = "draw"
            return {
                "rounds": rounds,
                "results": results,
                "blue_total": blue_total,
                "red_total": red_total,
                "winner": winner,
                "stoppage": stoppage,
                "official_scores": True,
                "winner_file": winner_file,
            }

        for r in sorted(rounds):
            stats = rounds[r]
            res = self._scorecard_round_result(stats)
            results.append(res)
            blue_total += int(res.get("blue_score", 0) or 0)
            red_total += int(res.get("red_score", 0) or 0)
            tkos_for = dict(stats.get("tkos_for") or {})
            kd_against = dict(stats.get("knockdowns_against") or {})
            if int(tkos_for.get("blue", 0) or 0) > 0:
                stoppage = {"winner": "blue", "loser": "red", "round": r, "method": "TKO"}
            elif int(tkos_for.get("red", 0) or 0) > 0:
                stoppage = {"winner": "red", "loser": "blue", "round": r, "method": "TKO"}
            elif int(kd_against.get("blue", 0) or 0) >= 3:
                stoppage = {"winner": "red", "loser": "blue", "round": r, "method": "3다운 TKO"}
            elif int(kd_against.get("red", 0) or 0) >= 3:
                stoppage = {"winner": "blue", "loser": "red", "round": r, "method": "3다운 TKO"}
        if stoppage:
            winner = str(stoppage.get("winner") or "")
        elif blue_total > red_total:
            winner = "blue"
        elif red_total > blue_total:
            winner = "red"
        else:
            winner = "draw"
        return {
            "rounds": rounds,
            "results": results,
            "blue_total": blue_total,
            "red_total": red_total,
            "winner": winner,
            "stoppage": stoppage,
        }

    def _scorecard_rounds_line(self, scorecard: Dict[str, Any]) -> str:
        results = list(scorecard.get("results") or [])
        if not results:
            return ""
        pieces = []
        for res in results[:5]:
            r = int(res.get("round", 0) or 0)
            winner = str(res.get("winner") or "")
            if winner in ("blue", "red"):
                pieces.append(f"{r}라운드는 {self._josa(self._caster_name(winner), '이/가')} 가져갔습니다")
            else:
                pieces.append(f"{r}라운드는 큰 차이가 없었습니다")
        if not pieces:
            return ""
        return ", ".join(pieces) + "."

    def _scorecard_top_round_line(self, scorecard: Dict[str, Any]) -> str:
        results = list(scorecard.get("results") or [])
        if not results:
            return ""
        try:
            best = max(results, key=lambda r: abs(float(r.get("blue_damage", 0.0) or 0.0) - float(r.get("red_damage", 0.0) or 0.0)) + (float(r.get("blue_kd_against", 0) or 0) + float(r.get("red_kd_against", 0) or 0)) * 60.0)
        except Exception:
            return ""
        r = int(best.get("round", 0) or 0)
        blue_kd = int(best.get("blue_kd_against", 0) or 0)
        red_kd = int(best.get("red_kd_against", 0) or 0)
        if blue_kd or red_kd:
            downed = "blue" if blue_kd >= red_kd else "red"
            return f"가장 큰 장면은 {r}라운드 다운 장면이었고, {self._caster_name(downed)} 쪽에 감점이 붙었습니다."
        winner = str(best.get("winner") or "")
        if winner in ("blue", "red"):
            return f"가장 차이가 컸던 라운드는 {r}라운드였고, {self._josa(self._caster_name(winner), '이/가')} 유효타에서 앞섰습니다."
        return "전체적으로 큰 차이가 한 번에 벌어진 라운드보다는, 작은 정타가 쌓인 경기였습니다."

    def _scorecard_gauge_final_line(self, scorecard: Dict[str, Any], damage_path: str) -> str:
        snap = self._punishment_snapshot(damage_path)
        if not snap:
            return ""
        def lost(side: str) -> float:
            return self._clamp_percent((snap.get(side) or {}).get("lost_pct", 0.0))
        blue_lost, red_lost = lost("blue"), lost("red")
        gap = abs(blue_lost - red_lost)
        if max(blue_lost, red_lost) >= 70.0:
            worst = "blue" if blue_lost >= red_lost else "red"
            return f"마지막 데미지 상황을 보면 {self._caster_name(worst)} 쪽 체력 부담이 상당히 크게 남았습니다."
        if gap >= 18.0:
            worst = "blue" if blue_lost >= red_lost else "red"
            return f"받은 데미지까지 보면 {self._caster_name(worst)} 쪽이 더 많은 부담을 안고 경기를 마쳤습니다."
        return "데미지 부담 차이는 완전히 일방적이지 않았고, 점수는 라운드별 유효타와 다운 여부가 핵심입니다."

    def _scorecard_weak_final_line(self, scorecard: Dict[str, Any]) -> str:
        buckets: Dict[str, Dict[str, Any]] = {}
        for stats in dict(scorecard.get("rounds") or {}).values():
            for key, item in dict(stats.get("weak") or {}).items():
                weak = str((item or {}).get("weak") or "")
                if not weak:
                    continue
                cur = buckets.setdefault(weak, {"count": 0, "damage": 0.0})
                cur["count"] += int((item or {}).get("count", 0) or 0)
                cur["damage"] += float((item or {}).get("damage", 0.0) or 0.0)
        if not buckets:
            return ""
        weak, item = max(buckets.items(), key=lambda kv: int(kv[1].get("count", 0) or 0) * 20.0 + float(kv[1].get("damage", 0.0) or 0.0))
        cnt = int(item.get("count", 0) or 0)
        dmg = float(item.get("damage", 0.0) or 0.0)
        if weak in ("간", "복부", "명치") and (cnt >= 2 or dmg >= 75.0):
            return "바디 쪽 데미지가 쌓이면서 경기 후반 부담으로 이어졌습니다."
        if (weak == "턱" or "관자놀이" in weak) and (cnt >= 2 or dmg >= 80.0):
            return "머리 쪽 정타 허용이 반복되면서 위험한 장면을 만들었습니다."
        if weak in ("눈", "코", "얼굴") and cnt >= 3:
            return "얼굴 쪽 정타가 반복되면서 수비 부담이 계속 쌓였습니다."
        return ""

    def _build_match_final_summary(self, damage_path: str, round_no: Optional[int], pair_key: Tuple[str, str], state: str) -> str:
        """Build a post-fight scorecard summary with varied broadcast patterns.

        User rule: damage leader wins each round by one point, normal boxing
        knockdown deductions apply, and three knockdowns in one round ends the
        fight.  This summary combines scorecard, decisive moments, total damage,
        gauge burden, weak-point trends, and final tactical read.
        """
        if not bool(getattr(self.cfg, "spectator_commentary_enabled", False)):
            return ""
        events, _effect_counts = self._scan_damage_file_for_session_reset(damage_path)
        sig = self._file_sig(damage_path)
        match_dir = os.path.dirname(str(damage_path or ""))
        scores_sig = self._file_sig(os.path.join(match_dir, "scores.csv"))
        winner_sig = self._file_sig(os.path.join(match_dir, "winner.txt"))
        summary_key = (str(state or ""), str(pair_key or ""), f"{sig[0]}:{sig[1]}", f"{scores_sig[0]}:{scores_sig[1]}", f"{winner_sig[0]}:{winner_sig[1]}", str(len(self._scorecard_rounds or {})))
        if summary_key == self._last_match_summary_key:
            return ""
        self._last_match_summary_key = summary_key

        scorecard = self._scorecard_compute(damage_path, round_no, events)
        results = list(scorecard.get("results") or [])
        if not results:
            return ""

        blue_name = self._caster_name("blue")
        red_name = self._caster_name("red")
        blue_total = int(scorecard.get("blue_total", 0) or 0)
        red_total = int(scorecard.get("red_total", 0) or 0)
        winner_side = str(scorecard.get("winner") or "")
        winner_name = self._caster_name(winner_side) if winner_side in ("blue", "red") else ""
        loser_side = "red" if winner_side == "blue" else "blue" if winner_side == "red" else ""
        loser_name = self._caster_name(loser_side) if loser_side else ""
        stoppage = dict(scorecard.get("stoppage") or {})
        rounds = dict(scorecard.get("rounds") or {})

        dealt_total = {"blue": 0.0, "red": 0.0}
        big_total = {"blue": 0, "red": 0}
        hit_total = {"blue": 0, "red": 0}
        counter_total = {"blue": 0, "red": 0}
        kd_for = {"blue": 0, "red": 0}
        stun_for = {"blue": 0, "red": 0}
        for stats in rounds.values():
            for side in ("blue", "red"):
                dealt_total[side] += float(((stats.get("dealt") or {}).get(side, 0.0)) or 0.0)
                big_total[side] += int(((stats.get("bigs") or {}).get(side, 0)) or 0)
                hit_total[side] += int(((stats.get("hits") or {}).get(side, 0)) or 0)
                counter_total[side] += int(((stats.get("counters_for") or {}).get(side, 0)) or 0)
                kd_for[side] += int(((stats.get("knockdowns_for") or {}).get(side, 0)) or 0)
                stun_for[side] += int(((stats.get("stuns_for") or {}).get(side, 0)) or 0)

        key_base = f"match-summary-pattern:{summary_key[2]}:{len(results)}:{blue_total}:{red_total}"
        local_used: set = set()

        def pick(suffix: str, candidates: List[str]) -> str:
            items = [str(x or "").strip() for x in list(candidates or []) if str(x or "").strip()]
            pool = [x for x in items if x not in local_used]
            if not pool:
                pool = items
            if not pool:
                return ""
            try:
                seed = sum(ord(ch) for ch in f"{key_base}:{suffix}") + len(local_used) * 23
                chosen = pool[abs(seed) % len(pool)]
            except Exception:
                chosen = pool[0]
            local_used.add(chosen)
            return chosen

        def result_line() -> str:
            if stoppage and winner_name:
                method = str(stoppage.get("method") or "TKO")
                r = int(stoppage.get("round", 0) or 0)
                if "3다운" in method:
                    return pick("result-3kd", [
                        f"경기 종료 후 정리하면, {r}라운드에 3다운이 나오면서 {self._josa(winner_name, '이/가')} 테크니컬 녹아웃으로 경기를 가져갑니다.",
                        f"{r}라운드 세 번째 다운이 결정적이었고, {self._josa(winner_name, '이/가')} 스톱승으로 마무리합니다.",
                    ])
                return pick("result-tko", [
                    f"경기 종료 후 정리하면, {self._josa(winner_name, '이/가')} 테크니컬 녹아웃으로 경기를 가져갑니다.",
                    f"결정적인 스톱 장면이 나오면서 {self._josa(winner_name, '이/가')} 경기를 끝냅니다.",
                ])
            if winner_name:
                return pick("result-decision", [
                    f"경기 종료 후 스코어카드 기준으로 보면, {self._josa(winner_name, '이/가')} 판정으로 경기를 가져갑니다.",
                    f"복싱식 점수 계산으로 보면, {self._josa(winner_name, '이/가')} 더 많은 라운드를 가져간 경기입니다.",
                    f"최종 흐름을 종합하면, {winner_name} 쪽이 점수에서 앞선 경기였습니다.",
                ])
            return pick("result-draw", [
                "경기 종료 후 스코어카드 기준으로 보면, 무승부에 가까운 경기입니다.",
                "라운드별 흐름이 나뉘면서, 점수상으로는 팽팽한 경기로 정리됩니다.",
            ])

        def score_line() -> str:
            return f"최종 예상 점수는 {blue_name} {blue_total}점, {red_name} {red_total}점입니다."

        def rounds_line() -> str:
            base = self._scorecard_rounds_line(scorecard)
            if base:
                return base
            return "라운드별 유효타 흐름을 기준으로 점수가 정리됩니다."

        def decisive_line() -> str:
            top_round_line = self._scorecard_top_round_line(scorecard)
            if top_round_line:
                return top_round_line
            if winner_side in ("blue", "red") and big_total[winner_side] >= big_total["red" if winner_side == "blue" else "blue"] + 2:
                return pick("decisive-bigs", [
                    "큰 타격 숫자에서 차이가 났고, 그 장면들이 경기 인상에 강하게 남았습니다.",
                    "결정적인 다운은 없었더라도, 강한 정타의 질에서 차이가 났습니다.",
                ])
            return pick("decisive-small", [
                "한 장면으로 끝난 경기라기보다, 작은 정타와 라운드 운영이 쌓인 경기였습니다.",
                "승부를 가른 건 한 번의 폭발보다, 라운드마다 만든 유효타가 쌓인 흐름이었습니다.",
                "마지막까지 점수표가 바빴던 경기였습니다.",
            ])

        def damage_line() -> str:
            if winner_side in ("blue", "red"):
                other = "red" if winner_side == "blue" else "blue"
                dmg_gap = dealt_total[winner_side] - dealt_total[other]
                if dmg_gap >= 55.0:
                    return pick("damage-clear", [
                        f"전체 데미지 흐름에서도 {winner_name} 쪽 유효타가 더 많이 쌓였습니다.",
                        "총 데미지와 큰 타격 흐름을 같이 보면 승부의 방향이 꽤 분명했습니다.",
                    ])
                if abs(dmg_gap) < 25.0 and not stoppage:
                    return pick("damage-close", [
                        "총 데미지 자체는 크게 벌어지지 않았지만, 라운드별로 가져간 장면과 감점 차이가 승부를 갈랐습니다.",
                        "데미지 차이는 크지 않았고, 점수는 라운드 운영과 다운 여부에서 갈렸습니다.",
                    ])
            return pick("damage-balanced", [
                "전체 데미지 흐름은 라운드별로 조금씩 나뉘었고, 한쪽이 모든 구간을 지배한 경기는 아니었습니다.",
                "유효타와 큰 타격이 서로 다른 라운드에 나뉘면서 경기 전체 흐름이 복잡하게 흘렀습니다.",
            ])

        def total_record_line() -> str:
            return (
                f"전체 기록은 {blue_name} 유효타 {hit_total['blue']}회, 총 데미지 {int(round(dealt_total['blue']))}, "
                f"{red_name} 유효타 {hit_total['red']}회, 총 데미지 {int(round(dealt_total['red']))}로 정리됩니다."
            )

        def impact_record_line() -> str:
            blue_events = big_total["blue"] + stun_for["blue"] + kd_for["blue"] + counter_total["blue"]
            red_events = big_total["red"] + stun_for["red"] + kd_for["red"] + counter_total["red"]
            if blue_events == 0 and red_events == 0:
                return "큰 위기 장면은 많지 않았고, 경기의 무게는 잔타와 라운드 운영 쪽에 더 실렸습니다."
            return (
                f"위험 장면만 보면 {blue_name} 강타 {big_total['blue']}회, 스턴 {stun_for['blue']}회, 다운 {kd_for['blue']}회, 카운터 {counter_total['blue']}회, "
                f"{red_name} 강타 {big_total['red']}회, 스턴 {stun_for['red']}회, 다운 {kd_for['red']}회, 카운터 {counter_total['red']}회입니다."
            )

        def weak_line() -> str:
            return self._scorecard_weak_final_line(scorecard)

        def gauge_line() -> str:
            return self._scorecard_gauge_final_line(scorecard, damage_path)

        def tactical_line() -> str:
            if stoppage and loser_name:
                return pick("tactical-stop", [
                    f"{self._josa(loser_name, '은/는')} 회복할 시간을 만들지 못했고, 같은 라운드 안에서 위기가 반복된 것이 치명적이었습니다.",
                    "위기가 한 번으로 끝나지 않고 반복되면서, 결국 경기를 버티기 어려운 흐름으로 이어졌습니다.",
                ])
            if winner_name:
                return pick("tactical-win", [
                    f"결국 {self._josa(winner_name, '은/는')} 더 좋은 라운드를 더 많이 만들었고, 복싱식 점수 계산에서도 앞서는 경기였습니다.",
                    "결국 더 많은 라운드에서 유효타와 안정적인 운영을 만든 쪽이 승리를 가져가는 경기였습니다.",
                    "점수로 보면 큰 한 방만이 아니라, 라운드 운영과 쌓인 데미지가 함께 작용했습니다.",
                ])
            return pick("tactical-draw", [
                "라운드별로 서로 가져간 구간이 나뉘었고, 어느 한쪽이 확실히 앞섰다고 보기 어려운 흐름이었습니다.",
                "결과적으로 큰 차이 없이 맞선 경기였고, 라운드별 세부 장면을 다시 봐야 할 정도로 접전이었습니다.",
                "마지막까지 쉽게 정리되지 않는 경기였습니다.",
            ])

        # Pattern selection: stoppage / clear decision / close decision / draw.
        margin = abs(blue_total - red_total)
        if stoppage:
            pattern_name = "stoppage"
            order = [result_line, score_line, rounds_line, total_record_line, impact_record_line, decisive_line, damage_line, gauge_line, weak_line, tactical_line]
        elif winner_side == "draw" or margin <= 1:
            pattern_name = "close"
            order = [result_line, score_line, rounds_line, total_record_line, impact_record_line, damage_line, decisive_line, gauge_line, weak_line, tactical_line]
        elif margin >= 3:
            pattern_name = "clear"
            order = [result_line, score_line, total_record_line, impact_record_line, damage_line, rounds_line, decisive_line, gauge_line, weak_line, tactical_line]
        else:
            pattern_name = "decision"
            order = [result_line, score_line, rounds_line, total_record_line, impact_record_line, decisive_line, damage_line, gauge_line, weak_line, tactical_line]

        lines = [x for x in (fn() for fn in order) if str(x or "").strip()]
        # Long enough to feel like a real post-fight recap, but capped so it does not talk forever.
        max_lines = 12 if pattern_name != "stoppage" else 10
        text = " ".join(lines[:max_lines]).strip()
        logging.info(
            "SPECTATORLOG_SCORECARD_FINAL blue=%s red=%s winner=%s rounds=%s pattern=%s lines=%s",
            blue_total, red_total, winner_side, len(results), pattern_name, len(lines[:max_lines]),
        )
        return text

    def _read_damage_update(self, path: str, fast_only: bool = False) -> dict:
        if not os.path.exists(path):
            return {}
        # Fast path: round_time/head/glove files can change many times per second.
        # Do not rescan the full damage_events.txt unless that file itself changed.
        cur_sig = (0, 0)
        try:
            cur_sig = self._file_sig(path)
            if fast_only:
                if bool(self._damage_initialized) and cur_sig == tuple(getattr(self, "_last_fast_damage_update_sig", (0, 0)) or (0, 0)):
                    return {}
                self._last_fast_damage_update_sig = cur_sig
            else:
                pending_sig = tuple(getattr(self, "_fast_pending_damage_sig", (0, 0)) or (0, 0))
                if bool(self._damage_initialized) and cur_sig == tuple(getattr(self, "_last_damage_update_sig", (0, 0)) or (0, 0)) and pending_sig != cur_sig:
                    return {}
                self._last_damage_update_sig = cur_sig
        except Exception:
            pass
        blue_dealt = 0.0
        red_dealt = 0.0
        effect_counts = {
            "blue": {"stun": 0, "knockdown": 0, "tko": 0},
            "red": {"stun": 0, "knockdown": 0, "tko": 0},
        }
        latest: Optional[dict] = None
        latest_receiver_side = ""
        latest_effect_kind = ""
        parsed_events: List[dict] = []
        rows = 0
        try:
            with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            return {}
        for line in lines:
            line = str(line or "").strip()
            if not line:
                continue
            parts = line.split("\t")
            latest = self._parse_damage_event_parts(parts)
            if not latest:
                continue
            try:
                damage = float(latest.get("damage", 0.0) or 0.0)
            except Exception:
                continue
            corner = str(latest.get("receiver_side") or "").strip().lower()
            damage_type = str(latest.get("damage_type") or "").strip()
            attacker_side = str(latest.get("attacker_side") or "").strip().lower()
            if corner == "red":
                blue_dealt += damage
            elif corner == "blue":
                red_dealt += damage
            else:
                continue
            rows += 1
            parsed_events.append(latest)
            latest_receiver_side = corner
            effect_kind = self._damage_effect_kind(damage_type)
            latest_effect_kind = effect_kind
            if effect_kind:
                effect_counts[corner][effect_kind] = int(effect_counts[corner].get(effect_kind, 0)) + 1

        out: Dict[str, Any] = {}
        was_damage_initialized = bool(self._damage_initialized)
        file_reset_detected = False
        if was_damage_initialized:
            prev_blue = float(self._damage_file_last_dealt.get("blue", 0.0) or 0.0)
            prev_red = float(self._damage_file_last_dealt.get("red", 0.0) or 0.0)
            if blue_dealt + 0.001 < prev_blue or red_dealt + 0.001 < prev_red:
                file_reset_detected = True
                self._damage_total_offset["blue"] = float(self._damage_total_offset.get("blue", 0.0) or 0.0) + prev_blue
                self._damage_total_offset["red"] = float(self._damage_total_offset.get("red", 0.0) or 0.0) + prev_red
                self._seen_damage_event_keys = set()
                self._last_effect_counts = {
                    "blue": {"stun": 0, "knockdown": 0, "tko": 0},
                    "red": {"stun": 0, "knockdown": 0, "tko": 0},
                }
                self._reset_down_state_machine()
        stun_sides = []
        effect_events = []
        active_round_no = self._last_fight_round_no or self._last_round_time_round or 1
        self._ensure_down_round(active_round_no)
        if was_damage_initialized:
            for side in ("blue", "red"):
                for kind in ("stun", "knockdown", "tko"):
                    prev = int((self._last_effect_counts.get(side, {}) or {}).get(kind, 0) or 0)
                    cur = int((effect_counts.get(side, {}) or {}).get(kind, 0) or 0)
                    if cur > prev:
                        for _i in range(cur - prev):
                            item = {"side": side, "kind": kind}
                            if kind == "knockdown":
                                item["round_down_count"] = self._register_knockdown(side, active_round_no)
                            effect_events.append(item)
                        if kind in ("knockdown", "tko"):
                            self._punishment_mid_forced_until[side] = time.time() + (30.0 if kind == "tko" else 8.0)
                        if kind == "stun":
                            stun_sides.append(side)
        self._last_effect_counts = effect_counts
        self._last_stun_counts = {side: int(effect_counts.get(side, {}).get("stun", 0) or 0) for side in ("blue", "red")}
        self._damage_initialized = True
        if effect_events:
            out["spectator_effect_events"] = effect_events
        new_events: List[dict] = []
        if parsed_events:
            current_keys = set()
            for ev in parsed_events:
                key = self._damage_event_key(ev)
                current_keys.add(key)
                if was_damage_initialized and (file_reset_detected or key not in self._seen_damage_event_keys):
                    ev = dict(ev)
                    ev["seen_at"] = time.time()
                    ev["effect_kind"] = self._damage_effect_kind(str(ev.get("damage_type", "") or ""))
                    new_events.append(ev)
                    self._recent_damage_events.append(ev)
            self._seen_damage_event_keys = set(list(current_keys)[:600])
        if new_events:
            self._last_damage_seen_at = time.time()
        if not was_damage_initialized:
            self._damage_total_offset["blue"] = 0.0
            self._damage_total_offset["red"] = 0.0
        self._damage_file_last_dealt["blue"] = float(blue_dealt)
        self._damage_file_last_dealt["red"] = float(red_dealt)
        self._total_damage_dealt["blue"] = float(self._damage_total_offset.get("blue", 0.0) or 0.0) + float(blue_dealt)
        self._total_damage_dealt["red"] = float(self._damage_total_offset.get("red", 0.0) or 0.0) + float(red_dealt)
        out["blue_damage_dealt"] = round(float(self._total_damage_dealt.get("blue", 0.0) or 0.0), 2)
        out["red_damage_dealt"] = round(float(self._total_damage_dealt.get("red", 0.0) or 0.0), 2)
        out["blue_round_damage_dealt"] = round(float(blue_dealt), 2)
        out["red_round_damage_dealt"] = round(float(red_dealt), 2)
        hit_effect_events = []
        # Screen-space hit sparks use damage_events.screen_x/y first because the
        # SpectatorLog format defines them as the actual hit location. Attack glove
        # pose is only a fallback for old/malformed rows without screen coordinates.
        if was_damage_initialized:
            root_dir = os.path.dirname(os.path.dirname(path))
            for ev in new_events:
                try:
                    dmg = float(ev.get("damage", 0.0) or 0.0)
                except Exception:
                    dmg = 0.0
                side = str(ev.get("receiver_side") or "").lower()
                attacker_side = str(ev.get("attacker_side") or "").lower()
                pose = self._fallback_hit_screen_pose(ev)
                glove = {}
                if str((pose or {}).get("source") or "") != "hit":
                    glove = self._pick_attacking_glove_pose(root_dir, attacker_side, ev)
                    if glove and glove.get("screen_x") is not None and glove.get("screen_y") is not None:
                        pose = dict(glove or {})
                        pose["source"] = str(pose.get("source") or "glove_fallback")
                sx = pose.get("screen_x")
                sy = pose.get("screen_y")
                try:
                    sx = None if sx is None or sx == "" else float(sx)
                except Exception:
                    sx = None
                try:
                    sy = None if sy is None or sy == "" else float(sy)
                except Exception:
                    sy = None
                if side in ("blue", "red") and dmg > 0.0 and sx is not None and sy is not None:
                    try:
                        hit_time = round(float(ev.get("time", 0.0) or 0.0), 3)
                    except Exception:
                        hit_time = 0.0
                    hitfx_key = "%s|%.2f|%.4f|%.4f|%.3f|%s" % (side, float(round(dmg, 2)), float(round(sx, 4)), float(round(sy, 4)), float(hit_time), str(ev.get("punch") or ""))
                    hit_effect_events.append({
                        "side": side,
                        "attacker_side": attacker_side,
                        "damage": round(dmg, 2),
                        "punch": str(ev.get("punch") or ""),
                        "weak_point": str(ev.get("weak_point") or ""),
                        "effect_kind": str(ev.get("effect_kind") or ""),
                        "counter_mult": round(float(ev.get("counter_mult", 1.0) or 1.0), 3),
                        "is_counter": self._is_counter_event(ev),
                        "screen_x": round(sx, 4),
                        "screen_y": round(sy, 4),
                        "coord_source": str(pose.get("source") or "hit"),
                        "glove_hand": str((glove or {}).get("hand") or ""),
                        "event_time": hit_time,
                        "hitfx_key": hitfx_key,
                        "hitfx_detect_perf_ms": time.perf_counter() * 1000.0,
                        "hitfx_detect_wall_ms": time.time() * 1000.0,
                    })
        if hit_effect_events:
            try:
                DIAG.record("spectator_hit_effect_events", count=len(hit_effect_events), first=dict(hit_effect_events[0] or {}))
            except Exception:
                pass
            out["spectator_hit_effect_events"] = hit_effect_events
            if bool(getattr(self.cfg, "spectator_hit_effect_fast_emit", True)) and not fast_only:
                try:
                    self._safe_emit_update({
                        "spectator_hit_effect_events": list(hit_effect_events),
                        "_hitfx_fast_emit": True,
                    })
                    if bool(getattr(self.cfg, "spectator_hit_effect_latency_log", True)):
                        logging.info("HITFX_FAST_EMIT count=%s keys=%s", len(hit_effect_events), ",".join(str(x.get("hitfx_key") or "") for x in hit_effect_events[:5]))
                except Exception:
                    logging.exception("HITFX_FAST_EMIT_FAIL")

        if fast_only:
            # Hand the same new rows to the full pass so TTS/commentary/report
            # logic does not miss them after the hot path has already emitted FX.
            try:
                self._fast_pending_damage_sig = tuple(cur_sig or (0, 0))
                self._fast_pending_new_events = [dict(x or {}) for x in list(new_events or [])]
                self._fast_pending_effect_events = [dict(x or {}) for x in list(effect_events or [])]
            except Exception:
                self._fast_pending_damage_sig = (0, 0)
                self._fast_pending_new_events = []
                self._fast_pending_effect_events = []
            if new_events:
                try:
                    out["latest_hit"] = dict(new_events[-1])
                except Exception:
                    pass
            out["_damage_fast_only"] = True
            return out

        try:
            pending_sig = tuple(getattr(self, "_fast_pending_damage_sig", (0, 0)) or (0, 0))
            if pending_sig == tuple(cur_sig or (0, 0)):
                pending_events = [dict(x or {}) for x in list(getattr(self, "_fast_pending_new_events", []) or [])]
                pending_effects = [dict(x or {}) for x in list(getattr(self, "_fast_pending_effect_events", []) or [])]
                if pending_events and not new_events:
                    new_events = pending_events
                    logging.info("SPECTATORLOG_FAST_HANDOFF_COMMENTARY events=%s effects=%s", len(pending_events), len(pending_effects))
                if pending_effects and not effect_events:
                    effect_events = pending_effects
                self._fast_pending_damage_sig = (0, 0)
                self._fast_pending_new_events = []
                self._fast_pending_effect_events = []
        except Exception:
            logging.debug("SPECTATORLOG_FAST_HANDOFF_FAIL", exc_info=True)

        punishment_snapshot = self._punishment_snapshot(path)
        self._remember_punishment_snapshot(punishment_snapshot)
        try:
            self._record_scorecard_events(new_events, active_round_no, path, punishment_snapshot)
        except Exception:
            logging.exception("SPECTATORLOG_SCORECARD_RECORD_FAIL")
        combo_info = self._build_combo_update(new_events)
        counter_commentary = ""
        combo_commentary = ""
        if combo_info:
            counter_commentary = str(combo_info.pop("_counter_commentary_text", "") or "").strip()
            combo_commentary = str(combo_info.pop("_combo_commentary_text", "") or "").strip()
            out["combo_info"] = combo_info
        event_commentary, event_role = ("", "")
        down_plan = self._build_knockdown_commentary_plan(effect_events, new_events, active_round_no, punishment_snapshot)
        if down_plan:
            out["commentary_tts_text"] = str(down_plan.get("text") or "")
            out["commentary_tts_role"] = "caster"
            followups = list(down_plan.get("followups") or [])
            if followups:
                out["commentary_tts_followups"] = followups
            out["spectator_down_state"] = {
                "side": str(down_plan.get("side") or ""),
                "round": int(active_round_no or 1),
                "count": int(down_plan.get("count") or 0),
            }
            self._commentary_last_at = time.time()
        elif new_events:
            event_commentary, event_role = self._build_fight_summary_commentary(new_events, effect_events, path, punishment_snapshot)
        if event_commentary and event_role == "caster" and "commentary_tts_text" not in out:
            out["commentary_tts_text"] = event_commentary
            out["commentary_tts_role"] = "caster"
            self._commentary_last_at = time.time()
        priority_commentary = counter_commentary or combo_commentary
        if priority_commentary and "commentary_tts_text" not in out and bool(getattr(self.cfg, "spectator_commentary_enabled", False)):
            out["commentary_tts_text"] = priority_commentary
            out["commentary_tts_role"] = "analyst"
            self._commentary_last_at = time.time()
        if new_events and event_commentary and "commentary_tts_text" not in out:
            commentary, role = event_commentary, event_role
            now = time.time()
            try:
                cooldown = max(0.0, float(getattr(self.cfg, "spectator_commentary_cooldown_sec", 6.0)))
            except Exception:
                cooldown = 6.0
            if role == "analyst" and str(getattr(self.cfg, "spectator_commentary_mode", "standard") or "standard").lower() == "active":
                cooldown = min(cooldown, 3.5)
            if now - float(self._commentary_last_at or 0.0) >= max(0.0, cooldown):
                out["commentary_tts_text"] = commentary
                out["commentary_tts_role"] = role or "analyst"
                self._commentary_last_at = now
        if new_events:
            try:
                out["latest_hit"] = dict(min(new_events, key=lambda e: float(e.get("time", 0.0) or 0.0)))
            except Exception:
                out["latest_hit"] = dict(new_events[-1])
        elif latest:
            out["latest_hit"] = latest
            commentary, role = self._build_fight_summary_commentary(new_events, effect_events, path, punishment_snapshot) if "commentary_tts_text" not in out else ("", "")
            if commentary:
                now = time.time()
                try:
                    cooldown = max(0.0, float(getattr(self.cfg, "spectator_commentary_cooldown_sec", 6.0)))
                except Exception:
                    cooldown = 6.0
                urgent = role == "caster"
                if urgent or now - float(self._commentary_last_at or 0.0) >= max(0.0, cooldown):
                    out["commentary_tts_text"] = commentary
                    out["commentary_tts_role"] = role or "analyst"
                    self._commentary_last_at = now
        if rows:
            logging.debug(
                "SPECTATORLOG_DAMAGE rows=%s blue_dealt=%.2f red_dealt=%.2f effects=%s",
                rows,
                blue_dealt,
                red_dealt,
                ",".join([f"{e.get('side')}:{e.get('kind')}" for e in effect_events]),
            )
        return out

    def _build_combo_update(self, new_events: List[dict]) -> dict:
        if not new_events:
            return {}
        combo_min_damage = 15.0
        break_damage = 20.0
        max_gap = 0.8
        counter_prev_damage = COUNTER_PREV_DAMAGE_THRESHOLD
        counter_damage = COUNTER_DEALT_DAMAGE_THRESHOLD
        counter_window = COUNTER_WINDOW_SEC
        info: Dict[str, str] = {}
        state = dict(getattr(self, "_combo_state", {}) or {})
        changed = False
        last_counter_event = dict(getattr(self, "_last_counter_event", None) or {})
        for ev in sorted(list(new_events or []), key=lambda e: float(e.get("time", 0.0) or 0.0), reverse=True):
            attacker = str(ev.get("attacker_side") or "").lower()
            receiver = str(ev.get("receiver_side") or "").lower()
            if attacker not in ("blue", "red") or receiver not in ("blue", "red"):
                continue
            try:
                dmg = float(ev.get("damage", 0.0) or 0.0)
            except Exception:
                dmg = 0.0
            try:
                t = float(ev.get("time", 0.0) or 0.0)
            except Exception:
                t = 0.0

            # Counter source of truth is shared with reports/commentary:
            # explicit log counter, whiff punish within the window, or light-hit reversal.
            try:
                counter_hit = self._is_counter_event(ev)
            except Exception:
                counter_hit = False

            active_attacker = str(state.get("attacker_side") or "")
            active_receiver = str(state.get("receiver_side") or "")

            # A counter-hit below break_damage does not break the active combo.
            if (
                active_attacker in ("blue", "red")
                and active_receiver in ("blue", "red")
                and attacker == active_receiver
                and receiver == active_attacker
                and dmg < break_damage
            ):
                last_counter_event = dict(ev)
                continue

            if (
                active_attacker in ("blue", "red")
                and active_receiver in ("blue", "red")
                and attacker == active_receiver
                and receiver == active_attacker
                and dmg >= break_damage
            ):
                if int(state.get("count", 0) or 0) >= 2:
                    info[f"{active_attacker}_combo_hit_text"] = ""
                    info[f"{active_attacker}_combo_damage_text"] = ""
                    changed = True
                state = {"attacker_side": "", "receiver_side": "", "last_time": None, "count": 0, "damage": 0.0}

            if dmg < combo_min_damage:
                continue

            last_time = state.get("last_time", None)
            same_chain = (
                state.get("attacker_side") == attacker
                and state.get("receiver_side") == receiver
                and last_time is not None
                and abs(t - float(last_time or 0.0)) <= max_gap
            )
            if same_chain:
                prev_count = int(state.get("count", 0) or 0)
                count = int(state.get("count", 0) or 0) + 1
                total = float(state.get("damage", 0.0) or 0.0) + dmg
            else:
                prev_count = 0
                old_attacker = str(state.get("attacker_side") or "")
                if old_attacker in ("blue", "red") and int(state.get("count", 0) or 0) >= 2:
                    info[f"{old_attacker}_combo_hit_text"] = ""
                    info[f"{old_attacker}_combo_damage_text"] = ""
                    changed = True
                count = 1
                total = dmg
            state = {
                "attacker_side": attacker,
                "receiver_side": receiver,
                "last_time": t,
                "count": count,
                "damage": total,
            }
            if count >= 2:
                info[f"{attacker}_combo_hit_text"] = f"{count} HIT COMBO"
                info[f"{attacker}_combo_damage_text"] = f"{int(round(total))} DAMAGE"
                if prev_count < 2:
                    info["_combo_commentary_text"] = self._commentary_pick(f"combo:{attacker}:{receiver}:{count}:{int(total)}", [
                        "좋은 콤보가 적중합니다.",
                        "연타가 깔끔하게 이어집니다.",
                        "방어가 늦었습니다. 콤보가 들어갑니다.",
                        "공격 흐름을 끊기지 않고 이어갑니다.",
                    ])
                changed = True
            elif changed:
                info[f"{attacker}_combo_hit_text"] = ""
                info[f"{attacker}_combo_damage_text"] = ""
            if counter_hit:
                info[f"{attacker}_combo_hit_text"] = "COUNTER"
                info[f"{attacker}_combo_damage_text"] = f"{int(round(dmg))} DAMAGE"
                info["_counter_commentary_text"] = self._commentary_pick(f"counter:{attacker}:{receiver}:{int(dmg)}", [
                    "카운터가 적중됩니다.",
                    "정확한 반격 타이밍입니다.",
                    "들어오는 순간을 받아쳤습니다.",
                    "좋은 카운터입니다.",
                ])
                changed = True
            last_counter_event = dict(ev)
        self._combo_state = state
        self._last_counter_event = last_counter_event if last_counter_event else None
        return info if changed or info else {}

    def _fmt_float_text(self, value: str, scale: float = 100.0) -> str:
        try:
            return f"{float(str(value or '0').strip()) * scale:.0f}%"
        except Exception:
            return "0%"

    def _punishment_percent(self, value: str, scale: float = 100.0) -> float:
        try:
            return max(0.0, min(100.0, float(str(value or "0").strip()) * scale))
        except Exception:
            return 0.0

    def _read_pose_file(self, path: str) -> dict:
        sig = self._file_sig(path)
        cached = (self._pose_file_cache or {}).get(path)
        if cached and tuple(cached.get("sig") or (0, 0)) == sig:
            return dict(cached.get("data") or {})
        raw = self._read_text(path)
        parts = str(raw or "").strip().split()
        data: Dict[str, Any] = {}
        if len(parts) >= 5:
            try:
                data = {
                    "screen_x": float(parts[0]),
                    "screen_y": float(parts[1]),
                    "world_x": float(parts[2]),
                    "world_y": float(parts[3]),
                    "world_z": float(parts[4]),
                }
            except Exception:
                data = {}
        self._pose_file_cache[path] = {"sig": sig, "data": dict(data)}
        return dict(data)

    def _parse_accessibility_text(self, raw: str) -> dict:
        text = str(raw or "").strip()
        if not text:
            return {}
        out: Dict[str, Any] = {"raw": text}
        m = re.search(r"\[Accessibility\]\s*(blue|red)?\s*\(([^)]*)\)\s*:\s*(.*)$", text, re.IGNORECASE)
        body = text
        if m:
            out["side"] = str(m.group(1) or "").lower()
            out["name"] = str(m.group(2) or "").strip()
            body = str(m.group(3) or "")
        for km in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^,\s]+)", body):
            key = km.group(1)
            val = km.group(2)
            low = str(val).strip().lower()
            if low in ("true", "false"):
                out[key] = low == "true"
            else:
                try:
                    out[key] = float(val)
                except Exception:
                    out[key] = val
        enabled = bool(out.get("enabled", False))
        allow_slaps = bool(out.get("allowSlaps", False))
        out["enabled"] = enabled
        out["allowSlaps"] = allow_slaps
        return out

    def _read_glove_pose(self, root: str, side: str, hand: str) -> dict:
        hand_key = "left" if str(hand or "").lower().startswith("l") else "right"
        path = os.path.join(root, side, f"glove_{hand_key}_position.txt")
        pose = self._read_pose_file(path)
        if pose:
            pose["hand"] = hand_key
            pose["source"] = "glove"
        return pose

    def _pick_attacking_glove_pose(self, root: str, attacker_side: str, ev: dict) -> dict:
        attacker_side = str(attacker_side or "").lower()
        if attacker_side not in ("blue", "red"):
            return {}
        ev_hand = str((ev or {}).get("hand") or "").strip().lower()
        if ev_hand.startswith(("l", "r")):
            direct = self._read_glove_pose(root, attacker_side, "left" if ev_hand.startswith("l") else "right")
            if direct and direct.get("screen_x") is not None and direct.get("screen_y") is not None:
                direct = dict(direct)
                direct["attacker_side"] = attacker_side
                direct["source"] = "glove_hand"
                return direct
        left = self._read_glove_pose(root, attacker_side, "left")
        right = self._read_glove_pose(root, attacker_side, "right")
        if not left and not right:
            return {}

        def _dist_sq(glove: dict) -> Optional[float]:
            try:
                gx = float(glove.get("world_x"))
                gy = float(glove.get("world_y"))
                gz = float(glove.get("world_z"))
                ex = float(ev.get("world_x"))
                ey = float(ev.get("world_y"))
                ez = float(ev.get("world_z"))
                return (gx - ex) ** 2 + (gy - ey) ** 2 + (gz - ez) ** 2
            except Exception:
                return None

        left_d = _dist_sq(left) if left else None
        right_d = _dist_sq(right) if right else None
        if left_d is not None and right_d is not None:
            chosen = left if left_d <= right_d else right
        elif left_d is not None:
            chosen = left
        elif right_d is not None:
            chosen = right
        else:
            punch = re.sub(r"[^a-z]+", "", str(ev.get("punch") or "").lower())
            if any(tok in punch for tok in ("left", "lead", "jab")) and left:
                chosen = left
            elif any(tok in punch for tok in ("right", "rear", "cross", "overhand")) and right:
                chosen = right
            else:
                chosen = left or right
        chosen = dict(chosen or {})
        if chosen:
            chosen["attacker_side"] = attacker_side
        return chosen

    def _fallback_hit_screen_pose(self, ev: dict) -> dict:
        side = str(ev.get("receiver_side") or "").lower()
        weak = str(ev.get("weak_point") or "").strip().lower()
        punch = str(ev.get("punch") or "").strip().lower()
        sx = ev.get("screen_x")
        sy = ev.get("screen_y")
        try:
            sx = None if sx in (None, "") else float(sx)
        except Exception:
            sx = None
        try:
            sy = None if sy in (None, "") else float(sy)
        except Exception:
            sy = None
        if sx is not None and sy is not None:
            return {"screen_x": sx, "screen_y": sy, "source": "hit"}
        base_x = 0.37 if side == "blue" else 0.63
        x = base_x
        y = 0.58
        if any(k in weak for k in ("temple", "관자")):
            x += -0.03 if ("left" in weak or "왼" in weak) else (0.03 if ("right" in weak or "오른" in weak) else 0.0)
            y = 0.40
        elif any(k in weak for k in ("chin", "jaw", "턱")):
            y = 0.46
        elif any(k in weak for k in ("nose", "코")):
            y = 0.39
        elif any(k in weak for k in ("head", "face", "eye", "안면")):
            y = 0.42
        elif any(k in weak for k in ("solar", "명치")):
            y = 0.54
        elif any(k in weak for k in ("liver", "간")):
            x += 0.03 if side == "blue" else -0.03
            y = 0.60
        elif any(k in weak for k in ("body", "stomach", "gut", "rib", "복", "갈비", "몸통")):
            y = 0.58
        if any(k in punch for k in ("jab", "cross", "straight", "스트레이트")):
            x += -0.01 if side == "blue" else 0.01
        elif any(k in punch for k in ("hook", "훅")):
            x += 0.015 if side == "blue" else -0.015
        elif any(k in punch for k in ("upper", "uppercut", "어퍼")):
            y -= 0.015
        return {"screen_x": max(0.08, min(0.92, x)), "screen_y": max(0.12, min(0.88, y)), "source": "fallback"}

    def _read_side_info(self, root: str, side: str) -> dict:
        """Read only realtime HUD fields.

        Position/cosmetics files are constantly rewritten by the game.  Keep the
        hot path focused on punishment values, but also read accessibility.txt
        because it is small and useful for fairness/condition display.
        """
        base = os.path.join(root, side)
        mid = self._read_text(os.path.join(base, "punishment_mid.txt"))
        long_weighted = self._read_text(os.path.join(base, "punishment_long_weighted.txt"))
        out = {"meta_text": ""}
        has_mid = str(mid or "").strip() != ""
        has_long = str(long_weighted or "").strip() != ""
        if has_mid or has_long:
            out["punishment_text"] = f"PUN M {self._fmt_float_text(mid)} L {self._fmt_float_text(long_weighted)}"
            if has_mid:
                out["punishment_mid"] = self._punishment_percent(mid)
            if has_long:
                out["punishment_long"] = self._punishment_percent(long_weighted)
        acc_path = os.path.join(base, "accessibility.txt")
        acc_raw = self._read_text(acc_path)
        acc = self._parse_accessibility_text(acc_raw)
        if acc:
            out["accessibility"] = acc
            enabled = bool(acc.get("enabled", False))
            allow_slaps = bool(acc.get("allowSlaps", False))
            if enabled or allow_slaps:
                flags = []
                if enabled:
                    flags.append("ACCESSIBILITY ON")
                if allow_slaps:
                    flags.append("SLAPS ON")
                out["meta_text"] = " · ".join(flags)
        return out

    def _read_log_info(self, root: str, state_raw: str, round_raw: str, time_raw: str, camera_raw: str, damage_update: dict) -> dict:
        blue = self._read_side_info(root, "blue")
        red = self._read_side_info(root, "red")
        latest = (damage_update or {}).get("latest_hit") or {}
        recent = ""
        blue_recent = ""
        red_recent = ""
        if latest:
            side = str(latest.get("attacker_side") or "").lower()
            recent = self._format_recent_hit_text(latest)
            if side == "blue":
                blue_recent = recent
            elif side == "red":
                red_recent = recent
        cam_parts = str(camera_raw or "").split("\t")
        camera_text = ""
        if len(cam_parts) >= 3:
            camera_text = f"CAM pos {cam_parts[0].strip()} | fov {cam_parts[2].strip()}"
        elif camera_raw:
            camera_text = f"CAM {camera_raw}"
        info = {
            "match_text": "",
            "recent_hit_text": "",
            "blue_recent_hit_text": blue_recent,
            "red_recent_hit_text": red_recent,
            "blue_meta_text": blue.get("meta_text", ""),
            "red_meta_text": red.get("meta_text", ""),
            "blue_accessibility": blue.get("accessibility", {}),
            "red_accessibility": red.get("accessibility", {}),
            "camera_text": camera_text,
        }
        for side, data in (("blue", blue), ("red", red)):
            if "punishment_text" in data:
                info[f"{side}_punishment_text"] = data.get("punishment_text", "")
            if "punishment_mid" in data:
                info[f"{side}_punishment_mid"] = data.get("punishment_mid", 0.0)
            if "punishment_long" in data:
                info[f"{side}_punishment_long"] = data.get("punishment_long", 0.0)
        now = time.time()
        for side in ("blue", "red"):
            if now <= float((self._punishment_mid_forced_until or {}).get(side, 0.0) or 0.0):
                info[f"{side}_punishment_mid"] = 100.0
                old = str(info.get(f"{side}_punishment_text", "") or "")
                if old:
                    info[f"{side}_punishment_text"] = re.sub(r"PUN M\s+\d+%", "PUN M 100%", old)
                else:
                    info[f"{side}_punishment_text"] = "PUN M 100%"
        return info


# Controller
# -----------------------------
