# Menu log toggle / opacity hotfix

## Fixed

- Top overlay/menu SpectatorLog toggle no longer stops the watcher synchronously on the UI thread.
- When log detection is running and the user clicks the log button again, the UI immediately flips to stopped and the watcher shutdown runs on a background thread.
- A transition guard prevents rapid double-clicks from starting/stopping the watcher while Windows file-watch cleanup is still finishing.
- The top menu toggle now treats stop as a real runtime off switch and updates the SpectatorLog checkbox/config state, preventing Settings auto-apply from restarting it immediately.
- Browser overlay output-only mode now receives and applies:
  - `overlay_bg_color`
  - `overlay_bg_opacity`
  - `overlay_vs_bg_opacity`
  - `overlay_vs_hold_sec`
- Browser overlay now has `overlayBgColor` / `overlayBgOpacity` in state and applies the background opacity in JavaScript.
- VS background opacity now updates in browser-output mode without requiring QML preview.

## Notes

- The GUI was not executed in this Linux container because PyQt6 runtime is unavailable here, but Python syntax compilation passed.
- On Windows, the key behavior to verify is: click top `로그 감지 켜짐` button while running; the app should not freeze, and the button should switch off immediately.
