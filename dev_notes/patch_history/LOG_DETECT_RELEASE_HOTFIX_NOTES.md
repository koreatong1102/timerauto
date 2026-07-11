# LOG DETECT RELEASE HOTFIX

- Fixed first-run release builds where `build_release.ps1` does not include the developer config, leaving `spectatorlog_enabled` false.
- `Start Log Detection` now force-enables SpectatorLog instead of silently doing nothing when the setting is off.
- Settings close now starts SpectatorLog independently from screen/OCR detection.
- Public release build now writes a tiny sanitized `config.json` with SpectatorLog enabled and empty path for auto-discovery.
- Frozen app config path now falls back to `%APPDATA%\TimerAuto\config.json` when the exe folder is not writable.
- Default config enables SpectatorLog, timer/player sync, and commentary for first-run usability.
- If a bundled config exists beside the exe but that folder is not writable (installer/Program Files case), it is copied to `%APPDATA%\TimerAuto\config.json` and the per-user writable config is used.
