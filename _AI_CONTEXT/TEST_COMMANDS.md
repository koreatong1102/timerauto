# Test Commands

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
