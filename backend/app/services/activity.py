"""Проверка активности: аккаунты смотрят ленту и лайкают посты друг друга.

Зачем: куки TikTok живут ровно столько, сколько аккаунт выглядит используемым.
Профиль, который только публикует и ничего не смотрит, отваливается первым, и
узнаём мы об этом в момент неудачной публикации. Поэтому аккаунты сами заходят в
ленту в случайное время и на случайный срок, а для подтверждения активности
ставят лайки — но ТОЛЬКО постам других аккаунтов этой же панели.

Ограничение «только свои» держится не на намерении, а на факте: перед кликом
сверяется фактический адрес открытой страницы (`video_url_allowed`). В ленте
лайков нет вовсе — там нечем случайно лайкнуть чужое.
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

# Ник в адресе профиля/видео: TikTok разрешает буквы, цифры, точку и подчёркивание
HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,64}$")
VIDEO_PATH_RE = re.compile(r"^/@([A-Za-z0-9._]{1,64})/video/(\d+)/?$")
TIKTOK_HOSTS = {"tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com"}

FEED_URL = "https://www.tiktok.com/foryou"
# В студии профиль всегда свой — в ленте же полно чужих ссылок
STUDIO_URL = "https://www.tiktok.com/tiktokstudio"
PROFILE_URL = "https://www.tiktok.com/@{handle}"

# Сколько первых постов профиля считаем «свежими» и выбираем из них
TOP_POSTS = 5


# ---------------------------------------------------------------- чистая логика


def parse_handle(value: str | None) -> str | None:
    """«@Name», «https://tiktok.com/@Name», «Name» → «name». Мусор → None."""
    if not value:
        return None
    raw = value.strip()
    if "tiktok.com" in raw.lower():
        path = urlparse(raw if "//" in raw else f"https://{raw}").path
        raw = path.strip("/").split("/")[0]
    raw = raw.lstrip("@").strip()
    if not raw or not HANDLE_RE.match(raw):
        return None
    return raw.lower()


def video_url_allowed(url: str | None, allowed_handles: set[str] | frozenset[str]) -> bool:
    """Барьер: это точно пост аккаунта нашей панели?

    Проверяется ровно то, что открыто в браузере: домен TikTok, путь строго вида
    /@ник/video/<цифры> и ник из белого списка. Всё остальное — реклама в ленте,
    чужой профиль, редирект, похожий ник вроде «mine.evil.com» — отбивается.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if (parsed.hostname or "").lower() not in TIKTOK_HOSTS:
        return False
    m = VIDEO_PATH_RE.match(parsed.path or "")
    if not m:
        return False
    allowed = {h.lower() for h in allowed_handles if h}
    return m.group(1).lower() in allowed


def eligible_for_likes(accounts) -> list:
    """Кто вообще участвует в лайках: активен, с куками, с ником и включён."""
    return [
        a for a in accounts
        if a.active and getattr(a, "likes_on", False)
        and getattr(a, "has_cookies", False) and parse_handle(getattr(a, "tiktok_handle", None))
    ]


def pick_like_pairs(accounts, recent_pairs, count: int, rnd: random.Random) -> list[tuple]:
    """Случайные пары «кто лайкает → кого».

    Никто не лайкает сам себя; повтор адресата из `recent_pairs` (кулдаун) не
    берётся; один аккаунт за прогон лайкает не больше одного раза — иначе всплеск
    активности выдаёт ферму.
    """
    pool = eligible_for_likes(accounts)
    if len(pool) < 2 or count <= 0:
        return []

    likers = pool[:]
    rnd.shuffle(likers)
    pairs: list[tuple] = []
    chosen: set[tuple[int, int]] = set()
    for liker in likers:
        if len(pairs) >= count:
            break
        targets = [t for t in pool
                   if t.id != liker.id and (liker.id, t.id) not in recent_pairs
                   # Взаимность в одном прогоне — самый заметный след фермы: два
                   # аккаунта лайкают друг друга с разницей в минуты. Через сутки
                   # ответный лайк уже выглядит обычно, поэтому ограничение живёт
                   # только внутри прогона, а не на весь кулдаун.
                   and (t.id, liker.id) not in chosen]
        if not targets:
            continue
        target = rnd.choice(targets)
        chosen.add((liker.id, target.id))
        pairs.append((liker, target))
    return pairs


def due_for_activity(accounts, now: datetime) -> list:
    """Кому пора смотреть ленту (время разыграно заранее и уже наступило)."""
    return [
        a for a in accounts
        if a.active and getattr(a, "activity_on", False) and getattr(a, "has_cookies", False)
        and (getattr(a, "next_activity_at", None) is None or a.next_activity_at <= now)
    ]


def fit_into_window(moment: datetime, hour_from: int, hour_to: int,
                    rnd: random.Random) -> datetime:
    """Сдвигает время в разрешённое окно суток.

    hour_from >= hour_to трактуется как «круглосуточно»: так пользователь может
    отключить окно, не заводя отдельной галки.
    """
    if hour_from >= hour_to:
        return moment
    if hour_from <= moment.hour < hour_to:
        return moment
    day = moment.date() if moment.hour < hour_from else (moment + timedelta(days=1)).date()
    start = datetime.combine(day, datetime.min.time()).replace(hour=hour_from)
    # Точка внутри ВСЕГО окна, а не в его начале. Раньше сдвиг был 0–90 минут, и
    # всё, что в окно не попало, сваливалось в первый его час: у панели с десятком
    # аккаунтов получался ежедневный всплеск активности в одно и то же время —
    # ровно тот признак фермы, от которого остальное расписание и уводит.
    span_minutes = (hour_to - hour_from) * 60
    return start + timedelta(minutes=rnd.randint(0, max(0, span_minutes - 1)))


def next_activity_time(now: datetime, *, per_day_min: int, per_day_max: int,
                       hour_from: int, hour_to: int, rnd: random.Random) -> datetime:
    """Когда аккаунт пойдёт в ленту в следующий раз.

    Сутки делятся на случайное число сессий, интервал берётся с разбросом ±40% —
    ровное расписание у десятка аккаунтов выглядит как ферма.
    """
    lo, hi = sorted((max(1, per_day_min), max(1, per_day_max)))
    sessions = rnd.randint(lo, hi)
    base_minutes = 24 * 60 / sessions
    jitter = rnd.uniform(0.6, 1.4)
    moment = now + timedelta(minutes=base_minutes * jitter)
    return fit_into_window(moment, hour_from, hour_to, rnd)


def next_likes_time(now: datetime, *, interval_min: int, interval_max: int,
                    rnd: random.Random) -> datetime:
    lo, hi = sorted((max(1, interval_min), max(1, interval_max)))
    return now + timedelta(minutes=rnd.randint(lo, hi))


def session_seconds(*, seconds_min: int, seconds_max: int, rnd: random.Random) -> int:
    lo, hi = sorted((max(5, seconds_min), max(5, seconds_max)))
    return rnd.randint(lo, hi)


# --------------------------------------------------------------- разгон
# Свежий аккаунт, который с первого же дня листает ленту по расписанию взрослого,
# выглядит хуже, чем молчащий: живой человек раскачивается постепенно. Поэтому
# нагрузка растёт линейно от доли `start_percent` в первый день до полной к
# последнему дню разгона, а лайки включаются не сразу.


def warmup_day(started_at: datetime | None, now: datetime) -> int:
    """Какой это день прогрева, считая первый за единицу."""
    if started_at is None:
        return 1
    return max(1, (now.date() - started_at.date()).days + 1)


def warmup_factor(started_at: datetime | None, now: datetime, *, days: int,
                  start_percent: int, enabled: bool = True) -> float:
    """Доля полной нагрузки для этого аккаунта: от start_percent до 1.0."""
    if not enabled or days <= 1:
        return 1.0
    day = warmup_day(started_at, now)
    if day >= days:
        return 1.0
    start = min(100, max(1, start_percent)) / 100
    return start + (1.0 - start) * (day - 1) / (days - 1)


def scale_range(lo: int, hi: int, factor: float, *, floor: int = 1) -> tuple[int, int]:
    """Сжимает диапазон настроек по коэффициенту разгона, не обнуляя его."""
    lo, hi = sorted((lo, hi))
    return max(floor, round(lo * factor)), max(floor, round(hi * factor))


def likes_allowed(started_at: datetime | None, now: datetime, *, after_day: int,
                  enabled: bool = True) -> bool:
    """Дорос ли аккаунт до лайков.

    Первые дни аккаунт только смотрит: лайки у профиля без истории просмотров —
    отдельный повод для подозрений.
    """
    if not enabled:
        return True
    return warmup_day(started_at, now) >= max(1, after_day)


# Дольше этого на одном ролике не задерживаемся, даже если он длинный: сессия
# должна успеть охватить несколько роликов, иначе «просмотр ленты» вырождается в
# один экран.
MAX_DWELL_SECONDS = 120.0


def watch_plan(duration: float, rnd: random.Random) -> tuple[float, str]:
    """Сколько секунд смотреть ролик и как это назвать в журнале.

    Раскладка приближена к живому зрителю: часть роликов бросают на первых
    секундах, большинство досматривают, некоторые уходят на второй круг. Это не
    украшение: доля досмотров — главный сигнал вовлечённости, который TikTok
    считает по аккаунту. Прежняя версия держала на каждом ролике одинаковые 2–8
    секунд независимо от его длины, то есть не досматривала вообще ничего и
    полезного сигнала не давала совсем.
    """
    if duration <= 0:            # длительность ещё не подгрузилась
        return rnd.uniform(4.0, 12.0), "без длительности"
    roll = rnd.random()
    if roll < 0.25:
        return duration * rnd.uniform(0.15, 0.45), "бросил"
    if roll < 0.80:
        return duration * rnd.uniform(0.90, 1.05), "досмотрел"
    return duration * rnd.uniform(1.6, 2.6), "пересмотрел"


# ------------------------------------------------------------------- браузер
# Отпечаток берём тот же, что у постинга и входа: куки, снятые «одним» браузером,
# палятся, когда ими ходит «другой».

# Состояние лайка: у TikTok нет надёжного aria-атрибута, поэтому смотрим ещё и на
# фирменный красный цвет залитого сердца.
LIKE_STATE_JS = """() => {
    const btn = document.querySelector('[data-e2e="browse-like-icon"], [data-e2e="like-icon"]');
    if (!btn) return 'not_found';
    if (btn.getAttribute('aria-pressed') === 'true') return 'liked';
    const svg = btn.querySelector('svg');
    const html = ((svg && svg.outerHTML) || '').toLowerCase();
    const red = html.includes('#fe2c55') || html.includes('rgba(254, 44, 85')
        || html.includes('rgb(254, 44, 85');
    return red ? 'liked' : 'not_liked';
}"""

LIKE_CLICK_JS = """() => {
    const btn = document.querySelector('[data-e2e="browse-like-icon"], [data-e2e="like-icon"]');
    if (!btn) return false;
    (btn.closest('button') || btn).click();
    return true;
}"""

# Ссылка на собственный профиль в шапке — из неё берём ник аккаунта
# Ник берём ТОЛЬКО из состояния приложения и навигации. Раньше тут стоял перебор
# любых ссылок вида /@…, а на странице ленты это авторы чужих роликов: сработай
# такой поиск — панель записала бы чужой ник как свой и внесла его в белый список
# для лайков. Поэтому произвольные ссылки не рассматриваются вовсе.
OWN_PROFILE_JS = r"""() => {
    // 1) состояние, которое TikTok кладёт в страницу для гидрации
    const fromState = () => {
        const ids = ['__UNIVERSAL_DATA_FOR_REHYDRATION__', 'SIGI_STATE'];
        for (const id of ids) {
            const el = document.getElementById(id);
            if (!el || !el.textContent) continue;
            try {
                const data = JSON.parse(el.textContent);
                const scope = data.__DEFAULT_SCOPE__ || {};
                const ctx = scope['webapp.app-context'] || data.AppContext || {};
                const uid = (ctx.user && (ctx.user.uniqueId || ctx.user.nickName))
                    || ctx.uniqueId || (data.AppContext && data.AppContext.uniqueId);
                if (uid) return String(uid);
            } catch (e) { /* следующий источник */ }
        }
        return null;
    };
    // 2) явная ссылка «Профиль» в навигации — не из ленты
    const fromNav = () => {
        const sels = ['[data-e2e="nav-profile"]', 'a[data-e2e="nav-profile"]',
                      'nav a[href^="/@"]', 'aside a[href^="/@"]',
                      'header a[href^="/@"]'];
        for (const sel of sels) {
            const el = document.querySelector(sel);
            const href = el && (el.getAttribute('href')
                || (el.querySelector('a[href^="/@"]') || {}).getAttribute?.('href'));
            const m = (href || '').match(/^\/@([A-Za-z0-9._]{1,64})/);
            if (m) return m[1];
        }
        return null;
    };
    return fromState() || fromNav();
}"""

# Свой профиль отличается от чужого кнопкой редактирования: на чужом её нет.
# Без этой проверки ошибочно определённый ник попал бы в белый список лайков.
OWN_PROFILE_CHECK_JS = """() => {
    const marks = ['[data-e2e="edit-profile"]', '[data-e2e="profile-edit"]'];
    for (const sel of marks) if (document.querySelector(sel)) return true;
    const text = (document.body.innerText || '').toLowerCase();
    return text.includes('редактировать профиль') || text.includes('edit profile');
}"""

POST_LINKS_JS = """() => Array.from(document.querySelectorAll('a[href*="/video/"]'))
    .map((a) => a.href).slice(0, 40)"""

# Длительность нужна от того ролика, который сейчас на экране: в ленте элементов
# <video> несколько (соседние подгружены заранее), и первый попавшийся — не тот.
ACTIVE_VIDEO_JS = """() => {
    const vids = Array.from(document.querySelectorAll('video'));
    if (!vids.length) return null;
    const h = window.innerHeight || 1;
    let best = null, bestVisible = -1;
    for (const v of vids) {
        const r = v.getBoundingClientRect();
        const visible = Math.max(0, Math.min(r.bottom, h) - Math.max(r.top, 0));
        if (visible > bestVisible) { bestVisible = visible; best = v; }
    }
    if (!best) return null;
    const d = Number(best.duration);
    return {duration: (isFinite(d) && d > 0) ? d : 0,
            position: Number(best.currentTime) || 0};
}"""

# Комментарии только открываем и закрываем: ничего не пишем и не лайкаем.
COMMENTS_OPEN_JS = """() => {
    const btn = document.querySelector(
        '[data-e2e="browse-comment"], [data-e2e="comment-icon"]');
    if (!btn) return false;
    (btn.closest('button') || btn).click();
    return true;
}"""


class ActivityError(RuntimeError):
    """Аккаунт не смог выполнить действие: протухли куки, упал прокси и т.п."""


def _session(account):
    """Контекст Playwright с куками и прокси аккаунта — как в cookies_alive."""
    from playwright.sync_api import sync_playwright

    from .uploaders.base import (
        STEALTH_INIT_JS,
        load_storage_state,
        parse_proxy,
        stealth_context_kwargs,
        stealth_launch_kwargs,
    )

    if not account.has_cookies:
        raise ActivityError("У аккаунта нет кук — импортируйте storage_state")
    proxy = parse_proxy(account.proxy_url) if account.proxy_url else None
    pw = sync_playwright().start()
    browser = pw.chromium.launch(**stealth_launch_kwargs(proxy, headless=True))
    ctx = browser.new_context(
        storage_state=load_storage_state(account.cookies_path), **stealth_context_kwargs())
    ctx.add_init_script(STEALTH_INIT_JS)
    return pw, browser, ctx


def _check_logged_in(page) -> None:
    url = (page.url or "").lower()
    if "/login" in url or "/signup" in url:
        raise ActivityError("TikTok перекинул на страницу входа — куки недействительны")


def discover_handle(account) -> str | None:
    """Определяет публичный ник аккаунта и убеждается, что профиль действительно его.

    Ошибиться здесь опаснее, чем не найти: чужой ник попал бы в белый список, и
    панель начала бы лайкать посторонний аккаунт. Поэтому найденный ник
    проверяется открытием профиля — на своём есть кнопка редактирования.
    """
    pw, browser, ctx = _session(account)
    try:
        page = ctx.new_page()
        handle = None
        # Студия надёжнее ленты: там профиль всегда свой и в навигации, и в состоянии
        for url in (STUDIO_URL, FEED_URL):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                _check_logged_in(page)
                page.wait_for_timeout(3_000)
                handle = parse_handle(page.evaluate(OWN_PROFILE_JS))
                if handle:
                    break
            except ActivityError:
                raise
            except Exception:  # noqa: BLE001 — источник не сработал, пробуем следующий
                continue
        if not handle:
            return None

        page.goto(PROFILE_URL.format(handle=handle), wait_until="domcontentloaded",
                  timeout=60_000)
        _check_logged_in(page)
        page.wait_for_timeout(2_500)
        if not page.evaluate(OWN_PROFILE_CHECK_JS):
            raise ActivityError(
                f"Нашёлся ник @{handle}, но этот профиль не выглядит вашим "
                f"(нет кнопки редактирования). Впишите ник вручную.")
        return handle
    finally:
        _close(pw, browser)


def _dwell(page, seconds: float, rnd: random.Random) -> None:
    """Пережидает ролик, изредка двигая мышью: страница не должна выглядеть замершей."""
    left = seconds
    while left > 0:
        step = min(left, rnd.uniform(1.5, 4.0))
        page.wait_for_timeout(int(step * 1000))
        left -= step
        if rnd.random() < 0.2:
            try:
                page.mouse.move(rnd.randint(200, 900), rnd.randint(150, 700))
            except Exception:  # noqa: BLE001 — жест необязательный
                pass


def _peek_comments(page, rnd: random.Random) -> None:
    """Открывает панель комментариев и закрывает её. Только чтение."""
    try:
        if not page.evaluate(COMMENTS_OPEN_JS):
            return
        page.wait_for_timeout(int(rnd.uniform(2.0, 6.0) * 1000))
        page.keyboard.press("Escape")
    except Exception:  # noqa: BLE001 — вёрстка могла смениться, сессию не роняем
        pass


def _advance(page, rnd: random.Random, watched: int) -> None:
    """Переход к следующему ролику: то колесом, то клавишей, изредка назад."""
    if watched > 1 and rnd.random() < 0.10:
        page.keyboard.press("ArrowUp")
        return
    if rnd.random() < 0.5:
        try:
            page.mouse.wheel(0, rnd.randint(500, 1200))
            return
        except Exception:  # noqa: BLE001
            pass
    page.keyboard.press("ArrowDown")


def browse_feed(account, seconds: int, rnd: random.Random | None = None,
                log=lambda m: None) -> str:
    """Смотрит ленту заданное число секунд, досматривая ролики по-человечески.

    Ключевое отличие от простого пролистывания: сколько держать ролик, решает
    `watch_plan` по его настоящей длительности, поэтому часть роликов
    досматривается до конца и уходит в сигнал вовлечённости аккаунта. Переходы
    чередуются между колесом и клавишами, изредка заглядываем в комментарии.

    Лайков здесь нет намеренно: в ленте попадаются чужие ролики и реклама, и
    единственный надёжный способ ничего лишнего не лайкнуть — не уметь этого.
    """
    rnd = rnd or random.Random()
    pw, browser, ctx = _session(account)
    try:
        page = ctx.new_page()
        page.goto(FEED_URL, wait_until="domcontentloaded", timeout=60_000)
        _check_logged_in(page)
        page.wait_for_timeout(int(rnd.uniform(1.5, 4.0) * 1000))   # осмотреться

        deadline = _now_monotonic() + seconds
        watched = finished = again = 0
        while True:
            left = deadline - _now_monotonic()
            if left <= 1.0:
                break
            try:
                info = page.evaluate(ACTIVE_VIDEO_JS) or {}
            except Exception:  # noqa: BLE001 — страница перерисовывается
                info = {}
            plan, kind = watch_plan(float(info.get("duration") or 0.0), rnd)
            _dwell(page, min(plan, MAX_DWELL_SECONDS, left), rnd)
            watched += 1
            if kind == "досмотрел":
                finished += 1
            elif kind == "пересмотрел":
                again += 1
            if rnd.random() < 0.15 and deadline - _now_monotonic() > 8:
                _peek_comments(page, rnd)
            _advance(page, rnd, watched)

        log(f"Просмотрено роликов: {watched}, из них досмотрено {finished}")
        return (f"лента {seconds} с: роликов {watched}, "
                f"досмотров {finished}, повторов {again}")
    finally:
        _close(pw, browser)


def like_one(account, target_handle: str, allowed_handles: set[str],
             rnd: random.Random | None = None, log=lambda m: None) -> tuple[str, str]:
    """Ставит лайк одному свежему посту аккаунта панели.

    Возвращает (status, detail). Перед кликом сверяет фактический адрес страницы
    с белым списком: даже если TikTok увёл редиректом, лайка не будет.
    """
    rnd = rnd or random.Random()
    target = parse_handle(target_handle)
    if not target or target not in {h.lower() for h in allowed_handles}:
        return "skipped", "адресат не из панели"

    pw, browser, ctx = _session(account)
    try:
        page = ctx.new_page()
        page.goto(PROFILE_URL.format(handle=target), wait_until="domcontentloaded", timeout=60_000)
        _check_logged_in(page)
        page.wait_for_timeout(3_000)

        links = [u for u in (page.evaluate(POST_LINKS_JS) or [])
                 if video_url_allowed(u, {target})]
        if not links:
            return "skipped", f"у @{target} нет доступных постов"

        url = rnd.choice(links[:TOP_POSTS])
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        _check_logged_in(page)
        page.wait_for_timeout(2_500)

        # Барьер: смотрим не на то, куда собирались, а на то, где оказались
        if not video_url_allowed(page.url, allowed_handles):
            return "skipped", f"адрес вне панели: {page.url}"

        state = page.evaluate(LIKE_STATE_JS)
        if state == "not_found":
            return "error", "кнопка лайка не найдена"
        if state == "liked":
            return "ok", f"пост @{target} уже был отмечен"

        page.evaluate(LIKE_CLICK_JS)
        page.wait_for_timeout(1_500)
        if page.evaluate(LIKE_STATE_JS) != "liked":
            return "error", "лайк не отметился"
        log(f"Лайк посту @{target}")
        return "ok", f"лайк посту @{target}"
    finally:
        _close(pw, browser)


def _now_monotonic() -> float:
    import time

    return time.monotonic()


def _close(pw, browser) -> None:
    try:
        browser.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        pw.stop()
    except Exception:  # noqa: BLE001
        pass
