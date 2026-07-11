# PLAYER UI SYNC HOTFIX

- Fixed program UI player name/id/portrait staying stale when `browser_overlay_output_only` is enabled.
- Player IDs, display names, flags, streak metadata, and portraits are now applied to the QML program UI regardless of browser-output mode.
- Browser overlay still receives the same updates.
- When a fresh player ID/name arrives without an explicit `*_player_img` payload, the app now reloads a fallback portrait from registered player images or SpectatorLog `blue/red/portrait.png`.
- Browser image cache no longer keeps the old side image when a fresh player ID/name update arrives.
