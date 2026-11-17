"""Authored Korean sports-stream material, not a sentence-fragment generator.

The caller supplies the confirmed event as ``{setup}``. These replies interpret
only the named scene. Shared topic keys deliberately join the same joke premise
across scenes so swapping words or fighters cannot defeat repetition control.
No injury, fatigue, stance, intent or unofficial result is inferred here.
"""


def _row(reply, topic, *, family="dry", intent="humor", swear=0,
         short=False, delivery="dry", analyst=False, requires_setup=False):
    return {"lead": "{setup}", "reply": reply, "family": family, "swear": swear,
            "seed": "", "lead_role": "analyst" if analyst else "caster",
            "topic": topic, "intent": intent, "length": "short" if short else "normal",
            "delivery": delivery, "requires_setup": requires_setup}


_MATERIAL = {
    "whiff": (
        _row("헛친 뒤 반격까지 맞았습니다.", "whiff_then_response", family="analysis", intent="analysis", short=True, delivery="neutral"),
        _row("주먹이 빗나간 다음을 잡았어요.", "whiff_opening", family="analysis", intent="analysis", delivery="neutral"),
        _row("민망한 걸로 끝내 주질 않네요.", "whiff_embarrassment"),
        _row("허공은 공짜인데 뒷일이 비싸요.", "counter_toll"),
        _row("샤갈, 빈손으로 갔다 맞고 왔어요!", "whiff_empty_handed", swear=2, delivery="surprised"),
        _row("헛쳤으면 쿨하게 보내 줍시다 좀!", "whiff_no_pardon", family="absurd", analyst=True),
        _row("저라면 헛친 것도 아직 모르죠.", "self_late_reaction", family="self"),
    ),
    "graze": (
        _row("작게 받고 크게 돌려줬어요.", "graze_response_gap", family="analysis", intent="analysis", short=True, delivery="neutral"),
        _row("가벼운 적중 뒤에 반격이 왔습니다.", "graze_sequence", family="analysis", intent="analysis", delivery="neutral"),
        _row("살짝 건드렸다가 일이 커졌네요.", "graze_escalation"),
        _row("잔돈 줬는데 지폐로 돌아와요.", "graze_change", family="absurd"),
        _row("샤갈, 이게 왜 이렇게 돌아와요!", "graze_disproportion", swear=2, delivery="surprised"),
        _row("답장은 좀 살살 써도 되잖아요.", "counter_reply_message", analyst=True),
        _row("저쪽은 답장이 존나 성실하네요.", "counter_reply_message", swear=1),
    ),
    "counter": (
        _row("공격하는 순간을 받아쳤습니다.", "counter_timing", family="analysis", intent="analysis", short=True, delivery="neutral"),
        _row("공격 중에도 반격은 들어옵니다.", "counter_exposure", family="analysis", intent="analysis", delivery="neutral"),
        _row("주먹 내밀 때 영수증도 나오네요.", "counter_receipt", family="absurd"),
        _row("샤갈, 공격했는데 왜 벌을 받아요!", "counter_punishment", swear=2, delivery="surprised"),
        _row("저 타이밍엔 저도 관객입니다.", "self_timing", family="self", short=True),
        _row("복싱인데 반사신경 시험도 봐요.", "counter_exam"),
        _row("네, 지금 건 타이밍으로 봐야죠.", "counter_timing", family="analysis", intent="analysis", analyst=True, delivery="neutral"),
    ),
    "counter_combo": (
        _row("반격과 연타가 한 공방에 나왔어요.", "counter_combo_join", family="analysis", intent="analysis", delivery="neutral"),
        _row("받아치고 연타까지 붙였어요.", "counter_combo_join", family="analysis", intent="analysis", short=True, delivery="neutral"),
        _row("하나 걸렸다고 우르르 몰려오네요.", "combo_crowd", family="absurd"),
        _row("샤갈, 반격에도 추가 옵션이 있어요!", "combo_options", swear=2, delivery="surprised"),
        _row("저는 첫 반격에서 설명 포기해요.", "self_counter_combo", family="self"),
        _row("카운터도 했는데 야근까지 시켜요.", "combo_overtime"),
        _row("네, 반격 한 대로 끝난 게 아니죠.", "counter_combo_followup", family="analysis", intent="analysis", analyst=True, delivery="neutral"),
        _row("받아친 뒤에 한 묶음을 더 줍니다.", "combo_bundle"),
        _row("이건 존나 불친절한 세트 메뉴네요.", "combo_menu", swear=1),
        _row("제가 말 붙일 자리가 없네요.", "commentator_no_gap", family="self", short=True),
    ),
    "combo": (
        _row("한 번 맞히고 후속타를 붙였어요.", "combo_connection", family="analysis", intent="analysis", delivery="neutral"),
        _row("연타 안에서 적중이 이어졌습니다.", "combo_connection", family="analysis", intent="analysis", short=True, delivery="neutral"),
        _row("한 대만 택배 온 게 아니었어요.", "combo_bundle", family="absurd"),
        _row("샤갈, 뒤에 대기 번호가 있어요!", "combo_queue", swear=2, delivery="surprised"),
        _row("저는 두 번째부터 자막 필요해요.", "self_combo_count", family="self"),
        _row("한 대씩 말하라니까 단체로 말해요.", "combo_talking", family="absurd"),
        _row("네, 첫 타보다 연결을 봐야겠네요.", "combo_followup_attention", family="analysis", intent="analysis", analyst=True, delivery="neutral"),
    ),
    "long_combo": (
        _row("이번 공방은 연결이 길었습니다.", "long_combo_length", family="analysis", intent="analysis", short=True, delivery="neutral"),
        _row("첫 적중 뒤에 여러 타가 붙었어요.", "combo_connection", family="analysis", intent="analysis", delivery="neutral"),
        _row("끝맺음을 안 배운 주먹들인가 봐요.", "long_combo_punctuation", family="absurd"),
        _row("샤갈, 다음 손이 자꾸 출근해요!", "combo_overtime", swear=2, delivery="excited"),
        _row("저 같으면 세다가 해설 그만둡니다.", "self_combo_count", family="self"),
        _row("구경하는 제 말도 숨이 차네요.", "commentator_no_gap", family="self", analyst=True),
        _row("이 묶음은 존나 해체가 안 되네요.", "combo_bundle", swear=1),
    ),
    "heavy": (
        _row("이번엔 한 대의 데미지가 큽니다.", "heavy_single_value", family="analysis", intent="analysis", short=True, delivery="neutral"),
        _row("연타 수와 한 방의 무게는 다르죠.", "heavy_not_combo", family="analysis", intent="analysis", delivery="neutral"),
        _row("주먹 한 대가 화면 지분 다 가져가요.", "heavy_screen_share"),
        _row("샤갈, 구경하다 허리가 펴지네요!", "heavy_posture", swear=2, delivery="surprised"),
        _row("저는 방금 의자랑 한 팀 됐어요.", "heavy_chair", family="self"),
        _row("네, 이건 소리 좀 나올 만합니다.", "heavy_reaction", family="reaction", intent="reaction", analyst=True, delivery="surprised"),
        _row("한 대인데 존재감이 존나 진하네요.", "heavy_presence", swear=1),
    ),
    "weak": (
        _row("급소 위치까지 정확히 찍혔습니다.", "target_precision", family="analysis", intent="analysis", short=True, delivery="neutral"),
        _row("타격 세기와 맞힌 위치를 같이 보죠.", "target_location", family="analysis", intent="analysis", delivery="neutral"),
        _row("맞는 자리 뽑기만 운이 좋으면 뭐해요.", "target_lottery", family="absurd"),
        _row("샤갈, 하필 저기 당첨이네요!", "target_lottery", swear=2, delivery="surprised"),
        _row("저는 화면에다 찍으래도 빗나가요.", "target_mouse_aim", family="self"),
        _row("네, 그냥 적중하고는 자리부터 다르죠.", "target_location", family="analysis", intent="analysis", analyst=True, delivery="neutral"),
        _row("주먹이 존나 까다롭게 방문하네요.", "target_navigation", swear=1),
    ),
    "target_repeat": (
        _row("같은 자리 적중이 또 쌓였습니다.", "target_accumulation", family="analysis", intent="pattern", short=True, delivery="neutral"),
        _row("이번 것도 앞서 맞힌 부위입니다.", "target_accumulation", family="analysis", intent="pattern", delivery="neutral"),
        _row("저기만 출석 체크를 몇 번 합니까.", "target_attendance"),
        _row("샤갈, 이 집 주소를 외웠네요!", "target_address", swear=2, delivery="surprised"),
        _row("단골이라고 서비스가 너무 거칩니다.", "target_regular"),
        _row("네, 재방송 아니고 새 적중입니다.", "target_extra_charge", family="analysis", intent="pattern", analyst=True, delivery="neutral"),
        _row("여긴 존나 성실하게 또 오네요.", "target_return_visit", swear=1),
    ),
    "reversal": (
        _row("받아치는 쪽이 바뀌었습니다.", "counter_role_switch", family="analysis", intent="change", short=True, delivery="neutral"),
        _row("앞서 반격하던 선수가 이번엔 맞았죠.", "counter_role_switch", family="analysis", intent="change", delivery="neutral"),
        _row("사장님도 손님으로 한 번 맞네요.", "counter_owner_customer", family="absurd"),
        _row("샤갈, 여기 카운터 독점 안 되네요!", "counter_monopoly", swear=2, delivery="surprised"),
        _row("이쪽도 답장 기능은 있었습니다.", "counter_reply_message"),
        _row("네, 이제 반대편 이야기도 해야죠.", "counter_other_side", family="analysis", intent="change", analyst=True, delivery="neutral"),
        _row("자리 바꾸니까 존나 공평하네요.", "counter_role_fairness", swear=1),
    ),
    "repeat_counter": (
        _row("같은 쪽 반격이 또 나왔습니다.", "counter_accumulation", family="analysis", intent="pattern", short=True, delivery="neutral"),
        _row("한 번이 아니라 반격 적중이 쌓여요.", "counter_accumulation", family="analysis", intent="pattern", delivery="neutral"),
        _row("이쯤 되면 들어갈 때 통행료 있네요.", "counter_toll"),
        _row("샤갈, 뭐만 내면 반품부터 와요!", "counter_returns", swear=2, delivery="surprised"),
        _row("공격 접수처가 너무 불친절합니다.", "counter_punishment"),
        _row("네, 같은 쪽 타이밍이 또 맞았죠.", "counter_timing", family="analysis", intent="pattern", analyst=True, delivery="neutral"),
        _row("답장이 존나 빠른데 읽기는 싫겠죠.", "counter_reply_message", swear=1),
    ),
    "answer_back": (
        _row("맞힌 쪽도 곧바로 돌려받았습니다.", "answer_exchange", family="analysis", intent="change", short=True, delivery="neutral"),
        _row("한쪽 적중으로 끝난 공방은 아니죠.", "answer_exchange", family="analysis", intent="analysis", delivery="neutral"),
        _row("둘 다 마지막 말은 자기가 해야 돼요.", "answer_last_word", family="absurd"),
        _row("샤갈, 주먹으로 댓글 달고 있어요!", "answer_comments", swear=2, delivery="surprised"),
        _row("저는 맞은 얘기 하다가 또 맞아요.", "self_late_reaction", family="self"),
        _row("네, 받은 쪽도 적중으로 답했습니다.", "answer_exchange", family="analysis", intent="change", analyst=True, delivery="neutral"),
        _row("서로 읽씹을 존나 못 하네요.", "answer_comments", swear=1),
    ),
    "counter_release": (
        _row("카운터 뒤에 연타까지 붙였습니다.", "counter_combo_followup", family="analysis", intent="change", short=True, delivery="neutral"),
        _row("받아친 한 대를 연속 적중으로 키웠죠.", "counter_combo_conversion", family="analysis", intent="analysis", delivery="neutral"),
        _row("입장료 냈는데 추가 결제가 붙어요.", "counter_toll", family="absurd"),
        _row("샤갈, 반격 끝에 또 뭐가 달렸어요!", "combo_options", swear=2, delivery="excited"),
        _row("한 대 돌려주고 잔돈까지 얹네요.", "graze_change"),
        _row("네, 반격이 연타의 출발이 됐습니다.", "counter_combo_conversion", family="analysis", intent="change", analyst=True, delivery="neutral"),
        _row("카운터부터 존나 알차게 묶었네요.", "combo_bundle", swear=1),
    ),
    "exchange_return": (
        _row("이번에는 맞던 쪽도 적중했습니다.", "exchange_return", family="analysis", intent="change", short=True, delivery="neutral"),
        _row("앞선 연속 적중 뒤에 반대쪽도 맞혔죠.", "exchange_return", family="analysis", intent="change", delivery="neutral"),
        _row("받기만 하다 보내기 버튼 찾았네요.", "exchange_send_button", family="absurd"),
        _row("샤갈, 이제 이쪽에서도 날아와요!", "exchange_two_way", swear=2, delivery="surprised"),
        _row("제가 한쪽만 떠들 뻔했잖아요.", "commentator_reassessment", family="self"),
        _row("네, 다만 이 한 대로 역전은 아니죠.", "exchange_not_result", family="analysis", intent="analysis", analyst=True, delivery="neutral"),
        _row("받은 편지에 존나 짧게 답장했어요.", "counter_reply_message", swear=1),
    ),
    "target_switch": (
        _row("맞힌 부위가 달라졌습니다.", "target_switch", family="analysis", intent="change", short=True, delivery="neutral"),
        _row("앞서 적중이 쌓인 자리와는 다릅니다.", "target_switch", family="analysis", intent="change", delivery="neutral"),
        _row("단골집 말고 다른 지점도 가네요.", "target_branch", family="absurd"),
        _row("샤갈, 주먹 배송지를 바꿨네요!", "target_address", swear=2, delivery="surprised"),
        _row("아픈 곳 투어는 안 해도 되잖아요.", "target_tour", family="absurd"),
        _row("네, 부위가 바뀌었다는 건 확인돼요.", "target_switch", family="analysis", intent="change", analyst=True, delivery="neutral"),
        _row("방문 구역이 존나 넓어졌네요.", "target_tour", swear=1),
    ),
    "stun": (
        _row("스턴 뒤 다음 공방을 봐야죠.", "stun_next_exchange", family="analysis", intent="analysis", short=True, delivery="neutral"),
        _row("스턴은 나왔지만 끝난 건 아닙니다.", "stun_not_result", family="analysis", intent="analysis", delivery="neutral"),
        _row("지금은 한마디 줄이고 같이 보죠.", "terminal_silence", family="analysis", intent="analysis", short=True, delivery="neutral"),
        _row("저도 모르게 허리를 폈네요.", "heavy_posture", family="self", short=True, delivery="surprised"),
        _row("샤갈, 갑자기 방송 톤이 바뀌네요!", "stun_broadcast_tone", swear=2, delivery="surprised"),
        _row("아, 이 장면은 눈 떼면 안 되겠어요.", "stun_attention", family="audience", intent="reaction", delivery="surprised"),
        _row("드립은 잠깐 접어 두겠습니다.", "terminal_silence", family="dry", intent="reaction", short=True),
        _row("다음 적중이 나오는지 봐야 합니다.", "stun_next_exchange", family="analysis", intent="analysis", delivery="neutral"),
        _row("와, 존나 순식간에 분위기가 달라져요.", "stun_broadcast_tone", family="reaction", intent="reaction", swear=1, delivery="excited"),
        _row("네, 지금은 해설보다 화면이 먼저죠.", "stun_attention", family="analysis", intent="analysis", analyst=True, delivery="neutral"),
        _row("제가 놀랐다고 결과까지 말하진 않죠.", "stun_not_result", family="self", intent="analysis"),
        _row("방금은 저도 말보다 소리가 나왔네요.", "heavy_reaction", family="reaction", intent="reaction", analyst=True, delivery="surprised"),
    ),
    "knockdown": (
        _row("다운입니다. 카운트를 지켜보죠.", "down_count_watch", family="analysis", intent="analysis", short=True, delivery="neutral"),
        _row("일어나는지부터 확인해야 합니다.", "down_recovery_watch", family="analysis", intent="analysis", short=True, delivery="neutral"),
        _row("지금 결과를 먼저 말할 수는 없죠.", "down_not_result", family="analysis", intent="analysis", delivery="neutral"),
        _row("샤갈, 말하다 저도 멈췄네요!", "down_commentator_stop", family="reaction", intent="reaction", swear=2, delivery="surprised"),
        _row("제 드립은 대기실로 보내겠습니다.", "terminal_silence", family="self"),
        _row("와, 방금 장면은 확실히 남겠네요.", "down_memory", family="reaction", intent="reaction", delivery="surprised"),
        _row("이럴 땐 저희가 숫자 위로 말하면 안 되죠.", "down_count_watch", family="analysis", intent="analysis", delivery="neutral"),
        _row("저는 앉아 있는데 같이 굳었어요.", "down_observer_freeze", family="self"),
        _row("아, 이건 존나 숨죽이고 보게 되네요.", "down_observer_freeze", family="reaction", intent="reaction", swear=1, delivery="surprised"),
        _row("네, 재개되는지 카운트부터 봅시다.", "down_recovery_watch", family="analysis", intent="analysis", analyst=True, delivery="neutral"),
        _row("놀란 건 놀란 거고, 판정은 기다리죠.", "down_not_result", family="analysis", intent="analysis", delivery="neutral"),
        _row("마이크보다 카운트가 먼저입니다.", "down_count_watch", family="dry", intent="analysis", short=True, analyst=True),
    ),
    "tko": (
        _row("여기서 경기 종료가 나왔습니다.", "tko_result", family="analysis", intent="analysis", short=True, delivery="neutral"),
        _row("이 장면으로 경기가 끝났습니다.", "tko_finish", family="analysis", intent="analysis", short=True, delivery="neutral"),
        _row("마지막 적중까지 다시 봐야겠어요.", "tko_review", family="analysis", intent="analysis", delivery="neutral"),
        _row("샤갈, 끝맺음까지 맵네요!", "tko_spicy_finish", swear=2, short=True, delivery="excited"),
        _row("끝났다고 하니까 이제 숨이 나오네요.", "tko_observer_release", family="self", intent="reaction"),
        _row("방송용 침착함은 오늘 휴무입니다.", "heavy_composure", family="self"),
        _row("와, 엔딩을 이렇게 찍어 버리네요.", "tko_ending", family="reaction", intent="reaction", delivery="excited"),
        _row("저 장면에 제 설명이 늦었네요.", "commentator_no_gap", family="self", short=True),
        _row("경기 끝입니다. 존나 강렬하게 끝나요.", "tko_ending", family="reaction", intent="reaction", swear=1, delivery="excited"),
        _row("네, 마지막 공방부터 짚어 봐야죠.", "tko_review", family="analysis", intent="analysis", analyst=True, delivery="neutral"),
        _row("이건 마침표가 아니라 느낌표네요.", "tko_punctuation", family="absurd"),
        _row("결과는 나왔고, 기록으로 정리하죠.", "tko_report", family="analysis", intent="analysis", analyst=True, delivery="neutral"),
    ),
}


_CALLS = {
    "counter_release": ("받아치고 연타까지!", "카운터 뒤에도 들어가요!", "반격에서 연타로!", "받아친 뒤 몰아칩니다!"),
    "exchange_return": ("이번엔 이쪽도 맞혀요!", "반대쪽 적중도 나옵니다!", "맞던 쪽도 돌려줍니다!", "이번에는 이쪽 적중!"),
    "target_switch": ("이번엔 다른 부위!", "맞히는 위치가 바뀝니다!", "다른 자리에도 적중!", "이번 적중은 다른 자리!"),
}


def scene_material():
    """Return fresh rows so selection code cannot mutate the authored corpus."""
    return {scene: tuple(dict(row) for row in rows) for scene, rows in _MATERIAL.items()}


def call_material():
    """Exact, complete contextual calls; no numbers or nickname fragments."""
    return dict(_CALLS)
