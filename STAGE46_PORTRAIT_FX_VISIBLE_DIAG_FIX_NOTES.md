# Stage46 Portrait FX Visible + Diagnostic Cleanup

- Re-enabled `portraitFxLayer` as a local flash/slash/spark layer aligned to the real portrait image.
- Kept `portraitFlashImg` clone disabled, so no small duplicate portrait can appear behind the real portrait.
- `portrait()` now reconnects `bluePortraitFx` / `redPortraitFx` and restarts their child animations.
- Added JS alignment helper so the FX layer uses the computed size/position of the actual portrait image.
- QML local preview spectator hit/stun handlers no longer silently drop test effects when `qml_effects_enabled` is false.
- Diagnostic app_state now stores a compact diagnostics summary instead of embedding the full event list, reducing `<max_depth>` noise in clipboard output.

Validation:
- `python -m py_compile timerauto.py browser_overlay.py diagnostics.py config_model.py spectator_log_watcher.py ai_project_snapshot.py`
- Extracted browser overlay script and ran `node --check`.
