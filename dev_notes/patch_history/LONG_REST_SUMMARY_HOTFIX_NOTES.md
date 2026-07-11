# Long Rest-Time Summary Hotfix

Scope intentionally limited to `spectator_log_watcher.py`.

## Changed
- Rest-time round summary is now a longer broadcast-style corner analysis paragraph instead of a single sentence.
- Standard/active mode summaries are built from multiple short sports-broadcast sentences covering:
  - round headline
  - damage / clean-hit flow
  - knockdown/stun/big-hit context
  - weak-point accumulation
  - late-round momentum
  - next-round tactical point
  - corner adjustment point
- Quiet mode remains shorter to respect the mode.
- Existing TTS follow-up mechanism is reused; no overlay, settings UI, browser design, image, or hotkey logic was changed.

## Notes
- The long summary is sent as one TTS paragraph so it plays continuously during the break.
- It avoids repeating player names every sentence; names are still mainly reserved for major caster events.
