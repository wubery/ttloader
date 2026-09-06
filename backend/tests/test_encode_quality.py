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
    """По умолчанию не хуже 18: на 23 картинка сыпалась (см. жалобу на качество)."""
    args = _encode_args()
    assert int(args[args.index("-crf") + 1]) <= 18
    assert args[args.index("-preset") + 1] == settings.video_preset
    assert args[args.index("-b:a") + 1] == settings.audio_bitrate


# --- Качество конвейера: fps исходника и размер кадра -------------------------

import random as _random

from app.services.uniqueizer import _pick_fps, merge_params, roll, segment_chain


def _plan(params, *, source_fps=None, duration=30.0):
    return roll(params, duration=duration, rnd=_random.Random(1), source_fps=source_fps)


def test_gop_follows_fps():
    args = _encode_args(60)
    assert args[args.index("-g") + 1] == "120"          # ключевой кадр раз в 2 секунды
    assert args[args.index("-profile:v") + 1] == "high"
    assert _encode_args(30)[_encode_args(30).index("-g") + 1] == "60"


def test_gop_has_sane_floor_without_fps():
    assert int(_encode_args(None)[_encode_args(None).index("-g") + 1]) >= 24


def test_source_fps_is_kept():
    assert _pick_fps(0, 59.94) == 60                    # раньше здесь жёстко стояло 30
    assert _pick_fps(0, 24.0) == 24
    assert _pick_fps(0, 23.976) == 24


def test_fps_is_capped_and_floored():
    assert _pick_fps(0, 120.0) == 60                    # выше TikTok не принимает
    assert _pick_fps(0, 0) == 30                        # ffprobe промолчал
    assert _pick_fps(0, None) == 30


def test_profile_fps_wins_over_source():
    assert _pick_fps(30, 60.0) == 30


def test_plan_takes_fps_from_source():
    p = merge_params({"canvas": {"on": True, "fps": 0}})
    assert _plan(p, source_fps=59.94).fps == 60


def _graph(params, *, width, height, canvas_on):
    plan = _plan(merge_params(params))
    if not canvas_on:
        plan.out_w, plan.out_h = width, height
    return ";".join(segment_chain(plan.main, plan, "[0:v]", "[v0]", width, height))


def test_canvas_off_keeps_source_frame():
    """Выключенный холст больше не перегоняет горизонтальный ролик в 1080x1920."""
    g = _graph({"canvas": {"on": False}}, width=1920, height=1080, canvas_on=False)
    assert "scale=1920:1080" in g
    assert "1080:1920" not in g


def test_canvas_on_still_fits_into_canvas():
    """Регресс: с включённым холстом кадр по-прежнему вертикальный 1080x1920."""
    g = _graph({"canvas": {"on": True, "w": 1080, "h": 1920}},
               width=1920, height=1080, canvas_on=True)
    assert "1080" in g and "1920" in g


def test_fps_filter_uses_planned_value():
    p = merge_params({"canvas": {"on": False, "fps": 0}})
    plan = _plan(p, source_fps=59.94)
    plan.out_w, plan.out_h = 1080, 1920
    g = ";".join(segment_chain(plan.main, plan, "[0:v]", "[v0]", 1080, 1920))
    assert "fps=60" in g and "fps=30" not in g
