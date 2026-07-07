# RFC Timer App Chat Handoff

## 새 채팅에서 먼저 할 일
1. 이 파일을 읽는다.
2. `PROJECT_OVERVIEW.md`, `ARCHITECTURE.md`, `EVENT_FLOW.md`, `CODE_INDEX.json` 순서로 본다.
3. 최신 코드 ZIP이 있으면 그 코드를 기준으로 수정한다.
4. 사용자가 '파악만'이라고 하면 절대 수정하지 않는다.

## 현재 앱 목적
TOTF2 / VR 복싱 방송용 Python Qt 타이머 앱. SpectatorLog를 읽어서 타이머, 선수 HUD, 피격 이펙트, KO/TKO/DOWN, 라운드 리포트, 자동해설, OBS/PRISM 브라우저 오버레이를 제어한다.

## 현재 작업 흐름
- 사용자가 채팅에서 버그/디자인/기능을 지적한다.
- AI가 zip을 수정해서 새 stage zip으로 준다.
- 새 채팅 한도 문제 때문에 이 프로젝트 스냅샷을 같이 넘겨 전체 맥락을 복구한다.

## 최근 중요 변경
- stage40: SpectatorLogs2 새 damage_events hand 컬럼 대응, punches_thrown/scores/winner 대응 시작, 초상화 clone FX 실험.
- stage40b: clone 크기/z-index 보정.
- stage41: 진단 탭 / 버그 진단 ZIP 생성 기능 추가.
- stage42: AI 인수인계용 프로젝트 전체 스냅샷 생성 기능 추가.

## 알려진 위험/주의
- 초상화 피격 이펙트는 stage40~40b에서 clone 방식으로 수정 중이며 실제 방송 화면 검증이 중요함.
- SpectatorLogs2 기준 damage_events는 hand 컬럼 포함 12컬럼이다. 파서가 구버전 11컬럼도 방어해야 함.
- 피격 이펙트 fast path, 타이머 기본 동기화, 기존 설정 호환성은 절대 망가뜨리면 안 됨.
- stage41부터 진단 ZIP 기능이 들어갔고, stage42부터 AI 프로젝트 스냅샷 기능을 추가함.

## 검증 기준
`TEST_COMMANDS.md`를 따른다.
