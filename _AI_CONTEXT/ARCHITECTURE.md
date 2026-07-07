# Architecture

## 큰 구조
```text
Qt Settings / Timer UI
  ├─ timerauto.py / MainApp / SettingsDialog
  ├─ config_model.py / AppConfig
  ├─ spectator_log_watcher.py / SpectatorLogWatcher
  ├─ browser_overlay.py / BrowserOverlayServer
  ├─ browser_overlay_sync.py / state publisher
  ├─ diagnostics.py / trace + bug diagnostic ZIP
  └─ ai_project_snapshot.py / AI handoff project snapshot
```

## 책임 분리
- `timerauto.py`: 대부분의 GUI, 설정 적용, watcher 연결, 이벤트 처리, 상태 저장 담당.
- `spectator_log_watcher.py`: 로그 파일을 읽고 정규화된 이벤트/상태로 앱에 전달.
- `browser_overlay.py`: 브라우저 오버레이 HTML/CSS/JS를 제공하고 이벤트를 push.
- `browser_overlay_sync.py`: AppConfig/TimerWindow 상태를 브라우저 상태로 변환해 publish.
- `config_model.py`: 설정 키와 저장/로드 호환성.
- `diagnostics.py`: 앱 흐름 기록과 버그 진단 ZIP.
- `ai_project_snapshot.py`: 새 채팅/다른 AI가 전체 구조를 읽도록 문서/색인 ZIP 생성.

## 새 기능 추가 시 주의
설정 키 추가 시 `AppConfig` dataclass, `from_json`, `to_dict/to_json` 계열을 같이 맞춰야 한다. 오버레이 관련 설정은 Qt 설정 UI → cfg → browser_overlay_sync/push settings → browser_overlay.js 경로까지 이어지는지 확인해야 한다.
