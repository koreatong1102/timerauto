# Stage44 Portrait No-Clone FX Hotfix

## Problem
Stage40/43 tried to flash the portrait using a cloned `<img>` element. In real overlay CSS this still appeared as a smaller portrait behind the main portrait because older `.portraitFlashImg` rules used fixed `74x74 !important` sizing and the real HUD portrait was larger.

## Fix
- Disabled the clone image path entirely.
- `portraitFlashImage()` now only removes any existing `bluePortraitFlashImg` / `redPortraitFlashImg` and returns.
- Added final CSS override that hides `.portraitFlashImg` and `.portraitFxLayer` completely.
- The flash/shake effect now applies only to the real `.portrait` element using stronger Stage44 keyframes.

## Validation
- `python -m py_compile timerauto.py browser_overlay.py spectator_log_watcher.py config_model.py`
- extracted overlay JS and `node --check` passed.
