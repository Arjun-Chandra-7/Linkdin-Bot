"""Domain enumerations shared by the database, API and mobile client."""

from __future__ import annotations

from enum import StrEnum


class DraftStatus(StrEnum):
    """Lifecycle of a post. Transitions are validated server-side."""

    DRAFT = "DRAFT"
    QUALITY_CHECK = "QUALITY_CHECK"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SAVED_FOR_LATER = "SAVED_FOR_LATER"


class PostType(StrEnum):
    BUILD_LOG = "BUILD_LOG"
    TECHNICAL_BREAKDOWN = "TECHNICAL_BREAKDOWN"
    FAILURE_AND_FIX = "FAILURE_AND_FIX"
    OPINION = "OPINION"
    NEWS_WITH_ANALYSIS = "NEWS_WITH_ANALYSIS"
    MILESTONE = "MILESTONE"
    CASE_STUDY = "CASE_STUDY"
    SHORT_OBSERVATION = "SHORT_OBSERVATION"
    PROJECT_DEMO = "PROJECT_DEMO"


class ContentCategory(StrEnum):
    """Used for the configurable content mix (build logs vs news vs ...)."""

    BUILD_LOG = "BUILD_LOG"
    TECHNICAL_LESSON = "TECHNICAL_LESSON"
    AI_OBSERVATION = "AI_OBSERVATION"
    MILESTONE = "MILESTONE"


class IdeaStatus(StrEnum):
    NEW = "NEW"
    SCORED = "SCORED"
    REJECTED = "REJECTED"
    RESEARCHED = "RESEARCHED"
    DRAFTED = "DRAFTED"
    ARCHIVED = "ARCHIVED"


class SourceType(StrEnum):
    RSS = "RSS"
    GITHUB = "GITHUB"
    MANUAL = "MANUAL"
    PROJECT_LOG = "PROJECT_LOG"
    RELEASE_NOTES = "RELEASE_NOTES"


class ApprovalAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    SAVE_FOR_LATER = "SAVE_FOR_LATER"


class ScheduleStatus(StrEnum):
    PENDING = "PENDING"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DEAD = "DEAD"
    CANCELLED = "CANCELLED"


class ConnectionStatus(StrEnum):
    NEW = "NEW"
    SAVED = "SAVED"
    SKIPPED = "SKIPPED"
    OPENED = "OPENED"
    MARKED_CONNECTED = "MARKED_CONNECTED"


class PublishMethod(StrEnum):
    MANUAL = "MANUAL"
    API = "API"


class VersionOrigin(StrEnum):
    LLM = "LLM"
    USER_EDIT = "USER_EDIT"
    REGENERATED = "REGENERATED"


class RejectionReason(StrEnum):
    TOO_GENERIC = "TOO_GENERIC"
    SOUNDS_AI_GENERATED = "SOUNDS_AI_GENERATED"
    BAD_HOOK = "BAD_HOOK"
    INCORRECT = "INCORRECT"
    TOO_LONG = "TOO_LONG"
    NOT_INTERESTING = "NOT_INTERESTING"
    TOO_CRINGE = "TOO_CRINGE"
    ALREADY_POSTED_SIMILAR = "ALREADY_POSTED_SIMILAR"
    OTHER = "OTHER"


class ConfidenceLevel(StrEnum):
    """Sample-size aware confidence used by the learning engine."""

    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    EARLY_SIGNAL = "EARLY_SIGNAL"
    MODERATE_CONFIDENCE = "MODERATE_CONFIDENCE"
    STRONG_SIGNAL = "STRONG_SIGNAL"


class NotificationType(StrEnum):
    APPROVAL_READY = "APPROVAL_READY"
    POST_SCHEDULED_SOON = "POST_SCHEDULED_SOON"
    PUBLISH_FAILED = "PUBLISH_FAILED"
    PUBLISH_REMINDER = "PUBLISH_REMINDER"
    NETWORK_CANDIDATE = "NETWORK_CANDIDATE"
    SYSTEM = "SYSTEM"


class NotificationPriority(StrEnum):
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"
