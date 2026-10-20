import unittest
from unittest.mock import patch, Mock

from commentary_calls import SHORT_CALLS, SpokenFocus, short_call
from commentary_entertainment import BGradeCommentary
from tests import test_commentary_tts_queue as queue_tests
from timerauto import QMediaPlayer


class ShortCallTests(unittest.TestCase):
    def setUp(self):
        self.bank = BGradeCommentary()
        self.focus = self.bank.story.focus = SpokenFocus()

    def call(self, *, side="blue", now=100, tag="counter", name="통", **kwargs):
        self.focus.observe(self.bank.story.scope, self.bank.story.round, side)
        return self.bank.make_call(tag, side=side, name=name, now=now, **kwargs)

    def start(self, call, now=100):
        self.focus.started(call.presentation["focus"], now=now)
        self.bank.accept_call(call)

    def test_first_call_names_player_following_actual_speech_may_omit(self):
        first = self.call()
        self.assertTrue(first.presentation["focus"]["named"])
        self.assertIn("통,", first.presentation["turns"][0]["text"])
        self.start(first)
        second = self.call(now=106)
        self.assertFalse(second.presentation["focus"]["named"])
        self.assertNotIn("통", second.presentation["turns"][0]["text"])

    def test_selection_queued_and_failed_audio_do_not_establish_a_subject(self):
        first = self.call()
        self.bank.accept_call(first)
        self.assertTrue(self.call(now=106).presentation["focus"]["named"])

    def test_switching_spoken_attacker_restores_name_but_unannounced_hits_do_not_spam_names(self):
        first = self.call()
        self.start(first)
        old_bare = self.call(now=102)
        self.focus.observe(self.bank.story.scope, 1, "red")
        self.assertTrue(self.focus.valid(old_bare.presentation["focus"], now=103))
        opponent = self.call(side="red", name="현선호", now=103)
        self.assertTrue(opponent.presentation["focus"]["named"])
        self.start(opponent, now=103)
        self.assertFalse(self.focus.valid(old_bare.presentation["focus"], now=103))
        blue_again = self.call(now=104)
        self.assertTrue(blue_again.presentation["focus"]["named"])
        self.start(blue_again, now=104)
        self.assertTrue(self.call(side="red", name="현선호", now=106).presentation["focus"]["named"])

    def test_periodic_name_refresh_and_long_silence(self):
        first = self.call()
        self.start(first)
        for stamp in (106, 112, 118):
            out = self.call(now=stamp)
            self.assertFalse(out.presentation["focus"]["named"])
            self.start(out, now=stamp)
        self.assertTrue(self.call(now=119).presentation["focus"]["named"])
        self.assertTrue(self.call(now=130).presentation["focus"]["named"])

    def test_round_match_rename_and_other_speech_restore_explicit_name(self):
        first = self.call()
        self.start(first)
        self.assertTrue(self.call(now=102, name="새 닉네임").presentation["focus"]["named"])
        self.bank.story.round = 2
        self.assertTrue(self.call(now=103).presentation["focus"]["named"])
        self.bank.reset_match()
        self.assertTrue(self.call(now=104).presentation["focus"]["named"])
        self.focus.invalidate()
        self.assertTrue(self.call(now=105).presentation["focus"]["named"])

    def test_stoppages_and_stuns_always_identify_receiver_not_attacker(self):
        first = self.call()
        self.start(first)
        for tag in ("knockdown", "tko", "stun"):
            out = self.call(now=106, tag=tag, receiver="현선호", receiver_side="red", count=2)
            lead = out.presentation["turns"][0]["text"]
            self.assertIn("현선호", lead)
            self.assertNotIn("통,", lead)
            self.assertTrue(out.presentation["focus"]["named"])
        self.assertIn("두 번째", self.call(tag="knockdown", count=2).text)

    def test_nickname_is_not_removed_using_substring_replacement(self):
        name = "카운터! 콤보"
        first = self.call(name=name)
        self.assertTrue(first.presentation["turns"][0]["text"].startswith(name + ", "))
        self.start(first)
        out = self.call(name=name, now=106)
        self.assertIn(out.presentation["turns"][0]["text"], SHORT_CALLS["counter"])

    def test_each_event_has_eight_short_variants_and_exact_combo_count(self):
        for tag in SHORT_CALLS:
            rows = [short_call(tag, i, name="통", named=False, hits=7, target="왼쪽 눈", count=2) for i in range(8)]
            self.assertEqual(len(set(rows)), 8, tag)
            self.assertLess(max(map(len, rows)), 30, tag)
            if tag in ("combo", "counter_combo"):
                self.assertTrue(all("7" in line for line in rows))

    def test_context_does_not_invent_a_reversal_without_evidence(self):
        plain = short_call("counter", 0, name="통", named=False)
        repeated = short_call("counter", 0, name="통", named=False, context={"repeat_counter": True})
        reversal = short_call("counter", 0, name="통", context={"reversal": True})
        self.assertNotIn("또", plain)
        self.assertIn("또", repeated)
        self.assertIn("반대", reversal)
        self.assertIn("통", reversal)

    def test_normal_hits_are_single_turn_and_full_mode_is_not_mandatory_duo(self):
        sizes = []
        for index in range(16):
            out = self.call(now=100 + index * 6)
            sizes.append(len(out.presentation["turns"]))
            self.bank.accept_call(out)
        self.assertIn(1, sizes)
        self.assertIn(2, sizes)
        self.assertLess(sum(size == 2 for size in sizes), 9)
        for index in range(10):
            out = self.call(tag="hit", now=300 + index)
            self.assertEqual(len(out.presentation["turns"]), 1)

    def test_playback_rechecks_ellipsis_after_opponent_action(self):
        first = self.call()
        self.start(first)
        out = self.call(now=102)
        opponent = self.call(side="red", name="현선호", now=102)
        self.start(opponent, now=102)
        app = queue_tests.CommentaryTtsQueueTests()._app()
        app._commentary_tts_generations["caster"] = 1
        app._commentary_tts_dialogues["caster"] = {"focus": out.presentation["focus"]}
        app._clear_commentary_tts_busy = Mock()
        with patch("timerauto.SPOKEN_FOCUS", self.focus), patch("timerauto.time.monotonic", return_value=103), patch("timerauto.os.path.isfile") as exists:
            app._play_commentary_tts_file("caster", "cached.mp3", 1)
        exists.assert_not_called()
        app._clear_commentary_tts_busy.assert_called_once_with("caster", 1)

    def test_only_playing_state_registers_focus_not_enqueue_or_file_generation(self):
        first = self.call()
        app = queue_tests.CommentaryTtsQueueTests()._app()
        app._commentary_tts_dialogues["caster"] = {"focus": first.presentation["focus"], "play_started": False}
        with patch("timerauto.SPOKEN_FOCUS", self.focus), patch("timerauto.time.monotonic", return_value=100):
            self.assertTrue(self.call(now=100).presentation["focus"]["named"])
            app._on_commentary_playback_state("caster", QMediaPlayer.PlaybackState.PlayingState)
            self.assertFalse(self.call(now=101).presentation["focus"]["named"])

    def test_interrupting_same_fighters_reply_does_not_invalidate_new_short_call(self):
        first = self.call()
        self.start(first)
        app = queue_tests.CommentaryTtsQueueTests()._app()
        app._commentary_players = {"analyst": Mock()}
        app._commentary_tts_cache_dir = ""
        short = self.call(now=102).presentation["focus"]
        with patch("timerauto.SPOKEN_FOCUS", self.focus), patch("timerauto.time.monotonic", return_value=102):
            app._stop_commentary_tts_role("analyst", "new_action_over_banter")
            self.assertTrue(self.focus.valid(short, now=102))
            app._stop_commentary_tts_role("analyst", "round_start")
            self.assertFalse(self.focus.valid(short, now=102))

    def test_idle_or_report_audio_resets_subject(self):
        first = self.call()
        self.start(first)
        app = queue_tests.CommentaryTtsQueueTests()._app()
        with patch("timerauto.SPOKEN_FOCUS", self.focus), patch("timerauto.time.monotonic", return_value=102):
            app._on_commentary_playback_state("analyst", QMediaPlayer.PlaybackState.PlayingState)
        self.assertTrue(self.call(now=103).presentation["focus"]["named"])

