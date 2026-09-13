"""Настройка «Разрешить общий прокси».

По умолчанию один proxy_url двум аккаунтам не назначить: общий IP — повод для
TikTok связать их. Настройка снимает запрет осознанно, поэтому проверяем оба
состояния, а не только «разрешено».
"""
from __future__ import annotations

PROXY = "http://user:pass@10.0.0.1:8080"


def _make(client, name, proxy=None):
    body = {"name": name, "platform": "tiktok"}
    if proxy:
        body["proxy_url"] = proxy
    return client.post("/api/accounts", json=body)


def test_shared_proxy_is_rejected_by_default(client):
    client.post("/api/settings", json={"allow_shared_proxy": False})
    assert _make(client, "первый", PROXY).status_code in (200, 201)
    r = _make(client, "второй", PROXY)
    assert r.status_code == 409
    assert "уже привязан" in r.text


def test_shared_proxy_allowed_when_enabled(client):
    saved = client.post("/api/settings", json={"allow_shared_proxy": True})
    assert saved.status_code == 200 and saved.json()["allow_shared_proxy"] is True
    r = _make(client, "третий", PROXY)
    assert r.status_code in (200, 201), r.text
    # и через правку существующего аккаунта тоже
    acc_id = _make(client, "четвёртый").json()["id"]
    assert client.patch(f"/api/accounts/{acc_id}",
                        json={"proxy_url": PROXY}).status_code == 200
    client.post("/api/settings", json={"allow_shared_proxy": False})
