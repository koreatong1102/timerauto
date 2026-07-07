# Stage56 - Round Report / KD Flow / Portrait FX / Counter Source Patch

## What changed

- Embedded the official scorecard into the round report card instead of showing it as a separate scorecard overlay.
- Reworked the round report wording toward Korean broadcast text.
- Round report names now prefer registered profile nicknames over raw SpectatorLog game IDs.
- Counter detection is now based only on `damage_events.counter_mult > 1.00`.
  - Removed the old heuristic that guessed counters from back-and-forth timing.
  - Counter commentary, combo text, reports, and hit metadata now share this single source of truth.
- Added RoundKnockdown count-state handling so the KD count from `round_time.txt` does not overwrite the normal match clock.
- Removed portrait HP-drop fallback shaking that could retrigger repeatedly while the gauge was updating.
- Disabled extra portrait FX light layers again and made normal hit portrait movement a short gauge-like shake, without the old bright flash.
- Kept heavier portrait response for heavy/stun/KO, but shortened and toned down the brightness.
- Kept blackbox default OFF and removed generated logs from the release ZIP.

## Notes

- General hits still shake the portrait briefly, but they should no longer create a separate flash layer or stay shaking through stacked HP/gauge changes.
- Official scorecard rows appear inside the round report when `scores.csv` is available.
- Standalone scorecard side-card events are suppressed by the watcher.
