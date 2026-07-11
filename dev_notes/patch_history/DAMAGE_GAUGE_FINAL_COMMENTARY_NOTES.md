# Damage + Gauge Final Commentary Patch

- Real-time commentary now separates: event impact (damage_events), actual danger (punishment/HP gauge), and recent pressure flow.
- Health/위험/체력 부담 lines are gated by punishment_mid / punishment_long_weighted / calculated hp_ratio, not raw hit damage alone.
- Gauge-danger lines outrank weak-point/pressure/big-hit analysis when the actual gauge is in a dangerous state.
- Big-hit wording is punch-aware: jabs are described as timing/앞손/거리 싸움, not awkward power-shot phrasing like “큰 잽”.
- Generic pressure lines no longer overclaim health loss when the gauge does not confirm it.
- Long rest summaries and match-end summaries retain gauge context and weak-point context.
- No UI/layout/browser design changes were made in this patch.
