# Break Budget Summary Hotfix

## Purpose
Rest-time round summaries now try to finish before the break ends.

## Changes
- Added a conservative Korean TTS duration estimator.
- Added a break-time budget for round recap lines.
- Round summaries now select only the highest-priority lines that fit the available break time.
- If the next round starts while an analyst recap is still playing, the analyst TTS is stopped.
- Pending analyst follow-up TTS retries are cancelled when the next round starts.

## Policy
- Keep a safety buffer before the next round.
- Keep the caster round-start line from being covered by old round analysis.
- Prefer shorter useful summaries over long summaries that bleed into the next round.
