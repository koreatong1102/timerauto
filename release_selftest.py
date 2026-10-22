"""Offline source/frozen parity check. Never starts watchers, OBS or audio."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback
from types import SimpleNamespace


def run_checks():
    # Isolate even incidental diagnostic/archive writes from the live install.
    previous_cwd = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="TimerAuto_release_check_") as temp:
        os.chdir(temp)
        try:
            return _checks(Path(temp))
        finally:
            os.chdir(previous_cwd)


def _checks(temp):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, QUrl
    from PyQt6.QtGui import QGuiApplication, QImage
    from PyQt6.QtQml import QQmlComponent, QQmlEngine
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput  # Import only: no playback.
    import cv2
    import numpy as np
    import edge_tts
    import aiohttp
    from browser_overlay import BrowserOverlayServer
    from config_model import AppConfig
    from event_engine import FightEventEngine
    from spectator_log_watcher import SpectatorLogWatcher
    from match_log_archive import MatchLogArchive
    from match_event_ledger import MatchEventLedger
    from venue_backgrounds import VENUES
    from commentary_entertainment import bgrade_demo_steps
    from local_tts import commentary_voice, decode_voice
    from speech_runtime import commentary_cache_path
    from tts_settings import TtsEngineControls  # import-only: no UI or model download

    app = QGuiApplication.instance() or QGuiApplication([])
    qml_engine = QQmlEngine()
    component = QQmlComponent(qml_engine)
    component.setData(b'import QtQuick\nimport QtQuick.Controls\nimport QtMultimedia\nItem { width: 16; height: 16; Label { text: "check" } }', QUrl())
    obj = component.create()
    if obj is None:
        raise RuntimeError("QML plugin load failed: " + "; ".join(e.toString() for e in component.errors()))

    cfg = AppConfig()
    qwen_cfg = AppConfig()
    qwen_cfg.spectator_tts_engine = "qwen3"
    qwen_voice = commentary_voice(qwen_cfg, "caster", "")
    local_speech = {"default_engine": cfg.spectator_tts_engine, "options": decode_voice(qwen_voice),
                    "cache_suffix": Path(commentary_cache_path("offline", "caster", qwen_voice, 200, 100, 0)).suffix}
    if local_speech["default_engine"] != "edge" or local_speech["cache_suffix"] != ".wav":
        raise AssertionError("Optional local TTS/default Edge regression")
    # Regression gate for the genuine 1.01 -> synthetic 1.00 identity split.
    probe_ledger = MatchEventLedger(str(temp / "identity-probe.db"))
    try:
        probe = {"time": 14.23, "damage": 31.23, "attacker_side": "blue", "receiver_side": "red",
                 "counter_mult": 1.01, "raw_line": "2\t14.23\t31.23\t1.01\tred\tright\t.4\t.4\t0\t0\t0\tCross\tHit\tHead"}
        probe_ledger.upsert_events(2, "damage", [probe])
        probe_ledger.upsert_events(2, "damage", [dict(probe, counter_reason="whiff")])
        probe_rows = probe_ledger.records()[2]["events"]
        if len(probe_rows) != 1 or probe_rows[0]["counter_mult"] != 1.01:
            raise AssertionError("Immutable multiplier / ledger identity regression")
    finally:
        probe_ledger.close()
    watcher = SpectatorLogWatcher(cfg)
    archive = MatchLogArchive(str(temp / "archive"))
    watcher._match_archive = archive
    try:
        # Round-prefixed current format, ordinary hit, counter, combo and KD.
        lines = [
            "1\t100\t28\t1.03\tred\tleft\t.4\t.4\t0\t0\t0\tJab\tHit\tChin",
            "1\t99.6\t32\t1\tred\tright\t.4\t.4\t0\t0\t0\tCross\tHit\tChin",
            "1\t95\t12\t1\tblue\tleft\t.4\t.4\t0\t0\t0\tJab\tHit\t",
            "1\t90\t65\t1\tred\tright\t.4\t.4\t0\t0\t0\tHook\tKnockdown\tChin",
        ]
        events = [watcher._parse_damage_event_parts(line.split("\t")) for line in lines]
        if any(ev is None for ev in events):
            raise AssertionError("SpectatorLog fixture failed to parse")
        for ev in events:
            ev["effect_kind"] = watcher._damage_effect_kind(ev["damage_type"])
        watcher._annotate_counter_events(events)
        engine = FightEventEngine(cfg)
        verdicts = engine.classify_many(events)
        if not verdicts[0]["counter"] or verdicts[1]["combo_hits"] != 2 or "knockdown" not in verdicts[-1]["tags"]:
            raise AssertionError("Counter/combo/KD golden fixture mismatch")
        archive.start("offline-parity", ("BLUE", "RED"))
        for event, verdict in zip(events, verdicts):
            event["_central_event"] = verdict
        archive.record_damage(1, events)
        archive.record_classified(1, events, ruleset_version=engine.ruleset_version())
        report = watcher._build_round_report_payload(str(temp / "damage_events.txt"), 1, ("BLUE", "RED"), force_final=False)
        # Keep all report fields except presentation IDs/timing (non-deterministic).
        report_facts = {side: report[side] for side in ("blue", "red")}
        for facts in report_facts.values():
            for key in list(facts):
                if "image" in key.lower() or "portrait" in key.lower():
                    facts.pop(key)
        overlay = BrowserOverlayServer()
        html = overlay._html()
        for element in ("blueNickname", "redNickname", "vsBlueGameId", "vsRedGameId"):
            if f'id="{element}"' not in html:
                raise AssertionError("HUD/VS element missing: " + element)
        # Decode actual packaged runtime assets without playing anything.
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        assets = {}
        asset_names = ["timer_ui.qml", "cinematic_overlay.qml", "timer_controls.qml", "assets/images/overlays/KD.png", "assets/images/overlays/TKO.png"]
        asset_names.extend(venue[1] for venue in VENUES.values())
        for name in asset_names:
            path = base / name
            data = path.read_bytes()
            if name.endswith(".png") and QImage(str(path)).isNull():
                raise AssertionError("Cannot decode " + name)
            assets[name] = hashlib.sha256(data).hexdigest()
        pixel = np.zeros((4, 4, 3), dtype=np.uint8)
        if not cv2.imencode(".png", pixel)[0]:
            raise AssertionError("OpenCV image encoder unavailable")
        return {"schema": 1, "ok": True, "ruleset": engine.ruleset_version(), "verdicts": verdicts,
                "local_speech_configuration": local_speech,
                "bgrade_commentary": bgrade_demo_steps(),
                "report": report_facts, "overlay_sha256": hashlib.sha256(html.encode()).hexdigest(),
                "assets": assets, "runtime": {"python": sys.version.split()[0], "pyqt": PYQT_VERSION_STR,
                "qt": QT_VERSION_STR, "numpy": np.__version__, "opencv": cv2.__version__,
                "edge_tts": edge_tts.__version__, "aiohttp": aiohttp.__version__}}
    finally:
        archive.close()
        del obj, component, qml_engine
        app.processEvents()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-self-test", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected")
    parser.add_argument("--verify-package", action="store_true")
    args = parser.parse_args()
    try:
        result = run_checks()
        if args.verify_package:
            from release_integrity import verify_package
            integrity = verify_package(Path(sys.executable).parent)
            if not integrity["ok"]:
                raise AssertionError("Package integrity failed: " + json.dumps(integrity))
        if args.expected:
            expected = json.loads(Path(args.expected).read_text(encoding="utf-8"))
            if result != expected:
                changed = [key for key in sorted(set(result) | set(expected)) if result.get(key) != expected.get(key)]
                raise AssertionError("Source/frozen results differ: " + ", ".join(changed))
    except Exception:
        result = {"ok": False, "error": traceback.format_exc()}
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
