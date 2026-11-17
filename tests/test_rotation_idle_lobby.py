import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from config_model import AppConfig
from spectator_log_watcher import SpectatorLogWatcher
from camera_director import AutoCameraDirector
from camera_direction_policy import DirectorFeed


class RotationLobbyTests(unittest.TestCase):
    def test_rotation_choice_survives_settings_save(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=AppConfig();cfg.camera_director_profile='rotation'
            path=str(Path(folder)/'config.json');cfg.to_json(path)
            self.assertEqual(AppConfig.from_json(path).camera_director_profile,'rotation')

    def test_lobby_feed_blocks_rotation_even_if_game_keeps_old_fight_file(self):
        feed=DirectorFeed()
        feed.update({'spectator_round_state':'lobby'},now=10)
        self.assertFalse(feed.snapshot(10)[0])
        feed.update({'spectator_round_state':'fight'},now=11)
        self.assertTrue(feed.snapshot(11)[0])

    def test_rotation_selection_and_normal_camera_interval(self):
        d = AutoCameraDirector(lambda s:None, lambda:(True, 'fixture'))
        d.rotation=True;d.rotation_index=0;d.rotation_sequence=0;d.state='idle'
        first=d._opportunity(0,True,True,None)
        self.assertEqual(first['side'],'blue')
        self.assertIsNone(d._opportunity(1,False,True,None))
        d._rotation_returned(10)
        self.assertEqual(d.next_cut,10)
        self.assertEqual(d._opportunity(10,True,True,None)['side'],'red')
        d._rotation_returned(20)
        self.assertEqual(d.next_cut,30)
        self.assertNotEqual(first['flow'],d._opportunity(30,True,True,None)['flow'])

    def test_new_single_fighter_lobby_overrides_stale_fight_not_live_clock(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);match=root/'match';match.mkdir()
            for name,text in [('round_state.txt','RoundFight'),('round_time.txt','76.5'),
                              ('round_number.txt','1'),('round_total.txt','3'),('damage_events.txt','')]:
                (match/name).write_text(text)
                os.utime(match/name,(time.time()-120,time.time()-120))
            (root/'lobby.txt').write_text('slot_0: type=DesktopSpectator occupied=True name=host ready=False\nslot_1: type=PlayerBlue occupied=True name=ONE ready=False\nready_to_start: False\n')
            cfg=AppConfig();cfg.spectator_match_archive_dir=str(root/'archive')
            cfg.spectator_lobby_auto_start_enabled=True
            w=SpectatorLogWatcher(cfg)
            result=w._read_update(str(root))
            self.assertEqual(result['spectator_round_state'],'lobby')
            self.assertTrue(result['spectator_lobby_confirmed'])
            self.assertFalse(result['spectator_match_active'])
            (root/'lobby.txt').write_text('slot_0: type=DesktopSpectator occupied=True name=host ready=False\nslot_1: type=PlayerBlue occupied=True name=ONE ready=True\nslot_2: type=PlayerRed occupied=True name=TWO ready=True\nready_to_start: True\n')
            result=w._read_update(str(root))
            self.assertEqual(result['spectator_round_state'],'lobby')
            self.assertIn('spectator_lobby_auto_start',result)
            self.assertNotIn('spectator_lobby_auto_start',w._read_update(str(root)))
            self.assertEqual(w.lobby_auto_start_recovery_context(str(root),w._read_lobby_info(str(root))),'ready')
            (match/'round_time.txt').write_text('75.0')
            result=w._read_update(str(root))
            self.assertEqual(result['spectator_round_state'],'fight')
            self.assertNotIn('spectator_lobby_confirmed',result)
            self.assertIsNone(w.lobby_auto_start_recovery_context(str(root),w._read_lobby_info(str(root))))

    def test_restart_already_ready_lobby_requires_stability_and_newer_evidence(self):
        w=SpectatorLogWatcher(AppConfig())
        old=int((time.time()-120)*1e9)
        sig=((old,5),(old,5),(old,5))
        lobby={'ready_to_start':True,'slots':[
            {'slot':1,'type':'PlayerBlue','name':'ONE','occupied':True,'ready':True},
            {'slot':2,'type':'PlayerRed','name':'TWO','occupied':True,'ready':True}]}
        with patch('spectator_log_watcher.time.monotonic',return_value=10):
            self.assertFalse(w._confirmed_stale_match_lobby('fight',lobby,(time.time_ns(),10),sig))
        with patch('spectator_log_watcher.time.monotonic',return_value=11.1):
            self.assertTrue(w._confirmed_stale_match_lobby('fight',lobby,(time.time_ns(),10),sig))
        changed=(sig[0],(time.time_ns(),5),sig[2])
        self.assertFalse(w._confirmed_stale_match_lobby('fight',lobby,(old,10),changed))
