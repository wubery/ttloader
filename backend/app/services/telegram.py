"""Telegram: уведомления, коды входа в панель и бот управления.

Без внешних зависимостей — только stdlib (urllib). Отправка сообщений синхронная;
приём команд — фоновый поток с long-polling getUpdates. Токен и chat_id берём из
настроек панели (AppSettings), поэтому их можно менять из UI без перезапуска.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request

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


def _settings():
    from .appsettings import get_settings_row

    db = SessionLocal()
    try:
        row = get_settings_row(db)
        return row.tg_bot_token, row.tg_chat_id, row.tg_login_enabled
    finally:
        db.close()


def send_message(token: str, chat_id: str, text: str) -> None:
    try:
        _api("sendMessage", token, {"chat_id": chat_id, "text": text}, timeout=15)
    except Exception:  # noqa: BLE001
        pass


def notify(text: str) -> None:
    """Шлёт уведомление в настроенный chat_id (no-op, если Telegram не настроен)."""
    token, chat_id, _ = _settings()
    if token and chat_id:
        send_message(token, chat_id, text)


# ---------- Вход в панель через Telegram ----------
def issue_login_code() -> bool:
    """Генерирует код, шлёт его в Telegram. Возвращает False, если ТГ не настроен."""
    import secrets

    token, chat_id, enabled = _settings()
    if not (token and chat_id and enabled):
        return False
    code = f"{secrets.randbelow(1000000):06d}"
    _login_codes[code] = time.time() + 300  # 5 минут
    send_message(token, chat_id, f"Код для входа в панель Video Poster: {code}\nДействует 5 минут.")
    return True


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
def _handle_update(token: str, allowed_chat: str, upd: dict) -> None:
    msg = upd.get("message") or upd.get("channel_post")
    if not msg:
        return
    chat_id = str(msg.get("chat", {}).get("id", ""))
    if allowed_chat and chat_id != str(allowed_chat):
        return  # команды только от владельца

    text = (msg.get("text") or "").strip()
    if text.startswith("/start") or text.startswith("/help"):
        send_message(token, chat_id,
                     "Video Poster бот:\n"
                     "/queue — последние задачи\n"
                     "/accounts — аккаунты и статус прокси\n"
                     "Пришли видеофайл — добавлю его в библиотеку.")
        return
    if text.startswith("/queue"):
        _cmd_queue(token, chat_id)
        return
    if text.startswith("/accounts"):
        _cmd_accounts(token, chat_id)
        return

    video = msg.get("video") or msg.get("document")
    if video:
        _intake_video(token, chat_id, video)


def _cmd_queue(token: str, chat_id: str) -> None:
    from ..models import Job

    db = SessionLocal()
    try:
        jobs = db.query(Job).order_by(Job.id.desc()).limit(10).all()
        if not jobs:
            send_message(token, chat_id, "Очередь пуста.")
            return
        lines = [f"#{j.id} {j.status.value}" + (f" — {j.error[:60]}" if j.error else "") for j in jobs]
        send_message(token, chat_id, "Последние задачи:\n" + "\n".join(lines))
    finally:
        db.close()


def _cmd_accounts(token: str, chat_id: str) -> None:
    from ..models import Account

    db = SessionLocal()
    try:
        accs = db.query(Account).order_by(Account.id).all()
        if not accs:
            send_message(token, chat_id, "Аккаунтов нет.")
            return
        lines = []
        for a in accs:
            proxy = "прокси ✓" if a.proxy_ok else ("прокси ✗" if a.proxy_url else "без прокси")
            cookies = "куки ✓" if a.cookies_path else "нет кук"
            lines.append(f"#{a.id} {a.name} [{a.platform.value}] {cookies} {proxy}")
        send_message(token, chat_id, "Аккаунты:\n" + "\n".join(lines))
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
            send_message(token, chat_id, f"Видео добавлено (id={v.id}). Создай пост в панели.")
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        send_message(token, chat_id, f"Не удалось принять видео: {e}")


def _poll_loop() -> None:
    global _running
    offset = 0
    while _running:
        token, chat_id, _ = _settings()
        if not token:
            time.sleep(5)
            continue
        try:
            resp = _api("getUpdates", token, {"offset": offset, "timeout": 25}, timeout=35)
            for u in resp.get("result", []):
                offset = u["update_id"] + 1
                try:
                    _handle_update(token, chat_id, u)
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
