# runtime_support.py
# -*- coding: utf-8 -*-
"""Startup/runtime helpers kept out of the main Qt application file."""

from __future__ import annotations

import fnmatch
import logging
import os
import sys
import threading
import traceback
from datetime import datetime
from typing import List

from app_paths import get_app_base_dir

def _is_dir_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".timerauto_write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        try:
            os.remove(probe)
        except Exception:
            pass
        return True
    except Exception:
        return False


def _user_config_dir() -> str:
    base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "TimerAuto")


def resolve_config_path() -> str:
    candidates: List[str] = []
    exe_dir = ""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.join(exe_dir, "config.json"))
    if "__file__" in globals():
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(script_dir, "config.json"))
    candidates.append(os.path.join(get_app_base_dir(), "config.json"))
    candidates.append(os.path.join(os.getcwd(), "config.json"))
    user_cfg = os.path.join(_user_config_dir(), "config.json")
    candidates.append(user_cfg)
    for path in candidates:
        if os.path.exists(path):
            if getattr(sys, "frozen", False) and exe_dir:
                try:
                    path_dir = os.path.dirname(os.path.abspath(path))
                    if os.path.abspath(path_dir).lower() == os.path.abspath(exe_dir).lower() and not _is_dir_writable(exe_dir):
                        # Installer/Program Files case: preserve the bundled first-run
                        # defaults, but use a writable per-user config from then on.
                        try:
                            os.makedirs(os.path.dirname(user_cfg), exist_ok=True)
                            if not os.path.exists(user_cfg):
                                import shutil
                                shutil.copy2(path, user_cfg)
                        except Exception:
                            pass
                        return user_cfg
                except Exception:
                    pass
            return path
    # Portable folder is preferred, but installer/Program Files builds may not be
    # writable.  In that case keep user settings under AppData so first-run
    # SpectatorLog enable/path discovery can actually persist.
    if getattr(sys, "frozen", False) and exe_dir and not _is_dir_writable(exe_dir):
        try:
            os.makedirs(os.path.dirname(user_cfg), exist_ok=True)
        except Exception:
            pass
        return user_cfg
    return candidates[0] if candidates else "config.json"


def _prune_runtime_logs(log_dir: str, *, pattern: str = "timerauto_*.log", keep: int = 50) -> None:
    """Keep runtime app logs from growing forever.

    Chapter exports are user data and are intentionally not touched here.
    """
    try:
        keep = max(5, int(keep or 50))
        entries = []
        for name in os.listdir(log_dir):
            if not fnmatch.fnmatch(name, pattern):
                continue
            path = os.path.join(log_dir, name)
            if os.path.isfile(path):
                entries.append((os.path.getmtime(path), path))
        entries.sort(reverse=True)
        for _mtime, path in entries[keep:]:
            try:
                os.remove(path)
            except Exception:
                pass
    except Exception:
        pass


def _setup_logging(cfg_path: str) -> str:
    base_dir = os.path.dirname(os.path.abspath(cfg_path)) if cfg_path else get_app_base_dir()
    log_dir = os.path.join(base_dir, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        log_dir = get_app_base_dir()
    _prune_runtime_logs(log_dir, keep=50)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"timerauto_{ts}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
    )

    class _TeeStream:
        def __init__(self, stream, log_file):
            self._stream = stream
            self._log_file = log_file

        def write(self, s):
            try:
                self._stream.write(s)
            except Exception:
                pass
            try:
                self._log_file.write(s)
            except Exception:
                pass

        def flush(self):
            try:
                self._stream.flush()
            except Exception:
                pass
            try:
                self._log_file.flush()
            except Exception:
                pass

    try:
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = _TeeStream(sys.__stdout__, log_file)
        sys.stderr = _TeeStream(sys.__stderr__, log_file)
    except Exception:
        pass

    def _log_exception(exc_type, exc, tb):
        logging.error("Unhandled exception", exc_info=(exc_type, exc, tb))
        try:
            traceback.print_exception(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = _log_exception

    def _thread_hook(args):
        logging.error("Unhandled thread exception", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        try:
            traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)
        except Exception:
            pass

    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_hook

    logging.info("Logging started: %s", log_path)
    return log_path
