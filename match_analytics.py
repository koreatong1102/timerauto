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


def _korean_final_consonant_index(text: Any) -> int:
    """Return the Hangul final-consonant index used for Korean particles."""
    value = str(text or "").strip()
    if not value:
        return 0
    code = ord(value[-1])
    if 0xAC00 <= code <= 0xD7A3:
        return (code - 0xAC00) % 28
    # Common digit pronunciations with a final-consonant sound.
    if value[-1].isdigit():
        return 1 if value[-1] in "013678" else 0
    # Roman/other IDs use the no-final-consonant form, which is the least
    # awkward TTS fallback and preserves the previous behaviour for them.
    return 0


def _josa(text: Any, pair: str) -> str:
    """Append the grammatically correct Korean particle to a display name."""
    value = str(text or "").strip()
    if not value:
        return ""
    final_index = _korean_final_consonant_index(value)
    has_batchim = final_index > 0
    choices = {
        "은/는": ("은", "는"),
        "이/가": ("이", "가"),
        "을/를": ("을", "를"),
        "과/와": ("과", "와"),
        "와/과": ("과", "와"),
    }
    if pair == "으로/로":
        return value + ("으로" if has_batchim and final_index != 8 else "로")
    suffixes = choices.get(str(pair or "").strip())
    return value + (suffixes[0] if suffixes and has_batchim else suffixes[1] if suffixes else str(pair or ""))


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


def _health_percent(stats: dict) -> float:
    """Read the preserved actual-health/SP gauge from a report payload."""
    data = dict(stats or {})
    for key in ("actualHealthPct", "staminaPct"):
        actual = _number(data.get(key), -1.0)
        if actual >= 0.0:
            return max(0.0, min(100.0, actual))
    # ``healthPct`` is the yellow in-game health gauge.  Keep it only as a
    # compatibility fallback for old archives that predate SP persistence.
    direct = _number(data.get("healthPct"), -1.0)
    if direct >= 0.0:
        return max(0.0, min(100.0, direct))
    punishment = dict(data.get("punishment") or {})
    ratio = _number(punishment.get("hp_ratio"), -1.0)
    if ratio >= 0.0:
        return max(0.0, min(100.0, ratio * 100.0))
    long_value = _number(punishment.get("long"), -1.0)
    return max(0.0, min(100.0, 100.0 - long_value)) if long_value >= 0.0 else 50.0


def _operation_medal(
    *, health: float, opponent_health: float, counters: int, attempts: int,
    opponent_attempts: int, knockdowns: int, stuns: int,
) -> Dict[str, Any]:
    """Turn actual-health management into one readable broadcast honor."""
    diff = health - opponent_health
    pressure_advantage = attempts - opponent_attempts
    decisive = knockdowns > 0 or stuns >= 2
    if counters >= 12 and diff >= 12.0:
        return {"code": "the_read", "label": "THE READ", "detail": "카운터 우세와 실제체력 보존을 함께 만든 읽기 싸움", "healthDiff": round(diff, 1)}
    if diff >= 20.0:
        return {"code": "iron_guard", "label": "IRON GUARD", "detail": "상대보다 훨씬 덜 맞으며 실제체력을 지킨 운영", "healthDiff": round(diff, 1)}
    if pressure_advantage >= 35 and diff >= 10.0:
        return {"code": "safe_pressure", "label": "SAFE PRESSURE", "detail": "공격량 우세를 만들면서도 실제체력을 보존한 압박", "healthDiff": round(diff, 1)}
    if health <= 45.0 and diff >= 8.0:
        return {"code": "survivor", "label": "SURVIVOR", "detail": "버거운 실제체력 상황에서도 끝까지 흐름을 지킨 생존 운영", "healthDiff": round(diff, 1)}
    if diff <= -15.0 and decisive:
        return {"code": "war_machine", "label": "WAR MACHINE", "detail": "소모전 속에서도 결정적인 결과를 만들어낸 난전 지배", "healthDiff": round(diff, 1)}
    if diff >= 8.0:
        return {"code": "match_control", "label": "MATCH CONTROL", "detail": "불필요한 소모를 줄이며 실제체력 우위를 만든 운영", "healthDiff": round(diff, 1)}
    return {"code": "even_ground", "label": "EVEN GROUND", "detail": "치열한 공방 속에서 서로 비슷한 실제체력으로 맞선 운영", "healthDiff": round(diff, 1)}


def _progress(value: Any, start: float, cap: float) -> float:
    """Return a stable 0..1 absolute-threshold progress value."""
    lower = float(start)
    upper = max(lower + 0.0001, float(cap))
    return max(0.0, min(1.0, (_number(value) - lower) / (upper - lower)))


def _style_mastery(
    label: str,
    *,
    rounds: int,
    attempts: int,
    landed: int,
    accuracy: float,
    counters: int,
    big45: int,
    big55: int,
    knockdowns: int,
    stuns: int,
    combo: int,
    opponent_attempts: int,
    punch_counts: Dict[str, int],
) -> tuple[float, Dict[str, float]]:
    """Score the selected style without reusing its selection score.

    Selection answers *which* style best describes the fighter.  Mastery is
    an absolute 0..100 strength scale for that specific style.  Every formula
    uses a rate plus a per-round sustain signal where applicable, so a long
    match cannot collapse elite and merely-good performances into one level.
    """
    rounds = max(1, int(rounds or 1))
    landed_base = max(1, int(landed or 0))
    counter_rate = float(counters) / landed_base
    power_rate = float(big45) / landed_base
    pressure_ratio = float(attempts) / max(1, int(opponent_attempts or 0))
    counter_per_round = float(counters) / rounds
    big55_per_round = float(big55) / rounds
    kd_per_round = float(knockdowns) / rounds
    attempts_per_round = float(attempts) / rounds
    stuns_per_round = float(stuns) / rounds
    landed_per_round = float(landed) / rounds
    punch_variety = sum(1 for value in punch_counts.values() if int(value or 0) >= 6)

    if label == "카운터 마스터":
        parts = {
            "counterRate": 50.0 * _progress(counter_rate, 0.28, 0.44),
            "counterSustain": 30.0 * _progress(counter_per_round, 5.0, 22.0),
        }
        return 20.0 + sum(parts.values()), parts
    if label == "슬러거":
        parts = {
            "powerRate": 35.0 * _progress(power_rate, 0.22, 0.45),
            "powerSustain": 25.0 * _progress(big55_per_round, 1.5, 9.0),
            "knockdownRate": 20.0 * _progress(kd_per_round, 0.2, 2.0),
        }
        return 20.0 + sum(parts.values()), parts
    if label == "압박형 파이터":
        parts = {
            "activitySustain": 45.0 * _progress(attempts_per_round, 50.0, 115.0),
            "pressureAdvantage": 35.0 * _progress(pressure_ratio, 1.10, 1.55),
        }
        return 20.0 + sum(parts.values()), parts
    if label == "정밀 타격형":
        parts = {
            "accuracy": 45.0 * _progress(accuracy, 65.0, 85.0),
            "precisionSustain": 35.0 * _progress(landed_per_round, 16.0, 55.0),
        }
        return 20.0 + sum(parts.values()), parts
    if label == "콤보 장인":
        parts = {
            "comboDepth": 60.0 * _progress(combo, 5.0, 12.0),
            "stunSustain": 20.0 * _progress(stuns_per_round, 0.0, 2.0),
        }
        return 20.0 + sum(parts.values()), parts

    # "균형형 파이터" is a real neutral identity, not a failure state.  Its
    # mastery is breadth and sustained clean work, never damage inflation.
    parts = {
        "cleanWork": 35.0 * _progress(landed_per_round, 10.0, 55.0),
        "accuracy": 25.0 * _progress(accuracy, 45.0, 75.0),
        "variety": 20.0 * _progress(punch_variety, 1.0, 4.0),
    }
    return 15.0 + sum(parts.values()), parts


def analyze_fight_style(
    stats: Optional[dict],
    opponent_stats: Optional[dict] = None,
    *,
    min_attempts: int = 20,
    min_landed: int = 10,
) -> Dict[str, Any]:
    """Classify one fighter into non-overlapping broadcast style roles.

    The result intentionally separates a main identity from attack, defense and
    fight-flow chips.  That prevents five near-identical power labels from
    appearing together in the final report.
    """
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
            "tier": "",
            "chips": [],
            "styles": [],
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
    opponent_attempts = _count(opponent.get("thrown") or opponent.get("activity"))
    rounds_observed = max(
        1,
        _count(data.get("roundsObserved") or data.get("roundCount") or data.get("roundsPlayed") or 1),
    )
    health = _health_percent(data)
    opponent_health = _health_percent(opponent)
    defense = dict(data.get("defenseMetrics") or {})
    opponent_misses = _count(defense.get("opponentMisses", opponent.get("misses")))
    low_damage_defenses = _count(defense.get("lowDamageDefenses"))
    return_counters = _count(defense.get("returnCounters"))
    return_power = _count(defense.get("returnPowerHits"))
    heavy_received = _count(defense.get("heavyReceived"))
    defense_base = max(1, opponent_attempts)
    evade_rate = opponent_misses / defense_base
    soft_defense_rate = low_damage_defenses / max(1, _count(opponent.get("landed")))

    # Tuple: score, label, signature, description, evidence.
    main: List[tuple] = []
    counter_rate = counters / landed_base
    # Fixed absolute v1 cut-lines calibrated from the completed-match archive.
    # Median counter rate was 22.8%, so the old 16% gate classified ordinary
    # exchanges as counter mastery. A main identity now requires 35 counters
    # and 28% of all landed punches.
    if counters >= 35 and counter_rate >= 0.28:
        main.append((50 + min(32, (counter_rate - 0.28) * 600) + min(18, (counters - 35) * 0.45), "카운터 마스터", "빈틈을 읽는 반격", "상대의 공격 뒤 빈틈을 읽고 반격으로 흐름을 가져가는 유형입니다.", [f"카운터 {counters}회", f"카운터율 {int(round(counter_rate * 100))}%"]))
    power_signals = sum((big45 >= 4, big55 >= 2, knockdowns > 0, average >= 32.0))
    power_rate = big45 / landed_base
    if power_signals >= 2 and power_rate >= 0.22 and (big55 >= 8 or knockdowns >= 2):
        main.append((50 + min(28, (power_rate - 0.22) * 550) + min(14, (big55 - 8) * 1.5) + min(12, knockdowns * 4), "슬러거", "한 방으로 판을 바꾸는 힘", "강한 정타와 다운 위협으로 한순간에 경기 흐름을 바꾸는 유형입니다.", [f"45 이상 강타율 {int(round(power_rate * 100))}%", f"다운 {knockdowns}회"]))
    pressure_ratio = attempts / max(1, opponent_attempts)
    if attempts >= 210 and (opponent_attempts <= 0 or pressure_ratio >= 1.10):
        main.append((50 + min(28, (attempts - 210) * 0.20) + min(14, max(0.0, pressure_ratio - 1.10) * 40), "압박형 파이터", "공격량으로 주도권 장악", "꾸준한 공격량으로 상대의 선택지를 줄이고 경기를 앞으로 끌고 가는 유형입니다.", [f"공격 시도 {attempts}회"]))
    opponent_accuracy = _number(opponent.get("accuracy"), -1.0)
    precision_advantage = accuracy - opponent_accuracy if opponent_accuracy >= 0 else accuracy - 50.0
    if attempts >= 150 and accuracy >= 65.0 and (opponent_accuracy < 0 or precision_advantage >= 7.0):
        main.append((50 + min(28, (accuracy - 65.0) * 2.0) + min(14, max(0.0, precision_advantage - 7.0) * 1.4), "정밀 타격가", "낭비를 줄인 정확한 운영", "무리하게 손을 내기보다 높은 적중률로 효율적인 공격을 만드는 유형입니다.", [f"적중률 {int(round(accuracy))}%"]))
    if combo >= 5:
        main.append((50 + min(36, (combo - 5) * 12) + min(12, stuns * 3), "연타 장인", "끊기지 않는 연속 공격", "첫 타 이후 공격을 자연스럽게 연결해 상대에게 대응할 틈을 주지 않는 유형입니다.", [f"최대 {combo}연타"]))

    attack: List[tuple] = []
    if targets["total"] >= 5 and targets["head"] / max(1, targets["total"]) >= 0.55:
        attack.append((57 + min(20, targets["head"] * 1.7) + min(8, stuns * 2), "헤드 헌터", "얼굴 급소 집중 공략", "턱과 관자놀이 등 얼굴 급소를 집요하게 노리는 유형입니다.", [f"얼굴 급소 {targets['head']}회"]))
    if targets["total"] >= 4 and targets["body"] / max(1, targets["total"]) >= 0.45:
        attack.append((58 + min(20, targets["body"] * 1.7), "바디 헌터", "몸통을 무너뜨리는 집요함", "명치와 간을 반복해서 공략하며 상대의 움직임과 체력을 깎는 유형입니다.", [f"몸통 급소 {targets['body']}회"]))
    total_punches = max(1, sum(punch_counts.values()))
    punch_styles = (("jab", "잽 스페셜리스트"), ("hook", "훅 파이터"), ("over", "오버핸드 헌터"))
    for key, label in punch_styles:
        count = punch_counts.get(key, 0)
        share = count / total_punches
        if count >= 6 and share >= 0.30:
            attack.append((54 + min(28, max(0.0, share - 0.25) * 70) + min(12, count * 0.8), label, "주무기 집중", "한 종류의 공격을 반복해서 성공시킨 유형입니다.", [f"{label} 비중 {int(round(share * 100))}%"]))

    defense_styles: List[tuple] = []
    if opponent_attempts >= 25 and evade_rate >= 0.40:
        defense_styles.append((58 + min(28, (evade_rate - 0.35) * 70) + min(10, opponent_misses / 3.0), "회피 장인", "상대 공격을 흘리는 운영", "상대 시도 대비 유효타를 허용하지 않아 공격을 비워내는 유형입니다.", [f"미적중 유도 {opponent_misses}회"]))
    if opponent_attempts >= 20 and soft_defense_rate >= 0.35 and heavy_received <= max(2, opponent_attempts // 18):
        defense_styles.append((56 + min(26, (soft_defense_rate - 0.25) * 70) + min(8, low_damage_defenses), "철벽 방어", "큰 피해를 억제하는 수비", "낮은 피해로 버티며 큰 유효타를 최소화한 유형입니다.", [f"저피해 방어 {low_damage_defenses}회"]))
    if (return_counters + return_power) >= 3:
        defense_styles.append((60 + min(28, (return_counters + return_power) * 5), "유도 반격형", "방어 뒤 즉시 되받아치기", "상대 공격을 흘리거나 막은 뒤 빠르게 반격을 연결한 유형입니다.", [f"방어 뒤 반격 {return_counters + return_power}회"]))

    flow: List[tuple] = []
    if knockdowns > 0:
        flow.append((62 + min(24, knockdowns * 9) + min(10, big55 * 3), "다운 마무리", "결정타로 흐름 완성", "결정적인 다운으로 우세를 승부로 연결한 유형입니다.", [f"다운 {knockdowns}회"]))
    trend = dict(data.get("roundTrend") or {})
    early_damage = _number(trend.get("earlyDamage"))
    late_damage = _number(trend.get("lateDamage"))
    early_landed = _count(trend.get("earlyLanded"))
    late_landed = _count(trend.get("lateLanded"))
    if early_damage > 0 and late_damage >= early_damage * 1.25 and late_landed >= early_landed:
        flow.append((59 + min(22, (late_damage / max(1.0, early_damage) - 1.0) * 38), "후반 집중형", "후반으로 갈수록 살아난 공격", "경기 후반으로 갈수록 유효타와 데미지를 끌어올린 유형입니다.", ["후반 공격 상승"]))
    if attempts <= max(1, opponent_attempts) and accuracy >= max(56.0, _number(opponent.get("accuracy"), 0.0) + 6.0) and average >= _number(opponent.get("averageDamage"), 0.0):
        flow.append((57 + min(22, accuracy - 52.0) + min(12, max(0.0, average - 20.0)), "효율형 파이터", "적은 낭비로 만든 우세", "공격 수를 낭비하지 않고 정확한 유효타로 차이를 만든 유형입니다.", [f"적중률 {int(round(accuracy))}%"]))
    if attempts >= max(55, int(min_attempts) * 2) and accuracy < 52.0:
        flow.append((54 + min(20, attempts / 7.0) + min(12, 52.0 - accuracy), "난타형 파이터", "끊임없이 이어진 공방", "공격량으로 전장을 넓히며 난전의 흐름을 만든 유형입니다.", [f"공격 시도 {attempts}회"]))

    main_ranked = sorted(main, key=lambda item: item[0], reverse=True)
    if main_ranked:
        primary = main_ranked[0]
    else:
        primary = (55.0, "균형형 파이터", "상황에 맞춘 다재다능함", "특정 공격 하나에 치우치지 않고 상황에 따라 운영을 바꾸는 유형입니다.", [f"유효타 {landed}회"])
    supplements: List[tuple] = []
    for bucket, limit in ((attack, 2), (defense_styles, 1), (flow, 1)):
        selected = 0
        for item in sorted(bucket, key=lambda candidate: candidate[0], reverse=True):
            if item[0] < 63 or item[1] == primary[1] or any(old[1] == item[1] for old in supplements):
                continue
            supplements.append(item)
            selected += 1
            if selected >= limit:
                break
    chips = [str(item[1]) for item in supplements[:4]]
    score, label, signature, description, evidence = primary
    # Keep overall match performance as a separate four-part diagnostic.
    # Raw damage has the smallest weight because it is comparatively easy to
    # inflate in VR; technique and actual-health management matter more.
    technique_score = min(100.0, max(0.0,
        min(40.0, counter_rate * 100.0) * 1.15
        + min(24.0, max(0, combo - 1) * 5.0)
        + min(20.0, max(0.0, accuracy - 45.0) * 0.45)
        + min(16.0, evade_rate * 30.0)
    ))
    result_score = min(100.0, max(0.0,
        knockdowns * 24.0 + stuns * 9.0 + (20.0 if bool(data.get("isWinner", False)) else 0.0)
    ))
    operation_score = min(100.0, max(0.0, 50.0 + (health - opponent_health) * 2.0 + (health - 55.0) * 0.25))
    damage_share = landed_damage / max(1.0, landed_damage + _number(opponent.get("landedDamage"), _number(opponent.get("damage"))))
    damage_score = min(100.0, max(0.0, damage_share * 100.0))
    performance_score = (
        technique_score * 0.40
        + result_score * 0.35
        + operation_score * 0.15
        + damage_score * 0.10
    )
    performance_level = max(1, min(10, int(round(performance_score / 10.0))))
    # Do not reuse the role-selection score for the displayed tier.  The old
    # formulas capped quickly (for example counter rate at roughly 33%), which
    # compressed a 121:69 counter match into only one tier.  Mastery keeps the
    # same absolute rules for everyone, but measures each chosen role with its
    # own rate and sustained-per-round curve.
    style_strength, mastery_parts = _style_mastery(
        label,
        rounds=rounds_observed,
        attempts=attempts,
        landed=landed,
        accuracy=accuracy,
        counters=counters,
        big45=big45,
        big55=big55,
        knockdowns=knockdowns,
        stuns=stuns,
        combo=combo,
        opponent_attempts=opponent_attempts,
        punch_counts=punch_counts,
    )
    style_strength = max(0.0, min(100.0, float(style_strength)))
    level = max(1, min(10, 1 + int(round(style_strength * 9.0 / 100.0))))
    tier = f"레벨 {level}"
    operation_medal = _operation_medal(
        health=health,
        opponent_health=opponent_health,
        counters=counters,
        attempts=attempts,
        opponent_attempts=opponent_attempts,
        knockdowns=knockdowns,
        stuns=stuns,
    )
    return {
        "label": label,
        "signature": signature,
        "description": description,
        "confidence": max(1, min(99, int(round(score)))),
        "level": level,
        "styleScore": round(float(score), 1),
        "selectionScore": round(float(score), 1),
        "levelScore": round(style_strength, 1),
        "levelBreakdown": {
            "styleStrength": round(style_strength, 1),
            "mastery": round(style_strength, 1),
            "roundsObserved": rounds_observed,
            "components": {key: round(value, 1) for key, value in mastery_parts.items()},
        },
        "performanceLevel": performance_level,
        "performanceScore": round(performance_score, 1),
        "performanceBreakdown": {
            "technique": round(technique_score, 1),
            "result": round(result_score, 1),
            "operation": round(operation_score, 1),
            "damage": round(damage_score, 1),
        },
        "operationMedal": operation_medal,
        "evidence": evidence,
        "tier": tier,
        "chips": chips,
        "styles": [{"label": label, "tier": tier, "role": "main"}] + [
            {"label": item[1], "tier": "", "role": "support"} for item in supplements[:4]
        ],
        "secondaryLabel": chips[0] if len(chips) >= 1 else "",
        "secondarySignature": supplements[0][2] if len(supplements) >= 1 else "",
        "tertiaryLabel": chips[1] if len(chips) >= 2 else "",
        "tertiarySignature": supplements[1][2] if len(supplements) >= 2 else "",
    }


def analyze_round_approach(stats: Optional[dict], opponent_stats: Optional[dict] = None) -> Dict[str, Any]:
    """Describe one round as method, result and condition.

    A knockdown is a result, not a permanent fighting style.  Older builds put
    knockdowns, counters, pressure and punch preference in one winner-takes-all
    score.  Since a single knockdown started above every normal method score,
    nearly every break card became ``다운 마무리``.  Keep those dimensions
    separate so the card can say *how* the fighter operated, *what* it produced
    and *what condition* the fighter finished the round in.
    """
    data = dict(stats or {})
    opponent = dict(opponent_stats or {})
    attempts = _count(data.get("thrown") or data.get("activity"))
    landed = _count(data.get("landed"))
    opponent_attempts = _count(opponent.get("thrown") or opponent.get("activity"))
    opponent_landed = _count(opponent.get("landed"))
    accuracy = _number(data.get("accuracy"), -1.0)
    if accuracy < 0.0 and attempts:
        accuracy = landed / attempts * 100.0
    opponent_accuracy = _number(opponent.get("accuracy"), -1.0)
    if opponent_accuracy < 0.0 and opponent_attempts:
        opponent_accuracy = opponent_landed / opponent_attempts * 100.0
    counters = _count(data.get("counterHits"))
    opponent_counters = _count(opponent.get("counterHits"))
    knockdowns = _count(data.get("knockdowns"))
    opponent_knockdowns = _count(opponent.get("knockdowns"))
    stuns = _count(data.get("stuns"))
    opponent_stuns = _count(opponent.get("stuns"))
    combo = _count(data.get("maxComboHits"))
    opponent_combo = _count(opponent.get("maxComboHits"))
    big45 = _count(data.get("bigHits"))
    opponent_big45 = _count(opponent.get("bigHits"))
    big55 = _count(data.get("powerHits55"))
    average = _number(data.get("averageDamage", data.get("averageHitDamage")))
    punches = _punch_count_map(data)
    total_punches = max(1, sum(punches.values()))
    defense = dict(data.get("defenseMetrics") or {})
    opponent_misses = _count(defense.get("opponentMisses", opponent.get("misses")))
    candidates: List[tuple] = []

    counter_rate = counters / max(1, landed)
    opponent_counter_rate = opponent_counters / max(1, opponent_landed)
    counter_advantage = counter_rate - opponent_counter_rate
    if (
        counters >= 7
        and counter_rate >= 0.20
        and (counter_advantage >= 0.04 or counters >= opponent_counters + 4)
    ):
        candidates.append((
            58
            + min(16.0, max(0.0, counter_rate - 0.20) * 90.0)
            + min(14.0, max(0, counters - 7) * 0.8)
            + min(10.0, max(0.0, counter_advantage) * 80.0),
            "카운터 운영",
            "상대 진입에 맞춘 반격으로 교전의 주도권을 만들었습니다.",
            f"카운터 {counters}회 · {int(round(counter_rate * 100))}%",
        ))

    if combo >= 4 and (combo > opponent_combo or combo >= 6):
        candidates.append((
            58 + min(25.0, max(0, combo - 3) * 5.0),
            "연결 공격",
            "첫 타 이후 후속타를 자연스럽게 이어갔습니다.",
            f"최대 {combo} HIT",
        ))

    for key, label in (("jab", "잽 주도"), ("hook", "훅 집중"), ("over", "오버핸드 집중")):
        count = punches.get(key, 0)
        share = count / total_punches
        if count >= 8 and share >= 0.34:
            candidates.append((
                55 + min(22.0, max(0.0, share - 0.34) * 75.0) + min(12.0, count / 4.0),
                label,
                "주무기를 반복해서 성공시키며 라운드의 공격 형태를 만들었습니다.",
                f"{label.split()[0]} 적중 {count}회 · {int(round(share * 100))}%",
            ))

    pressure_ratio = attempts / max(1, opponent_attempts)
    if attempts >= 45 and pressure_ratio >= 1.20 and attempts >= opponent_attempts + 12:
        candidates.append((
            56
            + min(22.0, max(0.0, pressure_ratio - 1.20) * 45.0)
            + min(12.0, max(0, attempts - 45) / 9.0),
            "공세 주도",
            "더 많은 공격 시도로 상대의 선택지를 줄였습니다.",
            f"공격 시도 {attempts}회 · 상대 {opponent_attempts}회",
        ))
    if landed >= 16 and accuracy >= 52.0 and accuracy >= opponent_accuracy + 8.0:
        candidates.append((
            56
            + min(22.0, accuracy - 52.0)
            + min(12.0, max(0.0, accuracy - opponent_accuracy - 8.0)),
            "정확도 우세",
            "공격 낭비를 줄이고 유효타의 효율에서 차이를 만들었습니다.",
            f"적중률 {int(round(accuracy))}% · 상대 {int(round(opponent_accuracy))}%",
        ))
    evade_rate = opponent_misses / max(1, opponent_attempts)
    if opponent_attempts >= 35 and evade_rate >= 0.38:
        candidates.append((
            56 + min(28.0, max(0.0, evade_rate - 0.38) * 80.0),
            "회피 운영",
            "상대 공격을 비워내며 위험한 교전을 줄였습니다.",
            f"상대 미적중 {opponent_misses}회",
        ))

    power_rate = big45 / max(1, landed)
    if (
        big45 >= 5
        and power_rate >= 0.12
        and (big45 >= opponent_big45 + 2 or big55 >= 2 or average >= 35.0)
    ):
        candidates.append((
            56
            + min(18.0, max(0.0, power_rate - 0.12) * 90.0)
            + min(12.0, max(0, big45 - 5) * 1.2)
            + min(10.0, big55 * 2.0),
            "강타 주도",
            "강한 유효타의 비중을 높여 교전의 무게를 가져왔습니다.",
            f"45 이상 {big45}회 · 55 이상 {big55}회",
        ))

    ranked = sorted(candidates, key=lambda item: item[0], reverse=True)
    if ranked:
        score, label, description, evidence_text = ranked[0]
        support_labels = [str(item[1]) for item in ranked[1:3] if float(score) - float(item[0]) <= 8.0]
        if support_labels and float(score) - float(ranked[1][0]) < 5.0:
            label = "혼합 운영"
            description = "서로 다른 두 가지 운영이 비슷한 비중으로 나타난 라운드입니다."
            evidence_text = f"{ranked[0][1]} · {ranked[1][1]}"
    elif attempts >= 25 or landed >= 10:
        score, label, description, evidence_text = (
            50.0,
            "팽팽한 공방",
            "뚜렷한 한 가지 무기보다 서로의 교환이 이어진 라운드입니다.",
            f"유효타 {landed}회",
        )
        support_labels = []
    else:
        score, label, description, evidence_text = (
            0.0,
            "분석 중",
            "기록이 더 쌓이면 이번 라운드 운영을 판정합니다.",
            "",
        )
        support_labels = []

    result_label = ""
    if knockdowns > 0:
        if knockdowns > opponent_knockdowns:
            result_label = f"다운 우세 {knockdowns}:{opponent_knockdowns}"
        else:
            result_label = f"다운 {knockdowns}회"
    elif stuns > opponent_stuns and stuns > 0:
        result_label = f"스턴 우세 {stuns}:{opponent_stuns}"
    elif big45 >= opponent_big45 + 3:
        result_label = f"강타 우세 {big45}:{opponent_big45}"
    else:
        result_label = "결정타 없음"

    condition_label = ""
    stamina = data.get("staminaPct")
    if stamina is not None:
        stamina_value = max(0, min(100, int(round(_number(stamina)))))
        if stamina_value <= 30:
            condition_label = f"실제체력 위험 {stamina_value}%"
        elif stamina_value <= 50:
            condition_label = f"실제체력 부담 {stamina_value}%"
        elif stamina_value >= 75:
            condition_label = f"실제체력 안정 {stamina_value}%"
        else:
            condition_label = f"실제체력 {stamina_value}%"

    chips: List[str] = []
    for value in (result_label, condition_label, *support_labels, evidence_text):
        text = str(value or "").strip()
        if text and text != label and text not in chips:
            chips.append(text)
        if len(chips) >= 4:
            break
    evidence = [evidence_text] if evidence_text else []
    return {
        "label": label,
        "signature": "이번 라운드 운영",
        "description": description,
        "confidence": max(0, min(99, int(round(score)))),
        "evidence": evidence,
        "tier": "",
        "chips": chips,
        "styles": [{"label": label, "tier": "", "role": "round_method"}]
        + ([{"label": result_label, "tier": "", "role": "round_result"}] if result_label else [])
        + ([{"label": condition_label, "tier": "", "role": "round_condition"}] if condition_label else []),
        "secondaryLabel": result_label,
        "tertiaryLabel": condition_label,
        "roundResultLabel": result_label,
        "roundConditionLabel": condition_label,
        "roundEvidence": evidence_text,
        "roundApproach": True,
    }


def _style_label(side: dict) -> str:
    return str(dict(side.get("fightStyle") or {}).get("label") or "균형형 파이터")


def _style_phrase(side: dict) -> str:
    style = dict(side.get("fightStyle") or {})
    primary = str(style.get("label") or "균형형 파이터")
    chips = [str(item).strip() for item in list(style.get("chips") or []) if str(item).strip()]
    secondary = chips[0] if chips else str(style.get("secondaryLabel") or "").strip()
    return _josa(primary, "과/와") + f" {secondary}" if secondary else primary


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
        return f"초반에는 {_josa(names[decided[0]], '이/가')} 앞섰지만, {_josa(names[winner], '이/가')} 이후 라운드에서 전술을 바꾸며 흐름을 뒤집었습니다."
    if winner in ("blue", "red") and all(side == winner for side in decided):
        return f"{_josa(names[winner], '이/가')} 첫 라운드부터 주도권을 잡고 마지막까지 경기의 방향을 내주지 않았습니다."
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
        return f"가장 큰 전환점은 {round_no}라운드, {_josa(names[attacker], '이/가')} 만든 다운 장면이었습니다."
    blue_dealt = _number(row.get("red_damage_taken"))
    red_dealt = _number(row.get("blue_damage_taken"))
    if abs(blue_dealt - red_dealt) >= 80.0:
        side = "blue" if blue_dealt > red_dealt else "red"
        return f"승부의 흐름은 {round_no}라운드에 {_josa(names[side], '이/가')} 더 선명한 유효타를 쌓으면서 크게 움직였습니다."
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
        return f"{_josa(winner_name, '은/는')} 상대가 공격을 마친 뒤의 빈틈을 놓치지 않았고, 카운터 타이밍으로 중요한 교전을 가져갔습니다."
    winner_kd = _count(won.get("knockdowns"))
    loser_kd = _count(lost.get("knockdowns"))
    if winner_kd > loser_kd:
        return f"{_josa(winner_name, '은/는')} 단순히 많이 맞힌 것이 아니라, 승부를 바꾸는 강한 정타로 다운까지 만들어냈습니다."
    winner_big = _count(won.get("bigHits")) + _count(won.get("powerHits55"))
    loser_big = _count(lost.get("bigHits")) + _count(lost.get("powerHits55"))
    if winner_big >= loser_big + 2:
        return f"{_josa(winner_name, '은/는')} 강타의 질에서 앞섰고, 중요한 순간마다 더 무거운 유효타를 남겼습니다."
    winner_accuracy = _number(won.get("accuracy"), -1.0)
    loser_accuracy = _number(lost.get("accuracy"), -1.0)
    if winner_accuracy >= 0 and loser_accuracy >= 0 and winner_accuracy >= loser_accuracy + 8.0:
        return f"{_josa(winner_name, '은/는')} 불필요한 공격을 줄이고 더 정확한 선택으로 경기 효율에서 차이를 만들었습니다."
    winner_damage = _number(won.get("damage"))
    loser_damage = _number(lost.get("damage"))
    if winner_damage > loser_damage:
        return f"{_josa(winner_name, '은/는')} 한 장면에만 의존하지 않고 유효타를 꾸준히 누적해 경기의 무게를 가져왔습니다."
    return f"{_josa(winner_name, '은/는')} 결정적인 교전에서 더 침착하게 자기 공격을 완성했습니다."


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
            lines.append(f"{_josa(winner_name, '이/가')} 끝까지 압박을 이어가며 테크니컬 녹아웃으로 경기를 마무리합니다.")
        elif "knockout" in method_token or method_token == "ko":
            lines.append(f"{_josa(winner_name, '이/가')} 결정적인 한 방으로 녹아웃 승리를 완성합니다.")
        else:
            lines.append(f"{_josa(winner_name, '이/가')} 라운드 운영에서 앞서 판정승을 가져갑니다.")
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

    blue_style = _style_phrase(blue)
    red_style = _style_phrase(red)
    if blue_style != "분석 중" and red_style != "분석 중":
        lines.append(f"스타일로 보면 {_josa(blue_name, '은/는')} {blue_style}, {_josa(red_name, '은/는')} {red_style}의 색깔을 뚜렷하게 보여줬습니다.")

    if winner in ("blue", "red"):
        loser = "red" if winner == "blue" else "blue"
        winner_style = _style_phrase(payload.get(winner) or {})
        if winner_style != "분석 중":
            lines.append(f"결국 {_josa(names[winner], '이/가')} 자신의 {winner_style} 강점을 더 오래 유지했고, {_josa(names[loser], '은/는')} 그 흐름을 끊을 해답을 만들지 못했습니다.")
        else:
            lines.append(f"결국 {_josa(names[winner], '이/가')} 결정적인 순간의 집중력을 끝까지 유지하며 승리를 완성했습니다.")
    else:
        lines.append("서로 다른 강점이 맞물리면서 한쪽이 끝까지 흐름을 독점하지 못한 경기였습니다.")

    return " ".join(line for line in lines if line).strip()
