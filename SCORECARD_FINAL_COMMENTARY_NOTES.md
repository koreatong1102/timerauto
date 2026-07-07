# Scorecard Final Commentary Patch

Applied a post-fight scorecard summary for SpectatorLog commentary.

## Scope
Changed only commentary/scoring logic in `spectator_log_watcher.py`.

## New behavior
- Tracks live `damage_events.txt` rows by current round.
- Uses `receiver_side` correctly: the listed side is the fighter who was hit; the opposite side dealt the damage.
- Computes round scores with the requested rule:
  - Damage leader wins the round by one point, normally 10-9.
  - Knockdowns subtract one point from the downed fighter.
  - Three knockdowns in one round are treated as a TKO/stoppage.
- On `results` / `end`, builds a long final summary with:
  - winner / draw decision
  - estimated score totals
  - round-by-round winners
  - decisive round or knockdown note
  - damage/big-shot context
  - weak-point context when meaningful
  - final gauge/health burden context

## Notes
- If the app was started mid-fight and earlier round events were not observed live, it falls back to scoring the current damage file as one round.
- Official result files, if exposed later, should still be allowed to override this estimated scorecard.
