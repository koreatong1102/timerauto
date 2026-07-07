# Stage41 - Diagnostic Package / App Flow Recorder

## 추가 기능

### 1. 진단 탭 추가
설정창에 `진단` 탭을 추가했습니다.

버튼:
- `문제 발생 표시`
- `진단 ZIP 생성`
- `현재 상태 복사`
- `진단 폴더 열기`

설정:
- 앱 흐름 기록 켜기
- 개인정보/경로 가리고 내보내기
- 최근 기록 보관 분
- 원본 로그 샘플 줄 수

### 2. diagnostics.py 추가
앱 내부 흐름을 ring buffer로 보관하고, 필요할 때 ZIP으로 내보내는 독립 모듈을 추가했습니다.

생성 ZIP 주요 파일:
- `README.txt`
- `diagnostic_meta.json`
- `app_state.json`
- `settings_snapshot.json`
- `recent_trace.jsonl`
- `recent_errors.jsonl`
- `incidents.json`
- `overlay_snapshot.json`
- `spectator_format_detected.json`
- `raw_log_samples/*`

### 3. 기록되는 흐름
- 앱 시작
- SpectatorLog watcher 시작/중지
- damage_events 파일 변경 감지
- SpectatorLog update emit
- UI update 적용 흐름
- hit FX fast push
- browser overlay event push
- 사용자 문제 발생 표시
- 진단 ZIP 생성

### 4. 목적
버그/업그레이드 요청 시 코드 ZIP만 넘기는 게 아니라, 실제 앱 흐름과 SpectatorLog 샘플이 같이 들어있는 진단 ZIP을 넘겨 원인 파악 속도를 높이기 위한 기능입니다.

## 검사
- `python -m py_compile diagnostics.py config_model.py browser_overlay.py spectator_log_watcher.py timerauto.py` 통과
- `node --check extracted_overlay_stage41.js` 통과
- diagnostics export smoke test 통과
