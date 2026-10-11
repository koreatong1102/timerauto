"""Gather plain values on the UI thread; ZIP work never touches live Qt objects."""
from __future__ import annotations

import os
import time
from pathlib import Path

from app_paths import get_app_base_dir, normalize_app_path
from diagnostics import _evidence_json


def _attr(obj, name, default=None):
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _audio_state(player, output):
    result = {}
    for obj, methods in ((player, ("playbackState", "mediaStatus", "position", "duration", "errorString")),
                         (output, ("volume", "isMuted"))):
        if obj is None:
            continue
        for method in methods:
            try:
                value = getattr(obj, method)()
                result[method] = getattr(value, "name", value)
            except Exception as exc:
                result[method] = {"unavailable": str(exc)}
    if output is not None:
        try:
            result["device"] = output.device().description()
        except Exception:
            result["device"] = "unavailable"
    return result


def prepare_diagnostic_export(owner):
    cfg = _attr(owner, "cfg")
    overlay = _attr(owner, "browser_overlay")
    watcher = _attr(owner, "spectator_watcher")
    snapshot = overlay.snapshot() if overlay is not None else {}
    best = dict(_attr(owner, "_potm_best", {}) or {})
    integration = _attr(owner, "obs_integration")
    runtime = {"captured_at": time.time(), "potm_candidate": best,
               "prepared_report_payloads": _attr(owner, "_diagnostic_reports", {}),
               "obs": {"status": _attr(integration, "status", "unavailable"),
                       "source_record_result": _attr(owner, "_obs_source_record_diagnostic_result", {})},
               "audio": {"potm_bgm": _audio_state(_attr(owner, "_potm_bgm_player"), _attr(owner, "_potm_bgm_audio_out")),
                         "potm_clip": _audio_state(_attr(owner, "_potm_replay_audio_player"), _attr(owner, "_potm_replay_audio_out"))}}
    for name in ("_potm_archive_session_id", "_potm_terminal_pending", "_potm_played", "_potm_opening_round_report_shown",
                 "_potm_presentation_active", "_potm_replay_token", "_potm_final_report_payload", "_potm_final_commentary",
                 "_lobby_auto_start_window_pending", "_lobby_post_match_kick_last_session_id", "_obs_status_detail"):
        runtime[name.lstrip("_")] = _attr(owner, name)
    runtime["audio"]["commentary"] = {role: _audio_state(player, dict(_attr(owner, "_commentary_audio_outs", {}) or {}).get(role))
        for role, player in dict(_attr(owner, "_commentary_players", {}) or {}).items()}
    folders = []
    for folder in (_attr(_attr(watcher, "_match_archive"), "session_dir", ""), _attr(owner, "_potm_archive_dir", "")):
        if folder and folder not in folders:
            folders.append(str(folder))
    # Bounded scan: include the latest archive if no live watcher survived restart.
    base = Path(normalize_app_path(str(_attr(cfg, "spectator_match_archive_dir", "MatchLogArchive") or "MatchLogArchive")))
    try:
        recent = sorted((p for p in base.iterdir() if p.is_dir() and not p.is_symlink()), key=lambda p: p.stat().st_mtime, reverse=True)
        for folder in recent[:5]:
            if str(folder) not in folders:
                folders.append(str(folder))
            if len(folders) >= 2:
                break
    except OSError:
        pass
    paths = [best.get("file"), _attr(overlay, "_obs_replay_path", "")]
    ffmpeg = str(_attr(cfg, "obs_highlight_ffmpeg_path", "") or "")
    ffprobe = str(Path(normalize_app_path(ffmpeg)).parent / "ffprobe.exe") if ffmpeg else ""
    return {"output_dir": owner._diagnostic_folder(), "app_state": _evidence_json(owner._diagnostic_app_state(), False),
            "cfg_snapshot": _evidence_json(dict(_attr(cfg, "__dict__", {}) or {}), False),
            "spectator_root": owner._diagnostic_spectator_root(), "overlay_snapshot": _evidence_json(snapshot, False),
            "mask_sensitive": bool(_attr(cfg, "diagnostics_mask_sensitive", True)),
            "raw_sample_lines": int(_attr(cfg, "diagnostics_raw_sample_lines", 120) or 120),
            "app_base": get_app_base_dir(),
            "context": {"runtime": _evidence_json(runtime, False), "match_dirs": folders[:2], "media_paths": [p for p in paths if p], "ffprobe_path": ffprobe},
            "obs_provider": integration if callable(_attr(integration, "diagnostic_snapshot")) else None}
