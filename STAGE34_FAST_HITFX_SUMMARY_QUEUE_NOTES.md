# Stage34 fast hit FX + configurable settings + summary sentence queue

Base: user-provided 정상1.zip stable build.

Changes:
- Kept the original DOM/CSS hit impact visual base.
- Added configurable hit FX controls: duration, base size, damage size scale, ring width, opacity/intensity, glow, center fill, damage text on/off, text scale.
- Browser impact rendering now reuses a small DOM node pool to reduce create/remove churn during rapid hits.
- Browser direct update emits impact events immediately after overlay state update, before round report/fullscreen/heavy events.
- Round break summary TTS is queued as sentence chunks. On round_start, pending analyst followup sentences are cancelled while the currently playing analyst sentence is allowed to finish.
