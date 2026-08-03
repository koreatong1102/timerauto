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
    """Match-memory and final arbitration for live commentary.

    This class deliberately has no TTS or file I/O.  Its cooldown state is
    updated only after a candidate wins final arbitration, so a line that was
    merely considered never silences a later, real broadcast call.
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
        self._last_text_at: Dict[str, float] = {}

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
        """Remember hits and offer one contextual line, if it is meaningful."""
        state = self._ensure_round(round_no)
        names = dict(names or {})
        contextual: List[CommentaryCandidate] = []

        for raw in events or []:
            event = dict(raw or {})
            # Countdown timestamps can repeat in every round.  Without the
            # round number, an otherwise identical hit in a later round was
            # incorrectly treated as an already-seen event.
            key = (int(self._active_round or 1),) + self._event_key(event)
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
            item = {
                "attacker": attacker,
                "receiver": receiver,
                "damage": damage,
                "game_time": self._number(event.get("time")),
                "observed_at": time.monotonic(),
            }
            self._recent_exchange.append(item)
            state["damage"][attacker] += damage
            if damage >= 10.0:
                state["landed"][attacker] += 1
            event_tags = {
                str(tag or "").lower().strip()
                for tag in list(event.get("event_tags") or [])
            }
            if (
                bool(event_tags.intersection({"heavy", "signature", "counter_strong"}))
                if event_tags
                else damage >= 45.0
            ):
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
                        text=f"{name}, 맞자마자 곧바로 받아칩니다.",
                        role="caster",
                        category="answer_back",
                        priority=72,
                        key=f"answer:{attacker}:{round(gap, 1)}",
                        attacker_side=attacker,
                    ))

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
                    text=f"{name}, 흐름을 다시 가져옵니다!",
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
        """Choose exactly one line and consume cooldown only for that line."""
        timestamp = float(time.monotonic() if now is None else now)
        items = [item for item in candidates or [] if str(item.text or "").strip()]
        if not items:
            return CommentaryDecision(None, "empty")

        counter = next((item for item in items if item.category == "counter"), None)
        combo = next((item for item in items if item.category == "combo"), None)
        if counter and combo:
            attacker = counter.attacker_side or combo.attacker_side
            name = str(counter.attacker_name or combo.attacker_name or "").strip()
            merged_text = f"{name}, 카운터 뒤에 연타까지 연결합니다." if name else "카운터 뒤에 연타까지 연결합니다."
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
            text_key = " ".join(str(candidate.text or "").split()).casefold()
            if timestamp - float(self._last_key_at.get(key, 0.0) or 0.0) < 4.0:
                suppressed.append(f"{candidate.category}:duplicate")
                continue
            # Generic live calls used to repeat as soon as the six-second
            # global cooldown expired.  Keep exact non-critical sentences out
            # of rotation for 45 seconds, while still allowing a genuinely
            # new knockdown/stun/TKO call to describe the action.
            if (
                candidate.category not in ("tko", "knockdown", "stun")
                and text_key in self._last_text_at
                and timestamp - float(self._last_text_at[text_key]) < 45.0
            ):
                suppressed.append(f"{candidate.category}:text_duplicate")
                continue
            category_floor = 1.8 if candidate.urgent or candidate.priority >= 80 else 3.0
            if timestamp - float(self._last_category_at.get(candidate.category, 0.0) or 0.0) < category_floor:
                suppressed.append(f"{candidate.category}:category_cooldown")
                continue
            # Only stoppage/down/stun can ignore the broadcast pacing. Counter
            # and combo remain important, but must respect the user's cooldown.
            bypass_global = candidate.category in ("tko", "knockdown", "stun")
            if not bypass_global and timestamp - float(self._last_live_at or 0.0) < max(0.0, float(cooldown_sec)):
                suppressed.append(f"{candidate.category}:global_cooldown")
                continue
            self._last_key_at[key] = timestamp
            self._last_text_at[text_key] = timestamp
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
            return f"{self._name(names, current_leader)} 쪽이 흐름을 바꾸며 반등합니다."
        current_damage = dict(current.get("damage") or {})
        previous_damage = dict(previous.get("damage") or {})
        for side in VALID_SIDES:
            before = self._number(previous_damage.get(side))
            after = self._number(current_damage.get(side))
            if before >= 35.0 and after >= before * 1.45 and after - before >= 35.0:
                return f"{self._name(names, side)} 쪽이 지난 라운드보다 유효타 비중을 확실히 끌어올립니다."
        current_top = dict(current.get("top_punch") or {})
        previous_top = dict(previous.get("top_punch") or {})
        for side in VALID_SIDES:
            before = str(previous_top.get(side) or "").strip()
            after = str(current_top.get(side) or "").strip()
            if before and after and before != after:
                return f"{self._name(names, side)} 쪽이 주력 공격을 {before}에서 {after}(으)로 바꾸며 변화를 줍니다."
        current_kd = dict(current.get("knockdowns") or {})
        previous_kd = dict(previous.get("knockdowns") or {})
        for side in VALID_SIDES:
            if self._number(current_kd.get(side)) > self._number(previous_kd.get(side)):
                return f"{self._name(names, side)} 쪽이 다운을 만들어내며 지난 라운드와 다른 흐름을 보여줍니다."
        current_big = dict(current.get("big_hits") or {})
        previous_big = dict(previous.get("big_hits") or {})
        for side in VALID_SIDES:
            if (
                self._number(current_big.get(side)) >= self._number(previous_big.get(side)) + 2
                and self._number(current_big.get(side)) >= 3
            ):
                return f"{self._name(names, side)} 쪽이 강타 비중을 끌어올리며 교전의 무게를 바꿉니다."
        # Same leader, wider gap: describe reinforcement rather than repeating
        # the generic "앞섰습니다" line in every break report.
        if current_leader and current_leader == previous_leader:
            current_damage_gap = abs(
                self._number(current_damage.get("blue"))
                - self._number(current_damage.get("red"))
            )
            previous_damage = dict(previous.get("damage") or {})
            previous_damage_gap = abs(
                self._number(previous_damage.get("blue"))
                - self._number(previous_damage.get("red"))
            )
            if current_damage_gap >= previous_damage_gap + 20.0:
                return f"{self._name(names, current_leader)} 쪽이 같은 흐름을 이어가며 데미지 차이를 더 벌립니다."
        return ""
