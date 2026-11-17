import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import audio_routing as routing
from config_model import AppConfig


class AudioRoutingTests(unittest.TestCase):
    def tearDown(self):
        routing.configure('')

    def test_explicit_vb_never_falls_back_to_default(self):
        vb=SimpleNamespace(description=lambda:'CABLE Input')
        with patch.object(routing.QMediaDevices,'audioOutputs',return_value=[vb]), \
             patch.object(routing.QMediaDevices,'defaultAudioOutput',side_effect=AssertionError('fallback')):
            self.assertIs(routing.resolve_device('cable input'),vb)
            with self.assertRaises(RuntimeError):routing.resolve_device('missing')

    def test_route_only_never_stops_replays_or_detaches_player(self):
        output=SimpleNamespace(device=lambda:'old',setDevice=Mock())
        player=SimpleNamespace(audioOutput=lambda:output,stop=Mock(),play=Mock(),setSource=Mock(),setAudioOutput=Mock())
        routing.configure('VB')
        with patch.object(routing,'resolve_device',return_value='VB'):
            routing.prepare(player)
        output.setDevice.assert_called_once_with('VB')
        for method in (player.stop,player.play,player.setSource,player.setAudioOutput):method.assert_not_called()

    def test_missing_device_does_not_reset_anything(self):
        player=Mock()
        with patch.object(routing,'resolve_device',side_effect=RuntimeError('missing')):
            with self.assertRaises(RuntimeError):routing.prepare(player)
        player.audioOutput().setDevice.assert_not_called()
        player.stop.assert_not_called()

    def test_no_message_hook_or_recovery_callbacks_in_route_module(self):
        tree=ast.parse(Path(routing.__file__).read_text(encoding='utf-8'))
        names={node.id for node in ast.walk(tree) if isinstance(node,ast.Name)}
        self.assertFalse({'qInstallMessageHandler','QTimer','AudioGuard'} & names)
        self.assertFalse(hasattr(routing,'AudioGuard'))

    def test_config_roundtrip_and_selected_output_disables_winsound(self):
        import timerauto
        with tempfile.TemporaryDirectory() as td:
            cfg=AppConfig();cfg.app_audio_output_device='CABLE Input'
            path=str(Path(td,'config.json'));cfg.to_json(path)
            self.assertEqual(AppConfig.from_json(path).app_audio_output_device,'CABLE Input')
        routing.configure('CABLE Input')
        with patch.object(timerauto.winsound,'PlaySound') as play:
            self.assertFalse(timerauto._play_win_effect_sfx('unused.wav'))
            play.assert_not_called()
