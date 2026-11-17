"""One-click isolated voice-pack job control. No torch or network on the UI thread."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace
import uuid

from app_paths import app_path

PROFILE_ID = "ko_sports_duo_v1"


def _manifest(profile=PROFILE_ID):
    if profile != PROFILE_ID:
        return {}
    try:
        path = Path(app_path(".qwen_duo_profiles", profile, "manifest.json"))
        if path.stat().st_size > 100_000:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("profile") != profile or data.get("status") != "complete":
            return {}
        revision = str(data.get("revision") or "")
        if len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
            return {}
        return data
    except (OSError, ValueError, TypeError):
        return {}


def profile_revision(profile=PROFILE_ID):
    return str(_manifest(profile).get("revision") or "")


def profile_ready(profile=PROFILE_ID, *, revision=None):
    """A success label alone cannot activate an incomplete or outdated pack."""
    manifest = _manifest(profile)
    revision = revision or manifest.get("revision")
    if not manifest or not revision:
        return False
    # Older complete revisions remain usable while a newer one is being built.
    from commentary_pack import catalog, clip_path, ready
    from local_tts import commentary_voice, LocalTTSError
    cfg = SimpleNamespace(spectator_tts_engine="qwen3", spectator_qwen_duo_profile=profile,
                          spectator_qwen_duo_revision=revision)
    try:
        voices = {role: commentary_voice(cfg, role, "") for role in ("caster", "analyst")}
        return all(ready(clip_path(voices[role], text)) for role, text in catalog("full"))
    except (OSError, ValueError, LocalTTSError):
        return False


class DuoSetupJob:
    """Own exactly one child process tree; activation is left to the Qt caller."""
    def __init__(self, cfg):
        self.cfg = cfg
        self.process = None
        self.directory = Path(app_path(".runtime", "qwen_duo_jobs", uuid.uuid4().hex))
        self.progress_path = self.directory / "progress.jsonl"
        self.cancel_path = self.directory / "cancel"
        self._offset = 0
        self._pending = b""
        self._terminal = False
        self._succeeded = False
        self._cancel_at = None
        self._log = None
        self._stopping = False
        self._exit_seen = False
        self._started_at = None
        self._heartbeat_at = 0.
        self._last_progress = {"status": "progress", "done": 0, "total": 0,
                               "message": "격리된 Qwen 설치/모델 환경을 확인하고 있습니다."}

    def start(self):
        if self.process is not None:
            raise RuntimeError("이미 남성 2인 해설팩을 제작 중입니다.")
        launcher = Path(app_path("qwen_duo_launch.ps1"))
        builder = Path(app_path("qwen_duo_builder.py"))
        if not launcher.is_file() or not builder.is_file():
            raise RuntimeError("원클릭 제작 파일이 없습니다. 최신 배포본으로 업데이트해 주세요.")
        self.directory.mkdir(parents=True, exist_ok=False)
        # Only voice-related, non-secret values leave the GUI process.
        keys = ("spectator_qwen_port",)
        config = {key: getattr(self.cfg, key) for key in keys if hasattr(self.cfg, key)}
        job_path = self.directory / "job.json"
        job_path.write_text(json.dumps({"config": config, "device": "auto"}, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                   HF_HOME=app_path(".qwen_models"))
        self._log = (self.directory / "setup.log").open("ab", buffering=0)
        try:
            self.process = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher),
                 "-JobFile", str(job_path), "-ProgressFile", str(self.progress_path), "-CancelFile", str(self.cancel_path)],
                cwd=app_path(), env=env, stdin=subprocess.DEVNULL, stdout=self._log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self._started_at = time.monotonic()
        except Exception:
            self._close_log()
            raise

    def _close_log(self):
        if self._log:
            self._log.close()
            self._log = None

    def _stop_owned_process(self):
        if self.process is None or self.process.poll() is not None:
            return
        if self._stopping:
            return
        self._stopping = True
        threading.Thread(target=self._stop_worker, daemon=True, name="QwenDuoStop").start()

    def _stop_worker(self):
        try:
            if self.process.poll() is not None:
                return
            self._terminate_tree()
        except (OSError, subprocess.TimeoutExpired):
            # No UI-thread blocking or shutdown traceback if a process already
            # exited, or Windows is still releasing a model/download handle.
            pass

    def _terminate_tree(self):
        if os.name == "nt":
            # The exact PID belongs to this job. Never stop other Qwen servers,
            # Python processes, OBS, or the user's broadcast workloads.
            subprocess.run(["taskkill.exe", "/PID", str(self.process.pid), "/T", "/F"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
        else:
            self.process.terminate()

    def cancel(self):
        if self._terminal:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        self.cancel_path.touch(exist_ok=True)
        if self._cancel_at is None:
            self._cancel_at = time.monotonic()

    def close(self):
        """Used when settings/app closes; do not orphan model jobs on the GPU."""
        if not self._terminal:
            self.cancel()
        if not self._succeeded:
            self._stop_owned_process()
        self._close_log()

    def poll(self):
        if self._terminal or self.process is None:
            return []
        records = []
        try:
            with self.progress_path.open("rb") as stream:
                stream.seek(self._offset)
                chunk = stream.read(1_000_000)
                self._offset = stream.tell()
            lines = (self._pending + chunk).split(b"\n")
            self._pending = lines.pop()
            if len(self._pending) > 100_000:
                raise ValueError("제작 진행 기록이 올바르지 않습니다.")
            for line in lines:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict) and row.get("status") in ("progress", "complete", "error", "cancelled"):
                        if row["status"] == "complete" and (
                            row.get("profile") != PROFILE_ID or not row.get("revision")
                            or not profile_ready(PROFILE_ID, revision=row["revision"])):
                            row = {"status": "error", "message": "팩 완성 검증에 실패했습니다. 기존 목소리를 유지합니다. 다시 눌러 이어 만들어 주세요."}
                        if row["status"] == "complete" and self._cancel_at is not None:
                            row = {"status": "cancelled", "message": "중지 요청으로 새 팩을 자동 적용하지 않았습니다. 완성된 파일은 보존됩니다."}
                        records.append(row)
                        if row["status"] == "progress":
                            self._last_progress = row
                        if row["status"] != "progress":
                            self._terminal = True
                            self._succeeded = row["status"] == "complete"
                            break
                except (ValueError, TypeError, UnicodeError):
                    continue
        except FileNotFoundError:
            pass  # Setup/download precedes the first model progress record.
        except (OSError, ValueError) as exc:
            records.append({"status": "error", "message": str(exc)})
            self._terminal = True
        if self._cancel_at is not None and time.monotonic() - self._cancel_at >= 10 and not self._terminal:
            self._stop_owned_process()
        code = self.process.poll()
        if code is not None and not self._terminal and not self._exit_seen:
            # The final append may race the progress-file read above.
            self._exit_seen = True
            return records
        if code is not None and not self._terminal:
            records.append({"status": "cancelled" if self._cancel_at is not None else "error",
                            "message": ("제작을 중지했습니다. 완성된 파일은 다음에 재사용합니다." if self._cancel_at is not None else
                            "제작 프로세스가 완료되지 못했습니다. 기존 목소리를 유지합니다. 설치 기록: " + str(self.directory / "setup.log"))})
            self._terminal = True
        if self._terminal:
            self._close_log()
        elif not records and self._started_at is not None and time.monotonic() - self._heartbeat_at >= 2:
            self._heartbeat_at = time.monotonic()
            elapsed = max(0, int(self._heartbeat_at - self._started_at))
            records.append({**self._last_progress,
                            "message": self._last_progress["message"] +
                            f" · 경과 {elapsed // 60:02d}:{elapsed % 60:02d} (설치 기록: {self.directory / 'setup.log'})"})
        return records
