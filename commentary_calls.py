"""Short broadcast calls and actual-playback subject tracking. No verdicts."""
import threading
import time


class SpokenFocus:
    """Omit a name only when an actually started call established the subject.

    Focus follows the audible broadcast, not every unannounced punch. Otherwise
    a fast exchange would force a full nickname on almost every line. Bare
    calls are checked again before playback, not just before synthesis.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._action = None
        self._reference = None
        self._version = 0

    def observe(self, scope, round_no, side):
        action = (scope, round_no)
        with self._lock:
            if action != self._action:
                self._action = action
                self._reference = None
                self._version += 1

    def invalidate(self):
        with self._lock:
            self._reference = None
            self._version += 1

    def _same(self, plan, now):
        ref = self._reference
        return bool(ref and self._action == (plan["scope"], plan["round"])
                    and all(ref.get(k) == plan.get(k) for k in ("scope", "round", "side", "name", "orientation"))
                    and 0 <= now - ref["at"] <= 9.0 and 0 <= now - ref["named_at"] <= 18.0)

    def prepare(self, scope, round_no, side, name, *, important=False, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            plan = {"scope": scope, "round": round_no, "side": side, "name": name,
                    "orientation": "receiver" if important else "attacker", "version": self._version}
            plan["named"] = bool(important or side not in ("blue", "red") or not self._same(plan, now))
            return plan

    def valid(self, plan, *, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            return bool(plan.get("named") or (plan.get("version") == self._version and self._same(plan, now)))

    def started(self, plan, *, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            if not self.valid(plan, now=now):
                return
            if self._reference and any(self._reference.get(k) != plan.get(k) for k in ("scope", "round", "side", "name", "orientation")):
                self._version += 1
            named_at = now if plan["named"] else self._reference["named_at"]
            self._reference = {**plan, "at": now, "named_at": named_at}


SPOKEN_FOCUS = SpokenFocus()


# Complete short sentences. Never strip arbitrary nickname substrings from a
# finished line: a nickname may itself contain "카운터" or punctuation.
SHORT_CALLS = {
    "whiff": ("헛친 틈에 반격!", "빗나간 뒤 바로 받아쳐요!", "헛손질 뒤에 카운터!", "빈틈에 바로 꽂아요!", "헛친 다음을 잡았어요!", "빗나가자마자 들어가요!", "헛친 쪽이 맞습니다!", "주먹 빠진 틈에 반격!"),
    "graze": ("스친 뒤에 카운터!", "살짝 맞고 받아쳐요!", "가볍게 받고 반격!", "스친 다음 바로 돌려줘요!", "약하게 맞고 되받습니다!", "가벼운 타격 뒤 반격!", "스친 걸로 안 끝나요!", "받고 바로 꽂습니다!"),
    "counter": ("카운터!", "받아쳐요!", "반격 들어갑니다!", "타이밍 잡았어요!", "카운터 꽂아요!", "맞받아칩니다!", "반격 적중!", "카운터 맞췄어요!"),
    "counter_combo": ("카운터 섞인 연타!", "반격까지 이어갑니다!", "연타에 카운터까지!", "카운터 넣고 몰아쳐요!", "반격도 들어갔어요!", "연속 공격에 반격도 적중!", "카운터까지 맞히고 이어갑니다!", "반격 섞어서 몰아칩니다!"),
    "combo": ("연타 들어갑니다!", "계속 이어갑니다!", "연속으로 꽂아요!", "몰아붙입니다!", "공격이 이어져요!", "연타 연결!", "연속 타격 들어갑니다!", "계속 맞혀요!"),
    "heavy": ("강하게 들어가요!", "묵직하게 꽂아요!", "큰 한 방!", "강타 적중!", "세게 맞혔어요!", "한 방이 무겁습니다!", "강한 타격 들어갑니다!", "제대로 꽂았어요!"),
    "weak": ("{target} 적중!", "{target}에 들어가요!", "{target} 맞혔어요!", "{target}에 꽂습니다!", "{target} 들어갔어요!", "{target}에 정확히!", "{target} 타격!", "{target} 맞췄습니다!"),
    "answer_back": ("맞고 바로 받아쳐요!", "이번엔 되받습니다!", "곧바로 돌려줍니다!", "맞고도 바로 들어가요!", "바로 응수합니다!", "곧바로 맞받아쳐요!", "받은 뒤 바로 돌려줘요!", "이쪽도 받아칩니다!"),
    "hit": ("한 대 들어가요!", "맞혔어요!", "타격 들어갑니다!", "적중!", "한 대 챙깁니다!", "주먹 들어갔어요!", "정타 맞췄어요!", "한 대 꽂아요!"),
    "stun": ("흔들립니다!", "크게 흔들려요!", "스턴입니다!", "충격이 큽니다!", "타격에 흔들려요!", "스턴 발생!", "지금 흔들렸어요!", "스턴이 왔습니다!"),
    "tko": ("TKO! 경기 끝!", "TKO입니다!", "TKO로 끝납니다!", "여기서 TKO!", "경기 끝, TKO!", "TKO가 나옵니다!", "TKO로 경기 종료!", "TKO! 여기까지입니다!"),
    "knockdown": ("{count_label} 다운!", "{count_label} 다운입니다!", "{count_label} 다운 나옵니다!", "{count_label} 다운, 쓰러집니다!", "{count_label} 다운 발생!", "{count_label} 다운이에요!", "{count_label} 다운을 당합니다!", "{count_label} 다운, 카운트 봅시다!"),
}

REPEATED_COUNTER = ("또 받아쳐요!", "다시 카운터!", "또 반격 들어갑니다!", "이번에도 받아칩니다!",
                    "또 타이밍 잡았어요!", "다시 반격 적중!", "또 카운터 꽂아요!", "반격이 또 들어가요!")
REVERSAL = ("이번엔 반대로 받아칩니다!", "이번 카운터는 반대쪽!", "이번엔 이쪽이 받아쳐요!", "반격하던 쪽이 맞아요!",
            "이번에는 반대로 꽂아요!", "이번엔 반대편 카운터!", "반격의 방향이 바뀝니다!", "이번엔 상대가 받아쳐요!")

LONG_COMBO = {
    "combo": ("연타가 멈추질 않아요!", "계속 꽂아요, 계속!", "한참을 몰아붙입니다!", "공격이 끊기질 않아요!", "아직도 들어갑니다!", "긴 연타가 이어집니다!", "연속 공격을 쏟아냅니다!", "계속 맞히면서 밀어붙여요!"),
    "counter_combo": ("반격까지 섞어서 계속 몰아칩니다!", "카운터 넣고 멈추질 않아요!", "반격에 연타까지 길게 이어져요!", "카운터부터 계속 꽂습니다!", "받아치고 계속 몰아붙여요!", "반격도 맞히고 연타도 이어갑니다!", "긴 연타 속에 카운터까지!", "카운터 섞인 공격이 끊기질 않아요!"),
}


def short_call(tag, index, *, name, named=True, context=None, hits=0, target="급소", count=1):
    ctx = dict(context or {})
    pool = SHORT_CALLS[tag]
    if tag in LONG_COMBO and hits >= 6:
        pool = LONG_COMBO[tag]
    counter = tag in ("counter", "whiff", "graze")
    if counter and ctx.get("reversal"):
        pool = REVERSAL
    elif counter and ctx.get("repeat_counter"):
        pool = REPEATED_COUNTER
    text = pool[index % len(pool)].format(hits=hits, target=target,
        count_label={1: "첫 번째", 2: "두 번째", 3: "세 번째"}.get(int(count), f"{count}번째"))
    return f"{name}, {text}" if named else text
