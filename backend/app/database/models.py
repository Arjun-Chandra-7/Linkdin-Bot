"""ORM models for the LinkedIn Content Copilot.

Design notes
------------
* All timestamps are stored in UTC.
* Free-form structured payloads use ``JSON`` columns; anything queried or
  filtered gets a real column plus an index.
* Approval integrity is enforced by ``Approval.approved_content_hash`` - a
  publish is only allowed when the version's hash still matches.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UTCDateTime
from app.database.enums import (
    ApprovalAction,
    ConnectionStatus,
    ContentCategory,
    DraftStatus,
    IdeaStatus,
    JobStatus,
    NotificationPriority,
    NotificationType,
    PostType,
    PublishMethod,
    ScheduleStatus,
    SourceType,
    VersionOrigin,
)

# --------------------------------------------------------------------------
# Devices & auth
# --------------------------------------------------------------------------


class Device(Base, TimestampMixin):
    """A paired Android device. The bearer token is stored only as a hash."""

    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    platform: Mapped[str] = mapped_column(String(32), default="android")
    token_hash: Mapped[str] = mapped_column(String(255))
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    paired_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    push_token: Mapped[str | None] = mapped_column(String(255), nullable=True)


class PairingCode(Base, TimestampMixin):
    """Short-lived one-time code shown by the backend and typed/scanned on the phone."""

    __tablename__ = "pairing_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(255), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    consumed_by_device: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------
# Sources & ideas
# --------------------------------------------------------------------------


class Source(Base, TimestampMixin):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[SourceType] = mapped_column(String(32), index=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    category: Mapped[ContentCategory] = mapped_column(String(40), default=ContentCategory.AI_OBSERVATION)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    last_fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    ideas: Mapped[list[Idea]] = relationship(back_populates="source")


class Idea(Base, TimestampMixin):
    """A candidate topic, scored cheaply before any expensive model call."""

    __tablename__ = "ideas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True, index=True)
    source_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    category: Mapped[ContentCategory] = mapped_column(String(40), index=True)
    why_it_matters: Mapped[str | None] = mapped_column(Text, nullable=True)

    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    originality_score: Mapped[float] = mapped_column(Float, default=0.0)
    timeliness_score: Mapped[float] = mapped_column(Float, default=0.0)
    personal_experience_score: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_quality: Mapped[float] = mapped_column(Float, default=0.0)
    linkedin_fit_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)

    status: Mapped[IdeaStatus] = mapped_column(String(32), default=IdeaStatus.NEW, index=True)
    reject_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Stable hash of the normalised topic, used to avoid re-ingesting the same item.
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    source: Mapped[Source | None] = relationship(back_populates="ideas")
    research: Mapped[list[Research]] = relationship(back_populates="idea", cascade="all, delete-orphan")
    drafts: Mapped[list[Draft]] = relationship(back_populates="idea")

    __table_args__ = (UniqueConstraint("fingerprint", name="uq_idea_fingerprint"),)


class Research(Base, TimestampMixin):
    """Evidence gathered before writing. Claims carry their own confidence."""

    __tablename__ = "research"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idea_id: Mapped[int] = mapped_column(ForeignKey("ideas.id", ondelete="CASCADE"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    claims: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    references: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    contradictions: Mapped[list[str]] = mapped_column(JSON, default=list)
    uncertainty_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    idea: Mapped[Idea] = relationship(back_populates="research")


# --------------------------------------------------------------------------
# Drafts
# --------------------------------------------------------------------------


class Draft(Base, TimestampMixin):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idea_id: Mapped[int | None] = mapped_column(ForeignKey("ideas.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    post_type: Mapped[PostType] = mapped_column(String(40), index=True)
    category: Mapped[ContentCategory] = mapped_column(String(40), index=True)
    status: Mapped[DraftStatus] = mapped_column(String(32), default=DraftStatus.DRAFT, index=True)
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("draft_versions.id", use_alter=True, name="fk_draft_current_version"), nullable=True
    )
    generation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_publish_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejection_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    predicted_performance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    idea: Mapped[Idea | None] = relationship(back_populates="drafts")
    versions: Mapped[list[DraftVersion]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        foreign_keys="DraftVersion.draft_id",
        order_by="DraftVersion.id",
    )
    current_version: Mapped[DraftVersion | None] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )
    approvals: Mapped[list[Approval]] = relationship(back_populates="draft", cascade="all, delete-orphan")


class DraftVersion(Base, TimestampMixin):
    """One concrete piece of text. Edits always create a new version so that
    an approval can always point at exactly what was approved."""

    __tablename__ = "draft_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(40), default="A")
    content: Mapped[str] = mapped_column(Text)
    hook: Mapped[str | None] = mapped_column(String(500), nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    origin: Mapped[VersionOrigin] = mapped_column(String(24), default=VersionOrigin.LLM)
    quality: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    fact_check: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Simhash of the normalised body, for near-duplicate detection.
    simhash: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)

    draft: Mapped[Draft] = relationship(back_populates="versions", foreign_keys=[draft_id])


# --------------------------------------------------------------------------
# Approvals
# --------------------------------------------------------------------------


class Approval(Base, TimestampMixin):
    """An immutable record that a specific human approved specific bytes.

    ``approved_content_hash`` is compared against the live version hash before
    every publish; if the content changed the approval is invalidated and the
    draft returns to READY_FOR_REVIEW.
    """

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("draft_versions.id"), index=True)
    action: Mapped[ApprovalAction] = mapped_column(String(24), index=True)
    approved_content_hash: Mapped[str] = mapped_column(String(64), index=True)
    approval_timestamp: Mapped[datetime] = mapped_column(UTCDateTime)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    valid: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    invalidated_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    was_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Client-supplied id makes offline replay idempotent.
    client_action_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    draft: Mapped[Draft] = relationship(back_populates="approvals")

    __table_args__ = (
        UniqueConstraint("client_action_id", name="uq_approval_client_action"),
        Index("ix_approval_draft_valid", "draft_id", "valid"),
    )


# --------------------------------------------------------------------------
# Scheduling & publishing
# --------------------------------------------------------------------------


class ScheduledPost(Base, TimestampMixin):
    __tablename__ = "scheduled_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("draft_versions.id"))
    approval_id: Mapped[int] = mapped_column(ForeignKey("approvals.id"))
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    status: Mapped[ScheduleStatus] = mapped_column(String(24), default=ScheduleStatus.PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Guarantees a draft is never scheduled (and therefore published) twice.
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)


class PublishedPost(Base, TimestampMixin):
    __tablename__ = "published_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("draft_versions.id"))
    approval_id: Mapped[int] = mapped_column(ForeignKey("approvals.id"))
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    method: Mapped[PublishMethod] = mapped_column(String(16))
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    post_type: Mapped[PostType] = mapped_column(String(40), index=True)
    category: Mapped[ContentCategory] = mapped_column(String(40), index=True)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    hook_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hour_local: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (UniqueConstraint("draft_id", name="uq_published_draft"),)


class AnalyticsSnapshot(Base, TimestampMixin):
    """Metrics for a published post at a point in time.

    Every field is nullable on purpose: LinkedIn does not expose all of these
    to every integration, and unavailable metrics must stay NULL rather than
    being invented.
    """

    __tablename__ = "analytics_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    published_post_id: Mapped[int] = mapped_column(
        ForeignKey("published_posts.id", ondelete="CASCADE"), index=True
    )
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    source: Mapped[str] = mapped_column(String(24), default="manual")  # manual | api
    impressions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reactions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reposts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profile_visits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    followers_gained: Mapped[int | None] = mapped_column(Integer, nullable=True)


# --------------------------------------------------------------------------
# Style learning & networking
# --------------------------------------------------------------------------


class StyleFeedback(Base, TimestampMixin):
    """Signals derived from what the user keeps, rewrites, deletes and rejects."""

    __tablename__ = "style_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)  # edit | reject | approve
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"), nullable=True, index=True)
    before_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    removed_phrases: Mapped[list[str]] = mapped_column(JSON, default=list)
    added_phrases: Mapped[list[str]] = mapped_column(JSON, default=list)
    length_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)


class ConnectionCandidate(Base, TimestampMixin):
    """A person worth connecting with. The system never sends the invitation."""

    __tablename__ = "connection_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    profile_url: Mapped[str] = mapped_column(String(1000))
    reason_for_recommendation: Mapped[str] = mapped_column(Text)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    shared_interests: Mapped[list[str]] = mapped_column(JSON, default=list)
    suggested_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ConnectionStatus] = mapped_column(
        String(24), default=ConnectionStatus.NEW, index=True
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)


# --------------------------------------------------------------------------
# Infrastructure: notifications, jobs, settings, cost
# --------------------------------------------------------------------------


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[NotificationType] = mapped_column(String(40), index=True)
    priority: Mapped[NotificationPriority] = mapped_column(
        String(16), default=NotificationPriority.NORMAL, index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # Low-priority items are held until quiet hours end, then batched.
    deliver_after: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True, index=True
    )
    dedupe_key: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)


class Job(Base, TimestampMixin):
    """Persistent background work. Survives restarts; retried with backoff."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[JobStatus] = mapped_column(String(24), default=JobStatus.QUEUED, index=True)
    run_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)

    __table_args__ = (Index("ix_job_status_runat", "status", "run_at"),)


class Setting(Base, TimestampMixin):
    """Runtime-tunable configuration editable from the mobile Settings screen."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class LLMUsage(Base, TimestampMixin):
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str] = mapped_column(String(80), index=True)
    task: Mapped[str] = mapped_column(String(60), index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    succeeded: Mapped[bool] = mapped_column(Boolean, default=True)


class LearningInsight(Base, TimestampMixin):
    """Output of the learning engine, always carrying sample size + confidence."""

    __tablename__ = "learning_insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dimension: Mapped[str] = mapped_column(String(60), index=True)  # post_type | weekday | length ...
    segment: Mapped[str] = mapped_column(String(120))
    statement: Mapped[str] = mapped_column(Text)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    baseline: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed: Mapped[float | None] = mapped_column(Float, nullable=True)
    lift: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[str] = mapped_column(String(32), index=True)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
