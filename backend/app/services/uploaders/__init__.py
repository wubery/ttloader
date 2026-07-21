"""Загрузчики видео в соцсети через браузерную автоматизацию Playwright.

Авторизация — по сохранённым кукам (storage_state). У каждого аккаунта свой
прокси, который передаётся при запуске браузера, чтобы IP аккаунта был постоянным.
"""
from __future__ import annotations

from .base import ProxyConfig, UploadResult, parse_proxy
from .tiktok import upload_tiktok
from .youtube import upload_youtube

__all__ = [
    "ProxyConfig",
    "UploadResult",
    "parse_proxy",
    "upload_tiktok",
    "upload_youtube",
    "get_uploader",
]


def get_uploader(platform: str):
    return {"tiktok": upload_tiktok, "youtube": upload_youtube}[platform]
