# Stage42 AI Project Snapshot / Chat Handoff

## 목적
채팅 한도 때문에 새 채팅으로 넘어가도 프로그램 전체 구조를 빠르게 파악할 수 있게 `프로젝트 전체 스냅샷 생성` 기능을 추가했다.

## 추가 파일
- `ai_project_snapshot.py`
  - `export_project_snapshot(...)`
  - 코드 인덱스, 파일 manifest, 설정 schema, 주요 문서, 최근 패치노트 heads를 ZIP으로 생성.
- `_AI_CONTEXT/`
  - 코드 ZIP 자체 안에도 최신 인수인계 문서를 포함.

## UI 변경
설정 > 진단 탭에 버튼 추가:
- `프로젝트 전체 스냅샷 생성`

생성 ZIP 예:
- `diagnostics/RFC_ProjectSnapshot_YYYYMMDD_HHMMSS.zip`

## ZIP 안에 들어가는 것
- `CHAT_HANDOFF.md`
- `PROJECT_OVERVIEW.md`
- `ARCHITECTURE.md`
- `EVENT_FLOW.md`
- `SPECTATORLOG_FORMAT.md`
- `OVERLAY_MAP.md`
- `CONFIG_MAP.md`
- `KNOWN_ISSUES.md`
- `DO_NOT_BREAK.md`
- `TEST_COMMANDS.md`
- `CODE_INDEX.json`
- `FILE_MANIFEST.json`
- `settings_schema.json`
- `settings_snapshot.json`
- `app_state.json`
- `recent_trace_tail.jsonl`
- `patch_note_heads/`

## 같이 고친 것
Stage41에서 진단 관련 콜백 메서드가 `MainApp`에 명확히 없어서 설정창에서 호출이 꼬일 수 있는 위험이 있었다. `MainApp`에 `_diagnostic_*` 메서드와 `_project_snapshot_export_zip()`를 명시적으로 추가했다.

## 검증
- `python -m py_compile timerauto.py browser_overlay.py spectator_log_watcher.py config_model.py diagnostics.py ai_project_snapshot.py browser_overlay_sync.py actions.py hotkey_engine.py player_utils.py` 통과
- `browser_overlay.py` 내 JS 추출 후 `node --check` 통과
- `export_project_snapshot('.', './diagnostics')` 단독 생성 테스트 통과
