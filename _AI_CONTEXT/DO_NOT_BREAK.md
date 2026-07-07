# Do Not Break

- SpectatorLog fast hit effect 경로: 피격 이벤트는 해설/리포트보다 먼저 빠르게 오버레이로 가야 한다.
- 타이머 기본 동기화: round_state/round_time 기반 동작을 함부로 바꾸지 말 것.
- 기존 설정 호환성: config.json에 없는 새 키는 안전한 기본값으로 로드되어야 한다.
- 브라우저 오버레이 JS: 수정 후 반드시 추출해서 `node --check` 해야 한다.
- 방송용 안정판을 수정할 때는 전체 구조를 갈아엎기보다 작은 핫픽스를 우선한다.
