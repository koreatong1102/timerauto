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


COUNTER_PREV_DAMAGE_THRESHOLD = 25.0
COUNTER_DEALT_DAMAGE_THRESHOLD = 40.0
COUNTER_WINDOW_SEC = 0.8


def default_spectatorlog_path_resolver(path: str = "") -> str:
    raw = str(path or "").strip()
    return os.path.abspath(raw) if raw else os.path.abspath(os.path.join("ThrillOfTheFight2", "SpectatorLog"))


def default_game_id_normalizer(value: str, allow: str) -> str:
    allow_set = set(str(allow or ""))
    return "".join(ch for ch in str(value or "").upper().strip() if ch in allow_set)


def default_player_gid_canonicalizer(_cfg: Any, gid: str, threshold: int = 70) -> str:
    return str(gid or "").upper().strip()


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
        self._last_stun_counts: Dict[str, int] = {"blue": 0, "red": 0}
        self._last_effect_counts: Dict[str, Dict[str, int]] = {
            "blue": {"stun": 0, "knockdown": 0, "tko": 0},
            "red": {"stun": 0, "knockdown": 0, "tko": 0},
        }
        self._damage_initialized = False
        self._total_damage_dealt: Dict[str, float] = {"blue": 0.0, "red": 0.0}
        self._damage_total_offset: Dict[str, float] = {"blue": 0.0, "red": 0.0}
        self._damage_file_last_dealt: Dict[str, float] = {"blue": 0.0, "red": 0.0}
        self._seen_damage_event_keys: set = set()
        self._recent_damage_events: deque[dict] = deque(maxlen=80)
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
        self._round_time_mode: str = "elapsed"
        self._last_round_state: str = ""
        self._last_round_intro_key: Tuple[Optional[int], str] = (None, "")
        self._last_caster_event_key: Tuple[str, Optional[int], str] = ("", None, "")
        self._last_fight_round_no: Optional[int] = None
        self._last_active_match_pair: Tuple[str, str] = ("", "")
        self._last_vs_intro_pair: Tuple[str, str] = ("", "")
        self._last_synced_seconds_left: Optional[int] = None
        self._last_fight_seconds_left: Optional[int] = None
        self._last_rest_seconds_left: Optional[int] = None
        self._commentary_last_at = 0.0
        self._punishment_mid_forced_until: Dict[str, float] = {"blue": 0.0, "red": 0.0}
        self._change_event = threading.Event()
        self._change_thread: Optional[threading.Thread] = None
        self._change_root: str = ""
        self._change_handle: Optional[int] = None

    def start(self):
        if self.is_running():
            return
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop_event,), daemon=True)
        self._running = True
        self._thread.start()

    def stop(self):
        try:
            self._stop_event.set()
        except Exception:
            pass
        self._stop_change_notifier()
        self._running = False

    def force_refresh(self):
        self._last_signature = tuple()
        self._image_mtimes = {}
        self._reset_portrait_locks()

    def is_running(self) -> bool:
        return bool(self._running and self._thread and self._thread.is_alive())

    def _run(self, stop_event: threading.Event):
        try:
            while not stop_event.is_set():
                if not bool(getattr(self.cfg, "spectatorlog_enabled", False)):
                    stop_event.wait(0.25)
                    continue
                root = self._resolve_spectatorlog_path(str(getattr(self.cfg, "spectatorlog_path", "") or ""))
                if not os.path.isdir(root):
                    self.status_update.emit("SpectatorLog 폴더 없음")
                    self._stop_change_notifier()
                    stop_event.wait(1.0)
                    continue
                self._ensure_change_notifier(root, stop_event)
                try:
                    update = self._read_update(root)
                    if update:
                        self.ui_update.emit(update)
                except Exception:
                    logging.exception("SPECTATORLOG_READ_FAIL")
                fallback = max(0.25, min(5.0, float(getattr(self.cfg, "spectatorlog_poll_ms", 250) or 250) / 1000.0))
                self._change_event.wait(fallback)
                self._change_event.clear()
        finally:
            self._stop_change_notifier()
            if self._thread == threading.current_thread():
                self._running = False

    def _ensure_change_notifier(self, root: str, stop_event: threading.Event) -> None:
        root = os.path.abspath(str(root or ""))
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
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
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
            self._normalize_game_id(str(blue_raw or ""), self.cfg.ocr.allow_chars),
            self._normalize_game_id(str(red_raw or ""), self.cfg.ocr.allow_chars),
        )

    def _name_payload(self, raw_name: str) -> Tuple[str, str, bool, bool]:
        name = str(raw_name or "").strip()
        gid = self._canonical_player_gid_for_cfg(
            self.cfg,
            self._normalize_game_id(name, self.cfg.ocr.allow_chars),
            threshold=70,
        )
        registered = bool(gid and gid in (self.cfg.players or {}))
        display = str((self.cfg.players or {}).get(gid) or name or gid)
        return gid, display, registered, bool(gid)

    def _read_update(self, root: str) -> dict:
        blue_name_raw = self._read_text(os.path.join(root, "blue", "name.txt"))
        red_name_raw = self._read_text(os.path.join(root, "red", "name.txt"))
        round_raw = self._read_text(os.path.join(root, "match", "round_number.txt"))
        time_raw = self._read_text(os.path.join(root, "match", "round_time.txt"))
        state_raw = self._read_text(os.path.join(root, "match", "round_state.txt"))
        camera_raw = self._read_text(os.path.join(root, "match", "camera.txt"))

        b_img_path = os.path.join(root, "blue", "portrait.png")
        r_img_path = os.path.join(root, "red", "portrait.png")
        dmg_path = os.path.join(root, "match", "damage_events.txt")
        self._unlock_portrait_if_player_changed("blue", blue_name_raw)
        self._unlock_portrait_if_player_changed("red", red_name_raw)
        b_img_changed, b_img = self._read_image_if_changed("blue", b_img_path)
        r_img_changed, r_img = self._read_image_if_changed("red", r_img_path)
        dmg_sig = self._file_sig(dmg_path)

        sig = (
            blue_name_raw,
            red_name_raw,
            round_raw,
            time_raw,
            state_raw,
            camera_raw,
            self._image_mtimes.get("blue"),
            self._image_mtimes.get("red"),
            dmg_sig,
        )
        if sig == self._last_signature:
            return {}
        self._last_signature = sig

        out: Dict[str, Any] = {}
        sync_players = bool(getattr(self.cfg, "spectatorlog_sync_players", True))
        if sync_players:
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

        try:
            round_no = int(float(round_raw)) if round_raw else None
        except Exception:
            round_no = None
        try:
            elapsed = float(time_raw) if time_raw else None
        except Exception:
            elapsed = None
        state = self._normalize_round_state(state_raw)
        prev_round_state = self._last_round_state
        pair_key = self._match_pair_key(blue_name_raw, red_name_raw)
        pair_ready = bool(pair_key[0] and pair_key[1])
        if self._is_match_intro_state(state_raw) and prev_round_state != "intro":
            self._reset_portrait_locks()
            self._reset_damage_session(dmg_path)
            self._last_fight_round_no = None
            out["spectator_sp_reset"] = True
            out["spectator_match_stats_reset"] = True
        if self._is_match_intro_state(state_raw) and pair_ready:
            if pair_key != self._last_active_match_pair and pair_key != self._last_vs_intro_pair:
                out["vs_intro_event"] = True
                self._last_vs_intro_pair = pair_key
                self._set_caster_event_once(out, "vs", round_no, "intro", self._build_vs_caster_text())
        elif state in ("fight", "break", "results", "end") and pair_ready:
            self._last_active_match_pair = pair_key
        if round_no is not None:
            if state == "fight":
                self._last_fight_round_no = max(1, int(round_no or 1))
            caster_round_no = round_no
            if state in ("break", "results", "end", "cancel") and self._last_fight_round_no is not None:
                caster_round_no = self._last_fight_round_no
            intro_key = (round_no, state)
            if state == "fight" and prev_round_state != "fight" and intro_key != self._last_round_intro_key:
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
                    self._round_caster_text("start", round_no, getattr(self.cfg, "timer_total_rounds", 3)),
                )
            if state == "break" and prev_round_state != "break":
                self._set_caster_event_once(
                    out,
                    "break",
                    caster_round_no,
                    state,
                    self._round_caster_text("break", caster_round_no, getattr(self.cfg, "timer_total_rounds", 3)),
                )
            if state == "results" and prev_round_state != "results":
                self._set_caster_event_once(out, "results", caster_round_no, state, self._round_caster_text("results", caster_round_no))
            if state == "end" and prev_round_state != "end":
                out["spectator_match_clear"] = True
                self._set_caster_event_once(out, "end", caster_round_no, state, self._round_caster_text("end", caster_round_no))
            if state == "cancel" and prev_round_state != "cancel":
                out["spectator_match_clear"] = True
                self._set_caster_event_once(out, "cancel", caster_round_no, state, self._round_caster_text("cancel", caster_round_no))
            if state:
                self._last_round_state = state
        sync_timer = bool(getattr(self.cfg, "spectatorlog_sync_timer", False))
        if sync_timer and round_no is not None:
            out["round_current"] = max(1, round_no)
            out["round_total"] = int(getattr(self.cfg, "timer_total_rounds", 3) or 3)
        if sync_timer and state:
            self._set_rest_state_for_log(out, state == "break")
        if sync_timer and elapsed is not None:
            # Keep match time and break time separate. Non-fight states often export
            # their own counters, so they must not overwrite the last fight clock.
            seconds_left = None
            if state == "fight" or not state:
                seconds_left = int(max(0.0, elapsed))
                self._last_fight_seconds_left = int(seconds_left)
                self._last_synced_seconds_left = int(seconds_left)
                self._last_round_time_value = elapsed
                self._last_round_time_round = round_no
                self._round_time_mode = "fight_sync"
            elif state == "break":
                seconds_left = int(max(0.0, elapsed))
                self._last_rest_seconds_left = int(seconds_left)
                self._round_time_mode = "break_rest"
            elif state in ("knockdown", "foul", "results", "cancel", "intro", "end"):
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
        elif sync_timer and state in ("knockdown", "foul", "results", "cancel", "intro", "end"):
            seconds_left = self._last_fight_seconds_left
            if seconds_left is None:
                seconds_left = self._last_synced_seconds_left
            if seconds_left is not None:
                out["seconds_left"] = int(max(0, seconds_left))
                out["spectator_time_mode"] = f"{state}_hold_no_time"

        damage_update = self._read_damage_update(dmg_path)
        if damage_update:
            out.update(damage_update)
        log_info = self._read_log_info(root, state_raw, round_raw, time_raw, camera_raw, damage_update)
        if log_info and isinstance(damage_update.get("combo_info"), dict):
            log_info.update(damage_update.get("combo_info") or {})
        if log_info:
            out["spectator_log_info"] = log_info

        if out:
            logging.info(
                "SPECTATORLOG_APPLY root=%s sync_timer=%s blue=%s red=%s round_raw=%s time_raw=%s state_raw=%s state=%s mode=%s rest=%s seconds_left=%s keys=%s",
                root,
                sync_timer,
                blue_name_raw,
                red_name_raw,
                round_raw,
                time_raw,
                state_raw,
                state,
                out.get("spectator_time_mode", ""),
                out.get("spectator_rest_mode", None),
                out.get("seconds_left", None),
                sorted(out.keys()),
            )
        return out

    def _reset_damage_session(self, damage_path: Optional[str] = None) -> None:
        self._damage_initialized = False
        self._total_damage_dealt = {"blue": 0.0, "red": 0.0}
        self._damage_total_offset = {"blue": 0.0, "red": 0.0}
        self._damage_file_last_dealt = {"blue": 0.0, "red": 0.0}
        self._seen_damage_event_keys = set()
        self._recent_damage_events.clear()
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
            if len(parts) < 10:
                continue
            try:
                damage = float(parts[1])
                t = float(parts[0])
            except Exception:
                continue
            receiver = str(parts[2] or "").strip().lower()
            if receiver == "red":
                attacker = "BLUE"
                attacker_side = "blue"
            elif receiver == "blue":
                attacker = "RED"
                attacker_side = "red"
            else:
                continue
            damage_type = str(parts[9] or "").strip()
            ev = {
                "time": t,
                "attacker": attacker,
                "receiver": receiver.upper(),
                "receiver_side": receiver,
                "attacker_side": attacker_side,
                "damage": damage,
                "punch": str(parts[8] or "").strip(),
                "damage_type": damage_type,
                "weak_point": str(parts[10] or "").strip() if len(parts) > 10 else "",
            }
            events.append(ev)
            kind = self._damage_effect_kind(damage_type)
            if kind:
                effect_counts[receiver][kind] = int(effect_counts[receiver].get(kind, 0) or 0) + 1
        return events, effect_counts

    def _normalize_round_state(self, raw: str) -> str:
        s = re.sub(r"[^a-z0-9]+", "", str(raw or "").strip().lower())
        if not s:
            return ""
        if "matchintro" in s or s.endswith("intro") or s == "intro":
            return "intro"
        if "roundfight" in s or s == "fight":
            return "fight"
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
        gid = self._canonical_player_gid_for_cfg(
            self.cfg,
            self._normalize_game_id(raw, self.cfg.ocr.allow_chars),
            threshold=70,
        )
        return str((self.cfg.players or {}).get(gid) or "").strip() if gid else ""

    def _short_spoken_id(self, raw: str, fallback: str) -> str:
        token = re.split(r"[\s\.,_#@\-]+", str(raw or "").strip(), maxsplit=1)[0].strip()
        token = re.sub(r"[^0-9A-Za-z가-힣]+", "", token).strip()
        if not token:
            return fallback
        if re.search(r"[가-힣]", token):
            return token
        key = token.lower()
        # Korean Edge TTS spells many all-caps IDs letter by letter. Prefer known Korean call names.
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
        }
        if key in aliases:
            return aliases[key]
        if len(key) <= 3 or re.search(r"\d", key):
            return fallback
        return key

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
            "templeleft": "관자놀이",
            "templeright": "관자놀이",
            "liver": "복부",
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

    def _ko_subject(self, name: str) -> str:
        text = str(name or "").strip()
        if not text:
            return ""
        ch = text[-1]
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            return text + ("이" if (code - 0xAC00) % 28 else "가")
        return text + "가"

    def _format_recent_hit_text(self, ev: dict) -> str:
        ev = dict(ev or {})
        punch = self._punch_ko(str(ev.get("punch", "") or "").strip())
        if not punch:
            punch = str(ev.get("punch", "") or "").strip()
        try:
            damage = int(round(float(ev.get("damage", 0.0) or 0.0)))
        except Exception:
            damage = 0
        head = f"{punch} {damage}".strip()
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
                    out[side][key] = float(self._read_text(os.path.join(base, filename)) or 0.0)
                except Exception:
                    out[side][key] = 0.0
        return out

    def _build_fight_summary_commentary(self, new_events: List[dict], effect_events: List[dict], damage_path: str) -> Tuple[str, str]:
        if not bool(getattr(self.cfg, "spectator_commentary_enabled", False)):
            return "", ""
        if effect_events:
            last = effect_events[-1] or {}
            kind = str(last.get("kind") or "")
            side = str(last.get("side") or "")
            if kind == "tko":
                return f"{self._caster_name(side)}, 테크니컬 녹아웃 당합니다", "caster"
            if kind == "knockdown":
                return f"{self._caster_name(side)}, 다운 당합니다", "caster"
            if kind == "stun":
                return "크게 흔들립니다!", "caster"

        mode = str(getattr(self.cfg, "spectator_commentary_mode", "standard") or "standard").lower()
        if mode == "quiet":
            return "", ""
        if not new_events:
            return "", ""

        now = time.time()
        recent = [e for e in list(self._recent_damage_events) if now - float(e.get("seen_at", now) or now) <= 3.0]
        if not recent:
            recent = list(new_events)

        by_attacker = {"blue": {"damage": 0.0, "count": 0}, "red": {"damage": 0.0, "count": 0}}
        weak_counts: Dict[str, int] = {}
        max_ev = max(recent, key=lambda e: float(e.get("damage", 0.0) or 0.0))
        for ev in recent:
            attacker = str(ev.get("attacker_side") or "")
            if attacker in by_attacker:
                by_attacker[attacker]["damage"] += float(ev.get("damage", 0.0) or 0.0)
                by_attacker[attacker]["count"] += 1
            weak = self._weak_point_ko(str(ev.get("weak_point", "") or ""))
            if weak:
                weak_counts[weak] = weak_counts.get(weak, 0) + 1

        punish = self._read_punishment_values(damage_path)
        danger_side = ""
        for side in ("blue", "red"):
            mid = float((punish.get(side) or {}).get("mid", 0.0) or 0.0)
            long_w = float((punish.get(side) or {}).get("long_weighted", 0.0) or 0.0)
            if long_w >= 0.65 and mid >= 0.45:
                danger_side = side
                break
            if mid >= 0.65:
                danger_side = side
                break
        if danger_side:
            if float((punish.get(danger_side) or {}).get("long_weighted", 0.0) or 0.0) >= 0.65:
                return "누적 데미지가 부담됩니다", "analyst"
            return "이번 교전에서 체력이 크게 빠집니다", "analyst"

        try:
            min_damage = float(getattr(self.cfg, "spectator_commentary_min_damage", 25.0) or 25.0)
        except Exception:
            min_damage = 25.0
        max_damage = float(max_ev.get("damage", 0.0) or 0.0)
        if max_damage >= max(45.0, min_damage + 10.0):
            weak = self._weak_point_ko(str(max_ev.get("weak_point", "") or ""))
            punch = self._punch_ko(str(max_ev.get("punch", "") or ""))
            if weak:
                return f"{weak}에 큰 타격", "analyst"
            if punch:
                return f"큰 {punch}였습니다", "analyst"
            return "큰 타격", "analyst"

        repeated_weak = ""
        for weak, count in weak_counts.items():
            if count >= 2:
                repeated_weak = weak
                break
        if repeated_weak:
            return f"{repeated_weak} 쪽 데미지가 누적됩니다", "analyst"

        blue = by_attacker["blue"]
        red = by_attacker["red"]
        if blue["count"] >= 3 and blue["damage"] >= max(35.0, min_damage):
            return f"{self._ko_subject(self._commentary_name('blue'))} 교전을 가져갑니다", "analyst"
        if red["count"] >= 3 and red["damage"] >= max(35.0, min_damage):
            return f"{self._ko_subject(self._commentary_name('red'))} 교전을 가져갑니다", "analyst"
        if max(blue["count"], red["count"]) >= 3:
            return "연타가 들어갔습니다", "analyst"
        return "", ""

    def _read_damage_update(self, path: str) -> dict:
        if not os.path.exists(path):
            return {}
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
            if len(parts) < 10:
                continue
            try:
                damage = float(parts[1])
            except Exception:
                continue
            corner = str(parts[2] or "").strip().lower()
            damage_type = str(parts[9] or "").strip()
            if corner == "red":
                blue_dealt += damage
                attacker = "BLUE"
                attacker_side = "blue"
            elif corner == "blue":
                red_dealt += damage
                attacker = "RED"
                attacker_side = "red"
            else:
                continue
            rows += 1
            try:
                t = float(parts[0])
            except Exception:
                t = 0.0
            latest = {
                "time": t,
                "attacker": attacker,
                "receiver": corner.upper(),
                "receiver_side": corner,
                "attacker_side": attacker_side,
                "damage": damage,
                "punch": str(parts[8] or "").strip(),
                "damage_type": damage_type,
                "weak_point": str(parts[10] or "").strip() if len(parts) > 10 else "",
            }
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
        stun_sides = []
        effect_events = []
        if was_damage_initialized:
            for side in ("blue", "red"):
                for kind in ("stun", "knockdown", "tko"):
                    prev = int((self._last_effect_counts.get(side, {}) or {}).get(kind, 0) or 0)
                    cur = int((effect_counts.get(side, {}) or {}).get(kind, 0) or 0)
                    if cur > prev:
                        for _i in range(cur - prev):
                            effect_events.append({"side": side, "kind": kind})
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
        try:
            hit_threshold = max(0.0, float(getattr(self.cfg, "spectator_hit_effect_damage", 45.0) or 45.0))
        except Exception:
            hit_threshold = 45.0
        if was_damage_initialized and hit_threshold > 0:
            for ev in new_events:
                try:
                    dmg = float(ev.get("damage", 0.0) or 0.0)
                except Exception:
                    dmg = 0.0
                side = str(ev.get("receiver_side") or "").lower()
                if side in ("blue", "red") and dmg >= hit_threshold:
                    hit_effect_events.append({
                        "side": side,
                        "attacker_side": str(ev.get("attacker_side") or "").lower(),
                        "damage": dmg,
                        "punch": str(ev.get("punch") or ""),
                        "weak_point": str(ev.get("weak_point") or ""),
                        "effect_kind": str(ev.get("effect_kind") or ""),
                    })
        if hit_effect_events:
            out["spectator_hit_effect_events"] = hit_effect_events
        combo_info = self._build_combo_update(new_events)
        counter_commentary = ""
        combo_commentary = ""
        if combo_info:
            counter_commentary = str(combo_info.pop("_counter_commentary_text", "") or "").strip()
            combo_commentary = str(combo_info.pop("_combo_commentary_text", "") or "").strip()
            out["combo_info"] = combo_info
        priority_commentary = counter_commentary or combo_commentary
        if priority_commentary and bool(getattr(self.cfg, "spectator_commentary_enabled", False)):
            out["commentary_tts_text"] = priority_commentary
            out["commentary_tts_role"] = "analyst"
            self._commentary_last_at = time.time()
        if new_events:
            try:
                out["latest_hit"] = dict(sorted(new_events, key=lambda e: float(e.get("time", 0.0) or 0.0))[-1])
            except Exception:
                out["latest_hit"] = dict(new_events[-1])
        elif latest:
            out["latest_hit"] = latest
            commentary, role = self._build_fight_summary_commentary(new_events, effect_events, path)
            if commentary:
                now = time.time()
                try:
                    cooldown = float(getattr(self.cfg, "spectator_commentary_cooldown_sec", 6.0) or 6.0)
                except Exception:
                    cooldown = 6.0
                urgent = role == "caster"
                if urgent or now - float(self._commentary_last_at or 0.0) >= max(0.0, cooldown):
                    out["commentary_tts_text"] = commentary
                    out["commentary_tts_role"] = role or "analyst"
                    self._commentary_last_at = now
        if rows:
            logging.info(
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
        for ev in sorted(list(new_events or []), key=lambda e: float(e.get("time", 0.0) or 0.0)):
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

            counter_hit = False
            try:
                prev_t = float(last_counter_event.get("time", -9999.0))
                prev_dmg = float(last_counter_event.get("damage", 0.0) or 0.0)
            except Exception:
                prev_t = -9999.0
                prev_dmg = 0.0
            if (
                str(last_counter_event.get("attacker_side") or "").lower() == receiver
                and str(last_counter_event.get("receiver_side") or "").lower() == attacker
                and prev_dmg >= counter_prev_damage
                and dmg >= counter_damage
                and 0.0 <= (t - prev_t) <= counter_window
            ):
                counter_hit = True

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
                    info["_combo_commentary_text"] = "좋은 콤보가 적중합니다"
                changed = True
            elif changed:
                info[f"{attacker}_combo_hit_text"] = ""
                info[f"{attacker}_combo_damage_text"] = ""
            if counter_hit:
                info[f"{attacker}_combo_hit_text"] = "COUNTER"
                info[f"{attacker}_combo_damage_text"] = f"{int(round(dmg))} DAMAGE"
                info["_counter_commentary_text"] = "카운터가 적중됩니다!"
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

    def _read_side_info(self, root: str, side: str) -> dict:
        base = os.path.join(root, side)
        mid = self._read_text(os.path.join(base, "punishment_mid.txt"))
        long_raw = self._read_text(os.path.join(base, "punishment_long_raw.txt"))
        long_weighted = self._read_text(os.path.join(base, "punishment_long_weighted.txt"))
        acc = self._read_text(os.path.join(base, "accessibility.txt"))
        cosmetics = self._read_text(os.path.join(base, "cosmetics.txt"))
        head = self._read_text(os.path.join(base, "head_position.txt"))
        left = self._read_text(os.path.join(base, "glove_left_position.txt"))
        right = self._read_text(os.path.join(base, "glove_right_position.txt"))
        gear = []
        for line in cosmetics.splitlines():
            parts = [p.strip() for p in line.split(":")]
            if len(parts) >= 2:
                gear.append(f"{parts[0]}={parts[1]}")
        def pos2(raw: str) -> str:
            vals = str(raw or "").split()
            if len(vals) >= 2:
                return f"{vals[0]},{vals[1]}"
            return "-"
        out = {
            "meta_text": f"{'; '.join(gear[:4])} | head {pos2(head)} L {pos2(left)} R {pos2(right)} | {acc}",
        }
        has_mid = str(mid or "").strip() != ""
        has_long = str(long_weighted or "").strip() != ""
        if has_mid or has_long:
            out["punishment_text"] = f"PUN M {self._fmt_float_text(mid)} L {self._fmt_float_text(long_weighted)}"
            if has_mid:
                out["punishment_mid"] = self._punishment_percent(mid)
            if has_long:
                out["punishment_long"] = self._punishment_percent(long_weighted)
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
