"""Качество кодирования: шум не навязывается, параметры берутся из настроек.

Регрессия: в старом пути уникализации шум (`noise=alls=N:allf=t`) применялся
всегда, а CRF доходил до 23 — вместе это заметно «шакалило» ролик.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.services.media import _encode_args, _uniq_vf


def test_no_noise_by_default():
    assert "noise=" not in _uniq_vf(1080, 1920)


def test_uniqueization_still_changes_every_pixel():
    """Без шума хеш всё равно меняется: микрокроп + ресайз + eq."""
    vf = _uniq_vf(1080, 1920)
    assert "crop=iw-2:ih-2:1:1" in vf
    assert "scale=1080:1920" in vf
    assert "eq=brightness=" in vf


def test_noise_can_be_returned_by_setting(monkeypatch):
    monkeypatch.setattr(settings, "uniq_force_noise", True)
    assert "noise=alls=" in _uniq_vf(1080, 1920)


def test_crf_range_comes_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "video_crf_min", 17)
    monkeypatch.setattr(settings, "video_crf_max", 17)
    args = _encode_args()
    assert args[args.index("-crf") + 1] == "17"


def test_crf_range_survives_swapped_bounds(monkeypatch):
    """Перепутанные местами границы не должны ронять рендер."""
    monkeypatch.setattr(settings, "video_crf_min", 22)
    monkeypatch.setattr(settings, "video_crf_max", 18)
    for _ in range(20):
        assert 18 <= int(_encode_args()[_encode_args().index("-crf") + 1]) <= 22


@pytest.mark.parametrize("_", range(10))
def test_default_crf_is_visually_clean(_):
    """По умолчанию не хуже 20: на 23 картинка сыпалась (см. жалобу на качество)."""
    args = _encode_args()
    assert int(args[args.index("-crf") + 1]) <= 20
    assert args[args.index("-preset") + 1] == settings.video_preset
    assert args[args.index("-b:a") + 1] == settings.audio_bitrate
