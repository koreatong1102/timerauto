# Round Report TTS Link Notes

- Based on the round report broadcast-card version.
- Minimal scope: changed `spectator_log_watcher.py` only.
- Rest-time TTS summary now reuses the same `damage_events.txt` round statistics used by the visual ROUND REPORT card.
- Added report-aware summary lines for:
  - landed hit count,
  - total dealt damage,
  - leader's top landed punch type,
  - opponent's most meaningful weak-point damage.
- No changes to SettingsDialog, build_release.ps1, QML UI, VS trigger, portrait policy, or log start/stop behavior.

Accuracy notes:
- `damage_events.txt` rows are landed hits, not all thrown punches.
- The `corner` column is the receiver, so the attacker is the opposite side.
- TTS wording says "적중" and "데미지" rather than claiming thrown-punch counts.
