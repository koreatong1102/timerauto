# Match Event Architecture

## Source-of-truth order

1. `winner.txt`: official winner and result.
2. `scores.csv`: official score, damage and knockdowns.
3. `damage_events.txt` / `punches_thrown.txt`: immutable punch facts and timing.
4. Central event engine: derived counter, combo, heavy, signature and weak-point verdicts.
5. Archived vitals: broadcast game-health and actual-health snapshots.

Derived event logic must never overwrite the official result or official score data.

## Runtime path

```text
rolling SpectatorLog
  -> parser and stable event identity
  -> match_archive.db transaction (WAL)
  -> central FightEventEngine verdict
  -> browser overlay / commentary / OBS highlights / POTM
  -> round report / final report / fight style
```

`damage_events.jsonl` and `punches_thrown.jsonl` remain recovery mirrors for
older releases and manual inspection. SQLite is the primary durable ledger.

## Counter contract

A hit is a broadcast counter when it deals at least 25 damage and either:

- the game log declares it through `counter_mult`, or
- the opponent completely misses and the fighter lands 25+ damage within the
  configured window, or
- the opponent lands at/below the configured graze damage and the fighter
  answers within the configured window at/above the configured response
  damage.

The original game mark is retained as `official_counter` for audit even when
its damage is below 25; it is not promoted to the broadcast HUD/report
counter. Default broadcast values are 0.7 seconds, 15 damage and 30 damage,
with a hard 25-damage floor for every broadcast counter.

## Versioning and recovery

`FightEventEngine.ruleset_version()` hashes every shared classification
threshold. Reports rebuild old derived verdicts when this value changes.
Raw events stay unchanged. Restarting TimerAuto resumes the unfinished
player-pair archive and replays the latest round into the central engine so its
counter/combo context continues.

Every report read reconciles the primary ledger against its JSONL mirror.
Official score/winner snapshots and integrity results are recorded in the
ledger audit table.
