"""Откуда загрузчик берёт ник для ссылки на опубликованный ролик.

Ответ API публикации содержит только id ролика, а ссылка без ника — 404.
Порядок источников важен: сначала ник из аккаунта (бесплатно), потом раздел
«Контент» студии (там TikTok сам печатает ссылки на СВОИ ролики в рабочей
форме), и лишь в крайнем случае состояние страницы.

Отдельно проверяется, что наружу для сохранения в аккаунт отдаётся только
подтверждённый ник: по нику панель решает, чьи посты разрешено лайкать
(services/activity), и догадка в этом списке недопустима.
"""
from __future__ import annotations

from app.services.uploaders import tiktok

VIDEO_ID = "7683929703043829014"
GOOD = f"https://www.tiktok.com/@user914224979847/video/{VIDEO_ID}"
PUBLISH_RESPONSES = [(200, "https://x/api/post/item", '{"aweme_id":"%s"}' % VIDEO_ID)]


class FakePage:
    """Минимальная страница Playwright: адрес, переходы и evaluate по скрипту."""

    def __init__(self, links=(), own_handle=None, content_broken=False):
        self.url = "https://www.tiktok.com/tiktokstudio/upload?from=upload"
        self.links = list(links)
        self.own_handle = own_handle
        self.content_broken = content_broken
        self.visited: list[str] = []

    def goto(self, url, **_kw):
        if self.content_broken:
            raise RuntimeError("студия не открылась")
        self.visited.append(url)
        self.url = url

    def reload(self, **_kw):
        self.visited.append("reload")

    def wait_for_timeout(self, _ms):
        pass

    def evaluate(self, script, *_args):
        if script is tiktok.CONTENT_LINKS_JS:
            if self.content_broken:
                raise RuntimeError("список не отрисовался")
            return self.links
        return self.own_handle          # OWN_PROFILE_JS


def test_known_handle_needs_no_browsing():
    page = FakePage()
    url, save = tiktok._resolve_posted_url(page, PUBLISH_RESPONSES,
                                           handle="user914224979847")
    assert url == GOOD
    assert save is None                 # ник и так записан в аккаунте
    assert page.visited == []           # в «Контент» не ходили


def test_handle_taken_from_content_section():
    page = FakePage(links=[GOOD, "https://www.tiktok.com/@user914224979847/video/123456789"])
    url, save = tiktok._resolve_posted_url(page, PUBLISH_RESPONSES, handle=None)
    assert url == GOOD                  # ссылка от самого TikTok
    assert save == "user914224979847"   # ник подтверждён своими же роликами
    assert page.visited == [tiktok.CONTENT_URL]


def test_link_built_when_fresh_video_not_listed_yet():
    """Ролик ещё обрабатывается: ссылки на него в списке нет, но ник виден."""
    page = FakePage(links=["https://www.tiktok.com/@user914224979847/video/123456789"])
    url, save = tiktok._resolve_posted_url(page, PUBLISH_RESPONSES, handle=None)
    assert url == GOOD
    assert save == "user914224979847"
    assert "reload" in page.visited     # список перечитывали в ожидании ролика


def test_page_state_gives_link_but_not_a_saved_handle():
    page = FakePage(own_handle="@user914224979847", content_broken=True)
    url, save = tiktok._resolve_posted_url(page, PUBLISH_RESPONSES, handle=None)
    assert url == GOOD
    assert save is None                 # ник не подтверждён — в аккаунт не пишем


def test_no_handle_anywhere_means_no_link():
    page = FakePage(content_broken=True)
    assert tiktok._resolve_posted_url(page, PUBLISH_RESPONSES, handle=None) == (None, None)


def test_no_video_id_means_no_link():
    """Без id ролика ссылку составить не из чего, но ник запомнить можно."""
    page = FakePage(links=[GOOD])
    url, save = tiktok._resolve_posted_url(page, [(200, "u", "{}")], handle=None)
    assert url is None
    assert save == "user914224979847"


def test_known_handle_without_video_id():
    page = FakePage(content_broken=True)
    assert tiktok._resolve_posted_url(page, [], handle="user914224979847") == (None, None)


def test_video_id_read_from_various_fields():
    for field in ("aweme_id", "item_id", "video_id"):
        body = '{"status_code":0,"%s":"%s"}' % (field, VIDEO_ID)
        assert tiktok._publish_video_id([(200, "u", body)]) == VIDEO_ID
    assert tiktok._publish_video_id([(200, "u", "{}")]) is None
    assert tiktok._publish_video_id([]) is None
