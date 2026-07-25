"""Telegram: уведомления, коды входа в панель и бот управления.

Без внешних зависимостей — только stdlib (urllib). Отправка сообщений синхронная;
приём команд — фоновый поток с long-polling getUpdates. Токен и chat_id берём из
настроек панели (AppSettings), поэтому их можно менять из UI без перезапуска.

Chat ID может быть несколько (через запятую) — тогда уведомления и коды входа
получают все указанные аккаунты, и все они могут командовать ботом.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from ..db import SessionLocal

_API = "https://api.telegram.org"
_login_codes: dict[str, float] = {}  # code -> expiry ts
_poller: threading.Thread | None = None
_running = False

# Если у сервера нет прямого доступа к Telegram (блокировки провайдера) — можно
# пустить трафик бота через HTTP-прокси (например, локальный xray-клиент, который
# оборачивает VLESS). Задаётся env TELEGRAM_PROXY=http://xray:10809.
_PROXY = os.environ.get("TELEGRAM_PROXY", "").strip()


def _opener() -> urllib.request.OpenerDirector:
    if _PROXY:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": _PROXY, "https": _PROXY})
        )
    return urllib.request.build_opener()


def _api(method: str, token: str, params: dict, timeout: int = 30) -> dict:
    data = urllib.parse.urlencode(params).encode()
    url = f"{_API}/bot{token}/{method}"
    with _opener().open(urllib.request.Request(url, data=data), timeout=timeout) as r:
        return json.loads(r.read().decode())


def parse_chat_ids(raw: str | None) -> list[str]:
    """Разбирает строку chat_id в список: «598116316, 500135254» → ["598116316","500135254"].
    Разделители — запятая, точка с запятой, пробелы, перевод строки."""
    if not raw:
        return []
    out: list[str] = []
    for part in re.split(r"[,;\s]+", raw.strip()):
        p = part.strip()
        if p and p not in out:
            out.append(p)
    return out


def _settings() -> tuple[str | None, list[str], bool]:
    """(токен, список chat_id, включён ли вход через Telegram)."""
    from .appsettings import get_settings_row

    db = SessionLocal()
    try:
        row = get_settings_row(db)
        return row.tg_bot_token, parse_chat_ids(row.tg_chat_id), row.tg_login_enabled
    finally:
        db.close()


def send_message(token: str, chat_id: str, text: str, reply_markup: dict | None = None) -> bool:
    try:
        params: dict = {"chat_id": chat_id, "text": text}
        if reply_markup:
            params["reply_markup"] = json.dumps(reply_markup)
        r = _api("sendMessage", token, params, timeout=15)
        return bool(r.get("ok"))
    except Exception:  # noqa: BLE001
        return False


def notify(text: str) -> None:
    """Шлёт уведомление во ВСЕ настроенные chat_id (no-op, если Telegram не настроен)."""
    token, chat_ids, _ = _settings()
    if not token:
        return
    for cid in chat_ids:
        send_message(token, cid, text)


# ---------- Вход в панель через Telegram ----------
def issue_login_code() -> str:
    """Генерирует код и шлёт его во все настроенные чаты.

    Возвращает «ok» | «not_configured» | «send_failed» — вызывающему нужно
    различать «не настроено» и «настроено, но бот недоступен» (например,
    api.telegram.org заблокирован и не поднят туннель).
    Код запоминается, только если доставлен хотя бы в один чат.
    """
    import secrets

    token, chat_ids, enabled = _settings()
    if not (token and chat_ids and enabled):
        return "not_configured"
    code = f"{secrets.randbelow(1000000):06d}"
    text = f"Код для входа в панель Video Poster: {code}\nДействует 5 минут."
    delivered = False
    for cid in chat_ids:
        if send_message(token, cid, text):
            delivered = True
    if not delivered:
        return "send_failed"
    _login_codes[code] = time.time() + 300  # 5 минут
    return "ok"


def check_login_code(code: str) -> bool:
    exp = _login_codes.get(code)
    if exp and exp >= time.time():
        _login_codes.pop(code, None)
        return True
    # чистим протухшие
    for c in [c for c, e in _login_codes.items() if e < time.time()]:
        _login_codes.pop(c, None)
    return False


# ---------- Бот управления (команды + приём видео) ----------
def _handle_update(token: str, allowed: list[str], upd: dict) -> None:
    msg = upd.get("message") or upd.get("channel_post")
    callback = upd.get("callback_query")

    if callback:
        _handle_callback(token, allowed, callback)
        return

    if not msg:
        return
    chat_id = str(msg.get("chat", {}).get("id", ""))
    if allowed and chat_id not in allowed:
        return  # команды только от разрешённых аккаунтов

    text = (msg.get("text") or "").strip().lower()

    # Команды
    if text.startswith("/start") or text.startswith("/help"):
        _cmd_help(token, chat_id)
        return
    if text.startswith("/queue"):
        _cmd_queue(token, chat_id)
        return
    if text.startswith("/accounts"):
        _cmd_accounts(token, chat_id)
        return
    if text.startswith("/videos"):
        _cmd_videos(token, chat_id)
        return
    if text.startswith("/stats"):
        _cmd_stats(token, chat_id)
        return
    if text.startswith("/status"):
        _cmd_status(token, chat_id)
        return
    if text.startswith("/proxy"):
        _cmd_proxy(token, chat_id)
        return
    if text.startswith("/newpost"):
        _cmd_newpost(token, chat_id, text)
        return
    if text.startswith("/delete"):
        _cmd_delete(token, chat_id, text)
        return
    if text.startswith("/settings"):
        _cmd_settings(token, chat_id)
        return

    # Приём видео
    video = msg.get("video") or msg.get("document")
    if video:
        _intake_video(token, chat_id, video)
        return

    # Приём фото (баннеры)
    photo = msg.get("photo")
    if photo:
        _intake_photo(token, chat_id, photo)
        return


def _handle_callback(token: str, allowed: list[str], callback: dict) -> None:
    chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
    if allowed and chat_id not in allowed:
        return

    data = callback.get("data", "")
    cb_id = callback.get("id", "")

    # Подтверждаем callback (убираем "часики" на кнопке)
    try:
        _api("answerCallbackQuery", token, {"callback_query_id": cb_id}, timeout=5)
    except Exception:
        pass

    if data.startswith("refresh_queue"):
        _cmd_queue(token, chat_id)
    elif data.startswith("refresh_accounts"):
        _cmd_accounts(token, chat_id)
    elif data.startswith("refresh_videos"):
        _cmd_videos(token, chat_id)
    elif data.startswith("check_proxy_all"):
        _cmd_proxy(token, chat_id)
    elif data.startswith("system_status"):
        _cmd_status(token, chat_id)


def _cmd_help(token: str, chat_id: str) -> None:
    send_message(token, chat_id,
        "🎬 Video Poster — команды:\n\n"
        "📋 /queue — последние задачи\n"
        "👥 /accounts — аккаунты и прокси\n"
        "🎥 /videos — библиотека видео\n"
        "📊 /stats — статистика постинга\n"
        "💓 /status — здоровье системы\n"
        "🔍 /proxy — проверить все прокси\n"
        "⚙️ /settings — текущие настройки\n\n"
        "➕ /newpost <id_аккаунта> <id_видео> [подпись]\n"
        "   Пример: /newpost 1 3 Мой пост #теги\n\n"
        "🗑 /delete <тип> <id>\n"
        "   Пример: /delete video 5\n\n"
        "📹 Пришли видео — добавлю в библиотеку\n"
        "🖼 Пришли фото — добавлю как баннер",
        reply_markup={
            "inline_keyboard": [
                [{"text": "🔄 Обновить", "callback_data": "refresh_queue"}]
            ]
        }
    )


def _cmd_queue(token: str, chat_id: str) -> None:
    from ..models import Job, JobStatus

    db = SessionLocal()
    try:
        jobs = db.query(Job).order_by(Job.id.desc()).limit(10).all()
        if not jobs:
            send_message(token, chat_id, "📋 Очередь пуста.",
                reply_markup={"inline_keyboard": [[{"text": "🔄 Обновить", "callback_data": "refresh_queue"}]]})
            return
        status_emoji = {
            "pending": "⏳", "rendering": "🎨", "uploading": "🚀",
            "done": "✅", "failed": "❌"
        }
        lines = []
        for j in jobs:
            emoji = status_emoji.get(j.status.value, "❓")
            err = f" — {j.error[:50]}" if j.error else ""
            lines.append(f"{emoji} #{j.id} {j.status.value}{err}")
        send_message(token, chat_id, "📋 Последние задачи:\n\n" + "\n".join(lines),
            reply_markup={"inline_keyboard": [[{"text": "🔄 Обновить", "callback_data": "refresh_queue"}]]})
    finally:
        db.close()


def _cmd_accounts(token: str, chat_id: str) -> None:
    from ..models import Account

    db = SessionLocal()
    try:
        accs = db.query(Account).order_by(Account.id).all()
        if not accs:
            send_message(token, chat_id, "👥 Аккаунтов нет.",
                reply_markup={"inline_keyboard": [[{"text": "🔄 Обновить", "callback_data": "refresh_accounts"}]]})
            return
        lines = []
        for a in accs:
            proxy = "🟢" if a.proxy_ok else ("🔴" if a.proxy_url else "⚪")
            cookies = "🍪" if a.cookies_path else "❌"
            platform = "🎵" if a.platform.value == "tiktok" else "▶️"
            lines.append(f"{platform} #{a.id} {a.name} {cookies} {proxy}")
        send_message(token, chat_id, "👥 Аккаунты:\n\n" + "\n".join(lines),
            reply_markup={"inline_keyboard": [[{"text": "🔄 Обновить", "callback_data": "refresh_accounts"}]]})
    finally:
        db.close()


def _cmd_videos(token: str, chat_id: str) -> None:
    from ..models import Video

    db = SessionLocal()
    try:
        vids = db.query(Video).order_by(Video.id.desc()).limit(15).all()
        if not vids:
            send_message(token, chat_id, "🎥 Библиотека пуста. Пришли видеофайл.",
                reply_markup={"inline_keyboard": [[{"text": "🔄 Обновить", "callback_data": "refresh_videos"}]]})
            return
        lines = []
        for v in vids:
            dur = f" · {v.duration:.1f}с" if v.duration else ""
            res = f" {v.width}×{v.height}" if v.width and v.height else ""
            lines.append(f"🎥 #{v.id} {v.title[:30]}{res}{dur}")
        send_message(token, chat_id, "🎥 Библиотека видео:\n\n" + "\n".join(lines),
            reply_markup={"inline_keyboard": [[{"text": "🔄 Обновить", "callback_data": "refresh_videos"}]]})
    finally:
        db.close()


def _cmd_stats(token: str, chat_id: str) -> None:
    from ..models import Job, JobStatus, Account, Video

    db = SessionLocal()
    try:
        total = db.query(Job).count()
        done = db.query(Job).filter(Job.status == JobStatus.done).count()
        failed = db.query(Job).filter(Job.status == JobStatus.failed).count()
        pending = db.query(Job).filter(Job.status == JobStatus.pending).count()
        accounts = db.query(Account).count()
        videos = db.query(Video).count()

        # Статистика за последние 24 часа
        since = datetime.now() - timedelta(hours=24)
        recent_done = db.query(Job).filter(Job.status == JobStatus.done, Job.created_at >= since).count()
        recent_failed = db.query(Job).filter(Job.status == JobStatus.failed, Job.created_at >= since).count()

        success_rate = f"{(done / total * 100):.0f}%" if total > 0 else "—"

        send_message(token, chat_id,
            f"📊 Статистика:\n\n"
            f"Всего задач: {total}\n"
            f"✅ Выполнено: {done}\n"
            f"❌ Ошибки: {failed}\n"
            f"⏳ В очереди: {pending}\n"
            f"📈 Успешность: {success_rate}\n\n"
            f"За 24ч: ✅ {recent_done} / ❌ {recent_failed}\n\n"
            f"👥 Аккаунтов: {accounts}\n"
            f"🎥 Видео: {videos}")
    finally:
        db.close()


def _cmd_status(token: str, chat_id: str) -> None:
    import shutil

    ffmpeg_ok = shutil.which("ffmpeg") is not None
    ffprobe_ok = shutil.which("ffprobe") is not None

    from ..models import Account
    db = SessionLocal()
    try:
        accs = db.query(Account).filter(Account.active.is_(True)).all()
        proxy_ok = sum(1 for a in accs if a.proxy_ok is True)
        proxy_fail = sum(1 for a in accs if a.proxy_ok is False)
        proxy_unchecked = sum(1 for a in accs if a.proxy_ok is None and a.proxy_url)
    finally:
        db.close()

    send_message(token, chat_id,
        f"💓 Состояние системы:\n\n"
        f"{'✅' if ffmpeg_ok else '❌'} ffmpeg\n"
        f"{'✅' if ffprobe_ok else '❌'} ffprobe\n\n"
        f"🌐 Прокси:\n"
        f"  🟢 Работают: {proxy_ok}\n"
        f"  🔴 Упали: {proxy_fail}\n"
        f"  ⚪ Не проверены: {proxy_unchecked}")


def _cmd_proxy(token: str, chat_id: str) -> None:
    from ..models import Account

    db = SessionLocal()
    try:
        accs = db.query(Account).filter(Account.proxy_url.isnot(None)).all()
        if not accs:
            send_message(token, chat_id, "🔍 Нет аккаунтов с прокси.")
            return
        lines = []
        for a in accs:
            status = "🟢" if a.proxy_ok else ("🔴" if a.proxy_ok is False else "⚪")
            ip = f" ({a.proxy_ip})" if a.proxy_ip else ""
            checked = ""
            if a.proxy_checked_at:
                delta = datetime.now() - a.proxy_checked_at
                if delta.total_seconds() < 3600:
                    checked = f" · {int(delta.total_seconds() / 60)}м назад"
                else:
                    checked = f" · {int(delta.total_seconds() / 3600)}ч назад"
            lines.append(f"{status} {a.name}: {a.proxy_url[:40]}{ip}{checked}")
        send_message(token, chat_id, "🔍 Статус прокси:\n\n" + "\n".join(lines))
    finally:
        db.close()


def _cmd_newpost(token: str, chat_id: str, text: str) -> None:
    from ..models import Account, Video, Job

    parts = text.split(maxsplit=3)
    if len(parts) < 3:
        send_message(token, chat_id,
            "➕ Использование: /newpost <id_аккаунта> <id_видео> [подпись]\n"
            "Пример: /newpost 1 3 Мой пост #теги")
        return

    try:
        acc_id = int(parts[1])
        vid_id = int(parts[2])
    except ValueError:
        send_message(token, chat_id, "❌ ID должны быть числами.")
        return

    caption = parts[3] if len(parts) > 3 else ""

    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == acc_id).first()
        if not acc:
            send_message(token, chat_id, f"❌ Аккаунт #{acc_id} не найден.")
            return
        vid = db.query(Video).filter(Video.id == vid_id).first()
        if not vid:
            send_message(token, chat_id, f"❌ Видео #{vid_id} не найдено.")
            return
        if not acc.cookies_path:
            send_message(token, chat_id, f"⚠️ У аккаунта «{acc.name}» нет кук. Импортируй их в панели.")
            return

        job = Job(account_id=acc_id, video_id=vid_id, caption=caption)
        db.add(job)
        db.commit()
        db.refresh(job)
        send_message(token, chat_id,
            f"✅ Задача #{job.id} создана!\n"
            f"👤 {acc.name} ← 🎥 {vid.title}\n"
            f"📝 {caption or '(без подписи)'}")
    finally:
        db.close()


def _cmd_delete(token: str, chat_id: str, text: str) -> None:
    parts = text.split()
    if len(parts) < 3:
        send_message(token, chat_id,
            "🗑 Использование: /delete <тип> <id>\n"
            "Типы: video, banner, job\n"
            "Пример: /delete video 5")
        return

    item_type = parts[1].lower()
    try:
        item_id = int(parts[2])
    except ValueError:
        send_message(token, chat_id, "❌ ID должен быть числом.")
        return

    from ..models import Video, Banner, Job
    import os
    from ..config import settings

    db = SessionLocal()
    try:
        if item_type == "video":
            item = db.query(Video).filter(Video.id == item_id).first()
            if not item:
                send_message(token, chat_id, f"❌ Видео #{item_id} не найдено.")
                return
            # Удаляем файл
            fpath = os.path.join(settings.videos_dir, item.filename)
            if os.path.exists(fpath):
                os.remove(fpath)
            db.delete(item)
            db.commit()
            send_message(token, chat_id, f"✅ Видео «{item.title}» удалено.")
        elif item_type == "banner":
            item = db.query(Banner).filter(Banner.id == item_id).first()
            if not item:
                send_message(token, chat_id, f"❌ Баннер #{item_id} не найден.")
                return
            fpath = os.path.join(settings.banners_dir, item.filename)
            if os.path.exists(fpath):
                os.remove(fpath)
            db.delete(item)
            db.commit()
            send_message(token, chat_id, f"✅ Баннер «{item.name}» удалён.")
        elif item_type == "job":
            item = db.query(Job).filter(Job.id == item_id).first()
            if not item:
                send_message(token, chat_id, f"❌ Задача #{item_id} не найдена.")
                return
            db.delete(item)
            db.commit()
            send_message(token, chat_id, f"✅ Задача #{item_id} удалена.")
        else:
            send_message(token, chat_id, f"❌ Неизвестный тип: {item_type}. Используй: video, banner, job")
    finally:
        db.close()


def _cmd_settings(token: str, chat_id: str) -> None:
    from ..services.appsettings import get_settings_row

    db = SessionLocal()
    try:
        row = get_settings_row(db)
        ids = parse_chat_ids(row.tg_chat_id)
        tg_status = "✅ Настроен" if (row.tg_bot_token and ids) else "❌ Не настроен"
        login_status = "✅ Включён" if row.tg_login_enabled else "Выключен"
        ids_txt = ", ".join(ids) if ids else "не задан"
        send_message(token, chat_id,
            f"⚙️ Текущие настройки:\n\n"
            f"🤖 Telegram: {tg_status}\n"
            f"🔐 Вход через TG: {login_status}\n"
            f"💬 Chat ID ({len(ids)}): {ids_txt}")
    finally:
        db.close()


def _intake_video(token: str, chat_id: str, video: dict) -> None:
    import uuid

    from ..config import settings
    from ..models import Video

    file_id = video.get("file_id")
    try:
        info = _api("getFile", token, {"file_id": file_id}, timeout=20)
        file_path = info["result"]["file_path"]
        url = f"{_API}/file/bot{token}/{file_path}"
        settings.ensure_dirs()
        ext = os.path.splitext(file_path)[1].lower() or ".mp4"
        fname = f"{uuid.uuid4().hex}{ext}"
        dest = os.path.join(settings.videos_dir, fname)
        with _opener().open(url, timeout=120) as r, open(dest, "wb") as f:
            f.write(r.read())
        db = SessionLocal()
        try:
            from . import media
            w = h = None
            dur = None
            try:
                vi = media.probe(dest)
                w, h, dur = vi.width, vi.height, vi.duration
            except Exception:  # noqa: BLE001
                pass
            v = Video(title=f"tg_{fname}", filename=fname, width=w, height=h, duration=dur)
            db.add(v)
            db.commit()
            db.refresh(v)
            send_message(token, chat_id,
                f"🎥 Видео добавлено!\n"
                f"🆔 ID: {v.id}\n"
                f"📐 {w or '?'}×{h or '?'} {f'· {dur:.1f}с' if dur else ''}\n\n"
                f"Создай пост: /newpost <id_аккаунта> {v.id} [подпись]")
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        send_message(token, chat_id, f"❌ Не удалось принять видео: {e}")


def _intake_photo(token: str, chat_id: str, photos: list) -> None:
    """Принимает фото как баннер (берём максимальное разрешение)."""
    import uuid

    from ..config import settings
    from ..models import Banner, BannerType

    # Берём фото максимального размера
    best = max(photos, key=lambda p: p.get("file_size", 0))
    file_id = best.get("file_id")
    try:
        info = _api("getFile", token, {"file_id": file_id}, timeout=20)
        file_path = info["result"]["file_path"]
        url = f"{_API}/file/bot{token}/{file_path}"
        settings.ensure_dirs()
        ext = os.path.splitext(file_path)[1].lower() or ".jpg"
        fname = f"{uuid.uuid4().hex}{ext}"
        dest = os.path.join(settings.banners_dir, fname)
        with _opener().open(url, timeout=60) as r, open(dest, "wb") as f:
            f.write(r.read())
        db = SessionLocal()
        try:
            b = Banner(name=f"tg_{fname[:8]}", type=BannerType.image, filename=fname)
            db.add(b)
            db.commit()
            db.refresh(b)
            send_message(token, chat_id,
                f"🖼 Баннер добавлен!\n"
                f"🆔 ID: {b.id}\n"
                f"📝 Имя: {b.name}\n\n"
                f"Настрой позицию в редакторе панели.")
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        send_message(token, chat_id, f"❌ Не удалось принять фото: {e}")


def _poll_loop() -> None:
    global _running
    offset = 0
    while _running:
        token, chat_ids, _ = _settings()
        if not token:
            time.sleep(5)
            continue
        try:
            resp = _api("getUpdates", token, {"offset": offset, "timeout": 25}, timeout=35)
            for u in resp.get("result", []):
                offset = u["update_id"] + 1
                try:
                    _handle_update(token, chat_ids, u)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            time.sleep(3)


def start_bot() -> None:
    global _poller, _running
    if _poller is not None:
        return
    _running = True
    _poller = threading.Thread(target=_poll_loop, name="tg-bot", daemon=True)
    _poller.start()


def stop_bot() -> None:
    global _running
    _running = False
