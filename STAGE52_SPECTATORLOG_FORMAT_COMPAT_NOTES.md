# Stage52 SpectatorLog Format Compatibility Patch

This patch updates the RFC overlay tool for the SpectatorLog changes captured by the Stage51 blackbox recorder.

## Fixed / Added

- `damage_events.txt` parser now supports all observed layouts:
  - old 11-column rows without hand
  - 12-column rows with hand
  - new 13-column rows with `counter_mult` inserted after `final_damage`
- `counter_mult` is preserved as `counter_mult` / `counterMult` metadata.
- Counter hits are counted in round reports and can show `COUNTER 1.12x` on screen impact text.
- `round_time.txt` is now interpreted with an automatic mode:
  - observed countdown streams are used directly as remaining seconds
  - increasing streams are treated as elapsed and converted to countdown
  - auto mode resets on MatchIntro / force refresh
- `scores.csv` parser now supports the expanded 9-column format:
  - `round,blue_score,red_score,blue_total,red_total,blue_damage_taken,red_damage_taken,blue_kds,red_kds`
- Current-round placeholder rows are hidden from live scorecard overlays during RoundFight/RoundBreak/RoundIntro.
- `accessibility.txt` is parsed for enabled assist state and `allowSlaps` condition flags.
- SpectatorLog blackbox recorder now avoids duplicate raw snapshots when a file mtime changes but its bytes are identical.

## Raw archive rule preserved

Blackbox raw snapshot files remain byte-exact copies. Metadata and hashes are stored only in `events.jsonl`.
