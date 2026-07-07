# Round Report v2 Stage 4 - No-log test button

Added a settings test-tab button for showing the Round Report v2 card without SpectatorLog files.

## Added
- `라운드 리포트 테스트` button in SpectatorLog / HUD test group.
- Synthetic round report payload with:
  - roundTag
  - bestShot
  - decisiveMoment
  - punchTop
  - weakReceivedTop heatmap data
  - knockdown scenario
- Uses current in-app player names when available, otherwise falls back to BLUE TEST / RED TEST.
- Sends payload through the same `spectator_round_report` UI update path used by real SpectatorLog round breaks.

## Not changed
- Real SpectatorLog parsing
- TTS commentary/caster logic
- KO/TKO/KD cinematic overlay
- Browser overlay layout/CSS/JS
