"""Offline reproduction of archived central verdicts. No OBS, keys or file writes."""
from __future__ import annotations

import json
from collections import defaultdict
from types import SimpleNamespace


def replay_match_rows(rows, settings):
    from event_engine import FightEventEngine
    from spectator_log_watcher import SpectatorLogWatcher

    cfg = SimpleNamespace(**dict(settings or {}))
    watcher = SpectatorLogWatcher(cfg)  # Constructor only; never start its worker.
    version = watcher._event_ruleset_version()
    grouped = defaultdict(lambda: {"damage": [], "throw": []})
    for row in rows:
        if row.get("kind") in ("damage", "throw"):
            grouped[int(row["round_no"])][row["kind"]].append(row)
    result = {"status": "replayed", "ruleset": version, "rounds": {}, "compared": 0,
              "different": 0, "different_ruleset_or_unclassified": 0, "differences": []}
    for round_no in sorted(grouped):
        values = grouped[round_no]
        ordered = sorted(values["damage"], key=lambda row: row["sequence_no"])
        events = [json.loads(row["raw_json"]) for row in ordered]
        throws = [json.loads(row["raw_json"]) for row in sorted(values["throw"], key=lambda row: row["sequence_no"])]
        for event in events:
            event["is_counter"] = float(event.get("counter_mult", 1) or 1) > 1.0001
            event["effect_kind"] = watcher._damage_effect_kind(str(event.get("damage_type") or ""))
        watcher._annotate_counter_events(events)
        watcher._annotate_whiff_counters_from_throws(events, throws, events)
        verdicts = FightEventEngine(cfg).classify_many(events)
        facts = {side: {"landed_rows": 0, "counters": 0, "max_combo_hits": 0, "max_combo_damage": 0.0} for side in ("blue", "red")}
        for row, event, verdict in zip(ordered, events, verdicts):
            side = event.get("attacker_side")
            if side in facts:
                item = facts[side]
                item["landed_rows"] += 1
                item["counters"] += int(bool(verdict.get("counter")))
                item["max_combo_hits"] = max(item["max_combo_hits"], int(verdict.get("combo_hits") or 0))
                item["max_combo_damage"] = max(item["max_combo_damage"], float(verdict.get("combo_damage") or 0))
            stored = json.loads(row.get("classified_json") or "null")
            if row.get("ruleset_version") != version or not isinstance(stored, dict):
                result["different_ruleset_or_unclassified"] += 1
                continue  # A configuration/version change is NOT evidence of a bug.
            result["compared"] += 1
            keys = ("counter", "combo_hits", "combo_damage", "primary", "tags")
            old = {key: stored.get(key) for key in keys}
            new = {key: verdict.get(key) for key in keys}
            if old != new:
                result["different"] += 1
                if len(result["differences"]) < 20:
                    result["differences"].append({"event_id": row["event_id"], "stored": old, "replayed": new})
        result["rounds"][str(round_no)] = facts
    watcher._match_archive.close()
    return result


def replay_diagnostic_zip(zf):
    settings = json.loads(zf.read("settings_snapshot.json"))
    results = []
    for name in sorted(zf.namelist()):
        if name.endswith("/ledger_events.jsonl"):
            if zf.getinfo(name).file_size > 16 * 1024 * 1024:
                results.append({"entry": name, "status": "omitted_size"})
                continue
            try:
                rows = [json.loads(line) for line in zf.read(name).decode("utf-8").splitlines() if line.strip()]
                results.append({"entry": name, **replay_match_rows(rows, settings)})
            except Exception as exc:
                results.append({"entry": name, "status": "failed", "error": str(exc)})
    return {"matches": results, "note": "저장된 원장과 현재 코드/수집 설정으로 재현한 판정을 비교합니다. 공식 점수·승자·피해·다운을 대체하지 않으며 실제 방송/OBS를 조작하지 않습니다. 모든 판정 오류의 자동 탐지는 아닙니다."}
