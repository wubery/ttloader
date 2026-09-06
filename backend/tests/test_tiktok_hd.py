"""Настройка «Загружать в высоком качестве» в разделе «Дополнительно».

Без неё веб-загрузчик TikTok отдаёт ролик в пониженном качестве — сколько ни
улучшай рендер, зритель увидит мыло. Сам клик проверить юнит-тестом нельзя (он
живёт в браузере), поэтому здесь проверяется то, что ломается на практике: фразы,
по которым тумблер узнаётся среди соседних переключателей.
"""
from __future__ import annotations

import pytest

from app.services.uploaders.tiktok import HD_HINTS, HD_TOGGLE_JS, MORE_SETTINGS_LABELS


def matches(text: str) -> bool:
    """То же сопоставление, что делает HD_TOGGLE_JS: нижний регистр + вхождение."""
    low = text.lower()
    return any(h in low for h in HD_HINTS)


@pytest.mark.parametrize("label", [
    "Загружать в высоком качестве",
    "Загрузка в высоком качестве",
    "Загружать видео в высоком качестве",
    "Upload high quality video",
    "Allow high-quality uploads",
    "Upload HD video",
])
def test_quality_switch_is_recognised(label):
    assert matches(label)


@pytest.mark.parametrize("label", [
    "Разрешить комментарии",
    "Разрешить дуэты",
    "Разрешить склейку",
    "Кто может смотреть это видео",
    "Добавить ссылку",
    "Add hashtag",
    "Allow duet",
])
def test_other_switches_are_not_touched(label):
    """Короткое «hd» ловило чужие подписи — можно было щёлкнуть не тот тумблер."""
    assert not matches(label)


def test_advanced_tab_is_first_candidate():
    """Раздел называется «Дополнительно» — с него и начинаем раскрывать."""
    assert MORE_SETTINGS_LABELS[0] == "Дополнительно"
    assert "Advanced" in MORE_SETTINGS_LABELS


def test_toggle_script_verifies_result():
    """Скрипт обязан перечитывать состояние, а не считать клик успехом."""
    assert "aria-checked" in HD_TOGGLE_JS
    assert "'enabled'" in HD_TOGGLE_JS and "'unchanged'" in HD_TOGGLE_JS
    assert "'already'" in HD_TOGGLE_JS and "'not_found'" in HD_TOGGLE_JS
