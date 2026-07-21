"""Интерактивный вход в аккаунт: запускаем headed-браузер на виртуальном дисплее
(Xvfb) сервера через прокси аккаунта, пользователь логинится руками (пароль/SMS/капча),
а по завершении сохраняем storage_state (куки + localStorage).

Экран браузера отдаётся пользователю через noVNC (x11vnc → websockify), поэтому
никакого GUI на сервере не нужно — окно видно прямо в панели.

За раз открыта одна сессия входа (один общий дисплей :99). Playwright-объекты держим
живыми между HTTP-запросами start → finish, поэтому запускаем async_playwright вручную
и останавливаем при finish/cancel.
"""
from __future__ import annotations

import asyncio
import os

from .uploaders.base import (
    STEALTH_INIT_JS,
    UploadError,
    load_storage_state,
    parse_proxy,
    stealth_context_kwargs,
    stealth_launch_kwargs,
)

# Куда вести пользователя на логин. Для YouTube — Studio (редиректит на вход Google).
LOGIN_URLS: dict[str, str] = {
    "tiktok": "https://www.tiktok.com/login",
    "youtube": "https://studio.youtube.com",
}


class LoginManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._nav_task: asyncio.Task | None = None
        self._account_id: int | None = None
        self._account_name: str | None = None

    @property
    def active(self) -> bool:
        return self._context is not None

    def status(self) -> dict:
        return {
            "active": self.active,
            "account_id": self._account_id,
            "account_name": self._account_name,
        }

    async def start(
        self,
        *,
        account_id: int,
        account_name: str,
        platform: str,
        proxy_url: str | None,
        cookies_path: str | None,
        display: str,
    ) -> None:
        async with self._lock:
            if self._context is not None:
                raise UploadError(
                    f"Уже открыт вход в аккаунт «{self._account_name}». "
                    f"Заверши его (сохрани куки) или отмени, прежде чем начинать новый."
                )

            os.environ["DISPLAY"] = display
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            proxy = parse_proxy(proxy_url) if proxy_url else None
            # Маскировка под обычный десктопный Chrome + окно на весь экран (headed).
            launch_kwargs = stealth_launch_kwargs(proxy, headless=False)
            launch_kwargs["args"] = [*launch_kwargs["args"], "--start-maximized"]

            try:
                self._browser = await self._pw.chromium.launch(**launch_kwargs)
                ctx_kwargs = stealth_context_kwargs(no_viewport=True)
                # Если куки уже есть — подгружаем, чтобы можно было «дологиниться»/обновить.
                if cookies_path and os.path.exists(cookies_path):
                    ctx_kwargs["storage_state"] = load_storage_state(cookies_path)
                self._context = await self._browser.new_context(**ctx_kwargs)
                await self._context.add_init_script(STEALTH_INIT_JS)
                self._page = await self._context.new_page()
            except Exception:
                await self._teardown()
                raise

            self._account_id = account_id
            self._account_name = account_name
            # Навигацию НЕ ждём синхронно: страница логина грузится долго (особенно
            # через прокси), а пользователь всё равно видит загрузку вживую в noVNC.
            # Так start отвечает сразу, а блокировка не держится всё время goto.
            url = LOGIN_URLS.get(platform, "about:blank")
            self._nav_task = asyncio.create_task(self._navigate(url))

    async def _navigate(self, url: str) -> None:
        try:
            await self._page.goto(url, wait_until="commit", timeout=60_000)
        except Exception:  # noqa: BLE001 — ошибки навигации не критичны, страница видна в noVNC
            pass

    async def finish(self, account_id: int) -> dict:
        """Возвращает storage_state текущей сессии и закрывает браузер."""
        async with self._lock:
            if self._context is None:
                raise UploadError("Активной сессии входа нет.")
            if self._account_id != account_id:
                raise UploadError(
                    f"Сессия входа открыта для другого аккаунта «{self._account_name}»."
                )
            state = await self._context.storage_state()
            await self._teardown()
            return state

    async def cancel(self) -> None:
        async with self._lock:
            await self._teardown()

    async def _teardown(self) -> None:
        if self._nav_task is not None:
            self._nav_task.cancel()
            try:
                await self._nav_task
            except BaseException:  # noqa: BLE001 — в т.ч. CancelledError при отмене задачи
                pass
            self._nav_task = None
        for obj, meth in (
            (self._context, "close"),
            (self._browser, "close"),
            (self._pw, "stop"),
        ):
            if obj is None:
                continue
            try:
                await getattr(obj, meth)()
            except Exception:  # noqa: BLE001 — глушим ошибки закрытия
                pass
        self._pw = self._browser = self._context = self._page = None
        self._account_id = self._account_name = None


login_manager = LoginManager()
