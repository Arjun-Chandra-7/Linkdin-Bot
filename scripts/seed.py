#!/usr/bin/env python3
"""Seed default content sources and start the daily loop.

Run once after first setup:

    python scripts/seed.py --github Arjun-Chandra-7/Linkdin-Bot

Sources are only a starting point - add, remove and reweight them from the app
or by editing the sources table. Your own repository is the most valuable one,
because commits and releases are a factual record of what you actually built.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.logging import configure_logging  # noqa: E402
from app.database.enums import ContentCategory, SourceType  # noqa: E402
from app.database.migrations import run_migrations  # noqa: E402
from app.database.models import Source  # noqa: E402
from app.database.session import session_scope  # noqa: E402
from app.jobs.queue import enqueue  # noqa: E402

# Public engineering/AI feeds. Deliberately a short list: the goal is a few
# good sources, not a firehose that turns the account into a news reflector.
DEFAULT_FEEDS: list[tuple[str, str, ContentCategory, float]] = [
    (
        "Simon Willison",
        "https://simonwillison.net/atom/everything/",
        ContentCategory.AI_OBSERVATION,
        1.1,
    ),
    (
        "Hacker News front page",
        "https://hnrss.org/frontpage?points=200",
        ContentCategory.AI_OBSERVATION,
        0.8,
    ),
    (
        "Anthropic news",
        "https://www.anthropic.com/news/rss.xml",
        ContentCategory.AI_OBSERVATION,
        1.0,
    ),
    ("Julia Evans", "https://jvns.ca/atom.xml", ContentCategory.TECHNICAL_LESSON, 1.0),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed sources and start the daily loop")
    parser.add_argument(
        "--github",
        action="append",
        default=[],
        help="owner/repo to follow (repeatable). Your own projects.",
    )
    parser.add_argument("--no-feeds", action="store_true", help="Skip the default RSS feeds")
    parser.add_argument("--no-loop", action="store_true", help="Do not enqueue the daily loop")
    args = parser.parse_args()

    configure_logging()
    run_migrations()

    added = 0
    with session_scope() as db:
        existing = {s.url for s in db.query(Source).all() if s.url}

        if not args.no_feeds:
            for name, url, category, weight in DEFAULT_FEEDS:
                if url in existing:
                    continue
                db.add(
                    Source(
                        name=name, type=SourceType.RSS, url=url, category=category, weight=weight
                    )
                )
                added += 1
                print(f"  + feed    {name}")

        for repo in args.github:
            repo = repo.strip().removeprefix("https://github.com/").strip("/")
            url = f"https://github.com/{repo}"
            if url in existing:
                continue
            db.add(
                Source(
                    name=f"GitHub: {repo}",
                    type=SourceType.GITHUB,
                    url=url,
                    category=ContentCategory.BUILD_LOG,
                    weight=1.5,
                    config={"repo": repo},
                )
            )
            added += 1
            print(f"  + project {repo}")

        if not args.no_loop:
            enqueue(db, "daily_loop", {}, idempotency_key="daily-loop-bootstrap")
            print("  + queued the daily discovery loop")

    print(f"\n{added} source(s) added.")
    if not args.github:
        print("Tip: add your own repo with --github owner/repo - it is the best source there is.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
