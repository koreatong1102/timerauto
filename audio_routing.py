"""Explicit output selection only; no Qt logging hooks or automatic resets.

Stopping/detaching a Qt FFmpeg player from an audio-error callback can wait
for the same audio worker that is reporting the failure. Do not do it here.
"""
from PyQt6.QtMultimedia import QMediaDevices

_requested = ""


def configure(name):
    global _requested
    _requested = str(name or "").strip()


def requested_device():
    return _requested


def resolve_device(name):
    if not name:
        return QMediaDevices.defaultAudioOutput()
    for device in QMediaDevices.audioOutputs():
        if device.description().casefold() == name.casefold():
            return device
    raise RuntimeError(f"선택한 오디오 장치가 없습니다: {name}. 다른 장치로 전환하지 않습니다.")


def prepare(player):
    output = player.audioOutput()
    if output is None:
        raise RuntimeError('오디오 출력 객체가 없습니다.')
    device = resolve_device(_requested)
    if output.device() != device:
        output.setDevice(device)
