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
from urllib.parse import urlparse

try:
    import aiohttp
except Exception:  # pragma: no cover - handled as a runtime status
    aiohttp = None


OBS_OUTPUT_SUBSCRIPTION = 1 << 6
BROWSER_OVERLAY_PORT = 17872


def is_timerauto_browser_overlay_url(value: str) -> bool:
    """Return whether an OBS browser input points at this app's overlay.

    Only the loopback overlay on the app's fixed HTTP port is accepted.  This
    deliberately avoids changing audio routing for the broadcaster's other
    browser sources (alerts, chat, widgets, and so on).
    """
    try:
        parsed = urlparse(str(value or "").strip())
        host = str(parsed.hostname or "").lower()
        return host in {"127.0.0.1", "localhost", "::1"} and int(parsed.port or 0) == BROWSER_OVERLAY_PORT
    except Exception:
        return False


def source_record_hotkey_context(target_name: str) -> str:
    """Return the OBS hotkey context used by Source Record's replay save.

    The Settings UI intentionally stores the scene/source name (for example
    ``장면 2``), because that is what the broadcaster sees in OBS.  Source
    Record registers its save hotkey under the *filter* context instead:
    ``장면 2 - Source Record``.  Keeping this conversion here makes automatic
    WebSocket saves work without asking the user to type OBS's internal name.

    A full context is still accepted for installations whose filter was named
    something other than the default ``Source Record``.
    """
    value = str(target_name or "").strip()
    if not value:
        return ""
    if value.casefold().endswith(" - source record"):
        return value
    return f"{value} - Source Record"


def source_record_source_name(target_name: str) -> str:
    """Convert the UI's Source Record context back to the OBS source name."""
    value = str(target_name or "").strip()
    suffix = " - source record"
    if value.casefold().endswith(suffix):
        return value[: -len(suffix)].strip()
    return value


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
        self._pending_input_mute_requests: Dict[str, Dict[str, Any]] = {}
        self._pending_input_settings_requests: Dict[str, str] = {}

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
            # OBS may already be connected when the user enables either
            # automation checkbox. Queue the idempotent start requests again.
            self.ensure_capture_outputs()
            return
        self._settings = settings
        self._commands.put({"type": "reconfigure"})
        if not self._thread or not self._thread.is_alive():
            self.start()
        self.ensure_capture_outputs()

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

    def save_source_record_replay(
        self,
        context_name: str,
        reason: str = "",
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Save a Source Record plugin replay buffer through OBS WebSocket."""
        hotkey_context = source_record_hotkey_context(context_name)
        if not self._settings.enabled or not hotkey_context:
            return
        logging.info("OBS_SOURCE_RECORD_SAVE_REQUEST context=%s", hotkey_context)
        self._commands.put(
            {
                "type": "request",
                "requestType": "TriggerHotkeyByName",
                "requestData": {
                    "hotkeyName": "ReplayBuffer.Save",
                    "contextName": hotkey_context,
                },
                "reason": str(reason or ""),
                "context": dict(context or {}),
                "source_record": True,
            }
        )

    def set_source_record_enabled(self, target_name: str, enabled: bool = True) -> None:
        """Idempotently enable/disable the default Source Record filter."""
        source_name = source_record_source_name(target_name)
        if not self._settings.enabled or not source_name:
            return
        self._commands.put(
            {
                "type": "request",
                "requestType": "SetSourceFilterEnabled",
                "requestData": {
                    "sourceName": source_name,
                    "filterName": "Source Record",
                    "filterEnabled": bool(enabled),
                },
                "source_record_filter": True,
                "source_record_source": source_name,
            }
        )

    def ensure_replay_buffer(self) -> None:
        if not self._settings.enabled:
            return
        self._commands.put({"type": "request", "requestType": "GetReplayBufferStatus"})

    def ensure_capture_outputs(self) -> None:
        """Make capture buffers and browser-overlay audio ready; idempotent."""
        if not self._settings.enabled:
            return
        if (bool(getattr(self._cfg, "obs_replay_buffer_enabled", False))
                and bool(getattr(self._cfg, "obs_replay_buffer_auto_start", True))):
            self.ensure_replay_buffer()
        if (bool(getattr(self._cfg, "obs_source_record_enabled", False))
                and bool(getattr(self._cfg, "obs_source_record_auto_enable", True))):
            target = str(getattr(self._cfg, "obs_source_record_context", "") or "").strip()
            if target:
                self.set_source_record_enabled(target, True)
        # With OBS's browser-source audio control disabled, Chromium sends the
        # sound to the Windows playback device: the operator hears it, but OBS
        # may not.  Discover our one loopback overlay source and route it into
        # the OBS mixer instead.  The response handler also disables local
        # monitoring, so stream/program audio remains audible without echoing
        # on the broadcast PC.
        self._commands.put({"type": "request", "requestType": "GetInputList"})

    def get_input_mute(self, input_name: str, *, context: Optional[Dict[str, Any]] = None) -> None:
        if not self._settings.enabled or not str(input_name or "").strip():
            return
        self._commands.put({"type": "input_mute_get", "inputName": str(input_name).strip(), "context": dict(context or {})})

    def set_input_mute(self, input_name: str, muted: bool) -> None:
        if not self._settings.enabled or not str(input_name or "").strip():
            return
        self._commands.put({"type": "request", "requestType": "SetInputMute", "requestData": {"inputName": str(input_name).strip(), "inputMuted": bool(muted)}})

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
                self._pending_input_settings_requests.clear()
                self._set_status("connected")
                # Do this in the websocket worker as well as from the UI. It
                # removes any dependency on Qt's event-poll timing at startup.
                self.ensure_capture_outputs()
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
                        ws,
                        request_type,
                        reason=str(command.get("reason") or ""),
                        request_data=dict(command.get("requestData") or {}),
                    )
                    if request_type == "SaveReplayBuffer" and request_id:
                        self._pending_replay_requests.append(
                            {
                                "request_id": request_id,
                                "reason": str(command.get("reason") or ""),
                                "context": dict(command.get("context") or {}),
                            }
                        )
                elif kind == "input_mute_get":
                    input_name = str(command.get("inputName") or "").strip()
                    request_id = await self._send_request(ws, "GetInputMute", request_data={"inputName": input_name})
                    if request_id:
                        self._pending_input_mute_requests[request_id] = {"inputName": input_name, "context": dict(command.get("context") or {})}

    async def _send_request(
        self,
        ws: Any,
        request_type: str,
        *,
        request_id: str = "",
        reason: str = "",
        request_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        if not request_type:
            return ""
        rid = request_id or uuid.uuid4().hex
        payload: Dict[str, Any] = {"requestType": request_type, "requestId": rid}
        if request_data:
            payload["requestData"] = dict(request_data)
        await ws.send_json({"op": 6, "d": payload})
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
            elif request_type == "TriggerHotkeyByName":
                self._events.put(
                    {"type": "source_record_replay_saved", "ok": ok, "message": str(status.get("comment") or "")}
                )
            elif request_type == "SetSourceFilterEnabled":
                self._events.put(
                    {
                        "type": "source_record_filter_enabled",
                        "ok": ok,
                        "message": str(status.get("comment") or ""),
                    }
                )
            elif request_type == "GetInputMute":
                request_id = str(data.get("requestId") or "")
                pending = self._pending_input_mute_requests.pop(request_id, {})
                response = data.get("responseData") or {}
                self._events.put({"type": "input_mute_state", "ok": ok, "inputName": str(pending.get("inputName") or ""), "muted": bool(response.get("inputMuted", False)), "context": dict(pending.get("context") or {}), "message": str(status.get("comment") or "")})
            elif request_type == "GetInputList" and ok:
                response = data.get("responseData") or {}
                for item in list(response.get("inputs") or []):
                    item = dict(item or {})
                    input_name = str(item.get("inputName") or "").strip()
                    input_kind = str(item.get("unversionedInputKind") or item.get("inputKind") or "").lower()
                    if not input_name or input_kind != "browser_source":
                        continue
                    request_id = await self._send_request(
                        ws,
                        "GetInputSettings",
                        request_data={"inputName": input_name},
                    )
                    if request_id:
                        self._pending_input_settings_requests[request_id] = input_name
            elif request_type == "GetInputSettings":
                request_id = str(data.get("requestId") or "")
                input_name = str(self._pending_input_settings_requests.pop(request_id, "") or "")
                response = data.get("responseData") or {}
                input_settings = dict(response.get("inputSettings") or {})
                if ok and input_name and is_timerauto_browser_overlay_url(str(input_settings.get("url") or "")):
                    if input_settings.get("reroute_audio") is not True:
                        await self._send_request(
                            ws,
                            "SetInputSettings",
                            request_data={
                                "inputName": input_name,
                                "inputSettings": {"reroute_audio": True},
                                "overlay": True,
                            },
                        )
                    await self._send_request(
                        ws,
                        "SetInputAudioMonitorType",
                        request_data={
                            "inputName": input_name,
                            "monitorType": "OBS_MONITORING_TYPE_NONE",
                        },
                    )
                    logging.info(
                        "OBS_BROWSER_OVERLAY_AUDIO_ROUTE source=%s reroute_was=%s monitor=none",
                        input_name,
                        bool(input_settings.get("reroute_audio", False)),
                    )
                    self._events.put({
                        "type": "browser_overlay_audio_routed",
                        "ok": True,
                        "inputName": input_name,
                    })
