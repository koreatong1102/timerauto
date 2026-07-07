Stage38 portrait/hit-fx rework

What changed
- Portrait flash layer now sits exactly on top of the portrait image instead of showing as a separate side circle.
- Added configurable hit-fx pop speed setting: spectator_hit_effect_pop_ms.
- Browser overlay now separates pop time from fade time for a sharper "팍" burst.
- Replaced the embedded hit-fx sprite atlas with a higher-detail 12-frame fiery burst.
- Kept existing show/hide damage text option and existing color controls.

New setting
- 설정명: 팍 터지는 시간
- config key: spectator_hit_effect_pop_ms
- range: 30~280 ms
- lower = more instant burst

Files touched
- browser_overlay.py
- timerauto.py
- config_model.py
- hit_fx_sprite_atlas.png
