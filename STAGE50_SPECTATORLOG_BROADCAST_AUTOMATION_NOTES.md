# Stage50 SpectatorLog Broadcast Automation Patch

Applied to `rr2_patch.zip` baseline.

## Included

1. Hit FX coordinate priority
   - `damage_events.screen_x/screen_y` is now the first source for impact location.
   - Attacking glove pose is used only when the damage row has no valid screen coordinates.

2. `round_time.txt` elapsed-time correction
   - Fight timer now converts elapsed round time into countdown:
     `seconds_left = round_duration - elapsed`.
   - Break timer no longer treats `round_time.txt` as rest seconds; it uses lobby/config break duration with a local wall-clock countdown.

3. Late result sidecar detection
   - `scores.csv`, `winner.txt`, and `lobby.txt` signatures are tracked independently from `round_state.txt`.
   - Late writes after `Results`/`End` can still trigger overlay and commentary updates.

4. `punches_thrown.txt` fallback round report
   - Round report is created even when `damage_events.txt` has no landed hits.
   - Report now includes thrown, misses, accuracy, and activity values per side.

5. `lobby.txt` overlay
   - Shows occupied slots, ready status, venue, rounds, round duration, and break duration.
   - Hides when `lobby.txt` disappears.

6. Official scorecard overlay
   - Uses `scores.csv` rows.
   - Displays per-round score and totals.

7. Winner announcement overlay
   - Uses `winner.txt` when match result is announced.
   - Supports blue/red/draw.

## Validation

- `python3 -m py_compile spectator_log_watcher.py timerauto.py browser_overlay.py browser_overlay_sync.py config_model.py`
- Extracted browser overlay JavaScript and checked it with `node --check`.
- Ran a small mocked SpectatorLog runtime test for:
  - elapsed fight timer conversion,
  - no-damage punch activity report,
  - late scorecard/winner payloads,
  - lobby payload parsing,
  - hit FX using damage event screen coordinates.
