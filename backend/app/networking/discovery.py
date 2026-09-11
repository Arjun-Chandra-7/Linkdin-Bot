"""Finding people worth knowing.

The hard constraint: LinkedIn offers no people-search API, and scraping it is
both against their terms and a good way to lose an account. So this looks for
people in places that *do* have open APIs and that the user already cares
about - the contributors to AI and developer-tooling repositories they follow -
and produces a LinkedIn search link for each one.

That link is the handoff. The user clicks it, LinkedIn's own search finds the
person, and the user sends the invitation. Nothing here touches LinkedIn.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import quote_plus

import httpx

from app.agents.discovery.sources import USER_AGENT
from app.core.logging import log_event
from app.networking.service import CandidateInput

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
TIMEOUT = 20.0

LINKEDIN_SEARCH = "https://www.linkedin.com/search/results/people/?keywords={query}"
_LINKEDIN_URL = re.compile(r"(?:https?://)?(?:[\w-]+\.)?linkedin\.com/in/[\w%-]+", re.I)

# Signals that someone works in the areas this account is about.
RELEVANT_BIO = re.compile(
    r"\b(ai|ml|machine learning|llm|agent|agents|nlp|research|infra|infrastructure|"
    r"backend|developer tools|devtools|founder|engineer|engineering|open source|"
    r"data|platform|systems)\b",
    re.I,
)


@dataclass
class DiscoveredPerson:
    name: str
    handle: str
    bio: str
    company: str | None
    profile_url: str
    evidence: str
    linkedin_known: bool


def _headers(token: str | None) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _linkedin_from_profile(profile: dict) -> str | None:
    """A LinkedIn URL the person published themselves, if there is one."""
    for field in ("blog", "bio", "twitter_username"):
        value = profile.get(field)
        if not value or not isinstance(value, str):
            continue
        match = _LINKEDIN_URL.search(value)
        if match:
            url = match.group(0)
            return url if url.startswith("http") else f"https://{url}"
    return None


def discover_from_repo(
    repo: str, *, token: str | None = None, limit: int = 8
) -> list[DiscoveredPerson]:
    """People who contribute to a repository the user follows.

    Only public GitHub data, through GitHub's documented API.
    """
    people: list[DiscoveredPerson] = []
    seen: set[str] = set()
    try:
        with httpx.Client(timeout=TIMEOUT, headers=_headers(token)) as client:
            contributors = client.get(
                f"{GITHUB_API}/repos/{repo}/contributors", params={"per_page": limit * 2}
            )
            if contributors.status_code != 200:
                log_event(
                    log,
                    "PEOPLE_DISCOVERY_SKIPPED",
                    level=logging.WARNING,
                    repo=repo,
                    status=contributors.status_code,
                )
                return []

            for entry in contributors.json():
                if entry.get("type") != "User":
                    continue
                login = entry.get("login", "")
                if not login or login.endswith("[bot]") or login.lower() in seen:
                    continue

                profile = client.get(f"{GITHUB_API}/users/{login}")
                if profile.status_code != 200:
                    continue
                data = profile.json()

                bio = (data.get("bio") or "").strip()
                name = (data.get("name") or "").strip()
                # A LinkedIn people-search needs a real name. A single token is
                # almost always a handle ("ccurme"), which finds nobody.
                if not name or " " not in name:
                    continue
                if bio and not RELEVANT_BIO.search(bio):
                    continue
                # The same human can appear twice under different accounts.
                if name.lower() in seen:
                    continue
                seen.update({login.lower(), name.lower()})

                explicit = _linkedin_from_profile(data)
                company = (data.get("company") or "").strip().lstrip("@") or None
                # Search on the name alone: GitHub "company" is free text and is
                # often a handle like "@glide-browser", which finds nobody on
                # LinkedIn. The company is still shown on the card.
                query = name
                people.append(
                    DiscoveredPerson(
                        name=name,
                        handle=login,
                        bio=bio,
                        company=company,
                        profile_url=explicit or LINKEDIN_SEARCH.format(query=quote_plus(query)),
                        evidence=(
                            f"Contributes to {repo} on GitHub"
                            + (f" — {bio}" if bio else "")
                        ),
                        linkedin_known=explicit is not None,
                    )
                )
                if len(people) >= limit:
                    break
    except httpx.HTTPError as exc:
        log_event(
            log, "PEOPLE_DISCOVERY_FAILED", level=logging.WARNING,
            repo=repo, error=type(exc).__name__,
        )
        return []

    log_event(log, "PEOPLE_DISCOVERED", repo=repo, found=len(people))
    return people


def to_candidate(person: DiscoveredPerson) -> CandidateInput:
    return CandidateInput(
        name=person.name,
        profile_url=person.profile_url,
        role=person.bio[:200] or None,
        company=person.company,
        context=person.evidence,
    )
