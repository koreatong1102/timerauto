# Stage37A hit FX test + portrait fix
- Fixed settings hit FX test events: fast path expected snake_case screen_x/screen_y, while the test emitted camelCase screenX/screenY.
- Settings test now also pushes a direct browser impact event at screen center so it works even when SpectatorLog controller path is idle.
- Test hitfx keys are now unique per click, avoiding temporary duplicate suppression.
- Browser portrait() now toggles classes on bluePortraitFx/redPortraitFx layers, not only the portrait image, so flash/ring/slash/spark CSS can actually run.
