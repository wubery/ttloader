"""Чтение почты аккаунта: список писем и код подтверждения от TikTok.

Два способа, выбираются по домену ящика:

* **graph** — outlook/hotmail/live/msn. Microsoft отключила вход по обычному паролю для
  IMAP в личных ящиках, поэтому здесь только OAuth: подключение через device code
  (пользователь один раз вводит код на microsoft.com/devicelogin), дальше панель живёт
  по refresh-токену и читает почту через Microsoft Graph.
* **imap** — остальные провайдеры: обычный IMAP по логину и паролю.

Всё на stdlib (urllib/imaplib/email) — новых зависимостей не требуется.
"""
from __future__ import annotations

import email
import imaplib
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header

log = logging.getLogger(__name__)

# --- Microsoft OAuth ----------------------------------------------------------
# /consumers — личные аккаунты Microsoft (outlook.com, hotmail, live). Для рабочих
# ящиков Exchange понадобился бы /organizations, но у нас первые.
MS_AUTH_BASE = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
MS_SCOPE = "offline_access Mail.Read"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

MS_DOMAINS = ("outlook.", "hotmail.", "live.", "msn.", "passport.")

# Отправители писем TikTok с кодом
TIKTOK_SENDER_HINTS = ("tiktok", "bytedance")

_token_cache: dict[int, tuple[str, float]] = {}   # account_id -> (access_token, expires_ts)
_cache_lock = threading.Lock()


class MailError(RuntimeError):
    """Ожидаемая ошибка работы с почтой — роутер отдаёт её текст пользователю."""


@dataclass
class MailMessage:
    id: str
    sender: str
    subject: str
    received_at: datetime | None
    preview: str = ""


def detect_kind(address: str | None) -> str | None:
    """graph для ящиков Microsoft, imap для остальных."""
    if not address or "@" not in address:
        return None
    domain = address.rsplit("@", 1)[1].lower()
    return "graph" if any(domain.startswith(d) or f".{d}" in f".{domain}" for d in MS_DOMAINS) else "imap"


def guess_imap_host(address: str | None) -> str | None:
    """Хост IMAP для популярных провайдеров, чтобы не заставлять вводить руками."""
    if not address or "@" not in address:
        return None
    domain = address.rsplit("@", 1)[1].lower()
    known = {
        "gmail.com": "imap.gmail.com",
        "yandex.ru": "imap.yandex.ru",
        "yandex.com": "imap.yandex.com",
        "ya.ru": "imap.yandex.ru",
        "mail.ru": "imap.mail.ru",
        "bk.ru": "imap.mail.ru",
        "inbox.ru": "imap.mail.ru",
        "list.ru": "imap.mail.ru",
        "rambler.ru": "imap.rambler.ru",
        "firstmail.ltd": "imap.firstmail.ltd",
    }
    return known.get(domain) or f"imap.{domain}"


def extract_code(text: str) -> str | None:
    """Достаёт 6-значный код из текста письма.

    Осторожно с числами вокруг: в письмах TikTok попадаются годы, id и куски ссылок,
    поэтому сначала ищем код рядом с ключевыми словами, и только потом — любой
    отдельно стоящий шестизначный.
    """
    if not text:
        return None
    near = re.search(
        r"(?:code|код|verification|подтвержд\w*)[^0-9]{0,40}(\d{6})|(\d{6})[^0-9]{0,40}(?:is your|код)",
        text,
        re.IGNORECASE,
    )
    if near:
        return next(g for g in near.groups() if g)
    plain = re.search(r"(?<![0-9])(\d{6})(?![0-9])", text)
    return plain.group(1) if plain else None


# --- Microsoft Graph ----------------------------------------------------------
def _post_form(url: str, data: dict, timeout: int = 30) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:  # у Microsoft тело ошибки информативнее статуса
            return json.loads(e.read().decode())
        except Exception:  # noqa: BLE001
            raise MailError(f"Microsoft вернул HTTP {e.code}") from None
    except Exception as e:  # noqa: BLE001
        raise MailError(f"Нет связи с Microsoft: {e}") from None


def _graph_get(path: str, token: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(f"{GRAPH_BASE}{path}", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode()).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            pass
        raise MailError(f"Graph вернул HTTP {e.code}. {detail}".strip()) from None
    except Exception as e:  # noqa: BLE001
        raise MailError(f"Нет связи с Microsoft Graph: {e}") from None


def _access_token(account, db) -> str:
    """Свежий access-токен: из кэша или обменом refresh-токена (Microsoft их ротирует)."""
    from .crypto import decrypt, encrypt

    with _cache_lock:
        cached = _token_cache.get(account.id)
        if cached and cached[1] > time.time() + 60:
            return cached[0]

    refresh = decrypt(account.mail_refresh_token_enc)
    if not refresh:
        raise MailError("Почта не подключена: нет токена. Нажмите «Подключить почту».")
    client_id = _ms_client_id(db)

    res = _post_form(
        f"{MS_AUTH_BASE}/token",
        {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "scope": MS_SCOPE,
        },
    )
    if "access_token" not in res:
        raise MailError(
            f"Microsoft отклонил токен ({res.get('error_description') or res.get('error')}). "
            "Подключите почту заново."
        )
    if res.get("refresh_token"):
        account.mail_refresh_token_enc = encrypt(res["refresh_token"])
        db.commit()
    token = res["access_token"]
    with _cache_lock:
        _token_cache[account.id] = (token, time.time() + int(res.get("expires_in", 3600)))
    return token


def _ms_client_id(db) -> str:
    from .appsettings import get_settings_row

    client_id = (get_settings_row(db).ms_client_id or "").strip()
    if not client_id:
        raise MailError(
            "Не задан Client ID приложения Microsoft. Настройки → Почта "
            "(как его получить — в INSTALL.md)."
        )
    return client_id


def _parse_graph_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _graph_list(account, db, limit: int) -> list[MailMessage]:
    token = _access_token(account, db)
    query = urllib.parse.urlencode(
        {
            "$top": max(1, min(limit, 50)),
            "$select": "id,subject,from,receivedDateTime,bodyPreview",
            "$orderby": "receivedDateTime desc",
        }
    )
    data = _graph_get(f"/me/messages?{query}", token)
    out: list[MailMessage] = []
    for m in data.get("value", []):
        addr = (m.get("from") or {}).get("emailAddress") or {}
        out.append(
            MailMessage(
                id=m.get("id", ""),
                sender=addr.get("address") or addr.get("name") or "",
                subject=m.get("subject") or "(без темы)",
                received_at=_parse_graph_dt(m.get("receivedDateTime")),
                preview=(m.get("bodyPreview") or "")[:200],
            )
        )
    return out


def _graph_body(account, db, msg_id: str) -> str:
    token = _access_token(account, db)
    data = _graph_get(f"/messages/{urllib.parse.quote(msg_id)}?$select=body,subject", token)
    body = (data.get("body") or {}).get("content") or ""
    return _strip_html(body)


# --- IMAP ---------------------------------------------------------------------
def _imap_connect(account):
    from .crypto import decrypt

    host = account.mail_imap_host or guess_imap_host(account.mail_address)
    password = decrypt(account.mail_password_enc)
    if not host or not password:
        raise MailError("Для IMAP нужны адрес сервера и пароль ящика.")
    port = account.mail_imap_port or 993
    try:
        conn = imaplib.IMAP4_SSL(host, port)
        conn.login(account.mail_address, password)
        conn.select("INBOX")
        return conn
    except imaplib.IMAP4.error as e:
        raise MailError(f"IMAP отклонил вход: {e}") from None
    except Exception as e:  # noqa: BLE001
        raise MailError(f"Не удалось подключиться к {host}:{port} — {e}") from None


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001
        return value


def _imap_list(account, limit: int) -> list[MailMessage]:
    conn = _imap_connect(account)
    try:
        _typ, data = conn.search(None, "ALL")
        ids = (data[0] or b"").split()[-max(1, min(limit, 50)):]
        out: list[MailMessage] = []
        for num in reversed(ids):
            _typ, raw = conn.fetch(num, "(RFC822.HEADER)")
            if not raw or not raw[0]:
                continue
            msg = email.message_from_bytes(raw[0][1])
            received = None
            if msg.get("Date"):
                try:
                    received = email.utils.parsedate_to_datetime(msg["Date"])
                except Exception:  # noqa: BLE001
                    pass
            out.append(
                MailMessage(
                    id=num.decode(),
                    sender=_decode(msg.get("From")),
                    subject=_decode(msg.get("Subject")) or "(без темы)",
                    received_at=received,
                )
            )
        return out
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


def _imap_body(account, msg_id: str) -> str:
    conn = _imap_connect(account)
    try:
        _typ, raw = conn.fetch(msg_id.encode(), "(RFC822)")
        if not raw or not raw[0]:
            return ""
        msg = email.message_from_bytes(raw[0][1])
        return _message_text(msg)
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


def _message_text(msg) -> str:
    """Текст письма: предпочитаем text/plain, иначе чистим html."""
    if not msg.is_multipart():
        payload = msg.get_payload(decode=True) or b""
        text = payload.decode(msg.get_content_charset() or "utf-8", "replace")
        return text if msg.get_content_type() == "text/plain" else _strip_html(text)
    plain, html = "", ""
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        payload = part.get_payload(decode=True) or b""
        text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        if part.get_content_type() == "text/plain" and not plain:
            plain = text
        elif part.get_content_type() == "text/html" and not html:
            html = text
    return plain or _strip_html(html)


def _strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    )
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


# --- Публичный интерфейс ------------------------------------------------------
def list_messages(account, db, limit: int = 20) -> list[MailMessage]:
    kind = account.mail_kind or detect_kind(account.mail_address)
    if kind == "graph":
        return _graph_list(account, db, limit)
    if kind == "imap":
        return _imap_list(account, limit)
    raise MailError("У аккаунта не настроена почта.")


def get_body(account, db, msg_id: str) -> str:
    kind = account.mail_kind or detect_kind(account.mail_address)
    if kind == "graph":
        return _graph_body(account, db, msg_id)
    if kind == "imap":
        return _imap_body(account, msg_id)
    raise MailError("У аккаунта не настроена почта.")


def find_login_code(account, db, since: datetime | None = None, limit: int = 15) -> str | None:
    """Ищет код подтверждения TikTok в свежих письмах.

    `since` отсекает старые письма — иначе легко подставить код от прошлого входа,
    и TikTok его не примет.
    """
    messages = list_messages(account, db, limit=limit)
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)

    for m in messages:
        blob = f"{m.sender} {m.subject}".lower()
        if not any(h in blob for h in TIKTOK_SENDER_HINTS):
            continue
        if since is not None and m.received_at is not None:
            received = m.received_at if m.received_at.tzinfo else m.received_at.replace(tzinfo=timezone.utc)
            if received < since - timedelta(seconds=60):   # запас на расхождение часов
                continue
        code = extract_code(m.subject) or extract_code(m.preview)
        if code:
            return code
        code = extract_code(get_body(account, db, m.id))
        if code:
            return code
    return None


# --- Подключение почты Microsoft (device code) --------------------------------
_connects: dict[int, dict] = {}     # account_id -> состояние подключения
_connect_lock = threading.Lock()


def start_device_code(account, db) -> dict:
    """Запускает device code flow и фоновое ожидание подтверждения."""
    client_id = _ms_client_id(db)
    res = _post_form(f"{MS_AUTH_BASE}/devicecode", {"client_id": client_id, "scope": MS_SCOPE})
    if "device_code" not in res:
        raise MailError(
            f"Microsoft не выдал код: {res.get('error_description') or res.get('error')}. "
            "Проверьте Client ID и что в приложении включён «Allow public client flows»."
        )

    with _connect_lock:
        _connects[account.id] = {"state": "pending", "message": None}

    threading.Thread(
        target=_poll_device_code,
        args=(account.id, client_id, res["device_code"], int(res.get("interval", 5)), int(res.get("expires_in", 900))),
        daemon=True,
    ).start()

    return {
        "user_code": res.get("user_code", ""),
        "verification_uri": res.get("verification_uri") or "https://microsoft.com/devicelogin",
        "expires_in": int(res.get("expires_in", 900)),
    }


def _poll_device_code(account_id: int, client_id: str, device_code: str, interval: int, expires_in: int) -> None:
    """Ждём, пока человек введёт код на странице Microsoft, и сохраняем refresh-токен."""
    from ..db import SessionLocal
    from ..models import Account
    from .crypto import encrypt

    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(max(interval, 3))
        res = _post_form(
            f"{MS_AUTH_BASE}/token",
            {
                "client_id": client_id,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
            },
        )
        error = res.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error:
            _set_connect(account_id, "error", res.get("error_description") or error)
            return

        refresh = res.get("refresh_token")
        if not refresh:
            _set_connect(account_id, "error", "Microsoft не вернул refresh-токен")
            return

        db = SessionLocal()
        try:
            acc = db.get(Account, account_id)
            if acc is None:
                _set_connect(account_id, "error", "Аккаунт удалён")
                return
            acc.mail_refresh_token_enc = encrypt(refresh)
            acc.mail_kind = "graph"
            acc.mail_connected_at = datetime.now()
            db.commit()
        finally:
            db.close()
        _set_connect(account_id, "done", "Почта подключена")
        return

    _set_connect(account_id, "error", "Время ожидания истекло — начните подключение заново")


def _set_connect(account_id: int, state: str, message: str | None) -> None:
    with _connect_lock:
        _connects[account_id] = {"state": state, "message": message}


def connect_state(account_id: int) -> dict:
    with _connect_lock:
        return dict(_connects.get(account_id) or {"state": "idle", "message": None})
