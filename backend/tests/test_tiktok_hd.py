"""Настройка «Высококачественные загрузки» в разделе «Дополнительно».

В Web Studio она включена всегда и изменению не подлежит, поэтому панель её
только читает. Работу с браузером юнит-тестом не проверить, поэтому здесь
проверяется то, что ломается на практике: фразы, по которым тумблер узнаётся
среди соседних переключателей, и то, что скрипт по нему не кликает.
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


def test_toggle_script_only_reads_state():
    """Тумблер в Web Studio неизменяем — скрипт обязан его не трогать.

    Вреда от прежнего клика не было только потому, что элемент заблокирован.
    Будь он кликабельным, панель сама выключила бы HD, поэтому отсутствие
    click() здесь — не придирка к стилю, а защита от этого случая.
    """
    assert "aria-checked" in HD_TOGGLE_JS
    assert ".click()" not in HD_TOGGLE_JS
    assert "'on'" in HD_TOGGLE_JS and "'not_found'" in HD_TOGGLE_JS
    assert "'off|'" in HD_TOGGLE_JS          # к «выключено» прилагается диагностика


def test_locked_toggle_counts_as_enabled():
    """Заблокированный тумблер рядом с текстом про HD — это штатное «включено»."""
    assert "aria-disabled" in HD_TOGGLE_JS
    assert "pointerEvents" in HD_TOGGLE_JS
