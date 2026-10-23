"""Snip: a URL shortener with click analytics.

Run with:  uvicorn app.main:app --reload
"""

import io
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from typing import Annotated, Iterator

import segno
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .ratelimit import SlidingWindowRateLimiter
from .schemas import Count, DailyCount, Link, LinkCreate, LinkStats
from .shortcode import generate_code, validate_alias
from .useragent import parse_user_agent, referrer_domain

STATIC_DIR = Path(__file__).parent / "static"
CODE_ATTEMPTS = 5

router = APIRouter()


# --------------------------------------------------------------------------- helpers

def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = db.connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

LINK_QUERY = """
SELECT l.id, l.code, l.target_url, l.created_at, l.expires_at,
       (SELECT COUNT(*) FROM clicks c WHERE c.link_id = l.id) AS clicks
FROM links l
"""


def short_url(request: Request, code: str) -> str:
    return f"{request.base_url}{code}"


def to_link(request: Request, row: sqlite3.Row) -> Link:
    return Link(
        code=row["code"],
        short_url=short_url(request, row["code"]),
        target_url=row["target_url"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        clicks=row["clicks"],
    )


def fetch_link(conn: sqlite3.Connection, code: str) -> sqlite3.Row:
    row = conn.execute(LINK_QUERY + " WHERE l.code = ?", (code,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Short link not found.")
    return row


def is_expired(row: sqlite3.Row) -> bool:
    return row["expires_at"] is not None and datetime.fromisoformat(row["expires_at"]) <= db.utcnow()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def error_page(status_code: int, message: str) -> HTMLResponse:
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Snip · {status_code}</title>
<link rel="stylesheet" href="/static/styles.css"></head>
<body><main class="error-page"><h1>{status_code}</h1><p>{escape(message)}</p>
<a class="button" href="/">Create a short link</a></main></body></html>"""
    return HTMLResponse(body, status_code=status_code)


# --------------------------------------------------------------------------- API

@router.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/links", response_model=Link, status_code=status.HTTP_201_CREATED, tags=["links"])
def create_link(payload: LinkCreate, request: Request, conn: Conn) -> Link:
    """Shorten a URL, optionally with a custom alias and an expiry."""
    limiter: SlidingWindowRateLimiter = request.app.state.limiter
    ip = client_ip(request)
    if not limiter.allow(ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many links created. Please slow down.",
            headers={"Retry-After": str(limiter.retry_after(ip))},
        )

    # Refuse links back to this service, which would only redirect in a loop.
    own_port = request.url.port or (443 if request.url.scheme == "https" else 80)
    if (payload.url.host, payload.url.port) == (request.url.hostname, own_port):
        raise HTTPException(422, "That URL already points to this shortener.")

    if payload.alias is not None:
        if error := validate_alias(payload.alias):
            raise HTTPException(422, error)
        candidates: Iterator[str] = iter([payload.alias])
    else:
        candidates = (generate_code() for _ in range(CODE_ATTEMPTS))

    now = db.utcnow()
    expires_at = (now + timedelta(days=payload.expires_in_days)).isoformat() if payload.expires_in_days else None

    # The UNIQUE constraint on `code` is the source of truth for collisions,
    # so two concurrent requests can never end up with the same code.
    for code in candidates:
        try:
            conn.execute(
                "INSERT INTO links (code, target_url, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (code, str(payload.url), now.isoformat(), expires_at),
            )
            conn.commit()
            break
        except sqlite3.IntegrityError:
            continue
    else:
        if payload.alias is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Alias '{payload.alias}' is already taken.")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Could not allocate a short code. Please retry.")

    return to_link(request, fetch_link(conn, code))


@router.get("/api/links", response_model=list[Link], tags=["links"])
def list_links(request: Request, conn: Conn, limit: int = Query(20, ge=1, le=100)) -> list[Link]:
    """Most recently created links first."""
    rows = conn.execute(LINK_QUERY + " ORDER BY l.id DESC LIMIT ?", (limit,)).fetchall()
    return [to_link(request, row) for row in rows]


@router.get("/api/links/{code}", response_model=Link, tags=["links"])
def get_link(code: str, request: Request, conn: Conn) -> Link:
    return to_link(request, fetch_link(conn, code))


@router.delete("/api/links/{code}", status_code=status.HTTP_204_NO_CONTENT, tags=["links"])
def delete_link(code: str, conn: Conn) -> Response:
    """Delete a link and (via ON DELETE CASCADE) all of its clicks."""
    cur = conn.execute("DELETE FROM links WHERE code = ?", (code,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Short link not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/links/{code}/stats", response_model=LinkStats, tags=["analytics"])
def link_stats(code: str, conn: Conn) -> LinkStats:
    """Click totals, a 7-day histogram and the top referrers, browsers and devices."""
    link = fetch_link(conn, code)
    link_id = link["id"]

    today = db.utcnow().date()
    days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    per_day = dict(
        conn.execute(
            "SELECT substr(clicked_at, 1, 10) AS day, COUNT(*) FROM clicks "
            "WHERE link_id = ? AND clicked_at >= ? GROUP BY day",
            (link_id, days[0].isoformat()),
        ).fetchall()
    )

    def top(column: str) -> list[Count]:
        # `column` is always one of the literals below, never user input.
        rows = conn.execute(
            f"SELECT {column}, COUNT(*) AS n FROM clicks WHERE link_id = ? "
            f"GROUP BY {column} ORDER BY n DESC, {column} LIMIT 5",
            (link_id,),
        ).fetchall()
        return [Count(label=label, clicks=n) for label, n in rows]

    return LinkStats(
        code=link["code"],
        target_url=link["target_url"],
        total_clicks=link["clicks"],
        last_7_days=[DailyCount(date=d.isoformat(), clicks=per_day.get(d.isoformat(), 0)) for d in days],
        referrers=top("referrer"),
        browsers=top("browser"),
        devices=top("device"),
    )


@router.get(
    "/api/links/{code}/qr",
    tags=["links"],
    response_class=Response,
    responses={200: {"content": {"image/svg+xml": {}}, "description": "QR code for the short URL."}},
)
def link_qr(code: str, request: Request, conn: Conn) -> Response:
    fetch_link(conn, code)
    buffer = io.BytesIO()
    segno.make(short_url(request, code), error="m").save(buffer, kind="svg", scale=6, border=2, xmldecl=False)
    return Response(buffer.getvalue(), media_type="image/svg+xml")


# Must be registered last: it matches any single path segment.
@router.get("/{code}", tags=["redirect"], status_code=status.HTTP_302_FOUND)
def follow(code: str, request: Request, conn: Conn) -> Response:
    """Redirect to the target URL and record the click.

    302 rather than 301: browsers cache 301s and would skip us (and the
    analytics) on repeat visits.
    """
    wants_html = "text/html" in request.headers.get("accept", "")
    try:
        link = fetch_link(conn, code)
    except HTTPException as exc:
        if wants_html:
            return error_page(exc.status_code, "This short link doesn't exist.")
        raise

    if is_expired(link):
        message = "This short link has expired."
        if wants_html:
            return error_page(status.HTTP_410_GONE, message)
        raise HTTPException(status.HTTP_410_GONE, message)

    browser, device = parse_user_agent(request.headers.get("user-agent"))
    conn.execute(
        "INSERT INTO clicks (link_id, clicked_at, referrer, browser, device) VALUES (?, ?, ?, ?, ?)",
        (link["id"], db.utcnow().isoformat(), referrer_domain(request.headers.get("referer")), browser, device),
    )
    conn.commit()
    return RedirectResponse(link["target_url"], status_code=status.HTTP_302_FOUND)


# --------------------------------------------------------------------------- app factory

def create_app(db_path: str | None = None, rate_limit: int | None = None) -> FastAPI:
    db_path = db_path or os.getenv("SNIP_DB_PATH", "snip.db")
    rate_limit = rate_limit if rate_limit is not None else int(os.getenv("SNIP_RATE_LIMIT", "30"))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        db.init_db(db_path)
        yield

    app = FastAPI(
        title="Snip",
        version="1.0.0",
        summary="A URL shortener with click analytics.",
        lifespan=lifespan,
    )
    app.state.db_path = db_path
    app.state.limiter = SlidingWindowRateLimiter(limit=rate_limit, window_seconds=60)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(router)
    return app


app = create_app()
