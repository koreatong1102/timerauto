# config_model.py
# -*- coding: utf-8 -*-
"""Configuration dataclasses and normalization helpers for TimerAuto.

This module intentionally has no PyQt dependency. It can be imported by tests,
build tools, and lightweight utilities without loading the GUI stack.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional

from app_paths import app_path, normalize_app_path, normalize_builtin_asset_path, to_app_rel

def migrate_action_keys(actions: Dict[str, List[dict]],
                        pixel_rules: List[dict]) -> Dict[str, List[dict]]:
    updated = dict(actions or {})
    for rule in pixel_rules or []:
        name = str(rule.get("name") or "")
        rid = str(rule.get("id") or "")
        if not rid:
            continue
        new_key = f"pixel_id:{rid}"
        old_key = f"pixel:{name}"
        if old_key in updated and new_key not in updated:
            updated[new_key] = copy.deepcopy(updated[old_key])
        if new_key in updated and old_key not in updated:
            updated[old_key] = copy.deepcopy(updated[new_key])
    return updated


def sync_action_keys(actions: Dict[str, List[dict]],
                     pixel_rules: List[dict]) -> Dict[str, List[dict]]:
    synced = dict(actions or {})
    for rule in pixel_rules or []:
        name = str(rule.get("name") or "").strip()
        rid = str(rule.get("id") or "").strip()
        if not name or not rid:
            continue
        name_key = f"pixel:{name}"
        id_key = f"pixel_id:{rid}"
        if name_key in synced:
            src = synced[name_key]
        elif id_key in synced:
            src = synced[id_key]
        else:
            continue
        synced[name_key] = copy.deepcopy(src)
        synced[id_key] = copy.deepcopy(src)
    return synced


def prune_actions(actions: Dict[str, List[dict]],
                  pixel_rules: List[dict]) -> Dict[str, List[dict]]:
    pixel_names = {str(rule.get("name") or "").strip() for rule in (pixel_rules or [])}
    pixel_names.discard("")
    pixel_ids = {str(rule.get("id") or "").strip() for rule in (pixel_rules or [])}
    pixel_ids.discard("")

    pruned: Dict[str, List[dict]] = {}
    for key, value in (actions or {}).items():
        if key.startswith("sound_id:"):
            continue
        if key.startswith("pixel_id:"):
            pid = key.split(":", 1)[1]
            if pid in pixel_ids:
                pruned[key] = value
            continue
        if key.startswith("sound:"):
            continue
        if key.startswith("pixel:"):
            name = key.split(":", 1)[1]
            if name in pixel_names:
                pruned[key] = value
            continue
        pruned[key] = value
    return pruned




def _normalize_win_effects_paths(data: Optional[dict]) -> dict:
    raw = dict(data or {})
    burst = dict(raw.get("burst", {}) or {})
    if "sfx_path" in burst:
        burst["sfx_path"] = to_app_rel(normalize_builtin_asset_path(str(burst.get("sfx_path", "") or "")))
    raw["burst"] = burst
    fail = dict(raw.get("fail", {}) or {})
    if "sfx_path" in fail:
        fail["sfx_path"] = to_app_rel(normalize_builtin_asset_path(str(fail.get("sfx_path", "") or "")))
    raw["fail"] = fail
    nameplates = dict(raw.get("nameplates", {}) or {})
    imgs = nameplates.get("images", [])
    if isinstance(imgs, list):
        nameplates["images"] = [to_app_rel(normalize_builtin_asset_path(str(p or ""))) for p in imgs]
    raw["nameplates"] = nameplates
    return raw


def _normalize_config_paths(raw: dict) -> dict:
    out = dict(raw or {})
    if "players_images" in out and isinstance(out.get("players_images"), dict):
        out["players_images"] = {str(k): to_app_rel(str(v)) for k, v in (out.get("players_images") or {}).items()}
    if "players_flags" in out and isinstance(out.get("players_flags"), dict):
        out["players_flags"] = {str(k): to_app_rel(str(v)) for k, v in (out.get("players_flags") or {}).items()}
    if "win_effects" in out and isinstance(out.get("win_effects"), dict):
        out["win_effects"] = _normalize_win_effects_paths(out.get("win_effects"))
    return out


def _normalize_player_country(value: object) -> str:
    raw = str(value or "").strip().upper()
    if raw in ("JP", "JPN", "JAPAN", "?쇰낯"):
        return "JP"
    return "KR"


@dataclass
class Rect:
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0

    def valid(self) -> bool:
        return self.w > 0 and self.h > 0


@dataclass
class TriggerConfig:
    enabled: bool = True
    target_bgr: Tuple[int, int, int] = (0, 255, 0)  # default green
    tolerance: int = 35
    consecutive_needed: int = 6
    window_frames: int = 8
    cooldown_sec: float = 2.0
    action_cooldown_sec: float = 5.0


@dataclass
class PaletteConfig:
    # Player image palette extraction settings.
    frames: int = 3            # Number of sampled frames.
    k_colors: int = 5          # Number of dominant colors.
    mask_thresh: float = 0.5   # mediapipe person-mask threshold.
    max_pixels: int = 12000    # Max pixels used for kmeans.
    min_v_cut: int = 10        # Ignore very dark pixels.


def default_win_effects() -> Dict[str, object]:
    return {
        "stages": [
            {"min": 3, "color": "#B9C7D6", "opacity": 0.45, "pulse": 1.04},
            {"min": 6, "color": "#4F7BFF", "opacity": 0.6, "pulse": 1.08},
            {"min": 9, "color": "#7A3FFF", "opacity": 0.75, "pulse": 1.12},
            {"min": 12, "color": "#12C48B", "opacity": 0.85, "pulse": 1.15},
            {"min": 16, "color": "#FFB100", "opacity": 0.9, "pulse": 1.18},
            {"min": 21, "color": "#FF2B2B", "opacity": 0.95, "pulse": 1.22},
            {"min": 30, "color": "#F8FAFC", "opacity": 1.0, "pulse": 1.26},
        ],
        "aura": {
            "enabled": True,
            "frame_padding": 12,
            "outer_padding": 14,
            "border1": 2,
            "border2": 1,
            "border3": 1,
            "border_color": "",
            "border_opacity": 0.6,
            "border_effect_enabled": True,
            "backdrop_enabled": True,
            "backdrop_color": "#000000",
            "backdrop_opacity": 0.25,
            "backdrop_pad": 8,
            "frame_spark_emit": 6,
            "frame_spark_size": 8,
            "frame_spark_size_var": 6,
            "frame_spark_pace": 40,
            "flame_emit": 12,
            "smoke_emit": 6,
            "spark_emit": 10,
            "flame_size": 20,
            "flame_size_var": 14,
            "smoke_size": 36,
            "smoke_size_var": 20,
            "spark_size": 10,
            "spark_size_var": 8,
            "turbulence": 18,
            "blur_radius": 0,
            "core": {
                "emit_mul": 8.0,
                "life": 1200,
                "life_var": 220,
                "size_mul": 0.5,
                "size_var_mul": 0.12,
                "size_var_add": 1,
                "angle_var": 6,
                "speed": 120,
                "speed_var": 15,
                "accel": 30,
                "accel_var": 8,
                "accel_mag_var": 12,
                "color_var": 0.04,
                "alpha": 0.98,
                "alpha_var": 0.08,
                "rot_var": 0,
                "turb_mul": 0.15,
            },
            "body": {
                "emit_mul": 6.0,
                "life": 1500,
                "life_var": 260,
                "size_mul": 0.7,
                "size_var_mul": 0.18,
                "size_var_add": 1,
                "angle_var": 8,
                "speed": 85,
                "speed_var": 15,
                "accel": 22,
                "accel_var": 10,
                "accel_mag_var": 12,
                "color_var": 0.06,
                "alpha": 0.85,
                "alpha_var": 0.1,
                "rot_var": 2,
            },
            "glow": {
                "emit_mul": 1.2,
                "life": 1700,
                "life_var": 320,
                "size_mul": 0.6,
                "size_var_mul": 0.2,
                "size_var_add": 2,
                "angle_var": 8,
                "speed": 40,
                "speed_var": 12,
                "color_var": 0.08,
                "alpha": 0.22,
                "alpha_var": 0.08,
                "rot_var": 6,
                "turb_mul": 0.35,
            },
            "wisps": {
                "emit_mul": 0.8,
                "life": 1800,
                "life_var": 360,
                "size_mul": 0.55,
                "size_var_mul": 0.18,
                "size_var_add": 2,
                "angle_var": 7,
                "speed": 32,
                "speed_var": 10,
                "color_var": 0.1,
                "alpha": 0.12,
                "alpha_var": 0.06,
                "rot_var": 6,
            },
            "spark": {
                "emit_mul": 0.05,
                "life": 520,
                "life_var": 360,
                "size_mul": 0.6,
                "size_var_mul": 0.2,
                "angle_var": 18,
                "speed": 150,
                "speed_var": 45,
                "color_var": 0.1,
                "alpha": 0.2,
                "alpha_var": 0.08,
                "rot_var": 0,
            },
        },
        "inner": {
            "dust": {"enabled": True, "min": 3, "opacity": 0.12, "interval": 140},
            "hud": {"enabled": True, "min": 6, "opacity": 0.5, "speed": 10000},
            "electric": {"enabled": True, "min": 9, "interval": 100, "opacity_min": 0.3, "opacity_max": 0.9},
            "core": {"enabled": True, "min": 12, "size": 0.35, "opacity_max": 0.5, "period": 900},
            "chrono": {"enabled": True, "min": 30, "opacity": 1.0, "speed": 1500},
        },
        "burst": {
            "milestones": [3, 6, 9, 12, 16, 21, 30],
            "sfx_enabled": False,
            "sfx_path": "",
        },
        "fail": {
            "enabled": True,
            "overlay_opacity": 0.65,
            "tint": "#000000",
            "sfx_enabled": False,
            "sfx_path": "",
        },
        "nameplates": {
            "enabled": True,
            "milestones": [3, 6, 9, 12, 16, 21, 30],
            "images": [],
            "width": 110,
            "height": 30,
            "scale": 1.0,
            "gap": 6,
            "side_blue": "left",
            "side_red": "right",
        },
        "portrait": {
            "zoom": 1.25,
            "offset_x": 0.0,
            "offset_y": -0.08,
        },
        "win_text": {
            "enabled": True,
            "format": "W{n}",
            "size_scale": 0.18,
            "size_min": 11,
            "size_max": 18,
            "offset_ratio": 0.22,
            "base_color": "#d6dbe0",
            "highlight_color": "#f8fbff",
            "outline_color": "#2b2f34",
            "shadow_color": "#0b0f14",
            "shadow_opacity": 0.6,
            "highlight_height": 0.55,
        },
    }


def _migrate_win_effects_legacy(merged: Dict[str, object], raw_win_effects: Optional[Dict[str, object]]) -> Dict[str, object]:
    out = _merge_dict(default_win_effects(), merged or {})
    raw_we = raw_win_effects or {}
    inner_raw = raw_we.get("inner", {}) if isinstance(raw_we, dict) else {}
    inner = out.get("inner", {}) if isinstance(out.get("inner", {}), dict) else {}
    core = inner.get("core", {}) if isinstance(inner.get("core", {}), dict) else {}

    # Legacy compatibility: older presets commonly used scanlines at 12+ and core at 30+.
    # If legacy scanlines exist and core is still at old threshold, shift core to the old 12+ band.
    legacy_scan = inner_raw.get("scanlines", {}) if isinstance(inner_raw, dict) else {}
    if isinstance(legacy_scan, dict):
        try:
            core_min = int(core.get("min", 12))
        except Exception:
            core_min = 12
        if core_min >= 30:
            try:
                core["min"] = int(legacy_scan.get("min", 12))
            except Exception:
                core["min"] = 12
    inner["core"] = core
    out["inner"] = inner
    return out


def _player_image_path_for_gid(cfg: "AppConfig", gid: str) -> str:
    gid_key = str(gid or "").upper().strip()
    if not gid_key:
        return ""
    direct = str((cfg.players_images or {}).get(gid_key, "") or "").strip()
    if direct:
        return direct
    name = str((cfg.players or {}).get(gid_key, "") or "").strip()
    if not name:
        return ""
    for other_gid, other_name in (cfg.players or {}).items():
        if str(other_gid or "").upper().strip() == gid_key:
            continue
        if str(other_name or "").strip() != name:
            continue
        inherited = str((cfg.players_images or {}).get(str(other_gid or "").upper().strip(), "") or "").strip()
        if inherited:
            return inherited
    return ""


def _player_flag_path_for_gid(cfg: "AppConfig", gid: str) -> str:
    gid_key = str(gid or "").upper().strip()
    if not gid_key:
        return ""
    direct = str((cfg.players_flags or {}).get(gid_key, "") or "").strip()
    if direct:
        return direct
    country = _player_country_for_gid(cfg, gid_key)
    name = str((cfg.players or {}).get(gid_key, "") or "").strip()
    if not name:
        return _default_player_flag_path(country)
    for other_gid, other_name in (cfg.players or {}).items():
        other_key = str(other_gid or "").upper().strip()
        if other_key == gid_key:
            continue
        if str(other_name or "").strip() != name:
            continue
        if _player_country_for_gid(cfg, other_key) != country:
            continue
        inherited = str((cfg.players_flags or {}).get(other_key, "") or "").strip()
        if inherited:
            return inherited
    return _default_player_flag_path(country)


def _player_country_for_gid(cfg: "AppConfig", gid: str) -> str:
    gid_key = str(gid or "").upper().strip()
    if not gid_key:
        return "KR"
    countries = cfg.players_countries or {}
    if gid_key in countries:
        return _normalize_player_country(countries.get(gid_key, "KR"))
    name = str((cfg.players or {}).get(gid_key, "") or "").strip()
    if name:
        for other_gid, other_name in (cfg.players or {}).items():
            other_key = str(other_gid or "").upper().strip()
            if other_key == gid_key:
                continue
            if str(other_name or "").strip() == name and other_key in countries:
                return _normalize_player_country(countries.get(other_key, "KR"))
    return "KR"


def _default_player_flag_path(country: object) -> str:
    code = _normalize_player_country(country)
    name = "default_jp.png" if code == "JP" else "default_kr.png"
    path = app_path("image", "flags", name)
    if os.path.exists(path):
        return to_app_rel(path)
    return ""


def _merge_dict(base: Dict[str, object], override: Dict[str, object]) -> Dict[str, object]:
    out = dict(base or {})
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge_dict(out.get(k, {}), v)
        else:
            out[k] = v
    return out


def _normalize_hex_color(color: str) -> str:
    c = str(color or "").strip()
    if c.startswith("#") and len(c) == 9:
        # Strip alpha from #AARRGGBB -> #RRGGBB
        return "#" + c[3:]
    return c


def _normalize_player_mask(mask: str) -> str:
    v = str(mask or "").strip().lower()
    if v in ("circle", "round", "?먰삎"):
        return "circle"
    if v in ("hex", "hexagon"):
        return "hex"
    return "square"


def _normalize_mouse_actions(actions_by_event: Dict[str, List[dict]], default_monitor: int) -> Dict[str, List[dict]]:
    def _fix_action(action: dict) -> dict:
        atype = str(action.get("type", "")).lower()
        if atype in ("mouse_move", "mouse_click", "mouse_down", "mouse_up"):
            use_monitor = bool(action.get("use_monitor", False))
            action["use_monitor"] = use_monitor
            if use_monitor:
                try:
                    action["monitor"] = int(action.get("monitor", default_monitor))
                except Exception:
                    action["monitor"] = int(default_monitor)
            else:
                action.pop("monitor", None)
        return action

    out = {}
    for ev, acts in (actions_by_event or {}).items():
        out[ev] = [(_fix_action(dict(a)) if isinstance(a, dict) else a) for a in (acts or [])]
    return out


def _default_overlay_style_round() -> Dict[str, object]:
    return {
        "bg_color": "#bfa57a",
        "bg_opacity": 1.0,
        "border_color": "#5b4631",
        "border_opacity": 1.0,
        "border_width": 2,
        "text_color": "#3a2a1d",
        "text_opacity": 1.0,
        "font_family": "Bahnschrift",
        "font_size": 0,
        "font_bold": True,
        "font_weight": 700,
    }


def _default_overlay_style_time() -> Dict[str, object]:
    return {
        "bg_color": "#3a3a3a",
        "bg_opacity": 1.0,
        "border_color": "#1a1a1a",
        "border_opacity": 1.0,
        "border_width": 2,
        "text_color": "#ffffff",
        "text_opacity": 1.0,
        "rest_text_color": "#ff5a5a",
        "rest_text_opacity": 1.0,
        "font_family": "Bahnschrift",
        "font_size": 0,
        "font_bold": True,
        "font_weight": 700,
    }


def _default_overlay_style_blue_name() -> Dict[str, object]:
    return {
        "bg_color": "#2d5ed0",
        "bg_opacity": 1.0,
        "border_color": "#1b3f8a",
        "border_opacity": 1.0,
        "border_width": 1,
        "text_color": "#ffffff",
        "text_opacity": 1.0,
        "font_family": "Noto Sans KR",
        "font_size": 0,
        "font_bold": True,
        "font_weight": 900,
        "badge_enabled": True,
        "badge_color": "#3b82f6",
        "badge_width": 10,
        "badge_height": 14,
        "badge_side": "left",
    }


def _default_overlay_style_red_name() -> Dict[str, object]:
    return {
        "bg_color": "#d14b4b",
        "bg_opacity": 1.0,
        "border_color": "#8f2d2d",
        "border_opacity": 1.0,
        "border_width": 1,
        "text_color": "#ffffff",
        "text_opacity": 1.0,
        "font_family": "Noto Sans KR",
        "font_size": 0,
        "font_bold": True,
        "font_weight": 900,
        "badge_enabled": True,
        "badge_color": "#ef4444",
        "badge_width": 10,
        "badge_height": 14,
        "badge_side": "right",
    }


def _default_overlay_style_arena() -> Dict[str, object]:
    return {
        "bg_color": "#222222",
        "bg_opacity": 1.0,
        "border_color": "#555555",
        "border_opacity": 1.0,
        "border_width": 1,
        "text_color": "#ffffff",
        "text_opacity": 1.0,
        "font_family": "Malgun Gothic",
        "font_size": 0,
        "font_bold": True,
        "font_weight": 700,
    }


def _default_browser_text_styles() -> Dict[str, Dict[str, object]]:
    base = {
        "bg_color": "transparent",
        "bg_opacity": 0.0,
        "border_color": "#000000",
        "border_opacity": 1.0,
        "border_width": 0,
        "text_color": "#f8fafc",
        "text_opacity": 1.0,
        "font_family": "Bahnschrift Condensed",
        "font_size": 0,
        "font_bold": True,
        "font_weight": 900,
    }
    return {
        "time": dict(base, text_color="#f7fbff", text_opacity=1.0, font_size=54, border_color="#b91c2b", border_width=5),
        "total": dict(base, text_color="#f4f7fb", text_opacity=0.95, font_size=12),
        "dmg": dict(base, text_color="#e8eef7", text_opacity=0.86, font_size=12),
        "combo": dict(base, text_color="#f4f7fb", text_opacity=1.0, font_size=22, border_color="#111827", border_width=1),
        "recent": dict(base, text_color="#edf5ff", text_opacity=0.94, font_size=23),
    }


def _normalize_overlay_style(raw: Optional[dict], default: Dict[str, object]) -> Dict[str, object]:
    out = dict(default)
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        if k in ("bg_opacity", "border_opacity", "text_opacity"):
            try:
                out[k] = float(v)
            except Exception:
                continue
        elif k in ("border_width", "font_size", "font_weight"):
            try:
                out[k] = int(v)
            except Exception:
                continue
        elif k in ("font_bold",):
            out[k] = bool(v)
        else:
            out[k] = v
    return out


def _normalize_browser_text_styles(raw: Optional[dict]) -> Dict[str, Dict[str, object]]:
    defaults = _default_browser_text_styles()
    raw = raw if isinstance(raw, dict) else {}
    return {key: _normalize_overlay_style(raw.get(key), default) for key, default in defaults.items()}


@dataclass
class AppConfig:
    monitor_index: int = 1  # mss: 1..N
    trigger_monitor_index: int = 1  # mss: 1..N (trigger pixel)
    roi_monitors: Dict[str, int] = field(default_factory=dict)
    coords_global: bool = True

    roi_hotkey: str = "F9"
    pixel_hotkey: str = "F10"
    detect_hotkey: str = "F11"
    trigger_pixel_hotkey: str = "F8"
    action_pick_hotkey: str = "F7"
    action_test_hotkey: str = "F6"
    chapter_anchor_epoch: float = 0.0
    chapter_offset_sec: int = 0
    chapter_dedupe_sec: int = 20
    chapter_output_dir: str = ""
    chapter_nickname_only: bool = False
    chapter_hide_time: bool = False
    obs_integration_enabled: bool = False
    obs_host: str = "127.0.0.1"
    obs_port: int = 4455
    obs_password: str = ""
    obs_auto_chapter_enabled: bool = False
    obs_chapter_add_start_event: bool = True
    obs_chapter_export_on_stop: bool = False
    obs_replay_buffer_enabled: bool = False
    obs_replay_buffer_auto_start: bool = True
    obs_highlight_kd: bool = True
    obs_highlight_tko: bool = True
    obs_highlight_stun: bool = True
    obs_highlight_counter: bool = True
    obs_highlight_combo: bool = True
    obs_highlight_heavy: bool = True
    obs_highlight_counter_damage_min: float = 30.0
    obs_highlight_combo_min: int = 3
    obs_highlight_damage_min: float = 55.0
    obs_highlight_cooldown_sec: float = 8.0
    obs_auto_replay_enabled: bool = True
    obs_auto_replay_kd: bool = True
    obs_auto_replay_tko: bool = True
    # Wait briefly after every highlight trigger so the decisive moment is
    # present in OBS Replay Buffer before it is saved.
    obs_auto_replay_capture_delay_sec: float = 1.0
    obs_auto_replay_delay_sec: float = 2.0
    obs_auto_replay_muted: bool = True
    obs_auto_replay_volume: int = 100
    obs_auto_replay_fit: str = "cover"
    obs_auto_replay_fade_ms: int = 140
    obs_auto_replay_stop_on_round: bool = True
    idle_highlight_enabled: bool = False
    idle_highlight_path: str = ""
    idle_highlight_random: bool = True
    idle_highlight_muted: bool = True
    idle_highlight_volume: int = 0
    idle_highlight_fit: str = "cover"
    idle_highlight_fade_ms: int = 350
    # Release first-run default: ON, because public builds do not ship SWa's
    # config.json.  If the user presses log detection, it should work immediately
    # with auto SpectatorLog path discovery instead of silently staying OFF.
    spectatorlog_enabled: bool = True
    spectatorlog_path: str = ""
    spectatorlog_poll_ms: int = 250
    spectatorlog_file_watch_enabled: bool = True
    spectatorlog_debounce_ms: int = 8
    spectatorlog_backup_poll_ms: int = 1500
    # Stage51 SpectatorLog Blackbox Recorder. Raw snapshots are byte-exact;
    # timestamps/metadata are written separately to events.jsonl.
    spectatorlog_blackbox_enabled: bool = False
    spectatorlog_blackbox_dir: str = "SpectatorLogArchive"
    spectatorlog_blackbox_mode: str = "smart"  # light / smart / full
    spectatorlog_blackbox_poll_ms: int = 100
    spectatorlog_blackbox_sample_ms: int = 250
    spectatorlog_blackbox_max_snapshot_mb: int = 64
    spectatorlog_blackbox_zip_on_close: bool = False
    spectator_realtime_gauge_min_interval_ms: int = 75
    spectatorlog_sync_timer: bool = True
    spectatorlog_sync_players: bool = True
    spectator_lobby_auto_start_enabled: bool = False
    spectator_lobby_auto_start_target_title: str = "The Thrill of the Fight 2"
    spectator_lobby_auto_start_client_x: int = 0
    spectator_lobby_auto_start_client_y: int = 0
    spectator_lobby_auto_start_reference_width: int = 0
    spectator_lobby_auto_start_reference_height: int = 0
    spectator_lobby_auto_start_click_count: int = 1
    spectator_lobby_auto_start_delay_ms: int = 300
    spectator_lobby_auto_start_activate: bool = True
    spectator_lobby_auto_start_restore_focus: bool = True
    spectator_lobby_auto_start_restore_cursor: bool = True
    spectator_lobby_auto_start_minimize_target: bool = False
    spectator_final_report_delay_sec: float = 10.0
    spectator_sp_throw_cost_scale: float = 1.8
    spectator_sp_impact_cost_scale: float = 1.25
    spectator_sp_fight_recovery_pct: float = 5.0
    # Rest recovery is applied to the missing portion of SP, not as a flat
    # addition to the full gauge.  Thirty percent keeps a tired fighter tired.
    spectator_sp_break_recovery_pct: float = 30.0
    spectator_sp_recovery_delay_sec: float = 1.5
    spectator_sp_bar_x: int = 0
    spectator_sp_bar_y: int = 0
    spectator_sp_bar_length_pct: int = 100
    spectator_sp_bar_thickness: int = 10
    spectator_sp_bar_color: str = "#1876d3"
    spectator_name_bar_x: int = 0
    spectator_name_bar_y: int = 0
    spectator_fight_style_enabled: bool = True
    spectator_fight_style_min_attempts: int = 20
    spectator_fight_style_min_landed: int = 10
    spectator_commentary_enabled: bool = True
    spectator_commentary_mode: str = "standard"
    spectator_commentary_min_damage: float = 25.0
    spectator_hit_effect_damage: float = 45.0
    spectator_hit_effect_color_preset: str = "classic"
    spectator_hit_effect_color_low: str = "#38bdf8"
    spectator_hit_effect_color_mid: str = "#fb923c"
    spectator_hit_effect_color_high: str = "#f87171"
    spectator_hit_effect_color_weak: str = "#facc15"
    spectator_hit_effect_color_stun: str = "#ef4444"
    spectator_hit_effect_duration_ms: int = 170
    spectator_hit_effect_pop_ms: int = 58
    spectator_hit_effect_base_size: int = 86
    spectator_hit_effect_damage_scale: float = 0.42
    spectator_hit_effect_ring_width: int = 4
    spectator_hit_effect_opacity: float = 1.0
    spectator_hit_effect_glow: float = 1.0
    spectator_hit_effect_fill_opacity: float = 1.0
    spectator_hit_effect_show_text: bool = True
    spectator_hit_effect_text_scale: float = 1.0
    spectator_hit_effect_latency_log: bool = True
    spectator_hit_effect_fast_emit: bool = True
    spectator_hit_effect_sprite_enabled: bool = True
    spectator_hit_effect_ring_enabled: bool = False
    spectator_commentary_cooldown_sec: float = 6.0
    spectator_commentary_voice: str = "ko-KR-SunHiNeural"
    spectator_caster_voice: str = "ko-KR-InJoonNeural"
    spectator_commentary_rate: int = 200
    spectator_commentary_volume: float = 100.0
    spectator_commentary_pitch: int = 0
    spectator_replay_speed: float = 1.0
    spectator_replay_real_time: bool = False
    spectator_recent_text_size: int = 23
    spectator_stun_sfx_path: str = ""
    spectator_knockdown_sfx_path: str = ""
    spectator_tko_sfx_path: str = ""
    spectator_sfx_playback_rate: float = 1.0

    # 버그 수정/업그레이드용 진단 패키지 설정.
    diagnostics_enabled: bool = True
    diagnostics_trace_minutes: int = 10
    diagnostics_raw_sample_lines: int = 120
    diagnostics_mask_sensitive: bool = True

    # SpectatorLog 자동 동기화 시 초상화 선택 정책.
    # "log" = 로그 초상화 우선(기본, 프로필 fallback 없음)
    # "profile" = 프로필 사진 우선, 프로필 없으면 로그 초상화 fallback
    portrait_source_priority: str = "log"

    roi_trigger: Rect = field(default_factory=Rect)
    # Browser overlay output and QML preview controls.
    roi_left_player: Rect = field(default_factory=Rect)
    roi_right_player: Rect = field(default_factory=Rect)

    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    palette: PaletteConfig = field(default_factory=PaletteConfig)
    timer_total_rounds: int = 3
    timer_round_sec: int = 180
    timer_rest_sec: int = 60
    timer_rest_30s_tts_enabled: bool = True
    timer_rest_30s_tts_rate: int = 200
    timer_current_round: int = 1
    timer_seconds_left: int = 180
    overlay_bg_color: str = "transparent"
    overlay_bg_opacity: float = 0.0
    # QML UI 검은 배경만 조절하는 불투명도. 텍스트/초상화/버튼은 영향 없음.
    overlay_ui_bg_opacity: float = 0.75
    # 구버전 설정 호환용. 더 이상 상단 UI 투명 슬라이더가 사용하지 않음.
    overlay_window_opacity: float = 1.0
    overlay_ui_scale: float = 1.0
    overlay_timer_font_size: int = 54
    overlay_timer_x: int = 0
    overlay_timer_y: int = 0
    overlay_round_font_size: int = 11
    overlay_round_x: int = 0
    overlay_round_y: int = 0
    overlay_preset: str = "classic"
    overlay_player_mask: str = "square"
    overlay_show_round: bool = True
    overlay_show_time: bool = True
    overlay_show_blue_img: bool = True
    overlay_show_blue_name: bool = True
    overlay_show_red_img: bool = True
    overlay_show_red_name: bool = True
    overlay_show_arena_name: bool = True
    overlay_show_flags: bool = True
    overlay_show_cinematic: bool = True
    overlay_vs_bg_path: str = ""
    overlay_vs_bg_opacity: float = 1.0
    overlay_vs_bg_by_arena: Dict[str, str] = field(default_factory=dict)
    overlay_vs_hold_sec: float = 2.85
    overlay_kd_image_path: str = "assets/images/overlays/KD.png"
    overlay_tko_image_path: str = "assets/images/overlays/TKO.png"
    overlay_ko_image_scale_pct: int = 100
    overlay_ko_x: int = 0
    overlay_ko_y: int = 0
    overlay_ko_motion_blur_pct: int = 100
    overlay_ko_flash_intensity_pct: int = 100
    overlay_ko_trail_intensity_pct: int = 100
    overlay_ko_shake_intensity_pct: int = 100
    overlay_ko_screen_shake: bool = True
    overlay_ko_perspective_px: int = 1400
    overlay_ko_start_z_px: int = 760
    overlay_ko_impact_depth_px: int = 34
    overlay_ko_rebound_px: int = 20
    overlay_ko_entry_ms: int = 500
    overlay_ko_drop_y_px: int = 190
    overlay_kd_hold_sec: float = 2.2
    overlay_tko_hold_sec: float = 2.6
    browser_overlay_scale: float = 1.0
    browser_overlay_poll_ms: int = 50
    browser_overlay_output_only: bool = True
    browser_fullscreen_fx_intensity: float = 1.6
    qml_preview_enabled: bool = True
    qml_effects_enabled: bool = False
    overlay_style_round: Dict[str, object] = field(default_factory=_default_overlay_style_round)
    overlay_style_time: Dict[str, object] = field(default_factory=_default_overlay_style_time)
    overlay_style_blue_name: Dict[str, object] = field(default_factory=_default_overlay_style_blue_name)
    overlay_style_red_name: Dict[str, object] = field(default_factory=_default_overlay_style_red_name)
    overlay_style_arena: Dict[str, object] = field(default_factory=_default_overlay_style_arena)
    browser_text_styles: Dict[str, Dict[str, object]] = field(default_factory=_default_browser_text_styles)
    action_cooldown_sec: float = 5.0
    action_cooldowns: Dict[str, float] = field(default_factory=dict)
    action_edge_triggers: Dict[str, bool] = field(default_factory=dict)
    capture_player_images: bool = True

    # GameID -> DisplayName
    players: Dict[str, str] = field(default_factory=dict)
    players_images: Dict[str, str] = field(default_factory=dict)
    players_countries: Dict[str, str] = field(default_factory=dict)
    players_flags: Dict[str, str] = field(default_factory=dict)
    current_blue_id: str = ""
    current_red_id: str = ""
    current_blue_registered: bool = False
    current_red_registered: bool = False
    current_blue_valid: bool = False
    current_red_valid: bool = False
    koth_enabled: bool = False
    koth_champion_id: str = ""
    koth_streak: int = 0
    koth_min_score: int = 75
    layout: Dict[str, Dict[str, int]] = field(default_factory=dict)
    actions: Dict[str, List[dict]] = field(default_factory=dict)
    pixel_rules: List[dict] = field(default_factory=list)
    win_effects: Dict[str, object] = field(default_factory=default_win_effects)

    @staticmethod
    def from_json(path: str) -> "AppConfig":
        if not os.path.exists(path):
            return AppConfig()
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
        raw = _normalize_config_paths(raw)

        def rect_from(d: dict) -> Rect:
            return Rect(**{k: int(d.get(k, 0)) for k in ["x", "y", "w", "h"]})

        cfg = AppConfig()
        cfg.monitor_index = int(raw.get("monitor_index", 1))
        cfg.trigger_monitor_index = int(raw.get("trigger_monitor_index", cfg.monitor_index))
        cfg.roi_monitors = {str(k): int(v) for k, v in (raw.get("roi_monitors", {}) or {}).items()}
        cfg.coords_global = bool(raw.get("coords_global", False))
        cfg.roi_hotkey = str(raw.get("roi_hotkey", "F9"))
        cfg.pixel_hotkey = str(raw.get("pixel_hotkey", "F10"))
        cfg.detect_hotkey = str(raw.get("detect_hotkey", "F11"))
        cfg.trigger_pixel_hotkey = str(raw.get("trigger_pixel_hotkey", "F8"))
        cfg.action_pick_hotkey = str(raw.get("action_pick_hotkey", "F7"))
        cfg.action_test_hotkey = str(raw.get("action_test_hotkey", "F6"))
        try:
            cfg.chapter_anchor_epoch = float(raw.get("chapter_anchor_epoch", 0.0) or 0.0)
        except Exception:
            cfg.chapter_anchor_epoch = 0.0
        cfg.chapter_offset_sec = int(raw.get("chapter_offset_sec", 0))
        cfg.chapter_dedupe_sec = int(raw.get("chapter_dedupe_sec", 20))
        cfg.chapter_output_dir = str(raw.get("chapter_output_dir", "") or "")
        cfg.chapter_nickname_only = bool(raw.get("chapter_nickname_only", False))
        cfg.chapter_hide_time = bool(raw.get("chapter_hide_time", False))
        cfg.obs_integration_enabled = bool(raw.get("obs_integration_enabled", False))
        cfg.obs_host = str(raw.get("obs_host", "127.0.0.1") or "127.0.0.1").strip()
        cfg.obs_port = max(1, min(65535, int(raw.get("obs_port", 4455) or 4455)))
        cfg.obs_password = str(raw.get("obs_password", "") or "")
        cfg.obs_auto_chapter_enabled = bool(raw.get("obs_auto_chapter_enabled", False))
        cfg.obs_chapter_add_start_event = bool(raw.get("obs_chapter_add_start_event", True))
        cfg.obs_chapter_export_on_stop = bool(raw.get("obs_chapter_export_on_stop", False))
        cfg.obs_replay_buffer_enabled = bool(raw.get("obs_replay_buffer_enabled", False))
        cfg.obs_replay_buffer_auto_start = bool(raw.get("obs_replay_buffer_auto_start", True))
        cfg.obs_highlight_kd = bool(raw.get("obs_highlight_kd", True))
        cfg.obs_highlight_tko = bool(raw.get("obs_highlight_tko", True))
        cfg.obs_highlight_stun = bool(raw.get("obs_highlight_stun", True))
        cfg.obs_highlight_counter = bool(raw.get("obs_highlight_counter", True))
        cfg.obs_highlight_combo = bool(raw.get("obs_highlight_combo", True))
        cfg.obs_highlight_heavy = bool(raw.get("obs_highlight_heavy", True))
        cfg.obs_highlight_counter_damage_min = max(0.0, min(300.0, float(raw.get("obs_highlight_counter_damage_min", 30.0) or 0.0)))
        cfg.obs_highlight_combo_min = max(2, min(20, int(raw.get("obs_highlight_combo_min", 3) or 3)))
        cfg.obs_highlight_damage_min = max(0.0, min(300.0, float(raw.get("obs_highlight_damage_min", 55.0) or 55.0)))
        cfg.obs_highlight_cooldown_sec = max(0.0, min(120.0, float(raw.get("obs_highlight_cooldown_sec", 8.0) or 8.0)))
        cfg.obs_auto_replay_enabled = bool(raw.get("obs_auto_replay_enabled", True))
        cfg.obs_auto_replay_kd = bool(raw.get("obs_auto_replay_kd", True))
        cfg.obs_auto_replay_tko = bool(raw.get("obs_auto_replay_tko", True))
        cfg.obs_auto_replay_capture_delay_sec = max(0.0, min(15.0, float(raw.get("obs_auto_replay_capture_delay_sec", 1.0) or 0.0)))
        cfg.obs_auto_replay_delay_sec = max(0.0, min(15.0, float(raw.get("obs_auto_replay_delay_sec", 2.0) or 0.0)))
        cfg.obs_auto_replay_muted = bool(raw.get("obs_auto_replay_muted", True))
        cfg.obs_auto_replay_volume = max(0, min(100, int(raw.get("obs_auto_replay_volume", 100) or 0)))
        cfg.obs_auto_replay_fit = str(raw.get("obs_auto_replay_fit", "cover") or "cover").lower()
        if cfg.obs_auto_replay_fit not in ("cover", "contain"):
            cfg.obs_auto_replay_fit = "cover"
        cfg.obs_auto_replay_fade_ms = max(0, min(2000, int(raw.get("obs_auto_replay_fade_ms", 140) or 0)))
        cfg.obs_auto_replay_stop_on_round = bool(raw.get("obs_auto_replay_stop_on_round", True))
        cfg.idle_highlight_enabled = bool(raw.get("idle_highlight_enabled", False))
        cfg.idle_highlight_path = str(raw.get("idle_highlight_path", "") or "")
        cfg.idle_highlight_random = bool(raw.get("idle_highlight_random", True))
        cfg.idle_highlight_muted = bool(raw.get("idle_highlight_muted", True))
        cfg.idle_highlight_volume = max(0, min(100, int(raw.get("idle_highlight_volume", 0) or 0)))
        cfg.idle_highlight_fit = str(raw.get("idle_highlight_fit", "cover") or "cover").lower()
        if cfg.idle_highlight_fit not in ("cover", "contain"):
            cfg.idle_highlight_fit = "cover"
        cfg.idle_highlight_fade_ms = max(0, min(3000, int(raw.get("idle_highlight_fade_ms", 350) or 350)))
        cfg.spectatorlog_enabled = bool(raw.get("spectatorlog_enabled", True))
        cfg.spectatorlog_path = str(raw.get("spectatorlog_path", "") or "")
        cfg.spectatorlog_sync_timer = bool(raw.get("spectatorlog_sync_timer", True))
        cfg.spectatorlog_sync_players = bool(raw.get("spectatorlog_sync_players", True))
        cfg.spectator_lobby_auto_start_enabled = bool(raw.get("spectator_lobby_auto_start_enabled", False))
        cfg.spectator_lobby_auto_start_target_title = str(
            raw.get("spectator_lobby_auto_start_target_title", "The Thrill of the Fight 2")
            or "The Thrill of the Fight 2"
        )
        try:
            cfg.spectator_lobby_auto_start_client_x = max(0, int(raw.get("spectator_lobby_auto_start_client_x", 0) or 0))
            cfg.spectator_lobby_auto_start_client_y = max(0, int(raw.get("spectator_lobby_auto_start_client_y", 0) or 0))
        except Exception:
            cfg.spectator_lobby_auto_start_client_x = 0
            cfg.spectator_lobby_auto_start_client_y = 0
        try:
            cfg.spectator_lobby_auto_start_reference_width = max(0, int(raw.get("spectator_lobby_auto_start_reference_width", 0) or 0))
            cfg.spectator_lobby_auto_start_reference_height = max(0, int(raw.get("spectator_lobby_auto_start_reference_height", 0) or 0))
        except Exception:
            cfg.spectator_lobby_auto_start_reference_width = 0
            cfg.spectator_lobby_auto_start_reference_height = 0
        try:
            cfg.spectator_lobby_auto_start_click_count = max(
                1, min(10, int(raw.get("spectator_lobby_auto_start_click_count", 1) or 1))
            )
        except Exception:
            cfg.spectator_lobby_auto_start_click_count = 1
        try:
            cfg.spectator_lobby_auto_start_delay_ms = max(0, min(5000, int(raw.get("spectator_lobby_auto_start_delay_ms", 300) or 300)))
        except Exception:
            cfg.spectator_lobby_auto_start_delay_ms = 300
        cfg.spectator_lobby_auto_start_activate = bool(raw.get("spectator_lobby_auto_start_activate", True))
        cfg.spectator_lobby_auto_start_restore_focus = bool(raw.get("spectator_lobby_auto_start_restore_focus", True))
        cfg.spectator_lobby_auto_start_restore_cursor = bool(raw.get("spectator_lobby_auto_start_restore_cursor", True))
        cfg.spectator_lobby_auto_start_minimize_target = bool(
            raw.get("spectator_lobby_auto_start_minimize_target", False)
        )
        try:
            cfg.spectator_final_report_delay_sec = max(0.0, min(30.0, float(raw.get("spectator_final_report_delay_sec", 10.0) or 0.0)))
        except Exception:
            cfg.spectator_final_report_delay_sec = 10.0
        cfg.spectator_sp_throw_cost_scale = max(0.1, min(5.0, float(raw.get("spectator_sp_throw_cost_scale", 1.8) or 1.8)))
        cfg.spectator_sp_impact_cost_scale = max(0.0, min(5.0, float(raw.get("spectator_sp_impact_cost_scale", 1.25))))
        cfg.spectator_sp_fight_recovery_pct = max(0.0, min(100.0, float(raw.get("spectator_sp_fight_recovery_pct", 5.0) or 0.0)))
        cfg.spectator_sp_break_recovery_pct = max(0.0, min(100.0, float(raw.get("spectator_sp_break_recovery_pct", 30.0) or 0.0)))
        cfg.spectator_sp_recovery_delay_sec = max(0.0, min(10.0, float(raw.get("spectator_sp_recovery_delay_sec", 1.5) or 0.0)))
        try:
            cfg.spectator_sp_bar_x = max(-300, min(300, int(raw.get("spectator_sp_bar_x", 0) or 0)))
            cfg.spectator_sp_bar_y = max(-100, min(100, int(raw.get("spectator_sp_bar_y", 0) or 0)))
            cfg.spectator_sp_bar_length_pct = max(25, min(160, int(raw.get("spectator_sp_bar_length_pct", 100) or 100)))
            cfg.spectator_sp_bar_thickness = max(2, min(40, int(raw.get("spectator_sp_bar_thickness", 10) or 10)))
        except (TypeError, ValueError):
            cfg.spectator_sp_bar_x = 0
            cfg.spectator_sp_bar_y = 0
            cfg.spectator_sp_bar_length_pct = 100
            cfg.spectator_sp_bar_thickness = 10
        cfg.spectator_sp_bar_color = _normalize_hex_color(str(raw.get("spectator_sp_bar_color", "#1876d3") or "#1876d3"))
        cfg.spectator_name_bar_x = max(-300, min(300, int(raw.get("spectator_name_bar_x", 0) or 0)))
        cfg.spectator_name_bar_y = max(-100, min(100, int(raw.get("spectator_name_bar_y", 0) or 0)))
        cfg.spectator_fight_style_enabled = bool(raw.get("spectator_fight_style_enabled", True))
        try:
            cfg.spectator_fight_style_min_attempts = max(
                1, min(500, int(raw.get("spectator_fight_style_min_attempts", 20) or 20))
            )
            cfg.spectator_fight_style_min_landed = max(
                1, min(500, int(raw.get("spectator_fight_style_min_landed", 10) or 10))
            )
        except (TypeError, ValueError):
            cfg.spectator_fight_style_min_attempts = 20
            cfg.spectator_fight_style_min_landed = 10
        cfg.spectator_commentary_enabled = bool(raw.get("spectator_commentary_enabled", True))
        cfg.spectator_commentary_mode = str(raw.get("spectator_commentary_mode", "standard") or "standard")
        cfg.spectator_commentary_voice = str(raw.get("spectator_commentary_voice", "ko-KR-SunHiNeural") or "ko-KR-SunHiNeural")
        cfg.spectator_caster_voice = str(raw.get("spectator_caster_voice", "ko-KR-InJoonNeural") or "ko-KR-InJoonNeural")
        cfg.spectator_stun_sfx_path = normalize_builtin_asset_path(str(raw.get("spectator_stun_sfx_path", "") or ""))
        cfg.spectator_knockdown_sfx_path = normalize_builtin_asset_path(str(raw.get("spectator_knockdown_sfx_path", "") or ""))
        cfg.spectator_tko_sfx_path = normalize_builtin_asset_path(str(raw.get("spectator_tko_sfx_path", "") or ""))
        try:
            cfg.spectator_sfx_playback_rate = float(raw.get("spectator_sfx_playback_rate", 1.0) or 1.0)
        except Exception:
            cfg.spectator_sfx_playback_rate = 1.0
        try:
            cfg.spectator_commentary_min_damage = float(raw.get("spectator_commentary_min_damage", 25.0) or 25.0)
        except Exception:
            cfg.spectator_commentary_min_damage = 25.0
        try:
            cfg.spectator_hit_effect_damage = float(raw.get("spectator_hit_effect_damage", 45.0) or 45.0)
        except Exception:
            cfg.spectator_hit_effect_damage = 45.0
        cfg.spectator_hit_effect_color_preset = str(raw.get("spectator_hit_effect_color_preset", "classic") or "classic").strip().lower()
        if cfg.spectator_hit_effect_color_preset not in ("classic", "icefire", "neon", "custom"):
            cfg.spectator_hit_effect_color_preset = "classic"
        cfg.spectator_hit_effect_color_low = _normalize_hex_color(str(raw.get("spectator_hit_effect_color_low", "#38bdf8") or "#38bdf8"))
        cfg.spectator_hit_effect_color_mid = _normalize_hex_color(str(raw.get("spectator_hit_effect_color_mid", "#fb923c") or "#fb923c"))
        cfg.spectator_hit_effect_color_high = _normalize_hex_color(str(raw.get("spectator_hit_effect_color_high", "#f87171") or "#f87171"))
        cfg.spectator_hit_effect_color_weak = _normalize_hex_color(str(raw.get("spectator_hit_effect_color_weak", "#facc15") or "#facc15"))
        cfg.spectator_hit_effect_color_stun = _normalize_hex_color(str(raw.get("spectator_hit_effect_color_stun", "#ef4444") or "#ef4444"))
        try:
            cfg.spectator_hit_effect_duration_ms = int(raw.get("spectator_hit_effect_duration_ms", 170) or 170)
        except Exception:
            cfg.spectator_hit_effect_duration_ms = 170
        cfg.spectator_hit_effect_duration_ms = max(80, min(1200, int(cfg.spectator_hit_effect_duration_ms or 170)))
        try:
            cfg.spectator_hit_effect_pop_ms = int(raw.get("spectator_hit_effect_pop_ms", 58) or 58)
        except Exception:
            cfg.spectator_hit_effect_pop_ms = 58
        cfg.spectator_hit_effect_pop_ms = max(30, min(280, int(cfg.spectator_hit_effect_pop_ms or 58)))
        try:
            cfg.spectator_hit_effect_base_size = int(raw.get("spectator_hit_effect_base_size", 86) or 86)
        except Exception:
            cfg.spectator_hit_effect_base_size = 86
        cfg.spectator_hit_effect_base_size = max(24, min(240, int(cfg.spectator_hit_effect_base_size or 86)))
        try:
            cfg.spectator_hit_effect_damage_scale = float(raw.get("spectator_hit_effect_damage_scale", 0.42) or 0.42)
        except Exception:
            cfg.spectator_hit_effect_damage_scale = 0.42
        cfg.spectator_hit_effect_damage_scale = max(0.0, min(3.0, float(cfg.spectator_hit_effect_damage_scale or 0.42)))
        try:
            cfg.spectator_hit_effect_ring_width = int(raw.get("spectator_hit_effect_ring_width", 4) or 4)
        except Exception:
            cfg.spectator_hit_effect_ring_width = 4
        cfg.spectator_hit_effect_ring_width = max(1, min(20, int(cfg.spectator_hit_effect_ring_width or 4)))
        try:
            cfg.spectator_hit_effect_opacity = float(raw.get("spectator_hit_effect_opacity", 1.0) or 1.0)
        except Exception:
            cfg.spectator_hit_effect_opacity = 1.0
        cfg.spectator_hit_effect_opacity = max(0.05, min(1.5, float(cfg.spectator_hit_effect_opacity or 1.0)))
        try:
            cfg.spectator_hit_effect_glow = float(raw.get("spectator_hit_effect_glow", 1.0) or 1.0)
        except Exception:
            cfg.spectator_hit_effect_glow = 1.0
        cfg.spectator_hit_effect_glow = max(0.0, min(3.0, float(cfg.spectator_hit_effect_glow or 1.0)))
        try:
            cfg.spectator_hit_effect_fill_opacity = float(raw.get("spectator_hit_effect_fill_opacity", 1.0) or 1.0)
        except Exception:
            cfg.spectator_hit_effect_fill_opacity = 1.0
        cfg.spectator_hit_effect_fill_opacity = max(0.0, min(1.5, float(cfg.spectator_hit_effect_fill_opacity or 1.0)))
        cfg.spectator_hit_effect_show_text = bool(raw.get("spectator_hit_effect_show_text", True))
        try:
            cfg.spectator_hit_effect_text_scale = float(raw.get("spectator_hit_effect_text_scale", 1.0) or 1.0)
        except Exception:
            cfg.spectator_hit_effect_text_scale = 1.0
        cfg.spectator_hit_effect_text_scale = max(0.5, min(2.0, float(cfg.spectator_hit_effect_text_scale or 1.0)))
        cfg.spectator_hit_effect_latency_log = bool(raw.get("spectator_hit_effect_latency_log", True))
        cfg.spectator_hit_effect_fast_emit = bool(raw.get("spectator_hit_effect_fast_emit", True))
        cfg.spectator_hit_effect_sprite_enabled = bool(raw.get("spectator_hit_effect_sprite_enabled", True))
        cfg.spectator_hit_effect_ring_enabled = bool(raw.get("spectator_hit_effect_ring_enabled", False))
        try:
            cfg.spectator_commentary_cooldown_sec = max(
                0.0, float(raw.get("spectator_commentary_cooldown_sec", 6.0))
            )
        except Exception:
            cfg.spectator_commentary_cooldown_sec = 6.0
        try:
            cfg.spectator_commentary_rate = max(80, min(320, int(raw.get("spectator_commentary_rate", 200) or 200)))
        except Exception:
            cfg.spectator_commentary_rate = 200
        try:
            cfg.spectator_commentary_volume = max(0.0, min(100.0, float(raw.get("spectator_commentary_volume", 100.0) or 100.0)))
        except Exception:
            cfg.spectator_commentary_volume = 100.0
        try:
            cfg.spectator_commentary_pitch = max(-100, min(100, int(raw.get("spectator_commentary_pitch", 0) or 0)))
        except Exception:
            cfg.spectator_commentary_pitch = 0
        try:
            cfg.spectator_replay_speed = float(raw.get("spectator_replay_speed", 1.0) or 1.0)
        except Exception:
            cfg.spectator_replay_speed = 1.0
        cfg.spectator_replay_real_time = bool(raw.get("spectator_replay_real_time", False))
        try:
            cfg.spectator_recent_text_size = max(10, min(80, int(raw.get("spectator_recent_text_size", 23) or 23)))
        except Exception:
            cfg.spectator_recent_text_size = 23
        try:
            cfg.spectatorlog_poll_ms = max(100, min(5000, int(raw.get("spectatorlog_poll_ms", 250) or 250)))
        except Exception:
            cfg.spectatorlog_poll_ms = 250
        cfg.spectatorlog_file_watch_enabled = bool(raw.get("spectatorlog_file_watch_enabled", True))
        try:
            cfg.spectatorlog_debounce_ms = max(0, min(500, int(raw.get("spectatorlog_debounce_ms", 8) or 8)))
        except Exception:
            cfg.spectatorlog_debounce_ms = 8
        try:
            cfg.spectatorlog_backup_poll_ms = max(250, min(10000, int(raw.get("spectatorlog_backup_poll_ms", 1500) or 1500)))
        except Exception:
            cfg.spectatorlog_backup_poll_ms = 1500
        cfg.spectatorlog_blackbox_enabled = bool(raw.get("spectatorlog_blackbox_enabled", False))
        cfg.spectatorlog_blackbox_dir = str(raw.get("spectatorlog_blackbox_dir", "SpectatorLogArchive") or "SpectatorLogArchive")
        cfg.spectatorlog_blackbox_mode = str(raw.get("spectatorlog_blackbox_mode", "smart") or "smart").strip().lower()
        if cfg.spectatorlog_blackbox_mode not in ("light", "smart", "full"):
            cfg.spectatorlog_blackbox_mode = "smart"
        try:
            cfg.spectatorlog_blackbox_poll_ms = max(50, min(5000, int(raw.get("spectatorlog_blackbox_poll_ms", 100) or 100)))
        except Exception:
            cfg.spectatorlog_blackbox_poll_ms = 100
        try:
            cfg.spectatorlog_blackbox_sample_ms = max(50, min(5000, int(raw.get("spectatorlog_blackbox_sample_ms", 250) or 250)))
        except Exception:
            cfg.spectatorlog_blackbox_sample_ms = 250
        try:
            cfg.spectatorlog_blackbox_max_snapshot_mb = max(1, min(1024, int(raw.get("spectatorlog_blackbox_max_snapshot_mb", 64) or 64)))
        except Exception:
            cfg.spectatorlog_blackbox_max_snapshot_mb = 64
        cfg.spectatorlog_blackbox_zip_on_close = bool(raw.get("spectatorlog_blackbox_zip_on_close", False))
        try:
            cfg.spectator_realtime_gauge_min_interval_ms = max(30, min(350, int(raw.get("spectator_realtime_gauge_min_interval_ms", 75) or 75)))
        except Exception:
            cfg.spectator_realtime_gauge_min_interval_ms = 75
        cfg.diagnostics_enabled = bool(raw.get("diagnostics_enabled", True))
        try:
            cfg.diagnostics_trace_minutes = max(1, min(120, int(raw.get("diagnostics_trace_minutes", 10) or 10)))
        except Exception:
            cfg.diagnostics_trace_minutes = 10
        try:
            cfg.diagnostics_raw_sample_lines = max(20, min(2000, int(raw.get("diagnostics_raw_sample_lines", 120) or 120)))
        except Exception:
            cfg.diagnostics_raw_sample_lines = 120
        cfg.diagnostics_mask_sensitive = bool(raw.get("diagnostics_mask_sensitive", True))

        cfg.roi_trigger = rect_from(raw.get("roi_trigger", {}))
        cfg.roi_left_player = rect_from(raw.get("roi_left_player", {}))
        cfg.roi_right_player = rect_from(raw.get("roi_right_player", {}))

        tr = raw.get("trigger", {})
        cfg.trigger = TriggerConfig(
            enabled=bool(tr.get("enabled", True)),
            target_bgr=tuple(tr.get("target_bgr", [0, 255, 0])),
            tolerance=int(tr.get("tolerance", 35)),
            consecutive_needed=int(tr.get("consecutive_needed", 6)),
            window_frames=int(tr.get("window_frames", 8)),
            cooldown_sec=float(tr.get("cooldown_sec", 2.0)),
            action_cooldown_sec=float(tr.get("action_cooldown_sec", 5.0)),
        )

        pc = raw.get("palette", {})
        cfg.palette = PaletteConfig(
            frames=int(pc.get("frames", 3)),
            k_colors=int(pc.get("k_colors", 5)),
            mask_thresh=float(pc.get("mask_thresh", 0.5)),
            max_pixels=int(pc.get("max_pixels", 12000)),
            min_v_cut=int(pc.get("min_v_cut", 10)),
        )
        cfg.timer_total_rounds = int(raw.get("timer_total_rounds", 3))
        cfg.timer_round_sec = int(raw.get("timer_round_sec", 180))
        cfg.timer_rest_sec = int(raw.get("timer_rest_sec", 60))
        cfg.timer_rest_30s_tts_enabled = bool(raw.get("timer_rest_30s_tts_enabled", True))
        cfg.timer_rest_30s_tts_rate = int(raw.get("timer_rest_30s_tts_rate", 200))
        cfg.timer_current_round = int(raw.get("timer_current_round", 1))
        cfg.timer_seconds_left = int(raw.get("timer_seconds_left", cfg.timer_round_sec))

        psp = str(raw.get("portrait_source_priority", "log") or "log").strip().lower()
        cfg.portrait_source_priority = "profile" if psp in ("profile", "profiles", "registered", "player", "players") else "log"

        cfg.overlay_bg_color = _normalize_hex_color(str(raw.get("overlay_bg_color", "transparent")))
        try:
            if "overlay_bg_opacity" in raw:
                cfg.overlay_bg_opacity = float(raw.get("overlay_bg_opacity", 0.0))
            else:
                cfg.overlay_bg_opacity = 1.0 if cfg.overlay_bg_color and cfg.overlay_bg_color != "transparent" else 0.0
        except Exception:
            cfg.overlay_bg_opacity = 0.0
        try:
            cfg.overlay_ui_bg_opacity = float(raw.get("overlay_ui_bg_opacity", raw.get("overlay_bg_opacity", 0.75)))
        except Exception:
            cfg.overlay_ui_bg_opacity = 0.75
        cfg.overlay_ui_bg_opacity = max(0.0, min(1.0, float(cfg.overlay_ui_bg_opacity if cfg.overlay_ui_bg_opacity is not None else 0.75)))
        try:
            cfg.overlay_window_opacity = float(raw.get("overlay_window_opacity", 1.0))
        except Exception:
            cfg.overlay_window_opacity = 1.0
        cfg.overlay_window_opacity = max(0.2, min(1.0, float(cfg.overlay_window_opacity or 1.0)))
        try:
            cfg.overlay_ui_scale = float(raw.get("overlay_ui_scale", 1.0))
        except Exception:
            cfg.overlay_ui_scale = 1.0
        try:
            cfg.overlay_timer_font_size = max(24, min(96, int(raw.get("overlay_timer_font_size", 54) or 54)))
        except Exception:
            cfg.overlay_timer_font_size = 54
        try:
            cfg.overlay_timer_x = max(-160, min(160, int(raw.get("overlay_timer_x", 0) or 0)))
        except Exception:
            cfg.overlay_timer_x = 0
        try:
            cfg.overlay_timer_y = max(-80, min(120, int(raw.get("overlay_timer_y", 0) or 0)))
        except Exception:
            cfg.overlay_timer_y = 0
        try:
            cfg.overlay_round_font_size = max(6, min(40, int(raw.get("overlay_round_font_size", 11) or 11)))
        except Exception:
            cfg.overlay_round_font_size = 11
        try:
            cfg.overlay_round_x = max(-160, min(160, int(raw.get("overlay_round_x", 0) or 0)))
        except Exception:
            cfg.overlay_round_x = 0
        try:
            cfg.overlay_round_y = max(-80, min(120, int(raw.get("overlay_round_y", 0) or 0)))
        except Exception:
            cfg.overlay_round_y = 0
        cfg.overlay_preset = str(raw.get("overlay_preset", "classic") or "classic").strip().lower()
        if cfg.overlay_preset not in ("classic", "tekken8"):
            cfg.overlay_preset = "classic"
        cfg.overlay_player_mask = _normalize_player_mask(raw.get("overlay_player_mask", "square"))
        cfg.overlay_show_round = bool(raw.get("overlay_show_round", True))
        cfg.overlay_show_time = bool(raw.get("overlay_show_time", True))
        cfg.overlay_show_blue_img = bool(raw.get("overlay_show_blue_img", True))
        cfg.overlay_show_blue_name = bool(raw.get("overlay_show_blue_name", True))
        cfg.overlay_show_red_img = bool(raw.get("overlay_show_red_img", True))
        cfg.overlay_show_red_name = bool(raw.get("overlay_show_red_name", True))
        cfg.overlay_show_arena_name = bool(raw.get("overlay_show_arena_name", True))
        cfg.overlay_show_flags = bool(raw.get("overlay_show_flags", True))
        cfg.overlay_show_cinematic = bool(raw.get("overlay_show_cinematic", True))
        cfg.overlay_vs_bg_path = str(raw.get("overlay_vs_bg_path", "") or "")
        try:
            cfg.overlay_vs_bg_opacity = max(0.0, min(1.0, float(raw.get("overlay_vs_bg_opacity", 1.0) or 1.0)))
        except Exception:
            cfg.overlay_vs_bg_opacity = 1.0
        cfg.overlay_vs_bg_by_arena = {str(k): str(v) for k, v in (raw.get("overlay_vs_bg_by_arena", {}) or {}).items()}
        try:
            cfg.overlay_vs_hold_sec = max(0.5, min(15.0, float(raw.get("overlay_vs_hold_sec", 2.85) or 2.85)))
        except Exception:
            cfg.overlay_vs_hold_sec = 2.85
        cfg.overlay_kd_image_path = normalize_builtin_asset_path(str(raw.get("overlay_kd_image_path", "assets/images/overlays/KD.png") or "assets/images/overlays/KD.png"))
        cfg.overlay_tko_image_path = normalize_builtin_asset_path(str(raw.get("overlay_tko_image_path", "assets/images/overlays/TKO.png") or "assets/images/overlays/TKO.png"))
        try:
            cfg.overlay_ko_image_scale_pct = max(30, min(200, int(raw.get("overlay_ko_image_scale_pct", 100) or 100)))
            cfg.overlay_ko_x = max(-800, min(800, int(raw.get("overlay_ko_x", 0) or 0)))
            cfg.overlay_ko_y = max(-450, min(450, int(raw.get("overlay_ko_y", 0) or 0)))
            cfg.overlay_ko_motion_blur_pct = max(0, min(200, int(raw.get("overlay_ko_motion_blur_pct", 100) or 0)))
            cfg.overlay_ko_flash_intensity_pct = max(0, min(200, int(raw.get("overlay_ko_flash_intensity_pct", 100) or 0)))
            cfg.overlay_ko_trail_intensity_pct = max(0, min(200, int(raw.get("overlay_ko_trail_intensity_pct", 100) or 0)))
            cfg.overlay_ko_shake_intensity_pct = max(0, min(200, int(raw.get("overlay_ko_shake_intensity_pct", 100) or 0)))
            cfg.overlay_ko_perspective_px = max(700, min(3000, int(raw.get("overlay_ko_perspective_px", 1400) or 1400)))
            cfg.overlay_ko_start_z_px = max(100, min(2400, int(raw.get("overlay_ko_start_z_px", 760) or 760)))
            cfg.overlay_ko_impact_depth_px = max(0, min(180, int(raw.get("overlay_ko_impact_depth_px", 34) or 0)))
            cfg.overlay_ko_rebound_px = max(0, min(120, int(raw.get("overlay_ko_rebound_px", 20) or 0)))
            cfg.overlay_ko_entry_ms = max(250, min(1200, int(raw.get("overlay_ko_entry_ms", 500) or 500)))
            cfg.overlay_ko_drop_y_px = max(0, min(500, int(raw.get("overlay_ko_drop_y_px", 190) or 0)))
        except Exception:
            cfg.overlay_ko_image_scale_pct = 100
            cfg.overlay_ko_x = 0
            cfg.overlay_ko_y = 0
            cfg.overlay_ko_motion_blur_pct = 100
            cfg.overlay_ko_flash_intensity_pct = 100
            cfg.overlay_ko_trail_intensity_pct = 100
            cfg.overlay_ko_shake_intensity_pct = 100
            cfg.overlay_ko_perspective_px = 1400
            cfg.overlay_ko_start_z_px = 760
            cfg.overlay_ko_impact_depth_px = 34
            cfg.overlay_ko_rebound_px = 20
            cfg.overlay_ko_entry_ms = 500
            cfg.overlay_ko_drop_y_px = 190
        cfg.overlay_ko_screen_shake = bool(raw.get("overlay_ko_screen_shake", True))
        try:
            cfg.overlay_kd_hold_sec = max(0.8, min(10.0, float(raw.get("overlay_kd_hold_sec", 2.2) or 2.2)))
            cfg.overlay_tko_hold_sec = max(0.8, min(10.0, float(raw.get("overlay_tko_hold_sec", 2.6) or 2.6)))
        except Exception:
            cfg.overlay_kd_hold_sec = 2.2
            cfg.overlay_tko_hold_sec = 2.6
        try:
            cfg.browser_overlay_scale = max(0.25, min(4.0, float(raw.get("browser_overlay_scale", 1.0) or 1.0)))
        except Exception:
            cfg.browser_overlay_scale = 1.0
        try:
            cfg.browser_overlay_poll_ms = max(16, min(1000, int(raw.get("browser_overlay_poll_ms", 50) or 50)))
        except Exception:
            cfg.browser_overlay_poll_ms = 50
        cfg.browser_overlay_output_only = bool(raw.get("browser_overlay_output_only", True))
        try:
            cfg.browser_fullscreen_fx_intensity = max(0.0, min(3.0, float(raw.get("browser_fullscreen_fx_intensity", 1.6) or 1.6)))
        except Exception:
            cfg.browser_fullscreen_fx_intensity = 1.6
        cfg.qml_preview_enabled = bool(raw.get("qml_preview_enabled", True))
        cfg.qml_effects_enabled = bool(raw.get("qml_effects_enabled", False))
        cfg.overlay_style_round = _normalize_overlay_style(raw.get("overlay_style_round"), _default_overlay_style_round())
        cfg.overlay_style_time = _normalize_overlay_style(raw.get("overlay_style_time"), _default_overlay_style_time())
        cfg.overlay_style_blue_name = _normalize_overlay_style(raw.get("overlay_style_blue_name"), _default_overlay_style_blue_name())
        cfg.overlay_style_red_name = _normalize_overlay_style(raw.get("overlay_style_red_name"), _default_overlay_style_red_name())
        cfg.overlay_style_arena = _normalize_overlay_style(raw.get("overlay_style_arena"), _default_overlay_style_arena())
        cfg.browser_text_styles = _normalize_browser_text_styles(raw.get("browser_text_styles"))
        cfg.capture_player_images = bool(raw.get("capture_player_images", True))

        cfg.action_cooldown_sec = float(raw.get("action_cooldown_sec", 5.0))
        cfg.action_cooldowns = {str(k): float(v) for k, v in (raw.get("action_cooldowns", {}) or {}).items()}
        cfg.action_edge_triggers = {str(k): bool(v) for k, v in (raw.get("action_edge_triggers", {}) or {}).items()}
        if bool(tr.get("edge_trigger", False)) and "on_trigger" not in cfg.action_edge_triggers:
            cfg.action_edge_triggers["on_trigger"] = True

        cfg.players = {str(k).upper(): str(v) for k, v in raw.get("players", {}).items()}
        cfg.players_images = {str(k).upper(): str(v) for k, v in raw.get("players_images", {}).items()}
        cfg.players_countries = {
            str(k).upper(): _normalize_player_country(v)
            for k, v in (raw.get("players_countries", {}) or {}).items()
        }
        cfg.players_flags = {str(k).upper(): str(v) for k, v in (raw.get("players_flags", {}) or {}).items()}
        for gid in cfg.players.keys():
            cfg.players_countries.setdefault(str(gid).upper(), "KR")
            cfg.players_flags.setdefault(str(gid).upper(), "")
        cfg.current_blue_id = str(raw.get("current_blue_id", "") or "").upper().strip()
        cfg.current_red_id = str(raw.get("current_red_id", "") or "").upper().strip()
        cfg.current_blue_registered = bool(raw.get("current_blue_registered", False))
        cfg.current_red_registered = bool(raw.get("current_red_registered", False))
        cfg.current_blue_valid = bool(raw.get("current_blue_valid", False))
        cfg.current_red_valid = bool(raw.get("current_red_valid", False))
        cfg.koth_enabled = bool(raw.get("koth_enabled", False))
        cfg.koth_champion_id = str(raw.get("koth_champion_id", "") or "").upper().strip()
        cfg.koth_streak = max(0, int(raw.get("koth_streak", 0) or 0))
        cfg.koth_min_score = max(0, min(100, int(raw.get("koth_min_score", 75) or 75)))
        cfg.layout = raw.get("layout", {}) or {}
        cfg.actions = raw.get("actions", {}) or {}
        removed_action_types = {"ocr_refresh", "koth_winner_ocr"}
        cfg.actions = {
            str(event): [
                dict(action)
                for action in list(actions or [])
                if str((action or {}).get("type", "")).lower() not in removed_action_types
            ]
            for event, actions in dict(cfg.actions or {}).items()
        }

        if not cfg.coords_global:
            # Convert stored local coords to global coords once.
            try:
                if cfg.roi_trigger.valid():
                    tmon = int(raw.get("trigger_monitor_index", cfg.monitor_index))
                    cfg.roi_trigger = rect_local_to_global(tmon, cfg.roi_trigger)
            except Exception:
                pass

            try:
                for key, mon in list(cfg.roi_monitors.items()):
                    rect = getattr(cfg, key, None)
                    if isinstance(rect, Rect) and rect.valid():
                        setattr(cfg, key, rect_local_to_global(int(mon), rect))
            except Exception:
                pass
            cfg.roi_monitors = {}

            try:
                for rule in cfg.pixel_rules or []:
                    mode = str(rule.get("mode", "pixel"))
                    mon = int(rule.get("monitor_index", cfg.monitor_index))
                    if mode == "roi":
                        rr = rule.get("roi", {}) or {}
                        rect = Rect(
                            x=int(rr.get("x", 0)),
                            y=int(rr.get("y", 0)),
                            w=int(rr.get("w", 0)),
                            h=int(rr.get("h", 0)),
                        )
                        if rect.valid():
                            g = rect_local_to_global(mon, rect)
                            rule["roi"] = {"x": g.x, "y": g.y, "w": g.w, "h": g.h}
                    else:
                        x = int(rule.get("x", 0))
                        y = int(rule.get("y", 0))
                        gx, gy = xy_local_to_global(mon, x, y)
                        rule["x"] = int(gx)
                        rule["y"] = int(gy)
                    if "monitor_index" in rule:
                        rule.pop("monitor_index", None)
            except Exception:
                pass

            try:
                for ev, acts in list(cfg.actions.items()):
                    new_acts = []
                    for act in acts or []:
                        if not isinstance(act, dict):
                            new_acts.append(act)
                            continue
                        atype = str(act.get("type", "")).lower()
                        if atype in ("mouse_move", "mouse_click", "mouse_down", "mouse_up"):
                            if act.get("use_monitor") is False:
                                new_acts.append(act)
                                continue
                            mon = int(act.get("monitor", cfg.monitor_index))
                            try:
                                x = int(act.get("x"))
                                y = int(act.get("y"))
                            except Exception:
                                x = None
                                y = None
                            if x is not None and y is not None:
                                gx, gy = xy_local_to_global(mon, x, y)
                                act["x"] = int(gx)
                                act["y"] = int(gy)
                            act["use_monitor"] = False
                            act.pop("monitor", None)
                        new_acts.append(act)
                    cfg.actions[ev] = new_acts
            except Exception:
                pass

            cfg.coords_global = True

        cfg.actions = _normalize_mouse_actions(cfg.actions, cfg.monitor_index)
        raw_pixel_rules = raw.get("pixel_rules", []) or []
        norm_pixel_rules = []
        for i, rule in enumerate(raw_pixel_rules):
            r = dict(rule or {})
            if not r.get("id"):
                r["id"] = f"pixel_{uuid.uuid4().hex}"
            if not r.get("name"):
                r["name"] = f"rule{i+1}"
            norm_pixel_rules.append(r)
        cfg.pixel_rules = norm_pixel_rules

        # Sound detection was removed; legacy sound config is intentionally ignored.
        raw_win_effects = raw.get("win_effects", {}) or {}
        cfg.win_effects = _migrate_win_effects_legacy(
            _merge_dict(default_win_effects(), raw_win_effects),
            raw_win_effects,
        )
        cfg.actions = migrate_action_keys(cfg.actions, cfg.pixel_rules)
        cfg.actions = sync_action_keys(cfg.actions, cfg.pixel_rules)
        cfg.actions = prune_actions(cfg.actions, cfg.pixel_rules)
        return cfg

    def to_json(self, path: str) -> None:
        self.actions = sync_action_keys(self.actions, self.pixel_rules)
        self.actions = prune_actions(self.actions, self.pixel_rules)
        raw = {
            "monitor_index": self.monitor_index,
            "trigger_monitor_index": self.trigger_monitor_index,
            "roi_monitors": self.roi_monitors,
            "coords_global": self.coords_global,
            "roi_hotkey": self.roi_hotkey,
            "pixel_hotkey": self.pixel_hotkey,
            "detect_hotkey": self.detect_hotkey,
            "trigger_pixel_hotkey": self.trigger_pixel_hotkey,
            "action_pick_hotkey": self.action_pick_hotkey,
            "action_test_hotkey": self.action_test_hotkey,
            "chapter_anchor_epoch": float(self.chapter_anchor_epoch or 0.0),
            "chapter_offset_sec": int(self.chapter_offset_sec),
            "chapter_dedupe_sec": int(self.chapter_dedupe_sec),
            "chapter_output_dir": str(self.chapter_output_dir or ""),
            "chapter_nickname_only": bool(self.chapter_nickname_only),
            "chapter_hide_time": bool(self.chapter_hide_time),
            "obs_integration_enabled": bool(self.obs_integration_enabled),
            "obs_host": str(self.obs_host or "127.0.0.1"),
            "obs_port": int(max(1, min(65535, self.obs_port))),
            "obs_password": str(self.obs_password or ""),
            "obs_auto_chapter_enabled": bool(self.obs_auto_chapter_enabled),
            "obs_chapter_add_start_event": bool(self.obs_chapter_add_start_event),
            "obs_chapter_export_on_stop": bool(self.obs_chapter_export_on_stop),
            "obs_replay_buffer_enabled": bool(self.obs_replay_buffer_enabled),
            "obs_replay_buffer_auto_start": bool(self.obs_replay_buffer_auto_start),
            "obs_highlight_kd": bool(self.obs_highlight_kd),
            "obs_highlight_tko": bool(self.obs_highlight_tko),
            "obs_highlight_stun": bool(self.obs_highlight_stun),
            "obs_highlight_counter": bool(self.obs_highlight_counter),
            "obs_highlight_combo": bool(self.obs_highlight_combo),
            "obs_highlight_heavy": bool(self.obs_highlight_heavy),
            "obs_highlight_counter_damage_min": float(max(0.0, min(300.0, self.obs_highlight_counter_damage_min))),
            "obs_highlight_combo_min": int(max(2, min(20, self.obs_highlight_combo_min))),
            "obs_highlight_damage_min": float(max(0.0, min(300.0, self.obs_highlight_damage_min))),
            "obs_highlight_cooldown_sec": float(max(0.0, min(120.0, self.obs_highlight_cooldown_sec))),
            "obs_auto_replay_enabled": bool(self.obs_auto_replay_enabled),
            "obs_auto_replay_kd": bool(self.obs_auto_replay_kd),
            "obs_auto_replay_tko": bool(self.obs_auto_replay_tko),
            "obs_auto_replay_capture_delay_sec": float(max(0.0, min(15.0, self.obs_auto_replay_capture_delay_sec))),
            "obs_auto_replay_delay_sec": float(max(0.0, min(15.0, self.obs_auto_replay_delay_sec))),
            "obs_auto_replay_muted": bool(self.obs_auto_replay_muted),
            "obs_auto_replay_volume": int(max(0, min(100, self.obs_auto_replay_volume))),
            "obs_auto_replay_fit": str(self.obs_auto_replay_fit or "cover"),
            "obs_auto_replay_fade_ms": int(max(0, min(2000, self.obs_auto_replay_fade_ms))),
            "obs_auto_replay_stop_on_round": bool(self.obs_auto_replay_stop_on_round),
            "idle_highlight_enabled": bool(self.idle_highlight_enabled),
            "idle_highlight_path": to_app_rel(str(self.idle_highlight_path or "")),
            "idle_highlight_random": bool(self.idle_highlight_random),
            "idle_highlight_muted": bool(self.idle_highlight_muted),
            "idle_highlight_volume": int(max(0, min(100, self.idle_highlight_volume))),
            "idle_highlight_fit": str(self.idle_highlight_fit or "cover"),
            "idle_highlight_fade_ms": int(max(0, min(3000, self.idle_highlight_fade_ms))),
            "spectatorlog_enabled": bool(self.spectatorlog_enabled),
            "spectatorlog_path": to_app_rel(str(self.spectatorlog_path or "")),
            "spectatorlog_poll_ms": int(self.spectatorlog_poll_ms or 250),
            "spectatorlog_file_watch_enabled": bool(self.spectatorlog_file_watch_enabled),
            "spectatorlog_debounce_ms": int(self.spectatorlog_debounce_ms or 8),
            "spectatorlog_backup_poll_ms": int(self.spectatorlog_backup_poll_ms or 1500),
            "spectatorlog_blackbox_enabled": bool(self.spectatorlog_blackbox_enabled),
            "spectatorlog_blackbox_dir": to_app_rel(str(self.spectatorlog_blackbox_dir or "SpectatorLogArchive")),
            "spectatorlog_blackbox_mode": str(self.spectatorlog_blackbox_mode or "smart"),
            "spectatorlog_blackbox_poll_ms": int(self.spectatorlog_blackbox_poll_ms or 100),
            "spectatorlog_blackbox_sample_ms": int(self.spectatorlog_blackbox_sample_ms or 250),
            "spectatorlog_blackbox_max_snapshot_mb": int(self.spectatorlog_blackbox_max_snapshot_mb or 64),
            "spectatorlog_blackbox_zip_on_close": bool(self.spectatorlog_blackbox_zip_on_close),
            "spectator_realtime_gauge_min_interval_ms": int(self.spectator_realtime_gauge_min_interval_ms or 75),
            "spectatorlog_sync_timer": bool(self.spectatorlog_sync_timer),
            "spectatorlog_sync_players": bool(self.spectatorlog_sync_players),
            "spectator_lobby_auto_start_enabled": bool(self.spectator_lobby_auto_start_enabled),
            "spectator_lobby_auto_start_target_title": str(
                self.spectator_lobby_auto_start_target_title or "The Thrill of the Fight 2"
            ),
            "spectator_lobby_auto_start_client_x": int(max(0, self.spectator_lobby_auto_start_client_x)),
            "spectator_lobby_auto_start_client_y": int(max(0, self.spectator_lobby_auto_start_client_y)),
            "spectator_lobby_auto_start_reference_width": int(max(0, self.spectator_lobby_auto_start_reference_width)),
            "spectator_lobby_auto_start_reference_height": int(max(0, self.spectator_lobby_auto_start_reference_height)),
            "spectator_lobby_auto_start_click_count": int(
                max(1, min(10, self.spectator_lobby_auto_start_click_count))
            ),
            "spectator_lobby_auto_start_delay_ms": int(max(0, min(5000, self.spectator_lobby_auto_start_delay_ms))),
            "spectator_lobby_auto_start_activate": bool(self.spectator_lobby_auto_start_activate),
            "spectator_lobby_auto_start_restore_focus": bool(self.spectator_lobby_auto_start_restore_focus),
            "spectator_lobby_auto_start_restore_cursor": bool(self.spectator_lobby_auto_start_restore_cursor),
            "spectator_lobby_auto_start_minimize_target": bool(
                self.spectator_lobby_auto_start_minimize_target
            ),
            "spectator_final_report_delay_sec": float(max(0.0, min(30.0, self.spectator_final_report_delay_sec))),
            "spectator_sp_throw_cost_scale": float(max(0.1, min(5.0, self.spectator_sp_throw_cost_scale))),
            "spectator_sp_impact_cost_scale": float(max(0.0, min(5.0, self.spectator_sp_impact_cost_scale))),
            "spectator_sp_fight_recovery_pct": float(max(0.0, min(100.0, self.spectator_sp_fight_recovery_pct))),
            "spectator_sp_break_recovery_pct": float(max(0.0, min(100.0, self.spectator_sp_break_recovery_pct))),
            "spectator_sp_recovery_delay_sec": float(max(0.0, min(10.0, self.spectator_sp_recovery_delay_sec))),
            "spectator_sp_bar_x": int(max(-300, min(300, self.spectator_sp_bar_x))),
            "spectator_sp_bar_y": int(max(-100, min(100, self.spectator_sp_bar_y))),
            "spectator_sp_bar_length_pct": int(max(25, min(160, self.spectator_sp_bar_length_pct))),
            "spectator_sp_bar_thickness": int(max(2, min(40, self.spectator_sp_bar_thickness))),
            "spectator_sp_bar_color": _normalize_hex_color(str(self.spectator_sp_bar_color or "#1876d3")),
            "spectator_name_bar_x": int(max(-300, min(300, self.spectator_name_bar_x))),
            "spectator_name_bar_y": int(max(-100, min(100, self.spectator_name_bar_y))),
            "spectator_fight_style_enabled": bool(self.spectator_fight_style_enabled),
            "spectator_fight_style_min_attempts": int(
                max(1, min(500, self.spectator_fight_style_min_attempts))
            ),
            "spectator_fight_style_min_landed": int(
                max(1, min(500, self.spectator_fight_style_min_landed))
            ),
            "spectator_commentary_enabled": bool(self.spectator_commentary_enabled),
            "spectator_commentary_mode": str(self.spectator_commentary_mode or "standard"),
            "spectator_commentary_min_damage": float(self.spectator_commentary_min_damage or 25.0),
            "spectator_hit_effect_damage": float(self.spectator_hit_effect_damage or 45.0),
            "spectator_hit_effect_color_preset": str(self.spectator_hit_effect_color_preset or "classic"),
            "spectator_hit_effect_color_low": _normalize_hex_color(str(self.spectator_hit_effect_color_low or "#38bdf8")),
            "spectator_hit_effect_color_mid": _normalize_hex_color(str(self.spectator_hit_effect_color_mid or "#fb923c")),
            "spectator_hit_effect_color_high": _normalize_hex_color(str(self.spectator_hit_effect_color_high or "#f87171")),
            "spectator_hit_effect_color_weak": _normalize_hex_color(str(self.spectator_hit_effect_color_weak or "#facc15")),
            "spectator_hit_effect_color_stun": _normalize_hex_color(str(self.spectator_hit_effect_color_stun or "#ef4444")),
            "spectator_hit_effect_duration_ms": int(max(80, min(1200, int(self.spectator_hit_effect_duration_ms or 170)))),
            "spectator_hit_effect_base_size": int(max(24, min(240, int(self.spectator_hit_effect_base_size or 86)))),
            "spectator_hit_effect_damage_scale": float(max(0.0, min(3.0, float(self.spectator_hit_effect_damage_scale or 0.42)))),
            "spectator_hit_effect_ring_width": int(max(1, min(20, int(self.spectator_hit_effect_ring_width or 4)))),
            "spectator_hit_effect_opacity": float(max(0.05, min(1.5, float(self.spectator_hit_effect_opacity or 1.0)))),
            "spectator_hit_effect_glow": float(max(0.0, min(3.0, float(self.spectator_hit_effect_glow or 1.0)))),
            "spectator_hit_effect_fill_opacity": float(max(0.0, min(1.5, float(self.spectator_hit_effect_fill_opacity or 1.0)))),
            "spectator_hit_effect_show_text": bool(self.spectator_hit_effect_show_text),
            "spectator_hit_effect_text_scale": float(max(0.5, min(2.0, float(self.spectator_hit_effect_text_scale or 1.0)))),
            "spectator_hit_effect_latency_log": bool(self.spectator_hit_effect_latency_log),
            "spectator_hit_effect_fast_emit": bool(self.spectator_hit_effect_fast_emit),
            "spectator_hit_effect_sprite_enabled": bool(self.spectator_hit_effect_sprite_enabled),
            "spectator_hit_effect_ring_enabled": bool(self.spectator_hit_effect_ring_enabled),
            "spectator_commentary_cooldown_sec": max(
                0.0, float(self.spectator_commentary_cooldown_sec)
            ),
            "spectator_commentary_voice": str(self.spectator_commentary_voice or "ko-KR-SunHiNeural"),
            "spectator_caster_voice": str(self.spectator_caster_voice or "ko-KR-InJoonNeural"),
            "spectator_commentary_rate": int(self.spectator_commentary_rate or 200),
            "spectator_commentary_volume": float(self.spectator_commentary_volume if self.spectator_commentary_volume is not None else 100.0),
            "spectator_commentary_pitch": int(self.spectator_commentary_pitch or 0),
            "spectator_replay_speed": float(self.spectator_replay_speed or 1.0),
            "spectator_replay_real_time": bool(self.spectator_replay_real_time),
            "spectator_recent_text_size": int(self.spectator_recent_text_size or 23),
            "spectator_stun_sfx_path": to_app_rel(normalize_builtin_asset_path(str(self.spectator_stun_sfx_path or ""))),
            "spectator_knockdown_sfx_path": to_app_rel(normalize_builtin_asset_path(str(self.spectator_knockdown_sfx_path or ""))),
            "spectator_tko_sfx_path": to_app_rel(normalize_builtin_asset_path(str(self.spectator_tko_sfx_path or ""))),
            "spectator_sfx_playback_rate": float(self.spectator_sfx_playback_rate or 1.0),
            "diagnostics_enabled": bool(getattr(self, "diagnostics_enabled", True)),
            "diagnostics_trace_minutes": int(max(1, min(120, int(getattr(self, "diagnostics_trace_minutes", 10) or 10)))),
            "diagnostics_raw_sample_lines": int(max(20, min(2000, int(getattr(self, "diagnostics_raw_sample_lines", 120) or 120)))),
            "diagnostics_mask_sensitive": bool(getattr(self, "diagnostics_mask_sensitive", True)),
            "roi_trigger": asdict(self.roi_trigger),
            "roi_left_player": asdict(self.roi_left_player),
            "roi_right_player": asdict(self.roi_right_player),
            "trigger": asdict(self.trigger),
            "palette": asdict(self.palette),
            "timer_total_rounds": self.timer_total_rounds,
            "timer_round_sec": self.timer_round_sec,
            "timer_rest_sec": self.timer_rest_sec,
            "timer_rest_30s_tts_enabled": bool(self.timer_rest_30s_tts_enabled),
            "timer_rest_30s_tts_rate": int(self.timer_rest_30s_tts_rate),
            "timer_current_round": self.timer_current_round,
            "timer_seconds_left": self.timer_seconds_left,
            "overlay_bg_color": self.overlay_bg_color,
            "overlay_bg_opacity": self.overlay_bg_opacity,
            "overlay_ui_bg_opacity": self.overlay_ui_bg_opacity,
            "overlay_window_opacity": self.overlay_window_opacity,
            "overlay_ui_scale": self.overlay_ui_scale,
            "portrait_source_priority": self.portrait_source_priority,
            "overlay_timer_font_size": int(self.overlay_timer_font_size or 54),
            "overlay_timer_x": int(self.overlay_timer_x or 0),
            "overlay_timer_y": int(self.overlay_timer_y or 0),
            "overlay_round_font_size": int(self.overlay_round_font_size or 11),
            "overlay_round_x": int(self.overlay_round_x or 0),
            "overlay_round_y": int(self.overlay_round_y or 0),
            "overlay_preset": self.overlay_preset,
            "overlay_player_mask": self.overlay_player_mask,
            "overlay_show_round": self.overlay_show_round,
            "overlay_show_time": self.overlay_show_time,
            "overlay_show_blue_img": self.overlay_show_blue_img,
            "overlay_show_blue_name": self.overlay_show_blue_name,
            "overlay_show_red_img": self.overlay_show_red_img,
            "overlay_show_red_name": self.overlay_show_red_name,
            "overlay_show_arena_name": self.overlay_show_arena_name,
            "overlay_show_flags": self.overlay_show_flags,
            "overlay_show_cinematic": self.overlay_show_cinematic,
            "overlay_vs_bg_path": to_app_rel(str(self.overlay_vs_bg_path or "")),
            "overlay_vs_bg_opacity": float(self.overlay_vs_bg_opacity if self.overlay_vs_bg_opacity is not None else 1.0),
            "overlay_vs_bg_by_arena": {str(k): to_app_rel(str(v)) for k, v in (self.overlay_vs_bg_by_arena or {}).items()},
            "overlay_vs_hold_sec": float(self.overlay_vs_hold_sec if self.overlay_vs_hold_sec is not None else 2.85),
            "overlay_kd_image_path": to_app_rel(normalize_builtin_asset_path(str(self.overlay_kd_image_path or "assets/images/overlays/KD.png"))),
            "overlay_tko_image_path": to_app_rel(normalize_builtin_asset_path(str(self.overlay_tko_image_path or "assets/images/overlays/TKO.png"))),
            "overlay_ko_image_scale_pct": int(max(30, min(200, self.overlay_ko_image_scale_pct))),
            "overlay_ko_x": int(max(-800, min(800, self.overlay_ko_x))),
            "overlay_ko_y": int(max(-450, min(450, self.overlay_ko_y))),
            "overlay_ko_motion_blur_pct": int(max(0, min(200, self.overlay_ko_motion_blur_pct))),
            "overlay_ko_flash_intensity_pct": int(max(0, min(200, self.overlay_ko_flash_intensity_pct))),
            "overlay_ko_trail_intensity_pct": int(max(0, min(200, self.overlay_ko_trail_intensity_pct))),
            "overlay_ko_shake_intensity_pct": int(max(0, min(200, self.overlay_ko_shake_intensity_pct))),
            "overlay_ko_screen_shake": bool(self.overlay_ko_screen_shake),
            "overlay_ko_perspective_px": int(max(700, min(3000, self.overlay_ko_perspective_px))),
            "overlay_ko_start_z_px": int(max(100, min(2400, self.overlay_ko_start_z_px))),
            "overlay_ko_impact_depth_px": int(max(0, min(180, self.overlay_ko_impact_depth_px))),
            "overlay_ko_rebound_px": int(max(0, min(120, self.overlay_ko_rebound_px))),
            "overlay_ko_entry_ms": int(max(250, min(1200, self.overlay_ko_entry_ms))),
            "overlay_ko_drop_y_px": int(max(0, min(500, self.overlay_ko_drop_y_px))),
            "overlay_kd_hold_sec": float(max(0.8, min(10.0, self.overlay_kd_hold_sec))),
            "overlay_tko_hold_sec": float(max(0.8, min(10.0, self.overlay_tko_hold_sec))),
            "browser_overlay_scale": float(self.browser_overlay_scale if self.browser_overlay_scale is not None else 1.0),
            "browser_overlay_poll_ms": int(self.browser_overlay_poll_ms or 50),
            "browser_overlay_output_only": bool(self.browser_overlay_output_only),
            "browser_fullscreen_fx_intensity": float(self.browser_fullscreen_fx_intensity if self.browser_fullscreen_fx_intensity is not None else 1.6),
            "qml_preview_enabled": bool(self.qml_preview_enabled),
            "qml_effects_enabled": bool(self.qml_effects_enabled),
            "overlay_style_round": self.overlay_style_round,
            "overlay_style_time": self.overlay_style_time,
            "overlay_style_blue_name": self.overlay_style_blue_name,
            "overlay_style_red_name": self.overlay_style_red_name,
            "overlay_style_arena": self.overlay_style_arena,
            "browser_text_styles": self.browser_text_styles,
            "capture_player_images": self.capture_player_images,
            "action_cooldown_sec": self.action_cooldown_sec,
            "action_cooldowns": self.action_cooldowns,
            "action_edge_triggers": self.action_edge_triggers,
            "players": self.players,
            "players_images": {str(k): to_app_rel(v) for k, v in (self.players_images or {}).items()},
            "players_countries": {
                str(k): _normalize_player_country(v)
                for k, v in (self.players_countries or {}).items()
            },
            "players_flags": {str(k): to_app_rel(v) for k, v in (self.players_flags or {}).items()},
            "current_blue_id": str(self.current_blue_id or ""),
            "current_red_id": str(self.current_red_id or ""),
            "current_blue_registered": bool(self.current_blue_registered),
            "current_red_registered": bool(self.current_red_registered),
            "current_blue_valid": bool(self.current_blue_valid),
            "current_red_valid": bool(self.current_red_valid),
            "koth_enabled": bool(self.koth_enabled),
            "koth_champion_id": str(self.koth_champion_id or ""),
            "koth_streak": int(self.koth_streak or 0),
            "koth_min_score": int(self.koth_min_score or 75),
            "layout": self.layout,
            "actions": self.actions,
            "pixel_rules": self.pixel_rules,
            "win_effects": _normalize_win_effects_paths(self.win_effects),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
