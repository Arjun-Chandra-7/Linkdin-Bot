"""Content sources.

Sources are configuration, not code: the user adds feeds, project logs and
their own notes. Nothing here scrapes LinkedIn or anything behind a login -
these are public feeds and the user's own material.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from app.core.logging import log_event
from app.database.enums import ContentCategory, SourceType

log = logging.getLogger(__name__)

USER_AGENT = "linkedin-copilot/1.0 (personal content assistant)"
FETCH_TIMEOUT = 20.0


@dataclass
class RawItem:
    """One candidate item, before any scoring or model call."""

    title: str
    summary: str = ""
    url: str | None = None
    published_at: datetime | None = None
    category: ContentCategory = ContentCategory.AI_OBSERVATION
    source_name: str = ""
    extra: dict = field(default_factory=dict)


_COMMIT_PREFIX = re.compile(
    r"^(feat|fix|chore|docs|test|refactor|perf|ci|build|style)(\([^)]*\))?!?:\s*", re.I
)


def strip_commit_prefix(subject: str) -> str:
    """ "feat: add X" -> "add X". The prefix is noise in a post topic."""
    cleaned = _COMMIT_PREFIX.sub("", subject).strip()
    return cleaned or subject


def _iso_to_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_date(entry) -> datetime | None:
    from time import mktime

    for key in ("published_parsed", "updated_parsed"):
        value = getattr(entry, key, None) or (entry.get(key) if isinstance(entry, dict) else None)
        if value:
            try:
                return datetime.fromtimestamp(mktime(value))
            except (TypeError, ValueError, OverflowError):
                continue
    return None


def fetch_rss(
    url: str, *, source_name: str, category: ContentCategory, limit: int = 15
) -> list[RawItem]:
    """Read a public RSS/Atom feed."""
    import feedparser

    try:
        with httpx.Client(timeout=FETCH_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(url, follow_redirects=True)
            response.raise_for_status()
            body = response.content
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Could not fetch feed: {type(exc).__name__}") from exc

    parsed = feedparser.parse(body)
    items: list[RawItem] = []
    for entry in parsed.entries[:limit]:
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        summary = (entry.get("summary") or entry.get("description") or "").strip()
        # Feed summaries are frequently HTML; keep it as plain-ish text.
        summary = _strip_html(summary)[:800]
        items.append(
            RawItem(
                title=title,
                summary=summary,
                url=entry.get("link"),
                published_at=_parse_date(entry),
                category=category,
                source_name=source_name,
            )
        )
    return items


_TAG = None


def _strip_html(text: str) -> str:
    global _TAG
    if _TAG is None:
        import re

        _TAG = re.compile(r"<[^>]+>")
    import html

    return html.unescape(_TAG.sub(" ", text)).replace("\xa0", " ").strip()


def fetch_github_activity(
    repo: str, *, source_name: str, token: str | None = None, limit: int = 15
) -> list[RawItem]:
    """Recent commits and releases from the user's own repository.

    This is the highest-value source: it is a factual record of what the user
    actually built, which is exactly what the account is supposed to be about.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    items: list[RawItem] = []
    try:
        with httpx.Client(timeout=FETCH_TIMEOUT, headers=headers) as client:
            commits = client.get(
                f"https://api.github.com/repos/{repo}/commits", params={"per_page": limit}
            )
            if commits.status_code == 200:
                for commit in commits.json():
                    detail = commit.get("commit", {})
                    authored = (detail.get("author") or {}).get("date")
                    message = (detail.get("message") or "").split("\n")
                    subject = strip_commit_prefix(message[0].strip())
                    body = "\n".join(message[1:]).strip()
                    if not subject or subject.lower().startswith(("merge ", "bump ")):
                        continue
                    items.append(
                        RawItem(
                            title=subject[:300],
                            summary=body[:800],
                            url=commit.get("html_url"),
                            published_at=_iso_to_datetime(authored),
                            category=ContentCategory.BUILD_LOG,
                            source_name=source_name,
                            extra={"repo": repo, "kind": "commit"},
                        )
                    )

            releases = client.get(
                f"https://api.github.com/repos/{repo}/releases", params={"per_page": 5}
            )
            if releases.status_code == 200:
                for release in releases.json():
                    name = (release.get("name") or release.get("tag_name") or "").strip()
                    if not name:
                        continue
                    items.append(
                        RawItem(
                            title=f"Released {name}",
                            summary=(release.get("body") or "")[:800],
                            url=release.get("html_url"),
                            category=ContentCategory.MILESTONE,
                            source_name=source_name,
                            extra={"repo": repo, "kind": "release"},
                        )
                    )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Could not reach GitHub: {type(exc).__name__}") from exc

    return items


def fetch_source(source) -> list[RawItem]:
    """Dispatch on source type. Manual sources are supplied by the user."""
    config = source.config or {}
    if source.type == SourceType.RSS and source.url:
        return fetch_rss(source.url, source_name=source.name, category=source.category)
    if source.type == SourceType.GITHUB:
        repo = config.get("repo") or (source.url or "").removeprefix("https://github.com/")
        if not repo:
            return []
        return fetch_github_activity(
            repo.strip("/"), source_name=source.name, token=config.get("token")
        )
    if source.type in {SourceType.MANUAL, SourceType.PROJECT_LOG, SourceType.RELEASE_NOTES}:
        # Manual items arrive through the API, not by polling.
        return []
    log_event(log, "SOURCE_TYPE_UNSUPPORTED", source_id=source.id, type=str(source.type))
    return []
