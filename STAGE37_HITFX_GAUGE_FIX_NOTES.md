# Stage37 hit FX/gauge hotfix
- Test hit FX now uses screen center (0.5, 0.5).
- Replaced the previous rough sprite atlas with a cleaner custom burst atlas.
- Default ring overlay is off so the sprite is not covered by a circular HUD ring.
- Added browser-side optimistic HP draw on impact events so gauge reacts immediately before the next full state sync.
- Shortened and tightened portrait/bar shake timings with crisp punch-style motion.
- Results/end state forces timer to 0:00.
