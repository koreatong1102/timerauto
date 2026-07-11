# Stage57 Report / Commentary / Result Hotfix

## Fixed

- Restored both-side round report layout. The report cards use `.blue` / `.red` classes, which were being affected by old global HUD CSS. The report now force-scopes side cards so both fighters render.
- Removed separate match lobby / winner / scorecard broadcast cards. Lobby is still parsed and retained as data, but the overlay no longer displays a match lobby card.
- Official scorecard and winner/result are folded into the integrated round/match report.
- Match report now appears on `Results`, `End`, `RoundKnockout`, and `RoundDisqualified` flows.
- Fixed the realtime hot path consuming damage rows before full commentary/report logic could see them. Fast hit FX now hands off the same new damage events to the full watcher pass so knockdown/stun/TKO/counter TTS and score/report logic are not skipped.
- `RoundKnockout` and `RoundDisqualified` are normalized and handled as final-result states.
- Current-round 10-10 / zero-damage placeholder score rows are filtered during knockout/disqualification before winner/final scores arrive.

## Kept

- Counter source of truth remains `damage_events.counter_mult > 1.00` only.
- Blackbox remains opt-in and off by default.
- Raw logs are still not modified by archive metadata.
