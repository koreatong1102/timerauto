import logging
import os
import time
from typing import Any, Callable, Dict, Optional


class ObsAutoReplayController:
    """Coordinates saved OBS replay files with the browser overlay player."""

    def __init__(
        self,
        config_getter: Callable[[], Any],
        overlay_getter: Callable[[], Any],
        schedule_once: Callable[[int, Callable[[], None]], None],
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._config_getter = config_getter
        self._overlay_getter = overlay_getter
        self._schedule_once = schedule_once
        self._clock = clock
        self._generation = 0
        self._cancel_before = 0.0

    def cancel(self, reason: str = "") -> None:
        self._generation += 1
        self._cancel_before = self._clock()
        overlay = self._overlay_getter()
        if overlay is not None:
            try:
                overlay.stop_obs_replay()
            except Exception:
                logging.exception("OBS_AUTO_REPLAY_STOP_FAIL reason=%s", reason)
        logging.info("OBS_AUTO_REPLAY_CANCEL reason=%s", str(reason or "unspecified"))

    def schedule(self, path: str, reason: str, context: Optional[Dict[str, Any]] = None) -> bool:
        cfg = self._config_getter()
        context = dict(context or {})
        kind = str(context.get("auto_replay_kind") or "").lower().strip()
        if kind not in ("kd", "tko") or not self._kind_enabled(cfg, kind):
            return False

        replay_path = os.path.abspath(os.path.expanduser(str(path or "").strip()))
        if not os.path.isfile(replay_path):
            logging.warning("OBS_AUTO_REPLAY_FILE_MISSING kind=%s path=%s", kind, replay_path)
            return False

        try:
            triggered_at = float(context.get("trigger_monotonic", 0.0) or 0.0)
        except Exception:
            triggered_at = 0.0
        if triggered_at > 0.0 and triggered_at <= self._cancel_before:
            logging.info("OBS_AUTO_REPLAY_STALE kind=%s reason=%s", kind, reason)
            return False

        delay_sec = max(0.0, min(15.0, float(getattr(cfg, "obs_auto_replay_delay_sec", 2.0) or 0.0)))
        target_at = (triggered_at if triggered_at > 0.0 else self._clock()) + delay_sec
        remaining_ms = max(0, int(round((target_at - self._clock()) * 1000.0)))
        self._generation += 1
        generation = self._generation
        self._schedule_once(
            remaining_ms,
            lambda: self._start(generation, replay_path, kind),
        )
        logging.info(
            "OBS_AUTO_REPLAY_SCHEDULE kind=%s delay_ms=%s path=%s",
            kind,
            remaining_ms,
            replay_path,
        )
        return True

    def _start(self, generation: int, path: str, kind: str) -> bool:
        cfg = self._config_getter()
        if generation != self._generation or not self._kind_enabled(cfg, kind):
            return False
        if not os.path.isfile(path):
            logging.warning("OBS_AUTO_REPLAY_FILE_MISSING_AT_START kind=%s path=%s", kind, path)
            return False
        overlay = self._overlay_getter()
        if overlay is None:
            return False
        try:
            token = overlay.play_obs_replay(
                path,
                muted=bool(getattr(cfg, "obs_auto_replay_muted", True)),
                volume=int(getattr(cfg, "obs_auto_replay_volume", 100) or 0),
                fit=str(getattr(cfg, "obs_auto_replay_fit", "cover") or "cover"),
                fade_ms=int(getattr(cfg, "obs_auto_replay_fade_ms", 140) or 0),
            )
        except Exception:
            logging.exception("OBS_AUTO_REPLAY_START_FAIL kind=%s path=%s", kind, path)
            return False
        if not token:
            logging.warning("OBS_AUTO_REPLAY_START_REJECTED kind=%s path=%s", kind, path)
            return False
        logging.info("OBS_AUTO_REPLAY_START kind=%s token=%s path=%s", kind, token, path)
        return True

    @staticmethod
    def _kind_enabled(cfg: Any, kind: str) -> bool:
        if not bool(getattr(cfg, "obs_auto_replay_enabled", True)):
            return False
        if kind == "kd":
            return bool(getattr(cfg, "obs_auto_replay_kd", True))
        if kind == "tko":
            return bool(getattr(cfg, "obs_auto_replay_tko", True))
        return False
