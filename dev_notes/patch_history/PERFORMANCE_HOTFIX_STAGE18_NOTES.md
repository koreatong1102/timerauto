# PERFORMANCE HOTFIX STAGE18

- Avoid rescanning damage_events.txt on every round_time/head/glove file update.
- Limit round report allHits payload to last 64 received hits per side.
- Trim BrowserOverlay event payloads sent to OBS/browser clients; heavy round_report events expire after 8 seconds instead of being resent forever.
- Reduce Edge TTS prewarm jobs from 80 to 16 to avoid startup/runtime stalls.
- Drop stale non-urgent commentary TTS if Edge generation takes too long, so old hit commentary does not play several seconds late.
