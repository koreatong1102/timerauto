"""Local, evidence-bound entertainment direction. No new fight verdicts or I/O.

Fact memory observes canonical hits; broadcast memory records completed audio
only. A selected/queued/failed joke can never become an 'as we said' callback.
"""
from collections import OrderedDict, deque
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import threading
import time
import uuid
from commentary_calls import SPOKEN_FOCUS
from commentary_content import plan as content_plan, subject


class SpokenMemory:
    def __init__(self):
        self._lock = threading.RLock()
        self._scopes = OrderedDict()
        self._turns = OrderedDict()

    def complete_turn(self, story, index, *, now=None):
        """Audible content is independent from a fully completed callback seed."""
        if not isinstance(story, dict) or not story.get("scope") or not story.get("id"):
            return
        content = story.get("content") or ()
        if not 0 <= index < len(content):
            return
        with self._lock:
            rows = self._turns.setdefault(story["scope"], deque(maxlen=96))
            key = (story["id"], index)
            if any(row["key"] == key for row in rows):
                return
            rows.append({**content[index], "key": key, "side": story.get("side", ""),
                         "round": story.get("round", 1), "script": story.get("script"),
                         "family": story.get("family"),
                         "completed_at": time.monotonic() if now is None else now})
            self._turns.move_to_end(story["scope"])
            while len(self._turns) > 32:
                self._turns.popitem(last=False)

    def recent_content(self, scope, *, now=None, max_age=120):
        now = time.monotonic() if now is None else now
        with self._lock:
            return [dict(row) for row in self._turns.get(scope, ())
                    if 0 <= now - row["completed_at"] <= max_age]

    def complete(self, story, *, now=None):
        if not isinstance(story, dict) or not story.get("scope") or not story.get("id"):
            return
        for index in range(len(story.get("content") or ())):
            self.complete_turn(story, index, now=now)
        with self._lock:
            rows = self._scopes.setdefault(story["scope"], deque(maxlen=32))
            if any(row["id"] == story["id"] for row in rows):
                return
            rows.append({**story, "completed_at": time.monotonic() if now is None else now})
            self._scopes.move_to_end(story["scope"])
            while len(self._scopes) > 32:
                self._scopes.popitem(last=False)

    def recent(self, scope, *, now=None, max_age=120):
        now = time.monotonic() if now is None else now
        with self._lock:
            return [dict(row) for row in self._scopes.get(scope, ())
                    if 0 <= now - row["completed_at"] <= max_age]


SPOKEN_MEMORY = SpokenMemory()


@dataclass(frozen=True)
class Script:
    lead: str
    reply: str
    family: str
    swear: int = 0
    seed: str = ""
    lead_role: str = "caster"
    topic: str = ""
    intent: str = ""


@lru_cache(maxsize=256)
def script_key(script):
    text = "\0".join((script.lead, script.reply, script.family, str(script.swear), script.seed,
                      script.lead_role, script.topic, script.intent))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


# Complete, authored exchanges. No random profanity/subject/ending assembly.
# '{setup}' is the factual call selected for THIS hit, never another fighter.
SCENES = {
    "whiff": (
        Script("{setup}", "아 씨발, 허공 때린 건데 왜 벌까지 받아요!", "absurd", 2),
        Script("{setup}", "때리러 갔는데 맞고 돌아와요. 저는 저 역할 잘합니다.", "self"),
        Script("{setup}", "헛친 다음이 더 무섭네. 주먹 빼는 동안 또 들어옵니다.", "analysis"),
        Script("{setup}", "야, 헛손질 한 번 했다고 존나 엄격하네요!", "dry", 1),
        Script("{setup}", "안 맞았으면 됐지 굳이 따라가서 때리네. 독합니다!", "reaction"),
        Script("{setup}", "와, 이걸 받아치네. 저는 피했으면 오늘 할 일 다 했어요.", "self"),
        Script("{setup}", "상대 주먹은 빗나갔는데 본인 주먹은 꼬박꼬박 맞힙니다.", "contrast"),
        Script("{setup}", "아니, 헛친 쪽만 더 좆같아졌어요. 공격했는데!", "absurd", 2),
    ),
    "graze": (
        Script("{setup}", "살짝 건드렸잖아요. 이렇게까지 할 일입니까!", "absurd"),
        Script("{setup}", "아 씨발, 받은 만큼만 돌려주라고요!", "reaction", 2),
        Script("{setup}", "이 정도면 먼저 친 쪽도 억울하죠. 내가 더 맞았어!", "contrast"),
        Script("{setup}", "가볍게 맞고 무겁게 칩니다. 손해 보는 건 못 참네요.", "dry"),
        Script("{setup}", "저렇게 돌아오면 다음 주먹은 존나 고민되겠습니다.", "analysis", 1),
        Script("{setup}", "저는 살짝 맞아도 억울한데, 저분은 바로 해결하네요.", "self"),
        Script("{setup}", "살짝 건드렸다가 일이 커졌어요. 아주 크게요.", "dry"),
        Script("{setup}", "미쳤네, 스친 걸로 안 넘어가요. 바로 세게 돌아옵니다!", "reaction", 1),
    ),
    "counter": (
        Script("{setup}", "아 씨발, 때리러 갔다가 왜 내가 맞아요!", "absurd", 2),
        Script("{setup}", "저한테 저 타이밍 물어보지 마세요. 저는 맞는 역할입니다.", "self"),
        Script("{setup}", "주먹 내민 쪽만 억울하죠. 나는 공격했는데!", "contrast"),
        Script("{setup}", "타이밍 개같이 잘 맞추네요. 칭찬입니다, 지금!", "reaction", 2),
        Script("{setup}", "공격했다고 안심하면 안 되죠. 반대편 손은 살아 있어요.", "analysis"),
        Script("{setup}", "저걸 보자마자 때리네. 저는 보고도 어? 하다가 맞습니다.", "self"),
        Script("{setup}", "반격이 존나 빠릅니다. 때린다고 끝나는 게 아니에요.", "reaction", 1),
        Script("{setup}", "선빵 친 쪽이 손해 봤습니다. 기분 나쁘죠 이거.", "dry"),
    ),
    "counter_combo": (
        Script("{setup}", "씨발, 반격 한 대면 됐지 뒤에는 왜 또 와요!", "absurd", 2),
        Script("{setup}", "받아치는 걸로 끝낼 생각이 없네요. 뒤가 더 있습니다.", "analysis"),
        Script("{setup}", "카운터도 맞았는데 연타까지 맞아요. 너무하네 진짜!", "reaction"),
        Script("{setup}", "처음엔 공격했는데 지금은 막느라 존나 바쁩니다.", "contrast", 1),
        Script("{setup}", "저는 첫 카운터에서 이미 아 끝났다 했을 겁니다.", "self"),
        Script("{setup}", "야, 빈틈 하나 났다고 이렇게 많이 때립니까!", "dry"),
        Script("{setup}", "반격 맞았다고 끝난 게 아니죠. 다음 손도 봐야 됩니다.", "analysis"),
        Script("{setup}", "돌았네, 한 번 잡으니까 그냥 안 놔줍니다!", "reaction", 1),
    ),
    "combo": (
        Script("{setup}", "한 대씩 얘기합시다. 왜 몰아서 때려요!", "absurd"),
        Script("{setup}", "끝났나? 안 끝났어요. 씨발, 또 왔어요!", "reaction", 2),
        Script("{setup}", "맞는 쪽에선 저 사이가 존나 길겠죠.", "contrast", 1),
        Script("{setup}", "첫 타에 걸렸다고 끝까지 데려가네요. 끈질겨요.", "dry"),
        Script("{setup}", "저였으면 두 번째부터 숫자 못 셉니다. 그냥 아픕니다.", "self"),
        Script("{setup}", "아, 같이 치는 것보다 일단 이 연타를 끊어야죠.", "analysis"),
        Script("{setup}", "미쳤네, 한 대 맞고 끝날 일이 아니었어요!", "reaction", 1),
        Script("{setup}", "저희가 세는 동안에도 들어갔습니다. 보는 쪽도 바빠요.", "dry"),
    ),
    "heavy": (
        Script("{setup}", "와 씨발, 저는 구경하는데 의자에서 엉덩이 떴어요!", "reaction", 2),
        Script("{setup}", "저건 설명하기 전에 소리부터 나옵니다.", "dry"),
        Script("{setup}", "한 대인데 존재감이 존나 커요. 방금 건 확실합니다!", "reaction", 1),
        Script("{setup}", "저 지금 자세 고쳐 앉았습니다. 구경도 똑바로 해야겠어요.", "self"),
        Script("{setup}", "큰 한 방은 들어갔습니다. 다만 다음 상황까지 봐야죠.", "analysis"),
        Script("{setup}", "미쳤네. 조용히 중계하려고 해도 이런 게 나와요!", "reaction", 1),
        Script("{setup}", "채팅 치던 분들, 방금 거 보셨어요? 저는 봤습니다!", "audience"),
        Script("{name}, 강타 적중! 와, 저거 봤어요?", "보고 있습니다. 해설도 좀 해 주세요!", "banter", 0, lead_role="analyst"),
    ),
    "weak": (
        Script("{setup}", "아 씨발, 하필 거길 딱 맞히네요!", "reaction", 2),
        Script("{setup}", "때리는 쪽은 좋겠죠. 맞는 쪽은 생각이 다를 겁니다.", "contrast"),
        Script("{setup}", "저였으면 지금 복싱보다 말이 먼저 나옵니다.", "self"),
        Script("{setup}", "아무 데나 맞은 게 아니죠. 급소 적중이 찍혔습니다.", "analysis"),
        Script("{setup}", "안 좋은 데는 존나 정확하게 찾네요.", "reaction", 1),
        Script("{setup}", "아, 저 자리는 좀 지켜 줍시다. 또 맞으면 억울해요.", "dry"),
        Script("{setup}", "와, 거기요? 보는 제가 괜히 얼굴에 손이 갑니다.", "self"),
        Script("{setup}", "미쳤네. 그냥 휘두른 주먹이라고 넘길 장면은 아니에요.", "reaction", 1),
        Script("{setup} 아, 저 자리요!", "네, 보고 있습니다. 설명도 이어 주세요!", "banter", 0, lead_role="analyst"),
    ),
    "answer_back": (
        Script("{setup}", "둘 다 마지막 한 대는 자기가 쳐야 돼요. 복싱으로 말싸움합니다.", "absurd"),
        Script("{setup}", "씨발, 맞고 그냥 넘어가는 분들이 아니네요!", "reaction", 2),
        Script("{setup}", "이쪽도 돌려줍니다. 한쪽만 치는 교전이 아니에요.", "analysis"),
        Script("{setup}", "둘 다 먼저 그만둘 생각이 없어요. 저희만 존나 바쁩니다.", "banter", 1),
        Script("{setup}", "한 번씩만 하고 끝날 수는 없는 겁니까!", "dry"),
        Script("{setup}", "저였으면 맞았다는 얘기 하는 동안 또 맞았을 겁니다.", "self"),
    ),
    "hit": (
        Script("{setup}", "이런 한 대를 그냥 주면 나중에 억울하죠.", "analysis"),
        Script("{setup}", "깔끔하게 챙겼습니다. 저희 못 본 척은 안 합니다.", "dry"),
        Script("{setup}", "처음부터 연타가 있습니까. 한 대부터 치는 거죠.", "absurd"),
        Script("{setup}", "저희가 조용해도 맞는 쪽은 조용하지 않겠죠.", "contrast"),
        Script("{setup}", "맞혔어요. 존나 크게 떠들 타격만 기록되는 건 아닙니다.", "dry", 1),
        Script("{setup}", "저도 저렇게 한 대만 깔끔하게 쳐 보고 싶네요.", "self"),
        Script("{setup} 이건 챙겨야죠.", "네, 크게 소리 안 질러도 저희 보고 있습니다!", "banter", 0, lead_role="analyst"),
    ),
    "stun": (
        Script("{setup}", "아, 이거 좆됐는데요. 지금은 다음 한 대 봐야 됩니다!", "reaction", 2),
        Script("{setup}", "여긴 드립 칠 때 아닙니다. 버티는지 봅시다.", "analysis"),
        Script("{setup}", "미쳤네. 지금은 저도 말 줄이겠습니다!", "reaction", 1),
        Script("{setup}", "한 대 더 들어가느냐, 여기서 끊느냐입니다.", "analysis"),
    ),
    "knockdown": (
        Script("{setup}", "와 씨발. 일단 카운트 봅시다!", "reaction", 2),
        Script("{setup}", "아, 카운트부터 봐야 됩니다.", "analysis"),
        Script("{setup}", "미쳤네. 방금은 저도 말이 끊겼어요!", "reaction", 1),
        Script("{setup}", "여기선 더 떠들지 말고 카운트 보죠.", "dry"),
    ),
    "tko": (
        Script("{setup}", "와 씨발, 여기서 끝내 버립니다!", "reaction", 2),
        Script("{setup}", "끝났습니다. 방금 장면부터 다시 봐야겠어요.", "analysis"),
        Script("{setup}", "돌았네. 끝낼 때 이렇게 끝내네요!", "reaction", 1),
        Script("{setup}", "아, 더 갑니까 했는데 여기서 끝났어요!", "contrast"),
    ),
    "repeat_counter": (
        Script("{setup} 또 받아칩니다!", "아 씨발, 아까도 이쪽 카운터였잖아요!", "reaction", 2),
        Script("{setup}", "이제 주먹 내밀기 전에 허락받아야겠는데요.", "dry", 0, "permission"),
        Script("{setup}", "먼저 들어가는 쪽이 계속 맞아요. 저희는 쉽게 들어가라 못 합니다.", "analysis"),
        Script("{setup}", "뭐만 내밀면 돌아와요. 치는 쪽도 존나 고민됩니다.", "contrast", 1),
        Script("{setup}", "저한테 물어보지 마세요. 저는 방금 것도 맞았습니다.", "self"),
        Script("{setup}", "타이밍 개같이 잘 잡네요. 같은 쪽 카운터가 또 찍힙니다.", "reaction", 2),
    ),
    "permission_return": (
        Script("{setup}", "네, 허락 안 받고 또 들어갔네요!", "callback"),
        Script("{setup}", "아까 허락 얘기했잖아요. 무단으로 들어가니까 또 맞죠!", "callback", 1),
        Script("{setup}", "씨발, 허락은 받고 들어가야 된다니까요!", "callback", 2),
    ),
    "permission_reverse": (
        Script("{setup} 이번엔 반대쪽 카운터!", "아, 이번엔 허락 안 받고 들어가도 되네요!", "callback"),
        Script("{setup}", "아까 허락받으라던 쪽도 맞습니다. 여기 예외 없어요!", "callback"),
        Script("{setup}", "씨발, 허락받으라더니 본인도 맞네!", "callback", 2),
    ),
    "reversal": (
        Script("{setup} 이번엔 받아치는 쪽이 바뀝니다!", "당해 보니까 어떻습니까. 아까 그거예요!", "contrast"),
        Script("{setup}", "아 씨발, 카운터 잘 치던 쪽도 카운터를 맞아요!", "reaction", 2),
        Script("{setup}", "받아치던 손만 있는 줄 알았는데 반대쪽 손도 살아 있습니다.", "analysis"),
        Script("{setup}", "이번엔 반대네요. 저희도 한쪽 얘기만 할 수가 없어요.", "dry"),
    ),
    "target_repeat": (
        Script("{setup} 또 같은 부위예요!", "아까부터 저 자리 적중이 많습니다. 우연 한 번은 아니죠.", "analysis"),
        Script("{setup}", "그 자리만 존나 바쁩니다. 다른 얘기를 할 수가 없어요.", "dry", 1),
        Script("{setup}", "아 씨발, 같은 데 또 맞으면 기분 더럽죠!", "reaction", 2),
        Script("{setup}", "저기 적중이 계속 찍혀요. 일단 저 자리부터 지켜야죠.", "analysis"),
    ),
    "eye_seed": (
        Script("{setup}", "눈사냥꾼 얘기 나올 만합니다. 아까부터 눈 쪽 적중이 많아요.", "dry", 0, "eyes"),
        Script("{setup}", "아 씨발, 눈 쪽만 벌써 여러 번입니다. 눈사냥꾼이네.", "reaction", 2, "eyes"),
    ),
    "eye_return": (
        Script("{setup}", "네, 아까 그 눈사냥꾼 맞습니다.", "callback"),
        Script("{setup}", "눈사냥꾼 얘기 괜히 한 게 아니에요. 또 눈입니다.", "callback"),
        Script("{setup}", "씨발, 눈사냥꾼 또 왔어요. 같은 자리예요!", "callback", 2),
    ),
    "long_combo": (
        Script("{setup}", "씨발, 저희가 세는 동안에도 안 끝나요!", "reaction", 2),
        Script("{setup}", "저였으면 두 대부터 숫자 대신 살려 달라 했습니다.", "self"),
        Script("{setup}", "맞는 쪽에선 존나 긴 하루입니다. 아직도 와요!", "contrast", 1),
        Script("{setup}", "연타 끊는 게 먼저죠. 여기에 같이 치면 또 맞습니다.", "analysis"),
        Script("{setup}", "끝난 줄 알았는데 뒤가 더 있었습니다. 돌았네 진짜!", "reaction", 1),
        Script("{setup}", "아니, 한 대씩 얘기하자니까 이렇게 몰아서 옵니다!", "absurd"),
    ),
}


# Short lead, different speaker ownership: not two voices repeating the same
# fact. These remain optional reactions and never override the event call.
SCENES["heavy"] += (
    Script("{setup}", "해설하다가 본인이 먼저 소리 지르셨는데요?", "banter", lead_role="analyst"),
    Script("{setup}", "아 씨발, 방금은 저도 자세 고쳐 앉았어요!", "reaction", 2, lead_role="analyst"),
    Script("{setup}", "네, 그건 길게 설명 안 하셔도 알겠습니다!", "dry", lead_role="analyst"),
)
SCENES["counter"] += (
    Script("{setup}", "저 타이밍 물어보지 마세요. 저는 방금도 못 피했어요.", "self"),
    Script("{setup}", "공격하러 갔는데 영수증은 본인이 받아요. 존나 억울하죠.", "absurd", 1),
    Script("{setup}", "네, 주먹 내민 뒤가 더 무섭습니다!", "analysis", lead_role="analyst"),
)
SCENES["combo"] += (
    Script("{setup}", "한 대씩 주고받자고 했지 묶음으로 보내랬습니까!", "absurd"),
    Script("{setup}", "씨발, 끝났나 싶을 때 한 대가 더 있어요!", "reaction", 2),
    Script("{setup}", "네, 맞는 쪽은 저 숫자 세고 싶지도 않을 겁니다.", "contrast", lead_role="analyst"),
)
SCENES["weak"] += (
    Script("{setup}", "다른 데도 많은데 꼭 아픈 데를 찾네요.", "dry"),
    Script("{setup}", "네, 보는 저도 괜히 거기 손이 갑니다!", "self", lead_role="analyst"),
    Script("{setup}", "아 씨발, 거기는 맞고 웃어넘기기 힘들죠!", "reaction", 2),
)

# Different observations and comic premises, not synonyms of "that hurt".
# No unobserved stance, intent, injury, or result is asserted by these lines.
SCENES["target_repeat"] += (
    Script("{setup}", "같은 부위 적중이 쌓입니다. 이번 것도 거기예요.", "analysis", topic="target_accumulation", intent="pattern"),
    Script("{setup}", "부위는 그대로인데 맞힌 주먹은 또 들어왔어요.", "contrast", topic="target_new_hit", intent="pattern"),
    Script("{setup}", "저 부위만 오늘 출근 도장을 몇 번 찍습니까!", "absurd", topic="target_attendance", intent="humor"),
    Script("{setup}", "단골집도 이렇게 자주 안 가요. 존나 꾸준하네.", "dry", 1, topic="target_regular", intent="humor"),
    Script("{setup}", "맞은 데 또 맞는 건 재방송 아니고 추가 요금이에요.", "absurd", topic="target_extra_charge", intent="humor"),
    Script("{setup}", "여기 주먹 배송지는 변경이 안 됩니까?", "banter", topic="target_address", intent="humor"),
    Script("{setup}", "아 씨발, 아픈 데 기억해 뒀다가 또 보내네!", "reaction", 2, topic="target_return_visit", intent="reaction"),
    Script("{setup}", "저기만 경기 두 판 뛰는 기분이겠어요.", "contrast", topic="target_overtime", intent="humor"),
)
SCENES["weak"] += (
    Script("{setup}", "같은 적중이어도 맞은 자리는 구분해서 봐야죠.", "analysis", topic="target_location", intent="analysis"),
    Script("{setup}", "정확하게 맞혔어요. 세기 말고 위치도 봐 주세요.", "analysis", topic="target_precision", intent="analysis"),
    Script("{setup}", "저는 마우스로 눌러도 저기 한 번에 못 찍어요.", "self", topic="target_mouse_aim", intent="humor"),
    Script("{setup}", "저 자리까지 찍어 주네. 주먹에 내비 달았어요?", "absurd", topic="target_navigation", intent="humor"),
    Script("{setup}", "아 씨발, 맞는 자리에 당첨 운을 다 쓰면 어떡해요!", "absurd", 2, topic="target_lottery", intent="humor"),
    Script("{setup}", "거기 맞는 순간 저는 채팅 칠 손부터 멈춥니다.", "audience", topic="target_chat_freeze", intent="reaction"),
)
SCENES["repeat_counter"] += (
    Script("{setup}", "한 번 반응한 게 아니라 같은 쪽 반격이 쌓입니다.", "analysis", topic="counter_accumulation", intent="pattern"),
    Script("{setup}", "공격을 시작한 쪽보다 받아친 쪽이 눈에 띄네요.", "contrast", topic="counter_attention", intent="pattern"),
    Script("{setup}", "공격 버튼 누르면 반품부터 와요. 존나 빠르네.", "absurd", 1, topic="counter_returns", intent="humor"),
    Script("{setup}", "여기 선불이네. 들어가려면 한 대 내고 가야 돼요.", "dry", topic="counter_toll", intent="humor"),
    Script("{setup}", "주먹 보냈는데 수신 확인이 얼굴로 와요.", "absurd", topic="counter_read_receipt", intent="humor"),
    Script("{setup}", "아 씨발, 공격하는 쪽이 더 긴장되는 경기예요!", "reaction", 2, topic="counter_attacker_tension", intent="reaction"),
)
SCENES["reversal"] += (
    Script("{setup}", "아까 받아치던 쪽이 이번에는 맞았습니다.", "analysis", topic="counter_role_switch", intent="change"),
    Script("{setup}", "이번 반격은 반대편입니다. 한쪽 얘기만 하면 안 되죠.", "analysis", topic="counter_other_side", intent="change"),
    Script("{setup}", "카운터 맛집 사장님도 옆집에서 한 대 드셨네요.", "absurd", topic="counter_owner_customer", intent="humor"),
    Script("{setup}", "반격 치던 분 표정은 몰라도 제 입장은 바뀌었어요.", "self", topic="commentator_reassessment", intent="humor"),
    Script("{setup}", "씨발, 카운터가 독점 사업은 아니었어요!", "absurd", 2, topic="counter_monopoly", intent="humor"),
)
SCENES["combo"] += (
    Script("{setup}", "첫 적중 뒤에 후속타까지 연결했습니다.", "analysis", topic="combo_connection", intent="analysis"),
    Script("{setup}", "주먹은 한 대씩 오는데 결제는 왜 일시불이에요!", "absurd", topic="combo_installment", intent="humor"),
    Script("{setup}", "아 씨발, 닫기 버튼 누르는데 팝업이 또 떠요!", "absurd", 2, topic="combo_popup", intent="humor"),
    Script("{setup}", "연타 얘기하다 제가 말 더듬었네요. 주먹이 더 빠릅니다.", "banter", topic="combo_commentator_race", intent="humor"),
)
SCENES["heavy"] += (
    Script("{setup}", "한 방은 한 방이고, 이걸 연타 숫자로 부르진 않죠.", "analysis", topic="heavy_not_combo", intent="analysis"),
    Script("{setup}", "저 한 대에 제 방송용 침착함이 날아갔어요.", "self", topic="heavy_composure", intent="humor"),
    Script("{setup}", "씨발, 주먹은 저기서 맞는데 왜 제 어깨가 올라가죠!", "reaction", 2, topic="heavy_shoulder", intent="reaction"),
)


IDLE_SCENES = (
    Script("저 지금 소리 지를 준비는 끝났거든요?", "적중부터 나오고 지르세요. 먼저 지르면 사기예요.", "banter"),
    Script("제가 먼저 들어가라고 말씀드리고 싶은데요.", "남이 맞는다고 말 존나 쉽게 하시네.", "banter", 1),
    Script("제가 한번 해도 되겠는데요?", "염병, 마이크나 잡고 계세요.", "banter", 2),
    Script("다음 한 방은 누가 먼저 맞힐까요?", "그걸 알면 제가 여기서 해설하고 있겠습니까.", "self"),
    Script("잠깐 조용합니다. 저희도 숨 좀 돌리죠.", "저희는 앉아서 입만 움직였잖아요.", "banter"),
    Script("아까 한 방 보고 저도 몸에 힘이 들어갔어요.", "몸에 힘 빼세요. 여기선 안 맞습니다.", "banter", 0, "needs_heavy"),
    Script("제가 이런 경기 좋아합니다. 다음에 뭐 나올지 모르거든요.", "그건 원래 모르는 거 아닙니까.", "dry"),
    Script("저도 저 타이밍 보이긴 보이거든요.", "네, 보고 맞는 거죠. 저도 그래요.", "self", 0, "needs_counter"),
    Script("눈 한번 깜빡였는데 중요한 거 놓칠까 봐요.", "그 얘기하는 동안도 앞은 보고 계세요.", "audience"),
    Script("아까는 타격이 여럿 나왔는데 지금은 좀 잠잠하네요.", "저희가 계속 소리 지를 필요는 없죠. 잠깐 같이 봅시다.", "banter", 0, "needs_action"),
    Script("지금은 잠깐 잠잠하네요.", "아까 존나 떠들었으니까 저희도 한 박자 쉽시다.", "dry", 1, "needs_spoken"),
    Script("이럴 때 갑자기 터지면 저도 놀랍니다.", "그럼 같이 놀라죠. 아는 척은 하지 맙시다.", "self"),
)


LATE_SCENES = (
    Script("시간 얼마 안 남았어요. 막판 교전 봅시다!", "지금은 저희 얘기 말고 경기 볼 때죠.", "analysis"),
    Script("라운드 막판입니다. 끝까지 봐야겠어요.", "네, 끝나기 전에 저희가 먼저 정리하지 맙시다.", "dry"),
)


def _num(value):
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


def event_key(row, round_no):
    return (int(round_no or 1), str(row.get("event_id") or row.get("raw_line") or
        (row.get("time"), row.get("damage"), row.get("attacker_side"), row.get("receiver_side"), row.get("hand"), row.get("punch"))))


class MatchStory:
    def __init__(self, memory=SPOKEN_MEMORY):
        self.memory = memory
        self.focus = SPOKEN_FOCUS
        self.reset()

    def reset(self):
        self.scope = uuid.uuid4().hex
        self.round = 1
        self._seen = set()
        self._contexts = OrderedDict()
        self._stats = {}
        self._last_counter = {}
        self._selected = deque(maxlen=32)
        self._serial = 0
        self._rotation = None
        self._accepted_serial = 0
        self._callback_at = -1e9
        self.density, self.swearing = "full", "strong"

    def configure(self, cfg):
        self.density = "compact" if getattr(cfg, "spectator_bgrade_density", "full") == "compact" else "full"
        value = getattr(cfg, "spectator_bgrade_swearing", "strong")
        self.swearing = value if value in ("light", "mixed", "strong") else "strong"

    def observe(self, round_no, events):
        self.round = max(1, int(round_no or 1))
        stats = self._stats.setdefault(self.round, {s: {"counter": 0, "counter_at": None,
            "weak": {}, "landed": 0, "heavy": 0} for s in ("blue", "red")})
        for row in events or ():
            key = event_key(row, self.round)
            if key in self._seen:
                continue
            self._seen.add(key)
            side, receiver = row.get("attacker_side"), row.get("receiver_side")
            if side not in stats or receiver not in stats or side == receiver:
                continue
            if self._rotation is None:
                # Reproducible for the same archive, different opening choices
                # across bouts. Never shuffle words or depend on network state.
                self._rotation = int(hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:8], 16)
            # Non-punch movement records do not change the spoken attacker.
            if str(row.get("punch") or "").lower() not in ("pull", "other") and _num(row.get("damage")) > 0:
                self.focus.observe(self.scope, self.round, side)
            verdict = dict(row.get("_central_event") or {})
            counter = bool(verdict.get("counter", row.get("is_counter", False)))
            weak = str(row.get("weak_point") or "").lower()
            weak = "eyes" if weak in ("eyeleft", "eyeright") else weak
            stamp, damage = _num(row.get("time")), _num(row.get("damage"))
            own, other = stats[side], stats[receiver]
            context = {"side": side, "receiver": receiver, "round": self.round, "weak": weak,
                "counter": own["counter"], "weak_hits": own["weak"].get(weak, 0), "landed": own["landed"],
                "repeat_counter": counter and own["counter"] >= 2 and own["counter_at"] is not None
                    and 0 <= own["counter_at"] - stamp <= 25,
                "reversal": counter and other["counter"] >= 3 and other["counter_at"] is not None
                    and self._last_counter.get(self.round) == receiver
                    and 0 <= other["counter_at"] - stamp <= 35}
            self._contexts[key] = context
            while len(self._contexts) > 128:
                self._contexts.popitem(last=False)
            if counter:
                own["counter"] += 1
                own["counter_at"] = stamp
                self._last_counter[self.round] = side
            if damage >= 10:
                own["landed"] += 1
                if weak:
                    own["weak"][weak] = own["weak"].get(weak, 0) + 1
            if set(verdict.get("tags", row.get("event_tags", ())) or ()).intersection({"heavy", "signature"}):
                own["heavy"] += 1

    def context(self, row):
        return dict(self._contexts.get(event_key(row, self.round), {}))

    def _heard(self, seed, side, *, now):
        return any(item.get("seed") == seed and item.get("side") == side
                   for item in self.memory.recent(self.scope, now=now))

    def _active_seed(self, side, *, now):
        for item in reversed(self.memory.recent(self.scope, now=now)):
            if item.get("side") == side and item.get("seed") in ("permission", "eyes"):
                return item["seed"]
        return ""

    def _pick(self, scripts, *, now):
        heard = [item for item in self.memory.recent(self.scope, now=now)
                 if "content" not in item or len(item["content"]) > 1]
        recent = [item for item in self._selected if 0 <= now - item["at"] < 8]
        used_ids = {item.get("script") for item in recent} | {item.get("script") for item in heard}
        last_use = {}
        for item in recent + heard:
            identity = item.get("script")
            last_use[identity] = max(last_use.get(identity, -1e9), item.get("at", item.get("completed_at", -1e9)))
        last = recent[-1] if recent else (heard[-1] if heard else {})
        maximum = {"light": 0, "mixed": 1, "strong": 2}[self.swearing]
        pool = [(index, script) for index, script in enumerate(scripts) if script.swear <= maximum]
        if not pool:
            return None
        def score(item):
            index, script = item
            identity = script_key(script)
            return (identity not in used_ids, -last_use.get(identity, -1e9), script.family != last.get("family"),
                    script.swear != last.get("swear"), -((index - self._serial - (self._rotation or 0)) % len(scripts)))
        return max(pool, key=score)[1]

    def compose(self, tag, *, setup, name, side="", context=None, hits=0, now=None, brief=False):
        now = time.monotonic() if now is None else now
        ctx = dict(context or {})
        scene = tag
        if tag not in ("stun", "knockdown", "tko"):
            counter = tag in ("whiff", "graze", "counter", "counter_combo")
            completed_callbacks = [item["completed_at"] for item in self.memory.recent(self.scope, now=now)
                                   if item.get("family") == "callback"]
            pending_callbacks = [item["at"] for item in self._selected if item.get("family") == "callback"
                                 and len(item.get("content", ())) > 1 and 0 <= now - item["at"] < 8]
            callback_ready = (now - max(completed_callbacks or [-1e9]) >= 30 and not pending_callbacks)
            if counter and ctx.get("reversal"):
                scene = "permission_reverse" if callback_ready and self._heard("permission", ctx.get("receiver"), now=now) else "reversal"
            elif counter and ctx.get("repeat_counter"):
                scene = "permission_return" if callback_ready and self._heard("permission", side, now=now) else "repeat_counter"
            elif tag == "weak" and ctx.get("weak_hits", 0) >= 3:
                if ctx.get("weak") == "eyes" and ctx["weak_hits"] >= 5 and (ctx["weak_hits"] + 1) / max(1, ctx.get("landed", 0) + 1) >= .3:
                    active = self._active_seed(side, now=now)
                    scene = "eye_return" if callback_ready and active == "eyes" else "target_repeat" if active else "eye_seed"
                else:
                    scene = "target_repeat"
            elif tag in ("combo", "counter_combo") and hits >= 5:
                scene = "long_combo" if tag == "combo" else tag
        pool = SCENES.get(scene, SCENES[tag])
        pool = [script for script in pool if not script.seed or not self._active_seed(side, now=now)] or SCENES[tag]
        if brief:
            pool = [script for script in pool if script.lead.startswith("{setup}")] or pool
        maximum = {"light": 0, "mixed": 1, "strong": 2}[self.swearing]
        pool = [script for script in pool if script.swear <= maximum]
        directed, direction = pool, "authored_exchange"
        if brief:
            directed, direction = content_plan(pool, scene=scene, side=side, round_no=self.round,
                heard=self.memory.recent_content(self.scope, now=now), pending=self._selected,
                now=now, density=self.density, terminal=tag in ("stun", "knockdown", "tko"))
        script = self._pick(directed or pool, now=now)
        turns = [{"role": script.lead_role, "text": setup if brief else script.lead.format(setup=setup, name=name)},
                 {"role": "caster" if script.lead_role == "analyst" else "analyst", "text": script.reply}]
        if brief and (not directed or tag == "hit"):
            turns = turns[:1]
        if not brief and self.density == "compact" and not script.seed and script.family != "callback" and self._serial % 3:
            turns = turns[:1]
        self._serial += 1
        story = {"scope": self.scope, "id": f"{self.scope}:{self._serial}", "round": self.round,
            "scene": scene, "side": side, "seed": script.seed if len(turns) > 1 else "", "family": script.family,
            "swear": script.swear if len(turns) > 1 else 0, "script": script_key(script),
            "direction": direction, "content": [
                {"intent": "call", "topic": f"call:{tag}", "evidence": False},
                *([subject(script, scene)] if len(turns) > 1 else [])]}
        return {"turns": turns, "story": story, "selected_at": now}

    def selected(self, presentation):
        self._accepted_serial += 1
        story = dict(presentation.get("story") or {})
        self._selected.append({**story, "at": presentation.get("selected_at", time.monotonic())})

    def idle(self, *, now=None, seconds_left=None):
        now = time.monotonic() if now is None else now
        stats = self._stats.get(self.round, {})
        action = sum(item.get("landed", 0) for item in stats.values())
        counter = sum(item.get("counter", 0) for item in stats.values())
        heavy = sum(item.get("heavy", 0) for item in stats.values())
        heard = self.memory.recent(self.scope, now=now)
        pool = [script for script in IDLE_SCENES if not script.seed or
                (script.seed == "needs_heavy" and heavy) or (script.seed == "needs_counter" and counter) or
                (script.seed == "needs_action" and action >= 5) or (script.seed == "needs_spoken" and len(heard) >= 2)]
        if seconds_left is not None and 0 <= seconds_left <= 25:
            pool = LATE_SCENES
        maximum = {"light": 0, "mixed": 1, "strong": 2}[self.swearing]
        pool = [script for script in pool if script.swear <= maximum]
        pool, direction = content_plan(pool, scene="idle", side="", round_no=self.round,
            heard=self.memory.recent_content(self.scope, now=now), pending=self._selected,
            now=now, density=self.density)
        if not pool:
            return None
        script = self._pick(pool, now=now)
        self._serial += 1
        story = {"scope": self.scope, "id": f"{self.scope}:{self._serial}", "round": self.round,
            "scene": "idle", "side": "", "seed": "", "family": script.family, "swear": script.swear, "script": script_key(script),
            "direction": direction, "content": [subject(script, "idle"), subject(script, "idle")]}
        return {"turns": [{"text": script.lead, "role": "caster"}, {"text": script.reply, "role": "analyst"}],
                "story": story, "selected_at": now}

    def report_callback(self, report, *, final=False, now=None):
        now = time.monotonic() if now is None else now
        for story in reversed(self.memory.recent(self.scope, now=now, max_age=180)):
            if not final and story.get("round") != int(report.get("round") or 1):
                continue
            data = dict(report.get(story.get("side")) or {})
            if story.get("seed") == "permission" and int(data.get("counterHits") or 0) >= 3:
                return f"아까 주먹 내밀 때 허락 얘기했죠. {data.get('name') or '그 선수'}, 카운터 {int(data['counterHits'])}번입니다. 괜히 한 얘기가 아니에요."
            label = dict(dict(data.get("fightStyle") or {}).get("roundNickname") or {}).get("label")
            if story.get("seed") == "eyes" and label == "눈사냥꾼":
                return "아까 눈사냥꾼 얘기했죠. 리포트에도 찍혔습니다. 저희가 괜히 그 얘기만 한 게 아니에요."
        return ""
