# TTS Role Policy Hotfix

- Changed commentary TTS playback policy so caster and analyst do not block or stop each other.
- Same-role overlap is still prevented:
  - caster while caster is busy: skipped/retried depending on caller path.
  - analyst while analyst is busy: skipped/retried depending on caller path.
- Follow-up analyst summaries are no longer skipped just because caster is speaking.
- Caster event calls no longer stop the analyst player.
- No commentary conditions, browser overlay design, image handling, settings UI, or log parsing behavior was intentionally changed.
