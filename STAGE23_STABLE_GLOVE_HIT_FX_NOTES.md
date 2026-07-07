# STAGE23 STABLE GLOVE HIT FX

- Rebased the screen hit FX work on the known-working stage19 realtime latency hotfix path.
- Added glove-position based hit impact events only when a new damage_event appears.
- Browser overlay JS was simplified and parser-checked with Node to avoid the stage22 blank/default overlay issue.
- Recent side hit text stays hidden; combo/counter and KO/TKO overlays remain intact.
- Impact FX is a lightweight translucent pulse/ring, not a star/spark burst.
- Active impact nodes are capped and short-lived to reduce browser/OBS lag.
