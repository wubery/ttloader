"""Постинг YouTube Shorts через YouTube Studio на сохранённых куках.

Загрузка идёт через studio.youtube.com (та же веб-форма, что и в браузере).
Видео с вертикальным соотношением и коротким хронометражем YouTube сам
классифицирует как Shorts; можно также добавить #Shorts в описание.

Прокси задаётся при запуске браузера — постоянный IP аккаунта.
Селекторы Studio вынесены в константы (правьте при изменениях UI).
"""
from __future__ import annotations

from .base import (
    STEALTH_INIT_JS,
    ProxyConfig,
    UploadError,
    UploadResult,
    load_storage_state,
    require_cookies,
    stealth_context_kwargs,
    stealth_launch_kwargs,
)

STUDIO_URL = "https://studio.youtube.com/"

FILE_INPUT = 'input[type="file"]'
CREATE_BUTTON = '#create-icon, ytcp-button#create-icon'
UPLOAD_MENU = 'tp-yt-paper-item:has-text("Upload video"), #text-item-0'
TITLE_BOX = '#title-textarea #textbox, ytcp-social-suggestions-textbox[id="title-textarea"] #textbox'
NEXT_BUTTON = '#next-button'
NOT_FOR_KIDS = 'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]'
PUBLIC_RADIO = 'tp-yt-paper-radio-button[name="PUBLIC"]'
DONE_BUTTON = '#done-button'


def upload_youtube(
    video_path: str,
    caption: str,
    cookies_path: str | None,
    proxy: ProxyConfig | None,
    headless: bool = True,
    log=lambda m: None,
) -> UploadResult:
    require_cookies(cookies_path)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise UploadError(
            "Playwright не установлен. Выполните: pip install playwright && playwright install chromium"
        ) from e

    lines: list[str] = []

    def _log(msg: str) -> None:
        lines.append(msg)
        log(msg)

    # Гарантируем тег Shorts
    title = (caption.splitlines()[0][:95] if caption else "Short")
    if "#shorts" not in caption.lower():
        caption = (caption + "\n#Shorts").strip()

    with sync_playwright() as p:
        if proxy:
            _log(f"Запуск браузера через прокси {proxy.server}")
        browser = p.chromium.launch(**stealth_launch_kwargs(proxy, headless=headless))
        try:
            context = browser.new_context(storage_state=load_storage_state(cookies_path), **stealth_context_kwargs())
            context.add_init_script(STEALTH_INIT_JS)
            page = context.new_page()
            _log("Открываю YouTube Studio…")
            page.goto(STUDIO_URL, wait_until="load", timeout=60_000)

            _log("Открываю форму загрузки…")
            page.click(CREATE_BUTTON, timeout=30_000)
            page.click(UPLOAD_MENU, timeout=15_000)

            file_input = page.locator(FILE_INPUT).first
            file_input.wait_for(state="attached", timeout=30_000)
            _log("Загружаю видеофайл…")
            file_input.set_input_files(video_path)

            # Заголовок
            try:
                tbox = page.locator(TITLE_BOX).first
                tbox.wait_for(state="visible", timeout=60_000)
                tbox.click()
                page.keyboard.press("Control+A")
                page.keyboard.press("Delete")
                tbox.type(title, delay=10)
                _log("Заголовок задан.")
            except Exception as e:  # noqa: BLE001
                _log(f"Не удалось задать заголовок: {e}")

            # «Не для детей»
            try:
                page.click(NOT_FOR_KIDS, timeout=10_000)
            except Exception:  # noqa: BLE001
                _log("Переключатель 'не для детей' не найден — пропускаю.")

            # Три шага «Далее»
            for i in range(3):
                try:
                    page.click(NEXT_BUTTON, timeout=15_000)
                    page.wait_for_timeout(1_000)
                except Exception:  # noqa: BLE001
                    _log(f"Кнопка 'Далее' #{i+1} не найдена — возможно, шаг пропущен.")

            # Публичность
            try:
                page.click(PUBLIC_RADIO, timeout=10_000)
            except Exception:  # noqa: BLE001
                _log("Не удалось выставить 'Public' — оставляю значение по умолчанию.")

            _log("Жду завершения обработки видео…")
            page.wait_for_timeout(5_000)

            _log("Публикую…")
            page.click(DONE_BUTTON, timeout=30_000)
            page.wait_for_timeout(6_000)

            _log("Готово: видео отправлено на публикацию.")
            return UploadResult(ok=True, url=None, log="\n".join(lines))
        except UploadError:
            raise
        except Exception as e:  # noqa: BLE001
            _log(f"Ошибка: {e}")
            return UploadResult(ok=False, log="\n".join(lines), error=str(e))
        finally:
            browser.close()
