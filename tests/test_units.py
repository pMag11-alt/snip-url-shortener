from app.ratelimit import SlidingWindowRateLimiter
from app.shortcode import ALPHABET, generate_code, validate_alias
from app.useragent import parse_user_agent, referrer_domain


def test_generate_code_uses_base62():
    codes = {generate_code() for _ in range(1000)}
    assert len(codes) == 1000  # no collisions in a small sample
    assert all(len(code) == 6 and set(code) <= set(ALPHABET) for code in codes)
    assert len(generate_code(10)) == 10


def test_validate_alias():
    assert validate_alias("my_link-2026") is None
    assert validate_alias("API") is not None  # reserved, case-insensitive
    assert validate_alias("x" * 33) is not None
    assert validate_alias("bad/alias") is not None


def test_rate_limiter_slides():
    now = [0.0]
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=10, clock=lambda: now[0])

    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")  # limits are per client
    assert limiter.retry_after("a") == 10

    now[0] = 9.5
    assert not limiter.allow("a")
    now[0] = 10.0  # first hit has left the window
    assert limiter.allow("a")


def test_parse_user_agent():
    edge = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/130.0 Safari/537.36 Edg/130.0"
    firefox = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
    android = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36"
    ipad = "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Safari/604.1"
    googlebot = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"

    assert parse_user_agent(edge) == ("Edge", "Desktop")
    assert parse_user_agent(firefox) == ("Firefox", "Desktop")
    assert parse_user_agent(android) == ("Chrome", "Mobile")
    assert parse_user_agent(ipad) == ("Safari", "Tablet")
    assert parse_user_agent(googlebot)[1] == "Bot"
    assert parse_user_agent("curl/8.7.1") == ("curl", "Desktop")
    assert parse_user_agent(None) == ("Unknown", "Unknown")


def test_referrer_domain():
    assert referrer_domain("https://www.google.com/search?q=snip") == "google.com"
    assert referrer_domain("https://t.co/abc") == "t.co"
    assert referrer_domain(None) == "Direct"
    assert referrer_domain("garbage") == "Direct"


def test_seed_is_idempotent_and_feeds_stats(make_client, tmp_path):
    from app.seed import DEMO_LINKS, seed

    client = make_client()
    assert seed(str(tmp_path / "test.db")) == len(DEMO_LINKS)
    assert seed(str(tmp_path / "test.db")) == 0

    stats = client.get(f"/api/links/{DEMO_LINKS[0][0]}/stats").json()
    assert stats["total_clicks"] > 0
    assert sum(day["clicks"] for day in stats["last_7_days"]) == stats["total_clicks"]
