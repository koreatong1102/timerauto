"""Compatibility for the October 2026 Edge speech endpoint migration.

edge-tts 7.2.8 still uses the retired synthesis endpoint. Keep its voices,
SSML, authentication generation and audio format, but migrate that endpoint
before any synthesis workers start. Leave newer library endpoints untouched.
See https://github.com/rany2/edge-tts/pull/491.
"""

import importlib
import logging
import threading
from urllib.parse import parse_qsl, urlencode, urlsplit


_ENDPOINT_LOCK = threading.Lock()
_LEGACY_HOST = "speech.platform.bing.com"
_LEGACY_PATH = "/consumer/speech/synthesize/readaloud/edge/v1"
_SYNTHESIS_URL = "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"


def configure_edge_tts_endpoint() -> bool:
    """Migrate only the known legacy URL; return whether it was changed.

Use a process-wide, persistent setting, not a temporary per-request patch:
several commentary workers can synthesize concurrently. This works in both
source runs and frozen builds without modifying installed library files.
"""
    with _ENDPOINT_LOCK:
        communicate = importlib.import_module("edge_tts.communicate")
        constants = importlib.import_module("edge_tts.constants")
        current = getattr(communicate, "WSS_URL", "")
        if not isinstance(current, str):
            return False
        parsed = urlsplit(current)
        if (
            parsed.scheme != "wss"
            or parsed.netloc != _LEGACY_HOST
            or parsed.path != _LEGACY_PATH
        ):
            return False
        query = parse_qsl(parsed.query, keep_blank_values=True)
        token = next((value for key, value in query if key == "TrustedClientToken"), None)
        if token is None:
            # A future library may change authentication on the same host.
            return False
        if not token:
            raise RuntimeError("Edge TTS legacy endpoint has no client token")
        migrated_query = [("Ocp-Apim-Subscription-Key", token)]
        migrated_query.extend((key, value) for key, value in query if key != "TrustedClientToken")
        target = _SYNTHESIS_URL + "?" + urlencode(migrated_query)
        communicate.WSS_URL = target
        if getattr(constants, "WSS_URL", None) == current:
            constants.WSS_URL = target
        logging.info("TTS_EDGE_ENDPOINT_MIGRATED host=api.msedgeservices.com")
        return True
