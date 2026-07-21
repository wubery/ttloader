"""Постинг в TikTok через веб-загрузчик (tiktok.com/upload) на сохранённых куках.

Логика повторяет проверенный подход social-auto-upload / wkaisertexas/tiktok-uploader:
куки «убеждают» TikTok, что мы залогинены, а сам upload идёт через официальную
веб-форму. Прокси задаётся при запуске браузера — IP аккаунта остаётся постоянным.

ВАЖНО: селекторы TikTok периодически меняются. Они вынесены в константы ниже —
при поломке правьте здесь. Функция устойчиво ждёт появления элементов и пишет
подробный лог, который виден в панели.
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

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=upload"
UPLOAD_URL_FALLBACK = "https://www.tiktok.com/upload?lang=en"

# Селекторы (могут потребовать актуализации)
FILE_INPUT = 'input[type="file"]'
CAPTION_EDITOR = 'div[contenteditable="true"], .public-DraftEditor-content'
POST_BUTTON = 'button[data-e2e="post_video_button"], button:has-text("Post")'


def upload_tiktok(
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

    with sync_playwright() as p:
        if proxy:
            _log(f"Запуск браузера через прокси {proxy.server}")
        browser = p.chromium.launch(**stealth_launch_kwargs(proxy, headless=headless))
        try:
            context = browser.new_context(storage_state=load_storage_state(cookies_path), **stealth_context_kwargs())
            context.add_init_script(STEALTH_INIT_JS)
            page = context.new_page()
            _log("Открываю страницу загрузки TikTok…")
            page.goto(UPLOAD_URL, wait_until="load", timeout=60_000)

            # Поле загрузки TikTok Studio появляется не сразу — ждём до 60с.
            _log("Жду появления поля загрузки (TikTok дорисовывает его не сразу)…")
            file_input = _find_file_input(page, timeout_ms=60_000, log=_log)
            if file_input is None:
                _log("На основной странице не нашлось — пробую классическую /upload…")
                page.goto(UPLOAD_URL_FALLBACK, wait_until="load", timeout=60_000)
                file_input = _find_file_input(page, timeout_ms=45_000, log=_log)
            if file_input is None:
                raise UploadError(
                    "Не найдено поле загрузки файла даже после долгого ожидания. "
                    "Возможно, аккаунт ограничен в загрузке или изменилась вёрстка TikTok."
                )

            _log("Загружаю видеофайл…")
            file_input.set_input_files(video_path)

            # Ждём обработки видео (появление превью/прогресса)
            page.wait_for_timeout(8_000)

            # TikTok показывает диалог «Включить автоматическую проверку контента?» —
            # закрываем, иначе он перехватывает клики по описанию и кнопке Post.
            _dismiss_blocking_modal(page, log=_log, timeout_ms=12_000)
            _kill_overlays(page, log=_log)

            if caption:
                _log("Ввожу описание…")
                try:
                    editor = page.locator(CAPTION_EDITOR).first
                    editor.click(timeout=15_000)
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Delete")
                    editor.type(caption, delay=15)
                except Exception as e:  # noqa: BLE001
                    _log(f"Не удалось ввести описание автоматически: {e}")

            # Дожидаемся окончания загрузки видео на сервер перед публикацией
            _log("Жду завершения обработки видео на сервере…")
            page.wait_for_timeout(10_000)

            _log("Публикую…")
            # На случай, если диалог/обучающий оверлей появился/вернулся — убираем перед кликом.
            _dismiss_blocking_modal(page, log=_log, timeout_ms=4_000)
            _kill_overlays(page, log=_log)
            post_btn = page.locator(POST_BUTTON).first
            post_btn.wait_for(state="visible", timeout=30_000)
            try:
                post_btn.click(timeout=15_000)
            except Exception:  # noqa: BLE001 — что-то ещё перехватило клик, убираем оверлеи и жмём принудительно
                _kill_overlays(page, log=_log)
                _dismiss_blocking_modal(page, log=_log, timeout_ms=3_000)
                post_btn.click(force=True, timeout=15_000)

            page.wait_for_timeout(8_000)
            _log("Готово: запрос на публикацию отправлен.")
            return UploadResult(ok=True, url=None, log="\n".join(lines))
        except UploadError:
            raise
        except Exception as e:  # noqa: BLE001
            _log(f"Ошибка: {e}")
            return UploadResult(ok=False, log="\n".join(lines), error=str(e))
        finally:
            browser.close()


def _dismiss_blocking_modal(page, log=lambda m: None, timeout_ms: int = 10_000) -> bool:
    """Закрывает всплывающую модалку, перехватывающую клики.

    После загрузки видео TikTok показывает диалог «Включить автоматическую проверку
    контента?» (Отмена/Включить), который блокирует и поле описания, и кнопку Post.
    Жмём нейтральную «Отмена» (Cancel) — это не отменяет загрузку, только закрывает
    диалог. Тексты локализованы, поэтому перебираем и RU, и EN варианты.
    """
    from playwright.sync_api import Error as PWError

    labels = ["Отмена", "Cancel", "Включить", "Enable", "Не сейчас", "Not now", "OK"]
    waited = 0
    while waited < timeout_ms:
        for label in labels:
            try:
                btn = page.locator(
                    f'div[data-floating-ui-portal] button:has-text("{label}")'
                ).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=3_000, no_wait_after=True)
                    log(f"Закрыл всплывающий диалог кнопкой «{label}».")
                    page.wait_for_timeout(800)
                    return True
            except PWError:
                continue
        page.wait_for_timeout(1_000)
        waited += 1_000
    return False


def _kill_overlays(page, log=lambda m: None) -> None:
    """Удаляет обучающие оверлеи (react-joyride tour), перехватывающие клики.

    TikTok Studio показывает гайд-тур поверх страницы; его прозрачная накладка
    ловит все клики. Он чисто информационный — сносим его из DOM (не зависит от
    языка/шагов), вместе с прочими подобными оверлеями.
    """
    try:
        # ВАЖНО: не удаляем узлы (.remove ломает React-приложение TikTok и вызывает
        # «Произошла ошибка», блокируя публикацию). Делаем оверлей прозрачным для
        # кликов и невидимым, не трогая структуру DOM.
        n = page.evaluate(
            """() => {
              let n = 0;
              const sel = '#react-joyride-portal, .react-joyride__overlay, .react-joyride__spotlight';
              document.querySelectorAll(sel).forEach(e => {
                e.style.pointerEvents = 'none';
                e.style.visibility = 'hidden';
                n++;
              });
              return n;
            }"""
        )
        if n:
            log(f"Отключил обучающий оверлей TikTok (joyride), элементов: {n}.")
    except Exception:  # noqa: BLE001
        pass


def _find_file_input(page, timeout_ms: int = 60_000, log=lambda m: None):
    """Ищет input[type=file] на странице и во всех фреймах, опрашивая до timeout_ms.

    TikTok Studio дорисовывает поле загрузки не сразу — оно появляется через
    15–30с после загрузки страницы, поэтому ждём с запасом, а не 15с.
    """
    from playwright.sync_api import Error as PWError

    waited = 0
    step = 2_000
    while waited < timeout_ms:
        # основная страница
        try:
            loc = page.locator(FILE_INPUT).first
            if loc.count() > 0:
                return loc
        except PWError:
            pass
        # все фреймы
        for frame in page.frames:
            try:
                floc = frame.locator(FILE_INPUT).first
                if floc.count() > 0:
                    return floc
            except PWError:
                continue
        page.wait_for_timeout(step)
        waited += step
        if waited % 10_000 == 0:
            log(f"…жду поле загрузки ({waited // 1000}с)")
    return None
