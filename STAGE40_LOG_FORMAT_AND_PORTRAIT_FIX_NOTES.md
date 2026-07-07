Stage40 fixes

Portrait FX
- Removed the visible old portraitFxLayer path by forcing it off again.
- Added runtime portraitFlashImage() which clones the actual portrait image and flashes that clone.
- This avoids the old circular/rectangular div flash appearing next to the visible fighter when the PNG has transparent padding.
- Original portrait still shakes/brightens; the clone provides the white/hot flash on the same silhouette.

SpectatorLog2 format
- damage_events.txt parser now supports the new hand column:
  round_time, final_damage, corner, hand, screen_x, screen_y, world_x, world_y, world_z, punch_type, damage_type, weak_point
- Old damage_events rows without hand remain supported.
- hitfx and glove picking now use the logged hand first, before distance fallback.
- round_total.txt is read when timer sync is enabled.

New logs
- punches_thrown.txt is read for round report thrown-punch breakdown.
- scores.csv is read as official round scoring for final scorecard summary.
- winner.txt is read when available to lock the final winner/draw.

Validated
- python -m py_compile spectator_log_watcher.py browser_overlay.py timerauto.py config_model.py
- node --check extracted overlay JavaScript
