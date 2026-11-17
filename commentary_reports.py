"""Evidence-bound report narration. No log recounting, network or result inference."""
import math
import hashlib
import json


SIDES = ("blue", "red")


def number(value):
    try:
        result = float(value)
        return max(0., result) if math.isfinite(result) else 0.
    except (TypeError, ValueError):
        return 0.


def count(stats, key):
    return int(number(stats.get(key)))


def _variant(options, data, topic):
    """Stable wording for the same report; no name-based or random decisions."""
    facts = {"round": data.get("round"), "winner": data.get("winner"), "topic": topic}
    for side in SIDES:
        values = dict(data.get(side) or {})
        facts[side] = {key: values.get(key) for key in (
            "landed", "damage", "counterHits", "maxComboHits", "maxComboDamage", "knockdowns", "stuns")}
    key = json.dumps(facts, sort_keys=True, ensure_ascii=True, default=str).encode()
    return options[int(hashlib.sha256(key).hexdigest()[:8], 16) % len(options)]


def _round_opening(round_no, topic, data):
    frames = {
        "damage": ("주먹 개수와 데미지를 같이 봐야겠어요.", "많이 맞히는 것과 무겁게 맞히는 건 다른 얘기죠."),
        "counter": ("이번엔 받아친 기록이 먼저 눈에 들어옵니다.", "공격 뒤에 누가 반격을 챙겼는지 보죠."),
        "combo": ("이번엔 한 번에 어디까지 연결했는지 보죠.", "한 대보다 그다음 주먹에서 얘깃거리가 나왔어요."),
        "knockdowns": ("다운 기록부터 짚고 가죠.", "교환 중에 누가 다운을 만들었는지부터 보겠습니다."),
        "weak": ("어디를 맞혔는지 보면 얘기가 달라집니다.", "이번엔 적중 부위가 눈에 들어오네요."),
        "average": ("한 대당 데미지에서 차이를 볼 수 있어요.", "이번엔 타격 개수와 한 대의 무게를 나눠 보죠."),
        "maximum": ("가장 큰 한 방부터 짚고 가죠.", "이번엔 크게 들어간 펀치가 눈에 띕니다."),
        "accuracy": ("내민 주먹 중 얼마나 맞혔는지 보겠습니다.", "이번엔 정확도를 같이 봐야겠어요."),
    }
    options = frames.get(topic, ("양쪽 기록을 나란히 놓고 보죠.", "한쪽 얘기만 하지 말고 기록을 비교해 보겠습니다."))
    return f"{round_no}라운드 정리하죠. " + _variant(options, data, "opening:" + topic)


def build_report_narration(report, *, final=False, swearing="strong", callback=""):
    """Interpret the exact displayed scope; don't turn a damage lead into a win.

    A few high-value comparisons beat reading every cell. Missing measurements
    stay missing, and an official result always outranks inferred performance.
    """
    data = dict(report or {})
    stats = {side: dict(data.get(side) or {}) for side in SIDES}
    if not all(stats.values()):
        return ""
    names = {s: str(stats[s].get("name") or ("블루 코너" if s == "blue" else "레드 코너")) for s in SIDES}
    bn, rn = names["blue"], names["red"]
    b, r = stats["blue"], stats["red"]
    round_no = max(1, int(number(data.get("round"))))
    winner = str(data.get("winner") or "").lower()
    method = str(data.get("resultMethod") or dict(data.get("matchResult") or {}).get("method") or "").lower()
    if final:
        if winner in SIDES:
            result = ("경기 중단 승리" if method.replace(' ','')=='ko/tko' else
                      "TKO승" if "tko" in method or "technical" in method else
                      "KO승" if method == "ko" or "knockout" in method else
                      "기권승" if any(x in method for x in ("forfeit", "surrender", "retire", "기권")) else
                      "판정승" if any(x in method for x in ("decision", "point", "판정")) else "승리")
            opening = f"경기 전체를 정리하죠. {names[winner]}, {result}입니다."
        else:
            opening = "경기 결과는 무승부입니다. 서로 뭘 잘했는지 기록으로 보죠." if winner == "draw" else "경기 전체 기록을 보죠."
    else:
        openings = (f"{round_no}라운드, 숫자보다 차이가 난 대목을 봅시다.",
                    f"{round_no}라운드 정리하죠. 양쪽이 잘한 게 좀 달랐어요.",
                    f"{round_no}라운드 끝났습니다. 이번에는 이 기록이 눈에 들어오네요.")
        opening = openings[(round_no - 1) % len(openings)]
    lines = [opening]
    bs, rs = count(b, "officialScore"), count(r, "officialScore")
    if bs and rs:
        lines.append(f"공식 점수는 {bn} {bs}, {rn} {rs}입니다.")
    # Always anchor both participants, not only the fighter with the top combo.
    if all("landed" in stats[s] for s in SIDES):
        lines.append(f"유효타는 {bn} {count(b, 'landed')}번, {rn} {count(r, 'landed')}번.")

    facts = []
    fact_sides = {}
    def add(priority, topic, text, question="", reaction="", *, sides=SIDES):
        facts.append((priority, topic, text, question, reaction))
        fact_sides[text] = set(sides)

    if all("damage" in stats[s] for s in SIDES):
        bd, rd = count(b, "damage"), count(r, "damage")
        split = (all("landed" in stats[s] for s in SIDES)
                 and (count(b, "landed") - count(r, "landed")) * (bd - rd) < 0)
        more = "blue" if count(b, "landed") > count(r, "landed") else "red"
        harder = "blue" if bd > rd else "red"
        text = f"공식 데미지는 {bn} {bd}, {rn} {rd}."
        if split:
            text += f" 적중 횟수는 {names[more]} 쪽인데, 누적 데미지는 {names[harder]} 쪽이에요. 많이 맞힌 쪽과 더 아프게 때린 쪽이 달랐습니다."
        add(92 if split else 48, "damage", text,
            "다음에는 적중 횟수와 데미지 차이가 같이 움직이는지 보죠.",
            _variant(("주먹 많이 보냈다고 이자까지 붙는 건 아니네요.",
                      "많이 맞혀 놓고 데미지 영수증은 상대가 더 크게 끊었어요.",
                      "주먹은 개수로 셌는데 계산서는 무게로 나왔네요."), data, "damage-joke") if split else "")

    for key, label, priority in (("knockdowns", "다운", 100), ("stuns", "스턴", 68)):
        if all(key in stats[s] for s in SIDES) and max(count(b, key), count(r, key)):
            add(priority, key, f"{label}을 만든 횟수는 {bn} {count(b, key)}, {rn} {count(r, key)}입니다.",
                "다음 라운드는 큰 타격 뒤에 수비를 되찾는지가 관전 포인트예요.",
                _variant(("주먹은 많이 오갔어도 다운은 따로 남죠.",
                          "이 기록은 하이라이트 편집자가 먼저 찾겠는데요.",
                          "맞힌 개수 얘기하다가도 여기선 잠깐 멈추게 돼요."), data, "down-joke") if key == "knockdowns" else "")

    if all("counterHits" in stats[s] for s in SIDES) and max(count(b, "counterHits"), count(r, "counterHits")) >= 2:
        bc, rc = count(b, "counterHits"), count(r, "counterHits")
        side = "blue" if bc > rc else "red"
        extra = (f" {names[side]} 쪽이 반격 적중을 {abs(bc-rc)}번 더 쌓았습니다." if bc != rc else " 반격 적중 수는 같습니다.")
        add(70 + min(18, abs(bc-rc)), "counter", f"카운터는 {bn} {bc}번, {rn} {rc}번.{extra}",
            "다음에는 공격을 내민 뒤 반격을 얼마나 덜 허용하는지 봐야겠어요.",
            _variant({
                "light": ("공격하러 갔는데 돌아올 때 계산이 달라져요.", "주먹 내밀었다가 반송 택배를 받았어요."),
                "mixed": ("공격하러 갔는데 본인만 존나 억울해져요.", "들어갈 때마다 통행료가 존나 비싸요."),
                "strong": ("샤갈, 공격하러 갔는데 맞고 돌아오면 계산이 안 맞죠.",
                           "샤갈, 주먹 내민 건 본인인데 영수증도 본인이 받아요.",
                           "샤갈, 들어가는 건 자유인데 돌아오는 길이 유료예요.")
            }.get(swearing, ("",)), data, "counter-joke"))

    if max(count(b, "maxComboHits"), count(r, "maxComboHits")) >= 2:
        combo = []
        for side in SIDES:
            item = stats[side]
            if "maxComboHits" not in item:
                continue
            hits = count(item, "maxComboHits")
            combo.append((f"{names[side]} {hits}연타" + (f"에 {count(item, 'maxComboDamage')} 데미지" if "maxComboDamage" in item else ""))
                         if hits >= 2 else f"{names[side]} 쪽은 2연타 이상 기록이 없어요")
        extra = ""
        if all("maxComboHits" in stats[s] and "maxComboDamage" in stats[s] for s in SIDES):
            bh, rh = count(b, "maxComboHits"), count(r, "maxComboHits")
            bcd, rcd = number(b["maxComboDamage"]), number(r["maxComboDamage"])
            if (bh - rh) * (bcd - rcd) < 0:
                extra = " 길게 이은 쪽과 콤보 데미지가 높은 쪽은 달랐어요."
        add(70 + min(14, max(count(b, "maxComboHits"), count(r, "maxComboHits")) * 2), "combo", "최대 콤보는 " + ", ".join(combo) + "." + extra,
            "다음에는 첫 타를 맞은 뒤 연타를 끊어낼 수 있는지가 중요하겠네요.",
            _variant(("한 대 맞았으면 끝내 줘야지, 뒤에 줄이 서 있어요.",
                      "한 대만 주문했는데 묶음 배송이 와요.",
                      "끝났나 싶으면 다음 주먹이 출석하네요."), data, "combo-joke"))

    for side in SIDES:
        st = stats[side]
        weak = [dict(x) for x in st.get("weakHitAll", st.get("weakHitTop", [])) or [] if isinstance(x, dict)]
        weak = sorted(weak, key=lambda x: number(x.get("count")), reverse=True)
        if weak and number(weak[0].get("count")) >= 3:
            target = str(weak[0].get("label") or "").strip()
            if target:
                share = number(weak[0].get("count")) / max(1, count(st, "landed"))
                add(72 + min(18, share * 30), "weak", f"{names[side]} 쪽은 {target} 적중이 {int(number(weak[0]['count']))}번입니다. 급소 중에서는 이 부위가 가장 많았어요.",
                    f"다음 라운드는 {target} 수비가 달라지는지 보죠.",
                    _variant(("다른 데도 있는데 배송지가 안 바뀌네요.",
                              "단골집도 저렇게 자주 가면 적립금 줘야 돼요.",
                              "주먹 내비게이션에 저기만 즐겨찾기 해 놨나 봐요."), data, "target-joke"), sides=(side,))

    if all("averageDamage" in stats[s] and count(stats[s], "landed") >= 10 for s in SIDES):
        ba, ra = number(b["averageDamage"]), number(r["averageDamage"])
        if abs(ba-ra) >= 4:
            side = "blue" if ba > ra else "red"
            add(71 + min(17, abs(ba-ra)), "average", f"앱이 집계한 유효타 평균 데미지는 {bn} {ba:g}, {rn} {ra:g}. 유효타 한 대의 평균 무게는 {names[side]} 쪽이 높았어요.",
                "다음에는 타격 수뿐 아니라 정타 한 대의 질도 같이 보죠.",
                "많이 맞는 것도 싫은데 한 대 한 대가 비싸면 더 싫죠.")
    for side in SIDES:
        best = dict(stats[side].get("maxPunch") or {})
        if number(best.get("damage")) >= 60 and best.get("label"):
            add(65 + min(20, (number(best["damage"]) - 60) / 2), "maximum",
                f"{names[side]} 쪽 최고 펀치는 {best['label']}, {number(best['damage']):g} 데미지였습니다.",
                "다음에도 저 한 방이 다시 나오는지 지켜보죠.",
                "하이라이트를 고르라면 저 한 방도 빠지기 어렵겠네요.", sides=(side,))

    if all(stats[s].get("accuracyValid", True) and stats[s].get("accuracy") is not None
           and 0 <= number(stats[s]["accuracy"]) <= 100 and count(stats[s], "thrown") >= 10 for s in SIDES):
        ba, ra = count(b, "accuracy"), count(r, "accuracy")
        if abs(ba - ra) >= 8:
            add(66, "accuracy", f"적중률은 {bn} {ba}퍼센트, {rn} {ra}퍼센트. 공격 개수만 볼 때와 정확도를 볼 때는 느낌이 다르죠.",
                "다음에는 빈 주먹을 줄이면서 지금 정확도를 유지하는지 보겠습니다.")

    # Finals can refer to the actual score trajectory, never invent a tactical
    # change from a result row or call a high-damage round an official win.
    if final:
        card = dict(data.get("officialScorecard") or data.get("scorecard") or {})
        rows = sorted((dict(x) for x in card.get("rounds", []) if isinstance(x, dict)), key=lambda x: number(x.get("round")))
        decided = [(int(number(x.get("round"))), "blue" if number(x.get("blue_score")) > number(x.get("red_score")) else "red")
                   for x in rows if number(x.get("blue_score")) > 0 and number(x.get("red_score")) > 0 and number(x.get("blue_score")) != number(x.get("red_score"))]
        if len(decided) >= 2:
            changes = sum(a[1] != z[1] for a, z in zip(decided, decided[1:]))
            if changes:
                add(95, "arc", f"공식 채점에서 라운드를 가져간 쪽이 {changes}번 바뀌었습니다. 첫 유리 라운드는 {names[decided[0][1]]}, 마지막은 {names[decided[-1][1]]} 쪽이었어요.")
            else:
                add(95, "arc", f"점수 차가 난 {len(decided)}개 라운드는 모두 {names[decided[0][1]]} 쪽이 가져갔습니다.")

    chosen = []
    seen = set()
    ranked = sorted(facts, key=lambda x: x[0], reverse=True)
    # A single-fighter target/maximum story must not consume every supporting
    # slot. Give a measured contribution from the other corner first refusal.
    if ranked:
        covered = fact_sides[ranked[0][2]]
        if len(covered) == 1:
            ranked[1:] = sorted(ranked[1:], key=lambda x: (bool(fact_sides[x[2]] - covered), x[0]), reverse=True)
    for fact in ranked:
        if fact[1] not in seen:
            chosen.append(fact)
            seen.add(fact[1])
        if len(chosen) >= (4 if final else 3):
            break
    if not final:
        lines[0] = _round_opening(round_no, chosen[0][1] if chosen else "", data)
    for index, fact in enumerate(chosen):
        lines.append(fact[2])
        if index == 0 and fact[4] and not callback:
            lines.append(fact[4])
    if callback:
        lines.append(callback)
    if not final:
        question = next((fact[3] for fact in chosen if fact[3]), "")
        if question:
            lines.append(question)
    elif winner in SIDES and "damage" in b and "damage" in r:
        other = "red" if winner == "blue" else "blue"
        if number(stats[winner]["damage"]) < number(stats[other]["damage"]):
            lines.append(f"데미지는 {names[other]} 쪽이 높았지만, 공식 승자는 {names[winner]}입니다. 데미지만으로 승패를 정하면 안 되죠.")
    return " ".join(lines)
