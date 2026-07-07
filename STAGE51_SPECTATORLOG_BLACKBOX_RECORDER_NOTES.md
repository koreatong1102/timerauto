# Stage51 SpectatorLog Blackbox Recorder

## 목적

관전툴 SpectatorLog 폴더는 append-only 로그가 아니라, 많은 파일이 한 줄 상태값으로 계속 덮어써지고 일부 파일은 생성됐다가 삭제된다. 그래서 경기 종료 후 폴더를 한 번 복사하면 `lobby.txt`처럼 사라진 파일이나 `camera.txt`/`round_time.txt`처럼 과거 값이 지워진 파일을 분석할 수 없다.

Stage51은 프로그램이 현재 사용하지 않는 파일까지 포함해 SpectatorLog 폴더 전체를 블랙박스처럼 기록한다.

## 핵심 원칙

- `snapshots/` 안의 raw 파일은 원본 bytes 그대로 복사한다.
- raw 스냅샷 파일 안에는 timestamp, event type, path 같은 메타데이터를 절대 삽입하지 않는다.
- 생성/수정/삭제/샘플링 시각과 스냅샷 경로는 `events.jsonl`에만 기록한다.
- 삭제되는 파일은 마지막 raw snapshot을 `deleted_last_snapshots/`에 따로 복사한다.
- 현재 마지막 상태는 `latest_snapshot/`에 원본 폴더 구조 그대로 복사한다.

## 저장 위치

기본값:

```txt
SpectatorLogArchive/<YYYYMMDD_HHMMSS_session>/
```

## 저장 구조

```txt
manifest.json
 events.jsonl
 snapshots/
 latest_snapshot/
 deleted_last_snapshots/
```

## 고빈도 파일 처리

기본 `smart` 모드에서는 아래 파일들을 고빈도 파일로 보고 250ms 간격으로 샘플링한다.

- `camera.txt`
- `camera_input.txt`
- `round_time.txt`
- `head_position.txt`
- `glove_left_position.txt`
- `glove_right_position.txt`
- `punishment_mid.txt`
- `punishment_long_raw.txt`
- `punishment_long_weighted.txt`

## 설정값

```json
{
  "spectatorlog_blackbox_enabled": true,
  "spectatorlog_blackbox_dir": "SpectatorLogArchive",
  "spectatorlog_blackbox_mode": "smart",
  "spectatorlog_blackbox_poll_ms": 100,
  "spectatorlog_blackbox_sample_ms": 250,
  "spectatorlog_blackbox_max_snapshot_mb": 64,
  "spectatorlog_blackbox_zip_on_close": false
}
```

모드:

- `light`: create/delete와 주요 이벤트 파일 위주
- `smart`: 기본 추천. 이벤트 파일은 즉시 저장, 고빈도 파일은 샘플링
- `full`: 모든 변경을 최대한 저장. 디버그용

## 변경 파일

- `spectator_log_blackbox.py` 추가
- `spectator_log_watcher.py`에 blackbox poll/close 연결
- `config_model.py`에 설정값 추가
- `config.json`에 기본 설정 추가

## 검사

```txt
python3 -m py_compile spectator_log_blackbox.py spectator_log_watcher.py config_model.py timerauto.py diagnostics.py browser_overlay.py browser_overlay_sync.py
```

통과.
