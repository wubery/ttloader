"""Тесты сборки конвейера уникализации — без запуска ffmpeg.

Проверяется то, что можно проверить строкой: розыгрыш параметров, порядок
фильтров, склейка сегментов, ветка «сегмент без звука».
"""
from __future__ import annotations

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import uniqueizer as u  # noqa: E402

FULL = {
    "trim": {"on": True, "percent": [10, 10], "from": "both"},
    "speed": {"on": True, "factor": [1.05, 1.05]},
    "crop": {"on": True, "px": [4, 4]},
    "rotate": {"on": True, "deg": [2, 2], "flip180": False},
    "color": {"on": True, "presets": ["warm"]},
    "noise": {"on": True, "strength": [2, 2]},
    "canvas": {"on": True, "w": 1080, "h": 1920, "border_px": [12, 12], "bg": "color", "color": "#101010"},
    "overlay": {"on": True, "opacity": [0.1, 0.1]},
    "metadata": {"on": True},
}


def plan_of(params, duration=20.0, seed=1, **kw):
    return u.roll(params, duration=duration, rnd=random.Random(seed), **kw)


# ---------------------------------------------------------------- розыгрыш


def test_ручной_режим_равные_границы_дают_точные_значения():
    p = plan_of(FULL).main
    assert p.speed == pytest.approx(1.05)
    assert p.crop_px == 4
    assert abs(p.rotate_deg) == pytest.approx(2.0)
    assert p.color == "warm"
    assert p.noise == 2
    assert p.border_px == 12
    # обрезка 10% от 20 с, поровну с двух сторон
    assert p.trim_start == pytest.approx(1.0)
    assert p.trim_duration == pytest.approx(18.0)


def test_разные_seed_дают_разные_параметры():
    wide = {"speed": {"on": True, "factor": [0.9, 1.1]},
            "crop": {"on": True, "px": [1, 10]},
            "rotate": {"on": True, "deg": [1, 3]}}
    a, b = plan_of(wide, seed=1).main, plan_of(wide, seed=2).main
    assert (a.speed, a.crop_px, a.rotate_deg) != (b.speed, b.crop_px, b.rotate_deg)


def test_переворот_180_не_появляется_сам():
    """В авторежиме допустим только микронаклон — 180° включается вручную."""
    for seed in range(50):
        assert plan_of({"rotate": {"on": True, "deg": [1, 3], "flip180": False}}, seed=seed).main.flip180 is False
    assert plan_of({"rotate": {"on": True, "flip180": True}}).main.flip180 is True


def test_выключенные_блоки_ничего_не_добавляют():
    off = {k: {"on": False} for k in ("trim", "speed", "crop", "rotate", "color", "noise", "canvas", "overlay")}
    p = plan_of(off).main
    assert (p.speed, p.crop_px, p.rotate_deg, p.color, p.noise, p.border_px) == (1.0, 0, 0.0, None, 0, 0)


def test_обрезка_не_съедает_короткий_ролик_целиком():
    p = plan_of({"trim": {"on": True, "percent": [99, 99]}}, duration=3.0).main
    assert p.trim_duration >= 0.5


def test_скорость_ограничена_пределами_atempo():
    p = plan_of({"speed": {"on": True, "factor": [5, 5]}}).main
    assert p.speed == 2.0


# ---------------------------------------------------------------- фильтры


def test_цепочка_сегмента_содержит_все_шаги_по_порядку():
    plan = plan_of(FULL)
    chain = ";".join(u.segment_chain(plan.main, plan, "[0:v]", "[out]", 720, 1280))
    for i, part in enumerate(["setpts=PTS/", "crop=iw-8", "scale=iw*", "rotate=", "eq=", "noise="]):
        assert part in chain, part
    assert chain.index("setpts") < chain.index("crop=iw-8") < chain.index("rotate=")
    assert "pad=1080:1920" in chain and "0x101010" in chain
    assert chain.rstrip().endswith("[out]")


def test_размытый_фон_даёт_split_и_gblur():
    params = dict(FULL, canvas={**FULL["canvas"], "bg": "blur"})
    plan = plan_of(params)
    chain = ";".join(u.segment_chain(plan.main, plan, "[0:v]", "[out]", 720, 1280))
    assert "split=2" in chain and "gblur" in chain and "overlay=(W-w)/2:(H-h)/2" in chain


def test_поворот_компенсируется_масштабом():
    """Кадр увеличивается перед поворотом и обрезается после — иначе чёрные углы."""
    assert u.rotate_scale_factor(0, 720, 1280) == 1.0
    k = u.rotate_scale_factor(3, 720, 1280)
    assert 1.0 < k < 1.2
    assert u.rotate_scale_factor(3, 720, 1280) > u.rotate_scale_factor(1, 720, 1280)


def test_180_градусов_это_hflip_vflip_без_масштабирования():
    plan = plan_of({"rotate": {"on": True, "flip180": True}, "canvas": {"on": False}})
    chain = ";".join(u.segment_chain(plan.main, plan, "[0:v]", "[out]", 720, 1280))
    assert "hflip,vflip" in chain and "rotate=" not in chain


def test_аудио_меняет_темп_вместе_с_видео():
    plan = plan_of(FULL)
    assert "atempo=1.05000" in u.audio_chain(plan.main, "[0:a]", "[a0]")
    slow = u.SegmentPlan(speed=1.0)
    assert "atempo" not in u.audio_chain(slow, "[0:a]", "[a0]")


# ---------------------------------------------------------------- команда


def _seg(path="/v.mp4", audio=True, plan=None, dur=20.0):
    return u.SegmentInput(path=path, width=720, height=1280, duration=dur,
                          has_audio=audio, plan=plan or u.SegmentPlan())


def build(main, plan, **kw):
    return u.build_command(
        ffmpeg_bin="ffmpeg", main=main, plan=plan, output_path="/out.mp4",
        encode_args=["-c:v", "libx264"], metadata_args=["-map_metadata", "-1"], **kw,
    )


def test_без_хука_склейки_нет():
    plan = plan_of(FULL)
    cmd = build(_seg(plan=plan.main), plan)
    graph = cmd.args[cmd.args.index("-filter_complex") + 1]
    assert "concat=" not in graph


def test_хук_идёт_первым_и_склеивается():
    plan = plan_of(FULL, with_hook=True, hook_duration=5.0)
    cmd = build(_seg(plan=plan.main), plan, hook=_seg(path="/hook.mp4", plan=plan.hook, dur=5.0))
    graph = cmd.args[cmd.args.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=1[cv][ca]" in graph
    # первым входом идёт именно хук
    inputs = [cmd.args[i + 1] for i, a in enumerate(cmd.args) if a == "-i"]
    assert inputs[0] == "/hook.mp4"


def test_сегмент_без_звука_получает_тишину():
    plan = plan_of(FULL, with_hook=True, hook_duration=5.0)
    cmd = build(_seg(plan=plan.main), plan,
                hook=_seg(path="/hook.mp4", audio=False, plan=plan.hook, dur=5.0))
    assert "anullsrc=r=44100:cl=stereo" in cmd.args
    graph = cmd.args[cmd.args.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=1" in graph


def test_обрезка_уходит_во_входные_ключи():
    plan = plan_of(FULL)
    cmd = build(_seg(plan=plan.main), plan)
    assert "-ss" in cmd.args and "-t" in cmd.args
    assert cmd.args.index("-ss") < cmd.args.index("-i")   # до своего входа


def test_png_оверлей_накладывается_на_весь_кадр():
    plan = plan_of(FULL)
    cmd = build(_seg(plan=plan.main), plan, overlay_png="/ov.png")
    graph = cmd.args[cmd.args.index("-filter_complex") + 1]
    assert "scale=1080:1920,format=rgba,colorchannelmixer=aa=0.1000" in graph
    assert "overlay=0:0:format=auto[ov_out]" in graph


def test_метаданные_стираются_когда_включено():
    plan = plan_of(FULL)
    assert "-map_metadata" in build(_seg(plan=plan.main), plan).args
    plan.metadata = False
    assert "-map_metadata" not in build(_seg(plan=plan.main), plan).args


def test_слои_редактора_ложатся_последними():
    plan = plan_of(FULL)

    def fake_layers(overlays, *, src_label, next_input, width, height, duration):
        assert (width, height) == (1080, 1920)     # слои считаются от холста, не от исходника
        return type("B", (), {"chains": [f"{src_label}drawtext=x[vl]"], "inputs": [],
                              "out_label": "[vl]", "tmp_texts": []})()

    cmd = build(_seg(plan=plan.main), plan,
                editor_overlays=[{"type": "text", "text": "hi"}], layers_builder=fake_layers)
    graph = cmd.args[cmd.args.index("-filter_complex") + 1]
    assert graph.endswith("drawtext=x[vl]")
    assert cmd.args[cmd.args.index("-map")] == "-map"
    assert "[vl]" in cmd.args
