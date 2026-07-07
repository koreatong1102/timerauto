# Event Flow

## SpectatorLog → 피격 이펙트
```text
SpectatorLog damage_events.txt 변경
→ spectator_log_watcher.py가 새 행 파싱
→ hand/screen/world/punch_type/damage_type/weak_point 정규화
→ timerauto.py fast path가 즉시 browser overlay impact 이벤트 push
→ browser_overlay.py JS showScreenImpact + portrait FX 실행
→ 라운드 통계/해설/리포트는 후속 경로에서 처리
```

## 타이머 동기화
```text
match/round_state.txt, round_time.txt, round_number.txt, round_total.txt
→ spectator_log_watcher.py
→ timerauto.py
→ TimerWindow/QML + BrowserOverlaySync
```

## 진단/인수인계 흐름
```text
DIAG.record(...)
→ recent_trace ring buffer
→ 설정 > 진단 > 문제 발생 표시 / 진단 ZIP 생성
→ 설정 > 진단 > 프로젝트 스냅샷 생성
→ 새 채팅에는 최신 코드 ZIP + RFC_ProjectSnapshot_*.zip 업로드
```
