from __future__ import annotations

import time
import threading
import logging
import re
import ctypes
import subprocess
import sys
import os
import tempfile
import asyncio
from queue import Queue, Empty
from collections import deque
from typing import List, Optional, Deque, Tuple

from PyQt6.QtCore import QObject, QTimer

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except Exception:
    HAS_PYAUTOGUI = False
    pyautogui = None

try:
    import edge_tts
    HAS_EDGE_TTS = True
except Exception:
    HAS_EDGE_TTS = False
    edge_tts = None


class ActionRunner(QObject):
    def __init__(self, controller, timer_win, status_cb):
        super().__init__()
        self._controller = controller
        self._timer_win = timer_win
        self._status_cb = status_cb
        self._actions: List[dict] = []
        self._index = 0
        self._running = False
        self._pending_action: Optional[dict] = None
        self._run_key: Optional[str] = None
        self._queue: Deque[Tuple[List[dict], Optional[str]]] = deque()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._next)
        self._tts_queue: Queue[Tuple[str, int, int, int, float, str]] = Queue()
        self._tts_worker_lock = threading.Lock()
        self._tts_worker: Optional[threading.Thread] = None
        self._matchup_wait_lock = threading.Lock()
        self._matchup_wait_active = False
        self._matchup_last_spoken_sig = ""
        self._matchup_last_spoken_at = 0.0
        self._runner_tag = f"{id(self):x}"[-6:]
        self._start_tts_worker()

    def run(self, actions: List[dict], key: Optional[str] = None):
        actions_list = list(actions or [])
        if not actions_list:
            try:
                logging.info("RUNNER_RESET key=%s reason=empty_actions", key)
            except Exception:
                pass
            self._actions = []
            self._index = 0
            self._running = False
            self._timer.stop()
            self._pending_action = None
            self._run_key = None
            self._queue.clear()
            return
        if self._running:
            # Prevent queue explosion for repeated pixel timer_start events.
            if self._should_skip_duplicate_timer_start(actions_list, key):
                try:
                    logging.info("RUNNER_SKIP_DUP_TIMER_START key=%s", key)
                except Exception:
                    pass
                return
            # Queue every trigger while running.
            # Dedup-by-key made repeated on_trigger events appear as "only first run works".
            self._queue.append((actions_list, key))
            try:
                logging.info("RUNNER_QUEUE key=%s queued_count=%s queue_size=%s", key, len(actions_list), len(self._queue))
            except Exception:
                pass
            return
        try:
            logging.info("RUNNER_START key=%s action_count=%s", key, len(actions_list))
        except Exception:
            pass
        self._start_run(actions_list, key)

    def _has_timer_start(self, actions_list: List[dict]) -> bool:
        for act in actions_list or []:
            if str((act or {}).get("type", "")).lower() == "timer_start":
                return True
        return False

    def _should_skip_duplicate_timer_start(self, actions_list: List[dict], key: Optional[str]) -> bool:
        if not key:
            return False
        if not str(key).startswith("pixel"):
            return False
        if not self._has_timer_start(actions_list):
            return False
        if self._run_key == key and self._has_timer_start(self._actions):
            return True
        for queued_actions, queued_key in self._queue:
            if queued_key == key and self._has_timer_start(queued_actions):
                return True
        return False

    def _start_run(self, actions_list: List[dict], key: Optional[str]) -> None:
        self._actions = list(actions_list)
        self._index = 0
        self._running = True
        self._pending_action = None
        self._run_key = key
        self._timer.stop()
        try:
            logging.info("RUNNER_EXEC_BEGIN key=%s count=%s", key, len(self._actions))
        except Exception:
            pass
        self._next()

    def _next(self):
        if self._pending_action is not None:
            action = self._pending_action
            self._pending_action = None
            delay_ms = self._execute(action)
            if delay_ms is None:
                delay_ms = 0
            self._timer.start(max(0, int(delay_ms)))
            return
        if self._index >= len(self._actions):
            self._running = False
            try:
                logging.info("RUNNER_EXEC_DONE key=%s", self._run_key)
            except Exception:
                pass
            self._run_key = None
            if self._queue:
                next_actions, next_key = self._queue.popleft()
                self._start_run(next_actions, next_key)
            return
        action = self._actions[self._index] or {}
        self._index += 1
        pre_delay = action.get("pre_delay_ms", 0)
        if pre_delay:
            try:
                logging.info("RUNNER_PRE_DELAY key=%s ms=%s type=%s", self._run_key, int(pre_delay), str(action.get("type", "")))
            except Exception:
                pass
            self._pending_action = action
            self._timer.start(max(0, int(pre_delay)))
            return
        delay_ms = self._execute(action)
        if delay_ms is None:
            delay_ms = 0
        self._timer.start(max(0, int(delay_ms)))

    def _execute(self, action: dict) -> int:
        global HAS_PYAUTOGUI, pyautogui
        atype = str(action.get("type", "")).lower()
        try:
            logging.info("ACTION_EXEC key=%s type=%s", self._run_key, atype)
        except Exception:
            pass
        if atype == "delay_ms":
            return int(action.get("ms", 0))

        try:
            if atype in ("key_press", "key_down", "key_up", "hotkey", "type_text",
                         "mouse_move", "mouse_click", "mouse_down", "mouse_up"):
                if not HAS_PYAUTOGUI:
                    # Try lazy import in case the bundle contains it but startup import failed.
                    try:
                        import pyautogui as _pyautogui  # type: ignore
                        pyautogui = _pyautogui
                        HAS_PYAUTOGUI = True
                    except Exception as e:
                        self._status_cb("pyautogui ?꾩슂: pip install pyautogui")
                        try:
                            logging.warning("Action blocked: pyautogui missing (type=%s) err=%s", atype, e)
                        except Exception:
                            pass
                        return int(action.get("post_delay_ms", 0))
                self._run_input_action(atype, action)
            elif atype == "timer_start":
                self._timer_win.timer_start()
            elif atype == "timer_stop":
                self._timer_win.timer_stop()
            elif atype == "timer_reset":
                self._timer_win.timer_reset()
            elif atype == "timer_set":
                self._timer_win.set_round_time(
                    action.get("round_current", None),
                    action.get("round_total", None),
                    action.get("seconds_left", None),
                )
            elif atype == "blue_win_plus":
                if self._timer_win is not None:
                    self._timer_win.add_win("blue")
            elif atype == "red_win_plus":
                if self._timer_win is not None:
                    self._timer_win.add_win("red")
            elif atype == "tts_en":
                self._run_tts(action)
            elif atype == "matchup_tts_en":
                self._run_matchup_tts(action)
            elif atype == "ocr_refresh":
                self._controller.on_screen_trigger_for_names()
            elif atype == "koth_winner_ocr":
                if hasattr(self._controller, "run_koth_winner_ocr"):
                    self._controller.run_koth_winner_ocr()
            elif atype == "palette_capture":
                self._controller.read_palette_test_once()
        except Exception as e:
            try:
                logging.exception("ACTION_EXEC_FAIL key=%s type=%s err=%s", self._run_key, atype, e)
            except Exception:
                pass
            try:
                self._status_cb(f"?≪뀡 ?ㅻ쪟({atype}): {e}")
            except Exception:
                pass
        return int(action.get("post_delay_ms", 0))

    def drop_pending_timer_start(self):
        def _has_timer_start(actions_list: List[dict]) -> bool:
            for act in actions_list or []:
                if str(act.get("type", "")).lower() == "timer_start":
                    return True
            return False

        if self._queue:
            self._queue = deque([(acts, key) for acts, key in self._queue if not _has_timer_start(acts)])

        if self._running and self._actions:
            keep_head = self._actions[:self._index]
            tail = [a for a in self._actions[self._index:] if str(a.get("type", "")).lower() != "timer_start"]
            self._actions = keep_head + tail

        if self._pending_action and str(self._pending_action.get("type", "")).lower() == "timer_start":
            self._pending_action = None

    def _run_input_action(self, atype: str, action: dict):
        def _resolve_xy(x_val, y_val):
            x = ensure_int(x_val)
            y = ensure_int(y_val)
            if x is None or y is None:
                return None, None
            use_mon = action.get("use_monitor", False)
            if not use_mon:
                return x, y
            mon = action.get("monitor", None)
            try:
                mon = int(mon) if mon is not None else int(getattr(self._controller.cfg, "monitor_index", 1))
            except Exception:
                mon = 1
            return _to_screen_xy(x, y, mon)

        if atype == "key_press":
            key = action.get("key", "")
            hold_ms = int(action.get("hold_ms", 0))
            if hold_ms > 0:
                pyautogui.keyDown(key)
                time.sleep(hold_ms / 1000.0)
                pyautogui.keyUp(key)
            else:
                pyautogui.press(key)
        elif atype == "key_down":
            pyautogui.keyDown(action.get("key", ""))
        elif atype == "key_up":
            pyautogui.keyUp(action.get("key", ""))
        elif atype == "hotkey":
            keys = action.get("keys", [])
            if isinstance(keys, list):
                pyautogui.hotkey(*keys)
        elif atype == "type_text":
            text = action.get("text", "")
            interval_ms = int(action.get("interval_ms", 0))
            pyautogui.typewrite(text, interval=interval_ms / 1000.0)
        elif atype == "mouse_move":
            x = int(action.get("x", 0))
            y = int(action.get("y", 0))
            duration_ms = int(action.get("duration_ms", 0))
            rx, ry = _resolve_xy(x, y)
            if rx is not None and ry is not None:
                x, y = rx, ry
            pyautogui.moveTo(x, y, duration=duration_ms / 1000.0)
        elif atype == "mouse_click":
            x = ensure_int(action.get("x", None))
            y = ensure_int(action.get("y", None))
            button = action.get("button", "left")
            clicks = int(action.get("clicks", 1))
            interval_ms = int(action.get("interval_ms", 0))
            if x is not None and y is not None:
                rx, ry = _resolve_xy(x, y)
                if rx is not None and ry is not None:
                    x, y = rx, ry
                move_ms = int(action.get("move_ms", action.get("move_duration_ms", 0)) or 0)
                move_delay_ms = int(action.get("move_delay_ms", 30) or 0)
                pyautogui.moveTo(x, y, duration=move_ms / 1000.0)
                if move_delay_ms > 0:
                    time.sleep(move_delay_ms / 1000.0)
                pyautogui.click(x=x, y=y, clicks=clicks, interval=interval_ms / 1000.0, button=button)
            else:
                pyautogui.click(clicks=clicks, interval=interval_ms / 1000.0, button=button)
        elif atype == "mouse_down":
            x = ensure_int(action.get("x", None))
            y = ensure_int(action.get("y", None))
            button = action.get("button", "left")
            if x is not None and y is not None:
                rx, ry = _resolve_xy(x, y)
                if rx is not None and ry is not None:
                    x, y = rx, ry
                pyautogui.mouseDown(x=x, y=y, button=button)
            else:
                pyautogui.mouseDown(button=button)
        elif atype == "mouse_up":
            x = ensure_int(action.get("x", None))
            y = ensure_int(action.get("y", None))
            button = action.get("button", "left")
            if x is not None and y is not None:
                rx, ry = _resolve_xy(x, y)
                if rx is not None and ry is not None:
                    x, y = rx, ry
                pyautogui.mouseUp(x=x, y=y, button=button)
            else:
                pyautogui.mouseUp(button=button)

    def _run_tts(self, action: dict):
        if not self._ensure_tts_ready():
            return
        text = str(action.get("text", "")).strip()
        if not text:
            return
        rate = int(action.get("rate", 200))
        volume = float(action.get("volume", 100))
        voice_mode = str(action.get("voice_mode", "auto") or "auto").strip().lower()
        try:
            logging.info("TTS_ENQUEUE type=tts_en rate=%s volume=%.1f voice_mode=%s text=%s", rate, volume, voice_mode, self._log_text(text))
        except Exception:
            pass
        self._enqueue_tts(text, rate, repeat=1, gap_ms=0, volume=volume, voice_mode=voice_mode)

    def _run_matchup_tts(self, action: dict):
        if not self._ensure_tts_ready():
            return
        template = str(
            action.get("text", "")
            or action.get("template", "")
            or "{blue} versus {red}, the match will begin shortly."
        ).strip()
        repeat = max(1, int(action.get("repeat", 1) or 1))
        rate = int(action.get("rate", 200))
        gap_ms = max(0, int(action.get("repeat_gap_ms", 200) or 200))
        volume = float(action.get("volume", 100))
        voice_mode = str(action.get("voice_mode", "auto") or "auto").strip().lower()
        wait_sec = float(action.get("wait_sec", 8.0) or 8.0)
        # Default to edge-like behavior for matchup: speak only after text changes
        # from the baseline captured at trigger time to avoid announcing stale names.
        require_change = bool(action.get("require_change", True))
        immediate_if_ready = bool(action.get("immediate_if_ready", False))
        repeat_same_after_sec = float(action.get("repeat_same_after_sec", 60.0) or 60.0)
        current_text, baseline_sig = self._compose_matchup_tts_text(template=template)
        if current_text and immediate_if_ready and (not require_change):
            try:
                logging.info("TTS_MATCHUP_IMMEDIATE runner=%s", self._runner_tag)
            except Exception:
                pass
            self._enqueue_tts(
                current_text,
                int(rate),
                repeat=int(repeat),
                gap_ms=int(gap_ms),
                volume=float(volume),
                voice_mode=voice_mode,
            )
            return
        self._schedule_matchup_tts_wait(
            rate=rate,
            repeat=repeat,
            gap_ms=gap_ms,
            wait_sec=wait_sec,
            template=template,
            baseline_sig=baseline_sig,
            volume=volume,
            voice_mode=voice_mode,
            require_change=require_change,
            repeat_same_after_sec=repeat_same_after_sec,
        )

    def _schedule_matchup_tts_wait(
        self,
        rate: int,
        repeat: int,
        gap_ms: int,
        wait_sec: float,
        template: str,
        baseline_sig: str,
        volume: float,
        voice_mode: str,
        require_change: bool = True,
        repeat_same_after_sec: float = 60.0,
    ) -> None:
        with self._matchup_wait_lock:
            if self._matchup_wait_active:
                try:
                    logging.info("TTS_MATCHUP_WAIT_SKIP runner=%s reason=already_waiting", self._runner_tag)
                except Exception:
                    pass
                return
            self._matchup_wait_active = True
        try:
            logging.info(
                "TTS_MATCHUP_WAIT runner=%s wait_sec=%s require_change=%s repeat_same_after_sec=%s baseline=%s",
                self._runner_tag,
                wait_sec,
                require_change,
                repeat_same_after_sec,
                self._log_text(baseline_sig, limit=120),
            )
        except Exception:
            pass

        def _probe():
            try:
                deadline = time.time() + max(0.0, float(wait_sec))
                text = ""
                sig = ""
                last_text = ""
                last_sig = ""
                while time.time() < deadline and not text:
                    text, sig = self._compose_matchup_tts_text(template=template)
                    if text:
                        last_text = text
                        last_sig = sig
                    if text and ((not require_change) or (not baseline_sig or sig != baseline_sig)):
                        break
                    text = ""
                    time.sleep(0.05)
                if not text:
                    now = time.time()
                    allow_repeat = (
                        bool(last_text)
                        and (
                            last_sig != self._matchup_last_spoken_sig
                            or (now - float(self._matchup_last_spoken_at)) >= max(0.0, float(repeat_same_after_sec))
                        )
                    )
                    if allow_repeat:
                        text = last_text
                        sig = last_sig
                        try:
                            logging.info(
                                "TTS_MATCHUP_REPEAT runner=%s sig=%s after_sec=%.3f",
                                self._runner_tag,
                                self._log_text(sig, limit=120),
                                now - float(self._matchup_last_spoken_at),
                            )
                        except Exception:
                            pass
                    else:
                        try:
                            logging.info(
                                "TTS_MATCHUP_SKIP reason=stale_or_not_ready wait_sec=%s baseline=%s",
                                wait_sec,
                                self._log_text(baseline_sig, limit=120),
                            )
                        except Exception:
                            pass
                        return
                try:
                    logging.info(
                        "TTS_ENQUEUE type=matchup(deferred) rate=%s repeat=%s gap_ms=%s volume=%.1f voice_mode=%s text=%s",
                        rate,
                        repeat,
                        gap_ms,
                        volume,
                        voice_mode,
                        self._log_text(text),
                    )
                except Exception:
                    pass
                self._matchup_last_spoken_sig = str(sig or "")
                self._matchup_last_spoken_at = time.time()
                self._enqueue_tts(
                    text,
                    int(rate),
                    repeat=int(repeat),
                    gap_ms=int(gap_ms),
                    volume=float(volume),
                    voice_mode=str(voice_mode or "auto"),
                )
            finally:
                with self._matchup_wait_lock:
                    self._matchup_wait_active = False

        threading.Thread(target=_probe, daemon=True, name="MatchupTTSWait").start()

    def _compose_matchup_tts_text(self, template: str) -> tuple[str, str]:
        blue = ""
        red = ""
        blue_id = ""
        red_id = ""
        try:
            backend = getattr(self._timer_win, "_backend", None)
            if backend is not None:
                blue_name = str(getattr(backend, "blueName", "") or "").strip()
                red_name = str(getattr(backend, "redName", "") or "").strip()
                blue_id = str(getattr(backend, "bluePlayerId", "") or "").strip()
                red_id = str(getattr(backend, "redPlayerId", "") or "").strip()
                players = {}
                try:
                    players = dict(getattr(getattr(self._controller, "cfg", None), "players", {}) or {})
                except Exception:
                    players = {}
                # Priority: mapped nickname by ID -> overlay display name (if differs from ID) -> raw ID.
                blue_nick = str(players.get(str(blue_id).upper(), "") or "").strip() if blue_id else ""
                red_nick = str(players.get(str(red_id).upper(), "") or "").strip() if red_id else ""
                if blue_nick:
                    blue = blue_nick
                elif blue_name and (not blue_id or blue_name.upper() != blue_id.upper()):
                    blue = blue_name
                else:
                    blue = blue_id or blue_name
                if red_nick:
                    red = red_nick
                elif red_name and (not red_id or red_name.upper() != red_id.upper()):
                    red = red_name
                else:
                    red = red_id or red_name
        except Exception:
            blue = ""
            red = ""
            blue_id = ""
            red_id = ""
        blue = str(blue or "").strip()
        red = str(red or "").strip()
        if not blue or not red:
            return "", self._matchup_signature(blue_id, red_id, blue, red)
        tpl = str(template or "").strip() or "{blue} versus {red}, the match will begin shortly."
        # Backward compatibility for legacy placeholder style.
        out = tpl.replace("<blue>", blue).replace("<red>", red)
        out = out.replace("{blue}", blue).replace("{red}", red)
        return out, self._matchup_signature(blue_id, red_id, blue, red)

    def _matchup_signature(
        self,
        blue_id: str = "",
        red_id: str = "",
        blue_text: str = "",
        red_text: str = "",
    ) -> str:
        if not blue_id and not red_id and not blue_text and not red_text:
            try:
                backend = getattr(self._timer_win, "_backend", None)
                if backend is not None:
                    blue_id = str(getattr(backend, "bluePlayerId", "") or "")
                    red_id = str(getattr(backend, "redPlayerId", "") or "")
                    blue_text = str(getattr(backend, "blueName", "") or "")
                    red_text = str(getattr(backend, "redName", "") or "")
            except Exception:
                pass
        return "|".join(
            [
                str(blue_id or "").strip().upper(),
                str(red_id or "").strip().upper(),
                str(blue_text or "").strip().upper(),
                str(red_text or "").strip().upper(),
            ]
        )

    def _edge_voice_for_mode(self, voice_mode: str, text: str) -> str:
        mode = str(voice_mode or "auto").strip().lower()
        raw = str(voice_mode or "").strip()
        if raw and raw.endswith("Neural") and "-" in raw:
            return raw
        wants_ko = self._has_hangul(text)
        if mode in ("en", "english"):
            return "en-US-GuyNeural"
        if mode in ("ko", "korean", "kr"):
            return "ko-KR-SunHiNeural"
        return "ko-KR-SunHiNeural" if wants_ko else "en-US-GuyNeural"

    def _edge_rate(self, rate: int) -> str:
        try:
            pct = int(round((float(rate) - 200.0) / 2.0))
        except Exception:
            pct = 0
        pct = max(-50, min(50, pct))
        return f"{pct:+d}%"

    def _edge_volume(self, volume: float) -> str:
        try:
            pct = int(round(float(volume) - 100.0))
        except Exception:
            pct = 0
        pct = max(-100, min(0, pct))
        return f"{pct:+d}%"

    def _edge_pitch(self, pitch: int = 0) -> str:
        try:
            hz = int(round(float(pitch)))
        except Exception:
            hz = 0
        hz = max(-100, min(100, hz))
        return f"{hz:+d}Hz"

    def _edge_save_cli(self, text: str, path: str, voice: str, rate: str, volume: str, pitch: str = "+0Hz") -> bool:
        try:
            if not self._ensure_tts_ready() or edge_tts is None:
                return False

            async def _save_media():
                communicate = edge_tts.Communicate(
                    str(text or ""),
                    str(voice),
                    rate=str(rate or "+0%"),
                    volume=str(volume or "+0%"),
                    pitch=str(pitch or "+0Hz"),
                )
                await communicate.save(str(path))

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_save_media())
            finally:
                loop.close()
            return os.path.exists(path) and os.path.getsize(path) > 0
        except Exception as e:
            try:
                logging.warning("TTS_EDGE_SAVE_EX runner=%s err=%s", self._runner_tag, e)
            except Exception:
                pass
            return False

    def _play_media_file_blocking(self, path: str, timeout_sec: float = 45.0) -> bool:
        if os.name == "nt":
            return self._play_media_file_mci(path, timeout_sec)
        cmd = [sys.executable, "-c", "import time; time.sleep(0.1)"]
        try:
            run_kwargs = {"capture_output": True, "text": True, "timeout": max(5, int(timeout_sec)), "check": False}
            res = subprocess.run(cmd, **run_kwargs)
            return int(res.returncode) == 0
        except Exception as e:
            try:
                logging.warning("TTS_EDGE_PLAY_EX runner=%s err=%s", self._runner_tag, e)
            except Exception:
                pass
            return False

    def _play_media_file_mci(self, path: str, timeout_sec: float = 45.0) -> bool:
        alias = f"timerauto_tts_{threading.get_ident()}_{int(time.time() * 1000)}"
        path_abs = os.path.abspath(path)
        winmm = ctypes.windll.winmm

        def _mci(cmd: str) -> int:
            return int(winmm.mciSendStringW(str(cmd), None, 0, None))

        try:
            _mci(f'close {alias}')
            err = _mci(f'open "{path_abs}" type mpegvideo alias {alias}')
            if err != 0:
                logging.warning("TTS_MCI_OPEN_FAIL runner=%s code=%s path=%s", self._runner_tag, err, path_abs)
                return False
            err = _mci(f'play {alias} wait')
            if err != 0:
                logging.warning("TTS_MCI_PLAY_FAIL runner=%s code=%s", self._runner_tag, err)
                return False
            return True
        except Exception as e:
            try:
                logging.warning("TTS_MCI_EX runner=%s err=%s", self._runner_tag, e)
            except Exception:
                pass
            return False
        finally:
            try:
                _mci(f'close {alias}')
            except Exception:
                pass

    def _speak_edge_tts(self, text: str, rate: int, volume: float, voice_mode: str) -> bool:
        if not self._ensure_tts_ready():
            return False
        src_text = str(text or "").strip()
        if not src_text:
            return True
        speak_text = self._replace_numbers_for_korean_tts(src_text) if self._has_hangul(src_text) else src_text
        voice = self._edge_voice_for_mode(voice_mode, speak_text)
        edge_rate = self._edge_rate(rate)
        edge_volume = self._edge_volume(volume)
        edge_pitch = self._edge_pitch(0)
        fd, media_path = tempfile.mkstemp(prefix="timerauto_tts_", suffix=".mp3")
        os.close(fd)
        try:
            try:
                logging.info(
                    "TTS_EDGE_SPEAK runner=%s voice=%s rate=%s volume=%s text=%s",
                    self._runner_tag,
                    voice,
                    edge_rate,
                    edge_volume,
                    self._log_text(speak_text),
                )
            except Exception:
                pass
            if not self._edge_save_cli(speak_text, media_path, voice, edge_rate, edge_volume, edge_pitch):
                return False
            ok = self._play_media_file_blocking(media_path)
            if ok:
                try:
                    logging.info("TTS_EDGE_DONE runner=%s text=%s", self._runner_tag, self._log_text(speak_text))
                except Exception:
                    pass
            return bool(ok)
        except Exception as e:
            try:
                logging.warning("TTS_EDGE_FAIL runner=%s err=%s", self._runner_tag, e)
            except Exception:
                pass
            self._safe_status(f"Edge TTS ?ㅻ쪟: {e}")
            return False
        finally:
            try:
                os.remove(media_path)
            except Exception:
                pass

    def _ensure_tts_ready(self) -> bool:
        global HAS_EDGE_TTS, edge_tts
        if HAS_EDGE_TTS and edge_tts is not None:
            return True
        try:
            import edge_tts as _edge_tts
            edge_tts = _edge_tts
            HAS_EDGE_TTS = True
            return True
        except Exception as e:
            logging.warning("TTS_EDGE_UNAVAILABLE runner=%s import_err=%s", self._runner_tag, e)
            self._safe_status(f"Edge TTS 필요: pip install edge-tts ({e})")
            return False
    def _enqueue_tts(
        self,
        text: str,
        rate: int,
        repeat: int = 1,
        gap_ms: int = 0,
        volume: float = 100.0,
        voice_mode: str = "auto",
    ) -> None:
        self._start_tts_worker()
        try:
            self._tts_queue.put(
                (
                    str(text or ""),
                    int(rate),
                    max(1, int(repeat)),
                    max(0, int(gap_ms)),
                    float(max(0.0, min(100.0, float(volume)))),
                    str(voice_mode or "auto").strip().lower(),
                )
            )
            try:
                logging.info("TTS_QUEUE runner=%s size=%s", self._runner_tag, self._tts_queue.qsize())
            except Exception:
                pass
        except Exception as e:
            self._safe_status(f"TTS ???ㅻ쪟: {e}")

    def speak_text(
        self,
        text: str,
        rate: int = 200,
        volume: float = 100.0,
        voice_mode: str = "ko",
    ) -> None:
        self._enqueue_tts(text, rate, repeat=1, gap_ms=0, volume=volume, voice_mode=voice_mode)

    def _tts_worker_loop(self) -> None:
        coinited = False
        try:
            hr = ctypes.windll.ole32.CoInitialize(None)
            coinited = (hr >= 0)
        except Exception:
            coinited = False
        try:
            while True:
                try:
                    text, rate, repeat, gap_ms, volume, voice_mode = self._tts_queue.get(timeout=0.5)
                except Empty:
                    continue
                except Exception:
                    time.sleep(0.05)
                    continue
                if not text:
                    continue
                try:
                    logging.info(
                        "TTS_DEQUEUE runner=%s repeat=%s gap_ms=%s rate=%s volume=%.1f voice_mode=%s text=%s",
                        self._runner_tag,
                        repeat,
                        gap_ms,
                        rate,
                        volume,
                        voice_mode,
                        self._log_text(text),
                    )
                except Exception:
                    pass
                for i in range(max(1, int(repeat))):
                    ok = False
                    for attempt in range(1, 4):
                        try:
                            ok = self._speak_edge_tts(text, int(rate), float(volume), str(voice_mode or "auto"))
                        except Exception as e:
                            try:
                                logging.warning("TTS worker attempt=%s failed: %s", attempt, e)
                            except Exception:
                                pass
                            ok = False
                        if ok:
                            break
                        time.sleep(min(0.4, 0.1 * attempt))
                    if not ok:
                        self._safe_status("Edge TTS ?ъ깮 ?ㅽ뙣")
                        break
                    if i < repeat - 1 and gap_ms > 0:
                        time.sleep(gap_ms / 1000.0)
        except Exception as e:
            try:
                logging.exception("TTS worker crashed: %s", e)
            except Exception:
                pass
            self._safe_status(f"TTS ?뚯빱 ?ㅻ쪟: {e}")
        finally:
            if coinited:
                try:
                    ctypes.windll.ole32.CoUninitialize()
                except Exception:
                    pass
            # Keep TTS available even if worker crashes unexpectedly.
            with self._tts_worker_lock:
                if self._tts_worker is threading.current_thread():
                    self._tts_worker = None
            self._start_tts_worker()

    def _start_tts_worker(self) -> None:
        with self._tts_worker_lock:
            t = self._tts_worker
            if t is not None and t.is_alive():
                return
            self._tts_worker = threading.Thread(target=self._tts_worker_loop, daemon=True, name="TTSWorker")
            self._tts_worker.start()
            try:
                logging.info("TTS_WORKER started runner=%s", self._runner_tag)
            except Exception:
                pass

    def _safe_status(self, msg: str) -> None:
        try:
            self._status_cb(msg)
        except Exception:
            try:
                logging.warning("status_cb failed: %s", msg)
            except Exception:
                pass

    def _log_text(self, text: str, limit: int = 90) -> str:
        src = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(src) > limit:
            return src[: limit - 3] + "..."
        return src

    def _has_hangul(self, text: str) -> bool:
        if not text:
            return False
        return re.search(r"[\u3131-\u318E\uAC00-\uD7A3]", text) is not None

    def _replace_numbers_for_korean_tts(self, text: str) -> str:
        if not text:
            return text
        def _repl(match: re.Match) -> str:
            raw = str(match.group(0) or "")
            try:
                return self._int_to_korean(raw)
            except Exception:
                return raw
        return re.sub(r"\d+", _repl, text)

    def _int_to_korean(self, raw_num: str) -> str:
        return str(raw_num or "0")

def ensure_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None

def _to_screen_xy(x: int, y: int, monitor_index: int) -> tuple[int, int]:
    try:
        import mss
        with mss.mss() as sct:
            mons = sct.monitors
            if monitor_index < 1 or monitor_index >= len(mons):
                monitor_index = 1
            mon = mons[monitor_index]
            return int(mon["left"] + x), int(mon["top"] + y)
    except Exception:
        return int(x), int(y)

