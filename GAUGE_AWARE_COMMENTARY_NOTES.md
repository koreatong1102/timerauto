# Gauge-aware commentary hotfix

Scope kept narrow:
- `spectator_log_watcher.py` only.
- No UI, browser design, settings, image, hotkey, or overlay layout changes.

What changed:
- Commentary now reads `punishment_mid.txt` and `punishment_long_weighted.txt` before judging health-pressure lines.
- Lines such as `체력 부담이 커지고 있습니다`, `위험 구간에 들어갑니다`, and `회복할 시간이 필요합니다` are now gated by actual punishment/HP-bar state, not raw damage events alone.
- Damage-event pressure lines still exist, but health-specific wording is only used when the gauge/punishment data confirms it.
- Rest-time long round summaries now include one gauge-context line when useful: stable, pressure, danger, or late gauge-loss context.
- Match-end summary can mention gauge burden in close fights when the gauge state is meaningful.

Interpretation:
- `damage_events.txt` = what hit, damage amount, weak point, stun/knockdown type.
- punishment/gauge files = current burden, remaining HP-bar state, and whether health-risk wording is justified.
