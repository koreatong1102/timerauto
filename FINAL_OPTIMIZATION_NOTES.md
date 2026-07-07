# TimerAuto final optimization source build

This package is the final source/build package prepared in this environment. It is not a precompiled Windows exe.
Build the executable on Windows with `build_release.ps1` or via the included GitHub Actions workflow.

## Final changes in this build

- Kept the previous major-surgery split:
  - `app_paths.py`
  - `config_model.py`
  - `runtime_support.py`
  - `update_manager.py`
  - `browser_overlay_sync.py`
- Reduced startup work:
  - `pyautogui` is no longer imported during main app startup.
  - `edge_tts` is no longer imported during action runner startup.
  - Both are imported lazily only when keyboard/mouse/TTS actions are actually used.
- Reduced browser-overlay background work:
  - Browser-output-only periodic asset sync is throttled to 0.5 seconds instead of running heavy file/player matching every poll tick.
  - Repeated browser asset path updates are skipped when paths did not change.
  - Full browser overlay payloads are cached so unchanged payloads do not call `BrowserOverlayServer.update()` again.
- Kept build/package cleanup:
  - user config/profile excluded by default,
  - `image/players` excluded by default,
  - OCR/Torch packaging can be skipped with `-NoOcr`,
  - logs/caches/scratch files removed from shared source zips and build outputs.

## Build examples

Clean normal build:

```powershell
.\build_release.ps1 -Version 1.0.0
```

Lighter build without OCR/Torch:

```powershell
.\build_release.ps1 -Version 1.0.0 -NoOcr
```

Private/RFC pack with local config and player portraits:

```powershell
.\build_release.ps1 -Version 1.0.0 -IncludeUserConfig -IncludePlayerImages
```

## Validation performed here

This environment cannot launch the PyQt Windows GUI or build the Windows exe. The following checks passed:

```text
python -m py_compile timerauto.py browser_overlay.py browser_overlay_sync.py app_paths.py config_model.py runtime_support.py update_manager.py screen_capture.py screen_watcher.py spectator_log_watcher.py player_utils.py actions.py hotkey_engine.py
AppConfig.from_json(config.json) smoke test
BrowserOverlaySync smoke test with a fake backend/server
```

## Remaining real-world checks

Run these on Windows before publishing to users:

1. Build with `build_release.ps1`.
2. Launch `dist\timerauto\timerauto.exe`.
3. Open settings and save once.
4. Open OBS browser URL: `http://127.0.0.1:17872/overlay`.
5. Confirm SpectatorLog sync, VS intro, hit/stun/KO/TKO effects, images, flags, TTS, and hotkeys.
6. If OCR is required, build without `-NoOcr` and test OCR buttons.

## Hotfix: settings dialog visibility/open failure

- Re-imported `_merge_dict` and `_normalize_hex_color` from `config_model.py`; the settings dialog still uses these helpers in overlay/effect settings.
- Wrapped `MainApp.open_settings()` dialog construction with exception logging and an error dialog, so future settings-open failures are visible instead of silently failing from a Qt slot.
- Temporarily disables the QML overlay always-on-top flag while the settings dialog is open, then restores it when the dialog closes. This prevents the overlay from covering the settings window.
