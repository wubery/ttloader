"""Автоматический вход в аккаунт: логин, пароль и код из почты — без участия человека.

Отличие от login_session.py: тот держит async-браузер между HTTP-запросами и ждёт, пока
пользователь вручную введёт код. Здесь весь вход идёт одним фоновым потоком с
синхронным Playwright (как в uploaders/), а код панель достаёт из почты сама. Человек
нужен только если TikTok показал капчу.

Состояние каждой попытки лежит в памяти процесса — фронт опрашивает его раз в пару
секунд и рисует прогресс.
"""
from __future__ import annotations

import base64
import logging
import threading
from datetime import datetime

from ..config import settings
from ..db import SessionLocal
from ..models import Account
from . import mail
from .crypto import decrypt
from .login_session import (
    CAPTCHA_SEL,
    CODE_INPUT_SEL,
    EMAIL_TAB_SEL,
    ERROR_SEL,
    LOGIN_BTN_SEL,
    LOGIN_URLS,
    PASSWORD_SEL,
    SEND_CODE_SEL,
    USERNAME_SEL,
    VERIFY_BTN_SEL,
)
from .uploaders.base import (
    STEALTH_INIT_JS,
    UploadError,
    parse_proxy,
    stealth_context_kwargs,
    stealth_launch_kwargs,
)

log = logging.getLogger(__name__)

# Больше двух Chromium разом домашний сервер не тянет — пачка аккаунтов встанет в очередь.
_slots = threading.Semaphore(2)
_state: dict[int, dict] = {}
_state_lock = threading.Lock()
_manual_codes: dict[int, str] = {}   # код, введённый руками, если из почты не пришёл

# Ждём код долго: письмо может задержаться, а если почта не подключена — человеку
# нужно время сходить за кодом. Раньше окно было 150с, и введённый вручную код
# прилетал уже в закрытую сессию («активной сессии входа нет»).
CODE_WAIT_SECONDS = 600
MAIL_FAST_POLL_SECONDS = 180  # первые три минуты опрашиваем почту часто
CAPTCHA_WAIT_SECONDS = 600    # сколько держим браузер, пока человек решает капчу


def get_state(account_id: int) -> dict:
    with _state_lock:
        return dict(_state.get(account_id) or {"stage": "idle"})


def _set(account_id: int, stage: str, message: str | None = None, screenshot: str | None = None) -> None:
    with _state_lock:
        cur = _state.setdefault(account_id, {"started_at": datetime.now()})
        cur["stage"] = stage
        cur["message"] = message
        if screenshot is not None:
            cur["screenshot"] = screenshot
        if stage in ("done", "error"):
            cur["finished_at"] = datetime.now()
    log.info("Автовход #%s: %s — %s", account_id, stage, message or "")


def submit_manual_code(account_id: int, code: str) -> None:
    """Код, введённый руками — подхватит ожидающий поток."""
    _manual_codes[account_id] = code.strip()


def is_running(account_id: int) -> bool:
    return get_state(account_id).get("stage") in ("starting", "filling", "waiting_code", "submitting_code", "captcha")


def start(account_id: int) -> None:
    """Запускает вход в фоне. Повторный запуск, пока идёт предыдущий, игнорируется."""
    if is_running(account_id):
        raise UploadError("Вход в этот аккаунт уже идёт.")
    with _state_lock:
        _state[account_id] = {"stage": "starting", "message": "Готовлю браузер…", "started_at": datetime.now()}
    _manual_codes.pop(account_id, None)
    threading.Thread(target=_run, args=(account_id,), daemon=True).start()


def _run(account_id: int) -> None:
    db = SessionLocal()
    try:
        acc = db.get(Account, account_id)
        if acc is None:
            _set(account_id, "error", "Аккаунт не найден")
            return
        login = acc.tt_login
        password = decrypt(acc.tt_password_enc)
        if not login or not password:
            _set(account_id, "error", "Не заданы логин и пароль аккаунта")
            return
        if acc.platform.value not in LOGIN_URLS:
            _set(account_id, "error", f"Вход для платформы {acc.platform.value} не поддержан")
            return

        with _slots:
            _login_flow(acc, db, login, password)
    except UploadError as e:
        _set(account_id, "error", str(e))
        _remember_error(db, account_id, str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("Автовход #%s упал", account_id)
        _set(account_id, "error", f"{type(e).__name__}: {e}")
        _remember_error(db, account_id, str(e))
    finally:
        db.close()


def _remember_error(db, account_id: int, message: str) -> None:
    try:
        acc = db.get(Account, account_id)
        if acc is not None:
            acc.login_error = message[:500]
            db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def _login_flow(acc: Account, db, login: str, password: str) -> None:
    from playwright.sync_api import sync_playwright

    started = datetime.now()
    proxy = parse_proxy(acc.proxy_url) if acc.proxy_url else None

    with sync_playwright() as p:
        browser = p.chromium.launch(**stealth_launch_kwargs(proxy, headless=settings.headless))
        try:
            context = browser.new_context(**stealth_context_kwargs())
            context.add_init_script(STEALTH_INIT_JS)
            page = context.new_page()

            _set(acc.id, "filling", "Открываю страницу входа TikTok…")
            page.goto(LOGIN_URLS[acc.platform.value], wait_until="load", timeout=60_000)
            page.wait_for_timeout(2_000)

            try:  # вкладка «Email or username» есть не всегда
                tab = page.locator(EMAIL_TAB_SEL).first
                if tab.count() > 0:
                    tab.click(timeout=5_000)
                    page.wait_for_timeout(800)
            except Exception:  # noqa: BLE001
                pass

            _set(acc.id, "filling", "Ввожу логин и пароль…")
            _type_into(page, USERNAME_SEL, login)
            _type_into(page, PASSWORD_SEL, password)
            _click_login(page)

            stage = _detect(page)
            if stage == "unknown":
                # TikTok мог показать «неверный пароль» / «аккаунт не найден» — покажем это
                err = _form_error(page)
                if err:
                    raise UploadError(f"TikTok отклонил вход: {err}")
            if stage == "done":
                _finish(acc, db, context)
                return
            if stage == "captcha":
                _wait_captcha(acc, db, page, context)
                return

            # Код с почты
            code = _obtain_code(acc, db, started)
            if not code:
                raise UploadError(
                    "Не удалось получить код из письма. Введите его вручную "
                    "или проверьте подключение почты."
                )

            _set(acc.id, "submitting_code", "Ввожу код из письма…")
            _type_into(page, CODE_INPUT_SEL, code)
            try:
                page.locator(VERIFY_BTN_SEL).first.click(timeout=8_000)
            except Exception:  # noqa: BLE001
                page.keyboard.press("Enter")

            stage = _detect(page)
            if stage == "done":
                _finish(acc, db, context)
            elif stage == "captcha":
                _wait_captcha(acc, db, page, context)
            else:
                raise UploadError("TikTok не принял код или показал неизвестный шаг.")
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass


def _type_into(page, selector: str, text: str) -> None:
    """Печатает текст по символам вместо fill().

    fill() проставляет значение напрямую в DOM, а форма TikTok на React ждёт обычных
    событий ввода: без них кнопка входа остаётся disabled и клик по ней падает
    по таймауту (ровно это и происходило).
    """
    field = page.locator(selector).first
    field.click(timeout=20_000)
    # Чистим поле клавишами, а не fill(): проверено на живой форме — после fill()
    # кнопка входа остаётся disabled, а после посимвольного набора становится активной.
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.keyboard.type(text, delay=45)
    page.wait_for_timeout(300)


def _click_login(page, wait_ms: int = 15_000) -> None:
    """Ждёт, пока кнопка входа станет активной, и жмёт её."""
    btn = page.locator(LOGIN_BTN_SEL).first
    waited = 0
    while waited < wait_ms:
        try:
            if btn.is_enabled():
                btn.click(timeout=10_000)
                return
        except Exception:  # noqa: BLE001 — кнопка могла перерисоваться, пробуем ещё
            pass
        page.wait_for_timeout(500)
        waited += 500
    raise UploadError(
        "Кнопка входа осталась неактивной — TikTok не принял введённые данные "
        "(проверьте логин и пароль) или изменил форму входа."
    )


def _form_error(page) -> str | None:
    """Текст ошибки формы («неверный пароль», «аккаунт не найден» и т.п.)."""
    try:
        texts = page.locator(ERROR_SEL).all_inner_texts()
    except Exception:  # noqa: BLE001
        return None
    for t in texts:
        t = (t or "").strip()
        if 3 < len(t) < 200:
            return t
    return None


def _detect(page, timeout_ms: int = 30_000) -> str:
    """done | email_code | captcha | unknown — та же логика, что в ручном входе."""
    waited = 0
    step = 1_500
    while waited < timeout_ms:
        url = page.url or ""
        if "/login" not in url and "/signup" not in url:
            return "done"
        try:
            if page.locator(CODE_INPUT_SEL).count() > 0:
                try:  # если рядом кнопка «отправить код» — жмём, чтобы письмо ушло
                    btn = page.locator(SEND_CODE_SEL).first
                    if btn.count() > 0 and btn.is_enabled():
                        btn.click(timeout=3_000)
                except Exception:  # noqa: BLE001
                    pass
                return "email_code"
        except Exception:  # noqa: BLE001
            pass
        try:
            if page.locator(CAPTCHA_SEL).count() > 0:
                return "captcha"
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(step)
        waited += step
    return "unknown"


def _obtain_code(acc: Account, db, started: datetime) -> str | None:
    """Ждёт код: сначала из почты, параллельно принимая ручной ввод."""
    minutes = CODE_WAIT_SECONDS // 60
    if not acc.mail_connected:
        _set(acc.id, "waiting_code", f"Почта не подключена — введите код из письма вручную (жду {minutes} мин).")
    else:
        _set(acc.id, "waiting_code", f"Жду письмо с кодом (до {minutes} мин)…")

    waited = 0
    next_mail_check = 0
    while waited < CODE_WAIT_SECONDS:
        manual = _manual_codes.pop(acc.id, None)
        if manual:
            return manual
        if acc.mail_connected and waited >= next_mail_check:
            try:
                code = mail.find_login_code(acc, db, since=started)
                if code:
                    return code
            except mail.MailError as e:
                _set(acc.id, "waiting_code", f"Почта недоступна ({e}). Введите код вручную.")
            # первые минуты проверяем часто, дальше реже — письмо обычно приходит сразу
            next_mail_check = waited + (5 if waited < MAIL_FAST_POLL_SECONDS else 20)
        _sleep(2)
        waited += 2
    return _manual_codes.pop(acc.id, None)


def _wait_captcha(acc: Account, db, page, context) -> None:
    """Капчу автоматически не решаем — показываем скриншот и ждём решения человека."""
    shot = _screenshot(page)
    _set(
        acc.id,
        "captcha",
        "TikTok показал капчу. Решите её в антидетект-браузере через тот же прокси и "
        "импортируйте куки, либо попробуйте позже.",
        screenshot=shot,
    )
    waited = 0
    while waited < CAPTCHA_WAIT_SECONDS:
        _sleep(5)
        waited += 5
        try:
            url = page.url or ""
            if "/login" not in url and "/signup" not in url:
                _finish(acc, db, context)
                return
        except Exception:  # noqa: BLE001
            return
    _set(acc.id, "error", "Капча не решена за 10 минут — вход отменён.")


def _finish(acc: Account, db, context) -> None:
    """Сохраняет куки — тем же способом, что и ручной вход."""
    from ..routers.accounts import _apply_saved_state

    state = context.storage_state()
    _apply_saved_state(acc, db, state)
    acc.last_login_at = datetime.now()
    acc.login_error = None
    db.commit()
    _set(acc.id, "done", "Вход выполнен, куки сохранены.")


def _screenshot(page) -> str | None:
    try:
        return "data:image/png;base64," + base64.b64encode(page.screenshot(type="png")).decode()
    except Exception:  # noqa: BLE001
        return None


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)
