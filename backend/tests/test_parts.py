"""Тесты нарезки на части и вставки рекламы — без запуска ffmpeg."""
from __future__ import annotations

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import uniqueizer as u  # noqa: E402

OFF = {"on": False}
PLAIN = {k: OFF for k in ("trim", "speed", "crop", "rotate", "color", "noise", "overlay", "hook")}
PLAIN["canvas"] = {"on": True, "w": 1080, "h": 1920, "border_px": [10, 10], "bg": "color"}
PLAIN["metadata"] = {"on": True}


def plan_of(params=None, duration=60.0, seed=1, **kw):
    return u.roll(params or PLAIN, duration=duration, rnd=random.Random(seed), **kw)


def seg(path="/v.mp4", audio=True, plan=None, dur=60.0, offset=0.0):
    return u.SegmentInput(path=path, width=720, height=1280, duration=dur,
                          has_audio=audio, plan=plan or u.SegmentPlan(trim_duration=dur),
                          offset=offset)


def build(**kw):
    return u.build_command(
        ffmpeg_bin="ffmpeg", output_path="/out.mp4",
        encode_args=["-c:v", "libx264"], metadata_args=["-map_metadata", "-1"], **kw,
    )


def graph_of(cmd):
    return cmd.args[cmd.args.index("-filter_complex") + 1]


def inputs_of(cmd):
    return [cmd.args[i + 1] for i, a in enumerate(cmd.args) if a == "-i"]


# ---------------------------------------------------------------- смещение части


def test_смещение_части_складывается_с_обрезкой():
    """-ss = начало части + обрезка уникализации, иначе вырежется не тот кусок."""
    p = u.SegmentPlan(trim_start=2.0, trim_duration=18.0)
    cmd = build(plan=plan_of(), segments=[seg(plan=p, offset=40.0)])
    ss = cmd.args[cmd.args.index("-ss") + 1]
    assert float(ss) == pytest.approx(42.0)
    assert cmd.args[cmd.args.index("-t") + 1] == "18.000"


def test_части_без_смещения_ведут_себя_как_раньше():
    p = u.SegmentPlan(trim_start=1.5, trim_duration=10.0)
    cmd = build(plan=plan_of(), segments=[seg(plan=p)])
    assert float(cmd.args[cmd.args.index("-ss") + 1]) == pytest.approx(1.5)


# ---------------------------------------------------------------- деление под рекламу


def test_половины_части_покрывают_её_целиком_и_не_налезают():
    p = u.SegmentPlan(trim_start=5.0, trim_duration=30.0)
    first, second = u._split_plan(p, 12.0)
    assert first.trim_start == 5.0 and first.trim_duration == pytest.approx(12.0)
    assert second.trim_start == pytest.approx(17.0)
    assert first.trim_duration + second.trim_duration == pytest.approx(30.0)


def test_у_половин_одинаковая_обработка():
    """Разный цвет или наклон у половин был бы виден на стыке вокруг рекламы."""
    p = u.SegmentPlan(trim_duration=30.0, color="warm", rotate_deg=2.0, speed=1.05, crop_px=4)
    first, second = u._split_plan(p, 10.0)
    for field in ("color", "rotate_deg", "speed", "crop_px", "border_px", "noise"):
        assert getattr(first, field) == getattr(second, field) == getattr(p, field)


@pytest.mark.parametrize("cut", [-5.0, 0.0, 0.1, 29.9, 100.0])
def test_точка_разреза_не_вылезает_за_границы(cut):
    p = u.SegmentPlan(trim_duration=30.0)
    first, second = u._split_plan(p, cut)
    assert first.trim_duration >= 0.5
    assert second.trim_duration >= 0.5


# ---------------------------------------------------------------- четыре сегмента


def test_хук_часть_реклама_часть_склеиваются_в_нужном_порядке():
    plan = plan_of()
    p = u.SegmentPlan(trim_duration=30.0)
    first, second = u._split_plan(p, 15.0)
    cmd = build(plan=plan, segments=[
        seg(path="/hook.mp4", dur=3.0),
        seg(path="/v.mp4", plan=first, offset=60.0),
        seg(path="/ad.mp4", dur=5.0),
        seg(path="/v.mp4", plan=second, offset=60.0),
    ])
    assert "concat=n=4:v=1:a=1[cv][ca]" in graph_of(cmd)
    assert inputs_of(cmd) == ["/hook.mp4", "/v.mp4", "/ad.mp4", "/v.mp4"]


def test_реклама_без_звука_получает_тишину():
    plan = plan_of()
    cmd = build(plan=plan, segments=[
        seg(path="/v.mp4", plan=u.SegmentPlan(trim_duration=10.0)),
        seg(path="/ad.mp4", audio=False, dur=5.0, plan=u.SegmentPlan(trim_duration=5.0)),
        seg(path="/v.mp4", plan=u.SegmentPlan(trim_start=10.0, trim_duration=10.0)),
    ])
    assert "anullsrc=r=44100:cl=stereo" in cmd.args
    assert "concat=n=3:v=1:a=1" in graph_of(cmd)


def test_метки_сегментов_не_конфликтуют():
    """При 4 сегментах метки фильтров должны остаться уникальными."""
    plan = plan_of()
    cmd = build(plan=plan, segments=[seg(path=f"/{i}.mp4") for i in range(4)])
    g = graph_of(cmd)
    for n in range(4):
        assert g.count(f"[sv{n}]") >= 1
    assert "concat=n=4" in g


def test_пустой_список_сегментов_отвергается():
    with pytest.raises(ValueError):
        build(plan=plan_of(), segments=[])


# ---------------------------------------------------------------- регресс


def test_старый_вызов_хук_плюс_видео_работает():
    """build_command по-прежнему принимает main/hook, без списка сегментов."""
    plan = plan_of()
    cmd = build(plan=plan, main=seg(path="/v.mp4"), hook=seg(path="/hook.mp4", dur=3.0))
    assert inputs_of(cmd) == ["/hook.mp4", "/v.mp4"]
    assert "concat=n=2:v=1:a=1" in graph_of(cmd)


def test_одиночное_видео_без_склейки():
    cmd = build(plan=plan_of(), main=seg())
    assert "concat=" not in graph_of(cmd)
