# STAGE19 REALTIME LATENCY HOTFIX

- Player/name/portrait payload is emitted only at new MatchIntro or player pair change.
- SpectatorLog portrait.png is read only at bout start/player change; same filename rewrites during the bout no longer cause reload churn.
- Browser overlay image writes are hash-cached and atomic; same image no longer bumps ImageRev.
- Hot-path side info reads only punishment files; cosmetics/head/glove/accessibility debug reads were removed from realtime path.
- Pure duplicate state churn from round_time/camera rewrites is suppressed while damage/hit/down/tko events remain immediate.
- SPECTATORLOG_APPLY logging is reduced for light state updates.
