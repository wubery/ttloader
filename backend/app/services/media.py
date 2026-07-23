"""Работа с медиа через ffmpeg/ffprobe: probe, наложение баннера (в т.ч. движущегося)
и уникализация видео (подмена хеша/фингерпринта).

Баннер описывается в долях кадра (0..1): x, y — левый верхний угол, scale — ширина
баннера как доля ширины видео, opacity — прозрачность. motion — тип движения по кадру.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import uuid
from dataclasses import dataclass

from ..config import settings


class MediaError(RuntimeError):
    pass


@dataclass
class VideoInfo:
    width: int
    height: int
    duration: float


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError as e:
        raise MediaError(
            f"Не найден бинарник: {cmd[0]}. Установите ffmpeg и/или укажите путь в .env "
            f"(FFMPEG_BIN / FFPROBE_BIN)."
        ) from e
    except subprocess.CalledProcessError as e:
        raise MediaError(f"{os.path.basename(cmd[0])} завершился с ошибкой:\n{e.stderr[-2000:]}") from e


def probe(path: str) -> VideoInfo:
    cmd = [
        settings.ffprobe_bin, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height:format=duration",
        "-of", "json", path,
    ]
    out = _run(cmd).stdout
    data = json.loads(out)
    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}
    try:
        return VideoInfo(
            width=int(stream["width"]),
            height=int(stream["height"]),
            duration=float(fmt.get("duration", 0.0) or 0.0),
        )
    except (KeyError, ValueError) as e:
        raise MediaError(f"Не удалось определить параметры видео: {path}") from e


def _motion_exprs(x: float, y: float, motion: str, speed: float) -> tuple[str, str]:
    """x/y выражения для overlay (в кавычках, чтобы запятые внутри mod() не ломали граф)."""
    bx = f"(main_w*{x:.6f})"
    by = f"(main_h*{y:.6f})"
    s = f"{max(0.05, speed):.4f}"
    if motion == "drift":
        return (f"{bx}+(main_w*0.03)*sin(2*PI*0.1*{s}*t)",
                f"{by}+(main_h*0.03)*cos(2*PI*0.1*{s}*t)")
    if motion == "bounce":
        return (f"abs(mod(t*(main_w*0.06*{s}),2*(main_w-overlay_w))-(main_w-overlay_w))",
                f"abs(mod(t*(main_h*0.06*{s}),2*(main_h-overlay_h))-(main_h-overlay_h))")
    if motion == "slide":
        return (f"mod(t*(main_w*0.08*{s}),main_w+overlay_w)-overlay_w", by)
    return (bx, by)


def build_overlay_filter(
    video_w: int,
    banner_is_video: bool,
    x: float,
    y: float,
    scale: float,
    opacity: float,
    motion: str = "none",
    motion_speed: float = 1.0,
) -> str:
    """-filter_complex для наложения баннера ([0]=видео, [1]=баннер) → метка [out]."""
    target_w = max(1, round(scale * video_w))
    x_expr, y_expr = _motion_exprs(x, y, motion, motion_speed)

    parts = [f"[1:v]scale={target_w}:-1"]
    if opacity < 0.999:
        parts.append(f"format=rgba,colorchannelmixer=aa={opacity:.4f}")
    parts.append("[bnr]")
    scale_chain = ",".join(parts[:-1]) + parts[-1]

    overlay = f"[0:v][bnr]overlay=x='{x_expr}':y='{y_expr}'"
    if banner_is_video:
        overlay += ":shortest=1"
    overlay += ":format=auto[out]"
    return f"{scale_chain};{overlay}"


def _uniq_vf(width: int, height: int) -> str:
    """Фильтр уникализации: микрокроп+ресайз (незаметно, меняет каждый пиксель) +
    крошечные яркость/насыщенность + лёгкий шум. Меняет фингерпринт/хеш видео."""
    b = random.uniform(-0.02, 0.02)
    s = random.uniform(0.97, 1.03)
    n = random.randint(1, 3)
    return (f"crop=iw-2:ih-2:1:1,scale={width}:{height},"
            f"eq=brightness={b:.4f}:saturation={s:.4f},noise=alls={n}:allf=t")


def _uniq_metadata_args() -> list[str]:
    return [
        "-map_metadata", "-1",
        "-metadata", f"title=v{uuid.uuid4().hex[:8]}",
        "-metadata", f"comment={uuid.uuid4().hex}",
    ]


def _encode_args() -> list[str]:
    return [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(random.randint(19, 23)),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
    ]


def render_with_banner(
    video_path: str,
    banner_path: str,
    banner_is_video: bool,
    output_path: str,
    x: float,
    y: float,
    scale: float,
    opacity: float = 1.0,
    motion: str = "none",
    motion_speed: float = 1.0,
    uniqueize: bool = True,
) -> str:
    """Накладывает баннер (опц. движущийся) и опц. уникализирует. Возвращает output_path."""
    info = probe(video_path)
    filt = build_overlay_filter(info.width, banner_is_video, x, y, scale, opacity, motion, motion_speed)

    map_label = "[out]"
    if uniqueize:
        filt += f";[out]{_uniq_vf(info.width, info.height)}[vout]"
        map_label = "[vout]"

    cmd = [settings.ffmpeg_bin, "-y", "-i", video_path]
    if banner_is_video:
        cmd += ["-stream_loop", "-1", "-i", banner_path]
    else:
        cmd += ["-i", banner_path]
    cmd += ["-filter_complex", filt, "-map", map_label, "-map", "0:a?"]
    cmd += _encode_args()
    if uniqueize:
        cmd += _uniq_metadata_args()
    cmd += [output_path]
    _run(cmd)
    return output_path


def render_uniqueize(video_path: str, output_path: str) -> str:
    """Уникализация без баннера: лёгкие изменения + случайные метаданные → новый хеш."""
    info = probe(video_path)
    cmd = [settings.ffmpeg_bin, "-y", "-i", video_path, "-vf", _uniq_vf(info.width, info.height)]
    cmd += ["-map", "0:v:0", "-map", "0:a?"]
    cmd += _encode_args()
    cmd += _uniq_metadata_args()
    cmd += [output_path]
    _run(cmd)
    return output_path
