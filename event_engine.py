"""Shared, data-driven fight event classification.

This module deliberately has no Qt/OBS/browser dependencies.  It converts a
raw spectator damage row into stable broadcast event names once, so the live
HUD, commentary metadata, OBS highlight capture, POTM scoring, and diagnostics
can share the same verdict.  A shadow switch remains for diagnostic comparison
and safe rollback.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List


SPECIAL_KINDS = {"stun", "knockdown", "down", "ko", "tko"}


def counter_opportunity_id(row: dict) -> str:
    """Stable identity for one opponent damage event used as a counter chance."""
    raw = dict(row or {})
    fields = (
        "time", "attacker_side", "receiver_side", "damage", "counter_mult",
        "hand", "punch", "damage_type", "weak_point", "raw_line",
    )
    identity = {key: raw.get(key) for key in fields if key in raw}
    encoded = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "damage:" + hashlib.sha1(encoded.encode("ascii", "ignore")).hexdigest()


class FightEventEngine:
    RULE_SCHEMA_VERSION = 8
    COUNTER_MIN_DAMAGE = 25.0

    def __init__(self, cfg: Any):
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self._combo: Dict[str, Dict[str, Any]] = {
            "blue": {},
            "red": {},
        }
        self._last_attack: Dict[str, Dict[str, Any]] = {
            "blue": {},
            "red": {},
        }
        self._consumed_counter_opportunities = set()
        self._momentum: Dict[str, List[Dict[str, Any]]] = {
            "blue": [],
            "red": [],
        }
        self._weak_targets: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
            "blue": {},
            "red": {},
        }

    @staticmethod
    def _number(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    def ruleset_version(self) -> str:
        values = {
            "schema": self.RULE_SCHEMA_VERSION,
            "counter_window": self._number(getattr(self.cfg, "event_counter_window_sec", 0.7), 0.7),
            "counter_graze_max": self._number(getattr(self.cfg, "event_counter_graze_max_damage", 15.0), 15.0),
            "counter_response_min": self._number(getattr(self.cfg, "event_counter_response_min_damage", 30.0), 30.0),
            "counter_official_min_mult": self._number(
                getattr(self.cfg, "event_counter_official_min_mult", 1.02), 1.02
            ),
            "counter_min_damage": self.COUNTER_MIN_DAMAGE,
            "counter_opportunity_policy": "consume_once",
            # Throw-only whiff inference is applied by the watcher before the
            # row reaches this engine. Keep its causal policy in the shared
            # ruleset identity so archived reports are rebuilt after a change.
            "whiff_clock_direction": "countdown",
            "whiff_log_jitter_sec": 0.10,
            "combo_min": self._number(getattr(self.cfg, "event_combo_min_damage", 15.0), 15.0),
            "combo_window": self._number(getattr(self.cfg, "event_combo_window_sec", 0.8), 0.8),
            "combo_break": self._number(getattr(self.cfg, "event_combo_break_damage", 20.0), 20.0),
            "heavy": self._number(getattr(self.cfg, "event_heavy_damage", 50.0), 50.0),
            "signature": self._number(getattr(self.cfg, "event_signature_damage", 60.0), 60.0),
            "counter_strong": self._number(getattr(self.cfg, "event_counter_min_damage", 40.0), 40.0),
            "combo_emphasis": int(self._number(getattr(self.cfg, "event_combo_emphasis_hits", 5), 5)),
            "answer_window": 1.2,
            "answer_damage": 35.0,
            "momentum_window": 3.0,
            "momentum_hits": 3,
            "momentum_damage": 80.0,
            "target_window": 8.0,
            "target_hits": 3,
            "target_damage": 70.0,
        }
        raw = json.dumps(values, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return f"fight-event-v{self.RULE_SCHEMA_VERSION}-{hashlib.sha1(raw.encode('ascii')).hexdigest()[:12]}"

    def classify_many(self, rows: Iterable[dict]) -> List[dict]:
        # SpectatorLog rows are already appended in real play order.  The game
        # clock normally counts down, so sorting by the numeric clock reverses
        # a batch and breaks otherwise valid combos.
        ordered = [dict(row or {}) for row in rows if isinstance(row, dict)]
        return [self.classify(row) for row in ordered]

    def classify(self, row: dict) -> dict:
        raw = dict(row or {})
        side = str(raw.get("attacker_side") or "").lower().strip()
        receiver = str(raw.get("receiver_side") or "").lower().strip()
        damage = max(0.0, self._number(raw.get("damage")))
        event_time = self._number(raw.get("time"))
        effect_kind = str(raw.get("effect_kind") or "").lower().strip()
        weak_point = str(raw.get("weak_point") or "").lower().strip()
        raw_counter_reason = str(raw.get("counter_reason") or "").lower().strip()
        if raw_counter_reason == "log":
            raw_counter_reason = "official"
        elif raw_counter_reason == "light_trade":
            raw_counter_reason = "graze"
        counter_mult = self._number(raw.get("counter_mult"), 1.0)
        inferred_reasons = {"whiff", "graze"}
        official_counter_raw = (
            raw_counter_reason == "official"
            or (counter_mult > 1.0001 and raw_counter_reason not in inferred_reasons)
        )
        official_min_mult = max(
            1.0,
            self._number(getattr(self.cfg, "event_counter_official_min_mult", 1.02), 1.02),
        )
        official_counter = bool(official_counter_raw and counter_mult + 1e-9 >= official_min_mult)
        inferred_counter = raw_counter_reason in inferred_reasons

        # Keep the game's official counter metadata, and additionally recognize
        # the broadcast rule. A counter is broadcast-eligible only at 25+
        # damage; official low-damage marks remain auditable but are suppressed
        # from the HUD/report counter verdict.
        previous_attack = self._last_attack.get(receiver) or {}
        counter_window = max(0.05, self._number(getattr(self.cfg, "event_counter_window_sec", 0.7), 0.7))
        graze_max = max(0.0, self._number(getattr(self.cfg, "event_counter_graze_max_damage", 15.0), 15.0))
        response_min = max(
            self.COUNTER_MIN_DAMAGE,
            self._number(getattr(self.cfg, "event_counter_response_min_damage", 30.0), 30.0),
        )
        elapsed_from_previous = abs(event_time - self._number(previous_attack.get("time"), -9999.0))
        previous_damage = self._number(previous_attack.get("damage"), 0.0)
        previous_is_opportunity = (
            str(previous_attack.get("receiver") or "") == side
            and elapsed_from_previous <= counter_window
        )
        if (
            not inferred_counter
            and previous_is_opportunity
            and (
                (previous_damage <= 0.0 and damage >= self.COUNTER_MIN_DAMAGE)
                or (previous_damage <= graze_max and damage >= response_min)
            )
        ):
            inferred_counter = True
            raw_counter_reason = "whiff" if previous_damage <= 0.0 else "graze"

        counter_eligible = damage >= self.COUNTER_MIN_DAMAGE
        if not counter_eligible:
            inferred_counter = False
        # A single opponent attack can produce only one counter success. The
        # first qualifying reply consumes that opportunity; later punches are
        # combo follow-ups, not additional counters.
        opportunity_id = str(raw.get("counter_opportunity_id") or "").strip()
        if not opportunity_id and previous_is_opportunity:
            opportunity_id = str(previous_attack.get("opportunity_id") or "")
        opportunity_consumed = bool(
            opportunity_id and opportunity_id in self._consumed_counter_opportunities
        )
        declared_counter = bool(raw.get("is_counter", False)) and counter_mult <= 1.0001
        counter = bool(
            counter_eligible
            and not opportunity_consumed
            and (official_counter or inferred_counter or declared_counter)
        )
        if counter and opportunity_id:
            self._consumed_counter_opportunities.add(opportunity_id)
        counter_reason = (
            "official"
            if counter and official_counter
            else raw_counter_reason
            if counter and raw_counter_reason in inferred_reasons
            else "declared"
            if counter
            else ""
        )
        combo_min_damage = max(0.0, self._number(getattr(self.cfg, "event_combo_min_damage", 15.0), 15.0))
        combo_window = max(0.1, self._number(getattr(self.cfg, "event_combo_window_sec", 0.8), 0.8))
        combo_break_damage = max(0.0, self._number(getattr(self.cfg, "event_combo_break_damage", 20.0), 20.0))

        combo_hits = 0
        combo_damage = 0.0
        if side in ("blue", "red") and receiver in ("blue", "red"):
            # A meaningful opponent hit breaks the current chain, matching the
            # current HUD behaviour.  Small counter trades do not.
            other = "red" if side == "blue" else "blue"
            other_state = self._combo.get(other) or {}
            if (str(other_state.get("receiver") or "") == side and damage >= combo_break_damage):
                self._combo[other] = {}
            if damage >= combo_min_damage:
                previous = self._combo.get(side) or {}
                elapsed = abs(event_time - self._number(previous.get("time"), -9999.0))
                same_chain = (
                    str(previous.get("receiver") or "") == receiver
                    and elapsed <= combo_window
                )
                combo_hits = int(previous.get("hits", 0) or 0) + 1 if same_chain else 1
                combo_damage = self._number(previous.get("damage"), 0.0) + damage if same_chain else damage
                self._combo[side] = {"receiver": receiver, "time": event_time, "hits": combo_hits, "damage": combo_damage}
            self._last_attack[side] = {
                "receiver": receiver,
                "time": event_time,
                "damage": damage,
                "opportunity_id": counter_opportunity_id(raw),
            }

        heavy_min = max(0.0, self._number(getattr(self.cfg, "event_heavy_damage", 50.0), 50.0))
        signature_min = max(heavy_min, self._number(getattr(self.cfg, "event_signature_damage", 60.0), 60.0))
        counter_min = max(0.0, self._number(getattr(self.cfg, "event_counter_min_damage", 40.0), 40.0))
        combo_emphasis_min = max(2, int(self._number(getattr(self.cfg, "event_combo_emphasis_hits", 5), 5)))

        tags = ["hit"]
        if counter:
            tags.append("counter")
            if counter_reason:
                tags.append(f"counter_{counter_reason}")
        if counter and damage >= counter_min:
            tags.append("counter_strong")
        if combo_hits >= 2:
            tags.append("combo")
        if combo_hits >= combo_emphasis_min:
            tags.append("combo_emphasis")
        if damage >= heavy_min:
            tags.append("heavy")
        # High raw damage is not enough to call a signature play: it must also
        # show a read or a sequence, unless the game itself declares a result.
        if damage >= signature_min and (counter or combo_hits >= 3):
            tags.append("signature")
        if effect_kind in SPECIAL_KINDS:
            tags.append(effect_kind)
            tags.append("decisive")
        if weak_point and weak_point not in ("none", "normal", "-", "0"):
            weak_tag = "".join(ch if ch.isalnum() else "_" for ch in weak_point).strip("_")
            tags.append("weak_point")
            if weak_tag:
                tags.append(f"weak_{weak_tag}")

        # Secondary broadcast moments are also classified here, rather than
        # independently in the browser, so commentary/POTM/reports can consume
        # the exact same verdict later without reinterpreting raw rows.
        if (
            not counter
            and damage >= 35.0
            and str(previous_attack.get("receiver") or "") == side
            and previous_damage >= combo_min_damage
            and elapsed_from_previous <= 1.2
        ):
            tags.append("answer_back")

        if side in ("blue", "red") and receiver in ("blue", "red"):
            other = "red" if side == "blue" else "blue"
            if damage >= combo_break_damage:
                self._momentum[other] = []
            if damage >= combo_min_damage:
                sequence = [
                    item for item in list(self._momentum.get(side) or [])
                    if abs(event_time - self._number(item.get("time"), -9999.0)) <= 3.0
                    and str(item.get("receiver") or "") == receiver
                ]
                sequence.append({"time": event_time, "damage": damage, "receiver": receiver})
                if len(sequence) >= 3 and sum(self._number(item.get("damage")) for item in sequence) >= 80.0:
                    tags.append("momentum")
                    self._momentum[side] = []
                else:
                    self._momentum[side] = sequence

            if weak_point and weak_point not in ("none", "normal", "-", "0") and damage > 0.0:
                target_map = self._weak_targets.setdefault(side, {})
                target_rows = [
                    item for item in list(target_map.get(weak_point) or [])
                    if abs(event_time - self._number(item.get("time"), -9999.0)) <= 8.0
                ]
                target_rows.append({"time": event_time, "damage": damage})
                if len(target_rows) >= 3 and sum(self._number(item.get("damage")) for item in target_rows) >= 70.0:
                    tags.append("target_lock")
                    target_map[weak_point] = []
                else:
                    target_map[weak_point] = target_rows

        return {
            "event_id": str(raw.get("event_id") or ""),
            "side": side,
            "receiver_side": receiver,
            "damage": round(damage, 2),
            "counter": counter,
            "counter_eligible": counter_eligible,
            "counter_reason": counter_reason,
            "official_counter": bool(official_counter),
            "official_counter_raw": bool(official_counter_raw),
            "inferred_counter": bool(inferred_counter),
            "counter_opportunity_id": opportunity_id,
            "effect_kind": effect_kind,
            "weak_point": weak_point,
            "combo_hits": combo_hits,
            "combo_damage": round(combo_damage, 2),
            "tags": tags,
            "primary": "decisive" if "decisive" in tags else "signature" if "signature" in tags else "heavy" if "heavy" in tags else "counter_strong" if "counter_strong" in tags else "combo_emphasis" if "combo_emphasis" in tags else "answer_back" if "answer_back" in tags else "momentum" if "momentum" in tags else "target_lock" if "target_lock" in tags else "weak_point" if "weak_point" in tags else "hit",
        }
