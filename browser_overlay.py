from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

import cv2
import numpy as np
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QImage


_NO_UPDATE_FALLBACK = object()

class BrowserOverlayServer:
    def __init__(self, port: int = 17872, *, no_update: Any = _NO_UPDATE_FALLBACK, path_resolver: Optional[Callable[[str], str]] = None):
        self.port = int(port or 17872)
        self._no_update = no_update
        self._path_resolver = path_resolver or (lambda path: path)
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._state: Dict[str, Any] = {
            "seq": 0,
            "timeText": "3:00",
            "roundText": "RD 1 of 3",
            "blueName": "BLUE",
            "redName": "RED",
            "arenaName": "",
            "blueDamageText": "DMG 0",
            "redDamageText": "DMG 0",
            "blueTotalDamageText": "0",
            "redTotalDamageText": "0",
            "blueSpRatio": 1.0,
            "redSpRatio": 1.0,
            "blueRoundKnockdowns": 0,
            "redRoundKnockdowns": 0,
            "blueComboHitText": "",
            "blueComboDamageText": "",
            "redComboHitText": "",
            "redComboDamageText": "",
            "blueRecentHitText": "",
            "redRecentHitText": "",
            "bluePunishmentMid": 0.0,
            "redPunishmentMid": 0.0,
                "bluePunishmentLong": 0.0,
                "redPunishmentLong": 0.0,
                "blueHpRatio": 1.0,
                "redHpRatio": 1.0,
                "blueHpGhostRatio": 0.0,
                "redHpGhostRatio": 0.0,
                "blueImageRev": 0,
                "redImageRev": 0,
                "blueHasImage": False,
                "redHasImage": False,
                "blueflagRev": 0,
                "redflagRev": 0,
                "vsbgRev": 0,
                "showRound": True,
                "showTime": True,
                "showBlueImage": True,
                "showBlueName": True,
                "showRedImage": True,
                "showRedName": True,
                "showArenaName": True,
                "showFlags": True,
                "showCinematic": True,
                "vsBgOpacity": 1.0,
            "overlayVsHoldMs": 2800,
            "overlayUiScale": 1.0,
            "browserOverlayScale": 1.0,
            "overlayTopPad": 40,
            "overlayTimerX": 0,
            "overlayRoundX": 0,
            "browserTextStyles": {},
            "events": [],
            }
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._image_paths: Dict[str, str] = {}
        self._asset_paths: Dict[str, str] = {}
        self._event_id = 0
        self._last_event_key_ts: Dict[tuple, float] = {}
        self._cache_dir = os.path.join(tempfile.gettempdir(), "timerauto_browser_overlay")
        os.makedirs(self._cache_dir, exist_ok=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/overlay"

    def start(self) -> bool:
        if self._server is not None:
            return True
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "timerauto-overlay/1.0"

            def log_message(self, _fmt, *_args):
                return

            def _send(self, code: int, body: bytes, content_type: str):
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                try:
                    parsed = urlparse(self.path)
                    path = parsed.path or "/"
                    if path in ("/", "/overlay"):
                        self._send(200, outer._html().encode("utf-8"), "text/html; charset=utf-8")
                        return
                    if path == "/state":
                        body = json.dumps(outer.snapshot(), ensure_ascii=False).encode("utf-8")
                        self._send(200, body, "application/json; charset=utf-8")
                        return
                    if path == "/events":
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Connection", "keep-alive")
                        self.end_headers()
                        self.close_connection = True
                        last_seq = -1
                        try:
                            while True:
                                state = outer.wait_snapshot_after(last_seq, timeout=15.0)
                                seq = int(state.get("seq", 0) or 0)
                                payload = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                                self.wfile.write(b"id: " + str(seq).encode("ascii") + b"\n")
                                self.wfile.write(b"event: state\n")
                                self.wfile.write(b"data: " + payload + b"\n\n")
                                self.wfile.flush()
                                last_seq = seq
                        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                            return
                        return
                    if path.startswith("/image/"):
                        side = os.path.basename(path).split(".")[0].lower()
                        img_path = outer.image_path(side)
                        if img_path and os.path.isfile(img_path):
                            with open(img_path, "rb") as f:
                                self._send(200, f.read(), "image/png")
                            return
                        self._send(404, b"", "text/plain")
                        return
                    if path.startswith("/asset/"):
                        name = os.path.basename(path).split(".")[0].lower()
                        asset_path = outer.asset_path(name)
                        if asset_path and os.path.isfile(asset_path):
                            ctype = "image/png"
                            ext = os.path.splitext(asset_path)[1].lower()
                            if ext in (".jpg", ".jpeg"):
                                ctype = "image/jpeg"
                            elif ext == ".webp":
                                ctype = "image/webp"
                            elif ext == ".gif":
                                ctype = "image/gif"
                            with open(asset_path, "rb") as f:
                                self._send(200, f.read(), ctype)
                            return
                        self._send(404, b"", "text/plain")
                        return
                    self._send(404, b"not found", "text/plain")
                except Exception as e:
                    try:
                        self._send(500, str(e).encode("utf-8", "ignore"), "text/plain; charset=utf-8")
                    except Exception:
                        pass

        try:
            self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
            self._thread = threading.Thread(target=self._server.serve_forever, name="timerauto-browser-overlay", daemon=True)
            self._thread.start()
            logging.info("BROWSER_OVERLAY_SERVER started url=%s", self.url)
            return True
        except Exception as e:
            logging.warning("BROWSER_OVERLAY_SERVER failed: %s", e)
            self._server = None
            self._thread = None
            return False

    def stop(self):
        srv = self._server
        self._server = None
        if srv is not None:
            try:
                srv.shutdown()
                srv.server_close()
            except Exception:
                pass

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state)

    def wait_snapshot_after(self, last_seq: int, timeout: float = 15.0) -> Dict[str, Any]:
        deadline = time.time() + max(0.5, float(timeout or 15.0))
        with self._cond:
            while int(self._state.get("seq", 0) or 0) == int(last_seq):
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self._cond.wait(timeout=remaining)
            return copy.deepcopy(self._state)

    def update(self, **kwargs):
        with self._cond:
            changed = False
            for k, v in kwargs.items():
                if v is self._no_update:
                    continue
                if self._state.get(k) != v:
                    self._state[k] = v
                    changed = True
            if changed:
                self._state["seq"] = int(self._state.get("seq", 0) or 0) + 1
                self._cond.notify_all()

    def push_event(self, kind: str, **payload):
        ev = dict(payload)
        ev["kind"] = str(kind or "")
        ev["ts"] = time.time()
        with self._cond:
            key = (
                str(ev.get("kind") or ""),
                str(ev.get("side") or ""),
                str(ev.get("round") or ""),
                str(ev.get("damage") or ""),
            )
            last_ts = float(self._last_event_key_ts.get(key, 0.0) or 0.0)
            if ev["ts"] - last_ts < 0.08:
                return
            self._last_event_key_ts[key] = ev["ts"]
            self._event_id += 1
            ev["id"] = int(self._event_id)
            events = list(self._state.get("events") or [])
            events.append(ev)
            self._state["events"] = events[-80:]
            self._state["seq"] = int(self._state.get("seq", 0) or 0) + 1
            self._cond.notify_all()
        try:
            logging.info("BROWSER_OVERLAY_EVENT id=%s kind=%s side=%s", ev.get("id"), ev.get("kind"), ev.get("side", ""))
        except Exception:
            pass

    def set_image(self, side: str, img: Any):
        side = "red" if str(side).lower() == "red" else "blue"
        path = os.path.join(self._cache_dir, f"{side}.png")
        is_empty_np = False
        try:
            is_empty_np = getattr(img, "size", 1) == 0 and not isinstance(img, QImage)
        except Exception:
            is_empty_np = False
        if img is None or img is self._no_update or is_empty_np or (isinstance(img, QImage) and img.isNull()):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
            self._image_paths.pop(side, None)
            self.update(**{f"{side}ImageRev": int(time.time() * 1000)})
            return
        try:
            if isinstance(img, QImage):
                qimg = img.convertToFormat(QImage.Format.Format_RGBA8888)
                ok = qimg.save(path, "PNG")
                if not ok:
                    raise RuntimeError("QImage.save returned false")
            else:
                arr = np.ascontiguousarray(img)
                cv2.imwrite(path, arr)
            self._image_paths[side] = path
            self.update(**{f"{side}ImageRev": int(time.time() * 1000)})
        except Exception as e:
            logging.warning("BROWSER_OVERLAY_IMAGE failed side=%s err=%s", side, e)

    def image_path(self, side: str) -> str:
        with self._lock:
            return str(self._image_paths.get(str(side or "").lower(), "") or "")

    def set_asset_path(self, name: str, path: Any):
        key = str(name or "").strip().lower()
        if not key:
            return
        raw = str(path or "").strip()
        if raw.startswith("file:"):
            try:
                raw = QUrl(raw).toLocalFile()
            except Exception:
                pass
        if raw:
            raw = self._path_resolver(raw)
        rev_key = f"{key}Rev"
        with self._cond:
            old = str(self._asset_paths.get(key, "") or "")
            if raw and os.path.isfile(raw):
                self._asset_paths[key] = raw
            else:
                self._asset_paths.pop(key, None)
                raw = ""
            if old != raw:
                self._state[rev_key] = int(time.time() * 1000)
                self._state["seq"] = int(self._state.get("seq", 0) or 0) + 1
                self._cond.notify_all()

    def asset_path(self, name: str) -> str:
        with self._lock:
            return str(self._asset_paths.get(str(name or "").lower(), "") or "")

    def _html(self) -> str:
        return r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>timerauto OBS overlay</title>
<style>
:root{
  --ui-scale:1;
  --overlay-top-pad:8;
  --recent-font:23px;--timer-font:54px;--timer-x:0px;--timer-y:0px;--timer-opacity:1;--round-font:11px;--round-x:0px;--round-y:0px;--round-opacity:1;
  --hud-gold:#ffd66b;
  --hud-orange:#ff7b1a;
  --hud-red:#ff2e5f;
  --hud-cyan:#38c9ff;
  --hud-dark:#02050a;
  --bt-time-family:'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif;
  --bt-time-size:54px;
  --bt-time-weight:900;
  --bt-time-opacity:1;
  --bt-time-stroke:.35px rgba(255,255,255,.38);
  --bt-time-shadow:0 2px 0 #02040a,0 0 5px rgba(255,255,255,.72),0 0 8px rgba(185,30,42,.42);
  --bt-time-filter:drop-shadow(0 0 2px rgba(255,255,255,.22));
  --bt-total-family:'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif;
  --bt-total-size:12px;
  --bt-total-weight:900;
  --bt-total-color:#f4f7fb;
  --bt-total-opacity:.95;
  --bt-total-stroke:0px #000000;
  --bt-dmg-family:'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif;
  --bt-dmg-size:12px;
  --bt-dmg-weight:900;
  --bt-dmg-color:#e8eef7;
  --bt-dmg-opacity:.86;
  --bt-dmg-stroke:0px #000000;
  --bt-combo-family:'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif;
  --bt-combo-size:22px;
  --bt-combo-weight:900;
  --bt-combo-color:#f4f7fb;
  --bt-combo-opacity:1;
  --bt-combo-stroke:1px #111827;
  --bt-recent-family:'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif;
  --bt-recent-size:23px;
  --bt-recent-weight:900;
  --bt-recent-color:#edf5ff;
  --bt-recent-opacity:.94;
  --bt-recent-stroke:0px #000000;
}
*{box-sizing:border-box}
html,body{
  margin:0;width:100%;height:100%;overflow:hidden;background:transparent;color:white;
  font-family:'Bahnschrift Condensed','Arial Narrow','Roboto Condensed','Segoe UI','Malgun Gothic',sans-serif;
}
#root{
  position:fixed;inset:0;pointer-events:none;
  text-shadow:0 2px 3px #000,0 0 7px #000;
}
.hud{
  position:absolute;top:0;left:0;width:calc(100vw / var(--ui-scale));height:calc(100vh / var(--ui-scale));
  transform-origin:top left;transform:translateY(calc(var(--overlay-top-pad)*1px)) scale(var(--ui-scale));z-index:8;
  filter:drop-shadow(0 2px 3px rgba(0,0,0,.82));
}
/* v10 focused polish: life markers moved outward, metallic HP frame, wider nameplates. */
.center{
  position:absolute;left:50%;top:-4px;transform:translateX(-50%);width:104px;height:64px;text-align:center;z-index:210;
  display:flex;flex-direction:column;align-items:center;
}
.center:before,.center:after{display:none!important;content:none!important}
.time{
  position:relative;display:flex;align-items:flex-start;justify-content:center;margin:0 auto;width:104px;height:47px;
  font-family:'Bahnschrift Condensed','Arial Narrow','Impact','Arial Black',sans-serif;font-size:56px;font-weight:900;line-height:.78;
  letter-spacing:-4.5px;text-indent:-4.5px;font-variant-numeric:tabular-nums;color:#f7fbff;-webkit-text-stroke:1.35px #451019;
  transform:scaleX(.76);transform-origin:center top;
  text-shadow:0 2px 0 #02040a,0 0 5px rgba(255,255,255,.72),0 0 8px rgba(185,30,42,.42);
  background:linear-gradient(180deg,#ffffff 0%,#f8fdff 14%,#c7d0dd 29%,#6f7887 39%,#f9ffff 47%,#aeb8c7 53%,#4c5360 66%,#84202c 86%,#210509 100%);
  -webkit-background-clip:text;background-clip:text;color:transparent;
  filter:drop-shadow(0 0 2px rgba(255,255,255,.22));opacity:var(--timer-opacity);
}
.round{
  position:absolute;left:50%;top:46px;transform:translateX(-50%);width:82px;height:14px;
  display:flex;align-items:center;justify-content:center;
  padding-left:1.7px;
  font:900 11.5px/13px 'Bahnschrift Condensed','Arial Narrow',Arial,sans-serif;letter-spacing:1.7px;color:#f8fafc;
  text-shadow:0 2px 0 #000,0 0 4px #000;background:rgba(3,7,18,.62);border-top:1px solid rgba(255,255,255,.12);opacity:var(--round-opacity);
}
.side{
  position:absolute;top:0;height:94px;width:calc((100vw / var(--ui-scale) - 190px) / 2);z-index:6;
}
.blue{left:22px;text-align:left}.red{right:22px;text-align:right}
.side:before{
  content:"";position:absolute;top:18px;height:31px;z-index:12;pointer-events:none;
  background:linear-gradient(180deg,rgba(255,255,255,.34),rgba(10,13,19,.78) 35%,rgba(0,0,0,.58));
  border-top:1px solid rgba(255,255,255,.28);border-bottom:1px solid rgba(0,0,0,.82);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.18),0 2px 3px rgba(0,0,0,.72);
}
.blue:before{left:42px;right:0;clip-path:polygon(0 0,98.4% 0,100% 50%,98.4% 100%,0 100%,3% 50%)}
.red:before{right:42px;left:0;clip-path:polygon(1.6% 0,100% 0,97% 50%,100% 100%,1.6% 100%,0 50%)}
.portrait{
  position:absolute;top:-8px;width:74px;height:74px;object-fit:contain;z-index:50;
  image-rendering:auto;
  filter:drop-shadow(0 3px 4px #000) drop-shadow(0 0 8px rgba(255,255,255,.30)) drop-shadow(0 0 10px rgba(255,126,32,.18));
  transition:filter .08s;
}
.blue .portrait{left:-15px;--mirror:1}.red .portrait{right:-15px;--mirror:-1;transform:scaleX(-1)}
.total{
  position:absolute;top:2px;height:15px;font:900 13px/15px 'Bahnschrift Condensed','Arial Narrow',Arial,sans-serif;
  letter-spacing:1px;color:#eef2f7;text-shadow:0 2px 2px #000,0 0 5px #000;z-index:48;opacity:.96;
}
.blue .total{left:74px}.red .total{right:74px}
.barWrap{
  position:absolute;top:20px;height:25px;z-index:18;background:transparent!important;overflow:visible;
  filter:drop-shadow(0 2px 2px rgba(0,0,0,.92)) drop-shadow(0 0 5px rgba(255,126,32,.28));
  isolation:isolate;
}
.blue .barWrap{left:58px;right:8px;width:auto;clip-path:polygon(0 0,98.2% 0,100% 50%,98.2% 100%,0 100%,2.4% 50%)}
.red .barWrap{right:58px;left:8px;width:auto;clip-path:polygon(1.8% 0,100% 0,97.6% 50%,100% 100%,1.8% 100%,0 50%)}
.barWrap:before{
  content:"";position:absolute;inset:-5px -8px -6px -8px;z-index:0;pointer-events:none;
  background:linear-gradient(180deg,rgba(255,255,255,.78) 0%,rgba(173,184,196,.44) 10%,rgba(5,8,13,.94) 42%,rgba(0,0,0,.96) 70%,rgba(178,91,26,.34) 100%);
  clip-path:inherit;border-radius:2px;box-shadow:inset 0 1px 0 rgba(255,255,255,.82),inset 0 -2px 0 rgba(0,0,0,.9),0 2px 5px rgba(0,0,0,.88);
}
.barWrap:after{
  content:"";position:absolute;left:2.2%;right:2.2%;top:2px;height:5px;z-index:3;pointer-events:none;
  background:linear-gradient(90deg,rgba(255,255,255,0),rgba(255,255,255,.88) 22%,rgba(255,231,164,.72) 50%,rgba(255,255,255,.72) 78%,rgba(255,255,255,0));
  border-radius:999px;mix-blend-mode:screen;opacity:.78;filter:blur(.2px);
}
.hpCanvas{position:absolute!important;left:0!important;top:0!important;width:100%!important;height:25px!important;display:block!important;background:transparent!important;z-index:2;filter:drop-shadow(0 0 3px rgba(255,184,69,.32))}
.name{
  position:absolute;top:49px;height:19px;width:min(315px,calc(100% - 80px));padding:2px 12px 0;z-index:52;
  font:900 18px/.86 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif;letter-spacing:0;color:#fff;
  background:linear-gradient(90deg,#03070d 0%,#101722 42%,rgba(16,23,34,.78) 66%,rgba(16,23,34,.20) 88%,rgba(16,23,34,0) 100%);
  border-left:4px solid var(--hud-cyan);border-top:1px solid rgba(255,255,255,.24);border-bottom:1px solid rgba(255,255,255,.12);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.13),0 2px 3px rgba(0,0,0,.78);
  text-shadow:0 2px 0 #000,0 0 4px #000;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  clip-path:polygon(0 0,100% 0,94% 100%,0 100%);
}
.blue .name{left:76px;text-align:left}.red .name{right:76px;text-align:right;border-left:0;border-right:4px solid var(--hud-red);background:linear-gradient(270deg,#03070d 0%,#101722 42%,rgba(16,23,34,.78) 66%,rgba(16,23,34,.20) 88%,rgba(16,23,34,0) 100%);clip-path:polygon(6% 100%,0 0,100% 0,100% 100%)}
.dmg{
  position:absolute;top:74px;font:900 11px/1 'Bahnschrift Condensed','Arial Narrow',Arial,sans-serif;letter-spacing:1px;color:#dbe3ee;z-index:24;opacity:.82;
  text-shadow:0 2px 2px #000,0 0 5px #000;
}
.blue .dmg{left:10px}.red .dmg{right:10px;width:80px;text-align:right}
.flag{position:absolute;top:74px;width:38px;height:22px;object-fit:cover;z-index:20;filter:drop-shadow(0 2px 3px #000);opacity:.92}.blue .flag{left:62px}.red .flag{right:62px}
.lives{
  position:absolute;top:0;display:flex;gap:4px;z-index:205;
  padding:2px 5px 3px;border-radius:999px;
  background:linear-gradient(180deg,rgba(255,255,255,.16),rgba(0,0,0,.24) 42%,rgba(0,0,0,.52));
  box-shadow:inset 0 1px 0 rgba(255,255,255,.22),0 2px 4px rgba(0,0,0,.78);
  filter:drop-shadow(0 2px 3px #000);
}
.blue .lives{right:70px;left:auto}.red .lives{left:70px;right:auto;flex-direction:row-reverse}
.life{width:10.5px;height:10.5px;border-radius:50%;background:radial-gradient(circle at 32% 26%,#fff8dc 0,#ffe391 20%,#d39b3c 42%,#604018 67%,#03050a 100%);box-shadow:0 0 0 1px #05070a,0 0 3px #ffd38a,0 1px 2px #000}.life.off{background:radial-gradient(circle at 34% 30%,#5a626d,#202735 54%,#02040a 100%);box-shadow:0 0 0 1px #05070a,0 1px 2px #000;opacity:.52}
.recent{
  position:absolute;top:150px;max-width:215px;min-width:82px;padding:1px 7px 3px;z-index:13;opacity:0;white-space:pre-line;
  font:900 calc(var(--recent-font) * .54)/.92 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif;letter-spacing:.35px;color:#f8fafc;
  text-shadow:0 2px 0 #000,0 0 4px #000;transition:opacity .08s;transform-origin:center;
  background:linear-gradient(90deg,rgba(4,7,13,.68),rgba(4,7,13,.20),rgba(4,7,13,0));border-left:2px solid var(--hud-red);
}
.redRecent{background:linear-gradient(270deg,rgba(4,7,13,.68),rgba(4,7,13,.20),rgba(4,7,13,0));border-left:0;border-right:2px solid var(--hud-red)}
.recent.show{opacity:.88}.blueRecent{left:52px;text-align:left}.redRecent{right:52px;text-align:right}
.combo{
  position:absolute;top:124px;width:170px;height:54px;z-index:14;opacity:0;transition:opacity .08s;transform-origin:center;
  font-family:'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif;text-shadow:0 2px 0 #000,0 0 5px #000;
}
.combo.show{opacity:1}.blueCombo{left:54px;text-align:left}.redCombo{right:54px;text-align:right}
.hit{display:inline-block;font:900 17px/.88 'Bahnschrift Condensed','Arial Narrow',Arial,sans-serif;letter-spacing:.7px;color:#f5f7fb;-webkit-text-stroke:.35px #0f172a;text-shadow:0 2px 0 #000,0 0 4px #000}
.damage{display:block;margin-top:2px;font:900 25px/.84 'Bahnschrift Condensed','Arial Narrow',Arial,sans-serif;letter-spacing:.8px;color:#ffd16a;-webkit-text-stroke:.75px #5f2208;text-shadow:0 2px 0 #000,0 0 5px rgba(255,186,74,.55)}
.hit.counter{
  position:relative;display:inline-block;padding:2px 10px 3px;min-width:100px;transform:skewX(-12deg);
  font-size:20px;letter-spacing:1.4px;color:#fff;-webkit-text-stroke:.6px #7f102d;text-align:center;
  background:linear-gradient(90deg,#ff1560 0%,#ff477f 46%,rgba(255,71,127,.08) 100%);box-shadow:0 0 7px rgba(255,36,98,.45),0 2px 0 #000;
}
.redCombo .hit.counter{background:linear-gradient(270deg,#ff1560 0%,#ff477f 46%,rgba(255,71,127,.08) 100%)}

.fullscreen{position:absolute;inset:0;z-index:30;pointer-events:none}.roundIntro{opacity:0;display:none;text-align:center;z-index:35}.roundIntro.show{display:block;animation:roundIntroQml 1.95s ease forwards}.roundIntro .introMain{position:absolute;left:0;right:0;top:0;color:#fefce8;font:900 70px/0.92 'Bahnschrift Condensed','Arial Narrow','Impact',Arial,sans-serif;letter-spacing:2px;-webkit-text-stroke:2px #7c2d12;text-shadow:0 4px 0 #000,0 0 20px #000}.roundIntro .introSub{position:absolute;left:0;right:0;top:86px;color:#ffedd5;font:900 34px/1 'Bahnschrift Condensed','Arial Narrow',Arial,sans-serif;letter-spacing:4px;-webkit-text-stroke:1.4px #7f1d1d;text-shadow:0 2px 0 #000,0 0 12px #000}
.koOverlay{opacity:0;display:none;z-index:34}.koOverlay.show{display:block;animation:koWrapQml 2.36s ease forwards}.koOverlay .flash{position:absolute;inset:0;background:white;opacity:0;animation:koFlashQml .38s ease-out}.koOverlay .line1,.koOverlay .line2{position:absolute;left:50%;top:50%;border-radius:999px;transform:translate(-50%,-50%) rotate(-2deg);opacity:.8}.koOverlay .line1{width:90vw;height:max(8px,1.8vh);background:#fff7ed;animation:koLineQml 2.25s ease forwards}.koOverlay .line2{width:76vw;height:max(4px,.9vh);background:#ef4444;transform:translate(-50%,-50%) rotate(6deg);opacity:.65;animation:koLineQml 2.25s ease forwards}.koPanel{position:absolute;left:0;right:0;top:42%;height:max(46px,7vh);display:flex;align-items:center;justify-content:center;transform-origin:center;animation:koPanelQml 2.0s ease forwards}.koOverlay.tko .koPanel{height:max(65px,10vh)}.koPanel::before{content:"";position:absolute;width:min(22vw,310px);height:100%;border-radius:10px;background:#070b13;opacity:.84;border:2px solid #f59e0b}.koOverlay.tko .koPanel::before{width:min(29vw,380px)}.koPanel::after{content:"";position:absolute;width:min(24vw,328px);height:max(5px,.75vh);border-radius:999px;background:#dc2626;opacity:.78;transform:translateY(150%) rotate(2deg)}.koText{position:relative;width:82vw;text-align:center;color:#fff7ed;font:900 italic clamp(27px,3vw,48px)/.82 'Impact','Arial Black',Arial,sans-serif;letter-spacing:4px;-webkit-text-stroke:1.6px #7f1d1d;text-shadow:-5px 7px 0 #020617,4px 3px 0 #b91c1c,0 0 16px #000}.koOverlay.tko .koText{font-size:clamp(22px,2.45vw,39px);letter-spacing:2px}
.vs{opacity:0;display:none;overflow:hidden;z-index:40;background:#020617}.vs.show{display:block;animation:vsWrapQml var(--vs-total,3.8s) ease forwards}.vsBg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;filter:brightness(.7) saturate(1.15)}.vs .dark{position:absolute;inset:0;background:#020617;opacity:.78}.vs.hasBg .dark{opacity:.42}.vs .grad{position:absolute;inset:0;background:linear-gradient(90deg,#020617cc 0%,#0f172a22 36%,#11182722 68%,#020617dd 100%)}.vs .vsFlash{position:absolute;inset:0;background:#fff;opacity:0;animation:vsFlashQml .9s ease-out}.vs .slash1,.vs .slash2{position:absolute;left:50%;top:50%;border-radius:999px;transform:translate(-50%,-50%) rotate(-2deg);opacity:0}.vs .slash1{height:max(3px,1.2vh);background:#dff7ff;animation:vsSlash1 .55s ease-out}.vs .slash2{height:max(2px,.6vh);background:#ff2d75;transform:translate(-50%,-50%) rotate(8deg);animation:vsSlash2 .55s ease-out}.vsPortrait{position:absolute;top:max(16px,7vh);width:max(440px,34vw);height:max(520px,76vh);object-fit:contain;filter:drop-shadow(0 18px 22px #000) drop-shadow(0 0 18px #fff3)}.vsBlueImg{left:max(24px,3.5vw);animation:vsBlueQml .46s cubic-bezier(.2,1.25,.25,1) forwards}.vsRedImg{right:max(24px,3.5vw);transform:scaleX(-1);animation:vsRedQml .46s cubic-bezier(.2,1.25,.25,1) forwards}.vsName{position:absolute;top:63vh;width:32vw;color:#e0f2fe;font:900 italic max(34px,6.2vh)/1 Arial,sans-serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-shadow:0 3px 0 #0f172a,0 0 15px #38bdf8}.vsBlue{left:max(52px,5.2vw);animation:vsNameQml .52s ease-out forwards}.vsRed{right:max(52px,5.2vw);text-align:right;text-shadow:0 3px 0 #0f172a,0 0 15px #ef4444;animation:vsNameQml .52s ease-out forwards}.stagePanel{position:absolute;left:50%;top:73vh;width:max(420px,34vw);height:max(70px,7.5vh);transform:translateX(-50%);background:#44020617;border:1px solid #66e0f2fe;text-align:center;animation:vsStageQml .6s ease-out forwards}.stageLabel{position:absolute;left:0;right:0;top:-18px;color:#e5e7eb;opacity:.88;font:900 24px/1 Arial,sans-serif;letter-spacing:4px;-webkit-text-stroke:1px #020617}.stageName{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#ff2d75;font:900 italic max(24px,3.2vh)/1 Arial,sans-serif;letter-spacing:2px;-webkit-text-stroke:1px #020617;text-shadow:0 2px 0 #000,0 0 12px #000}
@keyframes roundIntroQml{0%{opacity:0;transform:scale(.82)}8%{opacity:1;transform:scale(1.06)}52%{opacity:1;transform:scale(1.06)}60%{opacity:.5;transform:scale(.82)}70%{opacity:1;transform:scale(1.15)}88%{opacity:1;transform:scale(1.15)}100%{opacity:0;transform:scale(1.34)}}@keyframes koWrapQml{0%{opacity:0}3%{opacity:1}82%{opacity:1}100%{opacity:0}}@keyframes koPanelQml{0%{transform:translateY(-190px) scale(1.34) rotate(-5deg)}7%{transform:translateY(24px) scale(.96) rotate(2deg)}12%{transform:translateY(0) scale(1.08) rotate(0)}20%{transform:translateX(-34px) scale(1.08)}26%{transform:translateX(26px) scale(.98)}33%{transform:translateX(-12px) scale(1.03)}45%,100%{transform:translateX(0) scale(1)}}@keyframes koFlashQml{0%{opacity:1}.38%{opacity:.25}100%{opacity:0}}@keyframes koLineQml{0%{width:12vw}12%{width:92vw}42%{width:68vw}100%{width:115vw;opacity:0}}@keyframes vsWrapQml{0%{opacity:0;transform:scale(1.04)}3%{opacity:1;transform:scale(1.04)}15%{opacity:1;transform:scale(1)}88%{opacity:1;transform:scale(1)}100%{opacity:0;transform:scale(1.12)}}@keyframes vsBlueQml{0%{transform:translateX(calc(-1 * max(640px,44vw))) rotate(-10deg)}62%{transform:translateX(42px) rotate(2.5deg)}100%{transform:translateX(0) rotate(0)}}@keyframes vsRedQml{0%{transform:scaleX(-1) translateX(calc(-1 * max(640px,44vw))) rotate(10deg)}62%{transform:scaleX(-1) translateX(-42px) rotate(-2.5deg)}100%{transform:scaleX(-1) translateX(0) rotate(0)}}@keyframes vsNameQml{0%{transform:translateY(96px)}70%{transform:translateY(14px)}100%{transform:translateY(0)}}@keyframes vsStageQml{0%{transform:translateX(-50%) translateY(120px)}70%{transform:translateX(-50%) translateY(20px)}100%{transform:translateX(-50%) translateY(0)}}@keyframes vsFlashQml{0%{opacity:1}25%{opacity:.15}45%{opacity:.55}100%{opacity:0}}@keyframes vsSlash1{0%{opacity:.85;width:18vw}45%{opacity:.85;width:143vw}100%{opacity:0;width:143vw}}@keyframes vsSlash2{0%{opacity:.7;width:12vw}45%{opacity:.7;width:107vw}100%{opacity:0;width:107vw}}


/* v8 BAR-SAFE HOTFIX: keep both HP gauges inside their own half of the scaled .hud.
   The old layout used vw inside a scaled container; at overlayUiScale > 1 it let bars cross the center. */
.hud{overflow:visible!important}
.side{
  top:0!important;
  height:90px!important;
  width:calc(50% - 100px)!important;
  max-width:calc(50% - 100px)!important;
  min-width:230px!important;
  z-index:6!important;
}
.blue{left:20px!important;right:auto!important;text-align:left!important}
.red{right:20px!important;left:auto!important;text-align:right!important}
.center{
  top:-2px!important;
  width:92px!important;
  height:61px!important;
  z-index:260!important;
  pointer-events:none!important;
}
.time{
  width:92px!important;
  height:43px!important;
  font-size:48px!important;
  line-height:.82!important;
  letter-spacing:-2.4px!important;
  -webkit-text-stroke:0!important;
  text-shadow:0 2px 0 #02040a,0 0 5px rgba(255,255,255,.58),0 0 7px rgba(198,35,55,.28)!important;
}
.round{
  top:43px!important;
  width:76px!important;
  height:14px!important;
  font-size:var(--round-font)!important;
  line-height:calc(var(--round-font) + 2px)!important;
  transform:translate(calc(-50% + var(--round-x)), var(--round-y))!important;
  letter-spacing:1.45px!important;
}
.portrait{
  top:0!important;
  width:50px!important;
  height:50px!important;
  z-index:44!important;
}
.blue .portrait{left:0!important}
.red .portrait{right:0!important}
.total{
  top:0!important;
  height:14px!important;
  font-size:12px!important;
  line-height:14px!important;
  letter-spacing:.9px!important;
  z-index:46!important;
}
.blue .total{left:62px!important;right:auto!important}
.red .total{right:62px!important;left:auto!important}
.barWrap{
  top:19px!important;
  height:23px!important;
  overflow:hidden!important;
  background:transparent!important;
  z-index:20!important;
  filter:drop-shadow(0 2px 2px rgba(0,0,0,.82)) drop-shadow(0 0 3px rgba(255,92,12,.18))!important;
}
.blue .barWrap{
  left:62px!important;
  right:0!important;
  width:auto!important;
  max-width:none!important;
  clip-path:polygon(0 0,98.4% 0,100% 50%,98.4% 100%,0 100%,2.2% 50%)!important;
}
.red .barWrap{
  right:62px!important;
  left:0!important;
  width:auto!important;
  max-width:none!important;
  clip-path:polygon(1.6% 0,100% 0,97.8% 50%,100% 100%,1.6% 100%,0 50%)!important;
}
.barWrap:before,.barWrap:after{display:none!important;content:none!important}
.hpCanvas{
  left:0!important;
  top:0!important;
  width:100%!important;
  height:23px!important;
  max-width:100%!important;
  display:block!important;
  background:transparent!important;
}
.name{
  top:45px!important;
  height:19px!important;
  width:min(188px,calc(100% - 68px))!important;
  padding:2px 8px 0!important;
  font-size:18px!important;
  line-height:.86!important;
  z-index:42!important;
}
.blue .name{left:62px!important;right:auto!important;text-align:left!important}
.red .name{right:62px!important;left:auto!important;text-align:right!important}
.dmg{
  top:67px!important;
  font-size:10px!important;
  z-index:38!important;
}
.blue .dmg{left:4px!important;right:auto!important}
.red .dmg{right:4px!important;left:auto!important}
.flag{top:67px!important;width:34px!important;height:20px!important;opacity:.86!important}
.blue .flag{left:54px!important;right:auto!important}.red .flag{right:54px!important;left:auto!important}
.lives{
  top:5px!important;
  gap:3px!important;
  z-index:280!important;
  pointer-events:none!important;
}
.blue .lives{right:-28px!important;left:auto!important;flex-direction:row!important}
.red .lives{left:-28px!important;right:auto!important;flex-direction:row-reverse!important}
.life{width:10px!important;height:10px!important;box-shadow:0 0 0 1px #05070a,0 0 3px #ffe1a0,0 2px 2px #000!important}
.recent{top:138px!important;max-width:190px!important;font-size:calc(var(--recent-font) * .50)!important}
.blueRecent{left:48px!important}.redRecent{right:48px!important}
.combo{top:128px!important;max-width:190px!important}
.blueCombo{left:48px!important}.redCombo{right:48px!important}


/* === RFC HUD v11: life dots on HP bar edge + premium metal frame + name fit === */
/* Keep timer styling from v10. Only move round-point dots, enrich frame, and improve name/portrait linkage. */
.side{
  height:96px!important;
}
.side:after{
  content:""!important;display:block!important;position:absolute;top:14px;width:92px;height:34px;z-index:16;pointer-events:none;
  background:linear-gradient(180deg,rgba(255,255,255,.34),rgba(58,65,78,.32) 13%,rgba(4,7,13,.86) 48%,rgba(0,0,0,.92) 100%);
  border-top:1px solid rgba(255,255,255,.38);border-bottom:1px solid rgba(0,0,0,.88);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.20),inset 0 -1px 0 rgba(255,112,24,.16),0 2px 5px rgba(0,0,0,.88);
  opacity:.95;
}
.blue:after{left:43px;clip-path:polygon(0 0,100% 0,88% 100%,0 100%)}
.red:after{right:43px;clip-path:polygon(12% 100%,0 0,100% 0,100% 100%)}
.portrait{
  top:-2px!important;width:58px!important;height:58px!important;z-index:62!important;
  filter:drop-shadow(0 3px 3px #000) drop-shadow(0 0 7px rgba(255,255,255,.24)) drop-shadow(0 0 10px rgba(255,121,31,.22));
}
.blue .portrait{left:-4px!important}.red .portrait{right:-4px!important}
.total{
  top:0!important;font-size:12px!important;line-height:14px!important;letter-spacing:.95px!important;
  color:#f4f7fb!important;text-shadow:0 2px 2px #000,0 0 4px #000!important;
}
.blue .total{left:78px!important}.red .total{right:78px!important}
.barWrap{
  top:18px!important;height:24px!important;overflow:visible!important;background:transparent!important;
  filter:drop-shadow(0 2px 2px rgba(0,0,0,.94)) drop-shadow(0 0 5px rgba(255,120,28,.22))!important;
  isolation:isolate!important;
}
.blue .barWrap{left:72px!important;right:0!important}
.red .barWrap{right:72px!important;left:0!important}
.barWrap:before{
  content:""!important;display:block!important;position:absolute;inset:-5px -7px -6px -7px;z-index:0;pointer-events:none;
  clip-path:inherit;border-radius:2px;
  background:linear-gradient(180deg,rgba(255,255,255,.86) 0%,rgba(219,224,230,.66) 8%,rgba(55,63,74,.55) 19%,rgba(7,10,16,.96) 42%,rgba(0,0,0,.96) 73%,rgba(139,65,24,.46) 100%);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.78),inset 0 -2px 0 rgba(0,0,0,.95),0 2px 6px rgba(0,0,0,.92),0 0 8px rgba(255,135,42,.18);
}
.barWrap:after{
  content:""!important;display:block!important;position:absolute;left:2.4%;right:2.4%;top:2px;height:4px;z-index:4;pointer-events:none;
  border-radius:999px;
  background:linear-gradient(90deg,rgba(255,255,255,0),rgba(255,255,255,.82) 20%,rgba(255,236,180,.68) 50%,rgba(255,255,255,.72) 80%,rgba(255,255,255,0));
  opacity:.70;mix-blend-mode:screen;filter:blur(.15px);
}
.hpCanvas{
  top:0!important;height:24px!important;z-index:2!important;filter:drop-shadow(0 0 3px rgba(255,176,55,.30))!important;
}
/* Round points: attach to the inner end of each HP bar, not to the timer. */
.lives{
  top:3px!important;gap:3px!important;padding:2px 5px 3px!important;z-index:290!important;
  background:linear-gradient(180deg,rgba(255,255,255,.18),rgba(21,26,36,.32) 36%,rgba(0,0,0,.62) 100%)!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.25),inset 0 -1px 0 rgba(0,0,0,.78),0 2px 4px rgba(0,0,0,.86)!important;
}
.blue .lives{right:62px!important;left:auto!important;flex-direction:row!important}
.red .lives{left:62px!important;right:auto!important;flex-direction:row-reverse!important}
.life{width:10px!important;height:10px!important;background:radial-gradient(circle at 30% 25%,#fff9d9 0,#ffe08d 19%,#cf9437 44%,#563612 70%,#030409 100%)!important;box-shadow:0 0 0 1px #03050a,0 0 4px rgba(255,213,126,.72),0 1px 2px #000!important}
.life.off{background:radial-gradient(circle at 35% 30%,#555d68,#1e2530 55%,#020309 100%)!important;box-shadow:0 0 0 1px #020309,0 1px 2px #000!important;opacity:.48!important}
.name{
  top:46px!important;height:18px!important;width:min(245px,calc(100% - 86px))!important;padding:2px 10px 0!important;
  font-size:16px!important;line-height:.88!important;letter-spacing:-.2px!important;z-index:58!important;
  background:linear-gradient(90deg,#02050b 0%,#0a101a 38%,rgba(15,22,33,.82) 68%,rgba(15,22,33,.24) 90%,rgba(15,22,33,0) 100%)!important;
  border-top:1px solid rgba(255,255,255,.26)!important;border-bottom:1px solid rgba(255,255,255,.10)!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.12),0 2px 4px rgba(0,0,0,.82)!important;
}
.blue .name{left:76px!important;right:auto!important;text-align:left!important}
.red .name{right:76px!important;left:auto!important;text-align:right!important;background:linear-gradient(270deg,#02050b 0%,#0a101a 38%,rgba(15,22,33,.82) 68%,rgba(15,22,33,.24) 90%,rgba(15,22,33,0) 100%)!important}
.dmg{top:69px!important;font-size:10px!important;opacity:.80!important}
.blue .dmg{left:10px!important}.red .dmg{right:10px!important}


/* RFC v12: portrait / life points / metal frame / text polish overrides */
.portrait{
  top:-18px!important;width:102px!important;height:102px!important;z-index:78!important;
  object-fit:contain!important;
  filter:drop-shadow(0 5px 7px rgba(0,0,0,.95)) drop-shadow(0 0 10px rgba(255,255,255,.34)) drop-shadow(0 0 12px rgba(255,127,48,.22));
}
.blue .portrait{left:-10px!important;--mirror:1!important}.red .portrait{right:-10px!important;--mirror:-1!important;transform:scaleX(-1)}
.side:before{
  top:17px!important;height:34px!important;z-index:11!important;
  background:linear-gradient(180deg,rgba(255,255,255,.42) 0%,rgba(159,170,183,.42) 16%,rgba(5,8,14,.90) 46%,rgba(0,0,0,.96) 76%,rgba(211,97,30,.22) 100%)!important;
  border-top:1px solid rgba(255,255,255,.34)!important;border-bottom:1px solid rgba(0,0,0,.95)!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.32),inset 0 -2px 0 rgba(0,0,0,.9),0 3px 5px rgba(0,0,0,.75)!important;
}
.blue:before{left:86px!important;right:0!important;clip-path:polygon(0 0,98.6% 0,100% 50%,98.6% 100%,0 100%,2.4% 50%)!important}
.red:before{right:86px!important;left:0!important;clip-path:polygon(1.4% 0,100% 0,97.6% 50%,100% 100%,1.4% 100%,0 50%)!important}
.barWrap{
  top:22px!important;height:24px!important;z-index:20!important;background:transparent!important;overflow:visible!important;
  filter:drop-shadow(0 3px 3px rgba(0,0,0,.96)) drop-shadow(0 0 6px rgba(255,118,24,.26))!important;
}
.blue .barWrap{left:96px!important;right:10px!important;width:auto!important}.red .barWrap{right:96px!important;left:10px!important;width:auto!important}
.barWrap:before{
  content:""!important;position:absolute!important;inset:-5px -8px -7px -8px!important;z-index:0!important;pointer-events:none!important;
  background:linear-gradient(180deg,rgba(255,255,255,.86) 0%,rgba(212,220,232,.56) 11%,rgba(47,55,67,.70) 30%,rgba(3,6,12,.96) 54%,rgba(0,0,0,.98) 78%,rgba(134,59,21,.42) 100%)!important;
  clip-path:inherit!important;border-radius:2px!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.88),inset 0 -2px 0 rgba(0,0,0,.95),0 2px 5px rgba(0,0,0,.86),0 0 7px rgba(255,139,42,.20)!important;
}
.barWrap:after{
  content:""!important;position:absolute!important;left:2.5%!important;right:2.5%!important;top:1px!important;height:3px!important;z-index:5!important;pointer-events:none!important;
  background:linear-gradient(90deg,rgba(255,255,255,0),rgba(255,255,255,.95) 20%,rgba(255,216,121,.80) 50%,rgba(255,255,255,.84) 80%,rgba(255,255,255,0))!important;
  border-radius:999px!important;mix-blend-mode:screen!important;opacity:.82!important;filter:blur(.15px)!important;
}
.hpCanvas{top:0!important;height:24px!important;z-index:2!important;border-radius:1px!important;clip-path:inherit!important}
.lives{
  top:4px!important;padding:0!important;gap:5px!important;background:transparent!important;box-shadow:none!important;border:0!important;filter:drop-shadow(0 2px 2px #000) drop-shadow(0 0 4px rgba(255,199,92,.32))!important;z-index:230!important;
}
.blue .lives{right:24px!important;left:auto!important}.red .lives{left:24px!important;right:auto!important;flex-direction:row-reverse!important}
.life{width:11.5px!important;height:11.5px!important;border-radius:50%!important;background:radial-gradient(circle at 32% 27%,#fff9da 0,#fff1ad 18%,#e1aa48 40%,#6e4718 66%,#05060a 100%)!important;box-shadow:0 0 0 1px rgba(5,6,9,.96),0 0 4px rgba(255,210,116,.64),0 1px 2px rgba(0,0,0,.9)!important}.life.off{background:radial-gradient(circle at 34% 30%,#545c68,#202632 56%,#02040a 100%)!important;box-shadow:0 0 0 1px rgba(5,6,9,.95),0 1px 2px rgba(0,0,0,.85)!important;opacity:.50!important}
.total{
  top:0!important;height:15px!important;font:900 12px/15px 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;
  letter-spacing:.95px!important;color:#edf2f8!important;opacity:.94!important;text-shadow:0 1px 1px #000,0 0 4px rgba(0,0,0,.8)!important;
}
.blue .total{left:112px!important}.red .total{right:112px!important}
.name{
  top:52px!important;height:18px!important;width:min(390px,calc(100% - 122px))!important;padding:2px 11px 0!important;z-index:62!important;
  font:900 16.5px/.90 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;letter-spacing:-.15px!important;color:#fff!important;
  background:linear-gradient(90deg,rgba(2,5,10,.98) 0%,rgba(14,21,31,.94) 46%,rgba(14,21,31,.58) 76%,rgba(14,21,31,0) 100%)!important;
  border-top:1px solid rgba(255,255,255,.20)!important;border-bottom:1px solid rgba(80,96,116,.38)!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.10),0 2px 2px rgba(0,0,0,.80)!important;
  text-shadow:0 1px 0 #000,0 0 3px rgba(0,0,0,.85)!important;
}
.blue .name{left:104px!important;text-align:left!important;border-left:3px solid var(--hud-cyan)!important}.red .name{right:104px!important;text-align:right!important;border-right:3px solid var(--hud-red)!important;border-left:0!important;background:linear-gradient(270deg,rgba(2,5,10,.98) 0%,rgba(14,21,31,.94) 46%,rgba(14,21,31,.58) 76%,rgba(14,21,31,0) 100%)!important}
.dmg{
  top:82px!important;font:900 11px/1 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;letter-spacing:.9px!important;color:#e2e8f0!important;opacity:.82!important;text-shadow:0 1px 1px #000,0 0 3px rgba(0,0,0,.9)!important;
}
.blue .dmg{left:16px!important}.red .dmg{right:16px!important;width:86px!important;text-align:right!important}
.flag{top:80px!important;width:34px!important;height:20px!important;opacity:.86!important}.blue .flag{left:76px!important}.red .flag{right:76px!important}
.recent{
  font:900 calc(var(--recent-font) * .50)/.94 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;letter-spacing:.25px!important;
  background:linear-gradient(90deg,rgba(3,6,12,.46),rgba(3,6,12,.16),rgba(3,6,12,0))!important;border-left:2px solid rgba(255,45,117,.86)!important;text-shadow:0 1px 0 #000,0 0 3px rgba(0,0,0,.82)!important;
}
.redRecent{background:linear-gradient(270deg,rgba(3,6,12,.46),rgba(3,6,12,.16),rgba(3,6,12,0))!important;border-left:0!important;border-right:2px solid rgba(255,45,117,.86)!important}
.hit{font:900 16px/.90 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;letter-spacing:.55px!important;color:#f2f5fa!important;-webkit-text-stroke:.25px #0b1020!important;text-shadow:0 1px 0 #000,0 0 3px rgba(0,0,0,.86)!important}.damage{font:900 23px/.84 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;letter-spacing:.55px!important;color:#ffc95d!important;-webkit-text-stroke:.55px #562006!important;text-shadow:0 1px 0 #000,0 0 4px rgba(255,180,62,.50)!important}.hit.counter{font-size:18px!important;min-width:86px!important;padding:2px 8px 3px!important;letter-spacing:1.0px!important;background:linear-gradient(90deg,#ff2d75,#ff4f95 64%,rgba(255,79,149,.18))!important;box-shadow:0 2px 0 #30020f,0 0 8px rgba(255,45,117,.42)!important}





/* === RFC HUD v13 FINAL: no life-frame overlap, larger portraits, cleaner fight text === */
/* Keep timer typography. Fix only: life dots, portrait/label spacing, non-timer text polish, stronger portrait FX. */
.hud{overflow:visible!important;}
.side{height:112px!important;overflow:visible!important;}

/* Life dots: no black capsule, no HP-bar overlap. They sit ABOVE the inner end of each HP bar. */
.lives{
  top:-10px!important;
  padding:0!important;
  gap:5px!important;
  background:transparent!important;
  border:0!important;
  box-shadow:none!important;
  filter:drop-shadow(0 1px 1px rgba(0,0,0,.95)) drop-shadow(0 0 4px rgba(255,204,104,.42))!important;
  z-index:310!important;
  pointer-events:none!important;
}
.blue .lives{right:22px!important;left:auto!important;flex-direction:row!important;}
.red .lives{left:22px!important;right:auto!important;flex-direction:row-reverse!important;}
.life{
  width:10px!important;height:10px!important;border-radius:50%!important;
  background:radial-gradient(circle at 30% 24%,#fffbe8 0%,#ffe7a6 22%,#cc9139 48%,#5a3510 72%,#07080c 100%)!important;
  box-shadow:inset 0 1px 1px rgba(255,255,255,.72),inset 0 -1px 1px rgba(0,0,0,.72),0 0 4px rgba(255,198,87,.55)!important;
  opacity:.98!important;
}
.life.off{
  background:radial-gradient(circle at 34% 28%,#5d6671 0%,#252c36 55%,#030409 100%)!important;
  box-shadow:inset 0 1px 1px rgba(255,255,255,.18),inset 0 -1px 1px rgba(0,0,0,.78),0 1px 1px rgba(0,0,0,.75)!important;
  opacity:.50!important;
}

/* Portraits: bigger, but the HP bar/nameplate are pushed away so nothing overlaps. */
.portrait{
  top:-24px!important;
  width:122px!important;height:122px!important;
  z-index:86!important;
  object-fit:contain!important;
  filter:drop-shadow(0 7px 9px rgba(0,0,0,.96)) drop-shadow(0 0 12px rgba(255,255,255,.30)) drop-shadow(0 0 15px rgba(255,122,34,.22));
}
.blue .portrait{left:-10px!important;--mirror:1!important;}
.red .portrait{right:-10px!important;--mirror:-1!important;transform:scaleX(-1);}

/* Small metal anchor behind portrait so it feels connected to the HP frame, not pasted on. */
.side:after{
  top:9px!important;width:124px!important;height:46px!important;z-index:14!important;opacity:.90!important;
  background:linear-gradient(180deg,rgba(255,255,255,.34) 0%,rgba(84,93,107,.42) 18%,rgba(5,8,14,.88) 54%,rgba(0,0,0,.92) 100%)!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.26),inset 0 -1px 0 rgba(255,119,28,.14),0 3px 6px rgba(0,0,0,.82)!important;
}
.blue:after{left:-18px!important;clip-path:polygon(0 0,100% 0,84% 100%,0 100%)!important;}
.red:after{right:-18px!important;clip-path:polygon(0 0,100% 0,100% 100%,16% 100%)!important;}

/* Push all HP/name texts away from the enlarged portrait. Timer CSS intentionally untouched. */
.blue .barWrap{left:128px!important;right:10px!important;top:22px!important;height:24px!important;}
.red .barWrap{right:128px!important;left:10px!important;top:22px!important;height:24px!important;}
.hpCanvas{position:absolute!important;inset:0!important;width:100%!important;height:100%!important;z-index:2!important;}

.total{
  top:0!important;height:15px!important;
  font:900 12px/15px 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;
  letter-spacing:.75px!important;color:#f4f7fb!important;opacity:.95!important;
  text-shadow:0 1px 1px #000,0 0 3px rgba(0,0,0,.85)!important;
  z-index:72!important;
}
.blue .total{left:132px!important;right:auto!important;}
.red .total{right:132px!important;left:auto!important;}

.name{
  top:54px!important;height:17px!important;width:min(392px,calc(100% - 150px))!important;
  padding:1px 10px 0!important;z-index:76!important;
  font:900 15.5px/.92 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;
  letter-spacing:-.28px!important;color:#f8fafc!important;
  text-shadow:0 1px 0 #000,0 0 2px rgba(0,0,0,.92)!important;
  background:linear-gradient(90deg,rgba(2,5,10,.98) 0%,rgba(11,17,27,.96) 45%,rgba(11,17,27,.56) 80%,rgba(11,17,27,0) 100%)!important;
  border-top:1px solid rgba(255,255,255,.18)!important;border-bottom:1px solid rgba(88,100,120,.34)!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 2px 2px rgba(0,0,0,.74)!important;
}
.blue .name{left:132px!important;right:auto!important;text-align:left!important;border-left:3px solid var(--hud-cyan)!important;}
.red .name{right:132px!important;left:auto!important;text-align:right!important;border-right:3px solid var(--hud-red)!important;border-left:0!important;background:linear-gradient(270deg,rgba(2,5,10,.98) 0%,rgba(11,17,27,.96) 45%,rgba(11,17,27,.56) 80%,rgba(11,17,27,0) 100%)!important;}

.dmg{
  top:84px!important;
  font:900 10.5px/1 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;
  letter-spacing:.70px!important;color:#dce6f2!important;opacity:.82!important;
  text-shadow:0 1px 1px #000,0 0 2px rgba(0,0,0,.9)!important;
  z-index:70!important;
}
.blue .dmg{left:18px!important;right:auto!important;}
.red .dmg{right:18px!important;left:auto!important;width:86px!important;text-align:right!important;}

/* Cleaner fight-game feedback text, without touching the timer. */
.recent{
  top:176px!important;
  font-family:'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;
  font-weight:900!important;letter-spacing:.15px!important;
  text-shadow:0 2px 0 #02040a,0 0 5px rgba(0,0,0,.95)!important;
}
.combo{
  top:148px!important;height:52px!important;width:210px!important;
  text-shadow:0 2px 0 #02040a,0 0 5px rgba(0,0,0,.95)!important;
}
.hit{
  font:900 22px/.88 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;
  letter-spacing:.35px!important;color:#f4f7fb!important;-webkit-text-stroke:.65px #111827!important;
}
.hit.counter{
  display:inline-block!important;padding:2px 9px 1px!important;
  color:#fff8fb!important;background:linear-gradient(90deg,#f92c72 0%,#b31346 68%,rgba(179,19,70,0) 100%)!important;
  -webkit-text-stroke:.45px #4a061c!important;clip-path:polygon(0 0,100% 0,92% 100%,0 100%)!important;
  text-shadow:0 2px 0 #3b0616,0 0 5px rgba(255,46,118,.54)!important;
}
.damage{
  font:900 21px/.9 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;
  letter-spacing:.15px!important;color:#ffd36a!important;-webkit-text-stroke:.55px #7c2d12!important;
  text-shadow:0 2px 0 #2b1005,0 0 5px rgba(255,177,46,.38)!important;
}

/* Stronger portrait reactions: makes stun/down/KO visibly fire when the JS class is applied. */





/* === RFC HUD v14: remove portrait backplate + slightly larger safe timer === */
/* Remove the dark metal anchor/background behind portraits. Keep only the portrait image/drop-shadow. */
.side:after{
  display:none!important;
  content:none!important;
  background:transparent!important;
  box-shadow:none!important;
  border:0!important;
}
/* Keep the HP frame away from the enlarged portrait so no dark plate sits behind the face/body. */
.blue:before{left:128px!important;}
.red:before{right:128px!important;}

/* Timer only: slightly bigger, still inside the reserved center gap so it cannot touch HP bars. */
.center{
  width:112px!important;
  height:66px!important;
  top:-5px!important;
}
.time{
  width:112px!important;
  height:49px!important;
  font-size:var(--timer-font)!important;
  line-height:.80!important;
  top:var(--timer-y)!important;
  letter-spacing:-2.8px!important;
  transform:translateX(var(--timer-x)) scaleX(.78)!important;
  transform-origin:center top!important;
}
.round{
  top:46px!important;
}




/* === RFC HUD v15: portrait FX actually visible ===
   Static portrait filter/transform !important was blocking keyframe animation.
   Keep the layout, but let hit/stun/KO animations control transform/filter while active. */
.portrait{
  will-change:transform,filter,opacity,box-shadow!important;
  transform-origin:center center!important;
}






/* === v17 PORTRAIT FX DEDUPE: remove duplicate backend pushes + exclusive portrait classes === */
/* Timer fill final: force OBS/CEF to use the internal highlight gradient. */
.time{
  background:
    linear-gradient(180deg,rgba(255,255,255,.38) 0%,rgba(255,255,255,.16) 18%,rgba(255,255,255,0) 34%,rgba(255,255,255,.34) 48%,rgba(255,255,255,.08) 54%,rgba(255,255,255,0) 66%),
    linear-gradient(180deg,#fbfdff 0%,#c9d0db 15%,#6e7685 30%,#1d232d 43%,#d8e0ea 49%,#5b6471 58%,#2f3540 70%,#67202a 88%,#160407 100%)!important;
  background-size:100% 100%!important;
  background-position:center!important;
  -webkit-background-clip:text!important;
  background-clip:text!important;
  color:transparent!important;
  -webkit-text-fill-color:transparent!important;
  -webkit-text-stroke:0!important;
  text-shadow:
    0 1.6px 0 #02040a,
    -.55px 0 rgba(132,32,44,.72),
    .55px 0 rgba(132,32,44,.72),
    0 -.55px rgba(168,47,58,.48),
    -.38px -.38px rgba(120,24,36,.44),
    .38px -.38px rgba(120,24,36,.44),
    -.38px .38px rgba(70,10,18,.58),
    .38px .38px rgba(70,10,18,.58)!important;
  filter:none!important;
}
.time::after{
  content:attr(data-text)!important;
  position:absolute!important;
  inset:-8px -12px -7px -12px!important;
  display:flex!important;
  align-items:flex-start!important;
  justify-content:center!important;
  padding-top:8px!important;
  pointer-events:none!important;
  background:
    radial-gradient(ellipse 82% 58% at 50% 38%,rgba(255,255,255,.24) 0%,rgba(235,244,255,.14) 24%,rgba(255,255,255,0) 58%),
    linear-gradient(180deg,rgba(255,255,255,0) 0%,rgba(255,255,255,.12) 24%,rgba(255,255,255,0) 42%,rgba(255,255,255,.22) 52%,rgba(205,226,255,.08) 60%,rgba(255,255,255,0) 76%),
    linear-gradient(100deg,rgba(255,255,255,0) 0%,rgba(255,255,255,.04) 34%,rgba(255,255,255,.18) 50%,rgba(255,255,255,.04) 66%,rgba(255,255,255,0) 100%)!important;
  background-size:145% 135%,140% 150%,150% 140%!important;
  background-position:center 48%,center 44%,center!important;
  -webkit-background-clip:text!important;
  background-clip:text!important;
  color:transparent!important;
  -webkit-text-fill-color:transparent!important;
  text-shadow:none!important;
  filter:none!important;
}
/* Same impact must not queue hit/stun/KO portrait animations twice. */

/* === v16 HP BAR IMPACT HOTFIX: QML-like stronger health gauge shake === */
.barWrap{transform-origin:center center!important;will-change:transform,filter!important;backface-visibility:hidden!important;}
.barWrap.heavy .hpCanvas,.barWrap.stun .hpCanvas,.barWrap.ko .hpCanvas{filter:drop-shadow(0 0 8px rgba(255,230,140,.72)) drop-shadow(0 0 4px rgba(255,95,32,.52))!important;}












/* === RFC HUD v18 FEEDBACK TEXT CLEANUP ===
   Combo/recent/punch text no longer shares the same space.
   Timer/HP/portrait layout is intentionally left alone. */
.combo,.recent{pointer-events:none!important;box-sizing:border-box!important;font-family:'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;}
.combo{top:124px!important;width:260px!important;height:60px!important;z-index:155!important;opacity:0!important;overflow:visible!important;transform-origin:center center!important;filter:drop-shadow(0 5px 8px rgba(0,0,0,.74))!important;}
.combo.show{opacity:1!important;}
.blueCombo{left:132px!important;text-align:left!important;}.redCombo{right:132px!important;text-align:right!important;}
.hit{display:inline-flex!important;align-items:center!important;justify-content:center!important;min-height:22px!important;padding:2px 9px 1px!important;max-width:235px!important;overflow:hidden!important;text-overflow:ellipsis!important;white-space:nowrap!important;font:900 20px/.92 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;letter-spacing:.35px!important;color:#f8fafc!important;-webkit-text-stroke:.35px rgba(2,6,23,.95)!important;text-shadow:0 2px 0 #02040a,0 0 7px rgba(0,0,0,.92)!important;background:linear-gradient(90deg,rgba(2,6,23,.92),rgba(15,23,42,.62),rgba(15,23,42,0))!important;border-top:1px solid rgba(255,255,255,.16)!important;border-bottom:1px solid rgba(0,0,0,.8)!important;clip-path:polygon(0 0,100% 0,94% 100%,0 100%)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.10),0 2px 0 rgba(0,0,0,.75)!important;}
.redCombo .hit{background:linear-gradient(270deg,rgba(2,6,23,.92),rgba(15,23,42,.62),rgba(15,23,42,0))!important;clip-path:polygon(6% 100%,0 0,100% 0,100% 100%)!important;}
.hit.counter{min-width:112px!important;max-width:242px!important;padding:2px 13px 1px!important;font-size:22px!important;letter-spacing:1.15px!important;color:#fff7fb!important;-webkit-text-stroke:.45px #3f0618!important;background:linear-gradient(90deg,#ff2d75 0%,#d11451 58%,rgba(209,20,81,.16) 100%)!important;border-top:1px solid rgba(255,210,228,.46)!important;border-bottom:1px solid rgba(73,5,28,.92)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.22),0 2px 0 #27020e,0 0 10px rgba(255,45,117,.44)!important;transform:none!important;}
.redCombo .hit.counter{background:linear-gradient(270deg,#ff2d75 0%,#d11451 58%,rgba(209,20,81,.16) 100%)!important;}
.damage{display:block!important;margin-top:1px!important;max-width:240px!important;overflow:hidden!important;text-overflow:ellipsis!important;white-space:nowrap!important;font:900 25px/.86 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;letter-spacing:.25px!important;color:#ffd76b!important;-webkit-text-stroke:.45px #4a1d05!important;text-shadow:0 2px 0 #160902,0 0 8px rgba(255,190,72,.46),0 0 2px #000!important;}
.redCombo .damage{margin-left:auto!important;}
.recent{top:194px!important;width:auto!important;min-width:128px!important;max-width:282px!important;min-height:34px!important;padding:5px 11px 6px!important;z-index:145!important;opacity:0!important;overflow:hidden!important;white-space:normal!important;font:900 calc(var(--recent-font) * .54)/.96 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;letter-spacing:.05px!important;color:#edf5ff!important;-webkit-text-stroke:0!important;text-shadow:0 2px 0 #02040a,0 0 5px rgba(0,0,0,.90)!important;background:linear-gradient(90deg,rgba(2,6,23,.88) 0%,rgba(13,20,32,.70) 55%,rgba(13,20,32,.05) 100%)!important;border-left:3px solid rgba(56,189,248,.82)!important;border-right:0!important;border-top:1px solid rgba(255,255,255,.13)!important;border-bottom:1px solid rgba(0,0,0,.75)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 3px 5px rgba(0,0,0,.58)!important;clip-path:polygon(0 0,100% 0,94% 100%,0 100%)!important;}
.recent.show{opacity:.94!important;}.blueRecent{left:132px!important;right:auto!important;text-align:left!important;}.redRecent{right:132px!important;left:auto!important;text-align:right!important;background:linear-gradient(270deg,rgba(2,6,23,.88) 0%,rgba(13,20,32,.70) 55%,rgba(13,20,32,.05) 100%)!important;border-left:0!important;border-right:3px solid rgba(248,113,113,.82)!important;clip-path:polygon(6% 100%,0 0,100% 0,100% 100%)!important;}
.recent.dimForCombo{opacity:.78!important;filter:saturate(1.02) brightness(.92)!important;}
.recent .punchLine{display:flex!important;align-items:baseline!important;gap:7px!important;min-width:0!important;}.redRecent .punchLine{justify-content:flex-end!important;}
.recent .punchName{display:inline-block!important;max-width:178px!important;overflow:hidden!important;text-overflow:ellipsis!important;white-space:nowrap!important;color:#f8fafc!important;font-size:1.05em!important;line-height:.92!important;}
.recent .punchDmg{display:inline-block!important;color:#ffd76b!important;font-size:1.34em!important;line-height:.84!important;letter-spacing:.15px!important;text-shadow:0 2px 0 #2b1005,0 0 6px rgba(255,194,80,.40)!important;}
.recent .punchWeak{display:inline-block!important;margin-top:2px!important;padding:1px 6px 2px!important;max-width:190px!important;overflow:hidden!important;text-overflow:ellipsis!important;white-space:nowrap!important;font-size:.82em!important;line-height:.92!important;letter-spacing:.35px!important;color:#bae6fd!important;background:rgba(2,132,199,.22)!important;border:1px solid rgba(125,211,252,.28)!important;text-shadow:0 1px 0 #02040a!important;}.redRecent .punchWeak{margin-left:auto!important;}









/* === RFC HUD v19 PUNCH TEXT SIZE HOTFIX ===
   Punch/recent hit text was too small in v18 because it used
   spectatorRecentTextSize * .54 (23px default => ~12px base).
   Keep the v18 no-overlap layout, but make punch name/damage readable. */
.recent{
  top:192px!important;
  min-width:168px!important;
  max-width:350px!important;
  min-height:46px!important;
  padding:7px 14px 8px!important;
  font:900 calc(var(--recent-font) * .74)/.98 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;
  letter-spacing:.12px!important;
  overflow:visible!important;
}
.blueRecent{left:132px!important;right:auto!important;}
.redRecent{right:132px!important;left:auto!important;}
.recent .punchLine{
  gap:9px!important;
  align-items:flex-end!important;
}
.recent .punchName{
  max-width:235px!important;
  font-size:1.10em!important;
  line-height:.90!important;
  letter-spacing:-.15px!important;
  color:#f9fbff!important;
  text-shadow:0 2px 0 #02040a,0 0 6px rgba(0,0,0,.96),0 0 7px rgba(125,211,252,.24)!important;
}
.recent .punchDmg{
  font-size:1.48em!important;
  line-height:.78!important;
  letter-spacing:.2px!important;
  color:#ffd56a!important;
  text-shadow:0 2px 0 #2a0d05,0 0 8px rgba(255,194,80,.58),0 0 3px rgba(0,0,0,.9)!important;
}
.recent .punchWeak{
  margin-top:4px!important;
  padding:2px 7px 3px!important;
  max-width:240px!important;
  font-size:.88em!important;
  line-height:.95!important;
  letter-spacing:.22px!important;
}
.recent.dimForCombo{
  opacity:.84!important;
  filter:saturate(.95) brightness(.96)!important;
}





/* === RFC HUD v20: portrait FX clean + feedback text 1080p layout ===
   1920x1080 湲곗?. 珥덉긽???ш컖 寃? 諛뺤뒪 ?쒓굅, 肄ㅻ낫/?移??띿뒪??諛붽묑 諛곗튂,
   ?移섏쥌瑜??됰꽕???섎┝ ?꾪솕. Timer/HP gauge logic untouched. */
.portrait{
  box-shadow:none!important;
  will-change:transform,filter,opacity!important;
  transform-origin:center center!important;
  filter:drop-shadow(0 5px 7px rgba(0,0,0,.68)) drop-shadow(0 0 10px rgba(255,255,255,.22));
}




/* Nickname/id plate: stop vertical/edge clipping, keep it attached to HP bar. */
.name{
  top:52px!important;
  height:22px!important;
  width:min(520px,calc(100% - 154px))!important;
  padding:3px 14px 1px!important;
  font:900 15.5px/1.04 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;
  letter-spacing:-.34px!important;
  overflow:visible!important;
  text-overflow:clip!important;
  white-space:nowrap!important;
  clip-path:polygon(0 0,100% 0,98.5% 100%,0 100%)!important;
}
.blue .name{left:132px!important;right:auto!important;text-align:left!important;}
.red .name{right:132px!important;left:auto!important;text-align:right!important;clip-path:polygon(1.5% 100%,0 0,100% 0,100% 100%)!important;}

/* Feedback text: move outward to fighter zones, not toward center. */
.combo{
  top:122px!important;
  width:252px!important;
  height:62px!important;
  max-width:252px!important;
  filter:drop-shadow(0 4px 7px rgba(0,0,0,.58))!important;
}
.blueCombo{left:46px!important;right:auto!important;text-align:left!important;}
.redCombo{right:46px!important;left:auto!important;text-align:right!important;}
.hit{max-width:250px!important;overflow:visible!important;text-overflow:clip!important;font-size:21px!important;}
.hit.counter{max-width:252px!important;font-size:22px!important;}
.damage{max-width:252px!important;overflow:visible!important;text-overflow:clip!important;font-size:25px!important;}

.recent{
  top:192px!important;
  min-width:226px!important;
  max-width:440px!important;
  min-height:48px!important;
  padding:7px 15px 8px!important;
  overflow:visible!important;
  font:900 calc(var(--recent-font) * .76)/.98 'Bahnschrift Condensed','Arial Narrow','Malgun Gothic',Arial,sans-serif!important;
  filter:drop-shadow(0 3px 5px rgba(0,0,0,.54))!important;
}
.blueRecent{left:46px!important;right:auto!important;text-align:left!important;}
.redRecent{right:46px!important;left:auto!important;text-align:right!important;}
.recent .punchLine{gap:10px!important;flex-wrap:nowrap!important;align-items:flex-end!important;}
.recent .punchName{
  max-width:330px!important;
  overflow:visible!important;
  text-overflow:clip!important;
  white-space:nowrap!important;
  font-size:1.10em!important;
  line-height:.92!important;
  letter-spacing:-.20px!important;
}
.recent .punchDmg{font-size:1.50em!important;line-height:.78!important;flex:0 0 auto!important;}
.recent .punchWeak{
  max-width:360px!important;
  overflow:visible!important;
  text-overflow:clip!important;
  white-space:nowrap!important;
  font-size:.90em!important;
  line-height:.96!important;
}





/* === RFC HUD v21: QML-timing FX cleanup ===
   1920x1080 湲곗?. 珥덉긽??寃? FX ?쒓굅, HP諛??붾뱾由?吏?띿떆媛?QML??留욎땄,
   ?移섏쥌瑜??쒖떆?쒓컙??留?tick留덈떎 ?곗옣?섎뒗 臾몄젣 ?섏젙??CSS. */
.portrait{
  box-shadow:none!important;
  filter:drop-shadow(0 2px 3px rgba(0,0,0,.38)) drop-shadow(0 0 8px rgba(255,255,255,.20));
}




/* HP諛??붾뱾由쇱? QML 湲곗???留욎떠 吏㏐퀬 媛뺥븯寃? ?ㅻ옒 ?⑤뒗 glow ?쒓굅. */
.barWrap.heavy .hpCanvas,.barWrap.stun .hpCanvas,.barWrap.ko .hpCanvas{filter:drop-shadow(0 0 5px rgba(255,230,140,.42))!important;}









/* === RFC HUD v24: full audit cleanup ===
   Combo timer no longer extends every render; portrait event class hold matches CSS duration.
   Keep portrait FX bright, no black box/shadow frame. */
.portrait.hit,.portrait.stun,.portrait.ko{box-shadow:none!important;outline:none!important;}
.portrait{background:transparent!important;}


/* === RFC HUD v25: keep portraits full-color during all FX ===
   v24 still used low saturate() inside stun/KO keyframes, so the flash could look grayscale.
   This final override removes desaturation and heavy black shadows from portrait effects. */
.portrait{
  background:transparent!important;
  mix-blend-mode:normal!important;
  opacity:1!important;
  filter:saturate(1.10) contrast(1.04) brightness(1.02)
         drop-shadow(0 2px 3px rgba(0,0,0,.42))
         drop-shadow(0 0 7px rgba(255,255,255,.20));
}
.portrait.hit{
  box-shadow:none!important;
  outline:none!important;
}
.portrait.stun{
  box-shadow:none!important;
  outline:none!important;
}
.portrait.ko{
  box-shadow:none!important;
  outline:none!important;
}






/* === RFC HUD v26: portrait FX restore / guaranteed visible ===
   Fix: heavy hits were mapped to weak hit, HP/recent changes only shook the bar,
   and class animation could be visually swallowed by old overrides.  This keeps portraits full-color
   and makes hit/heavy/stun/KO visibly fire without black box frames. */
.portrait,
.portrait.hit,
.portrait.heavy,
.portrait.stun,
.portrait.ko{
  box-shadow:none!important;
  outline:none!important;
  background:transparent!important;
  mix-blend-mode:normal!important;
  opacity:1!important;
  transform-origin:center center!important;
  will-change:transform!important;
}
.portraitFxLayer{
  position:absolute;top:-14px;width:86px;height:86px;z-index:72;pointer-events:none;border-radius:50%;opacity:0;
  background:radial-gradient(circle at 50% 48%,rgba(255,255,255,.98) 0%,rgba(255,255,255,.80) 20%,rgba(125,211,252,.50) 38%,rgba(255,128,48,.25) 58%,rgba(255,255,255,0) 74%);
  mix-blend-mode:screen;filter:none;transform-origin:center center;
  will-change:transform,opacity;backface-visibility:hidden;contain:paint;transform:translateZ(0);
}
.blue .portraitFxLayer{left:-21px}.red .portraitFxLayer{right:-21px}




.combo,.recent,.roundIntro,.koOverlay,.vs,.barWrap{will-change:transform,opacity;backface-visibility:hidden;transform:translateZ(0)}
.portrait{will-change:transform,opacity;backface-visibility:hidden}
.hpCanvas{contain:strict;will-change:contents}






/* Browser/OBS performance pass:
   Keep the original static HUD polish. Only runtime FX are forced onto transform/opacity paths. */
.barWrap,.combo,.recent,.roundIntro,.koOverlay,.vs,.koPanel{
  transform:translateZ(0);
  backface-visibility:hidden;
  perspective:1000px;
}
.portraitFxLayer.stun,.portraitFxLayer.ko,.portraitFxLayer.heavy,.portraitFxLayer.hit{
  filter:none!important;
}
.barWrap.hit,.barWrap.heavy,.barWrap.stun,.barWrap.ko,
.barWrap.heavy .hpCanvas,.barWrap.stun .hpCanvas,.barWrap.ko .hpCanvas,
.recent.dimForCombo,.combo.blueIn,.combo.redIn,.combo.bluePunch,.combo.redPunch,
.recent.bluePunch,.recent.redPunch{
  filter:none!important;
}

/* Text FX performance: combo/counter/recent must not trigger filter/reflow-heavy animation in OBS. */
.combo,.recent{
  contain:layout paint;
  will-change:transform,opacity;
}







/* Final HUD FX quality pass: old v16/v21 bar and portrait flash animations were too short/steppy. */
.blue .barWrap.hit{animation:blueBarHitQml .150s linear!important}
.red .barWrap.hit{animation:redBarHitQml .150s linear!important}
.blue .barWrap.heavy{animation:blueBarHeavyQml .430s cubic-bezier(.18,.9,.24,1)!important}
.red .barWrap.heavy{animation:redBarHeavyQml .430s cubic-bezier(.18,.9,.24,1)!important}
.blue .barWrap.stun{animation:blueBarStunQml .430s cubic-bezier(.14,1.05,.22,1)!important}
.red .barWrap.stun{animation:redBarStunQml .430s cubic-bezier(.14,1.05,.22,1)!important}
.blue .barWrap.ko{animation:blueBarKoQml .520s cubic-bezier(.14,1.05,.22,1)!important}
.red .barWrap.ko{animation:redBarKoQml .520s cubic-bezier(.14,1.05,.22,1)!important}
.combo.blueIn{animation:comboBlueInQml .230s cubic-bezier(.16,1.1,.26,1)!important}
.combo.redIn{animation:comboRedInQml .230s cubic-bezier(.16,1.1,.26,1)!important}
.combo.bluePunch{animation:comboBluePunchQml .260s linear!important}
.combo.redPunch{animation:comboRedPunchQml .260s linear!important}
.recent.bluePunch{animation:recentBlueImpactQml .210s linear!important}
.recent.redPunch{animation:recentRedImpactQml .210s linear!important}
.recent.dimForCombo{transform:translate3d(0,7px,0) scale(.94)!important;opacity:.70!important}

/* Combo/counter text sanity: avoid duplicate pseudo outlines; keep native stroke thin and aligned. */
.hit::before,.damage::before{content:none!important;display:none!important;}
.hit{ -webkit-text-stroke:.18px rgba(2,6,23,.82)!important; text-shadow:0 2px 0 #02040a,0 0 5px rgba(0,0,0,.84)!important; }
.hit.counter{ -webkit-text-stroke:.22px #3f0618!important; text-shadow:0 2px 0 #27020e,0 0 7px rgba(255,45,117,.42)!important; }
.damage{ -webkit-text-stroke:.22px #4a1d05!important; text-shadow:0 2px 0 #160902,0 0 6px rgba(255,190,72,.38),0 0 1px #000!important; }

/* Feedback side layout: only normal combo loses its black plate; counter/recent keep panels. */
.combo{
  width:360px!important;
  max-width:360px!important;
  height:80px!important;
  filter:drop-shadow(0 4px 7px rgba(0,0,0,.58))!important;
}
.blueCombo{left:24px!important;right:auto!important;text-align:left!important;}
.redCombo{right:24px!important;left:auto!important;text-align:right!important;}
.hit:not(.counter){
  padding:0!important;
  min-width:0!important;
  max-width:360px!important;
  justify-content:flex-start!important;
  background:transparent!important;
  border:0!important;
  clip-path:none!important;
  box-shadow:none!important;
  -webkit-text-stroke:.45px rgba(2,6,23,.90)!important;
  text-shadow:0 2px 0 #02040a,0 0 7px rgba(0,0,0,.95),0 0 8px rgba(255,255,255,.20)!important;
}
.redCombo .hit:not(.counter){justify-content:flex-end!important;}
.hit.counter{
  min-width:112px!important;
  max-width:242px!important;
  padding:2px 13px 1px!important;
  background:linear-gradient(90deg,#ff2d75 0%,#d11451 58%,rgba(209,20,81,.16) 100%)!important;
  border-top:1px solid rgba(255,210,228,.46)!important;
  border-bottom:1px solid rgba(73,5,28,.92)!important;
  clip-path:polygon(0 0,100% 0,92% 100%,0 100%)!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.22),0 2px 0 #27020e,0 0 10px rgba(255,45,117,.44)!important;
  -webkit-text-stroke:.45px #3f0618!important;
  text-shadow:0 2px 0 #27020e,0 0 7px rgba(255,45,117,.42)!important;
}
.redCombo .hit.counter{
  background:linear-gradient(270deg,#ff2d75 0%,#d11451 58%,rgba(209,20,81,.16) 100%)!important;
  clip-path:polygon(8% 100%,0 0,100% 0,100% 100%)!important;
}
.damage{
  max-width:360px!important;
  -webkit-text-stroke:.45px #4a1d05!important;
  text-shadow:0 2px 0 #160902,0 0 8px rgba(255,190,72,.50),0 0 3px #000!important;
}
.recent{
  min-width:226px!important;
  max-width:440px!important;
  padding:7px 15px 8px!important;
  background:linear-gradient(90deg,rgba(2,6,23,.88) 0%,rgba(13,20,32,.70) 55%,rgba(13,20,32,.05) 100%)!important;
  border-left:3px solid rgba(56,189,248,.82)!important;
  border-right:0!important;
  border-top:1px solid rgba(255,255,255,.13)!important;
  border-bottom:1px solid rgba(0,0,0,.75)!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 3px 5px rgba(0,0,0,.58)!important;
  clip-path:polygon(0 0,100% 0,94% 100%,0 100%)!important;
  text-shadow:0 2px 0 #02040a,0 0 5px rgba(0,0,0,.90)!important;
}
.blueRecent{left:24px!important;right:auto!important;text-align:left!important;}
.redRecent{
  right:24px!important;left:auto!important;text-align:right!important;
  background:linear-gradient(270deg,rgba(2,6,23,.88) 0%,rgba(13,20,32,.70) 55%,rgba(13,20,32,.05) 100%)!important;
  border-left:0!important;
  border-right:3px solid rgba(248,113,113,.82)!important;
  clip-path:polygon(6% 100%,0 0,100% 0,100% 100%)!important;
}
.recent .punchWeak{
  padding:1px 6px 2px!important;
  background:rgba(2,132,199,.22)!important;
  border:1px solid rgba(125,211,252,.28)!important;
  color:#bae6fd!important;
}
.total{
  font-family:var(--bt-total-family)!important;
  font-size:var(--bt-total-size)!important;
  font-weight:var(--bt-total-weight)!important;
  color:var(--bt-total-color)!important;
  opacity:var(--bt-total-opacity)!important;
  -webkit-text-stroke:var(--bt-total-stroke)!important;
}
.dmg{
  font-family:var(--bt-dmg-family)!important;
  font-size:var(--bt-dmg-size)!important;
  font-weight:var(--bt-dmg-weight)!important;
  color:var(--bt-dmg-color)!important;
  opacity:var(--bt-dmg-opacity)!important;
  -webkit-text-stroke:var(--bt-dmg-stroke)!important;
}
.hit{
  font-family:var(--bt-combo-family)!important;
  font-size:var(--bt-combo-size)!important;
  font-weight:var(--bt-combo-weight)!important;
  color:var(--bt-combo-color)!important;
  opacity:var(--bt-combo-opacity)!important;
  -webkit-text-stroke:var(--bt-combo-stroke)!important;
}
.damage{
  font-family:var(--bt-combo-family)!important;
  font-size:calc(var(--bt-combo-size) * 1.14)!important;
  font-weight:var(--bt-combo-weight)!important;
}
.recent{
  font-family:var(--bt-recent-family)!important;
  font-size:calc(var(--bt-recent-size) * .54)!important;
  font-weight:var(--bt-recent-weight)!important;
  color:var(--bt-recent-color)!important;
  -webkit-text-stroke:var(--bt-recent-stroke)!important;
}
.recent.show{opacity:var(--bt-recent-opacity)!important;}
.time{
  font-family:var(--bt-time-family)!important;
  font-size:var(--bt-time-size)!important;
  font-weight:var(--bt-time-weight)!important;
  -webkit-text-stroke:var(--bt-time-stroke)!important;
  text-shadow:var(--bt-time-shadow)!important;
  filter:var(--bt-time-filter)!important;
  opacity:var(--bt-time-opacity)!important;
}
@keyframes blueBarHitQml{0%{transform:translate3d(-7px,2px,0)}28%{transform:translate3d(7px,-2px,0)}58%{transform:translate3d(-4px,1px,0)}100%{transform:translate3d(0,0,0)}}
@keyframes redBarHitQml{0%{transform:translate3d(7px,2px,0)}28%{transform:translate3d(-7px,-2px,0)}58%{transform:translate3d(4px,1px,0)}100%{transform:translate3d(0,0,0)}}
@keyframes blueBarHeavyQml{0%{transform:translate3d(-18px,5px,0) rotate(-.7deg) scale(1.018)}16%{transform:translate3d(16px,-4px,0) rotate(.5deg) scale(.992)}34%{transform:translate3d(-10px,2px,0) rotate(-.28deg) scale(1.008)}58%{transform:translate3d(6px,-1px,0) rotate(.14deg)}82%{transform:translate3d(-2px,0,0)}100%{transform:translate3d(0,0,0) rotate(0) scale(1)}}
@keyframes redBarHeavyQml{0%{transform:translate3d(18px,5px,0) rotate(.7deg) scale(1.018)}16%{transform:translate3d(-16px,-4px,0) rotate(-.5deg) scale(.992)}34%{transform:translate3d(10px,2px,0) rotate(.28deg) scale(1.008)}58%{transform:translate3d(-6px,-1px,0) rotate(-.14deg)}82%{transform:translate3d(2px,0,0)}100%{transform:translate3d(0,0,0) rotate(0) scale(1)}}
@keyframes blueBarStunQml{0%{transform:translate3d(-22px,-5px,0) scale(1.024)}10%{transform:translate3d(19px,5px,0) scale(.99)}23%{transform:translate3d(-14px,-3px,0) scale(1.012)}42%{transform:translate3d(10px,2px,0)}65%{transform:translate3d(-5px,-1px,0)}100%{transform:translate3d(0,0,0) scale(1)}}
@keyframes redBarStunQml{0%{transform:translate3d(22px,-5px,0) scale(1.024)}10%{transform:translate3d(-19px,5px,0) scale(.99)}23%{transform:translate3d(14px,-3px,0) scale(1.012)}42%{transform:translate3d(-10px,2px,0)}65%{transform:translate3d(5px,-1px,0)}100%{transform:translate3d(0,0,0) scale(1)}}
@keyframes blueBarKoQml{0%{transform:translate3d(-24px,-8px,0) rotate(-1.2deg) scale(1.035)}18%{transform:translate3d(21px,8px,0) rotate(.8deg) scale(.98)}38%{transform:translate3d(-13px,-4px,0) rotate(-.35deg) scale(1.01)}65%{transform:translate3d(6px,2px,0) rotate(.14deg)}100%{transform:translate3d(0,0,0) rotate(0) scale(1)}}
@keyframes redBarKoQml{0%{transform:translate3d(24px,-8px,0) rotate(1.2deg) scale(1.035)}18%{transform:translate3d(-21px,8px,0) rotate(-.8deg) scale(.98)}38%{transform:translate3d(13px,-4px,0) rotate(.35deg) scale(1.01)}65%{transform:translate3d(-6px,2px,0) rotate(-.14deg)}100%{transform:translate3d(0,0,0) rotate(0) scale(1)}}
@keyframes comboBlueInQml{0%{opacity:0;transform:translate3d(-120px,14px,0) skewX(-10deg) scale(.82)}62%{opacity:1;transform:translate3d(16px,0,0) skewX(-2deg) scale(1.08)}100%{opacity:1;transform:translate3d(0,0,0) skewX(0) scale(1)}}
@keyframes comboRedInQml{0%{opacity:0;transform:translate3d(120px,14px,0) skewX(10deg) scale(.82)}62%{opacity:1;transform:translate3d(-16px,0,0) skewX(2deg) scale(1.08)}100%{opacity:1;transform:translate3d(0,0,0) skewX(0) scale(1)}}
@keyframes comboBluePunchQml{0%{transform:translate3d(-18px,-4px,0) rotate(-1.4deg) scale(1.18)}18%{transform:translate3d(11px,3px,0) rotate(.8deg) scale(.96)}38%{transform:translate3d(-7px,-2px,0) rotate(-.35deg) scale(1.06)}66%{transform:translate3d(3px,1px,0) rotate(.14deg)}100%{transform:translate3d(0,0,0) rotate(0) scale(1)}}
@keyframes comboRedPunchQml{0%{transform:translate3d(18px,-4px,0) rotate(1.4deg) scale(1.18)}18%{transform:translate3d(-11px,3px,0) rotate(-.8deg) scale(.96)}38%{transform:translate3d(7px,-2px,0) rotate(.35deg) scale(1.06)}66%{transform:translate3d(-3px,1px,0) rotate(-.14deg)}100%{transform:translate3d(0,0,0) rotate(0) scale(1)}}
@keyframes recentBlueImpactQml{0%{transform:translate3d(-12px,-3px,0) rotate(-.8deg) scale(1.10)}22%{transform:translate3d(9px,2px,0) rotate(.5deg) scale(.98)}48%{transform:translate3d(-5px,-1px,0) rotate(-.22deg) scale(1.03)}74%{transform:translate3d(2px,0,0)}100%{transform:translate3d(0,0,0) rotate(0) scale(1)}}
@keyframes recentRedImpactQml{0%{transform:translate3d(12px,-3px,0) rotate(.8deg) scale(1.10)}22%{transform:translate3d(-9px,2px,0) rotate(-.5deg) scale(.98)}48%{transform:translate3d(5px,-1px,0) rotate(.22deg) scale(1.03)}74%{transform:translate3d(-2px,0,0)}100%{transform:translate3d(0,0,0) rotate(0) scale(1)}}














/* QML parity pass: browser portrait FX uses the same side-specific motion model as timer_ui.qml. */
.blue .portrait.hit{animation:bluePortraitHitQml .186s linear!important}
.red .portrait.hit{animation:redPortraitHitQml .186s linear!important}
.blue .portrait.heavy{animation:bluePortraitHeavyQml .430s cubic-bezier(.25,.46,.45,.94)!important}
.red .portrait.heavy{animation:redPortraitHeavyQml .430s cubic-bezier(.25,.46,.45,.94)!important}
.blue .portrait.stun{animation:bluePortraitStunQml .746s cubic-bezier(.15,1.05,.22,1)!important}
.red .portrait.stun{animation:redPortraitStunQml .746s cubic-bezier(.15,1.05,.22,1)!important}
.blue .portrait.ko{animation:bluePortraitKoQml .620s cubic-bezier(.16,1.02,.24,1)!important}
.red .portrait.ko{animation:redPortraitKoQml .620s cubic-bezier(.16,1.02,.24,1)!important}
.portraitFxLayer.hit{background:radial-gradient(circle at 50% 48%,rgba(255,255,255,.76) 0%,rgba(255,255,255,.45) 22%,rgba(125,211,252,.22) 44%,rgba(255,255,255,0) 72%)!important}
.portraitFxLayer.heavy{background:radial-gradient(circle at 50% 48%,rgba(255,244,190,.95) 0%,rgba(255,172,64,.62) 26%,rgba(239,68,68,.36) 48%,rgba(255,255,255,0) 76%)!important}
.portraitFxLayer.stun{background:radial-gradient(circle at 50% 48%,rgba(255,255,255,1) 0%,rgba(230,252,255,.88) 22%,rgba(125,211,252,.60) 42%,rgba(255,255,255,0) 76%)!important}
.portraitFxLayer.ko{background:radial-gradient(circle at 50% 48%,rgba(255,255,255,.95) 0%,rgba(255,80,80,.68) 28%,rgba(127,29,29,.44) 52%,rgba(255,255,255,0) 78%)!important}

/* Browser VFX portrait stack: the container stays stable; child layers provide flash/ring/slash/sparks. */
.portraitFxLayer{background:none!important;opacity:1!important;overflow:visible!important;mix-blend-mode:normal!important;filter:none!important}
.portraitFxLayer.hit,.portraitFxLayer.heavy,.portraitFxLayer.stun,.portraitFxLayer.ko{background:none!important}
.portraitFxLayer .fxFlash,.portraitFxLayer .fxRing,.portraitFxLayer .fxCore,.portraitFxLayer .fxSlash,.portraitFxLayer .fxSparks{position:absolute;inset:-10px;display:block;pointer-events:none;opacity:0;transform-origin:center center;will-change:transform,opacity;backface-visibility:hidden;transform:translateZ(0)}
.portraitFxLayer .fxFlash{border-radius:50%;mix-blend-mode:screen;background:radial-gradient(circle at 50% 48%,rgba(255,255,255,1) 0%,rgba(255,255,255,.78) 16%,rgba(125,211,252,.22) 42%,rgba(255,255,255,0) 72%)}
.portraitFxLayer .fxRing{border-radius:50%;border:2px solid rgba(255,255,255,.0);box-shadow:0 0 0 rgba(255,255,255,0);mix-blend-mode:screen}
.portraitFxLayer .fxCore{border-radius:50%;mix-blend-mode:screen;background:conic-gradient(from 20deg,rgba(255,255,255,0),rgba(255,255,255,.70),rgba(56,189,248,.0),rgba(255,255,255,.48),rgba(255,255,255,0))}
.portraitFxLayer .fxSlash{left:-28px;right:-28px;top:26px;bottom:auto;height:20px;border-radius:999px;mix-blend-mode:screen;background:linear-gradient(90deg,rgba(255,255,255,0),rgba(255,255,255,.95),rgba(255,180,65,.82),rgba(255,255,255,0));transform:translate3d(-16px,0,0) rotate(-16deg) scaleX(.2);filter:blur(.2px)}
.portraitFxLayer .fxSparks{inset:-20px;border-radius:50%;mix-blend-mode:screen;background:radial-gradient(circle at 18% 42%,rgba(255,255,255,.95) 0 2px,transparent 3px),radial-gradient(circle at 82% 35%,rgba(125,211,252,.95) 0 2px,transparent 3px),radial-gradient(circle at 70% 78%,rgba(255,210,90,.95) 0 2px,transparent 3px),radial-gradient(circle at 30% 80%,rgba(255,255,255,.75) 0 1.5px,transparent 2.5px)}
.portraitFxLayer.hit .fxFlash{animation:vfxHitFlash .220s ease-out both}.portraitFxLayer.hit .fxRing{animation:vfxHitRing .260s ease-out both}
.portraitFxLayer.heavy .fxFlash{background:radial-gradient(circle at 50% 48%,rgba(255,250,210,1) 0%,rgba(255,191,80,.82) 20%,rgba(239,68,68,.32) 48%,rgba(255,255,255,0) 74%);animation:vfxHeavyFlash .340s ease-out both}.portraitFxLayer.heavy .fxRing{animation:vfxHeavyRing .420s ease-out both}.portraitFxLayer.heavy .fxSlash{animation:vfxHeavySlash .320s cubic-bezier(.14,1.05,.22,1) both}.portraitFxLayer.heavy .fxSparks{animation:vfxHeavySparks .360s ease-out both}
.portraitFxLayer.stun .fxFlash{background:radial-gradient(circle at 50% 48%,rgba(255,255,255,1) 0%,rgba(220,252,255,.98) 18%,rgba(56,189,248,.46) 50%,rgba(255,255,255,0) 78%);animation:vfxStunFlash .620s linear both}.portraitFxLayer.stun .fxRing{animation:vfxStunRing .700s cubic-bezier(.12,.9,.2,1) both}.portraitFxLayer.stun .fxCore{animation:vfxStunCore .520s linear both}.portraitFxLayer.stun .fxSparks{animation:vfxStunSparks .680s steps(5,end) both}
.portraitFxLayer.ko .fxFlash{background:radial-gradient(circle at 50% 48%,rgba(255,255,255,1) 0%,rgba(255,95,95,.86) 20%,rgba(127,29,29,.44) 52%,rgba(255,255,255,0) 78%);animation:vfxKoFlash .560s ease-out both}.portraitFxLayer.ko .fxRing{animation:vfxKoRing .620s cubic-bezier(.16,1,.22,1) both}.portraitFxLayer.ko .fxSlash{background:linear-gradient(90deg,rgba(255,255,255,0),rgba(255,255,255,.95),rgba(239,68,68,.94),rgba(255,255,255,0));animation:vfxKoSlash .470s cubic-bezier(.14,1.05,.22,1) both}.portraitFxLayer.ko .fxSparks{animation:vfxKoSparks .560s ease-out both}
@keyframes vfxHitFlash{0%{opacity:.92;transform:scale(.72)}46%{opacity:.42;transform:scale(1.08)}100%{opacity:0;transform:scale(1.24)}}
@keyframes vfxHitRing{0%{opacity:.75;transform:scale(.58);border-color:rgba(255,255,255,.86);box-shadow:0 0 12px rgba(125,211,252,.50)}100%{opacity:0;transform:scale(1.36);border-color:rgba(125,211,252,.08);box-shadow:0 0 4px rgba(125,211,252,0)}}
@keyframes vfxHeavyFlash{0%{opacity:1;transform:scale(.66)}20%{opacity:.78;transform:scale(1.05)}100%{opacity:0;transform:scale(1.48)}}
@keyframes vfxHeavyRing{0%{opacity:.95;transform:scale(.50);border-color:rgba(255,245,190,.96);box-shadow:0 0 15px rgba(255,178,55,.72)}55%{opacity:.46;transform:scale(1.16);border-color:rgba(255,125,45,.72)}100%{opacity:0;transform:scale(1.62);border-color:rgba(255,125,45,0);box-shadow:0 0 2px rgba(255,125,45,0)}}
@keyframes vfxHeavySlash{0%{opacity:0;transform:translate3d(-36px,5px,0) rotate(-18deg) scaleX(.15)}22%{opacity:1;transform:translate3d(0,0,0) rotate(-18deg) scaleX(1.12)}100%{opacity:0;transform:translate3d(34px,-4px,0) rotate(-18deg) scaleX(.72)}}
@keyframes vfxHeavySparks{0%{opacity:0;transform:scale(.7) rotate(0)}18%{opacity:1}100%{opacity:0;transform:scale(1.65) rotate(34deg)}}
@keyframes vfxStunFlash{0%{opacity:1;transform:scale(.72)}8%{opacity:.20;transform:scale(1.08)}16%{opacity:.92;transform:scale(.94)}30%{opacity:.18;transform:scale(1.18)}52%{opacity:.62;transform:scale(1.28)}100%{opacity:0;transform:scale(1.56)}}
@keyframes vfxStunRing{0%{opacity:1;transform:scale(.46) rotate(0);border-color:rgba(230,252,255,1);box-shadow:0 0 18px rgba(56,189,248,.92),inset 0 0 12px rgba(255,255,255,.72)}42%{opacity:.68;transform:scale(1.18) rotate(18deg);border-color:rgba(125,211,252,.86)}100%{opacity:0;transform:scale(1.82) rotate(46deg);border-color:rgba(125,211,252,0);box-shadow:0 0 2px rgba(56,189,248,0)}}
@keyframes vfxStunCore{0%{opacity:0;transform:scale(.72) rotate(0)}8%{opacity:.82}46%{opacity:.55;transform:scale(1.15) rotate(80deg)}100%{opacity:0;transform:scale(1.44) rotate(180deg)}}
@keyframes vfxStunSparks{0%{opacity:0;transform:scale(.8) rotate(0)}10%{opacity:1}72%{opacity:.85;transform:scale(1.55) rotate(-60deg)}100%{opacity:0;transform:scale(1.85) rotate(-88deg)}}
@keyframes vfxKoFlash{0%{opacity:1;transform:scale(.58)}18%{opacity:.88;transform:scale(1.18)}100%{opacity:0;transform:scale(1.95)}}
@keyframes vfxKoRing{0%{opacity:1;transform:scale(.38);border-color:rgba(255,255,255,.96);box-shadow:0 0 20px rgba(239,68,68,.85),inset 0 0 14px rgba(255,255,255,.6)}36%{opacity:.68;transform:scale(1.24);border-color:rgba(239,68,68,.9)}100%{opacity:0;transform:scale(2.05);border-color:rgba(239,68,68,0);box-shadow:0 0 2px rgba(239,68,68,0)}}
@keyframes vfxKoSlash{0%{opacity:0;transform:translate3d(-48px,8px,0) rotate(-20deg) scaleX(.12)}16%{opacity:1;transform:translate3d(-4px,0,0) rotate(-20deg) scaleX(1.24)}100%{opacity:0;transform:translate3d(50px,-7px,0) rotate(-20deg) scaleX(.60)}}
@keyframes vfxKoSparks{0%{opacity:0;transform:scale(.65) rotate(0)}12%{opacity:1}100%{opacity:0;transform:scale(2.0) rotate(52deg)}}


/* Hard kill external portrait VFX layers: no shapes outside the transparent portrait image. */
.portraitFxLayer{display:block!important;opacity:1!important;background:none!important;animation:none!important}
.portraitFxLayer *{display:block!important;animation:none}
/* Portrait image whole-body flash override: no circle FX, the fighter image itself reacts. */
.portraitFxLayer .fxRing,.portraitFxLayer .fxCore{display:none!important;animation:none!important}
.portraitFxLayer .fxFlash{inset:-8px -18px;border-radius:0!important;background:linear-gradient(104deg,rgba(255,255,255,0) 0%,rgba(255,255,255,.92) 31%,rgba(255,255,255,.16) 52%,rgba(255,255,255,0) 100%)!important;clip-path:polygon(0 18%,68% 0,100% 22%,74% 48%,100% 76%,32% 100%,0 72%,24% 48%)!important;mix-blend-mode:screen!important}
.portraitFxLayer .fxSlash{height:30px!important;border-radius:0!important;clip-path:polygon(0 44%,82% 0,100% 22%,18% 100%)!important;background:linear-gradient(90deg,rgba(255,255,255,0),rgba(255,255,255,1),rgba(255,184,54,.75),rgba(255,255,255,0))!important}
.portraitFxLayer .fxSparks{border-radius:0!important;background:linear-gradient(120deg,transparent 0 18%,rgba(255,255,255,.95) 19% 21%,transparent 22% 100%),linear-gradient(40deg,transparent 0 42%,rgba(125,211,252,.95) 43% 45%,transparent 46% 100%),linear-gradient(160deg,transparent 0 62%,rgba(255,220,95,.95) 63% 65%,transparent 66% 100%)!important}
.portraitFxLayer.hit .fxFlash{animation:vfxBodyFlash .160s ease-out both}.portraitFxLayer.hit .fxSlash{animation:vfxBodySlash .150s ease-out both}
.portraitFxLayer.heavy .fxFlash{animation:vfxBodyHeavyFlash .300s ease-out both}.portraitFxLayer.heavy .fxSlash{animation:vfxBodyHeavySlash .320s cubic-bezier(.14,1.05,.22,1) both}.portraitFxLayer.heavy .fxSparks{animation:vfxBodySparks .320s ease-out both}
.portraitFxLayer.stun .fxFlash{background:linear-gradient(100deg,rgba(255,255,255,0),rgba(255,255,255,1),rgba(56,189,248,.56),rgba(255,255,255,0))!important;animation:vfxBodyStunFlash .640s linear both}.portraitFxLayer.stun .fxSlash{background:linear-gradient(90deg,rgba(255,255,255,0),rgba(236,254,255,1),rgba(56,189,248,.86),rgba(255,255,255,0))!important;animation:vfxBodyStunBolt .520s steps(4,end) both}.portraitFxLayer.stun .fxSparks{animation:vfxBodyStunSparks .620s steps(5,end) both}
.portraitFxLayer.ko .fxFlash{background:linear-gradient(104deg,rgba(255,255,255,0),rgba(255,255,255,1),rgba(239,68,68,.66),rgba(255,255,255,0))!important;animation:vfxBodyKoFlash .460s ease-out both}.portraitFxLayer.ko .fxSlash{background:linear-gradient(90deg,rgba(255,255,255,0),rgba(255,255,255,1),rgba(239,68,68,.94),rgba(255,255,255,0))!important;animation:vfxBodyKoSlash .460s cubic-bezier(.14,1.05,.22,1) both}.portraitFxLayer.ko .fxSparks{animation:vfxBodyKoSparks .460s ease-out both}
@keyframes vfxBodyFlash{0%{opacity:1;transform:translate3d(-18px,0,0) skewX(-18deg) scaleX(.35)}100%{opacity:0;transform:translate3d(22px,0,0) skewX(-18deg) scaleX(1.15)}}
@keyframes vfxBodySlash{0%{opacity:.95;transform:translate3d(-24px,0,0) rotate(-18deg) scaleX(.25)}100%{opacity:0;transform:translate3d(28px,-3px,0) rotate(-18deg) scaleX(.9)}}
@keyframes vfxBodyHeavyFlash{0%{opacity:1;transform:translate3d(-28px,0,0) skewX(-18deg) scaleX(.32)}28%{opacity:.75;transform:translate3d(0,0,0) skewX(-18deg) scaleX(1.15)}100%{opacity:0;transform:translate3d(34px,0,0) skewX(-18deg) scaleX(1.35)}}
@keyframes vfxBodyHeavySlash{0%{opacity:0;transform:translate3d(-42px,8px,0) rotate(-18deg) scaleX(.15)}18%{opacity:1;transform:translate3d(-4px,0,0) rotate(-18deg) scaleX(1.18)}100%{opacity:0;transform:translate3d(46px,-7px,0) rotate(-18deg) scaleX(.62)}}
@keyframes vfxBodySparks{0%{opacity:0;transform:translate3d(-6px,0,0) scale(.86)}18%{opacity:1}100%{opacity:0;transform:translate3d(16px,-10px,0) scale(1.35)}}
@keyframes vfxBodyStunFlash{0%{opacity:1;transform:translate3d(-22px,0,0) skewX(-16deg) scaleX(.45)}10%{opacity:.12;transform:translate3d(18px,0,0) skewX(-16deg) scaleX(1.05)}22%{opacity:.95;transform:translate3d(-12px,0,0) skewX(-16deg) scaleX(.82)}48%{opacity:.28;transform:translate3d(18px,0,0) skewX(-16deg) scaleX(1.28)}100%{opacity:0;transform:translate3d(38px,0,0) skewX(-16deg) scaleX(1.55)}}
@keyframes vfxBodyStunBolt{0%{opacity:0;clip-path:polygon(0 45%,36% 18%,30% 42%,70% 10%,54% 48%,100% 26%,64% 74%,72% 48%,26% 92%)}12%{opacity:1;transform:translate3d(-26px,0,0) rotate(-10deg) scaleX(.7)}82%{opacity:.85;transform:translate3d(18px,-4px,0) rotate(-10deg) scaleX(1.05)}100%{opacity:0;transform:translate3d(34px,-8px,0) rotate(-10deg) scaleX(.7)}}
@keyframes vfxBodyStunSparks{0%{opacity:0;transform:scale(.82) rotate(0)}12%{opacity:1}100%{opacity:0;transform:scale(1.45) rotate(-18deg)}}
@keyframes vfxBodyKoFlash{0%{opacity:1;transform:translate3d(-30px,0,0) skewX(-20deg) scaleX(.38)}35%{opacity:.86;transform:translate3d(0,0,0) skewX(-20deg) scaleX(1.22)}100%{opacity:0;transform:translate3d(52px,0,0) skewX(-20deg) scaleX(1.58)}}
@keyframes vfxBodyKoSlash{0%{opacity:0;transform:translate3d(-54px,9px,0) rotate(-21deg) scaleX(.16)}14%{opacity:1;transform:translate3d(-8px,0,0) rotate(-21deg) scaleX(1.30)}100%{opacity:0;transform:translate3d(60px,-10px,0) rotate(-21deg) scaleX(.58)}}
@keyframes vfxBodyKoSparks{0%{opacity:0;transform:translate3d(-8px,3px,0) scale(.76)}16%{opacity:1}100%{opacity:0;transform:translate3d(22px,-16px,0) scale(1.62)}}
@keyframes bluePortraitHitQml{0%{transform:scaleX(1) translate3d(-5px,2px,0) scale(1.015);filter:brightness(2.15) contrast(1.28) saturate(1.18) drop-shadow(0 0 10px rgba(255,255,255,.78)) drop-shadow(0 0 8px rgba(255,166,48,.48))}32%{transform:scaleX(1) translate3d(4px,-2px,0) scale(.998);filter:brightness(1.28) contrast(1.10) saturate(1.12) drop-shadow(0 0 6px rgba(255,184,72,.42))}66%{transform:scaleX(1) translate3d(-2px,1px,0) scale(1.005);filter:brightness(1.08) contrast(1.04) saturate(1.08)}100%{transform:scaleX(1) translate3d(0,0,0) scale(1);filter:drop-shadow(0 3px 4px #000) drop-shadow(0 0 8px rgba(255,255,255,.30)) drop-shadow(0 0 10px rgba(255,126,32,.18))}}
@keyframes redPortraitHitQml{0%{transform:scaleX(-1) translate3d(5px,2px,0) scale(1.015);filter:brightness(2.15) contrast(1.28) saturate(1.18) drop-shadow(0 0 10px rgba(255,255,255,.78)) drop-shadow(0 0 8px rgba(255,166,48,.48))}32%{transform:scaleX(-1) translate3d(-4px,-2px,0) scale(.998);filter:brightness(1.28) contrast(1.10) saturate(1.12) drop-shadow(0 0 6px rgba(255,184,72,.42))}66%{transform:scaleX(-1) translate3d(2px,1px,0) scale(1.005);filter:brightness(1.08) contrast(1.04) saturate(1.08)}100%{transform:scaleX(-1) translate3d(0,0,0) scale(1);filter:drop-shadow(0 3px 4px #000) drop-shadow(0 0 8px rgba(255,255,255,.30)) drop-shadow(0 0 10px rgba(255,126,32,.18))}}
@keyframes bluePortraitHeavyQml{0%{transform:scaleX(1) translate3d(-24px,8px,0) rotate(-2.1deg) scale(1.11);filter:brightness(4.2) contrast(1.95) saturate(1.55) drop-shadow(0 0 22px rgba(255,229,135,1)) drop-shadow(0 0 18px rgba(255,68,28,.82))}13%{transform:scaleX(1) translate3d(18px,-8px,0) rotate(1.15deg) scale(.965);filter:brightness(1.85) contrast(1.45) saturate(1.34) drop-shadow(0 0 14px rgba(255,80,32,.80))}31%{transform:scaleX(1) translate3d(-13px,5px,0) rotate(-.75deg) scale(1.045);filter:brightness(1.35) contrast(1.18) saturate(1.20)}55%{transform:scaleX(1) translate3d(7px,-3px,0) rotate(.35deg) scale(.99);filter:brightness(1.12) contrast(1.08) saturate(1.12)}100%{transform:scaleX(1) translate3d(0,0,0) rotate(0) scale(1);filter:drop-shadow(0 3px 4px #000) drop-shadow(0 0 8px rgba(255,255,255,.30)) drop-shadow(0 0 10px rgba(255,126,32,.18))}}
@keyframes redPortraitHeavyQml{0%{transform:scaleX(-1) translate3d(24px,8px,0) rotate(2.1deg) scale(1.11);filter:brightness(4.2) contrast(1.95) saturate(1.55) drop-shadow(0 0 22px rgba(255,229,135,1)) drop-shadow(0 0 18px rgba(255,68,28,.82))}13%{transform:scaleX(-1) translate3d(-18px,-8px,0) rotate(-1.15deg) scale(.965);filter:brightness(1.85) contrast(1.45) saturate(1.34) drop-shadow(0 0 14px rgba(255,80,32,.80))}31%{transform:scaleX(-1) translate3d(13px,5px,0) rotate(.75deg) scale(1.045);filter:brightness(1.35) contrast(1.18) saturate(1.20)}55%{transform:scaleX(-1) translate3d(-7px,-3px,0) rotate(-.35deg) scale(.99);filter:brightness(1.12) contrast(1.08) saturate(1.12)}100%{transform:scaleX(-1) translate3d(0,0,0) rotate(0) scale(1);filter:drop-shadow(0 3px 4px #000) drop-shadow(0 0 8px rgba(255,255,255,.30)) drop-shadow(0 0 10px rgba(255,126,32,.18))}}
@keyframes bluePortraitStunQml{0%{transform:scaleX(1) translate3d(-16px,-10px,0) scale(1.09);filter:brightness(5.4) contrast(2.05) saturate(1.12) drop-shadow(0 0 28px rgba(230,252,255,1)) drop-shadow(0 0 20px rgba(56,189,248,.98))}7%{transform:scaleX(1) translate3d(15px,9px,0) scale(1.035);filter:brightness(.92) contrast(1.10) saturate(1.05)}15%{transform:scaleX(1) translate3d(-12px,-8px,0) scale(1.055);filter:brightness(4.8) contrast(1.90) saturate(1.12) drop-shadow(0 0 24px rgba(125,211,252,1))}28%{transform:scaleX(1) translate3d(10px,5px,0) scale(1.02);filter:brightness(1.0) contrast(1.16) saturate(1.08)}43%{transform:scaleX(1) translate3d(-7px,-3px,0) scale(1.032);filter:brightness(3.7) contrast(1.55) saturate(1.12) drop-shadow(0 0 18px rgba(255,255,255,.88))}68%{transform:scaleX(1) translate3d(4px,2px,0) scale(1.008);filter:brightness(1.35) contrast(1.14) saturate(1.10)}100%{transform:scaleX(1) translate3d(0,0,0) scale(1);filter:drop-shadow(0 3px 4px #000) drop-shadow(0 0 8px rgba(255,255,255,.30)) drop-shadow(0 0 10px rgba(255,126,32,.18))}}
@keyframes redPortraitStunQml{0%{transform:scaleX(-1) translate3d(16px,-10px,0) scale(1.09);filter:brightness(5.4) contrast(2.05) saturate(1.12) drop-shadow(0 0 28px rgba(230,252,255,1)) drop-shadow(0 0 20px rgba(56,189,248,.98))}7%{transform:scaleX(-1) translate3d(-15px,9px,0) scale(1.035);filter:brightness(.92) contrast(1.10) saturate(1.05)}15%{transform:scaleX(-1) translate3d(12px,-8px,0) scale(1.055);filter:brightness(4.8) contrast(1.90) saturate(1.12) drop-shadow(0 0 24px rgba(125,211,252,1))}28%{transform:scaleX(-1) translate3d(-10px,5px,0) scale(1.02);filter:brightness(1.0) contrast(1.16) saturate(1.08)}43%{transform:scaleX(-1) translate3d(7px,-3px,0) scale(1.032);filter:brightness(3.7) contrast(1.55) saturate(1.12) drop-shadow(0 0 18px rgba(255,255,255,.88))}68%{transform:scaleX(-1) translate3d(-4px,2px,0) scale(1.008);filter:brightness(1.35) contrast(1.14) saturate(1.10)}100%{transform:scaleX(-1) translate3d(0,0,0) scale(1);filter:drop-shadow(0 3px 4px #000) drop-shadow(0 0 8px rgba(255,255,255,.30)) drop-shadow(0 0 10px rgba(255,126,32,.18))}}
@keyframes bluePortraitKoQml{0%{transform:scaleX(1) translate3d(-4px,-18px,0) rotate(-2.4deg) scale(1.13);filter:brightness(4.7) contrast(2.1) saturate(1.2) drop-shadow(0 0 28px rgba(255,255,255,.95)) drop-shadow(0 0 24px rgba(239,68,68,1))}18%{transform:scaleX(1) translate3d(8px,18px,0) rotate(1.8deg) scale(.925);filter:brightness(.48) contrast(1.65) saturate(1.02) drop-shadow(0 0 18px rgba(127,29,29,.95))}38%{transform:scaleX(1) translate3d(-5px,-7px,0) rotate(-.9deg) scale(1.035);filter:brightness(1.65) contrast(1.38) saturate(1.05) drop-shadow(0 0 16px rgba(255,60,60,.78))}66%{transform:scaleX(1) translate3d(2px,4px,0) rotate(.35deg) scale(.985);filter:brightness(.78) contrast(1.22) saturate(1.02)}100%{transform:scaleX(1) translate3d(0,0,0) rotate(0) scale(1);filter:drop-shadow(0 3px 4px #000) drop-shadow(0 0 8px rgba(255,255,255,.30)) drop-shadow(0 0 10px rgba(255,126,32,.18))}}
@keyframes redPortraitKoQml{0%{transform:scaleX(-1) translate3d(4px,-18px,0) rotate(2.4deg) scale(1.13);filter:brightness(4.7) contrast(2.1) saturate(1.2) drop-shadow(0 0 28px rgba(255,255,255,.95)) drop-shadow(0 0 24px rgba(239,68,68,1))}18%{transform:scaleX(-1) translate3d(-8px,18px,0) rotate(-1.8deg) scale(.925);filter:brightness(.48) contrast(1.65) saturate(1.02) drop-shadow(0 0 18px rgba(127,29,29,.95))}38%{transform:scaleX(-1) translate3d(5px,-7px,0) rotate(.9deg) scale(1.035);filter:brightness(1.65) contrast(1.38) saturate(1.05) drop-shadow(0 0 16px rgba(255,60,60,.78))}66%{transform:scaleX(-1) translate3d(-2px,4px,0) rotate(-.35deg) scale(.985);filter:brightness(.78) contrast(1.22) saturate(1.02)}100%{transform:scaleX(-1) translate3d(0,0,0) rotate(0) scale(1);filter:drop-shadow(0 3px 4px #000) drop-shadow(0 0 8px rgba(255,255,255,.30)) drop-shadow(0 0 10px rgba(255,126,32,.18))}}


/* Hit/heavy portrait reactions: short impulse only. Stun/KO keep the flash-heavy keyframes above. */
@keyframes bluePortraitHitQml{0%{transform:scaleX(1) translate3d(-7px,1px,0) scale(1.018);filter:saturate(1.10) contrast(1.04) brightness(1.02) drop-shadow(0 2px 3px rgba(0,0,0,.42)) drop-shadow(0 0 7px rgba(255,255,255,.20))}42%{transform:scaleX(1) translate3d(2px,0,0) scale(.998);filter:saturate(1.10) contrast(1.04) brightness(1.02) drop-shadow(0 2px 3px rgba(0,0,0,.42)) drop-shadow(0 0 7px rgba(255,255,255,.20))}100%{transform:scaleX(1) translate3d(0,0,0) scale(1);filter:saturate(1.10) contrast(1.04) brightness(1.02) drop-shadow(0 2px 3px rgba(0,0,0,.42)) drop-shadow(0 0 7px rgba(255,255,255,.20))}}
@keyframes redPortraitHitQml{0%{transform:scaleX(-1) translate3d(7px,1px,0) scale(1.018);filter:saturate(1.10) contrast(1.04) brightness(1.02) drop-shadow(0 2px 3px rgba(0,0,0,.42)) drop-shadow(0 0 7px rgba(255,255,255,.20))}42%{transform:scaleX(-1) translate3d(-2px,0,0) scale(.998);filter:saturate(1.10) contrast(1.04) brightness(1.02) drop-shadow(0 2px 3px rgba(0,0,0,.42)) drop-shadow(0 0 7px rgba(255,255,255,.20))}100%{transform:scaleX(-1) translate3d(0,0,0) scale(1);filter:saturate(1.10) contrast(1.04) brightness(1.02) drop-shadow(0 2px 3px rgba(0,0,0,.42)) drop-shadow(0 0 7px rgba(255,255,255,.20))}}
@keyframes bluePortraitHeavyQml{0%{transform:scaleX(1) translate3d(-18px,4px,0) rotate(-1.15deg) scale(1.045);filter:saturate(1.10) contrast(1.04) brightness(1.02) drop-shadow(0 2px 3px rgba(0,0,0,.42)) drop-shadow(0 0 7px rgba(255,255,255,.20))}30%{transform:scaleX(1) translate3d(6px,-1px,0) rotate(.35deg) scale(.992);filter:saturate(1.10) contrast(1.04) brightness(1.02) drop-shadow(0 2px 3px rgba(0,0,0,.42)) drop-shadow(0 0 7px rgba(255,255,255,.20))}58%{transform:scaleX(1) translate3d(-2px,0,0) rotate(-.12deg) scale(1.006);filter:saturate(1.10) contrast(1.04) brightness(1.02) drop-shadow(0 2px 3px rgba(0,0,0,.42)) drop-shadow(0 0 7px rgba(255,255,255,.20))}100%{transform:scaleX(1) translate3d(0,0,0) rotate(0) scale(1);filter:saturate(1.10) contrast(1.04) brightness(1.02) drop-shadow(0 2px 3px rgba(0,0,0,.42)) drop-shadow(0 0 7px rgba(255,255,255,.20))}}
@keyframes redPortraitHeavyQml{0%{transform:scaleX(-1) translate3d(18px,4px,0) rotate(1.15deg) scale(1.045);filter:saturate(1.10) contrast(1.04) brightness(1.02) drop-shadow(0 2px 3px rgba(0,0,0,.42)) drop-shadow(0 0 7px rgba(255,255,255,.20))}30%{transform:scaleX(-1) translate3d(-6px,-1px,0) rotate(-.35deg) scale(.992);filter:saturate(1.10) contrast(1.04) brightness(1.02) drop-shadow(0 2px 3px rgba(0,0,0,.42)) drop-shadow(0 0 7px rgba(255,255,255,.20))}58%{transform:scaleX(-1) translate3d(2px,0,0) rotate(.12deg) scale(1.006);filter:saturate(1.10) contrast(1.04) brightness(1.02) drop-shadow(0 2px 3px rgba(0,0,0,.42)) drop-shadow(0 0 7px rgba(255,255,255,.20))}100%{transform:scaleX(-1) translate3d(0,0,0) rotate(0) scale(1);filter:saturate(1.10) contrast(1.04) brightness(1.02) drop-shadow(0 2px 3px rgba(0,0,0,.42)) drop-shadow(0 0 7px rgba(255,255,255,.20))}}/* HP bar impact: short punch, no dangling wobble. */
.blue .barWrap.hit{animation:blueBarHitQml .115s cubic-bezier(.12,.95,.18,1)!important}
.red .barWrap.hit{animation:redBarHitQml .115s cubic-bezier(.12,.95,.18,1)!important}
.blue .barWrap.heavy{animation:blueBarHeavyQml .205s cubic-bezier(.10,.92,.18,1)!important}
.red .barWrap.heavy{animation:redBarHeavyQml .205s cubic-bezier(.10,.92,.18,1)!important}
@keyframes blueBarHitQml{0%{transform:translate3d(-6px,1px,0) scale(1.006)}48%{transform:translate3d(2px,0,0) scale(.998)}100%{transform:translate3d(0,0,0) scale(1)}}
@keyframes redBarHitQml{0%{transform:translate3d(6px,1px,0) scale(1.006)}48%{transform:translate3d(-2px,0,0) scale(.998)}100%{transform:translate3d(0,0,0) scale(1)}}
@keyframes blueBarHeavyQml{0%{transform:translate3d(-17px,3px,0) rotate(-.55deg) scale(1.018)}26%{transform:translate3d(7px,-1px,0) rotate(.18deg) scale(.996)}56%{transform:translate3d(-3px,0,0) rotate(-.08deg) scale(1.004)}100%{transform:translate3d(0,0,0) rotate(0) scale(1)}}
@keyframes redBarHeavyQml{0%{transform:translate3d(17px,3px,0) rotate(.55deg) scale(1.018)}26%{transform:translate3d(-7px,-1px,0) rotate(-.18deg) scale(.996)}56%{transform:translate3d(3px,0,0) rotate(.08deg) scale(1.004)}100%{transform:translate3d(0,0,0) rotate(0) scale(1)}}
/* Final round damage placement: sit below the nameplate, beside the portrait. */
.dmg{
  top:78px!important;
  height:14px!important;
  z-index:72!important;
  font-family:var(--bt-dmg-family)!important;
  font-size:var(--bt-dmg-size)!important;
  font-weight:var(--bt-dmg-weight)!important;
  line-height:1!important;
  letter-spacing:.9px!important;
  color:var(--bt-dmg-color)!important;
  opacity:var(--bt-dmg-opacity)!important;
  -webkit-text-stroke:var(--bt-dmg-stroke)!important;
  text-shadow:0 1px 1px #000,0 0 4px rgba(0,0,0,.85)!important;
  pointer-events:none!important;
}
.blue .dmg{
  left:132px!important;
  right:auto!important;
  width:92px!important;
  text-align:left!important;
}
.red .dmg{
  right:132px!important;
  left:auto!important;
  width:92px!important;
  text-align:right!important;
}</style></head>
<body><div id="root"><div class="hud"><div class="side blue"><img id="blueImg" class="portrait"><div id="bluePortraitFx" class="portraitFxLayer"><i class="fxFlash"></i><i class="fxRing"></i><i class="fxCore"></i><i class="fxSlash"></i><i class="fxSparks"></i></div><div id="blueTotal" class="total">TOTAL DAMAGE 0</div><div id="blueBar" class="barWrap"><canvas id="blueHpCanvas" class="hpCanvas" width="338" height="38"></canvas></div><div id="blueLives" class="lives"></div><div id="blueName" class="name">BLUE</div><div id="blueDmg" class="dmg">DMG 0</div><img id="blueFlag" class="flag"></div><div class="center"><div id="time" class="time">3:00</div><div id="round" class="round">RD 1 OF 3</div></div><div class="side red"><img id="redImg" class="portrait"><div id="redPortraitFx" class="portraitFxLayer"><i class="fxFlash"></i><i class="fxRing"></i><i class="fxCore"></i><i class="fxSlash"></i><i class="fxSparks"></i></div><div id="redTotal" class="total">TOTAL DAMAGE 0</div><div id="redBar" class="barWrap"><canvas id="redHpCanvas" class="hpCanvas" width="338" height="38"></canvas></div><div id="redLives" class="lives"></div><div id="redName" class="name">RED</div><div id="redDmg" class="dmg">DMG 0</div><img id="redFlag" class="flag"></div><div id="blueRecent" class="recent blueRecent"></div><div id="redRecent" class="recent redRecent"></div><div id="blueCombo" class="combo blueCombo"><div id="blueHit" class="hit"></div><div id="blueComboDmg" class="damage"></div></div><div id="redCombo" class="combo redCombo"><div id="redHit" class="hit"></div><div id="redComboDmg" class="damage"></div></div></div><div id="roundIntro" class="fullscreen roundIntro"><div id="introMain" class="introMain"></div><div id="introSub" class="introSub">READY</div></div><div id="koOverlay" class="fullscreen koOverlay"><div class="flash"></div><div class="line1"></div><div class="line2"></div><div class="koPanel"><div id="koText" class="koText"></div></div></div><div id="vs" class="fullscreen vs"><img id="vsBg" class="vsBg"><div class="dark"></div><div class="grad"></div><div class="vsFlash"></div><div class="slash1"></div><div class="slash2"></div><img id="vsBlueImg" class="vsPortrait vsBlueImg"><img id="vsRedImg" class="vsPortrait vsRedImg"><div id="vsBlue" class="vsName vsBlue">BLUE</div><div id="vsRed" class="vsName vsRed">RED</div><div class="stagePanel"><div class="stageLabel">STAGE</div><div id="vsStage" class="stageName">DEFAULT</div></div></div></div>
<script>
let lastSeq=-1,lastEventId=0,seenFirst=false,lastCombo={blue:null,red:null},lastRecent={blue:null,red:null},prevHp={blue:null,red:null},lastPortraitFallback={blue:0,red:0},stateBusy=false,stateTimer=0;const timers={},recentActiveUntil={blue:0,red:0},comboActiveUntil={blue:0,red:0},barFx={blue:{kind:'',until:0,blockUntil:0},red:{kind:'',until:0,blockUntil:0}},portraitFx={blue:{kind:'',until:0,blockUntil:0},red:{kind:'',until:0,blockUntil:0}},lastHpDraw={blue:'',red:''},lastLivesDraw={blue:null,red:null},cssCache={};function q(id){return document.getElementById(id)}function setText(id,v){let e=q(id),s=String(v||'');if(e&&e.textContent!==s)e.textContent=s;if(e&&id==='time'&&e.dataset.text!==s)e.dataset.text=s}function setVar(n,v){let s=String(v);if(cssCache[n]===s)return;cssCache[n]=s;document.documentElement.style.setProperty(n,s)}function ratio(v){return Math.max(0,Math.min(1,Number(v)))||0}function retrigger(el,cls,ms=250){if(!el)return;if(!el.dataset.fxid)el.dataset.fxid='fx'+Math.random().toString(36).slice(2);let key='fx_'+el.dataset.fxid+'_'+cls,rafKey=key+'_raf';clearTimeout(timers[key]);if(timers[rafKey]){cancelAnimationFrame(timers[rafKey]);timers[rafKey]=0}el.classList.remove(cls);timers[rafKey]=requestAnimationFrame(()=>{el.classList.add(cls);timers[key]=setTimeout(()=>el.classList.remove(cls),ms)})}function restartClass(el,cls='show'){if(!el)return;if(!el.dataset.fxid)el.dataset.fxid='fx'+Math.random().toString(36).slice(2);let key='restart_'+el.dataset.fxid+'_'+cls;if(timers[key])cancelAnimationFrame(timers[key]);el.classList.remove(cls);timers[key]=requestAnimationFrame(()=>el.classList.add(cls))}function visible(id,on){let e=q(id),v=on?'1':'0';if(e&&e.dataset.visible!==v){e.dataset.visible=v;e.style.display=on?'':'none'}}function recentDamage(txt){let first=String(txt||'').split('\n')[0],m=first.match(/\d+(?:\.\d+)?/g);return m?Number(m[m.length-1]):0}function recentScore(txt){let parts=String(txt||'').split('\n'),weak=parts.length>1&&String(parts[1]||'').trim()!=='';return recentDamage(txt)*(weak?1.2:1)}function recentColor(txt){let s=recentScore(txt);return s>=60?'#ff3b30':s>=45?'#ff8a00':s>=30?'#ffd84d':s>=18?'#8be9ff':'#f8fafc'}function recentOutline(txt){let s=recentScore(txt);return s>=60?'#4c0519':s>=45?'#7c2d12':s>=30?'#713f12':s>=18?'#083344':'#020617'}function bump(el,cls,ms=220){retrigger(el,cls,ms)}function drawHp(side,hpVal,ghostVal,spVal){let key=[Number(hpVal||0).toFixed(4),Number(ghostVal||0).toFixed(4),Number((spVal??1)||0).toFixed(4)].join('|');if(lastHpDraw[side]===key)return;lastHpDraw[side]=key;let c=q(side+'HpCanvas');if(!c)return;let ctx=c.getContext('2d'),w=c.width,h=c.height;ctx.clearRect(0,0,w,h);let hp=ratio(hpVal),ghost=ratio(ghostVal),sp=ratio(spVal??1),slant=38,top=4.5,bottom=h-3.5,red=side==='red';function path(){ctx.beginPath();if(red){ctx.moveTo(slant,top);ctx.lineTo(w,top);ctx.lineTo(w-slant,bottom);ctx.lineTo(0,bottom)}else{ctx.moveTo(0,top);ctx.lineTo(w-slant,top);ctx.lineTo(w,bottom);ctx.lineTo(slant,bottom)}ctx.closePath()}ctx.save();ctx.shadowColor='rgba(0,0,0,0.75)';ctx.shadowBlur=10;ctx.shadowOffsetY=2;path();ctx.fillStyle='#05070b';ctx.fill();ctx.restore();ctx.save();path();ctx.clip();let bg=ctx.createLinearGradient(0,0,0,h);bg.addColorStop(0,'#171c27');bg.addColorStop(.42,'#05070d');bg.addColorStop(1,'#0b1020');ctx.fillStyle=bg;ctx.fillRect(0,0,w,h);ctx.fillStyle='#071225';ctx.fillRect(0,h-8.5,w,5.5);let spg=ctx.createLinearGradient(0,0,w,0);if(red){spg.addColorStop(0,'#1e3a8a');spg.addColorStop(.28,'#2563eb');spg.addColorStop(.68,'#38bdf8');spg.addColorStop(1,'#dff6ff')}else{spg.addColorStop(0,'#dff6ff');spg.addColorStop(.32,'#38bdf8');spg.addColorStop(.72,'#2563eb');spg.addColorStop(1,'#1e3a8a')}ctx.fillStyle=spg;if(red){let sw=w*sp;ctx.fillRect(w-sw,h-8.5,sw,5.5)}else ctx.fillRect(0,h-8.5,w*sp,5.5);let g=ctx.createLinearGradient(0,0,w,0);if(red){g.addColorStop(0,hp<.25?'#ef4444':'#fb923c');g.addColorStop(.22,'#f59e0b');g.addColorStop(.48,'#ffd45a');g.addColorStop(.82,'#fff2aa');g.addColorStop(1,'#fffdf0')}else{g.addColorStop(0,'#fffdf0');g.addColorStop(.18,'#fff2aa');g.addColorStop(.52,'#ffd45a');g.addColorStop(.78,'#f59e0b');g.addColorStop(1,hp<.25?'#ef4444':'#fb923c')}let fw=w*hp,gw=w*ghost;ctx.fillStyle='rgba(255,255,255,0.14)';if(red)ctx.fillRect(w-fw-gw,8.5,gw,h-19);else ctx.fillRect(fw,8.5,gw,h-19);ctx.fillStyle=g;if(red)ctx.fillRect(w-fw,8.5,fw,h-19);else ctx.fillRect(0,8.5,fw,h-19);let shine=ctx.createLinearGradient(0,8,0,h*.55);shine.addColorStop(0,'rgba(255,255,255,0.72)');shine.addColorStop(1,'rgba(255,255,255,0)');ctx.fillStyle=shine;if(red)ctx.fillRect(w-fw+10,10,Math.max(0,fw-20),6);else ctx.fillRect(10,10,Math.max(0,fw-20),6);ctx.fillStyle='rgba(255,255,255,0.13)';ctx.fillRect(0,8.5,w,2);ctx.restore();path();ctx.strokeStyle='#f8fafc';ctx.lineWidth=2.6;ctx.stroke();ctx.beginPath();if(red){ctx.moveTo(slant+7,top+3);ctx.lineTo(w-5,top+3)}else{ctx.moveTo(5,top+3);ctx.lineTo(w-slant-7,top+3)}ctx.strokeStyle='rgba(255,255,255,0.55)';ctx.lineWidth=1;ctx.stroke()}function lives(id,kd){let el=q(id),side=id.indexOf('red')===0?'red':'blue',k=Math.max(0,Math.min(3,Number(kd)||0));if(!el||lastLivesDraw[side]===k)return;lastLivesDraw[side]=k;el.innerHTML='';for(let i=0;i<3;i++){let d=document.createElement('div');d.className='life'+(i>=k?'':' off');el.appendChild(d)}}function escapeHtml(v){return String(v||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}function formatRecent(txt){let raw=String(txt||'').trim();if(!raw)return '';let lines=raw.split('\n').map(x=>String(x||'').trim()).filter(Boolean);let first=lines[0]||'',weak=lines.slice(1).join(' / '),m=first.match(/(.*?)(\d+(?:\.\d+)?)\s*$/);if(m){let name=m[1].trim()||'HIT',dmg=m[2];return '<div class="punchLine"><span class="punchName">'+escapeHtml(name)+'</span><span class="punchDmg">'+escapeHtml(dmg)+'</span></div>'+(weak?'<div class="punchWeak">'+escapeHtml(weak)+'</div>':'')}return '<div class="punchLine"><span class="punchName">'+escapeHtml(first)+'</span></div>'+(weak?'<div class="punchWeak">'+escapeHtml(weak)+'</div>':'')}function showRecent(side,txt,force=false){let el=q(side+'Recent'),key=String(txt||'').trim();if(!el)return;let now=(performance&&performance.now)?performance.now():Date.now(),hold=1450;if(!key){if(lastRecent[side]!==key||el.innerHTML)el.innerHTML='';el.classList.remove('show','dimForCombo');lastRecent[side]=key;recentActiveUntil[side]=0;clearTimeout(timers[side+'Recent']);return}let changed=lastRecent[side]!==key,wasShown=el.classList.contains('show');if(changed){el.innerHTML=formatRecent(key);recentActiveUntil[side]=now+hold}if(force){recentActiveUntil[side]=now+hold}if(now>recentActiveUntil[side]){el.classList.remove('show','dimForCombo');lastRecent[side]=key;return}el.classList.toggle('dimForCombo',q(side+'Combo')&&q(side+'Combo').classList.contains('show'));el.style.color='';el.style.webkitTextStroke='';el.style.textShadow='';el.classList.add('show');if(force||changed||!wasShown)retrigger(el,side==='blue'?'bluePunch':'redPunch',210);clearTimeout(timers[side+'Recent']);timers[side+'Recent']=setTimeout(()=>{el.classList.remove('show','dimForCombo')},Math.max(60,recentActiveUntil[side]-now));lastRecent[side]=key}
function combo(side,hit,dmg,force=false){let box=q(side+'Combo'),recent=q(side+'Recent'),key=(hit||'')+'|'+(dmg||''),changed=lastCombo[side]!==key,now=(performance&&performance.now)?performance.now():Date.now(),hold=1900;if(changed||force){setText(side+'Hit',hit);setText(side+'ComboDmg',dmg);let title=q(side+'Hit');if(title)title.classList.toggle('counter',String(hit||'').toUpperCase()==='COUNTER')}if(!hit){box.classList.remove('show','blueIn','redIn','bluePunch','redPunch');if(recent)recent.classList.remove('dimForCombo');lastCombo[side]=key;comboActiveUntil[side]=0;clearTimeout(timers[side+'Combo']);return}if(changed||force||!comboActiveUntil[side])comboActiveUntil[side]=now+hold;if(now>comboActiveUntil[side]){box.classList.remove('show');if(recent)recent.classList.remove('dimForCombo');lastCombo[side]=key;return}let first=lastCombo[side]===null||lastCombo[side]==='|';let wasShown=box.classList.contains('show');box.classList.add('show');if(recent&&recent.classList.contains('show'))recent.classList.add('dimForCombo');if(first&&changed)retrigger(box,side==='blue'?'blueIn':'redIn',230);if(force||changed||!wasShown)retrigger(box,side==='blue'?'bluePunch':'redPunch',260);clearTimeout(timers[side+'Combo']);timers[side+'Combo']=setTimeout(()=>{box.classList.remove('show');if(recent)recent.classList.remove('dimForCombo')},Math.max(60,comboActiveUntil[side]-now));lastCombo[side]=key}function showCounter(side,dmgText=''){let cur=(q(side+'ComboDmg')&&q(side+'ComboDmg').textContent)||'',hit=(q(side+'Hit')&&q(side+'Hit').textContent)||'',dmg=dmgText||cur,changed=(String(hit).toUpperCase()!=='COUNTER'||cur!==dmg);combo(side,'COUNTER',dmg,changed)}function hideFullscreen(except=''){for(const id of ['roundIntro','koOverlay','vs']){if(id===except)continue;let el=q(id);if(el)el.classList.remove('show')}if(except!=='roundIntro'){clearTimeout(timers.roundIntro);clearTimeout(timers.roundIntroFight)}if(except!=='koOverlay')clearTimeout(timers.ko);if(except!=='vs')clearTimeout(timers.vs)}function showRoundIntro(n,s){if(s&&s.showCinematic===false)return;hideFullscreen('roundIntro');let el=q('roundIntro'),main=q('introMain'),sub=q('introSub');let scale=Math.max(.1,Math.min(4,Number((s&&s.overlayUiScale)||1))),top=Number((s&&s.overlayTopPad)??40)||40;el.style.top=(top+160*scale)+'px';main.textContent='ROUND '+(n||'');sub.textContent='READY';restartClass(el,'show');clearTimeout(timers.roundIntroFight);timers.roundIntroFight=setTimeout(()=>{if(el.classList.contains('show')){main.textContent='FIGHT';sub.textContent=''}},1000);clearTimeout(timers.roundIntro);timers.roundIntro=setTimeout(()=>el.classList.remove('show'),2000)}function showKO(text,isTko=false){hideFullscreen('koOverlay');let el=q('koOverlay'),t=q('koText');t.textContent=isTko?'TECHNICAL\nKNOCKOUT':text;el.classList.toggle('tko',!!isTko);restartClass(el,'show');clearTimeout(timers.ko);timers.ko=setTimeout(()=>el.classList.remove('show'),2450)}function showVs(s){if(s&&s.showCinematic===false)return;hideFullscreen('vs');let v=q('vs'),bg=q('vsBg');v.style.setProperty('--vs-total',Math.max(2100,(s.overlayVsHoldMs||2800)+950)+'ms');if((s.vsbgRev||0)>0){bg.src='/asset/vsbg?rev='+(s.vsbgRev||0);bg.style.opacity=String(Math.max(0,Math.min(1,s.vsBgOpacity??1)));v.classList.add('hasBg')}else{bg.removeAttribute('src');bg.style.opacity='0';v.classList.remove('hasBg')}if(s.blueHasImage===true){q('vsBlueImg').style.display='';q('vsBlueImg').src='/image/blue?rev='+(s.blueImageRev||0)}else{q('vsBlueImg').style.display='none';q('vsBlueImg').removeAttribute('src')}if(s.redHasImage===true){q('vsRedImg').style.display='';q('vsRedImg').src='/image/red?rev='+(s.redImageRev||0)}else{q('vsRedImg').style.display='none';q('vsRedImg').removeAttribute('src')}setText('vsBlue',s.blueName||'BLUE');setText('vsRed',s.redName||'RED');setText('vsStage',s.arenaName||'DEFAULT');syncVsImages(s);restartClass(v,'show');clearTimeout(timers.vs);timers.vs=setTimeout(()=>v.classList.remove('show'),Math.max(2100,(s.overlayVsHoldMs||2800)+1050))}function syncVsImages(s){let v=q('vs');if(!v||!v.classList.contains('show'))return;let br=s.blueImageRev||0,rr=s.redImageRev||0;if(s.blueHasImage===true){q('vsBlueImg').style.display='';if(q('vsBlueImg').dataset.rev!=br){q('vsBlueImg').dataset.rev=br;q('vsBlueImg').src='/image/blue?rev='+br}}else{q('vsBlueImg').style.display='none';q('vsBlueImg').dataset.rev='';q('vsBlueImg').removeAttribute('src')}if(s.redHasImage===true){q('vsRedImg').style.display='';if(q('vsRedImg').dataset.rev!=rr){q('vsRedImg').dataset.rev=rr;q('vsRedImg').src='/image/red?rev='+rr}}else{q('vsRedImg').style.display='none';q('vsRedImg').dataset.rev='';q('vsRedImg').removeAttribute('src')}}function barPriority(cls){return cls==='ko'?4:cls==='stun'?3:cls==='heavy'?2:cls==='hit'?1:0}
function barImpact(side,cls,ms=220){let bar=q(side+'Bar');if(!bar)return;let fx=(cls==='ko'||cls==='stun'||cls==='heavy'||cls==='hit')?cls:'hit',now=(performance&&performance.now)?performance.now():Date.now(),st=barFx[side]||(barFx[side]={kind:'',until:0,blockUntil:0}),prio=barPriority(fx),cur=barPriority(st.kind);if(fx===st.kind&&now<st.blockUntil)return;if(now<st.until&&prio<cur)return;let req=Number(ms)||0,dur=req>0?req:(fx==='ko'?520:fx==='stun'?430:fx==='heavy'?210:115);retrigger(bar,fx,dur);st.kind=fx;st.until=now+dur;st.blockUntil=now+(fx==='hit'?55:95)}
function applyTextStyles(styles){styles=styles||{};function fam(v){return String(v||'Bahnschrift Condensed').replace(/['"\\]/g,'')}function num(v,d,min,max){let n=Number(v);if(!Number.isFinite(n))n=d;return Math.max(min,Math.min(max,n))}function hexToRgb(v){let s=String(v||'').trim();if(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(s)){if(s.length===4)s='#'+s[1]+s[1]+s[2]+s[2]+s[3]+s[3];return [parseInt(s.slice(1,3),16),parseInt(s.slice(3,5),16),parseInt(s.slice(5,7),16)]}return [185,28,43]}function rgba(v,a){let r=hexToRgb(v);return 'rgba('+r[0]+','+r[1]+','+r[2]+','+num(a,1,0,1).toFixed(3)+')'}function sty(key,prefix,defSize,defColor,defOpacity,defStrokeColor,defStrokeWidth){let s=styles[key]||{},family=fam(s.font_family);setVar('--bt-'+prefix+'-family',"'"+family+"','Arial Narrow','Malgun Gothic',Arial,sans-serif");setVar('--bt-'+prefix+'-size',String(num(s.font_size,defSize,1,220))+'px');setVar('--bt-'+prefix+'-weight',String(num(s.font_weight,900,100,900)));setVar('--bt-'+prefix+'-color',String(s.text_color||defColor));setVar('--bt-'+prefix+'-opacity',String(num(s.text_opacity??defOpacity,defOpacity,0,1)));setVar('--bt-'+prefix+'-stroke',String(num(s.border_width??defStrokeWidth,defStrokeWidth,0,12))+'px '+String(s.border_color||defStrokeColor))}function styTime(){let s=styles.time||{},family=fam(s.font_family),size=num(s.font_size,54,24,220),weight=num(s.font_weight,900,100,900),opacity=num(s.text_opacity??1,1,0,1),power=num(s.border_width??5,5,0,12),glow=String(s.border_color||'#b91c2b'),go=num(s.border_opacity??1,1,0,1);setVar('--bt-time-family',"'"+family+"','Arial Narrow','Malgun Gothic',Arial,sans-serif");setVar('--bt-time-size',String(size)+'px');setVar('--bt-time-weight',String(weight));setVar('--bt-time-opacity',String(opacity));setVar('--bt-time-stroke',(power<=0?'.18px rgba(255,255,255,.25)':'.35px rgba(255,255,255,.38)'));setVar('--bt-time-shadow','0 2px 0 #02040a,0 0 '+(3+power*.6).toFixed(1)+'px rgba(255,255,255,.72),0 0 '+(4+power*1.2).toFixed(1)+'px '+rgba(glow,.18+go*.42)+',0 0 '+(power*2.2).toFixed(1)+'px '+rgba(glow,.10+go*.20));setVar('--bt-time-filter','drop-shadow(0 0 '+(1+power*.25).toFixed(1)+'px rgba(255,255,255,.22))')}styTime();sty('total','total',12,'#f4f7fb',.95,'#000000',0);sty('dmg','dmg',12,'#e8eef7',.86,'#000000',0);sty('combo','combo',22,'#f4f7fb',1,'#111827',1);sty('recent','recent',23,'#edf5ff',.94,'#000000',0)}
function portraitPriority(cls){return cls==='ko'?4:cls==='stun'?3:cls==='heavy'?2:cls==='hit'?1:0}
function portraitDuration(cls,ms){let n=Number(ms)||0;if(n>0)return n;return cls==='ko'?580:cls==='stun'?520:cls==='heavy'?400:260}
function portraitAnimName(side,fx){let cap=fx==='hit'?'Hit':fx==='heavy'?'Heavy':fx==='stun'?'Stun':'Ko';return (side==='red'?'red':'blue')+'Portrait'+cap+'Qml'}
function portraitAnimCurve(fx){return fx==='hit'?'linear':fx==='heavy'?'cubic-bezier(.25,.46,.45,.94)':fx==='stun'?'cubic-bezier(.15,1.05,.22,1)':'cubic-bezier(.16,1.02,.24,1)'}
function portrait(side,cls,ms,dmg=0){let fx=(cls==='ko'||cls==='stun'||cls==='heavy'||cls==='hit')?cls:'hit',img=q(side+'Img'),n=Number(dmg)||0;if(fx==='hit')ms=Math.max(115,Math.min(150,105+n*.75));else if(fx==='heavy')ms=Math.max(175,Math.min(245,160+n*.95));let now=(performance&&performance.now)?performance.now():Date.now(),st=portraitFx[side]||(portraitFx[side]={kind:'',until:0,blockUntil:0}),prio=portraitPriority(fx),curPrio=portraitPriority(st.kind),skip=false;if(fx===st.kind&&now<st.blockUntil)skip=true;if(now<st.until&&prio<curPrio)skip=true;if(!skip){let dur=portraitDuration(fx,ms);if(img){if(!img.dataset.fxid)img.dataset.fxid='pfx'+Math.random().toString(36).slice(2);let rid='portrait_raf_'+img.dataset.fxid;clearTimeout(timers['portrait_'+side]);if(timers[rid]){cancelAnimationFrame(timers[rid]);timers[rid]=0}clearTimeout(timers['fx_'+img.dataset.fxid+'_hit']);clearTimeout(timers['fx_'+img.dataset.fxid+'_heavy']);clearTimeout(timers['fx_'+img.dataset.fxid+'_stun']);clearTimeout(timers['fx_'+img.dataset.fxid+'_ko']);img.classList.remove('hit','heavy','stun','ko');img.style.animation='none';void img.offsetWidth;timers[rid]=requestAnimationFrame(()=>{img.classList.add(fx);img.style.animation=portraitAnimName(side,fx)+' '+(dur/1000).toFixed(3)+'s '+portraitAnimCurve(fx)+' 1 both'});timers['portrait_'+side]=setTimeout(()=>{img.classList.remove('hit','heavy','stun','ko');img.style.animation=''},dur+80)}st.kind=fx;st.until=now+Math.max(120,dur-20);st.blockUntil=now+(fx==='hit'?55:95)}if(fx==='ko')barImpact(side,'ko',520);else if(fx==='stun')barImpact(side,'stun',430);else if(fx==='heavy'||n>=45)barImpact(side,'heavy',Math.max(150,Math.min(230,ms+25)));else if(fx==='hit')barImpact(side,'hit',Math.max(95,Math.min(145,ms+15)))}
function render(s){if(s.seq===lastSeq)return;lastSeq=s.seq;let baseScale=Math.max(.1,Math.min(4,Number(s.overlayUiScale)||1)),browserScale=Math.max(.25,Math.min(4,Number(s.browserOverlayScale)||1)),scale=Math.max(.1,Math.min(8,baseScale*browserScale));setVar('--ui-scale',scale);setVar('--overlay-top-pad',Number(s.overlayTopPad??40)||40);setVar('--recent-font',String(Math.max(10,Math.min(80,Number(s.spectatorRecentTextSize)||23)))+'px');setVar('--timer-font',String(Math.max(24,Math.min(96,Number(s.overlayTimerFontSize)||54)))+'px');setVar('--timer-x',String(Math.max(-160,Math.min(160,Number(s.overlayTimerX)||0)))+'px');setVar('--timer-y',String(Math.max(-80,Math.min(120,Number(s.overlayTimerY)||0)))+'px');setVar('--timer-opacity',String(Math.max(0,Math.min(1,Number(s.overlayTimerOpacity??1)))));setVar('--round-font',String(Math.max(6,Math.min(40,Number(s.overlayRoundFontSize)||11)))+'px');setVar('--round-x',String(Math.max(-160,Math.min(160,Number(s.overlayRoundX)||0)))+'px');setVar('--round-y',String(Math.max(-80,Math.min(120,Number(s.overlayRoundY)||0)))+'px');setVar('--round-opacity',String(Math.max(0,Math.min(1,Number(s.overlayRoundOpacity??1)))));applyTextStyles(s.browserTextStyles||{});visible('time',s.showTime!==false);visible('round',s.showRound!==false);visible('blueImg',s.showBlueImage!==false&&s.blueHasImage===true);visible('redImg',s.showRedImage!==false&&s.redHasImage===true);visible('blueName',s.showBlueName!==false);visible('redName',s.showRedName!==false);visible('blueFlag',s.showFlags!==false);visible('redFlag',s.showFlags!==false);setText('time',s.timeText||'');setText('round',String(s.roundText||'').replace(' of ',' OF '));setText('blueName',s.blueName||'BLUE');setText('redName',s.redName||'RED');setText('blueDmg',s.blueDamageText||'DMG 0');setText('redDmg',s.redDamageText||'DMG 0');setText('blueTotal','TOTAL DAMAGE '+(s.blueTotalDamageText||'0'));setText('redTotal','TOTAL DAMAGE '+(s.redTotalDamageText||'0'));let br=s.blueImageRev||0,rr=s.redImageRev||0;if(s.blueHasImage===true){if(q('blueImg').dataset.rev!=br){q('blueImg').dataset.rev=br;q('blueImg').src='/image/blue?rev='+br}}else{q('blueImg').dataset.rev='';q('blueImg').removeAttribute('src')}if(s.redHasImage===true){if(q('redImg').dataset.rev!=rr){q('redImg').dataset.rev=rr;q('redImg').src='/image/red?rev='+rr}}else{q('redImg').dataset.rev='';q('redImg').removeAttribute('src')}let bf=s.blueflagRev||0,rf=s.redflagRev||0;if(q('blueFlag').dataset.rev!=bf){q('blueFlag').dataset.rev=bf;if(bf>0)q('blueFlag').src='/asset/blueflag?rev='+bf;else q('blueFlag').removeAttribute('src')}if(q('redFlag').dataset.rev!=rf){q('redFlag').dataset.rev=rf;if(rf>0)q('redFlag').src='/asset/redflag?rev='+rf;else q('redFlag').removeAttribute('src')}drawHp('blue',s.blueHpRatio,s.blueHpGhostRatio,s.blueSpRatio);drawHp('red',s.redHpRatio,s.redHpGhostRatio,s.redSpRatio);syncVsImages(s);let evs=s.events||[],pendingFx={blue:false,red:false};for(let pi=0;pi<evs.length;pi++){let pe=evs[pi]||{};if((Number(pe.id)||0)<=lastEventId)continue;let ps=(pe.side==='red'?'red':(pe.side==='blue'?'blue':'')),pk=String(pe.kind||'').toLowerCase(),pd=Number(pe.damage)||0;if(ps&&(pk==='hit'||pk.includes('hit')||pk.includes('impact')||pk.includes('damage')||pk.includes('punch')||pk==='stun'||pk.includes('stun')||pk.includes('dizzy')||pk.includes('wobble')||pk.includes('shake')||pk.includes('knockdown')||pk==='down'||pk.includes('downed')||pk==='ko'||pk==='knockout'||pd>0))pendingFx[ps]=true}let bhp=ratio(s.blueHpRatio),rhp=ratio(s.redHpRatio),hasFreshFx=pendingFx.blue||pendingFx.red;if(!hasFreshFx&&prevHp.blue!==null&&prevHp.blue-bhp>.003){let drop=prevHp.blue-bhp,fx=drop>.07?'heavy':'hit';portrait('blue',fx,fx==='heavy'?430:186,Math.round(drop*100));lastPortraitFallback.blue=(performance&&performance.now)?performance.now():Date.now()}if(!hasFreshFx&&prevHp.red!==null&&prevHp.red-rhp>.003){let drop=prevHp.red-rhp,fx=drop>.07?'heavy':'hit';portrait('red',fx,fx==='heavy'?430:186,Math.round(drop*100));lastPortraitFallback.red=(performance&&performance.now)?performance.now():Date.now()}prevHp.blue=bhp;prevHp.red=rhp;lives('blueLives',s.blueRoundKnockdowns||0);lives('redLives',s.redRoundKnockdowns||0);showRecent('blue',s.blueRecentHitText||'',false);showRecent('red',s.redRecentHitText||'',false);combo('blue',s.blueComboHitText,s.blueComboDamageText,false);combo('red',s.redComboHitText,s.redComboDamageText,false);if(!seenFirst){seenFirst=true;let nowSec=Date.now()/1000;for(let j=0;j<evs.length;j++){let fe=evs[j]||{},fid=Number(fe.id)||0,fts=Number(fe.ts)||0;if(!fts||nowSec-fts>2.0)lastEventId=Math.max(lastEventId,fid)}}for(let i=0;i<evs.length;i++){let e=evs[i]||{};if((Number(e.id)||0)<=lastEventId)continue;lastEventId=Math.max(lastEventId,Number(e.id)||0);let side=(e.side==='red'?'red':(e.side==='blue'?'blue':''));let kind=String(e.kind||'').toLowerCase(),dmg=Number(e.damage)||0;let isVs=kind==='vs',isRound=(kind==='round'||kind==='round_intro'),isDown=(kind==='knockdown'||kind.includes('knockdown')||kind==='down'||kind.includes('downed')),isTko=(kind==='tko'||kind.includes('technical')),isKo=(kind==='ko'||kind==='knockout'||(kind.includes('knockout')&&!isTko)),isStun=(kind==='stun'||kind.includes('stun')||kind.includes('dizzy')||kind.includes('wobble')||kind.includes('shake')),isCounter=kind.includes('counter'),isHit=(kind==='hit'||kind.includes('hit')||kind.includes('impact')||kind.includes('damage')||kind.includes('punch')||dmg>0);if(isVs)showVs(s);else if(isRound&&s.showCinematic!==false)showRoundIntro(e.round||'',s);else if(!side)continue;else if(isDown){portrait(side,'ko',620,dmg);if(s.showCinematic!==false)showKO('KNOCK DOWN',false)}else if(isTko){portrait(side,'ko',620,dmg);if(s.showCinematic!==false)showKO('TECHNICAL\nKNOCKOUT',true)}else if(isKo){portrait(side,'ko',620,dmg);if(s.showCinematic!==false)showKO('KNOCKOUT',false)}else if(isStun){portrait(side,'stun',746,dmg)}else if(isCounter){showCounter(side,dmg>0?Math.round(dmg)+' DAMAGE':'')}else if(isHit){portrait(side,(dmg>=45?'heavy':'hit'),dmg>=45?430:186,dmg)}}}async function tick(){if(stateBusy)return;stateBusy=true;try{let r=await fetch('/state?ts='+Date.now(),{cache:'no-store'});render(await r.json())}catch(e){}finally{stateBusy=false}}function stateLoop(){tick();stateTimer=setTimeout(stateLoop,250)}function startStateStream(){if(!window.EventSource){stateLoop();return}let es=null,failed=false,fallback=()=>{if(failed)return;failed=true;try{if(es)es.close()}catch(e){}stateLoop()};try{es=new EventSource('/events');es.addEventListener('state',ev=>{try{render(JSON.parse(ev.data||'{}'))}catch(e){}});es.onopen=()=>{clearTimeout(stateTimer);tick()};es.onerror=()=>{setTimeout(fallback,1200)};stateTimer=setTimeout(fallback,1800)}catch(e){fallback()}}startStateStream();
</script></body></html>"""
