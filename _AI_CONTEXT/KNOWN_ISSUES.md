# Known Issues / Current Risks

- 초상화 피격 이펙트는 stage40~40b에서 clone 방식으로 수정 중이며 실제 방송 화면 검증이 중요함.
- SpectatorLogs2 기준 damage_events는 hand 컬럼 포함 12컬럼이다. 파서가 구버전 11컬럼도 방어해야 함.
- 피격 이펙트 fast path, 타이머 기본 동기화, 기존 설정 호환성은 절대 망가뜨리면 안 됨.
- stage41부터 진단 ZIP 기능이 들어갔고, stage42부터 AI 프로젝트 스냅샷 기능을 추가함.
