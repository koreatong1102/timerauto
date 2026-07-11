# ROUND_REPORT_VISUAL_FIRST_PASS_NOTES

기준: 사용자가 정상 후보로 올린 `10.zip` (`rebase_from_5_clean_work`)에서 최소 패치.

이번 패치 범위:
- `spectator_log_watcher.py`: `damage_events.txt` 기반 라운드 리포트 payload 생성.
- `timerauto.py`: `spectator_round_report`를 OBS 브라우저 오버레이 이벤트로 전달.
- `browser_overlay.py`: `round_report` 이벤트 수신 시 브레이크용 라운드 리포트 카드 표시.

의도:
- 던진 수가 아니라 로그상 정확한 적중 수만 사용.
- `corner`는 피격자이므로 attacker는 반대 코너로 계산.
- 라운드별 총 적중, 총 데미지, 펀치 타입 TOP 3, 약점 피격 TOP 3 표시.
- 쉬는시간용으로 정보량을 압축한 카드만 표시. 경기 전체 대시보드는 아직 넣지 않음.

건드리지 않은 것:
- SettingsDialog / 설정창 구조.
- build_release.ps1.
- QML timer_ui.qml.
- TTS 큐/해설 문장 생성 로직.
- VS 오버레이 트리거 정책.
- 초상화 우선순위 정책.

검증:
- `python -m py_compile spectator_log_watcher.py timerauto.py browser_overlay.py config_model.py app_paths.py runtime_support.py` 통과.
- 브라우저 오버레이 JS 추출 후 `node --check` 통과.
- 이 환경에는 PyQt6가 없어 실제 Windows GUI/OBS 실행 검증은 하지 못함.
