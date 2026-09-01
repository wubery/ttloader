"""Конвейер уникализации видео.

Один проход ffmpeg: хук и основное видео проходят одинаковый набор операций
(каждый со своими значениями), затем склеиваются, сверху ложатся слои редактора,
метаданные стираются.

Сборка filtergraph — чистые функции (строка на входе, строка на выходе), чтобы
её можно было проверять тестами без единого реального рендера. Запуск ffmpeg —
отдельно, в `render`.

Правила экранирования те же, что сложились в media.py: выражения с запятыми — в
одинарных кавычках, `enable=between(t\\,a\\,b)` — со слэшем, текст — только файлом.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace
from typing import Any

# ---------------------------------------------------------------- параметры

# Цветовые пресеты: значения подобраны так, чтобы менять картинку заметно для
# алгоритма сравнения, но не бросаться в глаза зрителю.
COLOR_PRESETS: dict[str, str] = {
    "warm": "eq=brightness=0.02:saturation=1.06:gamma=1.02,hue=h=4",
    "cool": "eq=brightness=-0.01:saturation=1.04:gamma=0.99,hue=h=-5",
    "contrast": "eq=contrast=1.08:brightness=-0.01:saturation=1.02",
    "fade": "eq=contrast=0.94:brightness=0.03:saturation=0.92",
    "vivid": "eq=contrast=1.05:saturation=1.12:gamma=1.03",
}

DEFAULT_PARAMS: dict[str, Any] = {
    "trim": {"on": True, "percent": [0, 10], "from": "both"},
    "speed": {"on": True, "factor": [0.94, 1.06]},
    "crop": {"on": True, "px": [1, 10]},
    "rotate": {"on": True, "deg": [1, 3], "flip180": False},
    "color": {"on": True, "presets": list(COLOR_PRESETS)},
    "noise": {"on": False, "strength": [1, 3]},
    "canvas": {"on": True, "w": 1080, "h": 1920, "border_px": [10, 20], "bg": "blur",
               "color": "#000000", "bg_asset_id": None, "bg_random": True},
    "overlay": {"on": False, "asset_id": None, "random": True, "opacity": [0.05, 0.20]},
    "hook": {"on": False, "asset_id": None, "random": True},
    "ad": {"on": False, "asset_id": None, "random": True},
    "metadata": {"on": True},
}


def merge_params(raw: dict | None) -> dict:
    """Профиль поверх дефолтов: чего нет в JSON — берётся из DEFAULT_PARAMS."""
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in DEFAULT_PARAMS.items()}
    for key, val in (raw or {}).items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key].update(val)
        else:
            out[key] = val
    return out


def _rng_pair(block: dict, key: str, default: list) -> tuple[float, float]:
    pair = block.get(key) or default
    try:
        lo, hi = float(pair[0]), float(pair[1])
    except (TypeError, ValueError, IndexError):
        lo, hi = float(default[0]), float(default[1])
    return (lo, hi) if lo <= hi else (hi, lo)


@dataclass
class SegmentPlan:
    """Конкретные значения для одного сегмента (хука или основного видео)."""

    trim_start: float = 0.0
    trim_duration: float | None = None
    speed: float = 1.0
    crop_px: int = 0
    rotate_deg: float = 0.0
    flip180: bool = False
    color: str | None = None
    noise: int = 0
    border_px: int = 0

    def describe(self) -> str:
        """Короткая строка для лога задачи — чтобы видеть, что применилось."""
        bits = []
        if self.trim_start or self.trim_duration:
            bits.append(f"обрезка {self.trim_start:.1f}с"
                        + (f"+{self.trim_duration:.1f}с" if self.trim_duration else ""))
        if abs(self.speed - 1.0) > 0.001:
            bits.append(f"скорость {self.speed:.3f}")
        if self.crop_px:
            bits.append(f"кроп {self.crop_px}px")
        if self.flip180:
            bits.append("поворот 180°")
        elif self.rotate_deg:
            bits.append(f"наклон {self.rotate_deg:.2f}°")
        if self.color:
            bits.append(f"цвет {self.color}")
        if self.noise:
            bits.append(f"шум {self.noise}")
        if self.border_px:
            bits.append(f"рамка {self.border_px}px")
        return ", ".join(bits) or "без изменений"


@dataclass
class UniqPlan:
    """Разыгранные параметры на один рендер."""

    main: SegmentPlan
    hook: SegmentPlan | None = None
    canvas_w: int = 1080
    canvas_h: int = 1920
    canvas_on: bool = True
    canvas_bg: str = "blur"
    canvas_color: str = "#000000"
    overlay_opacity: float = 0.0
    metadata: bool = True
    fps: int = 30
    extra: dict = field(default_factory=dict)


def roll(params: dict, *, duration: float, rnd: random.Random,
         with_hook: bool = False, hook_duration: float = 0.0) -> UniqPlan:
    """Диапазоны → конкретные значения.

    Авторежим и ручной — одно и то же: «вручную» означает равные границы
    диапазона, тогда random вернёт именно это число.
    """
    p = merge_params(params)

    def segment(total: float) -> SegmentPlan:
        seg = SegmentPlan()

        trim = p.get("trim") or {}
        if trim.get("on") and total > 1.0:
            lo, hi = _rng_pair(trim, "percent", [0, 10])
            cut = total * rnd.uniform(lo, hi) / 100.0
            cut = min(cut, max(0.0, total - 0.5))     # не срезаем ролик в ноль
            where = trim.get("from", "both")
            if where == "start":
                seg.trim_start, seg.trim_duration = cut, total - cut
            elif where == "end":
                seg.trim_start, seg.trim_duration = 0.0, total - cut
            else:
                seg.trim_start = cut / 2
                seg.trim_duration = total - cut
        else:
            seg.trim_duration = total or None

        speed = p.get("speed") or {}
        if speed.get("on"):
            lo, hi = _rng_pair(speed, "factor", [0.94, 1.06])
            # atempo без каскада работает в 0.5–2.0; сюда же упираем ручной ввод
            seg.speed = max(0.5, min(2.0, rnd.uniform(lo, hi)))

        crop = p.get("crop") or {}
        if crop.get("on"):
            lo, hi = _rng_pair(crop, "px", [1, 10])
            seg.crop_px = int(round(rnd.uniform(lo, hi)))

        rot = p.get("rotate") or {}
        if rot.get("on"):
            if rot.get("flip180"):
                seg.flip180 = True                      # только вручную, в авто не попадает
            else:
                lo, hi = _rng_pair(rot, "deg", [1, 3])
                seg.rotate_deg = rnd.uniform(lo, hi) * rnd.choice((-1, 1))

        color = p.get("color") or {}
        if color.get("on"):
            names = [n for n in (color.get("presets") or []) if n in COLOR_PRESETS]
            if names:
                seg.color = rnd.choice(names)

        noise = p.get("noise") or {}
        if noise.get("on"):
            lo, hi = _rng_pair(noise, "strength", [1, 3])
            seg.noise = int(round(rnd.uniform(lo, hi)))

        canvas = p.get("canvas") or {}
        if canvas.get("on"):
            lo, hi = _rng_pair(canvas, "border_px", [10, 20])
            seg.border_px = int(round(rnd.uniform(lo, hi)))
        return seg

    canvas = p.get("canvas") or {}
    ov = p.get("overlay") or {}
    opacity = 0.0
    if ov.get("on"):
        lo, hi = _rng_pair(ov, "opacity", [0.05, 0.20])
        opacity = rnd.uniform(lo, hi)

    return UniqPlan(
        main=segment(duration),
        hook=segment(hook_duration) if with_hook else None,
        canvas_w=int(canvas.get("w") or 1080),
        canvas_h=int(canvas.get("h") or 1920),
        canvas_on=bool(canvas.get("on")),
        canvas_bg=str(canvas.get("bg") or "blur"),
        canvas_color=str(canvas.get("color") or "#000000"),
        overlay_opacity=opacity,
        metadata=bool((p.get("metadata") or {}).get("on", True)),
    )


# ---------------------------------------------------------------- filtergraph


def _norm_color(value: str | None) -> str:
    s = (value or "").strip().lstrip("#")
    if len(s) == 6 and all(c in "0123456789abcdefABCDEF" for c in s):
        return f"0x{s.lower()}"
    return "black"


def rotate_scale_factor(deg: float, w: int, h: int) -> float:
    """Во сколько раз увеличить кадр перед поворотом, чтобы не было чёрных углов.

    После поворота на угол a вписанный прямоугольник исходных пропорций меньше
    исходного; коэффициент — обратная величина этого сжатия.
    """
    a = abs(math.radians(deg))
    if a < 1e-6 or w <= 0 or h <= 0:
        return 1.0
    return abs(math.cos(a)) + abs(math.sin(a)) * (max(w, h) / min(w, h))


def segment_chain(plan: SegmentPlan, canvas: UniqPlan, src: str, out: str,
                  width: int, height: int, bg_src: str | None = None) -> list[str]:
    """Цепочка фильтров одного сегмента: [src] … [out]."""
    steps: list[str] = []

    if abs(plan.speed - 1.0) > 0.001:
        steps.append(f"setpts=PTS/{plan.speed:.5f}")

    if plan.crop_px > 0:
        d = plan.crop_px
        steps.append(f"crop=iw-{2 * d}:ih-{2 * d}:{d}:{d}")

    if plan.flip180:
        steps.append("hflip,vflip")
    elif abs(plan.rotate_deg) > 0.01:
        k = rotate_scale_factor(plan.rotate_deg, width, height)
        rad = math.radians(plan.rotate_deg)
        steps.append(f"scale=iw*{k:.5f}:ih*{k:.5f}")
        steps.append(f"rotate={rad:.6f}:ow=iw:oh=ih")
        # возвращаемся к размеру до масштабирования — края с чёрными углами уходят
        steps.append(f"crop=iw/{k:.5f}:ih/{k:.5f}")

    if plan.color and plan.color in COLOR_PRESETS:
        steps.append(COLOR_PRESETS[plan.color])

    if plan.noise > 0:
        steps.append(f"noise=alls={plan.noise}:allf=t")

    chains: list[str] = []
    cur = src
    if steps:
        chains.append(f"{cur}{','.join(steps)}[sg_{out.strip('[]')}]")
        cur = f"[sg_{out.strip('[]')}]"

    if canvas.canvas_on:
        chains.extend(_canvas_chain(plan, canvas, cur, out, bg_src))
    else:
        # без холста всё равно нормализуем — concat не терпит разных размеров
        chains.append(
            f"{cur}scale={canvas.canvas_w}:{canvas.canvas_h}:force_original_aspect_ratio=decrease,"
            f"pad={canvas.canvas_w}:{canvas.canvas_h}:(ow-iw)/2:(oh-ih)/2:{_norm_color(canvas.canvas_color)},"
            f"setsar=1,fps={canvas.fps}{out}"
        )
    return chains


def _canvas_chain(plan: SegmentPlan, canvas: UniqPlan, src: str, out: str,
                  bg_src: str | None = None) -> list[str]:
    """Вписывание в холст с рамкой.

    Фон рамки — три варианта: свой файл (картинка или видео), размытая копия
    кадра или сплошной цвет.
    """
    w, h = canvas.canvas_w, canvas.canvas_h
    b = max(0, plan.border_px)
    inner_w, inner_h = max(2, w - 2 * b), max(2, h - 2 * b)
    tag = out.strip("[]")

    fit = (f"scale={inner_w}:{inner_h}:force_original_aspect_ratio=decrease,"
           f"scale=trunc(iw/2)*2:trunc(ih/2)*2")

    if canvas.canvas_bg == "image" and bg_src:
        # свой фон: растягиваем на весь холст с обрезкой по центру, ролик — поверх
        return [
            f"{bg_src}scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1[bgi_{tag}]",
            f"{src}{fit}[fgi_{tag}]",
            f"[bgi_{tag}][fgi_{tag}]overlay=(W-w)/2:(H-h)/2:shortest=1,setsar=1,fps={canvas.fps}{out}",
        ]

    if canvas.canvas_bg == "blur":
        # копия кадра во весь холст, размытая, — фон; поверх вписанное видео
        return [
            f"{src}split=2[bg_{tag}][fg_{tag}]",
            f"[bg_{tag}]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},gblur=sigma=24[bgb_{tag}]",
            f"[fg_{tag}]{fit}[fgs_{tag}]",
            f"[bgb_{tag}][fgs_{tag}]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={canvas.fps}{out}",
        ]
    return [
        f"{src}{fit},pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:{_norm_color(canvas.canvas_color)},"
        f"setsar=1,fps={canvas.fps}{out}"
    ]


def audio_chain(plan: SegmentPlan, src: str, out: str) -> str:
    """Аудио сегмента: темп под скорость видео + приведение к общему формату."""
    steps = []
    if abs(plan.speed - 1.0) > 0.001:
        steps.append(f"atempo={plan.speed:.5f}")
    steps.append("aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo")
    return f"{src}{','.join(steps)}{out}"


# ---------------------------------------------------------------- команда


@dataclass
class SegmentInput:
    """Один входной ролик конвейера."""

    path: str
    width: int
    height: int
    duration: float
    has_audio: bool
    plan: SegmentPlan
    # Начало окна внутри файла: для части длинного видео. Обрезка уникализации
    # (plan.trim_start) считается ОТ ЭТОГО смещения, а не от начала файла.
    offset: float = 0.0


@dataclass
class BuiltCommand:
    args: list[str]
    tmp_texts: list[str]      # временные файлы слоёв — удалить после запуска


def build_command(
    *,
    ffmpeg_bin: str,
    plan: UniqPlan,
    output_path: str,
    main: SegmentInput | None = None,
    hook: SegmentInput | None = None,
    segments: list[SegmentInput] | None = None,
    overlay_png: str | None = None,
    background: str | None = None,
    background_is_video: bool = False,
    editor_overlays: list[dict] | None = None,
    encode_args: list[str],
    metadata_args: list[str],
    layers_builder=None,
) -> BuiltCommand:
    """Собирает полную команду ffmpeg: сегменты → склейка → слои → кодирование.

    `layers_builder` — media.build_layers_chain (передаётся аргументом, чтобы
    модуль оставался тестируемым без ffmpeg и без циклического импорта).
    """
    # Либо готовый список (части, реклама), либо привычная пара «хук + видео».
    if segments is None:
        segments = [s for s in (hook, main) if s is not None]   # хук идёт первым
    if not segments:
        raise ValueError("Не задан ни один сегмент для рендера")
    args: list[str] = [ffmpeg_bin, "-y"]
    chains: list[str] = []
    idx = 0
    v_labels: list[str] = []
    a_labels: list[str] = []

    for n, seg in enumerate(segments):
        # обрезка — на уровне входа: дешевле фильтров и не путает тайминги
        start = seg.offset + seg.plan.trim_start
        if start > 0.001:
            args += ["-ss", f"{start:.3f}"]
        if seg.plan.trim_duration and seg.plan.trim_duration > 0.05:
            args += ["-t", f"{seg.plan.trim_duration:.3f}"]
        args += ["-i", seg.path]
        seg_idx = idx
        idx += 1

        bg_label = None
        if plan.canvas_bg == "image" and background:
            # свой вход на каждый сегмент: одну метку нельзя использовать дважды
            if background_is_video:
                args += ["-stream_loop", "-1"]
            else:
                # без -loop картинка живёт один кадр, и overlay:shortest=1
                # обрезает результат до нуля — на выходе файл без видеодорожки
                args += ["-loop", "1"]
            args += ["-i", background]
            bg_label = f"[{idx}:v]"
            idx += 1

        vlbl = f"[sv{n}]"
        chains += segment_chain(seg.plan, plan, f"[{seg_idx}:v]", vlbl, seg.width, seg.height, bg_label)
        v_labels.append(vlbl)

        albl = f"[sa{n}]"
        if seg.has_audio:
            chains.append(audio_chain(seg.plan, f"[{seg_idx}:a]", albl))
        else:
            # concat=a=1 падает на сегменте без звука — подставляем тишину нужной длины
            dur = (seg.plan.trim_duration or seg.duration or 1.0) / max(0.1, seg.plan.speed)
            args += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
            chains.append(
                f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo{albl}"
            )
            idx += 1
        a_labels.append(albl)

    # склейка сегментов (или прямой проброс, если хука нет)
    if len(segments) > 1:
        joined = "".join(v + a for v, a in zip(v_labels, a_labels))
        chains.append(f"{joined}concat=n={len(segments)}:v=1:a=1[cv][ca]")
        cur_v, cur_a = "[cv]", "[ca]"
    else:
        cur_v, cur_a = v_labels[0], a_labels[0]

    # полнокадровый PNG-оверлей поверх результата
    if overlay_png and plan.overlay_opacity > 0.001:
        args += ["-i", overlay_png]
        ov_idx = idx
        idx += 1
        chains.append(
            f"[{ov_idx}:v]scale={plan.canvas_w}:{plan.canvas_h},format=rgba,"
            f"colorchannelmixer=aa={plan.overlay_opacity:.4f}[ovl]"
        )
        chains.append(f"{cur_v}[ovl]overlay=0:0:format=auto[ov_out]")
        cur_v = "[ov_out]"

    # слои редактора (баннеры и текст) — поверх всего
    tmp_texts: list[str] = []
    if editor_overlays and layers_builder is not None:
        total = sum((s.plan.trim_duration or s.duration or 0.0) / max(0.1, s.plan.speed)
                    for s in segments)
        built = layers_builder(
            editor_overlays,
            src_label=cur_v,
            next_input=idx,
            width=plan.canvas_w,
            height=plan.canvas_h,
            duration=total,
        )
        if built.chains:
            args += built.inputs
            chains += built.chains
            cur_v = built.out_label
        tmp_texts = built.tmp_texts

    args += ["-filter_complex", ";".join(chains), "-map", cur_v, "-map", cur_a]
    args += encode_args
    if plan.metadata:
        args += metadata_args
    args += [output_path]
    return BuiltCommand(args=args, tmp_texts=tmp_texts)


def _split_plan(plan: SegmentPlan, cut: float) -> tuple[SegmentPlan, SegmentPlan]:
    """Делит план части на две половины по точке `cut` (отсчёт от начала части).

    Обе половины получают одинаковую обработку (цвет, наклон, скорость) — иначе на
    стыке вокруг рекламы будет видно скачок картинки.
    """
    total = plan.trim_duration or 0.0
    cut = max(0.5, min(cut, max(0.5, total - 0.5)))
    first = replace(plan, trim_duration=cut)
    second = replace(plan, trim_start=plan.trim_start + cut, trim_duration=max(0.5, total - cut))
    return first, second


def render(
    *,
    video_path: str,
    output_path: str,
    params: dict,
    hook_path: str | None = None,
    ad_path: str | None = None,
    part_start: float = 0.0,
    part_duration: float | None = None,
    overlay_png: str | None = None,
    background: str | None = None,
    background_is_video: bool = False,
    editor_overlays: list[dict] | None = None,
    seed: int | None = None,
    log=lambda m: None,
) -> str:
    """Полный конвейер уникализации одним проходом ffmpeg.

    `part_start`/`part_duration` — окно внутри исходника (часть длинного видео).
    `ad_path` — рекламный ролик: часть разрезается в случайной точке средней трети,
    реклама вставляется между половинами.
    """
    from . import media  # локальный импорт: media тянет config, а тут только строки

    info = media.probe(video_path)
    hook_info = media.probe(hook_path) if hook_path else None
    ad_info = media.probe(ad_path) if ad_path else None

    # длительность именно того куска, который публикуем
    window = part_duration if part_duration and part_duration > 0.1 else info.duration
    rnd = random.Random(seed)
    plan = roll(
        params,
        duration=window,
        rnd=rnd,
        with_hook=hook_info is not None,
        hook_duration=hook_info.duration if hook_info else 0.0,
    )

    segments: list[SegmentInput] = []
    if hook_info and plan.hook:
        segments.append(SegmentInput(
            path=hook_path, width=hook_info.width, height=hook_info.height,
            duration=hook_info.duration, has_audio=hook_info.has_audio, plan=plan.hook,
        ))
        log(f"Хук: {plan.hook.describe()}")

    def _video_seg(plan_: SegmentPlan, offset: float) -> SegmentInput:
        return SegmentInput(
            path=video_path, width=info.width, height=info.height,
            duration=info.duration, has_audio=info.has_audio, plan=plan_, offset=offset,
        )

    if ad_info:
        # точка разреза — случайно в средней трети части
        eff = plan.main.trim_duration or window
        cut = eff * rnd.uniform(1 / 3, 2 / 3)
        first, second = _split_plan(plan.main, cut)
        segments.append(_video_seg(first, part_start))
        segments.append(SegmentInput(
            path=ad_path, width=ad_info.width, height=ad_info.height,
            duration=ad_info.duration, has_audio=ad_info.has_audio,
            plan=roll(params, duration=ad_info.duration, rnd=rnd).main,
        ))
        segments.append(_video_seg(second, part_start))
        log(f"Видео: {plan.main.describe()}; реклама вставлена на {cut:.1f}с "
            f"({ad_info.duration:.1f}с)")
    else:
        segments.append(_video_seg(plan.main, part_start))
        log(f"Видео: {plan.main.describe()}")

    built = build_command(
        ffmpeg_bin=media.settings.ffmpeg_bin,
        segments=segments,
        plan=plan,
        output_path=output_path,
        overlay_png=overlay_png,
        background=background,
        background_is_video=background_is_video,
        editor_overlays=editor_overlays,
        encode_args=media._encode_args(),
        metadata_args=media._uniq_metadata_args(),
        layers_builder=media.build_layers_chain,
    )
    try:
        media._run(built.args)
    finally:
        for p in built.tmp_texts:
            try:
                import os

                os.remove(p)
            except OSError:
                pass
    return output_path
