"""Общая обвязка для тестов: изолированная база и авторизованный клиент API.

Переменные окружения выставляются ДО импорта приложения — app.config.settings
создаётся при первом импорте, и позже подменить database_url уже нельзя.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

_TMP = Path(tempfile.mkdtemp(prefix="vp_tests_"))
# Перезаписываем, а НЕ setdefault: в контейнере DATABASE_URL и DATA_DIR уже указывают
# на боевые /data, и тесты (они создают аккаунты и группы) писали бы прямо туда.
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["DATA_DIR"] = str(_TMP / "data")
os.environ["ADMIN_USER"] = "test"
os.environ["ADMIN_PASS"] = "test-pass"
for _leak in ("VIDEOS_DIR", "BANNERS_DIR", "OUTPUT_DIR", "COOKIES_DIR",
              "HOOKS_DIR", "OVERLAYS_DIR", "BACKGROUNDS_DIR", "ADS_DIR"):
    os.environ.pop(_leak, None)        # иначе часть каталогов осталась бы боевой


@pytest.fixture(scope="session")
def client():
    """TestClient с валидной сессией.

    Создаём без `with`: контекстный менеджер запустил бы lifespan, а вместе с ним
    планировщик и Telegram-бота — тестам они не нужны. Поэтому init_db() и
    bootstrap_settings() зовём руками.
    """
    from fastapi.testclient import TestClient

    from app.db import init_db
    from app.main import app
    from app.services.appsettings import bootstrap_settings

    init_db()
    bootstrap_settings()
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": "test", "password": "test-pass"})
    assert r.status_code == 200, r.text        # иначе auth_guard вернёт 401 на всё
    return c
