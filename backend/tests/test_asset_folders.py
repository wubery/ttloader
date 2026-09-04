"""Папки библиотек: CRUD, привязка к группам и сужение случайного выбора при рендере."""
from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.models import Background, Hook
from app.services import folders as folders_service
from app.services.runner import _pick_assets


@pytest.fixture(scope="module")
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture(scope="module")
def group_ids(client):
    a = client.post("/api/account-groups", json={"name": "Папки-A"}).json()["id"]
    b = client.post("/api/account-groups", json={"name": "Папки-Б"}).json()["id"]
    return a, b


@pytest.fixture(scope="module")
def hooks(db):
    """Три хука: в папке группы A, в папке без групп и вовсе без папки."""
    rows = [Hook(name=n, filename=f"{n}.mp4") for n in ("h_a", "h_free", "h_none")]
    db.add_all(rows)
    db.commit()
    for r in rows:
        db.refresh(r)
    return {r.name: r.id for r in rows}


def test_create_folder_with_groups(client, group_ids):
    a, _ = group_ids
    r = client.post("/api/asset-folders", json={"kind": "hook", "name": "Только A", "group_ids": [a]})
    assert r.status_code == 200, r.text
    assert r.json()["group_ids"] == [a]
    assert r.json()["items_count"] == 0


def test_unknown_kind_rejected(client):
    assert client.post("/api/asset-folders",
                       json={"kind": "banner", "name": "x"}).status_code == 400


def test_duplicate_name_within_kind(client):
    assert client.post("/api/asset-folders",
                       json={"kind": "hook", "name": "только a"}).status_code == 409
    # в другой библиотеке то же имя разрешено — папки у библиотек свои
    assert client.post("/api/asset-folders",
                       json={"kind": "video", "name": "Только A"}).status_code == 200


def test_unknown_group_rejected(client):
    assert client.post("/api/asset-folders",
                       json={"kind": "hook", "name": "битая", "group_ids": [999999]}).status_code == 404


def test_assign_hook_to_folder(client, hooks):
    fid = next(f["id"] for f in client.get("/api/asset-folders?kind=hook").json()
               if f["name"] == "Только A")
    r = client.patch(f"/api/hooks/{hooks['h_a']}/folder", json={"folder_id": fid})
    assert r.status_code == 200, r.text
    assert r.json()["folder_id"] == fid
    row = next(f for f in client.get("/api/asset-folders?kind=hook").json() if f["id"] == fid)
    assert row["items_count"] == 1


def test_folder_of_other_kind_rejected(client, hooks):
    vid_folder = next(f["id"] for f in client.get("/api/asset-folders?kind=video").json())
    assert client.patch(f"/api/hooks/{hooks['h_none']}/folder",
                        json={"folder_id": vid_folder}).status_code == 404


def test_visibility_rules(client, db, hooks, group_ids):
    """Папка без групп и файл без папки доступны всем; папка с группой — только ей."""
    a, b = group_ids
    free = client.post("/api/asset-folders", json={"kind": "hook", "name": "Общая полка"}).json()
    client.patch(f"/api/hooks/{hooks['h_free']}/folder", json={"folder_id": free["id"]})
    db.expire_all()

    def names(gid):
        return {h.name for h in folders_service.visible_rows(db, Hook, "hook", gid)}

    assert names(a) >= {"h_a", "h_free", "h_none"}          # своя папка + полка + без папки
    assert "h_a" not in names(b)                            # чужая папка не видна
    assert {"h_free", "h_none"} <= names(b)
    assert names(None) >= {"h_a", "h_free", "h_none"}       # аккаунт без группы не ограничен


def test_regrouping_folder_changes_visibility(client, db, hooks, group_ids):
    a, b = group_ids
    fid = next(f["id"] for f in client.get("/api/asset-folders?kind=hook").json()
               if f["name"] == "Только A")
    client.patch(f"/api/asset-folders/{fid}", json={"group_ids": [a, b]})
    db.expire_all()
    assert "h_a" in {h.name for h in folders_service.visible_rows(db, Hook, "hook", b)}
    client.patch(f"/api/asset-folders/{fid}", json={"group_ids": [a]})


def test_pick_assets_respects_group(client, db, hooks, group_ids):
    """Случайный выбор хука при рендере не должен доставать чужой файл."""
    import os

    from app.config import settings

    a, b = group_ids
    settings.ensure_dirs()
    for name in ("h_a", "h_free", "h_none"):
        open(os.path.join(settings.hooks_dir, f"{name}.mp4"), "wb").close()

    params = {"hook": {"on": True, "random": True, "asset_id": None},
              "canvas": {"bg": "color"}, "overlay": {"on": False}, "ad": {"on": False}}

    # 40 попыток: при трёх кандидатах чужой файл выпал бы почти наверняка, будь он в выборке
    picked_b = {os.path.basename(_pick_assets(params, db, b)[0]) for _ in range(40)}
    assert "h_a.mp4" not in picked_b                  # папка группы A для Б закрыта
    assert picked_b <= {"h_free.mp4", "h_none.mp4"}

    picked_a = {os.path.basename(_pick_assets(params, db, a)[0]) for _ in range(40)}
    assert "h_a.mp4" in picked_a                      # своей группе файл достаётся


def test_delete_folder_frees_items(client, db, hooks):
    fid = next(f["id"] for f in client.get("/api/asset-folders?kind=hook").json()
               if f["name"] == "Только A")
    r = client.delete(f"/api/asset-folders/{fid}")
    assert r.status_code == 200 and r.json()["detached"] == 1, r.text
    db.expire_all()
    assert db.get(Hook, hooks["h_a"]).folder_id is None      # файл жив, доступен снова всем


def test_backgrounds_use_the_same_rules(client, db, group_ids):
    a, b = group_ids
    bg = Background(name="bg_a", filename="bg_a.png")
    db.add(bg)
    db.commit()
    db.refresh(bg)
    f = client.post("/api/asset-folders",
                    json={"kind": "background", "name": "Фоны A", "group_ids": [a]}).json()
    assert client.patch(f"/api/backgrounds/{bg.id}/folder",
                        json={"folder_id": f["id"]}).status_code == 200
    db.expire_all()
    assert "bg_a" in {r.name for r in folders_service.visible_rows(db, Background, "background", a)}
    assert "bg_a" not in {r.name for r in folders_service.visible_rows(db, Background, "background", b)}
