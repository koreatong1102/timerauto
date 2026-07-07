# Stage53 Blackbox Opt-In Clean Patch

- SpectatorLog Blackbox Recorder is now OFF by default.
- Settings UI adds a checkbox for `관전툴 로그 전체 기록(블랙박스)`.
- Added archive mode selector and archive folder opener.
- Existing generated `SpectatorLogArchive`, `logs`, and `diagnostics` contents were removed from this patch package.
- Raw snapshots remain byte-exact when blackbox recording is enabled; metadata stays in `events.jsonl`.
