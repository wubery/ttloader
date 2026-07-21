from fastapi.testclient import TestClient

from app.main import app
from app.services.media import build_overlay_filter

with TestClient(app) as c:
    r = c.get("/api/health")
    print("health:", r.status_code, r.json().get("status"),
          "ffmpeg=", r.json().get("ffmpeg"), "pw=", r.json().get("playwright"))

    r = c.post("/api/accounts",
               json={"name": "acc1", "platform": "tiktok",
                     "proxy_url": "http://user:pass@1.2.3.4:8080"})
    print("create account:", r.status_code, r.json().get("has_cookies"), r.json().get("proxy_url"))

    r = c.get("/api/accounts")
    print("list accounts:", r.status_code, len(r.json()))

    r = c.post("/api/jobs", json={"account_id": 1, "video_id": 1})
    print("job no cookies -> reject:", r.status_code, r.json().get("detail"))

    r = c.post("/api/accounts", json={"name": "bad", "platform": "tiktok",
                                      "proxy_url": "not-a-url"})
    print("bad proxy -> reject:", r.status_code)

print("filter(image):", build_overlay_filter(1080, False, 0.05, 0.8, 0.25, 1.0))
print("filter(video):", build_overlay_filter(1080, True, 0.1, 0.1, 0.3, 0.5))
