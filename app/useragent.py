"""Tiny User-Agent and Referer parsing for click analytics.

Real projects would use a library such as `ua-parser`; these heuristics
cover the common browsers without adding a dependency.
"""

from urllib.parse import urlparse

# Order matters: Edge and Opera UAs also contain "chrome", and Chrome UAs
# also contain "safari".
_BROWSERS = (
    ("edg/", "Edge"),
    ("opr/", "Opera"),
    ("firefox/", "Firefox"),
    ("fxios/", "Firefox"),
    ("crios/", "Chrome"),
    ("chrome/", "Chrome"),
    ("safari/", "Safari"),
    ("curl/", "curl"),
    ("python", "Python"),
)


def parse_user_agent(ua: str | None) -> tuple[str, str]:
    """Return (browser, device) for a User-Agent header."""
    if not ua:
        return "Unknown", "Unknown"
    s = ua.lower()

    if any(word in s for word in ("bot", "spider", "crawl")):
        device = "Bot"
    elif "ipad" in s or "tablet" in s:
        device = "Tablet"
    elif any(word in s for word in ("mobi", "iphone", "android")):
        device = "Mobile"
    else:
        device = "Desktop"

    browser = next((name for token, name in _BROWSERS if token in s), "Other")
    return browser, device


def referrer_domain(referer: str | None) -> str:
    """Reduce a Referer header to its host, or 'Direct' when absent."""
    if not referer:
        return "Direct"
    host = urlparse(referer).netloc.lower()
    return host.removeprefix("www.") or "Direct"
