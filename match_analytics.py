from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional


VALID_RESULTS = {"blue", "red", "draw"}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _count(value: Any) -> int:
    return max(0, int(round(_number(value))))


def _normalized_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def detect_stoppage(events: Iterable[dict], round_no: Optional[int] = None) -> Dict[str, Any]:
    """Find a terminal TKO directly from damage events.

    This intentionally does not depend on throw-to-impact matching. A terminal
    event is authoritative even when punches_thrown.txt is late or incomplete.
    """
    candidates: List[Dict[str, Any]] = []
    for raw in events or []:
        event = dict(raw or {})
        token = _normalized_token(event.get("damage_type"))
        if token != "tko" and "technicalknockout" not in token:
            continue
        winner = str(event.get("attacker_side") or "").lower().strip()
        loser = str(event.get("receiver_side") or "").lower().strip()
        if winner not in ("blue", "red") or loser not in ("blue", "red") or winner == loser:
            continue
        candidates.append({
            "winner": winner,
            "loser": loser,
            "round": max(1, _count(round_no or event.get("round") or 1)),
            "method": "TKO",
            "eventTime": _number(event.get("time")),
            "source": "damage_events",
        })
    if not candidates:
        return {}
    return max(candidates, key=lambda item: _number(item.get("eventTime")))


def resolve_match_result(
    winner_file: Optional[dict],
    stoppage: Optional[dict],
    state: str,
    blue_total: int = 0,
    red_total: int = 0,
) -> Dict[str, Any]:
    """Resolve a result with explicit source priority.

    winner.txt is official. A terminal damage event or three-down stoppage is
    next. Point totals are used only for normal result/end states, never to
    guess a TKO winner while winner.txt is still being written.
    """
    winner_data = dict(winner_file or {})
    winner = str(winner_data.get("side") or "").lower().strip()
    if winner in VALID_RESULTS:
        stoppage_data = dict(stoppage or {})
        stoppage_winner = str(stoppage_data.get("winner") or "").lower().strip()
        stoppage_method = str(stoppage_data.get("method") or "").strip()
        method = stoppage_method if winner == stoppage_winner and stoppage_method else str(
            winner_data.get("method") or "판정"
        )
        return {
            "winner": winner,
            "method": method,
            "source": "winner.txt+stoppage" if winner == stoppage_winner and stoppage_method else "winner.txt",
            "confidence": 1.0,
        }

    stoppage_data = dict(stoppage or {})
    winner = str(stoppage_data.get("winner") or "").lower().strip()
    if winner in ("blue", "red"):
        return {
            "winner": winner,
            "method": str(stoppage_data.get("method") or "TKO"),
            "source": str(stoppage_data.get("source") or "stoppage"),
            "confidence": 0.99,
        }

    normalized_state = _normalized_token(state)
    if normalized_state in ("results", "result", "end", "ended", "complete", "completed", "finished"):
        blue_score = int(blue_total or 0)
        red_score = int(red_total or 0)
        winner = "blue" if blue_score > red_score else "red" if red_score > blue_score else "draw"
        return {
            "winner": winner,
            "method": "판정",
            "source": "scores.csv",
            "confidence": 0.95,
        }

    return {"winner": "", "method": "", "source": "pending", "confidence": 0.0}


def _punch_count_map(stats: dict) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for item in list(stats.get("landedBreakdown") or stats.get("punchTop") or []):
        key = str((item or {}).get("key") or "").lower().strip()
        if key:
            result[key] = result.get(key, 0) + _count((item or {}).get("count"))
    return result


def _target_profile(stats: dict, opponent_stats: Optional[dict] = None) -> Dict[str, int]:
    result = {"head": 0, "body": 0, "total": 0}
    own = dict(stats or {})
    opponent = dict(opponent_stats or {})
    items = (
        own.get("weakHitAll")
        or own.get("weakHitTop")
        or opponent.get("weakReceivedAll")
        or opponent.get("weakReceivedTop")
        or []
    )
    for item in list(items):
        label = str((item or {}).get("label") or "")
        count = _count((item or {}).get("count"))
        if count <= 0:
            continue
        result["total"] += count
        if any(token in label for token in ("명치", "간", "복부", "몸통")):
            result["body"] += count
        elif any(token in label for token in ("턱", "코", "관자", "얼굴", "머리")):
            result["head"] += count
    return result


def analyze_fight_style(
    stats: Optional[dict],
    opponent_stats: Optional[dict] = None,
    *,
    min_attempts: int = 20,
    min_landed: int = 10,
) -> Dict[str, Any]:
    """Classify a fighter with inexpensive, deterministic Korean labels."""
    data = dict(stats or {})
    opponent = dict(opponent_stats or {})
    attempts = _count(data.get("thrown") or data.get("activity"))
    landed = _count(data.get("landed"))
    if attempts < max(1, int(min_attempts)) and landed < max(1, int(min_landed)):
        return {
            "label": "분석 중",
            "signature": "표본 부족",
            "description": "기록이 더 쌓이면 경기 스타일을 판정합니다.",
            "confidence": 0,
            "evidence": [],
        }

    accuracy = _number(data.get("accuracy"), -1.0)
    if accuracy < 0 and attempts > 0:
        accuracy = landed / attempts * 100.0
    landed_damage = _number(data.get("landedDamage"))
    average = _number(
        data.get("averageHitDamage", data.get("averageDamage")),
        landed_damage / landed if landed else 0.0,
    )
    big45 = _count(data.get("bigHits"))
    big55 = _count(data.get("powerHits55"))
    counters = _count(data.get("counterHits"))
    knockdowns = _count(data.get("knockdowns"))
    stuns = _count(data.get("stuns"))
    combo = _count(data.get("maxComboHits"))
    punch_counts = _punch_count_map(data)
    targets = _target_profile(data, opponent)
    landed_base = max(1, landed)
    candidates: List[tuple] = []

    counter_rate = counters / landed_base
    if counters >= 4 and counter_rate >= 0.16:
        score = 55 + min(22, counter_rate * 80) + min(12, counters * 1.5)
        candidates.append((score, "카운터 마스터", "빈틈을 읽는 반격", "상대의 공격 뒤 빈틈을 읽고 반격으로 흐름을 가져가는 유형입니다.", [f"카운터 {counters}회"]))

    power_signals = sum((big45 >= 4, big55 >= 2, knockdowns > 0, average >= 32.0))
    if power_signals >= 2:
        power_rate = big45 / landed_base
        score = 56 + min(18, power_rate * 40) + min(12, big55 * 4) + min(15, knockdowns * 5) + min(7, max(0.0, average - 30.0) * 0.7)
        candidates.append((score, "슬러거", "한 방으로 판을 바꾸는 힘", "강한 정타와 다운 위협으로 한순간에 경기 흐름을 바꾸는 유형입니다.", [f"45 이상 강타 {big45}회", f"다운 {knockdowns}회"]))

    if combo >= 3:
        score = 59 + min(30, combo * 6) + min(8, stuns * 2)
        candidates.append((score, "연타 장인", "끊기지 않는 연속 공격", "첫 타 이후 공격을 자연스럽게 연결해 상대에게 대응할 틈을 주지 않는 유형입니다.", [f"최대 {combo}연타"]))

    if attempts >= max(1, int(min_attempts)) and accuracy >= 58.0:
        score = 58 + min(28, (accuracy - 55.0) * 1.2) + min(6, landed / 8.0)
        candidates.append((score, "정밀 타격가", "낭비를 줄인 정확한 운영", "무리하게 손을 내기보다 높은 적중률로 효율적인 공격을 만드는 유형입니다.", [f"적중률 {int(round(accuracy))}%"]))

    opponent_attempts = _count(opponent.get("thrown") or opponent.get("activity"))
    if attempts >= max(45, int(min_attempts)) and (opponent_attempts <= 0 or attempts >= opponent_attempts * 1.12):
        volume_edge = attempts / max(1, opponent_attempts) if opponent_attempts > 0 else 1.25
        score = 54 + min(24, attempts / 6.0) + min(14, max(0.0, volume_edge - 1.0) * 35)
        candidates.append((score, "압박형 파이터", "공격량으로 주도권 장악", "꾸준한 공격량으로 상대의 선택지를 줄이고 경기를 앞으로 끌고 가는 유형입니다.", [f"공격 시도 {attempts}회"]))

    if targets["total"] >= 4 and targets["body"] / max(1, targets["total"]) >= 0.45:
        body_rate = targets["body"] / max(1, targets["total"])
        score = 58 + min(18, max(0.0, body_rate - 0.45) * 40) + min(18, targets["body"] * 1.5)
        candidates.append((score, "바디 헌터", "몸통을 무너뜨리는 집요함", "명치와 간을 반복해서 공략하며 상대의 움직임과 체력을 깎는 유형입니다.", [f"몸통 급소 {targets['body']}회"]))

    if targets["total"] >= 5 and targets["head"] / max(1, targets["total"]) >= 0.55:
        head_rate = targets["head"] / max(1, targets["total"])
        score = 57 + min(18, max(0.0, head_rate - 0.55) * 40) + min(18, targets["head"] * 1.3) + min(6, stuns * 2)
        candidates.append((score, "헤드 헌터", "얼굴 급소 집중 공략", "턱과 관자놀이 등 얼굴 급소를 집요하게 노리는 유형입니다.", [f"얼굴 급소 {targets['head']}회"]))

    jab_share = punch_counts.get("jab", 0) / max(1, sum(punch_counts.values()))
    if punch_counts.get("jab", 0) >= 6 and jab_share >= 0.38:
        score = 55 + min(22, max(0.0, jab_share - 0.30) * 55) + min(12, punch_counts.get("jab", 0) * 0.8)
        candidates.append((score, "잽 스페셜리스트", "앞손으로 만드는 거리", "잽으로 거리와 박자를 선점한 뒤 다음 공격의 길을 여는 유형입니다.", [f"잽 비중 {int(round(jab_share * 100))}%"]))

    if not candidates:
        return {
            "label": "균형형 파이터",
            "signature": "상황에 맞춘 다재다능함",
            "description": "특정 공격 하나에 치우치지 않고 상황에 따라 운영을 바꾸는 유형입니다.",
            "confidence": 55,
            "evidence": [f"유효타 {landed}회"],
        }

    score, label, signature, description, evidence = max(candidates, key=lambda item: item[0])
    if score < 63:
        return {
            "label": "균형형 파이터",
            "signature": "상황에 맞춘 다재다능함",
            "description": "특정 공격 하나에 치우치지 않고 상황에 따라 운영을 바꾸는 유형입니다.",
            "confidence": max(55, int(round(score))),
            "evidence": [f"유효타 {landed}회"],
        }
    return {
        "label": label,
        "signature": signature,
        "description": description,
        "confidence": max(1, min(99, int(round(score)))),
        "evidence": evidence,
    }


def _style_label(side: dict) -> str:
    return str(dict(side.get("fightStyle") or {}).get("label") or "균형형 파이터")


def _official_rounds(payload: dict) -> List[dict]:
    scorecard = dict(payload.get("officialScorecard") or payload.get("scorecard") or {})
    rows = [dict(row or {}) for row in list(scorecard.get("rounds") or [])]
    return sorted(rows, key=lambda row: _count(row.get("round")))


def _round_winner(row: dict) -> str:
    blue = _count(row.get("blue_score"))
    red = _count(row.get("red_score"))
    return "blue" if blue > red else "red" if red > blue else "draw"


def _match_arc_line(payload: dict, names: Dict[str, str], winner: str) -> str:
    rows = _official_rounds(payload)
    winners = [_round_winner(row) for row in rows]
    decided = [side for side in winners if side in ("blue", "red")]
    if len(decided) < 2:
        return ""
    if winner in ("blue", "red") and decided[0] != winner and winner in decided[1:]:
        return f"초반에는 {names[decided[0]]}가 앞섰지만, {names[winner]}가 이후 라운드에서 전술을 바꾸며 흐름을 뒤집었습니다."
    if winner in ("blue", "red") and all(side == winner for side in decided):
        return f"{names[winner]}가 첫 라운드부터 주도권을 잡고 마지막까지 경기의 방향을 내주지 않았습니다."
    if any(decided[index] != decided[index - 1] for index in range(1, len(decided))):
        return "라운드마다 주도권이 바뀌었고, 마지막까지 한 번의 교전이 결과를 바꿀 수 있는 경기였습니다."
    return ""


def _turning_point_line(payload: dict, names: Dict[str, str]) -> str:
    rows = _official_rounds(payload)
    if not rows:
        return ""

    def importance(row: dict) -> float:
        blue_dealt = _number(row.get("red_damage_taken"))
        red_dealt = _number(row.get("blue_damage_taken"))
        knockdowns = _count(row.get("blue_kds")) + _count(row.get("red_kds"))
        score_gap = abs(_count(row.get("blue_score")) - _count(row.get("red_score")))
        return knockdowns * 120.0 + abs(blue_dealt - red_dealt) + score_gap * 12.0

    row = max(rows, key=importance)
    round_no = max(1, _count(row.get("round")))
    blue_downs = _count(row.get("blue_kds"))
    red_downs = _count(row.get("red_kds"))
    if blue_downs != red_downs:
        attacker = "red" if blue_downs > red_downs else "blue"
        return f"가장 큰 전환점은 {round_no}라운드, {names[attacker]}가 만든 다운 장면이었습니다."
    blue_dealt = _number(row.get("red_damage_taken"))
    red_dealt = _number(row.get("blue_damage_taken"))
    if abs(blue_dealt - red_dealt) >= 80.0:
        side = "blue" if blue_dealt > red_dealt else "red"
        return f"승부의 흐름은 {round_no}라운드에 {names[side]}가 더 선명한 유효타를 쌓으면서 크게 움직였습니다."
    return ""


def _decisive_weapon_line(blue: dict, red: dict, names: Dict[str, str], winner: str) -> str:
    if winner not in ("blue", "red"):
        return ""
    loser = "red" if winner == "blue" else "blue"
    won = blue if winner == "blue" else red
    lost = red if winner == "blue" else blue
    winner_name = names[winner]
    winner_counters = _count(won.get("counterHits"))
    loser_counters = _count(lost.get("counterHits"))
    if winner_counters >= 3 and winner_counters >= loser_counters + 2:
        return f"{winner_name}는 상대가 공격을 마친 뒤의 빈틈을 놓치지 않았고, 카운터 타이밍으로 중요한 교전을 가져갔습니다."
    winner_kd = _count(won.get("knockdowns"))
    loser_kd = _count(lost.get("knockdowns"))
    if winner_kd > loser_kd:
        return f"{winner_name}는 단순히 많이 맞힌 것이 아니라, 승부를 바꾸는 강한 정타로 다운까지 만들어냈습니다."
    winner_big = _count(won.get("bigHits")) + _count(won.get("powerHits55"))
    loser_big = _count(lost.get("bigHits")) + _count(lost.get("powerHits55"))
    if winner_big >= loser_big + 2:
        return f"{winner_name}는 강타의 질에서 앞섰고, 중요한 순간마다 더 무거운 유효타를 남겼습니다."
    winner_accuracy = _number(won.get("accuracy"), -1.0)
    loser_accuracy = _number(lost.get("accuracy"), -1.0)
    if winner_accuracy >= 0 and loser_accuracy >= 0 and winner_accuracy >= loser_accuracy + 8.0:
        return f"{winner_name}는 불필요한 공격을 줄이고 더 정확한 선택으로 경기 효율에서 차이를 만들었습니다."
    winner_damage = _number(won.get("damage"))
    loser_damage = _number(lost.get("damage"))
    if winner_damage > loser_damage:
        return f"{winner_name}는 한 장면에만 의존하지 않고 유효타를 꾸준히 누적해 경기의 무게를 가져왔습니다."
    return f"{winner_name}는 결정적인 교전에서 더 침착하게 자기 공격을 완성했습니다."


def build_match_commentary(report: Optional[dict]) -> str:
    """Create a Korean match story instead of reading report numbers aloud."""
    payload = dict(report or {})
    blue = dict(payload.get("blue") or {})
    red = dict(payload.get("red") or {})
    winner = str(payload.get("winner") or "").lower().strip()
    method = str(payload.get("resultMethod") or dict(payload.get("matchResult") or {}).get("method") or "")
    blue_name = str(blue.get("name") or "블루 코너")
    red_name = str(red.get("name") or "레드 코너")
    names = {"blue": blue_name, "red": red_name}
    lines: List[str] = []

    if winner in ("blue", "red"):
        winner_name = names[winner]
        method_token = _normalized_token(method)
        if "tko" in method_token or "technicalknockout" in method_token:
            lines.append(f"{winner_name}가 끝까지 압박을 이어가며 테크니컬 녹아웃으로 경기를 마무리합니다.")
        elif "knockout" in method_token or method_token == "ko":
            lines.append(f"{winner_name}가 결정적인 한 방으로 녹아웃 승리를 완성합니다.")
        else:
            lines.append(f"{winner_name}가 라운드 운영에서 앞서 판정승을 가져갑니다.")
    elif winner == "draw":
        lines.append("끝까지 우열을 가리지 못한 치열한 승부가 무승부로 마무리됩니다.")
    else:
        lines.append("치열했던 경기가 마무리되고 양 선수의 흐름을 정리합니다.")

    arc = _match_arc_line(payload, names, winner)
    if arc:
        lines.append(arc)
    turning_point = _turning_point_line(payload, names)
    if turning_point:
        lines.append(turning_point)
    weapon = _decisive_weapon_line(blue, red, names, winner)
    if weapon:
        lines.append(weapon)

    blue_style = _style_label(blue)
    red_style = _style_label(red)
    if blue_style != "분석 중" and red_style != "분석 중":
        lines.append(f"스타일로 보면 {blue_name}는 {blue_style}, {red_name}는 {red_style}의 색깔을 뚜렷하게 보여줬습니다.")

    if winner in ("blue", "red"):
        loser = "red" if winner == "blue" else "blue"
        winner_style = _style_label(payload.get(winner) or {})
        if winner_style != "분석 중":
            lines.append(f"결국 {names[winner]}가 자신의 {winner_style} 강점을 더 오래 유지했고, {names[loser]}는 그 흐름을 끊을 해답을 만들지 못했습니다.")
        else:
            lines.append(f"결국 {names[winner]}가 결정적인 순간의 집중력을 끝까지 유지하며 승리를 완성했습니다.")
    else:
        lines.append("서로 다른 강점이 맞물리면서 한쪽이 끝까지 흐름을 독점하지 못한 경기였습니다.")

    return " ".join(line for line in lines if line).strip()
