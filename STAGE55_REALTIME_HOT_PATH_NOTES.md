# Stage55 Realtime Hot Path Patch

## Goal
Reduce the one-beat delay felt in browser overlay hit FX and gauges.

## Changes
- Moved SpectatorLog blackbox polling behind the live overlay update path.
  - Hit FX / gauge updates are emitted first.
  - Blackbox archive work runs afterward so it cannot block the broadcast hot path.
- Added a lightweight realtime watcher pass before the full watcher pass.
  - Reads only `damage_events.txt` and punishment gauge files.
  - Skips lobby, scorecard, reports, TTS, accessibility, camera and other heavy work.
- Added fast punishment gauge emission.
  - Default minimum interval: 75 ms.
  - Uses `spectator_realtime_gauge_min_interval_ms` if present in config.
- Added initial baseline protection.
  - On watcher startup, existing lobby/score/winner/round intro files are remembered but not replayed as fresh overlay events.
- Added safer Qt signal emission during shutdown.
  - Prevents the `wrapped C/C++ object ... has been deleted` shutdown race from crashing logs.
- Added browser overlay beacons.
  - `/beacon` endpoint records browser-side `hitfx_show`, `sse_open`, `sse_error`, `sse_fallback` events.
  - This makes future latency analysis split Python push vs browser render.
- Set `spectatorlog_blackbox_enabled` to `false` in bundled config for normal broadcast testing.

## Important
This does not remove SpectatorLog's own file update delay. If the game writes `damage_events.txt` in 0.5-1.0s batches, the program cannot display hit FX before the row exists. This patch makes the program react faster after the file change is visible.

## Test checklist
1. Keep blackbox OFF for normal broadcast tests.
2. Open browser overlay fresh in OBS/PRISM.
3. Confirm logs show `BROWSER_OVERLAY_BEACON event=sse_open`.
4. Throw hits and check `HITFX_LATENCY_PUSH` and `BROWSER_OVERLAY_BEACON event=hitfx_show`.
5. If `sse_fallback` appears, the browser is using polling and can feel up to ~250 ms slower.
