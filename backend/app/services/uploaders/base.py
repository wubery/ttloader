"""Общие утилиты для загрузчиков: прокси, storage_state, результат."""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class ProxyConfig:
    """Прокси в формате, который понимает Playwright browser.launch(proxy=...)."""

    server: str                 # e.g. "http://host:port" или "socks5://host:port"
    username: str | None = None
    password: str | None = None

    def as_playwright(self) -> dict:
        d: dict = {"server": self.server}
        if self.username:
            d["username"] = self.username
        if self.password:
            d["password"] = self.password
        return d


def parse_proxy(proxy_url: str | None) -> ProxyConfig | None:
    """Разбирает http://user:pass@host:port или socks5://host:port в ProxyConfig."""
    if not proxy_url:
        return None
    p = urlparse(proxy_url)
    if not p.scheme or not p.hostname:
        raise ValueError(f"Некорректный proxy_url: {proxy_url}")
    # Chromium (движок Playwright) НЕ поддерживает авторизацию в SOCKS-прокси.
    if p.scheme.lower().startswith("socks") and (p.username or p.password):
        raise ValueError(
            "Chromium не поддерживает SOCKS5 с логином/паролем. "
            "Укажите прокси как http://user:pass@host:port "
            "(обычно тот же адрес провайдера работает и по HTTP)."
        )
    server = f"{p.scheme}://{p.hostname}"
    if p.port:
        server += f":{p.port}"
    return ProxyConfig(server=server, username=p.username, password=p.password)


# ---------- Маскировка браузера (anti-detect) ----------
# Приводим Playwright-Chromium к виду обычного десктопного Chrome реального
# пользователя. Один и тот же отпечаток применяем и при интерактивном входе,
# и при постинге — иначе куки, полученные «одним» браузером, палятся, когда
# постинг идёт «другим». Главный тормоз при входе — датацентровый IP прокси;
# маскировка снимает JS-признаки автоматизации, но IP не меняет.

STEALTH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
)

# Аргументы запуска: убираем инфобар/флаги автоматизации.
STEALTH_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=Translate",
    "--lang=ru-RU",
    "--no-sandbox",
]
# Убираем дефолтный флаг Playwright, который выдаёт автоматизацию.
STEALTH_IGNORE_DEFAULT_ARGS = ["--enable-automation"]

# JS, выполняемый до скриптов страницы: прячем navigator.webdriver и типичные
# признаки headless/automation.
STEALTH_INIT_JS = r"""
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU','ru','en-US','en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
window.chrome = window.chrome || { runtime: {} };
try {
  const oq = window.navigator.permissions && window.navigator.permissions.query;
  if (oq) {
    window.navigator.permissions.query = (p) => (
      p && p.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : oq(p)
    );
  }
} catch (e) {}
try {
  const gp = WebGLRenderingContext.prototype.getParameter;
  WebGLRenderingContext.prototype.getParameter = function (p) {
    if (p === 37445) return 'Intel Inc.';
    if (p === 37446) return 'Intel Iris OpenGL Engine';
    return gp.call(this, p);
  };
} catch (e) {}
"""


def stealth_launch_kwargs(proxy: "ProxyConfig | None", *, headless: bool) -> dict:
    """Готовые аргументы для chromium.launch(**...) с маскировкой."""
    kwargs: dict = {
        "headless": headless,
        "args": list(STEALTH_LAUNCH_ARGS),
        "ignore_default_args": list(STEALTH_IGNORE_DEFAULT_ARGS),
    }
    if proxy:
        kwargs["proxy"] = proxy.as_playwright()
    return kwargs


def stealth_context_kwargs(*, no_viewport: bool = False, timezone_id: str = "Europe/Moscow") -> dict:
    """Готовые аргументы для browser.new_context(**...) с маскировкой."""
    kwargs: dict = {
        "user_agent": STEALTH_USER_AGENT,
        "locale": "ru-RU",
        "timezone_id": timezone_id,
        "is_mobile": False,
        "has_touch": False,
        "extra_http_headers": {
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    }
    if not no_viewport:
        kwargs["viewport"] = {"width": 1360, "height": 900}
        kwargs["device_scale_factor"] = 1
    return kwargs


@dataclass
class UploadResult:
    ok: bool
    url: str | None = None
    log: str = ""
    error: str | None = None


class UploadError(RuntimeError):
    pass


def _norm_samesite(v) -> str:
    """Приводит sameSite к значению, которое принимает Playwright (Strict|Lax|None).
    Расширения экспортируют его как no_restriction/unspecified/lax/null — маппим."""
    if not v:
        return "Lax"
    s = str(v).strip().lower()
    if s in ("no_restriction", "none"):
        return "None"
    if s == "strict":
        return "Strict"
    return "Lax"  # lax, unspecified и всё неизвестное


def _normalize_cookie(c: dict) -> dict:
    same = _norm_samesite(c.get("sameSite"))
    out: dict = {
        "name": c.get("name"),
        "value": c.get("value", ""),
        "domain": c.get("domain", ""),
        "path": c.get("path", "/"),
        "httpOnly": bool(c.get("httpOnly", False)),
        # Cookies с SameSite=None обязаны быть Secure — иначе браузер их отбросит.
        "secure": bool(c.get("secure", False)) or same == "None",
        "sameSite": same,
    }
    exp = c.get("expires", c.get("expirationDate"))
    if exp is None or (isinstance(exp, (int, float)) and exp < 0):
        out["expires"] = -1
    else:
        try:
            out["expires"] = int(float(exp))
        except (TypeError, ValueError):
            out["expires"] = -1
    return out


def normalize_storage_state(data) -> dict:
    """Приводит импортированные куки (массив или storage_state) к валидному для
    Playwright storage_state: чистим sameSite/expires, оставляем только нужные поля."""
    if isinstance(data, dict):
        cookies = data.get("cookies", [])
        origins = data.get("origins", [])
    else:
        cookies = data
        origins = []
    norm = [_normalize_cookie(c) for c in cookies if isinstance(c, dict) and c.get("name")]
    return {"cookies": norm, "origins": origins}


def load_storage_state(cookies_path: str) -> dict:
    """Читает файл кук и нормализует его для Playwright (чинит старые импорты на лету)."""
    import json

    with open(cookies_path, encoding="utf-8") as f:
        return normalize_storage_state(json.load(f))


def require_cookies(cookies_path: str | None) -> str:
    if not cookies_path or not os.path.exists(cookies_path):
        raise UploadError(
            "Не найден файл кук аккаунта (storage_state). Импортируйте куки через панель "
            "(экспорт из браузера) прежде чем публиковать."
        )
    return cookies_path


async def proxy_egress_ip(proxy_url: str, timeout_ms: int = 20000) -> str:
    """Возвращает внешний IP, с которого виден трафик через данный прокси.

    Использует APIRequestContext Playwright (поддерживает http и socks5) — тот же
    сетевой стек, что и постинг, поэтому проверка отражает реальный выход аккаунта.
    """
    from playwright.async_api import async_playwright

    cfg = parse_proxy(proxy_url)
    if cfg is None:
        raise ValueError("Пустой proxy_url")

    async with async_playwright() as pw:
        ctx = await pw.request.new_context(proxy=cfg.as_playwright())
        try:
            resp = await ctx.get("https://api.ipify.org?format=text", timeout=timeout_ms)
            if not resp.ok:
                raise UploadError(f"Прокси ответил статусом {resp.status}")
            return (await resp.text()).strip()
        finally:
            await ctx.dispose()
