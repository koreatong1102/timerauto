"""Shared, data-driven fight event classification.

This module deliberately has no Qt/OBS/browser dependencies.  It converts a
raw spectator damage row into stable broadcast event names once, so the live
HUD, commentary metadata, OBS highlight capture, POTM scoring, and diagnostics
can share the same verdict.  A shadow switch remains for diagnostic comparison
and safe rollback.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List


SPECIAL_KINDS = {"stun", "knockdown", "down", "ko", "tko"}


class FightEventEngine:
    def __init__(self, cfg: Any):
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self._combo: Dict[str, Dict[str, Any]] = {
            "blue": {},
            "red": {},
        }

    @staticmethod
    def _number(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    def classify_many(self, rows: Iterable[dict]) -> List[dict]:
        ordered = sorted((dict(row or {}) for row in rows if isinstance(row, dict)), key=lambda row: self._number(row.get("time")))
        return [self.classify(row) for row in ordered]

    def classify(self, row: dict) -> dict:
        raw = dict(row or {})
        side = str(raw.get("attacker_side") or "").lower().strip()
        receiver = str(raw.get("receiver_side") or "").lower().strip()
        damage = max(0.0, self._number(raw.get("damage")))
        event_time = self._number(raw.get("time"))
        effect_kind = str(raw.get("effect_kind") or "").lower().strip()
        counter = bool(raw.get("is_counter", False)) or self._number(raw.get("counter_mult"), 1.0) > 1.0001
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
                same_chain = (
                    str(previous.get("receiver") or "") == receiver
                    and 0.0 <= event_time - self._number(previous.get("time"), -9999.0) <= combo_window
                )
                combo_hits = int(previous.get("hits", 0) or 0) + 1 if same_chain else 1
                combo_damage = self._number(previous.get("damage"), 0.0) + damage if same_chain else damage
                self._combo[side] = {"receiver": receiver, "time": event_time, "hits": combo_hits, "damage": combo_damage}

        heavy_min = max(0.0, self._number(getattr(self.cfg, "event_heavy_damage", 50.0), 50.0))
        signature_min = max(heavy_min, self._number(getattr(self.cfg, "event_signature_damage", 60.0), 60.0))
        counter_min = max(0.0, self._number(getattr(self.cfg, "event_counter_min_damage", 40.0), 40.0))
        combo_emphasis_min = max(2, int(self._number(getattr(self.cfg, "event_combo_emphasis_hits", 5), 5)))

        tags = ["hit"]
        if counter:
            tags.append("counter")
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

        return {
            "event_id": str(raw.get("event_id") or ""),
            "side": side,
            "receiver_side": receiver,
            "damage": round(damage, 2),
            "counter": counter,
            "effect_kind": effect_kind,
            "combo_hits": combo_hits,
            "combo_damage": round(combo_damage, 2),
            "tags": tags,
            "primary": "decisive" if "decisive" in tags else "signature" if "signature" in tags else "heavy" if "heavy" in tags else "counter_strong" if "counter_strong" in tags else "combo_emphasis" if "combo_emphasis" in tags else "hit",
        }
