# DOWN_STATE_MACHINE_HOTFIX_NOTES

다운 직후 사운드가 비는 문제를 줄이기 위해 다운 전용 상태 머신을 추가했다.

## 핵심 정책

- 다운은 일반 타격 해설과 분리해서 처리한다.
- 1다운 / 2다운 / 3다운별로 톤과 후보풀을 다르게 쓴다.
- 실제 멘트는 고정이 아니라 후보풀에서 상황 가중 선택한다.
- 후속 멘트는 짧은 예약 큐로만 재생한다.
- 경기 재개, 결과, 종료, 브레이크 전환이 감지되면 남은 다운 후속 멘트는 즉시 취소한다.
- 한 라운드 같은 선수 3다운이면 종료 분위기 멘트로 전환한다.

## 제외한 표현

- 카운트 중계식 표현은 쓰지 않는다.
- 딱딱한 TKO 종료 표현은 쓰지 않는다.
- 모든 다운 후속 멘트는 짧게 유지한다.

## 다운별 톤

- 1다운: 충격 / 회복 가능성 / 위기 탈출
- 2다운: 진짜 위험 / 수비 우선 / 다음 교전 경고
- 3다운: 종료 분위기 / 승부 결정 / 경기 종료

## 기술 메모

- `spectator_log_watcher.py`
  - `_down_round_counts`로 라운드별 피격자 다운 수 추적
  - `_build_knockdown_commentary_plan()` 추가
  - `_cancel_down_commentary()`로 재개/종료 시 캐스터·해설자 예약 멘트 취소
  - `commentary_tts_followups` 리스트 출력 추가

- `timerauto.py`
  - `commentary_tts_followups` 리스트 처리 추가
  - `commentary_tts_stop_roles` 처리 추가
  - 역할별 follow-up epoch를 이용해 예약 멘트 취소
