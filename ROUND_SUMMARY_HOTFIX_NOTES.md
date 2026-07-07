# ROUND SUMMARY HOTFIX

## What changed

- Rest-time round summaries no longer depend on `round.txt` being present during break state.
- If break/rest state arrives without a round number, the watcher uses the last known fight round.
- Break caster line and round summary can now fire on `fight -> break` even when round number is missing/cleared.
- Round summary follow-up TTS now retries while caster TTS is still busy instead of being skipped once.
- Added `SPECTATORLOG_ROUND_SUMMARY` log line when a summary is generated.

## Files changed

- spectator_log_watcher.py
- timerauto.py
