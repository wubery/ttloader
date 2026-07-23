"""Встроенный вход в аккаунт: логин/пароль → (код с почты) → сохранение кук.

Backend в фоне держит headless-браузер Playwright (через прокси аккаунта), сам
заполняет форму входа TikTok, а пользователь при необходимости вводит код с почты
прямо в панели. Никакого живого окна/noVNC — при неожиданном шаге (капча) отдаём
скриншот, пользователь решает вне панели или импортирует куки вручную.

За раз открыта одна сессия входа. Playwright-объекты живут между HTTP-запросами
credentials → code, поэтому async_playwright запускаем вручную и держим до конца.

ВНИМАНИЕ: селекторы TikTok периодически меняются — правьте константы ниже.
"""
from __future__ import annotations

import asyncio
import base64

from .uploaders.base import (
    STEALTH_INIT_JS,
    UploadError,
    parse_proxy,
    stealth_context_kwargs,
    stealth_launch_kwargs,
)

LOGIN_URLS: dict[str, str] = {
    "tiktok": "https://www.tiktok.com/login/phone-or-email/email",
    # YouTube/Google логин по паролю через автоматизацию Google обычно блокирует —
    # для него остаётся ручной импорт кук.
    "youtube": "https://studio.youtube.com",
}

# --- селекторы TikTok (могут требовать актуализации) ---
EMAIL_TAB_SEL = (
    'a:has-text("email or username"), a:has-text("почты или имени"), '
    'a:has-text("Email"), a:has-text("почт")'
)
USERNAME_SEL = 'input[name="username"], input[type="text"]:not([name="code"])'
PASSWORD_SEL = 'input[type="password"]'
LOGIN_BTN_SEL = 'button[data-e2e="login-button"], button[type="submit"]'
CODE_INPUT_SEL = (
    'input[name="code"], input[placeholder*="code" i], input[placeholder*="код" i], '
    'input[maxlength="6"]'
)
SEND_CODE_SEL = (
    'button:has-text("Send code"), button:has-text("Отправить код"), '
    'button:has-text("Получить код"), button:has-text("Send")'
)
VERIFY_BTN_SEL = (
    'button:has-text("Verify"), button:has-text("Log in"), button:has-text("Войти"), '
    'button:has-text("Подтвердить"), button[data-e2e="login-button"], button[type="submit"]'
)
CAPTCHA_SEL = '.captcha_verify_container, [class*="captcha" i], #captcha-verify-container'
ERROR_SEL = '[class*="error" i]'


class LoginManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
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

    async def _screenshot_b64(self) -> str | None:
        try:
            png = await self._page.screenshot(type="png")
            return "data:image/png;base64," + base64.b64encode(png).decode()
        except Exception:  # noqa: BLE001
            return None

    async def _detect_stage(self, timeout_ms: int = 25_000) -> str:
        """Ждём один из исходов: done | email_code | captcha | unknown."""
        waited = 0
        step = 1500
        while waited < timeout_ms:
            url = self._page.url
            if "/login" not in url and "/signup" not in url:
                return "done"
            try:
                if await self._page.locator(CODE_INPUT_SEL).count() > 0:
                    # если рядом есть кнопка «отправить код» — жмём, чтобы код ушёл на почту
                    try:
                        btn = self._page.locator(SEND_CODE_SEL).first
                        if await btn.count() > 0 and await btn.is_enabled():
                            await btn.click(timeout=3000)
                    except Exception:  # noqa: BLE001
                        pass
                    return "email_code"
            except Exception:  # noqa: BLE001
                pass
            try:
                if await self._page.locator(CAPTCHA_SEL).count() > 0:
                    return "captcha"
            except Exception:  # noqa: BLE001
                pass
            await self._page.wait_for_timeout(step)
            waited += step
        return "unknown"

    async def start_credentials(
        self,
        *,
        account_id: int,
        account_name: str,
        platform: str,
        proxy_url: str | None,
        username: str,
        password: str,
    ) -> dict:
        async with self._lock:
            if self._context is not None:
                raise UploadError(
                    f"Уже открыт вход в аккаунт «{self._account_name}». "
                    f"Заверши его или отмени, прежде чем начинать новый."
                )
            from playwright.async_api import async_playwright

            proxy = parse_proxy(proxy_url) if proxy_url else None
            self._pw = await async_playwright().start()
            try:
                self._browser = await self._pw.chromium.launch(
                    **stealth_launch_kwargs(proxy, headless=True)
                )
                self._context = await self._browser.new_context(**stealth_context_kwargs())
                await self._context.add_init_script(STEALTH_INIT_JS)
                self._page = await self._context.new_page()
                url = LOGIN_URLS.get(platform, "about:blank")
                await self._page.goto(url, wait_until="load", timeout=60_000)
                await self._page.wait_for_timeout(2000)
                # при необходимости переключаемся на вкладку email/username
                try:
                    link = self._page.locator(EMAIL_TAB_SEL).first
                    if await link.count() > 0:
                        await link.click(timeout=3000)
                        await self._page.wait_for_timeout(800)
                except Exception:  # noqa: BLE001
                    pass
                await self._page.fill(USERNAME_SEL, username, timeout=20_000)
                await self._page.fill(PASSWORD_SEL, password, timeout=20_000)
                await self._page.locator(LOGIN_BTN_SEL).first.click(timeout=15_000)
                stage = await self._detect_stage()
            except Exception as e:  # noqa: BLE001
                await self._teardown()
                raise UploadError(f"Не удалось начать вход: {e}")

            self._account_id = account_id
            self._account_name = account_name
            return await self._stage_result(stage)

    async def submit_code(self, account_id: int, code: str) -> dict:
        async with self._lock:
            if self._context is None:
                raise UploadError("Активной сессии входа нет.")
            if self._account_id != account_id:
                raise UploadError(
                    f"Сессия входа открыта для другого аккаунта «{self._account_name}»."
                )
            try:
                await self._page.fill(CODE_INPUT_SEL, code, timeout=15_000)
                try:
                    await self._page.locator(VERIFY_BTN_SEL).first.click(timeout=8_000)
                except Exception:  # noqa: BLE001
                    await self._page.keyboard.press("Enter")
                stage = await self._detect_stage()
            except Exception as e:  # noqa: BLE001
                raise UploadError(f"Не удалось подтвердить код: {e}")
            return await self._stage_result(stage)

    async def _stage_result(self, stage: str) -> dict:
        """Формирует ответ; на done — отдаёт storage_state и закрывает сессию."""
        result: dict = {"stage": stage}
        if stage == "done":
            result["storage_state"] = await self._context.storage_state()
            await self._teardown()
        elif stage in ("captcha", "unknown"):
            result["screenshot"] = await self._screenshot_b64()
            result["message"] = (
                "TikTok показал проверку (капчу) или неожиданный шаг. "
                "Реши её вручную в антидетект-браузере и импортируй куки, "
                "либо попробуй позже."
            )
        return result

    async def cancel(self) -> None:
        async with self._lock:
            await self._teardown()

    async def _teardown(self) -> None:
        for obj, meth in (
            (self._context, "close"),
            (self._browser, "close"),
            (self._pw, "stop"),
        ):
            if obj is None:
                continue
            try:
                await getattr(obj, meth)()
            except Exception:  # noqa: BLE001
                pass
        self._pw = self._browser = self._context = self._page = None
        self._account_id = self._account_name = None


login_manager = LoginManager()
