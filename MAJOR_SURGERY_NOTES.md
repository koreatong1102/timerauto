# TimerAuto major-surgery source build

This package is a structural refactor build, not a newly compiled Windows exe.
Build the executable on Windows with `build_release.ps1` or through GitHub Actions.

## What changed

- Split path helpers out of `timerauto.py` into `app_paths.py`.
- Split config dataclasses/defaults/normalizers out of `timerauto.py` into `config_model.py`.
- Split runtime startup logging/config-path helpers into `runtime_support.py`.
- Split self-update helper functions into `update_manager.py`.
- Split OBS browser overlay state publishing into `browser_overlay_sync.py`.
- Kept previous safe build optimizations:
  - clean build excludes user config/profile by default,
  - clean build excludes `image/players` by default,
  - `-NoOcr` build option can skip EasyOCR/Torch/TorchVision collection,
  - runtime log pruning keeps recent TimerAuto logs only.

## Build examples

Clean normal build:

```powershell
.\build_release.ps1 -Version 1.0.0
```

Lighter build without OCR/Torch:

```powershell
.\build_release.ps1 -Version 1.0.0 -NoOcr
```

RFC/private pack with local config and player images:

```powershell
.\build_release.ps1 -Version 1.0.0 -IncludeUserConfig -IncludePlayerImages
```

## Validation performed here

The available environment cannot run the PyQt GUI or build a Windows exe. The following checks passed:

```text
python -m py_compile timerauto.py browser_overlay.py browser_overlay_sync.py app_paths.py config_model.py runtime_support.py update_manager.py screen_capture.py screen_watcher.py spectator_log_watcher.py player_utils.py actions.py hotkey_engine.py
AppConfig.from_json(config.json) round-trip save test
```

## Risk note

This is a larger structural refactor than the safe build cleanup. If something breaks, check imports around the new modules first:

- `app_paths.py`
- `config_model.py`
- `runtime_support.py`
- `update_manager.py`
- `browser_overlay_sync.py`
