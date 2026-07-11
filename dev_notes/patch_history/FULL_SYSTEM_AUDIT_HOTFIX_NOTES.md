# FULL SYSTEM AUDIT HOTFIX NOTES

전수 점검 범위:
- 상단 로그감지 토글 / 전체 감지 중지 / 설정창 닫기 시 SpectatorLog watcher 정리 경로
- SettingsDialog 자동적용 / 이벤트 필터 / 중복 정의
- Browser overlay 투명도/VS 배경/표시 설정 전달 경로
- SpectatorLog 자동해설: 듀오 후속, 다운 상태 머신, 재개/종료 시 TTS 취소, 브레이크 요약 시간예산
- build_release.ps1 공개 배포 기본 config 및 필수 파일 검사

발견 및 수정:
1. SettingsDialog.closeEvent 중복 정의로 인해 QApplication eventFilter 제거가 덮어써질 수 있던 문제 수정.
   - 닫을 때 apply_only(silent=True)와 removeEventFilter(self)를 둘 다 수행.
2. SettingsDialog 내부 죽은 중복 함수 정의 정리.
   - _monitor_to_local, _vk_from_key_name, _parse_hotkey, _hotkey_info, _clear_layout 중복 제거.
3. SpectatorLog watcher stop 경로 추가 정리.
   - 설정창 닫기 / 전체 감지 중지 / cfg OFF 상태 보정에서 GUI 스레드 직접 stop을 피하고 async stop 경로 사용.
4. 다운 재개 멘트 톤 보존 수정.
   - 기존에는 down cancel이 먼저 active down state를 비워 2다운 재개 멘트가 일반 톤으로 떨어질 수 있었음.
   - 재개 문구를 먼저 만든 뒤 예약 멘트를 취소하도록 순서 변경.

재확인:
- py_compile 주요 파일 통과.
- SettingsDialog 중복 함수 AST 검사 통과.
- 금지 TTS 문구 `카운트가 들어갑니다`, `TKO로 끝납니다`, `누적됩니다` 잔존 없음.
- `게이지`는 UI 버튼/내부 위험 태그에서만 남고 TTS 출력 문구에는 사용하지 않음.
- build_release.ps1 기본 빌드는 공개 배포용 sanitized config 생성 유지.

주의:
- 이 환경에서는 Windows exe GUI를 직접 클릭 실행할 수 없어 런타임 클릭 테스트는 코드 흐름과 정적 검증으로 대체함.
