from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import queue
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    import aiohttp
except Exception:  # pragma: no cover - handled as a runtime status
    aiohttp = None


OBS_OUTPUT_SUBSCRIPTION = 1 << 6


def build_obs_auth(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(
        hashlib.sha256((str(password or "") + str(salt or "")).encode("utf-8")).digest()
    ).decode("ascii")
    return base64.b64encode(
        hashlib.sha256((secret + str(challenge or "")).encode("utf-8")).digest()
    ).decode("ascii")


@dataclass(frozen=True)
class ObsSettings:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 4455
    password: str = ""

    @classmethod
    def from_config(cls, cfg: Any) -> "ObsSettings":
        return cls(
            enabled=bool(getattr(cfg, "obs_integration_enabled", False)),
            host=str(getattr(cfg, "obs_host", "127.0.0.1") or "127.0.0.1").strip(),
            port=max(1, min(65535, int(getattr(cfg, "obs_port", 4455) or 4455))),
            password=str(getattr(cfg, "obs_password", "") or ""),
        )


class ObsIntegration:
    """Non-blocking obs-websocket v5 client owned by a background thread."""

    def __init__(self, cfg: Any):
        self._cfg = cfg
        self._settings = ObsSettings.from_config(cfg)
        self._commands: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._events: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._status_lock = threading.Lock()
        self._status = "disabled" if not self._settings.enabled else "starting"
        self._pending_replay_requests = deque()

    @property
    def status(self) -> str:
        with self._status_lock:
            return self._status

    def _set_status(self, value: str, detail: str = "") -> None:
        with self._status_lock:
            changed = self._status != value
            self._status = value
        if changed or detail:
            self._events.put({"type": "status", "status": value, "detail": str(detail or "")})

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._thread_main, name="timerauto-obs-websocket", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._commands.put({"type": "stop"})
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    def reconfigure(self, cfg: Any) -> None:
        settings = ObsSettings.from_config(cfg)
        self._cfg = cfg
        if settings == self._settings:
            if settings.enabled and (not self._thread or not self._thread.is_alive()):
                self.start()
            return
        self._settings = settings
        self._commands.put({"type": "reconfigure"})
        if not self._thread or not self._thread.is_alive():
            self.start()

    def test_connection(self) -> None:
        self._commands.put({"type": "test"})
        if not self._thread or not self._thread.is_alive():
            self.start()

    def save_replay(self, reason: str = "", *, context: Optional[Dict[str, Any]] = None) -> None:
        if not self._settings.enabled:
            return
        self._commands.put(
            {
                "type": "request",
                "requestType": "SaveReplayBuffer",
                "reason": str(reason or ""),
                "context": dict(context or {}),
            }
        )

    def ensure_replay_buffer(self) -> None:
        if not self._settings.enabled:
            return
        self._commands.put({"type": "request", "requestType": "GetReplayBufferStatus"})

    def drain_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for _ in range(max(1, int(limit or 1))):
            try:
                result.append(self._events.get_nowait())
            except queue.Empty:
                break
        return result

    def _thread_main(self) -> None:
        if aiohttp is None:
            self._set_status("error", "aiohttp unavailable")
            return
        try:
            asyncio.run(self._run())
        except Exception as exc:
            logging.exception("OBS integration thread failed")
            self._set_status("error", type(exc).__name__)

    async def _run(self) -> None:
        reconnect_delay = 1.0
        while not self._stop.is_set():
            settings = self._settings
            if not settings.enabled:
                self._set_status("disabled")
                await self._wait_for_command(0.5)
                continue
            try:
                await self._connected_loop(settings)
                reconnect_delay = 1.0
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._set_status("disconnected", str(exc)[:160])
                logging.warning("OBS websocket disconnected: %s", exc)
                await self._wait_for_command(reconnect_delay)
                reconnect_delay = min(10.0, reconnect_delay * 1.7)

    async def _wait_for_command(self, timeout: float) -> Optional[Dict[str, Any]]:
        try:
            return await asyncio.to_thread(self._commands.get, True, max(0.05, float(timeout)))
        except queue.Empty:
            return None

    async def _connected_loop(self, settings: ObsSettings) -> None:
        url = f"ws://{settings.host}:{settings.port}"
        timeout = aiohttp.ClientTimeout(total=None, connect=4.0, sock_read=None)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(url, heartbeat=15.0, autoclose=True) as ws:
                hello_msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                if hello_msg.type != aiohttp.WSMsgType.TEXT:
                    raise RuntimeError("OBS did not send Hello")
                hello = json.loads(hello_msg.data)
                if int(hello.get("op", -1)) != 0:
                    raise RuntimeError("Invalid OBS Hello")
                identify: Dict[str, Any] = {
                    "rpcVersion": int((hello.get("d") or {}).get("rpcVersion", 1) or 1),
                    "eventSubscriptions": OBS_OUTPUT_SUBSCRIPTION,
                }
                auth = (hello.get("d") or {}).get("authentication") or {}
                if auth:
                    if not settings.password:
                        raise RuntimeError("OBS password required")
                    identify["authentication"] = build_obs_auth(
                        settings.password, str(auth.get("salt") or ""), str(auth.get("challenge") or "")
                    )
                await ws.send_json({"op": 1, "d": identify})
                identified_msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                if identified_msg.type != aiohttp.WSMsgType.TEXT:
                    raise RuntimeError("OBS identification failed")
                identified = json.loads(identified_msg.data)
                if int(identified.get("op", -1)) != 2:
                    raise RuntimeError("OBS authentication rejected")
                self._pending_replay_requests.clear()
                self._set_status("connected")
                await self._send_request(ws, "GetStreamStatus", request_id="startup-stream")
                await self._session_loop(ws, settings)

    async def _session_loop(self, ws: Any, connected_settings: ObsSettings) -> None:
        while not self._stop.is_set():
            if self._settings != connected_settings:
                return
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=0.1)
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(ws, json.loads(msg.data))
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    raise RuntimeError("OBS connection closed")
            except asyncio.TimeoutError:
                pass

            # Drain commands without spawning cancellable blocking workers.
            # This loop stays off the Qt thread and never delays overlay SSE.
            while True:
                try:
                    command = self._commands.get_nowait()
                except queue.Empty:
                    break
                kind = str(command.get("type") or "")
                if kind in ("stop", "reconfigure"):
                    return
                if kind == "test":
                    await self._send_request(ws, "GetVersion", request_id="connection-test")
                elif kind == "request":
                    request_type = str(command.get("requestType") or "")
                    request_id = await self._send_request(
                        ws, request_type, reason=str(command.get("reason") or "")
                    )
                    if request_type == "SaveReplayBuffer" and request_id:
                        self._pending_replay_requests.append(
                            {
                                "request_id": request_id,
                                "reason": str(command.get("reason") or ""),
                                "context": dict(command.get("context") or {}),
                            }
                        )

    async def _send_request(self, ws: Any, request_type: str, *, request_id: str = "", reason: str = "") -> str:
        if not request_type:
            return ""
        rid = request_id or uuid.uuid4().hex
        await ws.send_json({"op": 6, "d": {"requestType": request_type, "requestId": rid}})
        if reason:
            self._events.put({"type": "request_sent", "requestType": request_type, "reason": reason})
        return rid

    async def _handle_message(self, ws: Any, message: Dict[str, Any]) -> None:
        op = int(message.get("op", -1))
        data = message.get("d") or {}
        if op == 5:
            event_type = str(data.get("eventType") or "")
            event_data = data.get("eventData") or {}
            if event_type == "StreamStateChanged":
                active = bool(event_data.get("outputActive", False))
                self._events.put({"type": "stream_state", "active": active})
            elif event_type == "ReplayBufferSaved":
                pending = self._pending_replay_requests.popleft() if self._pending_replay_requests else {}
                self._events.put(
                    {
                        "type": "replay_file_saved",
                        "path": str(event_data.get("savedReplayPath") or ""),
                        "reason": str(pending.get("reason") or ""),
                        "context": dict(pending.get("context") or {}),
                    }
                )
        elif op == 7:
            request_type = str(data.get("requestType") or "")
            status = data.get("requestStatus") or {}
            ok = bool(status.get("result", False))
            if request_type == "GetStreamStatus" and ok:
                response = data.get("responseData") or {}
                self._events.put({"type": "stream_state", "active": bool(response.get("outputActive", False))})
            elif request_type == "GetVersion":
                self._events.put({"type": "test_result", "ok": ok, "message": str(status.get("comment") or "")})
            elif request_type == "GetReplayBufferStatus":
                response = data.get("responseData") or {}
                active = bool(response.get("outputActive", False)) if ok else False
                self._events.put(
                    {
                        "type": "replay_buffer_status",
                        "ok": ok,
                        "active": active,
                        "message": str(status.get("comment") or ""),
                    }
                )
                if ok and not active:
                    await self._send_request(ws, "StartReplayBuffer", request_id="auto-start-replay-buffer")
            elif request_type == "StartReplayBuffer":
                self._events.put(
                    {"type": "replay_buffer_started", "ok": ok, "message": str(status.get("comment") or "")}
                )
            elif request_type == "SaveReplayBuffer":
                self._events.put({"type": "replay_saved", "ok": ok, "message": str(status.get("comment") or "")})
                if not ok:
                    request_id = str(data.get("requestId") or "")
                    self._pending_replay_requests = deque(
                        item for item in self._pending_replay_requests
                        if str(item.get("request_id") or "") != request_id
                    )
