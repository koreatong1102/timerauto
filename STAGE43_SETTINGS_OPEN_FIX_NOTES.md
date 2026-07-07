# Stage43 Settings Open Hotfix

## Problem
QML called `backend.open_settings()` from `timer_ui.qml`, but `TimerBackend.open_settings` was a plain Python method, not exported as a Qt slot. In QML this appeared as:

```txt
TypeError: Property 'open_settings' of object TimerBackend(...) is not a function
```

## Fix
- Added `@pyqtSlot()` to `TimerBackend.open_settings`.
- Added `TimerBackend.openSettings()` camelCase alias for future QML calls.

## Validation
- `python -m py_compile timerauto.py browser_overlay.py spectator_log_watcher.py config_model.py` passed.
