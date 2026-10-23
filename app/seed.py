"""Fill the database with demo links and a week of realistic-looking clicks.

    python -m app.seed

Safe to run more than once: links that already exist are skipped.
"""

import os
import random
from contextlib import closing
from datetime import datetime, time, timedelta, timezone

from . import db

DEMO_LINKS = [
    ("fastapi-docs", "https://fastapi.tiangolo.com/tutorial/"),
    ("leetcode-75", "https://leetcode.com/studyplan/leetcode-75/"),
    ("sqlite-wal", "https://www.sqlite.org/wal.html"),
    ("gh-trending", "https://github.com/trending"),
]

# (value, relative weight)
REFERRERS = [("Direct", 5), ("linkedin.com", 4), ("google.com", 3), ("t.co", 2), ("github.com", 2)]
BROWSERS = [("Chrome", 6), ("Safari", 3), ("Firefox", 2), ("Edge", 1)]
DEVICES = [("Desktop", 5), ("Mobile", 4), ("Tablet", 1)]


def _pick(rng: random.Random, weighted: list[tuple[str, int]]) -> str:
    values, weights = zip(*weighted)
    return rng.choices(values, weights=weights)[0]


def seed(db_path: str, rng: random.Random | None = None) -> int:
    """Insert the demo links; returns how many were added."""
    rng = rng or random.Random(42)
    db.init_db(db_path)
    now = db.utcnow()
    added = 0

    with closing(db.connect(db_path)) as conn:
        for code, url in DEMO_LINKS:
            if conn.execute("SELECT 1 FROM links WHERE code = ?", (code,)).fetchone():
                continue
            cur = conn.execute(
                "INSERT INTO links (code, target_url, created_at) VALUES (?, ?, ?)",
                (code, url, (now - timedelta(days=8)).isoformat()),
            )
            clicks = []
            for days_ago in range(7):
                day_start = datetime.combine(now.date() - timedelta(days=days_ago), time(), tzinfo=timezone.utc)
                latest = int((now - day_start).total_seconds()) if days_ago == 0 else 86_399
                for _ in range(rng.randint(3, 24)):
                    clicked_at = day_start + timedelta(seconds=rng.randint(0, latest))
                    clicks.append((cur.lastrowid, clicked_at.isoformat(), _pick(rng, REFERRERS),
                                   _pick(rng, BROWSERS), _pick(rng, DEVICES)))
            conn.executemany(
                "INSERT INTO clicks (link_id, clicked_at, referrer, browser, device) VALUES (?, ?, ?, ?, ?)",
                clicks,
            )
            added += 1
        conn.commit()
    return added


if __name__ == "__main__":
    path = os.getenv("SNIP_DB_PATH", "snip.db")
    print(f"Added {seed(path)} demo links to {path}")
