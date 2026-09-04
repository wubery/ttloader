"""Баннер задачи не должен теряться, когда у задачи есть свои слои.

Регрессия: у частей длинного видео в job.overlays лежит подпись «Часть N», а
runner выбирал «слои ИЛИ баннер» — и баннер молча пропадал на каждой части.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from app.config import settings
from app.models import BannerType
from app.services.media import build_layers_chain
from app.services.runner import _banner_layer


@pytest.fixture
def banner():
    settings.ensure_dirs()
    open(os.path.join(settings.banners_dir, "b.png"), "wb").close()
    return SimpleNamespace(filename="b.png", type=BannerType.image, x=0.05, y=0.05,
                           scale=0.25, opacity=1.0, motion="none", motion_speed=1.0)


def _job(**kw):
    return SimpleNamespace(**{"banner_x": None, "banner_y": None, "banner_scale": None, **kw})


PART_LABEL = {"type": "text", "text": "Часть 2/3", "x": 0.5, "y": 0.06,
              "align": "center", "font_size": 0.05, "color": "#ffffff", "opacity": 1.0}


def test_banner_layer_empty_without_banner():
    assert _banner_layer(_job(), None) == []


def test_part_job_keeps_both_banner_and_label(banner):
    """Именно то, что раньше ломалось: подпись части + баннер вместе."""
    layers = _banner_layer(_job(), banner) + [PART_LABEL]
    assert [l["type"] for l in layers] == ["banner", "text"]

    built = build_layers_chain(layers, src_label="[0:v]", next_input=1,
                               width=1080, height=1920, duration=60.0)
    graph = ";".join(built.chains)
    assert "overlay=" in graph                      # баннер вжигается
    assert "drawtext=" in graph                     # подпись части тоже
    assert built.inputs.count("-i") == 1            # файл баннера подан входом
    assert any(str(i).endswith("b.png") for i in built.inputs)


def test_banner_goes_under_editor_layers(banner):
    """Порядок: баннер ниже, слои редактора поверх — как в runner."""
    layers = _banner_layer(_job(), banner) + [PART_LABEL]
    built = build_layers_chain(layers, src_label="[0:v]", next_input=1,
                               width=1080, height=1920, duration=60.0)
    graph = ";".join(built.chains)
    assert graph.index("overlay=") < graph.index("drawtext=")


def test_job_overrides_win_over_banner_defaults(banner):
    layers = _banner_layer(_job(banner_x=0.5, banner_y=0.8, banner_scale=0.4), banner)
    assert (layers[0]["x"], layers[0]["y"], layers[0]["scale"]) == (0.5, 0.8, 0.4)
