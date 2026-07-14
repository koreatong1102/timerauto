# app_paths.py
# -*- coding: utf-8 -*-
"""Filesystem path helpers shared by TimerAuto modules.

Kept outside timerauto.py so config/build/update code can use the same
frozen-app path rules without importing the Qt GUI.
"""

from __future__ import annotations

import os
import sys

_APP_BASE_DIR = None

# Built-in assets used to live beside the executable.  Keep old profiles and
# imported settings working after the release layout moved them under assets.
_LEGACY_ASSET_PATHS = {
    "kd.png": os.path.join("assets", "images", "overlays", "KD.png"),
    "tko.png": os.path.join("assets", "images", "overlays", "TKO.png"),
    "stun.wav": os.path.join("assets", "audio", "effects", "stun.wav"),
    "game-bonus-02-294436.mp3": os.path.join("assets", "audio", "effects", "game-bonus-02-294436.mp3"),
    "glass-crack-363162.mp3": os.path.join("assets", "audio", "effects", "glass-crack-363162.mp3"),
    "level-up-08-402152.mp3": os.path.join("assets", "audio", "effects", "level-up-08-402152.mp3"),
    "ting-sound-197759.mp3": os.path.join("assets", "audio", "effects", "ting-sound-197759.mp3"),
}
for _level in range(1, 8):
    _LEGACY_ASSET_PATHS[f"level/{_level}.png"] = os.path.join("assets", "images", "levels", f"{_level}.png")

def get_app_base_dir() -> str:
    global _APP_BASE_DIR
    if _APP_BASE_DIR:
        return _APP_BASE_DIR
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    elif "__file__" in globals():
        base = os.path.dirname(os.path.abspath(__file__))
    else:
        base = os.getcwd()
    _APP_BASE_DIR = base
    return base

def app_path(*parts: str) -> str:
    return os.path.join(get_app_base_dir(), *parts)

def normalize_app_path(path: str) -> str:
    if not path:
        return path
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return os.path.join(get_app_base_dir(), path)

def to_app_rel(path: str) -> str:
    if not path:
        return path
    try:
        base = get_app_base_dir()
        abs_path = os.path.abspath(path)
        base_abs = os.path.abspath(base)
        rel = os.path.relpath(abs_path, base_abs)
        if not rel.startswith("..") and not os.path.isabs(rel):
            return rel
    except Exception:
        pass
    return path


def normalize_builtin_asset_path(path: str) -> str:
    """Map only known legacy relative asset paths to the bundled layout.

    Absolute paths stay untouched because they may be user-selected files
    outside the app folder.
    """
    raw = str(path or "").strip()
    if not raw or os.path.isabs(os.path.expanduser(raw)):
        return raw
    key = raw.replace("\\", "/").lstrip("./").lower()
    return _LEGACY_ASSET_PATHS.get(key, raw)

def _candidate_documents_dirs() -> list[str]:
    candidates = []
    for env_name in ("USERPROFILE", "OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        base = os.environ.get(env_name, "")
        if base:
            candidates.append(os.path.join(base, "Documents"))
    home = os.path.expanduser("~")
    if home and home != "~":
        candidates.append(os.path.join(home, "Documents"))
    out = []
    seen = set()
    for item in candidates:
        norm = os.path.abspath(os.path.expanduser(item))
        key = norm.lower()
        if key not in seen:
            seen.add(key)
            out.append(norm)
    return out

def resolve_spectatorlog_path(path: str = "") -> str:
    raw = str(path or "").strip()
    if raw:
        base = normalize_app_path(raw)
        base = os.path.abspath(base)
        if os.path.basename(base).lower() == "spectatorlog":
            return base
        child = os.path.join(base, "SpectatorLog")
        if os.path.isdir(child):
            return child
        return base

    # First-run release default: find the common TTF2 SpectatorLog folder in
    # the user's Documents/OneDrive Documents instead of assuming it lives next
    # to the exe.  This lets portable builds work on another PC without SWa's
    # absolute config path.
    for doc_dir in _candidate_documents_dirs():
        for rel in (
            os.path.join("ThrillOfTheFight2", "SpectatorLog"),
            os.path.join("TheThrillOfTheFight2", "SpectatorLog"),
        ):
            candidate = os.path.join(doc_dir, rel)
            if os.path.isdir(candidate):
                return os.path.abspath(candidate)

    # Portable fallback for users who keep SpectatorLog beside the exe/source.
    base = app_path("ThrillOfTheFight2", "SpectatorLog")
    return os.path.abspath(base)

def resolve_player_image_path(path: str) -> str:
    if not path:
        return ""
    path = normalize_app_path(path)
    if os.path.exists(path):
        return path
    base_name = os.path.basename(path)
    candidates = [
        app_path("image", "players", base_name),
        app_path("image", base_name),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    stem = os.path.splitext(base_name)[0]
    gid_prefix = stem.rsplit("_", 1)[0].upper().strip() if "_" in stem else stem.upper().strip()
    if gid_prefix:
        players_dir = app_path("image", "players")
        try:
            for name in os.listdir(players_dir):
                cand_stem, cand_ext = os.path.splitext(name)
                if cand_ext.lower() not in (".png", ".jpg", ".jpeg", ".bmp"):
                    continue
                if not cand_stem.upper().startswith(gid_prefix + "_"):
                    continue
                candidate = os.path.join(players_dir, name)
                if os.path.exists(candidate):
                    return candidate
        except Exception:
            pass
    return path
