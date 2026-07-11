# Best Commentary Patch

Scope: commentary/caster logic only.

Changed files:
- spectator_log_watcher.py
- timerauto.py

What changed:
- Added phrase/category repetition control.
- Added meaning-group cooldowns so the system goes silent instead of repeating the same kind of line.
- Expanded counter/combo/big-hit/pressure phrase pools.
- Added weak-point accumulation commentary for chin/body/temple/face damage.
- Upgraded break-time round summary with weak-point, late-round, and corner-analysis style lines.
- Kept name-calling policy: player names are used mainly for major caster events such as stun/down/TKO.
- Added caster priority over analyst TTS. Analyst skips while caster is speaking; caster may interrupt analyst.
- Expanded TTS prewarm phrase pool for caster/analyst lines.
- Attempts to prewarm current SpectatorLog player-name caster lines when names are available.

Not changed:
- Settings UI structure.
- Browser overlay layout/design.
- OBS server structure.
- Player image/profile logic.
- Browser round fullscreen overlay removal from the previous patch is preserved.
