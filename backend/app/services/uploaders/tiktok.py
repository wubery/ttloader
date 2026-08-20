"""Постинг в TikTok через веб-загрузчик (tiktok.com/upload) на сохранённых куках.

Логика повторяет проверенный подход social-auto-upload / wkaisertexas/tiktok-uploader:
куки «убеждают» TikTok, что мы залогинены, а сам upload идёт через официальную
веб-форму. Прокси задаётся при запуске браузера — IP аккаунта остаётся постоянным.

ВАЖНО: селекторы TikTok периодически меняются. Они вынесены в константы ниже —
при поломке правьте здесь. Функция устойчиво ждёт появления элементов и пишет
подробный лог, который виден в панели.
"""
from __future__ import annotations

import os

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

# Ответы этих эндпоинтов = реальное подтверждение публикации. Только по ним
# считаем задачу успешной: клик по кнопке сам по себе ничего не доказывает.
PUBLISH_API_HINTS = ("/aweme/v1/web/aweme/post", "/project/post", "/web/project/publish", "/upload/publish")

MAX_UPLOAD_WAIT_MS = 10 * 60_000   # заливка большого видео через прокси идёт минутами
MAX_PUBLISH_WAIT_MS = 90_000       # ожидание подтверждения после клика «Опубликовать»


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

            # Ответы API публикации — единственное надёжное доказательство, что пост ушёл.
            publish_responses: list[tuple[int, str, str]] = []
            page.on("response", lambda r: _remember_publish(r, publish_responses))

            _log("Открываю страницу загрузки TikTok…")
            page.goto(UPLOAD_URL, wait_until="load", timeout=60_000)

            # Протухшие куки TikTok просто редиректит на /login. Раньше это не
            # распознавалось: код 105с искал поле загрузки и жаловался на вёрстку.
            _assert_logged_in(page)

            # Поле загрузки TikTok Studio появляется не сразу — ждём до 60с.
            _log("Жду появления поля загрузки (TikTok дорисовывает его не сразу)…")
            file_input = _find_file_input(page, timeout_ms=60_000, log=_log)
            if file_input is None:
                _log("На основной странице не нашлось — пробую классическую /upload…")
                page.goto(UPLOAD_URL_FALLBACK, wait_until="load", timeout=60_000)
                _assert_logged_in(page)
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

            # Ждём РЕАЛЬНОГО завершения заливки, а не фиксированные 10 секунд:
            # через прокси большое видео льётся минутами, и клик по неактивной
            # кнопке «Опубликовать» раньше молча ничего не делал.
            _wait_upload_complete(page, log=_log, timeout_ms=MAX_UPLOAD_WAIT_MS)

            _log("Публикую…")
            # На случай, если диалог/обучающий оверлей появился/вернулся — убираем перед кликом.
            _dismiss_blocking_modal(page, log=_log, timeout_ms=4_000)
            _kill_overlays(page, log=_log)
            _click_post(page, log=_log)

            # Клик ничего не доказывает — ждём подтверждения от самого TikTok.
            ok, detail = _wait_publish_confirmed(
                page, publish_responses, log=_log, timeout_ms=MAX_PUBLISH_WAIT_MS
            )
            if not ok:
                shot = _screenshot(page, "publish_unconfirmed", log=_log)
                raise UploadError(
                    f"TikTok не подтвердил публикацию: {detail}. Видео могло не уйти — "
                    f"проверьте «Контент» в TikTok Studio."
                    + (f" Скриншот: {shot}" if shot else "")
                )

            _log(f"Публикация подтверждена TikTok ({detail}).")
            return UploadResult(ok=True, url=_find_posted_url(publish_responses), log="\n".join(lines))
        except UploadError:
            raise
        except Exception as e:  # noqa: BLE001
            _log(f"Ошибка: {e}")
            return UploadResult(ok=False, log="\n".join(lines), error=str(e))
        finally:
            browser.close()


def _assert_logged_in(page) -> None:
    """Ловит редирект на страницу входа — значит, куки протухли."""
    url = (page.url or "").lower()
    if "/login" in url or "/signup" in url:
        raise UploadError(
            "TikTok перекинул на страницу входа — куки аккаунта недействительны. "
            "Переимпортируйте куки (снимать их нужно через тот же прокси: сессия привязана к IP)."
        )


def _remember_publish(response, sink: list) -> None:
    """Складывает ответы эндпоинтов публикации — по ним проверяем факт поста."""
    try:
        url = response.url
        if not any(h in url for h in PUBLISH_API_HINTS):
            return
        body = ""
        try:
            body = response.text()[:2000]
        except Exception:  # noqa: BLE001 — тело может быть недоступно
            pass
        sink.append((response.status, url, body))
    except Exception:  # noqa: BLE001
        pass


def _upload_state(page) -> dict:
    """Состояние страницы: активна ли кнопка публикации и виден ли прогресс заливки."""
    try:
        return page.evaluate(
            """() => {
                const btns = [...document.querySelectorAll('button')];
                const post = btns.find(b => b.getAttribute('data-e2e') === 'post_video_button')
                    || btns.find(b => /^(post|опубликовать|публиковать)$/i.test((b.innerText||'').trim()));
                const body = document.body ? (document.body.innerText || '') : '';
                const pct = body.match(/(\\d{1,3})\\s?%/);
                return {
                    hasPost: !!post,
                    postEnabled: !!post && !post.disabled
                        && post.getAttribute('aria-disabled') !== 'true'
                        && !/disabled/i.test(post.className || ''),
                    percent: pct ? parseInt(pct[1], 10) : null,
                    uploading: /uploading|загрузка|загружается|processing|обработ/i.test(body),
                    hasPreview: !!document.querySelector('video'),
                };
            }"""
        )
    except Exception:  # noqa: BLE001
        return {}


def _wait_upload_complete(page, log=lambda m: None, timeout_ms: int = MAX_UPLOAD_WAIT_MS) -> None:
    """Ждёт, пока видео дольётся и кнопка публикации станет активной.

    Раньше здесь стояли фиксированные 10 секунд: при заливке через прокси этого
    почти всегда мало, кнопка оставалась неактивной, а клик по ней ничего не делал.
    """
    log("Жду завершения заливки видео на серверы TikTok…")
    waited = 0
    step = 3_000
    last_note = ""
    while waited < timeout_ms:
        st = _upload_state(page)
        if st.get("postEnabled"):
            log(f"Заливка завершена за {waited // 1000}с — кнопка публикации активна.")
            return
        note = f"{st.get('percent')}%" if st.get("percent") is not None else (
            "идёт заливка" if st.get("uploading") else "жду готовности"
        )
        if note != last_note:
            log(f"…{note} ({waited // 1000}с)")
            last_note = note
        page.wait_for_timeout(step)
        waited += step
    spent = f"{timeout_ms // 60_000} мин" if timeout_ms >= 60_000 else f"{timeout_ms // 1000}с"
    raise UploadError(
        f"Видео не долилось за {spent}: кнопка публикации так и не стала активной. "
        "Обычно это медленный прокси или слишком большой файл."
    )


def _click_post(page, log=lambda m: None) -> None:
    """Жмёт «Опубликовать», не подменяя неудачу принудительным кликом.

    force=True обходит проверки Playwright и по неактивной кнопке просто ничего
    не делает — раньше именно так «успешная» задача не публиковала ничего.
    """
    post_btn = page.locator(POST_BUTTON).first
    post_btn.wait_for(state="visible", timeout=30_000)
    for attempt in (1, 2, 3):
        st = _upload_state(page)
        if not st.get("postEnabled"):
            log(f"Кнопка публикации неактивна (попытка {attempt}) — жду…")
            page.wait_for_timeout(5_000)
            continue
        try:
            post_btn.click(timeout=15_000)
            log("Кнопка «Опубликовать» нажата.")
            return
        except Exception as e:  # noqa: BLE001 — клик перехвачен: чистим оверлеи и пробуем снова
            log(f"Клик не прошёл ({type(e).__name__}) — убираю перекрытия и повторяю.")
            _kill_overlays(page, log=log)
            _dismiss_blocking_modal(page, log=log, timeout_ms=3_000)
    raise UploadError(
        "Не удалось нажать «Опубликовать»: кнопка осталась неактивной или её перекрывает "
        "элемент TikTok."
    )


def _wait_publish_confirmed(page, responses: list, log=lambda m: None, timeout_ms: int = MAX_PUBLISH_WAIT_MS):
    """Ждёт доказательства публикации: ответ API, уход со страницы загрузки или тост."""
    waited = 0
    step = 2_000
    while waited < timeout_ms:
        for status, url, body in list(responses):
            if status == 200 and ('"status_code":0' in body or '"status_code": 0' in body or not body):
                return True, f"ответ {url.split('?')[0]}"
            if status == 200 and '"status_code"' in body:
                return False, f"TikTok вернул ошибку в ответе: {body[:200]}"
        try:
            cur = (page.url or "").lower()
            if "/upload" not in cur and ("/content" in cur or "/tiktokstudio" in cur):
                return True, f"страница сменилась на {cur}"
            done = page.evaluate(
                """() => /видео опубликовано|ваше видео|posted|published|успешно/i
                    .test(document.body ? document.body.innerText : '')"""
            )
            if done:
                return True, "TikTok показал сообщение об успешной публикации"
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(step)
        waited += step
    return False, f"за {timeout_ms // 1000}с не пришло ни ответа API, ни перехода на «Контент»"


def _find_posted_url(responses: list) -> str | None:
    """Достаёт id опубликованного видео из ответа API, если он там есть."""
    import re

    for _status, _url, body in responses:
        m = re.search(r'"(?:aweme_id|item_id|video_id)"\s*:\s*"?(\d{6,})"?', body or "")
        if m:
            return f"https://www.tiktok.com/video/{m.group(1)}"
    return None


def _screenshot(page, tag: str, log=lambda m: None) -> str | None:
    """Скриншот в каталог данных — чтобы было что посмотреть при разборе."""
    import time as _time

    try:
        from ...config import settings

        path = os.path.join(settings.output_dir, f"tiktok_{tag}_{int(_time.time())}.png")
        page.screenshot(path=path, full_page=False)
        log(f"Сохранил скриншот страницы: {os.path.basename(path)}")
        return os.path.basename(path)
    except Exception:  # noqa: BLE001
        return None


def _dismiss_blocking_modal(page, log=lambda m: None, timeout_ms: int = 10_000) -> bool:
    """Закрывает всплывающую модалку, перехватывающую клики.

    После загрузки видео TikTok показывает диалог «Включить автоматическую проверку
    контента?» (Отмена/Включить), который блокирует и поле описания, и кнопку Post.
    Жмём нейтральную «Отмена» (Cancel) — это не отменяет загрузку, только закрывает
    диалог. Тексты локализованы, поэтому перебираем и RU, и EN варианты.
    """
    from playwright.sync_api import Error as PWError

    # Порядок важен: сначала нейтральные ответы. «Включить» (Enable) — крайний
    # случай: он что-то включает в аккаунте, поэтому жмём его последним и с меткой в логе.
    labels = ["Отмена", "Cancel", "Не сейчас", "Not now", "OK", "Включить", "Enable"]
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
