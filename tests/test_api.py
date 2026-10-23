import sqlite3

from app.shortcode import ALPHABET, DEFAULT_LENGTH

CHROME_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
IPHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"


def shorten(client, url="https://example.com/some/long/path", **extra):
    return client.post("/api/links", json={"url": url, **extra})


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_index_serves_frontend(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


def test_create_link_generates_base62_code(client):
    res = shorten(client)
    assert res.status_code == 201
    body = res.json()
    assert len(body["code"]) == DEFAULT_LENGTH
    assert set(body["code"]) <= set(ALPHABET)
    assert body["short_url"] == f"http://testserver/{body['code']}"
    assert body["target_url"] == "https://example.com/some/long/path"
    assert body["clicks"] == 0
    assert body["expires_at"] is None


def test_redirect_records_click(client):
    code = shorten(client).json()["code"]

    res = client.get(f"/{code}")
    assert res.status_code == 302
    assert res.headers["location"] == "https://example.com/some/long/path"
    assert client.get(f"/api/links/{code}").json()["clicks"] == 1


def test_custom_alias_and_conflict(client):
    assert shorten(client, alias="my-link").json()["code"] == "my-link"

    res = shorten(client, url="https://other.example", alias="my-link")
    assert res.status_code == 409
    assert "already taken" in res.json()["detail"]


def test_alias_is_validated(client):
    assert shorten(client, alias="no spaces!").status_code == 422
    assert shorten(client, alias="ab").status_code == 422
    assert shorten(client, alias="docs").status_code == 422  # reserved


def test_rejects_invalid_urls(client):
    assert shorten(client, url="not a url").status_code == 422
    assert shorten(client, url="ftp://example.com/file").status_code == 422
    assert shorten(client, url="javascript:alert(1)").status_code == 422


def test_rejects_links_to_itself(client):
    assert shorten(client, url="http://testserver/abc123").status_code == 422


def test_unknown_code_returns_404(client):
    assert client.get("/nope123").status_code == 404
    assert client.get("/api/links/nope123/stats").status_code == 404


def test_unknown_code_shows_html_page_to_browsers(client):
    res = client.get("/nope123", headers={"accept": "text/html"})
    assert res.status_code == 404
    assert "doesn&#x27;t exist" in res.text or "doesn't exist" in res.text


def test_expired_link_returns_410(client, tmp_path):
    code = shorten(client, expires_in_days=1).json()["code"]
    with sqlite3.connect(tmp_path / "test.db") as conn:
        conn.execute("UPDATE links SET expires_at = '2000-01-01T00:00:00+00:00' WHERE code = ?", (code,))

    assert client.get(f"/{code}").status_code == 410


def test_expiry_bounds(client):
    assert shorten(client, expires_in_days=0).status_code == 422
    assert shorten(client, expires_in_days=366).status_code == 422
    assert shorten(client, expires_in_days=7).json()["expires_at"] is not None


def test_stats_breakdown(client):
    code = shorten(client).json()["code"]
    client.get(f"/{code}", headers={"user-agent": CHROME_UA, "referer": "https://www.linkedin.com/feed/"})
    client.get(f"/{code}", headers={"user-agent": CHROME_UA, "referer": "https://www.linkedin.com/in/someone"})
    client.get(f"/{code}", headers={"user-agent": IPHONE_UA})

    stats = client.get(f"/api/links/{code}/stats").json()
    assert stats["total_clicks"] == 3
    assert len(stats["last_7_days"]) == 7
    assert stats["last_7_days"][-1]["clicks"] == 3  # all clicks happened today
    assert stats["referrers"] == [{"label": "linkedin.com", "clicks": 2}, {"label": "Direct", "clicks": 1}]
    assert stats["browsers"] == [{"label": "Chrome", "clicks": 2}, {"label": "Safari", "clicks": 1}]
    assert stats["devices"] == [{"label": "Desktop", "clicks": 2}, {"label": "Mobile", "clicks": 1}]


def test_list_links_newest_first(client):
    first = shorten(client, url="https://one.example").json()["code"]
    second = shorten(client, url="https://two.example").json()["code"]

    codes = [link["code"] for link in client.get("/api/links").json()]
    assert codes == [second, first]
    assert len(client.get("/api/links?limit=1").json()) == 1


def test_delete_cascades_clicks(client, tmp_path):
    code = shorten(client).json()["code"]
    client.get(f"/{code}")

    assert client.delete(f"/api/links/{code}").status_code == 204
    assert client.get(f"/{code}").status_code == 404
    assert client.delete(f"/api/links/{code}").status_code == 404
    with sqlite3.connect(tmp_path / "test.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM clicks").fetchone()[0] == 0


def test_qr_code_is_svg(client):
    code = shorten(client).json()["code"]
    res = client.get(f"/api/links/{code}/qr")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/svg+xml"
    assert res.text.lstrip().startswith("<svg")


def test_rate_limit(make_client):
    client = make_client(rate_limit=3)
    for _ in range(3):
        assert shorten(client).status_code == 201

    res = shorten(client)
    assert res.status_code == 429
    assert int(res.headers["retry-after"]) >= 1
