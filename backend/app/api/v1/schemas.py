"""Typed request/response models for the v1 API.

These are the contract the Android client codes against, so they are kept
explicit rather than serialising ORM objects directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.database.enums import (
    ApprovalAction,
    ConnectionStatus,
    ContentCategory,
    DraftStatus,
    NotificationPriority,
    NotificationType,
    PostType,
    RejectionReason,
    ScheduleStatus,
    VersionOrigin,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth ----


class PairRequest(BaseModel):
    code: str = Field(min_length=4, max_length=32)
    device_name: str = Field(min_length=1, max_length=120)
    platform: str = "android"


class PairResponse(BaseModel):
    device_id: str
    token: str = Field(description="Shown once. Store in Android EncryptedSharedPreferences.")
    server_name: str
    api_version: str
    timezone: str


class DeviceInfo(ORMModel):
    id: str
    name: str
    platform: str
    paired_at: datetime | None
    last_seen_at: datetime | None
    scopes: list[str] = []


# -------------------------------------------------------------- drafts ----


class QualityReport(BaseModel):
    quality: int
    originality: int
    specificity: int
    technical_depth: int
    readability: int
    ai_slop_probability: float
    engagement_bait_probability: float
    claim_confidence: float
    recommendation: str
    issues: list[str] = []
    notes: list[str] = []


class DraftVersionOut(ORMModel):
    id: int
    label: str
    content: str
    hook: str | None
    char_count: int
    content_hash: str
    origin: VersionOrigin
    quality: dict[str, Any] | None = None
    fact_check: dict[str, Any] | None = None
    created_at: datetime


class ResearchReference(BaseModel):
    title: str | None = None
    url: str | None = None
    published_at: str | None = None
    note: str | None = None


class DraftSummary(ORMModel):
    id: int
    title: str
    post_type: PostType
    category: ContentCategory
    status: DraftStatus
    created_at: datetime
    proposed_publish_at: datetime | None
    quality_score: int | None = None
    ai_slop_probability: float | None = None
    char_count: int | None = None
    hook: str | None = None
    preview: str | None = None
    version_count: int = 0


class DraftDetail(DraftSummary):
    generation_reason: str | None = None
    current_version: DraftVersionOut | None = None
    versions: list[DraftVersionOut] = []
    sources: list[ResearchReference] = []
    research_summary: str | None = None
    uncertainty_notes: str | None = None
    predicted_performance: dict[str, Any] | None = None
    has_valid_approval: bool = False
    rejection_reason: str | None = None
    failure_reason: str | None = None


class DraftListResponse(BaseModel):
    items: list[DraftSummary]
    total: int


# ----------------------------------------------------------- approvals ----


class ApprovalRequest(BaseModel):
    draft_id: int
    action: ApprovalAction
    # Hash of exactly what the phone displayed. Required for APPROVE so a
    # stale screen can never authorise different content.
    expected_content_hash: str | None = None
    version_id: int | None = None
    edited_content: str | None = None
    rejection_reason: RejectionReason | None = None
    note: str | None = Field(default=None, max_length=2000)
    # Stable per-action id generated on the device; makes offline replay safe.
    client_action_id: str | None = Field(default=None, max_length=80)
    scheduled_at: datetime | None = Field(
        default=None, description="Optional explicit publish time; otherwise the next free slot."
    )


class ApprovalResponse(BaseModel):
    approval_id: int
    draft_id: int
    version_id: int
    status: DraftStatus
    approved_content_hash: str
    approval_timestamp: datetime
    replayed: bool = False
    scheduled_at: datetime | None = None
    message: str


# --------------------------------------------------------------- edits ----


class RewriteOperation(BaseModel):
    """A targeted rewrite requested from the phone."""

    operation: str = Field(
        description="shorten | expand | more_technical | more_casual | rewrite_hook | "
        "rewrite_paragraph | regenerate"
    )
    paragraph_index: int | None = None
    instruction: str | None = Field(default=None, max_length=500)


class SaveEditRequest(BaseModel):
    content: str = Field(min_length=1)
    expected_content_hash: str | None = None


# ------------------------------------------------------------ schedule ----


class ScheduledPostOut(ORMModel):
    id: int
    draft_id: int
    version_id: int
    scheduled_at: datetime
    timezone: str
    status: ScheduleStatus
    attempts: int
    last_error: str | None = None
    title: str | None = None
    post_type: PostType | None = None


class CalendarEntry(BaseModel):
    draft_id: int
    slot_id: int | None = None
    title: str
    post_type: PostType
    status: DraftStatus
    scheduled_at: datetime | None
    published_at: datetime | None
    schedule_status: ScheduleStatus | None = None


# ------------------------------------------------------------- network ----


class ConnectionOut(ORMModel):
    id: int
    name: str
    role: str | None
    company: str | None
    profile_url: str
    reason_for_recommendation: str
    relevance_score: float
    shared_interests: list[str] = []
    suggested_note: str | None
    status: ConnectionStatus
    created_at: datetime


class ConnectionActionRequest(BaseModel):
    status: ConnectionStatus


# ----------------------------------------------------------- analytics ----


class PostMetrics(BaseModel):
    published_post_id: int
    draft_id: int
    title: str
    post_type: PostType
    published_at: datetime
    impressions: int | None = None
    reactions: int | None = None
    comments: int | None = None
    reposts: int | None = None
    clicks: int | None = None
    followers_gained: int | None = None
    has_data: bool = False


class MetricsInput(BaseModel):
    """Manual metric entry - LinkedIn does not expose these to every integration."""

    impressions: int | None = Field(default=None, ge=0)
    reactions: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    reposts: int | None = Field(default=None, ge=0)
    clicks: int | None = Field(default=None, ge=0)
    profile_visits: int | None = Field(default=None, ge=0)
    followers_gained: int | None = Field(default=None, ge=0)


class InsightOut(ORMModel):
    dimension: str
    segment: str
    statement: str
    sample_size: int
    confidence: str
    lift: float | None = None
    generated_at: datetime


class AnalyticsOverview(BaseModel):
    published_count: int
    posts_with_metrics: int
    insights: list[InsightOut] = []
    best_format: str | None = None
    empty_state: str | None = None
    posts: list[PostMetrics] = []


# ------------------------------------------------------ notifications ----


class NotificationOut(ORMModel):
    id: int
    type: NotificationType
    priority: NotificationPriority
    title: str
    body: str
    payload: dict[str, Any] = {}
    created_at: datetime
    read_at: datetime | None = None


# -------------------------------------------------------------- system ----


class ComponentStatus(BaseModel):
    name: str
    status: str  # ok | degraded | error | not_configured | disabled
    detail: str | None = None


class SystemStatus(BaseModel):
    backend: ComponentStatus
    database: ComponentStatus
    scheduler: ComponentStatus
    ai_provider: ComponentStatus
    linkedin: ComponentStatus
    last_discovery_at: datetime | None = None
    next_scheduled_job_at: datetime | None = None
    failed_jobs: int = 0
    server_time: datetime
    timezone: str


class HomeSummary(BaseModel):
    pending_approvals: int
    scheduled_posts: int
    published_this_week: int
    suggested_connections: int
    next_scheduled_at: datetime | None = None
    next_scheduled_title: str | None = None
    best_recent_format: str | None = None
    backend_status: str = "connected"


class SettingsOut(BaseModel):
    values: dict[str, Any]


class SettingsUpdate(BaseModel):
    values: dict[str, Any]
