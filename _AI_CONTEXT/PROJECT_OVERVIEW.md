# Project Overview

## 한 줄 설명
RFC Timer App은 TOTF2 SpectatorLog와 방송 오버레이를 연결하는 VR 복싱 방송 운영 도구다.

## 주요 기능
- Python/Qt 타이머 및 설정 UI
- QML/브라우저 오버레이 출력
- OBS/PRISM 브라우저 소스용 HUD
- SpectatorLog 파일 감시와 피격/펀치/점수 파싱
- 화면 피격 이펙트, 초상화 피격 이펙트, KO/TKO/DOWN 이펙트
- 라운드 리포트와 자동해설/TTS 연동
- 선수 프로필/이미지/국가 설정
- stage41 진단 ZIP, stage42 프로젝트 스냅샷

## 핵심 파일
- `timerauto.py`: 메인 Qt 앱/설정창/타이머/HUD 연결/자동해설/진단 UI
- `spectator_log_watcher.py`: TOTF2 SpectatorLog 파일 감시 및 파싱
- `browser_overlay.py`: OBS/PRISM 브라우저 오버레이 서버와 HTML/CSS/JS
- `browser_overlay_sync.py`: Qt 앱 상태를 브라우저 오버레이 상태로 동기화
- `config_model.py`: AppConfig 설정 모델, JSON 저장/로드
- `diagnostics.py`: 앱 흐름 기록, 진단 ZIP 생성
- `ai_project_snapshot.py`: 새 채팅/AI 인수인계용 프로젝트 전체 스냅샷 생성
- `actions.py`: 이벤트 액션/사운드/후킹 실행 로직
- `hotkey_engine.py`: 전역 단축키 감지

## 코드 파일 수
15 Python files. 전체 manifest 파일 수: 136.
