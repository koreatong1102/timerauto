from __future__ import annotations

from typing import Dict, List, Tuple

from commentary_director import CommentaryCandidate, CommentaryDirector
from match_analytics import build_match_commentary


def _step(candidate: CommentaryCandidate, label: str) -> dict:
    return {
        "role": candidate.role,
        "text": candidate.text,
        "category": candidate.category,
        "label": label,
        "post_ms": 850,
    }


def build_commentary_director_demo() -> Tuple[List[dict], Dict[str, bool]]:
    """Build deterministic spoken scenarios through the real commentary logic."""
    names = {"blue": "진혁", "red": "아버"}
    steps: List[dict] = []
    checks: Dict[str, bool] = {}

    priority_director = CommentaryDirector()
    merged = priority_director.choose_live(
        [
            CommentaryCandidate(
                "카운터가 적중됩니다!",
                "analyst",
                "counter",
                84,
                key="demo-counter",
                urgent=True,
                attacker_side="blue",
                attacker_name=names["blue"],
            ),
            CommentaryCandidate(
                "좋은 콤보가 적중합니다!",
                "analyst",
                "combo",
                78,
                key="demo-combo",
                urgent=True,
                attacker_side="blue",
                attacker_name=names["blue"],
            ),
        ],
        cooldown_sec=6.0,
        now=10.0,
    )
    checks["counter_combo_merge"] = bool(
        merged.candidate and merged.candidate.category == "counter_combo"
    )
    if merged.candidate:
        steps.append(_step(merged.candidate, "카운터와 콤보 병합"))

    urgent_director = CommentaryDirector()
    urgent = urgent_director.choose_live(
        [
            CommentaryCandidate(
                "좋은 콤보가 적중합니다!", "analyst", "combo", 78, urgent=True
            ),
            CommentaryCandidate(
                "아버, 크게 흔들립니다!", "caster", "stun", 96, urgent=True
            ),
        ],
        cooldown_sec=6.0,
        now=20.0,
    )
    checks["urgent_priority"] = bool(urgent.candidate and urgent.candidate.category == "stun")
    if urgent.candidate:
        steps.append(_step(urgent.candidate, "긴급 상황 우선순위"))

    exchange_director = CommentaryDirector()
    answer_back = exchange_director.observe_events(
        1,
        [
            {
                "time": 70.0,
                "damage": 32,
                "attacker_side": "red",
                "receiver_side": "blue",
                "punch": "Hook",
            },
            {
                "time": 69.4,
                "damage": 35,
                "attacker_side": "blue",
                "receiver_side": "red",
                "punch": "Straight",
            },
        ],
        names,
    )
    checks["answer_back"] = bool(answer_back and answer_back.category == "answer_back")
    if answer_back:
        steps.append(_step(answer_back, "즉시 반격 흐름"))

    momentum_director = CommentaryDirector()
    momentum_director.observe_events(
        1,
        [
            {"time": 60.0, "damage": 45, "attacker_side": "blue", "receiver_side": "red", "punch": "Hook"},
            {"time": 59.5, "damage": 40, "attacker_side": "blue", "receiver_side": "red", "punch": "Straight"},
        ],
        names,
    )
    momentum_flip = momentum_director.observe_events(
        1,
        [
            {"time": 58.0, "damage": 20, "attacker_side": "red", "receiver_side": "blue", "punch": "Jab"},
            {"time": 57.6, "damage": 60, "attacker_side": "red", "receiver_side": "blue", "punch": "Hook"},
            {"time": 57.1, "damage": 55, "attacker_side": "red", "receiver_side": "blue", "punch": "Uppercut"},
        ],
        names,
    )
    checks["momentum_flip"] = bool(
        momentum_flip and momentum_flip.category == "momentum_flip"
    )
    if momentum_flip:
        steps.append(_step(momentum_flip, "주도권 전환"))

    round_director = CommentaryDirector()
    round_director.record_round(
        1,
        {
            "leader": "blue",
            "damage": {"blue": 170, "red": 105},
            "top_punch": {"blue": "스트레이트", "red": "훅"},
        },
        names,
    )
    adaptation = round_director.record_round(
        2,
        {
            "leader": "red",
            "damage": {"blue": 120, "red": 205},
            "top_punch": {"blue": "훅", "red": "어퍼컷"},
        },
        names,
    )
    checks["round_adaptation"] = bool(adaptation)
    if adaptation:
        steps.append(
            {
                "role": "analyst",
                "text": adaptation,
                "category": "round_adaptation",
                "label": "라운드 전술 변화",
                "post_ms": 950,
            }
        )

    duplicate_director = CommentaryDirector()
    duplicate = CommentaryCandidate(
        "중복 억제 확인용 멘트입니다.",
        "analyst",
        "flow",
        55,
        key="demo-duplicate",
    )
    duplicate_director.choose_live([duplicate], cooldown_sec=0.0, now=100.0)
    suppressed = duplicate_director.choose_live([duplicate], cooldown_sec=0.0, now=101.0)
    checks["duplicate_suppression"] = suppressed.candidate is None

    final_text = build_match_commentary(
        {
            "winner": "red",
            "resultMethod": "TKO",
            "blue": {
                "name": names["blue"],
                "damage": 312,
                "counterHits": 2,
                "knockdowns": 0,
                "bigHits": 3,
                "powerHits55": 1,
                "accuracy": 51,
                "fightStyle": {"label": "압박형 인파이터"},
            },
            "red": {
                "name": names["red"],
                "damage": 488,
                "counterHits": 7,
                "knockdowns": 2,
                "bigHits": 8,
                "powerHits55": 3,
                "accuracy": 62,
                "fightStyle": {"label": "카운터 마스터"},
            },
            "officialScorecard": {
                "rounds": [
                    {
                        "round": 1,
                        "blue_score": 10,
                        "red_score": 9,
                        "blue_kds": 0,
                        "red_kds": 0,
                        "blue_damage_taken": 110,
                        "red_damage_taken": 150,
                    },
                    {
                        "round": 2,
                        "blue_score": 8,
                        "red_score": 10,
                        "blue_kds": 2,
                        "red_kds": 0,
                        "blue_damage_taken": 260,
                        "red_damage_taken": 120,
                    },
                ]
            },
        }
    )
    checks["match_narrative"] = bool(final_text)
    if final_text:
        steps.append(
            {
                "role": "analyst",
                "text": final_text,
                "category": "match_narrative",
                "label": "경기 종료 서사",
                "post_ms": 1200,
            }
        )

    return steps, checks
