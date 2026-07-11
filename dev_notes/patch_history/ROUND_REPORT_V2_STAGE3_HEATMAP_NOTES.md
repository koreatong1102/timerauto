# ROUND REPORT V2 STAGE 3 - BODY HEATMAP

- Added a compact TARGET MAP block to both BLUE and RED round report cards.
- Uses existing `weakReceivedTop` report payload; no new spectator log parsing is required.
- Maps weak point labels to stable broadcast spots:
  - 코 / Nose
  - 턱 / Chin
  - 관자놀이 / Temple
  - 명치 / SolarPlexus
  - 복부 / Liver
- Spot size/glow scales by count and accumulated damage.
- Empty state shows `약점 피격 없음` when no weak point hits were recorded.
- Added a round-report CSS guard so legacy HUD `.blue`/`.red` positioning does not offset nested report elements.

Validation:
- Python py_compile passed for all top-level .py files.
- Extracted browser overlay JavaScript passed `node --check`.
