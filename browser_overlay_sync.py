# browser_overlay_sync.py
# -*- coding: utf-8 -*-
"""Bridge TimerBackend state into the OBS browser overlay server.

The old implementation lived inside MainApp. Keeping it here reduces the
main application size and makes future browser-output optimizations safer.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional, Tuple

from config_model import _normalize_browser_text_styles


class BrowserOverlaySync:
    def __init__(self, cfg, timer_win, browser_overlay, asset_syncer: Optional[Callable[[dict], dict]] = None):
        self.cfg = cfg
        self.timer_win = timer_win
        self.browser_overlay = browser_overlay
        self._asset_syncer = asset_syncer
        self._browser_overlay_image_revs = {"blue": -1, "red": -1}
        self._last_payload = None
        self._last_asset_paths = {}
        self._last_asset_sync_ts = 0.0
        self._asset_sync_interval_sec = 0.50

    def _set_asset_path_if_changed(self, name: str, path: str) -> None:
        key = str(name or "").strip().lower()
        value = str(path or "").strip()
        if self._last_asset_paths.get(key) == value:
            return
        self._last_asset_paths[key] = value
        self.browser_overlay.set_asset_path(key, value)

    def mark_dirty(self) -> None:
        """Force the next periodic publish to run immediately."""
        self._last_asset_sync_ts = 0.0
        self._last_payload = None

    def publish(self):
        try:
            if bool(getattr(self.cfg, "browser_overlay_output_only", True)):
                if self._asset_syncer is None:
                    return
                now = time.monotonic()
                # In browser-output-only mode, live SpectatorLog updates call the direct
                # update path immediately. This periodic pass is only a safety net for
                # late image/path changes, so avoid doing file reads/player matching
                # every 50 ms.
                if now - self._last_asset_sync_ts < self._asset_sync_interval_sec:
                    return
                self._last_asset_sync_ts = now
                try:
                    update = self._asset_syncer({})
                    if update:
                        self.browser_overlay.update(**update)
                except Exception:
                    logging.debug("BROWSER_OVERLAY_PERIODIC_ASSET_SYNC_FAIL", exc_info=True)
                return
            b = self.timer_win._backend
            def _hp_pair(long_value: float, mid_value: float) -> Tuple[float, float]:
                try:
                    base = max(0.0, min(1.0, (100.0 - float(long_value or 0.0)) / 100.0))
                    mid = max(0.0, min(1.0, float(mid_value or 0.0) / 100.0))
                    current = max(0.0, min(1.0, base * (1.0 - mid)))
                    return current, max(0.0, base - current)
                except Exception:
                    return 1.0, 0.0
            blue_hp, blue_ghost = _hp_pair(getattr(b, "_blue_punishment_long", 0.0), getattr(b, "_blue_punishment_mid", 0.0))
            red_hp, red_ghost = _hp_pair(getattr(b, "_red_punishment_long", 0.0), getattr(b, "_red_punishment_mid", 0.0))
            try:
                self._set_asset_path_if_changed("blueflag", str(getattr(b, "_blue_flag_source", "") or ""))
                self._set_asset_path_if_changed("redflag", str(getattr(b, "_red_flag_source", "") or ""))
                try:
                    vs_bg_path = b._resolve_vs_background_path()
                except Exception:
                    vs_bg_path = str(getattr(b, "_overlay_vs_bg_path", "") or "")
                self._set_asset_path_if_changed("vsbg", vs_bg_path)
            except Exception:
                pass
            try:
                revs = getattr(self, "_browser_overlay_image_revs", {})
                for side in ("blue", "red"):
                    rev = int(getattr(b, f"_{side}_image_rev", 0) or 0)
                    if revs.get(side) != rev:
                        img = self.timer_win._provider.image(side)
                        self.browser_overlay.set_image(side, img)
                        revs[side] = rev
                self._browser_overlay_image_revs = revs
            except Exception as e:
                logging.debug("BROWSER_OVERLAY_IMAGE_SYNC skipped: %s", e)
            payload = dict(
                timeText=str(getattr(b, "_time_text", "") or ""),
                roundText=str(getattr(b, "_round_text", "") or ""),
                blueName=str(getattr(b, "_blue_name", "") or ""),
                redName=str(getattr(b, "_red_name", "") or ""),
                arenaName=str(getattr(b, "_arena_name", "") or ""),
                blueDamageText=str(getattr(b, "_blue_damage_text", "") or ""),
                redDamageText=str(getattr(b, "_red_damage_text", "") or ""),
                blueTotalDamageText=str(getattr(b, "_blue_total_damage_text", "0") or "0"),
                redTotalDamageText=str(getattr(b, "_red_total_damage_text", "0") or "0"),
                blueSpRatio=float(getattr(b, "_blue_sp_ratio", 1.0) or 0.0),
                redSpRatio=float(getattr(b, "_red_sp_ratio", 1.0) or 0.0),
                blueRoundKnockdowns=int(getattr(b, "_blue_round_knockdowns", 0) or 0),
                redRoundKnockdowns=int(getattr(b, "_red_round_knockdowns", 0) or 0),
                blueComboHitText=str(getattr(b, "_blue_combo_hit_text", "") or ""),
                blueComboDamageText=str(getattr(b, "_blue_combo_damage_text", "") or ""),
                redComboHitText=str(getattr(b, "_red_combo_hit_text", "") or ""),
                redComboDamageText=str(getattr(b, "_red_combo_damage_text", "") or ""),
                blueRecentHitText=str(getattr(b, "_blue_recent_hit_text", "") or ""),
                redRecentHitText=str(getattr(b, "_red_recent_hit_text", "") or ""),
                bluePunishmentMid=float(getattr(b, "_blue_punishment_mid", 0.0) or 0.0),
                redPunishmentMid=float(getattr(b, "_red_punishment_mid", 0.0) or 0.0),
                bluePunishmentLong=float(getattr(b, "_blue_punishment_long", 0.0) or 0.0),
                redPunishmentLong=float(getattr(b, "_red_punishment_long", 0.0) or 0.0),
                blueHpRatio=float(blue_hp),
                redHpRatio=float(red_hp),
                blueHpGhostRatio=float(blue_ghost),
                redHpGhostRatio=float(red_ghost),
                showRound=bool(getattr(b, "_overlay_show_round", True)),
                showTime=bool(getattr(b, "_overlay_show_time", True)),
                showBlueImage=bool(getattr(b, "_overlay_show_blue_img", True)),
                showBlueName=bool(getattr(b, "_overlay_show_blue_name", True)),
                showRedImage=bool(getattr(b, "_overlay_show_red_img", True)),
                showRedName=bool(getattr(b, "_overlay_show_red_name", True)),
                showArenaName=bool(getattr(b, "_overlay_show_arena_name", True)),
                showFlags=bool(getattr(b, "_overlay_show_flags", True)),
                showCinematic=bool(getattr(self.cfg, "overlay_show_cinematic", True)),
                vsBgOpacity=float(max(0.0, min(1.0, float(getattr(b, "_overlay_vs_bg_opacity", 1.0) or 1.0)))),
                overlayVsHoldMs=int(max(500, float(getattr(b, "_overlay_vs_hold_sec", 2.85) or 2.85) * 1000)),
                overlayUiScale=float(getattr(b, "_overlay_ui_scale", 1.0) or 1.0),
                browserOverlayScale=float(getattr(self.cfg, "browser_overlay_scale", 1.0) or 1.0),
                overlayTopPad=40,
                overlayTimerFontSize=int(getattr(self.cfg, "overlay_timer_font_size", 54) or 54),
                overlayTimerX=int(getattr(self.cfg, "overlay_timer_x", 0) or 0),
                overlayTimerY=int(getattr(self.cfg, "overlay_timer_y", 0) or 0),
                overlayRoundFontSize=int(getattr(self.cfg, "overlay_round_font_size", 11) or 11),
                overlayRoundX=int(getattr(self.cfg, "overlay_round_x", 0) or 0),
                overlayRoundY=int(getattr(self.cfg, "overlay_round_y", 0) or 0),
                spectatorRecentTextSize=int(getattr(b, "_spectator_recent_text_size", getattr(self.cfg, "spectator_recent_text_size", 23)) or 23),
                browserTextStyles=_normalize_browser_text_styles(getattr(self.cfg, "browser_text_styles", {}) or {}),
                blueImageRev=int(getattr(b, "_blue_image_rev", 0) or 0),
                redImageRev=int(getattr(b, "_red_image_rev", 0) or 0),
                blueHasImage=bool(self.browser_overlay.image_path("blue")),
                redHasImage=bool(self.browser_overlay.image_path("red")),
            )
            if payload != self._last_payload:
                self._last_payload = dict(payload)
                self.browser_overlay.update(**payload)
        except Exception:
            pass

