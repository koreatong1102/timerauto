"""Evidence-bound report narration. No log recounting, network or result inference."""
import math


SIDES = ("blue", "red")


def number(value):
    try:
        result = float(value)
        return max(0., result) if math.isfinite(result) else 0.
    except (TypeError, ValueError):
        return 0.


def count(stats, key):
    return int(number(stats.get(key)))


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
            result = ("TKO승" if "tko" in method or "technical" in method else
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
    def add(priority, topic, text, question="", reaction=""):
        facts.append((priority, topic, text, question, reaction))

    if all("damage" in stats[s] for s in SIDES):
        bd, rd = count(b, "damage"), count(r, "damage")
        split = ((count(b, "landed") - count(r, "landed")) * (bd - rd) < 0)
        more = "blue" if count(b, "landed") > count(r, "landed") else "red"
        harder = "blue" if bd > rd else "red"
        text = f"공식 데미지는 {bn} {bd}, {rn} {rd}."
        if split:
            text += f" 적중 횟수는 {names[more]} 쪽인데, 누적 데미지는 {names[harder]} 쪽이에요. 많이 맞힌 쪽과 더 아프게 때린 쪽이 달랐습니다."
        add(92 if split else 48, "damage", text,
            "다음에는 적중 횟수와 데미지 차이가 같이 움직이는지 보죠.",
            "주먹 많이 보냈다고 이자까지 붙는 건 아니네요." if split else "")

    for key, label, priority in (("knockdowns", "다운", 100), ("stuns", "스턴", 68)):
        if all(key in stats[s] for s in SIDES) and max(count(b, key), count(r, key)):
            add(priority, key, f"{label}을 만든 횟수는 {bn} {count(b, key)}, {rn} {count(r, key)}입니다.",
                "다음 라운드는 큰 타격 뒤에 수비를 되찾는지가 관전 포인트예요.",
                "많이 때렸냐와 별개로, 이건 맞는 쪽에서 절대 못 잊죠." if key == "knockdowns" else "")

    if all("counterHits" in stats[s] for s in SIDES) and max(count(b, "counterHits"), count(r, "counterHits")) >= 2:
        bc, rc = count(b, "counterHits"), count(r, "counterHits")
        side = "blue" if bc > rc else "red"
        extra = (f" {names[side]} 쪽이 반격 적중을 {abs(bc-rc)}번 더 쌓았습니다." if bc != rc else " 반격 적중 수는 같습니다.")
        add(70 + min(18, abs(bc-rc)), "counter", f"카운터는 {bn} {bc}번, {rn} {rc}번.{extra}",
            "다음에는 공격을 내민 뒤 반격을 얼마나 덜 허용하는지 봐야겠어요.",
            {"light": "공격하러 갔는데 돌아올 때 멍이 늘어요.",
             "mixed": "공격하러 갔는데 본인만 존나 억울해져요.",
             "strong": "씨발, 공격하러 갔는데 맞고 돌아오면 계산이 안 맞죠."}.get(swearing, ""))

    if max(count(b, "maxComboHits"), count(r, "maxComboHits")) >= 2:
        combo = []
        for side in SIDES:
            item = stats[side]
            if "maxComboHits" not in item:
                continue
            hits = count(item, "maxComboHits")
            combo.append((f"{names[side]} {hits}연타" + (f"에 {count(item, 'maxComboDamage')} 데미지" if "maxComboDamage" in item else ""))
                         if hits >= 2 else f"{names[side]} 쪽은 2연타 이상 기록이 없어요")
        add(70 + min(14, max(count(b, "maxComboHits"), count(r, "maxComboHits")) * 2), "combo", "최대 콤보는 " + ", ".join(combo) + ". 길게 이은 횟수와 그 연타의 데미지는 따로 봐야죠.",
            "다음에는 첫 타를 맞은 뒤 연타를 끊어낼 수 있는지가 중요하겠네요.",
            "한 대 맞았으면 끝내 줘야지, 뒤에 줄이 서 있어요.")

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
                    "다른 데도 있는데 꼭 거기를 찾네요. 맞는 쪽은 진짜 싫겠습니다.")

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
                "저건 한 번 맞아도 기억에 오래 남겠습니다.")

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
    for fact in sorted(facts, key=lambda x: x[0], reverse=True):
        if fact[1] not in seen:
            chosen.append(fact)
            seen.add(fact[1])
        if len(chosen) >= (4 if final else 3):
            break
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
