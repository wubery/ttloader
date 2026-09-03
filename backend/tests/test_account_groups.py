"""Группы аккаунтов: CRUD, привязка аккаунта и отвязка при удалении группы."""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def group(client):
    r = client.post("/api/account-groups", json={"name": "Прогретые", "color": "#22c55e"})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def account(client):
    r = client.post("/api/accounts", json={"name": "acc-groups", "platform": "tiktok",
                                           "start_login": False})
    assert r.status_code == 200, r.text
    return r.json()


def test_create_and_list(client, group):
    assert group["name"] == "Прогретые"
    assert group["color"] == "#22c55e"
    assert group["accounts_count"] == 0
    ids = [g["id"] for g in client.get("/api/account-groups").json()]
    assert group["id"] in ids


def test_duplicate_name_other_case_rejected(client, group):
    r = client.post("/api/account-groups", json={"name": "прогретые"})
    assert r.status_code == 409, r.text


def test_empty_name_rejected(client):
    assert client.post("/api/account-groups", json={"name": "   "}).status_code == 400


def test_assign_group_to_account(client, group, account):
    """Регрессия: PATCH раньше молча выбрасывал такие поля."""
    r = client.patch(f"/api/accounts/{account['id']}", json={"group_id": group["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["group_id"] == group["id"]
    # и правда сохранилось, а не только вернулось в ответе
    fresh = next(a for a in client.get("/api/accounts").json() if a["id"] == account["id"])
    assert fresh["group_id"] == group["id"]


def test_accounts_count_follows_assignment(client, group):
    row = next(g for g in client.get("/api/account-groups").json() if g["id"] == group["id"])
    assert row["accounts_count"] == 1


def test_unknown_group_rejected(client, account):
    assert client.patch(f"/api/accounts/{account['id']}", json={"group_id": 999999}).status_code == 404


def test_clear_group(client, account, group):
    r = client.patch(f"/api/accounts/{account['id']}", json={"group_id": None})
    assert r.status_code == 200, r.text
    assert r.json()["group_id"] is None
    client.patch(f"/api/accounts/{account['id']}", json={"group_id": group["id"]})  # вернём обратно


def test_other_fields_survive_partial_patch(client, account, group):
    """Правка имени не должна сбрасывать группу — поля без ключа в запросе не трогаем."""
    r = client.patch(f"/api/accounts/{account['id']}", json={"name": "acc-groups-2"})
    assert r.status_code == 200, r.text
    assert r.json()["group_id"] == group["id"]


def test_uniq_profile_id_persists(client, account):
    """Тот же баг был у профиля уникализации — селектор ничего не сохранял."""
    p = client.post("/api/uniq-profiles", json={"name": "гипотеза A"})
    assert p.status_code == 200, p.text
    pid = p.json()["id"]
    r = client.patch(f"/api/accounts/{account['id']}", json={"uniq_profile_id": pid})
    assert r.status_code == 200, r.text
    assert r.json()["uniq_profile_id"] == pid
    assert client.patch(f"/api/accounts/{account['id']}",
                        json={"uniq_profile_id": None}).json()["uniq_profile_id"] is None


def test_rename_and_recolor(client, group):
    r = client.patch(f"/api/account-groups/{group['id']}", json={"name": "Прогретые+", "color": "#3b82f6"})
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["color"]) == ("Прогретые+", "#3b82f6")


def test_delete_detaches_accounts_but_keeps_them(client, group, account):
    r = client.delete(f"/api/account-groups/{group['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["detached"] == 1
    fresh = next(a for a in client.get("/api/accounts").json() if a["id"] == account["id"])
    assert fresh["group_id"] is None                      # аккаунт жив, привязка снята
    assert client.delete(f"/api/account-groups/{group['id']}").status_code == 404
