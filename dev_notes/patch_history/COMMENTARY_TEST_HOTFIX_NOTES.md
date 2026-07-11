# Commentary / Test Tab Hotfix

## What was fixed

- Settings test-tab HUD buttons now route test events through `controller.ui_update`, the same path used by SpectatorLog.
- Browser-output-only mode no longer misses many test buttons that previously only called QML/TimerWindow methods.
- Stun/KD/TKO, damage, gauge, combo, counter, lives, timer-state, full HUD demo, replay, and clear buttons now emit browser overlay state/events where applicable.
- VS overlay test now emits a browser `vs_intro_event` and syncs test/player assets where possible.
- Commentary/Caster TTS test errors now show the actual failure message instead of only a generic settings warning.

## Why it broke

The optimized build defaults to browser-output-only mode. Some Settings test buttons still called only QML overlay methods, so OBS browser overlay could receive no state/event update.

## Verification performed

- `python -m py_compile` passed for all major Python files.
- Static patch check confirmed the test-tab functions now emit `ui_update` payloads for browser overlay.

## Still requires local testing

- Windows exe build
- PyQt GUI click test
- OBS browser overlay visual test
- Edge TTS availability test
