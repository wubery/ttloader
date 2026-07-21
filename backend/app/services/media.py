"""Работа с медиа через ffmpeg/ffprobe: probe размеров и наложение баннера.

Баннер описывается в долях кадра (0..1):
  x, y   — положение левого верхнего угла баннера,
  scale  — ширина баннера как доля от ширины исходного видео,
  opacity — прозрачность (0..1).

Это позволяет один и тот же баннер класть на видео любого разрешения одинаково
по «визуальным» координатам, как их видит пользователь в превью панели.
"""
from __future__ import annotations

import json
import os
import subprocess
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
    except FileNotFoundError as e:  # ffmpeg/ffprobe не установлены
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


def build_overlay_filter(
    video_w: int,
    banner_is_video: bool,
    x: float,
    y: float,
    scale: float,
    opacity: float,
) -> str:
    """Строит -filter_complex для наложения баннера ([0]=видео, [1]=баннер).

    Ширина баннера = scale * ширина_видео; позиция считается в пикселях от долей.
    Для видео-баннера используем shortest, чтобы длина не менялась.
    """
    target_w = max(1, round(scale * video_w))
    # x/y в пикселях выражаем через main_w/main_h (ffmpeg знает их в overlay)
    x_expr = f"(main_w*{x:.6f})"
    y_expr = f"(main_h*{y:.6f})"

    # Масштабируем баннер до target_w, высота — авто (сохранение пропорций).
    parts = [f"[1:v]scale={target_w}:-1"]
    if opacity < 0.999:
        # format с альфой + умножение альфа-канала на opacity
        parts.append(f"format=rgba,colorchannelmixer=aa={opacity:.4f}")
    parts.append("[bnr]")
    scale_chain = ",".join(parts[:-1]) + parts[-1]

    overlay = f"[0:v][bnr]overlay={x_expr}:{y_expr}"
    if banner_is_video:
        overlay += ":shortest=1"
    overlay += ":format=auto[out]"

    return f"{scale_chain};{overlay}"


def render_with_banner(
    video_path: str,
    banner_path: str,
    banner_is_video: bool,
    output_path: str,
    x: float,
    y: float,
    scale: float,
    opacity: float = 1.0,
) -> str:
    """Накладывает баннер на видео и пишет результат в output_path. Возвращает output_path."""
    info = probe(video_path)
    filt = build_overlay_filter(info.width, banner_is_video, x, y, scale, opacity)

    cmd = [settings.ffmpeg_bin, "-y"]
    cmd += ["-i", video_path]
    if banner_is_video:
        # Зацикливаем баннер-видео на всю длину исходника
        cmd += ["-stream_loop", "-1", "-i", banner_path]
    else:
        cmd += ["-i", banner_path]
    cmd += [
        "-filter_complex", filt,
        "-map", "[out]",
        "-map", "0:a?",           # звук исходника, если есть
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]
    _run(cmd)
    return output_path
