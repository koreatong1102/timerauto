# Round Report Broadcast Card Pass

Base: user-approved `10.zip` / first-pass round report.

Scope intentionally kept small:
- `damage_events.txt` based round report payload is still the source of truth.
- No SettingsDialog, build_release, VS trigger, portrait policy, QML UI, or TTS logic changes.

Changes:
- Added a compact `summaryLine` and `displayMs` to the round-report payload.
- Added `spectator_round_report_hide` on break -> fight transition.
- Browser overlay now handles `round_report_hide` and hides the report on next round/VS/down/KO events.
- Report card labels changed to broadcast-friendly Korean labels.
- Leader side gets a subtle highlight.
- Card hold time is bounded to 5-30 seconds, default 22 seconds.

Data correctness reminder:
- `corner` in `damage_events.txt` means the boxer who received the hit.
- Attacker stats are calculated by inverting that side.
