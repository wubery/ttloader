"""Лёгкие вариации подписи для постинга одного ролика на несколько аккаунтов.

Одинаковая байт-в-байт подпись на нескольких аккаунтах — заметный след. Меняем
только то, что не искажает смысл: порядок хештегов и эмодзи в хвосте. Тело текста
остаётся нетронутым.
"""
from __future__ import annotations

import random

# Нейтральный набор: добавляем один символ в конец, если своих эмодзи нет.
_TAIL_EMOJI = ("✨", "🔥", "🎬", "👀", "💫", "⚡", "🎯", "🙌")

# Диапазоны эмодзи, по которым определяем, есть ли он уже в подписи.
_EMOJI_RANGES = (
    (0x1F300, 0x1FAFF),   # пиктограммы, эмоции, символы
    (0x2600, 0x27BF),     # разные символы и дингбаты
    (0xFE0F, 0xFE0F),     # variation selector
    (0x2190, 0x21FF),     # стрелки
)


def has_emoji(text: str) -> bool:
    return any(any(lo <= ord(ch) <= hi for lo, hi in _EMOJI_RANGES) for ch in text)


def vary(text: str, seed: int) -> str:
    """Возвращает вариант подписи для аккаунта с номером `seed` в пачке.

    Детерминирована: один и тот же seed даёт один и тот же результат, разные —
    разные. Если варьировать нечего (нет хештегов и эмодзи уже есть), текст
    возвращается без изменений.
    """
    if not text or not text.strip():
        return text

    rnd = random.Random(seed)
    words = text.split()
    tags = [w for w in words if w.startswith("#") and len(w) > 1]
    body = [w for w in words if not (w.startswith("#") and len(w) > 1)]

    if len(tags) > 1:
        # Перемешиваем, пока порядок реально не изменится (для 2+ тегов это быстро).
        original = list(tags)
        for _ in range(5):
            rnd.shuffle(tags)
            if tags != original:
                break

    out = " ".join(body + tags).strip()
    if not has_emoji(out):
        out = f"{out} {_TAIL_EMOJI[seed % len(_TAIL_EMOJI)]}".strip()
    return out
