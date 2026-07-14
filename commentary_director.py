from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple


VALID_SIDES = ("blue", "red")


@dataclass(frozen=True)
class CommentaryCandidate:
    text: str
    role: str
    category: str
    priority: int
    key: str = ""
    urgent: bool = False
    attacker_side: str = ""
    attacker_name: str = ""


@dataclass(frozen=True)
class CommentaryDecision:
    candidate: Optional[CommentaryCandidate]
    reason: str
    suppressed: Tuple[str, ...] = ()


class CommentaryDirector:
    """Small, deterministic match-memory layer for broadcast commentary.

    The director never reads files, performs TTS, or touches the browser path.
    It only remembers lightweight facts and selects one line from facts that
    were already produced by the spectator watcher.
    """

    def __init__(self) -> None:
        self.reset_match()

    def reset_match(self) -> None:
        self._active_round = 0
        self._rounds: Dict[int, Dict[str, Any]] = {}
        self._seen_events: set = set()
        self._recent_exchange: Deque[Dict[str, Any]] = deque(maxlen=24)
        self._momentum_side = ""
        self._last_live_at = 0.0
        self._last_category_at: Dict[str, float] = {}
        self._last_key_at: Dict[str, float] = {}

    @staticmethod
    def _side(value: Any) -> str:
        side = str(value or "").strip().lower()
        return side if side in VALID_SIDES else ""

    @staticmethod
    def _number(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @classmethod
    def _event_key(cls, event: dict) -> Tuple[Any, ...]:
        return (
            round(cls._number(event.get("time")), 3),
            round(cls._number(event.get("damage")), 2),
            cls._side(event.get("attacker_side")),
            cls._side(event.get("receiver_side")),
            str(event.get("punch") or "").strip().lower(),
            str(event.get("damage_type") or "").strip().lower(),
            str(event.get("weak_point") or "").strip().lower(),
        )

    @staticmethod
    def _name(names: Dict[str, str], side: str) -> str:
        fallback = "블루 코너" if side == "blue" else "레드 코너"
        return str((names or {}).get(side) or fallback).strip()

    def _ensure_round(self, round_no: Optional[int]) -> Dict[str, Any]:
        try:
            number = max(1, int(round_no or 1))
        except (TypeError, ValueError):
            number = 1
        if number != self._active_round:
            self._active_round = number
            self._recent_exchange.clear()
            self._momentum_side = ""
        return self._rounds.setdefault(number, {
            "round": number,
            "damage": {"blue": 0.0, "red": 0.0},
            "landed": {"blue": 0, "red": 0},
            "big_hits": {"blue": 0, "red": 0},
            "weak": {"blue": {}, "red": {}},
        })

    def observe_events(
        self,
        round_no: Optional[int],
        events: Iterable[dict],
        names: Optional[Dict[str, str]] = None,
    ) -> Optional[CommentaryCandidate]:
        """Remember new hits and return one optional flow-level observation."""
        state = self._ensure_round(round_no)
        names = dict(names or {})
        contextual: List[CommentaryCandidate] = []

        for raw in events or []:
            event = dict(raw or {})
            key = self._event_key(event)
            if key in self._seen_events:
                continue
            self._seen_events.add(key)
            attacker = self._side(event.get("attacker_side"))
            receiver = self._side(event.get("receiver_side"))
            punch = str(event.get("punch") or "").strip().lower()
            damage = max(0.0, self._number(event.get("damage")))
            if attacker not in VALID_SIDES or receiver not in VALID_SIDES or punch in ("pull", "other"):
                continue

            previous = self._recent_exchange[-1] if self._recent_exchange else None
            observed_at = time.monotonic()
            item = {
                "attacker": attacker,
                "receiver": receiver,
                "damage": damage,
                "game_time": self._number(event.get("time")),
                "observed_at": observed_at,
            }
            self._recent_exchange.append(item)
            state["damage"][attacker] += damage
            if damage >= 10.0:
                state["landed"][attacker] += 1
            if damage >= 45.0:
                state["big_hits"][attacker] += 1
            weak = str(event.get("weak_point") or "").strip()
            if weak and damage >= 10.0:
                bucket = state["weak"][attacker]
                bucket[weak] = int(bucket.get(weak, 0) or 0) + 1

            if previous and previous.get("attacker") == receiver and damage >= 30.0:
                gap = abs(self._number(previous.get("game_time")) - self._number(item.get("game_time")))
                if gap <= 1.2 and self._number(previous.get("damage")) >= 25.0:
                    name = self._name(names, attacker)
                    contextual.append(CommentaryCandidate(
                    text=f"{name}, 맞자마자 곧바로 받아칩니다!",
                        role="caster",
                        category="answer_back",
                        priority=72,
                        key=f"answer:{attacker}:{round(gap, 1)}",
                        attacker_side=attacker,
                    ))

        # A short rolling exchange detects genuine flow changes without scanning
        # the damage file or delaying the immediate browser event path.
        now = time.monotonic()
        while self._recent_exchange and now - self._number(self._recent_exchange[0].get("observed_at")) > 4.0:
            self._recent_exchange.popleft()
        rolling = {"blue": 0.0, "red": 0.0}
        for item in self._recent_exchange:
            rolling[str(item.get("attacker") or "")] += self._number(item.get("damage"))
        leader = "blue" if rolling["blue"] > rolling["red"] else "red"
        gap = rolling[leader] - rolling["red" if leader == "blue" else "blue"]
        if rolling[leader] >= 70.0 and gap >= 40.0:
            if self._momentum_side and self._momentum_side != leader:
                name = self._name(names, leader)
                contextual.append(CommentaryCandidate(
                    text=f"{name}, 연속 정타로 흐름을 다시 가져옵니다!",
                    role="analyst",
                    category="momentum_flip",
                    priority=66,
                    key=f"momentum:{self._active_round}:{leader}",
                    attacker_side=leader,
                ))
            self._momentum_side = leader

        return max(contextual, key=lambda item: item.priority) if contextual else None

    def choose_live(
        self,
        candidates: Iterable[CommentaryCandidate],
        *,
        cooldown_sec: float,
        now: Optional[float] = None,
    ) -> CommentaryDecision:
        """Select one current line and suppress stale or lower-value lines."""
        timestamp = float(time.monotonic() if now is None else now)
        items = [item for item in candidates or [] if str(item.text or "").strip()]
        if not items:
            return CommentaryDecision(None, "empty")

        counter = next((item for item in items if item.category == "counter"), None)
        combo = next((item for item in items if item.category == "combo"), None)
        if counter and combo:
            attacker = counter.attacker_side or combo.attacker_side
            name = str(counter.attacker_name or combo.attacker_name or "").strip()
            merged_text = f"{name}, 카운터로 연타를 연결합니다!" if name else "카운터에 이어 연타까지 연결합니다!"
            items = [item for item in items if item.category not in ("counter", "combo")]
            items.append(CommentaryCandidate(
                text=merged_text,
                role="analyst",
                category="counter_combo",
                priority=max(counter.priority, combo.priority) + 2,
                key=f"counter-combo:{counter.key}:{combo.key}",
                urgent=True,
                attacker_side=attacker,
                attacker_name=name,
            ))

        items.sort(key=lambda item: (int(item.priority), bool(item.urgent)), reverse=True)
        suppressed: List[str] = []
        for candidate in items:
            key = str(candidate.key or f"{candidate.category}:{candidate.text}")
            last_key = float(self._last_key_at.get(key, 0.0) or 0.0)
            if timestamp - last_key < 4.0:
                suppressed.append(f"{candidate.category}:duplicate")
                continue
            category_floor = 1.8 if candidate.urgent or candidate.priority >= 80 else 3.0
            last_category = float(self._last_category_at.get(candidate.category, 0.0) or 0.0)
            if timestamp - last_category < category_floor:
                suppressed.append(f"{candidate.category}:category_cooldown")
                continue
            bypass_global = candidate.urgent or candidate.priority >= 75
            if not bypass_global and timestamp - float(self._last_live_at or 0.0) < max(0.0, float(cooldown_sec)):
                suppressed.append(f"{candidate.category}:global_cooldown")
                continue
            self._last_key_at[key] = timestamp
            self._last_category_at[candidate.category] = timestamp
            self._last_live_at = timestamp
            suppressed.extend(item.category for item in items if item is not candidate)
            return CommentaryDecision(candidate, "highest_priority", tuple(suppressed))
        return CommentaryDecision(None, "suppressed", tuple(suppressed))

    def record_round(
        self,
        round_no: Optional[int],
        metrics: Dict[str, Any],
        names: Optional[Dict[str, str]] = None,
    ) -> str:
        """Store one completed round and describe only a meaningful adaptation."""
        state = self._ensure_round(round_no)
        current = dict(metrics or {})
        current["round"] = int(state.get("round", 1) or 1)
        number = int(current["round"])
        previous = dict(self._rounds.get(number - 1) or {})
        self._rounds[number] = current
        if not previous:
            return ""

        names = dict(names or {})
        current_leader = self._side(current.get("leader"))
        previous_leader = self._side(previous.get("leader"))
        if current_leader and previous_leader and current_leader != previous_leader:
            name = self._name(names, current_leader)
            return f"전 라운드와 달리 이번에는 {name} 쪽이 흐름을 되찾으며 승부의 방향을 바꿨습니다."

        current_damage = dict(current.get("damage") or {})
        previous_damage = dict(previous.get("damage") or {})
        for side in VALID_SIDES:
            before = self._number(previous_damage.get(side))
            after = self._number(current_damage.get(side))
            if before >= 35.0 and after >= before * 1.45 and after - before >= 35.0:
                name = self._name(names, side)
                return f"{name}, 전 라운드보다 유효타의 힘과 빈도를 확실히 끌어올렸습니다."

        current_top = dict(current.get("top_punch") or {})
        previous_top = dict(previous.get("top_punch") or {})
        for side in VALID_SIDES:
            before = str(previous_top.get(side) or "").strip()
            after = str(current_top.get(side) or "").strip()
            if before and after and before != after:
                name = self._name(names, side)
                return f"{name}, 주력 공격을 {before}에서 {after}로 바꾸며 전술에 변화를 줬습니다."
        return ""
