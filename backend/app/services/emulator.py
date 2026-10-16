"""Тестовая заливка через Android-эмулятор (или телефон) по ADB.

Путь не браузерный: ролик кладётся в галерею устройства и «расшаривается» в
приложение TikTok системным интентом SEND — так же, как если бы пользователь
нажал «Поделиться» в галерее. Дальше — снимок экрана и разбор того, что на нём.

Это ТЕСТОВЫЙ режим, и сознательно ограниченный:

* кнопка «Опубликовать» не нажимается никогда — максимум доходим до экрана
  публикации. Автоматизация приложения проверяется вслепую хуже браузера, а
  ошибочная публикация необратима;
* приложение TikTok эмулятор распознаёт (ro.kernel.qemu, ranchu, serialno не
  подменяются), вход и регистрация в нём на эмуляторе обычно упираются в
  «Maximum number of attempts». Рабочим путём это станет только на аккаунте,
  который уже залогинен в приложении, — лучше на реальном телефоне по ADB.

Чистые функции (разбор вывода adb, дерева экрана) отделены от вызовов adb —
их проверяют тесты.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from ..config import settings

# Пакеты TikTok: глобальный, региональная сборка, китайский, Lite
TIKTOK_PACKAGES = ("com.zhiliaoapp.musically", "com.ss.android.ugc.trill",
                   "com.ss.android.ugc.aweme", "com.zhiliaoapp.musically.go")
ADDR_RE = re.compile(r"^[A-Za-z0-9.\-]+:\d{1,5}$|^emulator-\d{1,5}$")

# Подписи кнопок, по которым узнаём экраны приложения (ru/en)
NEXT_LABELS = ("Далее", "Next")
POST_LABELS = ("Опубликовать", "Post")
LOGIN_HINTS = ("Войти", "Log in", "Sign up", "Регистрация", "Use phone / email")


class EmulatorError(RuntimeError):
    pass


# ------------------------------------------------------------------ разбор


def parse_devices(output: str) -> list[dict]:
    """Вывод `adb devices -l` → [{serial, state, model}]."""
    out = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        model = next((p.split(":", 1)[1] for p in parts[2:] if p.startswith("model:")), "")
        out.append({"serial": parts[0], "state": parts[1], "model": model})
    return out


def pick_tiktok_package(pm_output: str) -> str | None:
    """Из вывода `pm list packages` — установленный пакет TikTok (по приоритету)."""
    installed = {ln.split(":", 1)[1].strip() for ln in pm_output.splitlines() if ln.startswith("package:")}
    return next((p for p in TIKTOK_PACKAGES if p in installed), None)


def parse_media_id(output: str, filename: str) -> str | None:
    """`content query … --projection _id:_display_name` → id записи с этим именем.

    Фильтр --where не используется: adb склеивает аргументы в строку для шелла
    устройства, и кавычки вокруг значения съедаются («Invalid token»).
    """
    for m in re.finditer(r"_id=(\d+), _display_name=(\S+)", output):
        if m.group(2) == filename:
            return m.group(1)
    return None


@dataclass
class ScreenNode:
    text: str
    desc: str
    clickable: bool
    center: tuple[int, int]


@dataclass
class Screen:
    package: str = ""
    nodes: list[ScreenNode] = field(default_factory=list)

    def texts(self) -> list[str]:
        return [t for n in self.nodes for t in (n.text, n.desc) if t]

    def find(self, labels: tuple[str, ...]) -> ScreenNode | None:
        """Узел с подписью из списка (точное совпадение — кнопки короткие)."""
        wanted = {lbl.lower() for lbl in labels}
        for n in self.nodes:
            if n.text.lower() in wanted or n.desc.lower() in wanted:
                return n
        return None


def parse_ui_dump(xml_text: str) -> Screen:
    """Дерево `uiautomator dump` → упрощённый экран."""
    screen = Screen()
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return screen
    for node in root.iter("node"):
        if not screen.package:
            screen.package = node.get("package", "")
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        text, desc = node.get("text", "").strip(), node.get("content-desc", "").strip()
        if not (text or desc):
            continue
        screen.nodes.append(ScreenNode(text, desc, node.get("clickable") == "true",
                                       ((x1 + x2) // 2, (y1 + y2) // 2)))
    return screen


def classify(screen: Screen, tiktok_pkg: str | None) -> str:
    """Где мы: login | post | editor | other_app | unknown."""
    if tiktok_pkg and screen.package and screen.package != tiktok_pkg:
        return "other_app"
    if screen.find(POST_LABELS):
        return "post"
    if screen.find(NEXT_LABELS):
        return "editor"
    if any(h.lower() in t.lower() for t in screen.texts() for h in LOGIN_HINTS):
        return "login"
    return "unknown"


SCREEN_LABELS = {
    "post": "экран публикации — дальше только «Опубликовать» (в тестовом режиме не нажимается)",
    "editor": "редактор ролика — видео в приложении, можно идти дальше",
    "login": "приложение просит войти — аккаунт в приложении не залогинен",
    "other_app": "на экране не TikTok — интент открыл другое приложение или выбор приложений",
    "unknown": "экран не распознан — смотрите снимок",
}


# ------------------------------------------------------------------ adb


def _adb(*args: str, serial: str | None = None, timeout: int = 30, binary: bool = False):
    cmd = [settings.adb_bin] + (["-s", serial] if serial else []) + list(args)
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except FileNotFoundError as e:
        raise EmulatorError(f"adb не найден ({settings.adb_bin}) — установите platform-tools "
                            f"или задайте ADB_BIN") from e
    except subprocess.TimeoutExpired as e:
        raise EmulatorError(f"adb {' '.join(args[:2])}: нет ответа за {timeout} с") from e
    if res.returncode != 0:
        err = (res.stderr or res.stdout).decode("utf-8", "replace").strip()
        raise EmulatorError(f"adb {' '.join(args[:2])}: {err[:300]}")
    return res.stdout if binary else res.stdout.decode("utf-8", "replace")


def connect(addr: str) -> str:
    """Подключается к устройству и возвращает его serial."""
    addr = (addr or "").strip()
    if not ADDR_RE.match(addr):
        raise EmulatorError("Адрес вида 192.168.1.10:5555 или emulator-5554")
    if ":" in addr:
        out = _adb("connect", addr, timeout=20)
        if "connected" not in out and "already" not in out:
            raise EmulatorError(f"Не подключился к {addr}: {out.strip()}")
    devices = {d["serial"]: d for d in parse_devices(_adb("devices", "-l"))}
    dev = devices.get(addr)
    if not dev:
        raise EmulatorError(f"{addr} нет в списке устройств adb")
    if dev["state"] != "device":
        raise EmulatorError(f"{addr}: состояние «{dev['state']}» (unauthorized — подтвердите отладку на устройстве)")
    return addr


def device_info(addr: str) -> dict:
    serial = connect(addr)
    prop = lambda k: _adb("shell", "getprop", k, serial=serial).strip()  # noqa: E731
    pkg = pick_tiktok_package(_adb("shell", "pm", "list", "packages", serial=serial))
    return {
        "serial": serial,
        "model": prop("ro.product.model"),
        "android": prop("ro.build.version.release"),
        "emulator": prop("ro.kernel.qemu") == "1" or prop("ro.hardware") in ("ranchu", "goldfish"),
        "tiktok_package": pkg,
    }


def _screenshot(serial: str, tag: str) -> str:
    settings.ensure_dirs()
    name = f"emu_{tag}_{uuid.uuid4().hex[:8]}.png"
    data = _adb("exec-out", "screencap", "-p", serial=serial, binary=True, timeout=30)
    with open(os.path.join(settings.output_dir, name), "wb") as f:
        f.write(data)
    return name


def _screen(serial: str, attempts: int = 4) -> Screen:
    """Дерево экрана. В редакторе крутится ролик, и uiautomator не всегда
    дожидается «покоя» экрана — тогда файл не пишется, пробуем ещё раз."""
    for i in range(attempts):
        _adb("shell", "rm", "-f", "/sdcard/vp_ui.xml", serial=serial)
        _adb("shell", "uiautomator", "dump", "/sdcard/vp_ui.xml", serial=serial, timeout=30)
        try:
            return parse_ui_dump(_adb("shell", "cat", "/sdcard/vp_ui.xml", serial=serial))
        except EmulatorError:
            if i == attempts - 1:
                raise EmulatorError("Не удалось снять дерево экрана (uiautomator)") from None
            time.sleep(2)
    return Screen()


def test_upload(addr: str, video_path: str, *, go_to_post: bool = False,
                wait_seconds: int = 12) -> dict:
    """Кладёт ролик в галерею, расшаривает его в TikTok и докладывает, что на экране.

    «Опубликовать» не нажимается: go_to_post только проходит «Далее» до экрана
    публикации, чтобы было видно, что приложение приняло ролик.
    """
    steps: list[str] = []
    log = steps.append
    info = device_info(addr)
    serial, pkg = info["serial"], info["tiktok_package"]
    log(f"Устройство {info['model']} (Android {info['android']})"
        + (", эмулятор" if info["emulator"] else ""))
    if not pkg:
        raise EmulatorError("Приложение TikTok на устройстве не установлено")
    log(f"TikTok: {pkg}")

    fname = f"vp_{uuid.uuid4().hex[:10]}.mp4"
    remote = f"/sdcard/DCIM/Camera/{fname}"
    _adb("shell", "mkdir", "-p", "/sdcard/DCIM/Camera", serial=serial)
    # Ролики прошлых проверок убираем: иначе каждый тест оставлял файл в галерее.
    # Текущий остаётся — он открыт в TikTok и нужен, пока человек смотрит экран.
    _adb("shell", "rm -f /sdcard/DCIM/Camera/vp_*.mp4", serial=serial)
    _adb("push", video_path, remote, serial=serial, timeout=600)
    log(f"Ролик загружен на устройство: {remote}")

    # Регистрируем в медиатеке и берём content:// — file:// приложения не принимают.
    # Ищем по имени файла: в _data медиатека пишет /storage/emulated/0/…, а не /sdcard/…
    _adb("shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
         "-d", f"file://{remote}", serial=serial)
    media_id = None
    for _ in range(10):
        time.sleep(1)
        out = _adb("shell", "content", "query", "--uri", "content://media/external/video/media",
                   "--projection", "_id:_display_name", serial=serial)
        media_id = parse_media_id(out, fname)
        if media_id:
            break
    if not media_id:
        raise EmulatorError("Медиатека не увидела ролик — сканирование не прошло")
    uri = f"content://media/external/video/media/{media_id}"
    log(f"В медиатеке: {uri}")

    _adb("shell", "am", "start", "-a", "android.intent.action.SEND", "-t", "video/mp4",
         "--eu", "android.intent.extra.STREAM", uri, "--grant-read-uri-permission",
         "-p", pkg, serial=serial)
    log("Открыл TikTok через «Поделиться»")
    time.sleep(wait_seconds)

    screen = _screen(serial)
    state = classify(screen, pkg)
    if go_to_post:
        for _ in range(3):
            if state != "editor":
                break
            btn = screen.find(NEXT_LABELS)
            _adb("shell", "input", "tap", str(btn.center[0]), str(btn.center[1]), serial=serial)
            log("Нажал «Далее»")
            time.sleep(4)
            screen = _screen(serial)
            state = classify(screen, pkg)

    shot = _screenshot(serial, state)
    log(f"Итог: {SCREEN_LABELS[state]}")
    return {"ok": state in ("editor", "post"), "state": state, "steps": steps,
            "screenshot": shot, "texts": screen.texts()[:40], "device": info}
