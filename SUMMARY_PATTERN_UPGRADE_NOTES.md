# Summary Pattern Upgrade Notes

Scope: commentary summary logic only.

Changed:
- Rest-time round recap now selects a broadcast pattern by situation:
  - event pattern: knockdown/stun rounds
  - close pattern: close damage rounds
  - dominant pattern: clear damage/gauge edge
  - flow pattern: ordinary flow rounds
- Rest-time summary still uses damage events, gauge/punishment snapshot, weak-point accumulation, late-round damage, and next-round points.
- Post-fight summary now selects a pattern by result:
  - stoppage
  - close decision / draw
  - clear decision
  - normal decision
- Scorecard final summary still follows the project rule: damage leader wins the round by one point, knockdowns deduct one point, three knockdowns in a round ends the fight.
- Added logs:
  - SPECTATORLOG_ROUND_SUMMARY_PATTERN
  - SPECTATORLOG_SCORECARD_FINAL ... pattern=...

Not changed:
- Browser overlay visuals.
- Settings UI.
- Image handling.
- TTS role policy.
- Damage/gauge live commentary rules.
