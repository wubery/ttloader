"""Тестовая заливка через эмулятор: разбор вывода adb и экрана, эндпоинты."""
from __future__ import annotations

import pytest

from app.services import emulator

DEVICES = """List of devices attached
emulator-5556          device product:sdk_gphone64 model:Pixel_7 device:emu64x transport_id:3
192.168.1.20:5555      unauthorized transport_id:4

"""

UI_EDITOR = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="" content-desc="" package="com.zhiliaoapp.musically" bounds="[0,0][1080,2400]">
    <node text="Звуки" content-desc="" clickable="true" package="com.zhiliaoapp.musically" bounds="[400,100][680,180]" />
    <node text="Далее" content-desc="" clickable="true" package="com.zhiliaoapp.musically" bounds="[800,2200][1040,2320]" />
  </node>
</hierarchy>"""


def test_parse_devices():
    devs = emulator.parse_devices(DEVICES)
    assert devs == [{"serial": "emulator-5556", "state": "device", "model": "Pixel_7"},
                    {"serial": "192.168.1.20:5555", "state": "unauthorized", "model": ""}]


def test_pick_tiktok_package_prefers_global():
    out = "package:com.android.chrome\npackage:com.ss.android.ugc.trill\npackage:com.zhiliaoapp.musically\n"
    assert emulator.pick_tiktok_package(out) == "com.zhiliaoapp.musically"
    assert emulator.pick_tiktok_package("package:com.android.chrome\n") is None


def test_parse_media_id():
    out = ("Row: 0 _id=1000000021, _display_name=vp_old.mp4\n"
           "Row: 1 _id=1000000023, _display_name=vp_new.mp4\n")
    assert emulator.parse_media_id(out, "vp_new.mp4") == "1000000023"
    assert emulator.parse_media_id(out, "vp_missing.mp4") is None
    assert emulator.parse_media_id("No result found.", "vp_new.mp4") is None


def test_ui_dump_editor_screen():
    screen = emulator.parse_ui_dump(UI_EDITOR)
    assert screen.package == "com.zhiliaoapp.musically"
    assert emulator.classify(screen, "com.zhiliaoapp.musically") == "editor"
    assert screen.find(emulator.NEXT_LABELS).center == (920, 2260)


@pytest.mark.parametrize("label,state", [("Опубликовать", "post"), ("Post", "post"),
                                         ("Войти в TikTok", "login"), ("Что-то", "unknown")])
def test_classify(label, state):
    xml = (f'<hierarchy><node text="{label}" package="com.zhiliaoapp.musically" '
           f'bounds="[0,0][10,10]" /></hierarchy>')
    assert emulator.classify(emulator.parse_ui_dump(xml), "com.zhiliaoapp.musically") == state


def test_classify_other_app_and_bad_xml():
    xml = '<hierarchy><node text="Далее" package="android" bounds="[0,0][10,10]" /></hierarchy>'
    assert emulator.classify(emulator.parse_ui_dump(xml), "com.zhiliaoapp.musically") == "other_app"
    assert emulator.parse_ui_dump("not xml").nodes == []


@pytest.mark.parametrize("addr", ["", "rm -rf /", "host:abc", "1.2.3.4:5555;ls"])
def test_connect_rejects_bad_address(addr):
    with pytest.raises(emulator.EmulatorError):
        emulator.connect(addr)


def test_connect_reports_unauthorized(monkeypatch):
    def fake_adb(*args, **_kw):
        return "already connected" if args[0] == "connect" else DEVICES

    monkeypatch.setattr(emulator, "_adb", fake_adb)
    with pytest.raises(emulator.EmulatorError, match="unauthorized"):
        emulator.connect("192.168.1.20:5555")
    assert emulator.connect("emulator-5556") == "emulator-5556"


def test_missing_adb_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(emulator.settings, "adb_bin", "definitely-no-adb-here")
    with pytest.raises(emulator.EmulatorError, match="adb не найден"):
        emulator._adb("devices")


def test_device_endpoint_maps_errors(client, monkeypatch):
    def boom(_addr):
        raise emulator.EmulatorError("нет устройства")

    monkeypatch.setattr(emulator, "device_info", boom)
    r = client.post("/api/emulator/device", json={"addr": "emulator-5554"})
    assert r.status_code == 400 and "нет устройства" in r.json()["detail"]


def test_test_upload_endpoint_unknown_video(client):
    r = client.post("/api/emulator/test-upload", json={"addr": "emulator-5554", "video_id": 999999})
    assert r.status_code == 404


def test_screenshot_name_is_validated(client):
    assert client.get("/api/emulator/screenshot/..%2Fsecret.key").status_code == 404
    assert client.get("/api/emulator/screenshot/emu_post_deadbeef.png").status_code == 404
