# ai_project_snapshot.py
# -*- coding: utf-8 -*-
"""AI handoff / project snapshot exporter.

This module creates a compact ZIP that helps a new ChatGPT conversation or a
new developer understand the whole project quickly.  It is intentionally
separate from diagnostics.py: diagnostics ZIP = bug situation, project snapshot
ZIP = full project handoff/context.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import platform
import time
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from diagnostics import diagnostics as DIAG, _safe_json, _mask_string
except Exception:  # pragma: no cover - diagnostics should never break exports
    DIAG = None

    def _safe_json(value: Any, **_: Any) -> Any:
        try:
            json.dumps(value)
            return value
        except Exception:
            return repr(value)

    def _mask_string(value: str) -> str:
        return str(value)


_SKIP_DIRS = {".git", "__pycache__", "build", "dist", ".venv", "venv", "diagnostics"}
_TEXT_EXTS = {".py", ".qml", ".json", ".md", ".txt", ".ps1", ".bat", ".csv", ".html", ".css", ".js"}
_MANIFEST_EXTS = _TEXT_EXTS | {".png", ".jpg", ".jpeg", ".webp", ".mp3", ".wav", ".ico"}


KNOWN_ROLES = {
    "timerauto.py": "메인 Qt 앱/설정창/타이머/HUD 연결/자동해설/진단 UI",
    "spectator_log_watcher.py": "TOTF2 SpectatorLog 파일 감시 및 파싱",
    "browser_overlay.py": "OBS/PRISM 브라우저 오버레이 서버와 HTML/CSS/JS",
    "browser_overlay_sync.py": "Qt 앱 상태를 브라우저 오버레이 상태로 동기화",
    "config_model.py": "AppConfig 설정 모델, JSON 저장/로드",
    "actions.py": "이벤트 액션/사운드/후킹 실행 로직",
    "hotkey_engine.py": "전역 단축키 감지",
    "player_utils.py": "선수 프로필/이미지/국가 유틸",
    "diagnostics.py": "앱 흐름 기록, 진단 ZIP 생성",
    "ai_project_snapshot.py": "새 채팅/AI 인수인계용 프로젝트 전체 스냅샷 생성",
}


RAW_SAMPLE_FILES = [
    "match/round_state.txt",
    "match/round_time.txt",
    "match/round_number.txt",
    "match/round_total.txt",
    "match/damage_events.txt",
    "match/punches_thrown.txt",
    "match/scores.csv",
    "match/winner.txt",
    "match/camera_input.txt",
    "blue/name.txt",
    "red/name.txt",
    "blue/accessibility.txt",
    "red/accessibility.txt",
    "blue/cosmetics.txt",
    "red/cosmetics.txt",
]


def _read_text(path: str, max_chars: int = 300_000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(max_chars + 1)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...<truncated>"
        return text
    except Exception as exc:
        return f"<read failed: {exc}>"


def _tail_text(path: str, lines: int = 120, max_bytes: int = 512 * 1024) -> str:
    try:
        if not os.path.isfile(path):
            return ""
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(max(0, size - max_bytes))
            data = f.read()
        text = data.decode("utf-8-sig", errors="replace")
        parts = text.splitlines()
        if len(parts) > lines:
            text = "\n".join(parts[-lines:])
        return text
    except Exception as exc:
        return f"<read failed: {exc}>"


def _detect_spectator_format(root: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {"root_exists": bool(root and os.path.isdir(root)), "root": _mask_string(root or "")}
    if not root or not os.path.isdir(root):
        return info
    dmg = os.path.join(root, "match", "damage_events.txt")
    last = ""
    for line in _tail_text(dmg, lines=20).splitlines():
        if line.strip():
            last = line.strip()
    if last:
        parts = last.split("\t")
        info["damage_events_columns"] = len(parts)
        info["damage_events_has_hand_column"] = bool(len(parts) >= 12 and str(parts[3]).lower() in ("left", "right"))
        info["damage_events_last_sample"] = _safe_json(parts, mask_sensitive=True, max_depth=2, max_list=20)
    for rel in ("match/punches_thrown.txt", "match/scores.csv", "match/winner.txt", "match/round_total.txt", "match/camera_input.txt"):
        path = os.path.join(root, *rel.split("/"))
        info[rel.replace("/", "_").replace(".", "_")] = os.path.isfile(path)
    return info


def build_code_index(root: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"root": _mask_string(root), "files": {}}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            try:
                src = _read_text(path, max_chars=2_000_000)
                tree = ast.parse(src)
                classes = []
                functions = []
                imports = []
                for node in tree.body:
                    if isinstance(node, ast.ClassDef):
                        methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                        classes.append({
                            "name": node.name,
                            "line": node.lineno,
                            "methods": methods[:100],
                            "method_count": len(methods),
                        })
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        functions.append({"name": node.name, "line": node.lineno})
                    elif isinstance(node, ast.Import):
                        imports.extend(a.name for a in node.names[:10])
                    elif isinstance(node, ast.ImportFrom):
                        imports.append(("." * int(node.level or 0)) + str(node.module or ""))
                out["files"][rel] = {
                    "role": KNOWN_ROLES.get(rel, KNOWN_ROLES.get(fn, "")),
                    "lines": src.count("\n") + 1,
                    "classes": classes,
                    "functions": functions[:160],
                    "function_count": len(functions),
                    "imports_sample": imports[:60],
                }
            except Exception as exc:
                out["files"][rel] = {"error": str(exc), "role": KNOWN_ROLES.get(rel, KNOWN_ROLES.get(fn, ""))}
    return out


def build_file_manifest(root: str) -> Dict[str, Any]:
    manifest: Dict[str, Any] = {"root": _mask_string(root), "files": []}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in sorted(files):
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            ext = os.path.splitext(fn)[1].lower()
            if ext not in _MANIFEST_EXTS:
                continue
            try:
                st = os.stat(path)
                h = ""
                if st.st_size <= 3 * 1024 * 1024:
                    with open(path, "rb") as f:
                        h = hashlib.sha256(f.read()).hexdigest()[:16]
                manifest["files"].append({"path": rel, "size": st.st_size, "mtime": int(st.st_mtime), "sha256_16": h})
            except Exception as exc:
                manifest["files"].append({"path": rel, "error": str(exc)})
    manifest["count"] = len(manifest["files"])
    return manifest


def extract_config_schema(root: str) -> Dict[str, Any]:
    path = os.path.join(root, "config_model.py")
    result: Dict[str, Any] = {"source": "config_model.py", "fields": []}
    try:
        src = _read_text(path, max_chars=2_000_000)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "AppConfig":
                for stmt in node.body:
                    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                        name = stmt.target.id
                        ann = ast.unparse(stmt.annotation) if hasattr(ast, "unparse") else ""
                        default = None
                        if stmt.value is not None:
                            try:
                                default = ast.literal_eval(stmt.value)
                            except Exception:
                                default = ast.unparse(stmt.value) if hasattr(ast, "unparse") else "<expr>"
                        result["fields"].append({"name": name, "type": ann, "default": _safe_json(default, max_depth=2)})
                break
    except Exception as exc:
        result["error"] = str(exc)
    result["count"] = len(result.get("fields", []))
    return result


def collect_patch_note_heads(root: str, limit: int = 80) -> Dict[str, str]:
    notes: List[tuple] = []
    if not os.path.isdir(root):
        return {}
    for fn in os.listdir(root):
        upper = fn.upper()
        if upper.endswith("_NOTES.MD") or upper in {"HELP.MD", "SIMPLE_MANUAL.MD"}:
            path = os.path.join(root, fn)
            try:
                notes.append((os.path.getmtime(path), fn, path))
            except Exception:
                pass
    notes.sort(reverse=True)
    out: Dict[str, str] = {}
    for _, fn, path in notes[:limit]:
        text = _read_text(path, max_chars=80_000)
        out[fn] = "\n".join(text.splitlines()[:100])
    return out


def make_project_docs(root: str, code_index: Dict[str, Any], file_manifest: Dict[str, Any],
                      config_schema: Dict[str, Any], format_detected: Dict[str, Any]) -> Dict[str, str]:
    py_files = code_index.get("files", {}) if isinstance(code_index, dict) else {}
    key_files = [
        "timerauto.py", "spectator_log_watcher.py", "browser_overlay.py", "browser_overlay_sync.py",
        "config_model.py", "diagnostics.py", "ai_project_snapshot.py", "actions.py", "hotkey_engine.py",
    ]
    roles = []
    for f in key_files:
        info = py_files.get(f, {})
        roles.append(f"- `{f}`: {info.get('role') or '역할 자동 감지 없음'}")
    patch_names = sorted([
        str(x.get("path", "")) for x in file_manifest.get("files", [])
        if str(x.get("path", "")).upper().endswith("_NOTES.MD")
    ])[-50:]
    current_known = (
        "- 초상화 피격 이펙트는 stage40~40b에서 clone 방식으로 수정 중이며 실제 방송 화면 검증이 중요함.\n"
        "- SpectatorLogs2 기준 damage_events는 hand 컬럼 포함 12컬럼이다. 파서가 구버전 11컬럼도 방어해야 함.\n"
        "- 피격 이펙트 fast path, 타이머 기본 동기화, 기존 설정 호환성은 절대 망가뜨리면 안 됨.\n"
        "- stage41부터 진단 ZIP 기능이 들어갔고, stage42부터 AI 프로젝트 스냅샷 기능을 추가함.\n"
    )
    docs: Dict[str, str] = {}
    docs["CHAT_HANDOFF.md"] = f"""# RFC Timer App Chat Handoff

## 새 채팅에서 먼저 할 일
1. 이 파일을 읽는다.
2. `PROJECT_OVERVIEW.md`, `ARCHITECTURE.md`, `EVENT_FLOW.md`, `CODE_INDEX.json` 순서로 본다.
3. 최신 코드 ZIP이 있으면 그 코드를 기준으로 수정한다.
4. 사용자가 '파악만'이라고 하면 절대 수정하지 않는다.

## 현재 앱 목적
TOTF2 / VR 복싱 방송용 Python Qt 타이머 앱. SpectatorLog를 읽어서 타이머, 선수 HUD, 피격 이펙트, KO/TKO/DOWN, 라운드 리포트, 자동해설, OBS/PRISM 브라우저 오버레이를 제어한다.

## 현재 작업 흐름
- 사용자가 채팅에서 버그/디자인/기능을 지적한다.
- AI가 zip을 수정해서 새 stage zip으로 준다.
- 새 채팅 한도 문제 때문에 이 프로젝트 스냅샷을 같이 넘겨 전체 맥락을 복구한다.

## 최근 중요 변경
- stage40: SpectatorLogs2 새 damage_events hand 컬럼 대응, punches_thrown/scores/winner 대응 시작, 초상화 clone FX 실험.
- stage40b: clone 크기/z-index 보정.
- stage41: 진단 탭 / 버그 진단 ZIP 생성 기능 추가.
- stage42: AI 인수인계용 프로젝트 전체 스냅샷 생성 기능 추가.

## 알려진 위험/주의
{current_known}
## 검증 기준
`TEST_COMMANDS.md`를 따른다.
"""
    docs["PROJECT_OVERVIEW.md"] = f"""# Project Overview

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
{chr(10).join(roles)}

## 코드 파일 수
{len(py_files)} Python files. 전체 manifest 파일 수: {file_manifest.get('count')}.
"""
    docs["ARCHITECTURE.md"] = """# Architecture

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
"""
    docs["EVENT_FLOW.md"] = """# Event Flow

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
"""
    docs["SPECTATORLOG_FORMAT.md"] = f"""# SpectatorLog Format Notes

## damage_events v2
현재 SpectatorLogs2 기준 tab-separated 컬럼:
```text
round_time final_damage corner hand screen_x screen_y world_x world_y world_z punch_type damage_type weak_point
```
`hand`가 추가되어 12컬럼이다. 구버전 11컬럼도 방어해야 한다.

## 추가/중요 파일
- `match/punches_thrown.txt`: `round_time corner hand punch_type`
- `match/scores.csv`: 공식 라운드 점수
- `match/winner.txt`: 최종 승자
- `match/round_total.txt`: 총 라운드
- `match/camera_input.txt`: 관전 카메라 입력/머리 숨김 플래그
- `blue|red/accessibility.txt`, `cosmetics.txt`: 선수 설정/외형 정보

## 현재 감지 결과
```json
{json.dumps(format_detected, ensure_ascii=False, indent=2)}
```
"""
    docs["OVERLAY_MAP.md"] = """# Overlay Map

## Browser overlay 핵심
`browser_overlay.py` 안에 HTML/CSS/JS가 문자열로 포함되어 있다. OBS/PRISM 브라우저 소스는 이 서버 페이지를 본다.

## 대표 DOM/이벤트
- `blueImg`, `redImg`: 선수 초상화 이미지
- `bluePortraitFx`, `redPortraitFx`: 과거 초상화 FX 레이어. stage40 이후 clone/이미지 기반 수정이 들어감.
- `screenImpact`: 화면 피격 이펙트 노드 풀
- impact 이벤트: 피격 위치/데미지/side/hand를 받아 화면 폭발 및 초상화 반응 실행

## 초상화 FX 주의
원형 div를 초상화 옆에 띄우는 방식은 실패했다. 실제 초상화 이미지와 픽셀 정렬되는 방식이어야 한다. 크기, z-index, transform, object-fit, left/right/top 값을 실제 이미지에서 복사하는지 확인해야 한다.
"""
    docs["CONFIG_MAP.md"] = f"""# Config Map

`config_model.py`의 `AppConfig`에서 추출한 설정 필드 수: {config_schema.get('count')}.

자세한 전체 목록은 `settings_schema.json`을 본다.

## 진단 관련 주요 설정
- `diagnostics_enabled`
- `diagnostics_trace_minutes`
- `diagnostics_raw_sample_lines`
- `diagnostics_mask_sensitive`

## SpectatorLog/HitFX 관련 설정은 config_model.py와 SettingsDialog의 SpectatorLog/진단 탭을 같이 봐야 한다.
"""
    docs["KNOWN_ISSUES.md"] = "# Known Issues / Current Risks\n\n" + current_known
    docs["DO_NOT_BREAK.md"] = """# Do Not Break

- SpectatorLog fast hit effect 경로: 피격 이벤트는 해설/리포트보다 먼저 빠르게 오버레이로 가야 한다.
- 타이머 기본 동기화: round_state/round_time 기반 동작을 함부로 바꾸지 말 것.
- 기존 설정 호환성: config.json에 없는 새 키는 안전한 기본값으로 로드되어야 한다.
- 브라우저 오버레이 JS: 수정 후 반드시 추출해서 `node --check` 해야 한다.
- 방송용 안정판을 수정할 때는 전체 구조를 갈아엎기보다 작은 핫픽스를 우선한다.
"""
    docs["TEST_COMMANDS.md"] = """# Test Commands

## Python 문법 검사
```bash
python -m py_compile timerauto.py browser_overlay.py spectator_log_watcher.py config_model.py diagnostics.py ai_project_snapshot.py browser_overlay_sync.py actions.py hotkey_engine.py player_utils.py
```

## Browser overlay JS 검사
```bash
python -c "from pathlib import Path; import re; text=Path('browser_overlay.py').read_text(encoding='utf-8'); ms=re.findall(r'<script>(.*?)</script>', text, re.S); Path('extracted_overlay.js').write_text(ms[-1], encoding='utf-8'); print(len(ms), len(ms[-1]))"
node --check extracted_overlay.js
```

## 프로젝트 스냅샷 생성 단독 확인
```bash
python -c "from ai_project_snapshot import export_project_snapshot; print(export_project_snapshot('.', './diagnostics'))"
```
"""
    docs["PATCH_HISTORY.md"] = "# Patch History Heads\n\n최근/주요 패치노트 파일명 일부:\n" + "\n".join(f"- {x}" for x in patch_names[-80:]) + "\n"
    return docs


def export_project_snapshot(project_root: str, output_dir: str, *, app_state: Optional[dict] = None,
                            cfg_snapshot: Optional[Any] = None, spectator_root: str = "",
                            mask_sensitive: bool = True, raw_sample_lines: int = 120) -> str:
    root = os.path.abspath(project_root or os.getcwd())
    os.makedirs(output_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.abspath(os.path.join(output_dir, f"RFC_ProjectSnapshot_{stamp}.zip"))

    code_index = build_code_index(root)
    file_manifest = build_file_manifest(root)
    config_schema = extract_config_schema(root)
    format_detected = _detect_spectator_format(spectator_root)
    docs = make_project_docs(root, code_index, file_manifest, config_schema, format_detected)
    app_state_safe = _safe_json(app_state or {}, mask_sensitive=mask_sensitive, max_depth=6, max_list=180)
    cfg_safe = _safe_json(cfg_snapshot or {}, mask_sensitive=mask_sensitive, max_depth=6, max_list=320)
    trace_snapshot = {}
    try:
        if DIAG is not None:
            trace_snapshot = DIAG.snapshot(mask_sensitive=mask_sensitive)
    except Exception:
        trace_snapshot = {}

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README_FIRST.txt", (
            "RFC Project Snapshot / AI Handoff Package\n"
            "==========================================\n\n"
            "새 채팅에서 프로그램 전체를 빠르게 파악하기 위한 패키지입니다.\n"
            "먼저 CHAT_HANDOFF.md → PROJECT_OVERVIEW.md → ARCHITECTURE.md → EVENT_FLOW.md → CODE_INDEX.json 순서로 보세요.\n"
            "버그 재현용은 RFC_Diagnostic_*.zip이고, 이 파일은 전체 인수인계용입니다.\n"
        ))
        zf.writestr("project_snapshot_meta.json", json.dumps({
            "created_at": stamp,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "project_root": _mask_string(root) if mask_sensitive else root,
            "kind": "ai_project_snapshot",
        }, ensure_ascii=False, indent=2))
        for name, body in docs.items():
            zf.writestr(name, body)
            zf.writestr("_AI_CONTEXT/" + name, body)
        zf.writestr("CODE_INDEX.json", json.dumps(code_index, ensure_ascii=False, indent=2))
        zf.writestr("FILE_MANIFEST.json", json.dumps(file_manifest, ensure_ascii=False, indent=2))
        zf.writestr("settings_schema.json", json.dumps(config_schema, ensure_ascii=False, indent=2))
        zf.writestr("settings_snapshot.json", json.dumps(cfg_safe, ensure_ascii=False, indent=2))
        zf.writestr("app_state.json", json.dumps(app_state_safe, ensure_ascii=False, indent=2))
        zf.writestr("spectator_format_detected.json", json.dumps(format_detected, ensure_ascii=False, indent=2))
        events = trace_snapshot.get("events", []) if isinstance(trace_snapshot, dict) else []
        errors = trace_snapshot.get("errors", []) if isinstance(trace_snapshot, dict) else []
        if isinstance(events, list):
            zf.writestr("recent_trace_tail.jsonl", "\n".join(json.dumps(ev, ensure_ascii=False) for ev in events[-300:]))
        if isinstance(errors, list):
            zf.writestr("recent_errors_tail.jsonl", "\n".join(json.dumps(ev, ensure_ascii=False) for ev in errors[-100:]))
        for rel, content in collect_patch_note_heads(root).items():
            zf.writestr("patch_note_heads/" + rel.replace("/", "__"), content)
        if spectator_root and os.path.isdir(spectator_root):
            for rel in RAW_SAMPLE_FILES:
                path = os.path.join(spectator_root, *rel.split("/"))
                text = _tail_text(path, lines=int(raw_sample_lines or 120))
                if text:
                    if mask_sensitive:
                        text = _mask_string(text)
                    zf.writestr("raw_log_samples/" + rel.replace("/", "__"), text)
    try:
        if DIAG is not None:
            DIAG.record("project_snapshot_exported", path=zip_path)
    except Exception:
        pass
    return zip_path


__all__ = ["export_project_snapshot", "build_code_index", "build_file_manifest", "extract_config_schema"]
