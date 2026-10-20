import copy
import json
import tempfile
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from commentary_entertainment import BGradeCommentary, STYLE_CHOICES, bgrade_demo_steps, normalize_style
from commentary_director import CommentaryCandidate, CommentaryDecision, CommentaryDirector
from config_model import AppConfig
from spectator_log_watcher import SpectatorLogWatcher


class EntertainmentStyleTests(unittest.TestCase):
    def test_old_and_unknown_configs_remain_sports(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "config.json")
            for data in ({}, {"spectator_commentary_style": "unknown"}):
                path.write_text(json.dumps(data), encoding="utf-8")
                self.assertEqual(AppConfig.from_json(str(path)).spectator_commentary_style, "sports")
        self.assertEqual(normalize_style("B_GRADE"), "b_grade")
        self.assertEqual([value for _, value in STYLE_CHOICES], ["sports", "b_grade"])

    def test_style_round_trips_independently_of_frequency(self):
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root, "config.json"))
            cfg = AppConfig()
            cfg.spectator_commentary_style = "b_grade"
            cfg.spectator_commentary_mode = "quiet"
            cfg.to_json(path)
            restored = AppConfig.from_json(path)
            self.assertEqual(restored.spectator_commentary_style, "b_grade")
            self.assertEqual(restored.spectator_commentary_mode, "quiet")

    def test_profanity_is_uncensored_and_same_sentence_does_not_repeat(self):
        bank = BGradeCommentary()
        first = bank.pick("counter", now=100)
        self.assertIn("씨발", first)
        self.assertEqual(bank.pick("counter", now=101), "")
        second = bank.pick("counter", now=109)
        self.assertNotEqual(first, second)
        bank.reset_match()
        self.assertEqual(bank.pick("counter", now=110), first)

    def test_decorating_never_mutates_facts_and_obeys_central_false_counter(self):
        bank = BGradeCommentary()
        event = {"is_counter": True, "damage": 12, "_central_event": {"counter": False, "tags": ["hit"]}}
        saved = copy.deepcopy(event)
        self.assertEqual(bank.decorate("유효타입니다.", event, "event_analysis", now=100), "유효타입니다.")
        self.assertEqual(event, saved)

    def test_whiff_graze_and_combo_have_different_context(self):
        for verdict, expected in (
            ({"counter": True, "counter_reason": "whiff"}, "계산은 본인"),
            ({"counter": True, "counter_reason": "graze"}, "답장이"),
            ({"counter": True, "combo_hits": 3}, "추가 배송"),
            ({"combo_hits": 4}, "여러 개"),
        ):
            bank = BGradeCommentary()
            text = bank.decorate("정확한 상황 콜.", {"_central_event": verdict}, "event_analysis", now=100)
            self.assertTrue(text.startswith("정확한 상황 콜."))
            self.assertIn(expected, text)

    def test_specials_keep_the_actual_result_call(self):
        for category in ("knockdown", "stun", "tko"):
            base = f"현선호, {category}입니다!"
            text = BGradeCommentary().decorate(base, {}, category, now=100)
            self.assertTrue(text.startswith(base))
            self.assertNotEqual(text, base)

    def test_preview_uses_real_style_bank_and_has_duo(self):
        steps = bgrade_demo_steps()
        self.assertTrue(any("씨발" in step["text"] + step.get("followup_text", "") for step in steps))
        self.assertTrue(any(step.get("followup_text") for step in steps))
        self.assertEqual({step["role"] for step in steps}, {"caster", "analyst"})

    def test_actual_settings_dialog_exposes_style_and_routes_preview(self):
        # An isolated offscreen process avoids touching the user's live window,
        # starting MainApp/OBS/audio, or mixing QApplication with other tests.
        script = '''
import os,tempfile
from PyQt6.QtWidgets import QApplication
from config_model import AppConfig
from timerauto import SettingsDialog
app=QApplication([])
previous=os.getcwd()
with tempfile.TemporaryDirectory(prefix="rfc_style_ui_") as td:
 try:
  os.chdir(td)
  cfg=AppConfig();cfg.spectator_commentary_style="b_grade"
  dlg=SettingsDialog(None,cfg,None,None,cfg_path=os.path.join(td,"config.json"))
  combo=dlg.cmb_spectator_commentary_style
  assert combo.currentData()=="b_grade"
  assert combo.count()==2
  assert combo.itemData(0)=="sports"
  assert dlg.cmb_spectator_bgrade_density.currentData()=="full"
  assert dlg.cmb_spectator_bgrade_swearing.currentData()=="strong"
  recorded=[]
  dlg._start_spectator_commentary_script=lambda name,steps:recorded.append((name,steps))
  dlg._test_spectator_commentary_duo_suite()
  assert any("씨발" in step["text"]+step.get("followup_text", "") for step in recorded[-1][1])
  combo.setCurrentIndex(0)
  dlg._test_spectator_commentary_duo_suite()
  assert not any("씨발" in step["text"]+step.get("followup_text", "") for step in recorded[-1][1])
  combo.setCurrentIndex(1)
  dlg.cmb_spectator_bgrade_swearing.setCurrentIndex(0)
  dlg._test_spectator_commentary_duo_suite()
  assert not any("씨발" in step["text"]+step.get("followup_text", "") for step in recorded[-1][1])
  dlg._apply_timer.stop()
  dlg.deleteLater()
 finally:
  os.chdir(previous)
print("STYLE_UI_OK")
'''
        result = subprocess.run([sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parents[1]),
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"},
            capture_output=True, text=True, encoding="utf-8", timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STYLE_UI_OK", result.stdout)


class EntertainmentWatcherTests(unittest.TestCase):
    def watcher(self, style="sports"):
        return SpectatorLogWatcher(SimpleNamespace(
            spectator_commentary_enabled=True, spectator_commentary_mode="standard",
            spectator_commentary_style=style, spectator_commentary_cooldown_sec=6,
        ))

    def test_only_winning_candidate_is_decorated_and_modes_switch_live(self):
        w = self.watcher()
        candidate = CommentaryCandidate("통, 카운터입니다!", "caster", "counter", 83, attacker_side="blue")
        w._commentary_director = Mock()
        w._commentary_director.observe_events.return_value = None
        w._commentary_director.choose_live.side_effect = lambda choices, **_kw: CommentaryDecision(choices[0] if choices else None, "test")
        event = {"attacker_side": "blue", "receiver_side": "red", "damage": 30,
                 "_central_event": {"counter": True, "counter_reason": "whiff"}}
        kwargs = dict(round_no=1, new_events=[event], down_plan=None,
                      event_commentary="", event_role="caster", counter_commentary=candidate.text, combo_commentary="")
        self.assertEqual(w._direct_live_commentary(**kwargs).text, candidate.text)
        w.cfg.spectator_commentary_style = "b_grade"
        result = w._direct_live_commentary(**kwargs)
        self.assertIn("헛친", result.text)
        self.assertEqual(len(result.presentation["turns"]), 2)
        self.assertEqual(result.category, "counter")
        self.assertFalse(result.text.startswith(candidate.text))
        self.assertTrue(result.key.startswith("bgrade:whiff:"))
        w.cfg.spectator_commentary_style = "sports"
        self.assertEqual(w._direct_live_commentary(**kwargs).text, candidate.text)

    def test_rejected_candidate_does_not_spend_joke(self):
        w = self.watcher("b_grade")
        w._commentary_director = Mock()
        w._commentary_director.observe_events.return_value = None
        w._commentary_director.choose_live.return_value = CommentaryDecision(None, "suppressed")
        self.assertIsNone(w._direct_live_commentary(round_no=1, new_events=[], down_plan=None,
            event_commentary="", event_role="caster", counter_commentary="", combo_commentary=""))
        self.assertEqual(w._bgrade_commentary._recent, w._bgrade_commentary._recent.__class__(maxlen=64))

    def test_idle_duo_is_context_bound_and_never_attaches_to_hit(self):
        w = self.watcher("b_grade")
        w._last_damage_seen_at = 80
        with patch("spectator_log_watcher.time.time", return_value=100):
            text, role = w._build_idle_fight_commentary("", 100, 1)
        self.assertEqual(role, "caster")
        hit = {"commentary_tts_text": text, "commentary_tts_role": role, "latest_hit": {}}
        w._attach_witty_duo_followup(hit, state="fight", round_no=1)
        self.assertNotIn("commentary_tts_followup_text", hit)
        idle = {"commentary_tts_text": text, "commentary_tts_role": role}
        w._attach_witty_duo_followup(idle, state="fight", round_no=1)
        self.assertTrue(idle["commentary_tts_followup_text"])
        self.assertEqual(idle["commentary_tts_story"]["scene"], "idle")
        self.assertEqual(idle["commentary_tts_followup_role"], "analyst")
        self.assertEqual(idle["commentary_tts_followup_retries"], 1)

    def test_down_call_keeps_count_and_adds_analyst_followup_only_in_bgrade(self):
        for style in ("sports", "b_grade"):
            w = self.watcher(style)
            w._live_commentary_name = lambda side: "통"
            plan = w._build_knockdown_commentary_plan(
                [{"kind": "knockdown", "side": "red", "round_down_count": 2}], [], 1)
            self.assertEqual(plan["count"], 2)
            self.assertIn("통", plan["text"])
            self.assertEqual("씨발" in plan["followups"][0]["text"], style == "b_grade")

    def test_report_style_preserves_factual_text(self):
        w = self.watcher("sports")
        facts = "통 10점, 현선호 9점입니다."
        self.assertEqual(w._style_report_commentary(facts, "round"), facts)
        w.cfg.spectator_commentary_style = "b_grade"
        self.assertTrue(w._style_report_commentary(facts, "round").startswith(facts))

    def test_bgrade_live_does_not_depend_on_sports_phrase_pool(self):
        w = self.watcher("b_grade")
        w._live_line = lambda *args, **kwargs: ""
        event = {"attacker_side": "blue", "receiver_side": "red", "time": 90., "damage": 35,
                 "punch": "Jab", "_central_event": {"counter": True, "counter_reason": "whiff"}}
        selected = w._direct_live_commentary(round_no=1, new_events=[event], down_plan=None,
            event_commentary="", event_role="analyst", counter_commentary="", combo_commentary="")
        self.assertIsNotNone(selected)
        self.assertIn("헛친", selected.text)
        # B-grade does not mean every bout must open with the same swear word.
        self.assertEqual(len(selected.presentation["turns"]), 2)
        self.assertNotEqual(selected.presentation["story"]["content"][1]["intent"], "call")
        self.assertEqual(selected.attacker_side, "blue")

    def test_bgrade_regular_hit_has_own_wording_and_quiet_still_suppresses_it(self):
        event = {"attacker_side": "blue", "receiver_side": "red", "time": 90., "damage": 30,
                 "punch": "Jab", "_central_event": {"counter": False, "tags": ["hit"]}}
        kwargs = dict(round_no=1, new_events=[event], down_plan=None,
            event_commentary="원래 스포츠 문장", event_role="analyst", counter_commentary="", combo_commentary="")
        active = self.watcher("b_grade")._direct_live_commentary(**kwargs)
        self.assertIsNotNone(active)
        self.assertNotIn("원래 스포츠 문장", active.text)
        quiet = self.watcher("b_grade")
        quiet.cfg.spectator_commentary_mode = "quiet"
        self.assertIsNone(quiet._direct_live_commentary(**kwargs))

    def test_bgrade_does_not_merge_different_fighters_counter_and_combo(self):
        w = self.watcher("b_grade")
        w._live_commentary_name = lambda side: "통" if side == "blue" else "현선호"
        events = [
            {"attacker_side": "blue", "receiver_side": "red", "damage": 30, "time": 90,
             "punch": "Jab", "_central_event": {"counter": True}},
            {"attacker_side": "red", "receiver_side": "blue", "damage": 30, "time": 89.8,
             "punch": "Cross", "_central_event": {"combo_hits": 4}},
        ]
        selected = w._direct_live_commentary(round_no=1, new_events=events, down_plan=None,
            event_commentary="", event_role="analyst", counter_commentary="", combo_commentary="")
        self.assertIn("통", selected.text)
        self.assertNotIn("4연타", selected.text)
        self.assertEqual(selected.category, "counter")

    def test_bgrade_urgent_effect_is_not_lost_without_a_new_damage_row(self):
        w = self.watcher("b_grade")
        w._live_commentary_name = lambda side: "통" if side == "blue" else "현선호"
        selected = w._direct_live_commentary(round_no=1, new_events=[], down_plan=None,
            event_commentary="원래 TKO 콜", event_role="caster", counter_commentary="", combo_commentary="",
            effect_events=[{"kind": "tko", "side": "red"}])
        self.assertEqual(selected.category, "tko")
        self.assertIn("현선호", selected.text)
        self.assertIn("TKO", selected.text)
        self.assertNotIn("원래", selected.text)

    def test_bgrade_down_call_names_receiver_and_preserves_count(self):
        w = self.watcher("b_grade")
        w._live_commentary_name = lambda side: "통" if side == "blue" else "현선호"
        selected = w._direct_live_commentary(round_no=1, new_events=[],
            down_plan={"side": "red", "count": 2}, event_commentary="", event_role="caster",
            counter_commentary="", combo_commentary="")
        self.assertIn("현선호", selected.text)
        self.assertIn("두 번째 다운", selected.text)

    def test_bgrade_report_is_independent_script_using_displayed_values(self):
        w = self.watcher("b_grade")
        report = {"round": 2, "winner": "red",
            "blue": {"name": "통", "landed": 31, "damage": 980, "maxComboHits": 4},
            "red": {"name": "현선호", "landed": 42, "damage": 1100, "counterHits": 8}}
        original = copy.deepcopy(report)
        text = w._style_report_commentary("원래 스포츠 분석 문단", "round", report)
        self.assertNotIn("원래 스포츠 분석 문단", text)
        self.assertIn("31번", text)
        self.assertIn("42번", text)
        self.assertIn("4연타", text)
        self.assertEqual(report, original)
        final = w._style_report_commentary("원래 스포츠 분석 문단", "final", report)
        self.assertIn("현선호, 승리", final)
        self.assertNotIn("다음 라운드", final)

    def test_live_payload_contains_both_turns_without_losing_the_joke(self):
        w = self.watcher("b_grade")
        for tag in ("whiff", "graze", "counter", "counter_combo", "combo", "heavy", "weak", "stun", "knockdown", "tko"):
            call = w._bgrade_commentary.make_call(tag, name="통", receiver="현선호", hits=4, count=2)
            payload = {}
            w._emit_bgrade_dialogue(payload, call)
            self.assertEqual(payload["commentary_tts_role"], call.role)
            self.assertTrue(payload["commentary_tts_live_dialogue"])
            reply = payload["commentary_tts_continuations"][0]
            self.assertEqual(reply["role"], "analyst" if call.role == "caster" else "caster")
            self.assertEqual(payload["commentary_tts_text"] + " " + reply["text"], call.text)
            self.assertTrue(reply["text"])
            self.assertIn("commentary_tts_story", payload)

    def test_bgrade_idle_does_not_lose_second_sentence_to_sports_compaction(self):
        text = "아니, 적중 소식이 없어요! 저희만 떠들고 있잖아요!"
        self.assertEqual(SpectatorLogWatcher._compact_live_commentary(text), "아니, 적중 소식이 없어요!")
        self.assertEqual(SpectatorLogWatcher._compact_live_commentary(text, single_sentence=False), text)

    def test_rotation_does_not_get_stuck_on_exact_text_cooldown(self):
        for tag in ("counter", "whiff", "combo", "heavy", "weak", "hit"):
            bank, director = BGradeCommentary(), CommentaryDirector()
            texts = []
            for index in range(24):
                call = bank.make_call(tag, name="통", hits=3, key=str(index))
                decision = director.choose_live([call], cooldown_sec=6, now=100 + 6 * index)
                self.assertIsNotNone(decision.candidate, (tag, index, decision.suppressed))
                bank.accept_call(decision.candidate)
                texts.append(call.text)
            self.assertGreaterEqual(len(set(texts)), 8)

    def test_all_knockdown_variants_keep_count_in_caster_turn(self):
        bank = BGradeCommentary()
        for index in range(6):
            call = bank.make_call("knockdown", receiver="현선호", count=2, key=str(index))
            setup, _ = bank.dialogue_for(call)
            self.assertIn("현선호", setup)
            self.assertIn("두 번째", setup)
            bank.accept_call(call)


if __name__ == "__main__":
    unittest.main()
