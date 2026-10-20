"""Opt-in broadcast wording. Never classifies a hit or changes match facts.

Profanity is deliberately uncensored in this style. Pools target the situation,
not a player's identity. All calls are local; no network/model request is made.
"""
from collections import deque
import re
from commentary_director import CommentaryCandidate
from commentary_story import MatchStory
from commentary_calls import SHORT_CALLS, short_call


STYLE_CHOICES = (("일반 스포츠", "sports"), ("B급 인방 예능 · 비속어 허용", "b_grade"))


def normalize_style(value):
    return "b_grade" if str(value or "").strip().lower() == "b_grade" else "sports"


POOLS = {
    "whiff": (
        "씨발, 때리러 갔다가 계산은 본인이 합니다.",
        "헛손질 한 번에 반격 청구서가 날아옵니다.",
        "공격은 출발했는데 본인한테 반품됐어요.",
        "빈손으로 들어갔다가 주먹만 존나 받아옵니다.",
        "공격 버튼 눌렀는데 피격 서비스가 실행됩니다.",
        "헛친 값이 이렇게 비쌉니다. 환불도 안 돼요.",
    ),
    "graze": (
        "살짝 건드렸는데 답장이 존나 깁니다.",
        "보낸 건 인사인데 돌아온 건 내용증명이에요.",
        "잔돈 넣었더니 지폐로 돌려줍니다.",
        "아니 씨발, 스친 값이 이 정도입니까.",
        "가볍게 보냈는데 반격은 착불입니다.",
    ),
    "counter": (
        "씨발, 카운터 타이밍 살벌합니다.",
        "반격 타이밍이 아주 개같이 정확합니다.",
        "빈틈 생기자마자 자동 결제 들어갑니다.",
        "타이밍 장사 잘하네요. 외상은 안 받습니다.",
        "반격 영수증이 바로 출력됩니다.",
    ),
    "counter_combo": (
        "반품했더니 추가 배송이 존나 옵니다.",
        "카운터 한 대인 줄 알았는데 씨발, 세트 메뉴예요.",
        "반격에 후속타까지. 서비스가 너무 과합니다.",
        "카운터로 문 열고 연타가 단체 입장합니다.",
        "반격은 시작일 뿐입니다. 본편은 연타예요.",
    ),
    "combo": (
        "한 대 주문했는데 존나 여러 개가 옵니다.",
        "씨발, 단품인 줄 알았는데 정기구독입니다.",
        "주먹이 줄 서서 들어갑니다. 새치기도 없어요.",
        "첫 타는 예고편이고 뒤가 본편입니다.",
        "연타 묶음 상품입니다. 낱개 취소 안 됩니다.",
        "타격 알림이 단체 채팅처럼 쌓입니다.",
    ),
    "heavy": (
        "씨발, 한 방에 존재감이 너무 큽니다.",
        "이건 펀치가 아니라 방문 철거예요.",
        "주먹에 무게감이 존나 실렸습니다.",
        "효과음 없어도 존재감 확실한 한 방입니다.",
        "한 방인데 분량을 혼자 다 가져갑니다.",
    ),
    "weak": (
        "그 자리는 타격 맛집이지 주차장이 아닙니다.",
        "급소에 씨발, 정확하게 배달됐습니다.",
        "주소를 너무 정확하게 찍었어요.",
        "아무 데나 친 게 아닙니다. 목적지가 확실해요.",
    ),
    "answer_back": (
        "씨발, 두 분 다 마지막 말은 본인이 해야 됩니다.",
        "맞고 바로 답장합니다. 읽씹은 없어요.",
        "반격 처리 속도가 존나 빠릅니다.",
        "교환은 되는데 환불은 안 되는 경기입니다.",
    ),
    "knockdown": (
        "와 씨발, 방금 장면은 다시 봐야 됩니다.",
        "다운 장면 나왔습니다. 이제 카운트부터 봅시다.",
        "연출이 아니라 경기에서 나온 장면입니다.",
        "방금 한 장면이 존나 강렬했습니다.",
    ),
    "stun": (
        "와 씨발, 방금 타격은 반응이 바로 나옵니다.",
        "흔들렸습니다. 여기서 다음 타격을 봐야죠.",
        "한 방의 존재감이 존나 큽니다.",
    ),
    "tko": (
        "씨발, 경기 종료 콜 나왔습니다.",
        "와, 이걸 이렇게 끝냅니다. 존나 강렬하네요.",
        "방금 장면으로 경기 마침표가 찍혔습니다.",
    ),
    "round": (
        "씨발, 숫자로 보니까 방금 라운드가 더 선명하네요.",
        "드립은 드립이고, 방금 기록은 이렇습니다.",
        "주먹은 쉬어도 영수증은 남습니다.",
    ),
    "final": (
        "드립은 존나 쳤지만 경기 기록은 진지하게 봤습니다.",
        "씨발, 중계는 떠들썩했어도 결과는 이렇습니다.",
        "이상, 주먹으로 작성한 경기 보고서였습니다.",
    ),
}

IDLE_PAIRS = (
    ("아니, 적중 소식이 없어요! 저희만 떠들고 있잖아요!", "씨발, 해설만 입 풀고 있습니다."),
    ("유효타가 안 나오니까 제 입만 바쁩니다!", "둘이 경기하는데 저희가 분량 걱정합니다."),
    ("잠깐만요. 적중 한 번 기다리다가 말이 더 많아졌어요!", "이러다 해설이 먼저 지치겠습니다."),
    ("적중 소식 좀 주세요! 저도 주먹 얘기 하고 싶어요!", "해설 둘이 존나 열심히 뛰고 있네요."),
    ("잠깐 조용해졌습니다. 저희도 좀 쉬나요?", "그 말 하면 꼭 한 대 들어오더라고요."),
    ("이럴 때 제가 먼저 들어가라고 해야 됩니까?", "여기서 말하는 건 쉽죠. 맞는 건 저희가 아닌데."),
    ("큰 거 하나 나올 때가 된 것 같은데요!", "그렇게 말하고 기다린 게 벌써 몇 번째입니까."),
    ("지금 조용하다고 화면 돌리면 안 됩니다!", "꼭 딴 데 볼 때만 터져요. 그러고 저한테 물어봅니다."),
    ("저 지금 소리 지를 준비는 끝났거든요?", "적중부터 나오고 지르세요. 먼저 지르면 사기예요."),
    ("다음 한 방, 누가 먼저 맞힐까요?", "그걸 알면 제가 여기서 해설하고 있겠습니까."),
    ("숨 좀 돌리는 구간이네요. 저희도 물 한 모금만.", "그러다 터지면 물부터 뿜습니다. 내려놓으세요."),
    ("지금은 잠잠합니다. 아까처럼 갑자기 터질 수도 있어요.", "예고하고 때리는 게임이 아니니까요. 눈 떼지 마세요."),
)

# Caster calls the fact; analyst answers with a short, situation-specific beat.
# These are separate turns, not a swear word pasted onto every sports call.
LIVE_REPLIES = {
    "whiff": (
        "아 씨발, 안 맞았다고 좋아할 틈도 없어요!",
        "때리러 갔잖아요. 왜 맞고 돌아옵니까!",
        "그냥 헛치고 끝났으면 다행이었죠. 바로 맞았어요.",
        "아니, 빗나간 거 보자마자 손이 나가네요. 성격 급합니다!",
        "저 빈틈을 안 봐주네. 친선은 저희끼리만 하고 있네요.",
        "빈손으로 돌아오면 되는데 굳이 한 대를 받아 와요!",
        "헛친 다음이 더 무섭네요. 주먹 거둘 때도 봐야 됩니다.",
        "야, 한 번 헛쳤다고 바로 혼내네요. 살벌합니다!",
    ),
    "graze": (
        "씨발, 살짝 맞았는데 대답은 왜 이렇게 세요!",
        "이렇게 나오면 다음엔 건드리기도 싫겠습니다.",
        "받은 만큼만 돌려주는 성격은 아니네요!",
        "살짝 건드렸잖아요. 이렇게까지 할 일입니까!",
        "가볍게 맞고 무겁게 때립니다. 아주 본인 위주예요.",
        "이건 때린 쪽도 억울하겠어요. 내가 더 맞았어!",
        "얌전히 맞아 줄 줄 알았습니까. 바로 돌아옵니다.",
        "아, 이 정도면 다음 주먹은 좀 고민되죠!",
    ),
    "counter": (
        "아 씨발, 때리러 갔다가 왜 내가 맞아요!",
        "주먹 뻗은 사람만 억울하죠. 나는 공격했는데!",
        "안 맞으려고 때렸는데 더 맞았습니다. 이게 복싱이에요.",
        "저 타이밍에 손이 나오네요. 저 같으면 그냥 맞았어요.",
        "야, 받아치는 게 빠릅니다. 성질도 빠르겠는데요!",
        "여기서 또 막 내밀면 또 맞아요. 방금 봤잖아요!",
        "기분 나쁘죠. 내가 먼저 때리려고 했는데!",
        "공격했다고 안심할 수가 없어요. 저게 기다리고 있네!",
    ),
    "counter_combo": (
        "씨발, 반격 한 대면 됐지 뒤에는 왜 또 와요!",
        "받아치는 걸로 끝낼 생각이 전혀 없네요!",
        "카운터도 맞았는데 연타도 맞아요. 너무하네 진짜!",
        "한 번 걸렸다고 끝까지 따라옵니다. 끈질겨요!",
        "아, 반격만 생각하고 있으면 뒤에 또 맞습니다!",
        "때리려던 쪽이 더 바빠졌어요. 이제 막아야 돼요!",
        "야, 틈 하나 났다고 이렇게 많이 때립니까!",
        "이러면 다음엔 주먹 내미는 것도 겁나죠!",
    ),
    "combo": (
        "야 씨발, 한 대 맞았으면 됐지 계속 와요!",
        "끝났나? 안 끝났어요. 또 맞았어요!",
        "저희도 세고 있습니다. 맞는 분은 더 길겠죠!",
        "아니, 한 대씩 얘기합시다. 왜 몰아서 때려요!",
        "한 번 걸리니까 그냥 안 놔주네요!",
        "저 사이에 끼면 안 됩니다. 일단 빠져야죠!",
        "첫 타 맞고 끝난 줄 알면 큰일 납니다!",
        "야, 연타 끊는 게 먼저예요. 같이 치다가 더 맞습니다!",
    ),
    "heavy": (
        "와 씨발, 저는 구경하는데도 소리 나왔어요!",
        "한 대인데 저절로 자세 고쳐 앉았습니다!",
        "저건 해설할 것도 없어요. 저도 방금 어! 했어요.",
        "야, 보는 사람도 조용히 못 있겠네요!",
        "가볍게 들어간 주먹은 아니죠. 방금 건 확실해요.",
        "지금 제 목소리 커진 거 이해해 주십시오!",
        "채팅 치던 분들, 방금 거 보셨어요? 고개 드세요!",
        "아, 이런 거 나오면 조용히 중계 못 합니다!",
    ),
    "weak": (
        "아 씨발, 거길 딱 찾아가네요. 보는 제가 다 싫어요!",
        "아무 데나 맞은 게 아니죠. 하필 거기예요!",
        "야, 저 자리는 좀 지켜 줍시다. 계속 열리면 또 와요!",
        "아픈 데는 기가 막히게 찾아요. 친절하진 않습니다!",
        "때리는 분은 좋겠죠. 맞는 쪽은 생각이 다릅니다!",
        "그냥 안 맞는 게 낫죠. 어디가 덜 아프냐고 묻지 마세요!",
        "저길 맞았네. 저였으면 지금 말부터 나왔어요!",
        "자리 비면 바로 들어옵니다. 봐주는 건 없네요!",
    ),
    "answer_back": (
        "씨발, 둘 다 마지막 한 대는 자기가 쳐야 돼요!",
        "맞고 그냥 넘어가는 분들이 아니네요!",
        "한 번씩만 합시다. 왜 계속 주고받아요!",
        "아, 이쪽도 참는 성격은 아니죠!",
        "서로 먼저 그만둘 생각이 없어요. 저희만 바쁩니다!",
        "맞았다고 물러나는 게 아니라 더 들어오네요!",
        "복싱인데 말싸움 같아요. 둘 다 마지막 말을 해요!",
        "그냥 넘어가면 지는 줄 아는 두 분입니다!",
    ),
    "hit": (
        "깔끔하게 하나 챙겼어요. 이런 게 쌓입니다.",
        "지금은 크게 안 떠들게요. 들어간 건 봤습니다!",
        "야, 이거 맞았어요. 저희 못 본 척은 안 합니다!",
        "일단 맞힌 쪽이 좋죠. 맞는 쪽은 별로겠지만요.",
        "저희가 조용해도 주먹은 들어갑니다. 방금도 들어갔어요.",
        "한 대부터 시작하는 거죠. 처음부터 연타가 있습니까!",
        "이런 한 대를 그냥 주면 나중에 억울합니다.",
        "저건 챙겨야죠. 때릴 수 있을 때 때려야 됩니다.",
    ),
    "stun": (
        "와 씨발, 흔들렸어요. 지금은 다음 한 대를 봐야 돼요!",
        "야, 지금은 드립 칠 때 아닙니다. 수비부터 봐야죠!",
        "한 대 더 들어가느냐, 버티느냐. 눈 떼지 마세요!",
        "제가 떠들 타이밍이 아니네요. 일단 봅시다!",
    ),
    "knockdown": (
        "와 씨발, 방금 건 다시 봐야 됩니다. 카운트부터 보죠!",
        "저 방금 말하다 끊겼어요. 아니, 저렇게 들어가네!",
        "야, 보는 저도 놀랐어요. 일단 카운트 봅시다!",
        "떠들다가 같이 소리 질렀습니다. 지금은 카운트예요!",
    ),
    "tko": (
        "와 씨발, 끝났어요! 여기서 끝내 버립니다!",
        "야, 더 갑니까 했는데 끝났어요. 확실하게 끝냅니다!",
        "말하던 거 다 잊었습니다. 방금 장면부터 다시 봐야죠!",
        "아니, 끝낼 때 이렇게 끝내네요!",
    ),
}

# Complete alternate calls, not suffixes on the sports commentator's sentence.
# Facts in braces come only from the selected central verdict/report.
LIVE_CALLS = {
    "whiff": (
        "{name}, 헛친 거 바로 받아먹어요! 아 씨발, 이걸 놓치질 않네!",
        "{name}, 상대 주먹 빗나가니까 바로 때립니다! 헛손질이 공짜가 아니에요!",
        "{name}, 헛친 틈에 카운터! 때리러 들어갔다가 맞고 돌아갑니다!",
        "아니 {name}, 헛치자마자 반격해요! 잠깐 빈틈 났다고 바로 들어오네!",
    ),
    "graze": (
        "{name}, 살짝 맞고 세게 돌려줍니다! 야, 받은 만큼만 돌려주라고!",
        "{name}, 스친 뒤에 바로 카운터! 아 씨발, 답장이 너무 세요!",
        "{name}, 살짝 건드리니까 바로 물어요! 이거 건드리면 안 됩니다!",
        "{name}, 가벼운 공격 뒤에 묵직하게 반격합니다! 손해 보고는 못 사네요!",
    ),
    "counter": (
        "{name}, 카운터! 아 씨발, 타이밍 보세요!",
        "{name}, 반격 꽂아요! 아니, 때리러 갔다가 왜 맞고 와요!",
        "{name}, 카운터 들어갑니다! 주먹 내밀기가 존나 무섭겠어요!",
        "{name}, 받아칩니다! 잠깐만, 공격한 쪽이 왜 손해예요!",
        "{name}, 카운터 맞췄어요! 반격 타이밍 하나는 살벌합니다!",
    ),
    "counter_combo": (
        "{name}, 카운터까지 섞인 {hits}연타! 야 씨발, 그냥 연타도 아니에요!",
        "{name}, 반격까지 들어간 {hits}연타입니다! 뭘 내밀어도 맞네요!",
        "{name}, {hits}연타에 카운터까지! 잠깐만, 너무 많이 챙겨갑니다!",
    ),
    "combo": (
        "{name}, {hits}연타! 야, 한 대 맞았으면 됐지 계속 들어옵니다!",
        "{name}, {hits}대 이어갑니다! 씨발, 끝난 줄 알았는데 안 끝나요!",
        "{name}, {hits}연타 꽂습니다! 잠깐만요, 아직도 때려요!",
        "{name}, {hits}연타예요! 한 대 맞고 끝날 일이 아니었습니다!",
        "{name}, {hits}대 연결! 아 이거, 맞는 쪽에선 존나 길어요!",
    ),
    "heavy": (
        "{name}, 한 방 꽂아요! 와 씨발, 이건 소리 나올 만합니다!",
        "{name}, 묵직하게 맞혔습니다! 야, 한 방 존재감이 너무 커요!",
        "{name}, 세게 들어갑니다! 아 이래서 한 방을 조심해야 돼요!",
        "{name}, 강타 적중! 지금 저절로 소리 나왔습니다!",
    ),
    "weak": (
        "{name}, {target}에 들어가요! 아 씨발, 거길 딱 맞히네!",
        "{name}, {target} 적중! 아니, 안 좋은 데는 기가 막히게 찾아요!",
        "{name}, {target} 맞혔습니다! 아무 데나 휘두른 게 아니에요!",
    ),
    "answer_back": (
        "{name}, 맞고 바로 받아쳐요! 씨발, 마지막 주먹은 자기가 쳐야 됩니다!",
        "{name}, 곧바로 반격! 둘 다 맞고는 그냥 못 넘어가요!",
        "{name}, 바로 돌려줍니다! 이쪽도 가만히 맞고 있을 생각 없습니다!",
    ),
    "hit": (
        "{name}, 한 대 들어갔어요! 야, 이건 챙겨갑니다!",
        "{name}, 맞혔습니다! 일단 한 대 먹이고 봅니다!",
        "{name}, 타격 들어갑니다! 주먹으로 말하네요!",
        "{name}, 적중! 아, 말할 틈도 없이 들어갑니다!",
    ),
    "stun": (
        "{receiver}, 흔들립니다! 와 씨발, 방금 제대로 들어갔어요!",
        "{receiver}, 크게 흔들려요! 야, 다음 타격 봐야 됩니다!",
        "{receiver}, 스턴입니다! 지금은 드립 칠 때가 아니에요!",
    ),
    "tko": (
        "{receiver}, TKO! 경기 끝났습니다! 와 씨발, 이렇게 끝나네요!",
        "{receiver}, TKO입니다! 여기서 경기 끝! 잠깐만, 끝났어요!",
        "{receiver}, TKO! 경기가 여기서 멈춥니다! 와, 이걸 끝내네요!",
    ),
    "knockdown": (
        "{receiver}, {count_label} 다운! 와 씨발, 일단 카운트 봅시다!",
        "{receiver}, {count_label} 다운입니다! 야, 지금은 카운트부터 봐야 돼요!",
        "{receiver}, 이번 라운드 {count_label} 다운! 와, 이 장면 보세요!",
    ),
}


class BGradeCommentary:
    def __init__(self):
        self.reset_match()

    def reset_match(self):
        self._indices = {}
        self._recent = deque(maxlen=64)
        self._last_at = {}
        self._live_indices = {}
        self.story = MatchStory()

    def pick(self, tag, *, now):
        pool = POOLS.get(tag, ())
        if not pool or now - self._last_at.get(tag, -1e9) < 8.0:
            return ""
        recent = {text for text, at in self._recent if now - at < 90.0}
        start = self._indices.get(tag, 0)
        for offset in range(len(pool)):
            index = (start + offset) % len(pool)
            text = pool[index]
            if text not in recent:
                self._indices[tag] = index + 1
                self._last_at[tag] = now
                self._recent.append((text, now))
                return text
        return ""

    def idle_pair(self):
        index = self._indices.get("idle", 0)
        self._indices["idle"] = index + 1
        return IDLE_PAIRS[index % len(IDLE_PAIRS)]

    def make_call(self, tag, *, name="블루 코너", receiver="레드 코너", hits=0, count=1,
                  target="급소", key="", side="", receiver_side="", context=None, now=None):
        pool = SHORT_CALLS.get(tag)
        if not pool:
            return None
        important = tag in ("knockdown", "tko", "stun")
        subject = (receiver_side or ("red" if side == "blue" else "blue" if side == "red" else "")) if important else side
        spoken_name = receiver if important else name
        focus = self.story.focus.prepare(self.story.scope, self.story.round, subject, spoken_name, important=important, now=now)
        setup = short_call(tag, self._live_indices.get(tag, 0), name=spoken_name, named=focus["named"],
                           context=context, hits=hits, target=target, count=count)
        presentation = self.story.compose(tag, setup=setup, name=name, side=side, context=context,
                                          hits=hits, now=now, brief=True)
        presentation["focus"] = focus
        text = " ".join(turn["text"] for turn in presentation["turns"])
        category = {"whiff": "counter", "graze": "counter", "weak": "event_analysis",
                    "heavy": "event_analysis", "hit": "event_analysis"}.get(tag, tag)
        priority = {"knockdown": 110, "tko": 108, "stun": 96, "counter_combo": 86,
                    "counter": 84, "whiff": 84, "graze": 84, "combo": 81,
                    "heavy": 70, "weak": 64, "answer_back": 72, "hit": 50}[tag]
        return CommentaryCandidate(text, presentation["turns"][0]["role"], category, priority,
            key=f"bgrade:{tag}:{key}", urgent=priority >= 96, attacker_name=name, attacker_side=side,
            presentation=presentation)

    @staticmethod
    def dialogue_for(candidate):
        """Keep the fact and punchline bound to the same playback request."""
        if candidate.presentation:
            turns = candidate.presentation["turns"]
            return turns[0]["text"], [dict(turn) for turn in turns[1:]]
        parts = re.split(r"(?<=[.!?])\s+", candidate.text, maxsplit=1)
        return parts[0], ([{"text": parts[1], "role": "analyst"}] if len(parts) > 1 else [])

    def accept_call(self, candidate):
        if str(candidate.key).startswith("bgrade:"):
            tag = candidate.key.split(":", 2)[1]
            self._live_indices[tag] = self._live_indices.get(tag, 0) + 1
        if candidate.presentation:
            self.story.selected(candidate.presentation)

    def event_call(self, event, *, name, receiver, target="급소", min_damage=25.0, key="", now=None):
        row = dict(event or {})
        verdict = dict(row.get("_central_event") or {})
        counter = bool(verdict.get("counter", row.get("is_counter", False)))
        hits = int(verdict.get("combo_hits", row.get("combo_hits", 0)) or 0)
        reason = str(verdict.get("counter_reason", row.get("counter_reason", "")) or "")
        tags = set(verdict.get("tags", row.get("event_tags", [])) or [])
        effect = str(row.get("effect_kind") or "").lower()
        if effect in ("tko", "stun"):
            tag = effect
        elif counter and hits >= 2:
            tag = "counter_combo"
        elif counter:
            tag = reason if reason in ("whiff", "graze") else "counter"
        elif hits >= 2:
            tag = "combo"
        elif "answer_back" in tags:
            tag = "answer_back"
        elif tags.intersection({"heavy", "signature"}):
            tag = "heavy"
        elif "weak_point" in tags and float(row.get("damage", 0) or 0) >= 10.0:
            tag = "weak"
        elif float(row.get("damage", 0) or 0) >= float(min_damage):
            tag = "hit"
        else:
            return None
        return self.make_call(tag, name=name, receiver=receiver, hits=hits, target=target, key=key,
                              side=str(row.get("attacker_side") or ""), receiver_side=str(row.get("receiver_side") or ""),
                              context=self.story.context(row), now=now)

    def report_text(self, report, *, final):
        """A separate script, using the exact numeric payload shown on screen."""
        from commentary_reports import build_report_narration
        return build_report_narration(report, final=final, swearing=self.story.swearing,
                                      callback=self.story.report_callback(dict(report or {}), final=final))

    def decorate(self, base, event, category, *, now):
        """Called only for the winning commentary candidate, not every punch."""
        row = dict(event or {})
        verdict = dict(row.get("_central_event") or {})
        # Read the existing verdict only. Never infer a counter from a phrase.
        counter = bool(verdict.get("counter", row.get("is_counter", False)))
        hits = int(verdict.get("combo_hits", row.get("combo_hits", 0)) or 0)
        reason = str(verdict.get("counter_reason", row.get("counter_reason", "")) or "")
        tags = set(verdict.get("tags", row.get("event_tags", [])) or [])
        if category in ("knockdown", "tko", "stun"):
            tag = category
        elif counter and hits >= 2:
            tag = "counter_combo"
        elif counter:
            tag = reason if reason in ("whiff", "graze") else "counter"
        elif hits >= 2:
            tag = "combo"
        elif "answer_back" in tags:
            tag = "answer_back"
        elif tags.intersection({"heavy", "signature"}):
            tag = "heavy"
        elif "weak_point" in tags:
            tag = "weak"
        else:
            return base
        joke = self.pick(tag, now=now)
        return f"{base} {joke}" if joke else base


def bgrade_demo_steps(*, density="full", swearing="strong"):
    """A deterministic fictional bout; failures stop the preview before callbacks.

    The preview's isolated memory never authorizes stories in a real match.
    """
    from commentary_story import SpokenMemory
    from commentary_calls import SpokenFocus
    from types import SimpleNamespace
    bank = BGradeCommentary()
    bank.story.memory = SpokenMemory()
    bank.story.focus = SpokenFocus()
    bank.story.configure(SimpleNamespace(spectator_bgrade_density=density, spectator_bgrade_swearing=swearing))
    steps = [{"role": "caster", "text": "B급 듀오 리허설입니다. 가상 경기로 반복 반격과 분위기 반전까지 들어봅니다.", "post_ms": 400}]
    for index in range(10):
        reverse = index == 9
        side, receiver = ("red", "blue") if reverse else ("blue", "red")
        row = {"time": 170 - index * 7, "damage": 35, "attacker_side": side, "receiver_side": receiver,
               "event_id": f"demo-{index}", "_central_event": {"counter": True, "counter_reason": "whiff"}}
        bank.story.observe(1, [row])
        if index not in (0, 2, 6, 9):
            continue  # Facts can occur without an announced line; do not fake a spoken seed.
        call = bank.event_call(row, name="현선호" if reverse else "통", receiver="통" if reverse else "현선호", now=1000 + index * 7)
        bank.accept_call(call)
        setup, replies = bank.dialogue_for(call)
        step = {"role": call.role, "text": setup, "post_ms": 400,
                "label": call.presentation["story"]["scene"]}
        if replies:
            step.update(followup_text=replies[0]["text"], followup_role=replies[0]["role"])
        steps.append(step)
        bank.story.memory.complete(call.presentation["story"], now=1000 + index * 7)
        if index == 2 and not bank.story._heard("permission", "blue", now=1014):
            # An explicit preview turn, not an invented broadcast memory. The
            # preview player stops the entire script if any earlier turn fails.
            steps.append({"role": "analyst", "text": "이제 주먹 내밀기 전에 허락받아야겠는데요.",
                          "label": "permission_seed", "post_ms": 400})
            bank.story.memory.complete({"scope": bank.story.scope, "id": "preview-permission",
                "seed": "permission", "side": "blue", "round": 1}, now=1014)
    for index, tag in enumerate(("weak", "combo", "heavy", "stun", "knockdown", "tko")):
        call = bank.make_call(tag, name="통", receiver="현선호", target="명치", hits=5, count=2,
                              key=f"demo-{tag}", now=1070 + index * 7)
        bank.accept_call(call)
        setup, replies = bank.dialogue_for(call)
        step = {"role": call.role, "text": setup, "label": tag, "post_ms": 400}
        if replies:
            step.update(followup_text=replies[0]["text"], followup_role=replies[0]["role"])
        steps.append(step)
    # An analyst-led reaction demonstrates that the personalities can swap.
    steps.extend((
        {"role": "analyst", "text": "와, 저거 봤어요? 방금 저거!", "followup_text": "보고 있습니다. 해설도 좀 해 주세요!", "followup_role": "caster", "post_ms": 500},
        {"role": "caster", "text": "이제 리허설을 마칩니다. 실제 경기에서는 기록이 있을 때만 앞말을 회수합니다.", "post_ms": 300},
    ))
    return steps
