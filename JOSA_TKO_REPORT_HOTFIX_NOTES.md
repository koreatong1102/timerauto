# Josa / TKO Round Report Hotfix

Applied fixes:
- Added Korean josa helper for natural TTS phrases (`은/는`, `이/가`, `을/를`, `와/과`, `으로/로`).
- Updated round-break commentary and final-summary lines that previously produced awkward phrases like `다니엘는` or `본즈가` when the wrong particle was hardcoded.
- Changed round-report leader priority to: TKO/stoppage > knockdown > total damage > landed count > stun/big hit.
- Added TKO counters to round-report payload (`tkos`) and surfaced `TKO 포함` in the browser report footer.
- Made TKO a first-class round-break summary event so TKO rounds do not get described as normal close/damage rounds.
- Cleaned visible mojibake/broken Korean status strings in `actions.py` and `timerauto.py`; cleaned broken comments in `browser_overlay.py` and `config_model.py`.

Validation performed:
- `python3 -m py_compile` for all top-level Python files.
- Extracted browser overlay JavaScript and checked it with `node --check`.
- Smoke-tested report generation with dummy SpectatorLog data for both TKO-overrides-damage and knockdown-overrides-damage cases.
