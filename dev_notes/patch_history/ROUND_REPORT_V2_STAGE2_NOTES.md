# Round Report V2 Stage 2 Notes

- Added portrait slots to the break-time round report card using the existing `/image/blue` and `/image/red` overlay endpoints.
- Added side badges for ROUND EDGE / DOWN SCORED / TKO MOMENT / BIG HIT state without changing the report payload contract.
- Added stronger visual treatment for round tags and decisive moments:
  - TKO ROUND
  - DOWN ROUND
  - BODY ATTACK
  - HEAD HUNTING
  - STUN / BIGGEST SHOT moments
- Kept spectator commentary, TTS, KO/TKO overlay, and round-report data generation unchanged.
- Verified Python syntax and extracted overlay JavaScript with `node --check`.
