package com.linkedincopilot.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Wire models mirroring the backend's /api/v1 contract.
 *
 * Every field the server may omit is nullable on purpose: a missing analytics
 * metric means "not collected", and rendering it as 0 would be inventing data.
 */

@Serializable
data class PairRequest(
    val code: String,
    @SerialName("device_name") val deviceName: String,
    val platform: String = "android",
)

@Serializable
data class PairResponse(
    @SerialName("device_id") val deviceId: String,
    val token: String,
    @SerialName("server_name") val serverName: String,
    @SerialName("api_version") val apiVersion: String,
    val timezone: String,
)

@Serializable
data class DeviceInfo(
    val id: String,
    val name: String,
    val platform: String,
    @SerialName("paired_at") val pairedAt: String? = null,
    @SerialName("last_seen_at") val lastSeenAt: String? = null,
)

@Serializable
data class DraftVersion(
    val id: Int,
    val label: String,
    val content: String,
    val hook: String? = null,
    @SerialName("char_count") val charCount: Int,
    @SerialName("content_hash") val contentHash: String,
    val origin: String,
    val quality: Map<String, kotlinx.serialization.json.JsonElement>? = null,
    @SerialName("fact_check") val factCheck: Map<String, kotlinx.serialization.json.JsonElement>? = null,
    @SerialName("created_at") val createdAt: String,
)

@Serializable
data class ResearchReference(
    val title: String? = null,
    val url: String? = null,
    @SerialName("published_at") val publishedAt: String? = null,
    val note: String? = null,
)

@Serializable
data class DraftSummary(
    val id: Int,
    val title: String,
    @SerialName("post_type") val postType: String,
    val category: String,
    val status: String,
    @SerialName("created_at") val createdAt: String,
    @SerialName("proposed_publish_at") val proposedPublishAt: String? = null,
    @SerialName("quality_score") val qualityScore: Int? = null,
    @SerialName("ai_slop_probability") val aiSlopProbability: Double? = null,
    @SerialName("char_count") val charCount: Int? = null,
    val hook: String? = null,
    val preview: String? = null,
    @SerialName("version_count") val versionCount: Int = 0,
)

@Serializable
data class DraftDetail(
    val id: Int,
    val title: String,
    @SerialName("post_type") val postType: String,
    val category: String,
    val status: String,
    @SerialName("created_at") val createdAt: String,
    @SerialName("proposed_publish_at") val proposedPublishAt: String? = null,
    @SerialName("quality_score") val qualityScore: Int? = null,
    @SerialName("ai_slop_probability") val aiSlopProbability: Double? = null,
    @SerialName("char_count") val charCount: Int? = null,
    val hook: String? = null,
    val preview: String? = null,
    @SerialName("version_count") val versionCount: Int = 0,
    @SerialName("generation_reason") val generationReason: String? = null,
    @SerialName("current_version") val currentVersion: DraftVersion? = null,
    val versions: List<DraftVersion> = emptyList(),
    val sources: List<ResearchReference> = emptyList(),
    @SerialName("research_summary") val researchSummary: String? = null,
    @SerialName("uncertainty_notes") val uncertaintyNotes: String? = null,
    @SerialName("predicted_performance")
    val predictedPerformance: Map<String, kotlinx.serialization.json.JsonElement>? = null,
    @SerialName("has_valid_approval") val hasValidApproval: Boolean = false,
    @SerialName("rejection_reason") val rejectionReason: String? = null,
    @SerialName("failure_reason") val failureReason: String? = null,
)

@Serializable
data class DraftListResponse(val items: List<DraftSummary>, val total: Int)

@Serializable
data class ApprovalRequest(
    @SerialName("draft_id") val draftId: Int,
    val action: String,
    @SerialName("expected_content_hash") val expectedContentHash: String? = null,
    @SerialName("version_id") val versionId: Int? = null,
    @SerialName("edited_content") val editedContent: String? = null,
    @SerialName("rejection_reason") val rejectionReason: String? = null,
    val note: String? = null,
    @SerialName("client_action_id") val clientActionId: String? = null,
    @SerialName("scheduled_at") val scheduledAt: String? = null,
)

@Serializable
data class ApprovalResponse(
    @SerialName("approval_id") val approvalId: Int,
    @SerialName("draft_id") val draftId: Int,
    @SerialName("version_id") val versionId: Int,
    val status: String,
    @SerialName("approved_content_hash") val approvedContentHash: String,
    @SerialName("approval_timestamp") val approvalTimestamp: String,
    val replayed: Boolean = false,
    @SerialName("scheduled_at") val scheduledAt: String? = null,
    val message: String,
)

@Serializable
data class RewriteOperation(
    val operation: String,
    @SerialName("paragraph_index") val paragraphIndex: Int? = null,
    val instruction: String? = null,
)

@Serializable
data class SaveEditRequest(
    val content: String,
    @SerialName("expected_content_hash") val expectedContentHash: String? = null,
)

@Serializable
data class ScheduledPost(
    val id: Int,
    @SerialName("draft_id") val draftId: Int,
    @SerialName("version_id") val versionId: Int,
    @SerialName("scheduled_at") val scheduledAt: String,
    val timezone: String,
    val status: String,
    val attempts: Int = 0,
    @SerialName("last_error") val lastError: String? = null,
    val title: String? = null,
    @SerialName("post_type") val postType: String? = null,
)

@Serializable
data class CalendarEntry(
    @SerialName("draft_id") val draftId: Int,
    @SerialName("slot_id") val slotId: Int? = null,
    val title: String,
    @SerialName("post_type") val postType: String,
    val status: String,
    @SerialName("scheduled_at") val scheduledAt: String? = null,
    @SerialName("published_at") val publishedAt: String? = null,
    @SerialName("schedule_status") val scheduleStatus: String? = null,
)

@Serializable
data class Connection(
    val id: Int,
    val name: String,
    val role: String? = null,
    val company: String? = null,
    @SerialName("profile_url") val profileUrl: String,
    @SerialName("reason_for_recommendation") val reason: String,
    @SerialName("relevance_score") val relevanceScore: Double,
    @SerialName("shared_interests") val sharedInterests: List<String> = emptyList(),
    @SerialName("suggested_note") val suggestedNote: String? = null,
    val status: String,
    @SerialName("created_at") val createdAt: String,
)

@Serializable
data class ConnectionActionRequest(val status: String)

@Serializable
data class PostMetrics(
    @SerialName("published_post_id") val publishedPostId: Int,
    @SerialName("draft_id") val draftId: Int,
    val title: String,
    @SerialName("post_type") val postType: String,
    @SerialName("published_at") val publishedAt: String,
    val impressions: Int? = null,
    val reactions: Int? = null,
    val comments: Int? = null,
    val reposts: Int? = null,
    val clicks: Int? = null,
    @SerialName("followers_gained") val followersGained: Int? = null,
    @SerialName("has_data") val hasData: Boolean = false,
)

@Serializable
data class MetricsInput(
    val impressions: Int? = null,
    val reactions: Int? = null,
    val comments: Int? = null,
    val reposts: Int? = null,
    val clicks: Int? = null,
    @SerialName("profile_visits") val profileVisits: Int? = null,
    @SerialName("followers_gained") val followersGained: Int? = null,
)

@Serializable
data class Insight(
    val dimension: String,
    val segment: String,
    val statement: String,
    @SerialName("sample_size") val sampleSize: Int,
    val confidence: String,
    val lift: Double? = null,
    @SerialName("generated_at") val generatedAt: String,
)

@Serializable
data class AnalyticsOverview(
    @SerialName("published_count") val publishedCount: Int,
    @SerialName("posts_with_metrics") val postsWithMetrics: Int,
    val insights: List<Insight> = emptyList(),
    @SerialName("best_format") val bestFormat: String? = null,
    @SerialName("empty_state") val emptyState: String? = null,
    val posts: List<PostMetrics> = emptyList(),
)

@Serializable
data class HomeSummary(
    @SerialName("pending_approvals") val pendingApprovals: Int,
    @SerialName("scheduled_posts") val scheduledPosts: Int,
    @SerialName("published_this_week") val publishedThisWeek: Int,
    @SerialName("suggested_connections") val suggestedConnections: Int,
    @SerialName("next_scheduled_at") val nextScheduledAt: String? = null,
    @SerialName("next_scheduled_title") val nextScheduledTitle: String? = null,
    @SerialName("best_recent_format") val bestRecentFormat: String? = null,
    @SerialName("backend_status") val backendStatus: String = "connected",
)

@Serializable
data class ComponentStatus(val name: String, val status: String, val detail: String? = null)

@Serializable
data class SystemStatus(
    val backend: ComponentStatus,
    val database: ComponentStatus,
    val scheduler: ComponentStatus,
    @SerialName("ai_provider") val aiProvider: ComponentStatus,
    val linkedin: ComponentStatus,
    @SerialName("last_discovery_at") val lastDiscoveryAt: String? = null,
    @SerialName("next_scheduled_job_at") val nextScheduledJobAt: String? = null,
    @SerialName("failed_jobs") val failedJobs: Int = 0,
    @SerialName("server_time") val serverTime: String,
    val timezone: String,
)

@Serializable
data class AppNotification(
    val id: Int,
    val type: String,
    val priority: String,
    val title: String,
    val body: String,
    val payload: Map<String, kotlinx.serialization.json.JsonElement> = emptyMap(),
    @SerialName("created_at") val createdAt: String,
    @SerialName("read_at") val readAt: String? = null,
)

@Serializable
data class ManualIdeaRequest(
    val topic: String,
    val notes: String = "",
    val category: String = "BUILD_LOG",
    @SerialName("post_type") val postType: String? = null,
    @SerialName("generate_now") val generateNow: Boolean = true,
    @SerialName("scheduled_at") val scheduledAt: String? = null,
)

@Serializable
data class SettingsPayload(val values: Map<String, kotlinx.serialization.json.JsonElement>)

/** The backend's uniform error shape: code, message, and a recovery hint. */
@Serializable
data class ApiErrorBody(
    val code: String = "error",
    val message: String = "Something went wrong.",
    val recovery: String? = null,
)
