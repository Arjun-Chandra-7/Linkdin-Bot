"""LinkedIn publishing.

Two supported modes, and browser automation is deliberately not one of them:

* ``manual``  - the safe default. At the scheduled time the system prepares
  copy-ready content and sends a reminder; the *user* posts it and confirms.
  Nothing is published on the user's behalf.
* ``api``     - the official LinkedIn REST Posts API using an authorised
  member token (``w_member_social``).

If the API mode is configured and fails, the post is marked FAILED and the
user is told. It never silently degrades into anything riskier.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from app.config import Settings
from app.core.errors import PublishingAuthExpiredError, PublishingNotConfiguredError
from app.database.enums import PublishMethod

log = logging.getLogger(__name__)

LINKEDIN_COMPOSE_URL = "https://www.linkedin.com/feed/?shareActive=true"


@dataclass
class PublishResult:
    method: PublishMethod
    published: bool
    message: str
    external_id: str | None = None
    external_url: str | None = None
    # True when the human still has to press "Post" in the LinkedIn app.
    awaiting_user_action: bool = False
    copy_ready_content: str | None = None
    open_url: str | None = None


@dataclass
class PublisherStatus:
    status: str  # ok | not_configured | error | disabled
    detail: str
    extra: dict = field(default_factory=dict)


class Publisher(ABC):
    method: PublishMethod

    @abstractmethod
    def publish(self, content: str, *, draft_id: int) -> PublishResult: ...

    @abstractmethod
    def health_check(self) -> PublisherStatus: ...


class ManualPublisher(Publisher):
    """Prepares the post for the user instead of publishing it."""

    method = PublishMethod.MANUAL

    def publish(self, content: str, *, draft_id: int) -> PublishResult:
        return PublishResult(
            method=PublishMethod.MANUAL,
            published=False,
            awaiting_user_action=True,
            message="Ready to post. Open LinkedIn, paste the text, then confirm here.",
            copy_ready_content=content,
            open_url=LINKEDIN_COMPOSE_URL,
        )

    def health_check(self) -> PublisherStatus:
        return PublisherStatus(
            status="ok",
            detail="Manual mode: the system prepares posts, you publish them.",
        )


class LinkedInApiPublisher(Publisher):
    """Official LinkedIn REST Posts API.

    Requires a member access token with ``w_member_social`` and the author's
    person URN. Obtaining that token is a one-time OAuth step performed by the
    user - see docs/linkedin.md.
    """

    method = PublishMethod.API
    BASE_URL = "https://api.linkedin.com/rest/posts"

    def __init__(self, settings: Settings) -> None:
        self.token = settings.linkedin_access_token
        self.author_urn = settings.linkedin_author_urn
        self.api_version = settings.linkedin_api_version
        self.timeout = 30.0

    def _require_config(self) -> None:
        if not self.token or not self.author_urn:
            raise PublishingNotConfiguredError(
                "LinkedIn API publishing is selected but no access token or author URN is set.",
                recovery="Add the credentials to .env, or switch publishing back to manual mode.",
            )

    def publish(self, content: str, *, draft_id: int) -> PublishResult:
        self._require_config()
        payload = {
            "author": self.author_urn,
            "commentary": content,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        headers = {
            "Authorization": f"Bearer {self.token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": self.api_version,
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.BASE_URL, json=payload, headers=headers)

        if response.status_code in (401, 403):
            raise PublishingAuthExpiredError(
                "LinkedIn rejected the access token.",
                details={"status": response.status_code},
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"LinkedIn API returned {response.status_code}: {response.text[:300]}"
            )

        post_urn = response.headers.get("x-restli-id") or response.headers.get("X-RestLi-Id")
        url = f"https://www.linkedin.com/feed/update/{post_urn}/" if post_urn else None
        return PublishResult(
            method=PublishMethod.API,
            published=True,
            message="Published to LinkedIn.",
            external_id=post_urn,
            external_url=url,
        )

    def health_check(self) -> PublisherStatus:
        if not self.token or not self.author_urn:
            return PublisherStatus(
                status="not_configured",
                detail="No LinkedIn access token or author URN configured.",
            )
        return PublisherStatus(
            status="ok", detail="LinkedIn API credentials present.", extra={"mode": "api"}
        )


def get_publisher(settings: Settings) -> Publisher:
    mode = (settings.linkedin_publish_mode or "manual").lower()
    if mode == "api":
        return LinkedInApiPublisher(settings)
    if mode != "manual":
        log.warning("Unknown LINKEDIN_PUBLISH_MODE=%r; using safe manual mode", mode)
    return ManualPublisher()
