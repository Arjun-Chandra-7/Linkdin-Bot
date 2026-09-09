package com.linkedincopilot.app.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.linkedincopilot.app.data.AnalyticsOverview
import com.linkedincopilot.app.data.ApiException
import com.linkedincopilot.app.data.CalendarEntry
import com.linkedincopilot.app.data.Connection
import com.linkedincopilot.app.data.DraftDetail
import com.linkedincopilot.app.data.DraftSummary
import com.linkedincopilot.app.data.HomeSummary
import com.linkedincopilot.app.data.ManualIdeaRequest
import com.linkedincopilot.app.data.MetricsInput
import com.linkedincopilot.app.data.OfflineException
import com.linkedincopilot.app.data.Repository
import com.linkedincopilot.app.data.RewriteOperation
import com.linkedincopilot.app.data.SecureStore
import com.linkedincopilot.app.data.SystemStatus
import com.linkedincopilot.app.data.local.PendingAction
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** A user-facing problem: a sentence plus, where possible, what to do. */
data class UiError(val message: String, val recovery: String? = null, val offline: Boolean = false)

data class AppState(
    val paired: Boolean = false,
    val loading: Boolean = false,
    val home: HomeSummary? = null,
    val drafts: List<DraftSummary> = emptyList(),
    val calendar: List<CalendarEntry> = emptyList(),
    val connections: List<Connection> = emptyList(),
    val analytics: AnalyticsOverview? = null,
    val status: SystemStatus? = null,
    val pendingSync: Int = 0,
    val pendingActionMap: Map<Int, PendingAction> = emptyMap(),
    val error: UiError? = null,
    val message: String? = null,
)

class AppViewModel(app: Application) : AndroidViewModel(app) {

    private val store = SecureStore(app)
    val repo = Repository(app, store)

    private val _state = MutableStateFlow(AppState(paired = store.isPaired))
    val state: StateFlow<AppState> = _state.asStateFlow()

    val serverName: String? get() = store.serverName
    val baseUrl: String? get() = store.baseUrl
    val hardwareBackedKeystore: Boolean get() = store.isHardwareBacked

    init {
        viewModelScope.launch {
            repo.pendingActions.collect { actions ->
                _state.value = _state.value.copy(
                    pendingSync = actions.size,
                    pendingActionMap = actions.associateBy { it.draftId },
                )
            }
        }
        if (store.isPaired) refreshAll()
    }

    private fun toUiError(e: Throwable): UiError = when (e) {
        is OfflineException -> UiError(
            "Backend offline",
            e.message?.takeIf { it.isNotBlank() && it != "Backend unreachable" }
                ?: "Your laptop is not reachable. Check it is awake and on the same Wi-Fi.",
            offline = true,
        )
        is ApiException -> UiError(e.message, e.recovery)
        else -> UiError("Something went wrong.", e.message)
    }

    private inline fun run(crossinline block: suspend () -> Unit) {
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true, error = null)
            try {
                block()
                _state.value = _state.value.copy(loading = false)
            } catch (e: Throwable) {
                if (e is kotlinx.coroutines.CancellationException) throw e
                _state.value = _state.value.copy(loading = false, error = toUiError(e))
            }
        }
    }

    fun clearMessage() {
        _state.value = _state.value.copy(message = null, error = null)
    }

    // ---- Pairing -------------------------------------------------------
    fun pair(baseUrl: String, code: String, deviceName: String, onDone: () -> Unit) = run {
        repo.pair(baseUrl, code, deviceName)
        _state.value = _state.value.copy(paired = true, message = "Paired with ${store.serverName}")
        onDone()
        refreshAll()
    }

    fun unpair() {
        repo.unpair()
        _state.value = AppState(paired = false)
    }

    // ---- Loading -------------------------------------------------------
    fun refreshAll() = run {
        // Send anything queued while offline before reading fresh state.
        val sync = repo.syncPending()
        val drafts = runCatching { repo.refreshDrafts() }.getOrElse { emptyList() }
        val home = runCatching { repo.api.home() }.getOrNull()
        _state.value = _state.value.copy(
            home = home ?: _state.value.home ?: HomeSummary(
                pendingApprovals = drafts.count { it.status == "READY_FOR_REVIEW" },
                scheduledPosts = 0,
                publishedThisWeek = 0,
                suggestedConnections = 0,
                backendStatus = "offline",
            ),
            drafts = if (drafts.isNotEmpty()) drafts else _state.value.drafts,
            paired = true,
            message = when {
                sync.sent > 0 && sync.conflicted > 0 ->
                    "Synced ${sync.sent} decision(s); ${sync.conflicted} needed re-review."
                sync.sent > 0 -> "Synced ${sync.sent} offline decision(s)."
                sync.conflicted > 0 ->
                    "${sync.conflicted} offline decision(s) were dropped because the post changed."
                else -> null
            },
        )
    }

    fun loadCalendar() = run {
        _state.value = _state.value.copy(calendar = repo.api.calendar())
    }

    fun loadConnections() = run {
        _state.value = _state.value.copy(connections = repo.api.connections())
    }

    fun loadAnalytics() = run {
        _state.value = _state.value.copy(analytics = repo.api.analytics())
    }

    fun loadStatus() = run {
        _state.value = _state.value.copy(status = repo.api.systemStatus())
    }

    suspend fun draftDetail(id: Int): DraftDetail = repo.draftDetail(id)

    // ---- Decisions -----------------------------------------------------
    fun approve(
        draftId: Int,
        contentHash: String,
        editedContent: String? = null,
        scheduledAt: String? = null,
        onDone: (String) -> Unit,
    ) = run {
        val response = repo.submitDecision(
            draftId = draftId,
            action = "APPROVE",
            expectedContentHash = contentHash,
            editedContent = editedContent,
            scheduledAt = scheduledAt,
        )
        val text = when {
            response == null -> "Saved offline. It will sync when your laptop is reachable."
            response.replayed -> "Already recorded."
            response.scheduledAt != null -> "Approved. Scheduled for ${Fmt.relativeDay(response.scheduledAt)}."
            else -> response.message
        }
        _state.value = _state.value.copy(message = text)
        onDone(text)
        refreshAllInternal()
    }

    fun reject(draftId: Int, contentHash: String, reason: String, note: String?, onDone: (String) -> Unit) = run {
        val response = repo.submitDecision(
            draftId = draftId,
            action = "REJECT",
            expectedContentHash = contentHash,
            rejectionReason = reason,
            note = note,
        )
        val text = if (response == null) "Saved offline. It will sync later." else "Rejected."
        _state.value = _state.value.copy(message = text)
        onDone(text)
        refreshAllInternal()
    }

    fun saveForLater(draftId: Int, contentHash: String, onDone: (String) -> Unit) = run {
        repo.submitDecision(draftId, "SAVE_FOR_LATER", contentHash)
        _state.value = _state.value.copy(message = "Saved for later.")
        onDone("Saved for later.")
        refreshAllInternal()
    }

    fun cancelPending(draftId: Int) = run {
        repo.cancelPending(draftId)
        _state.value = _state.value.copy(message = "Queued decision cancelled.")
        refreshAllInternal()
    }

    fun saveEditOffline(draftId: Int, content: String) = run {
        repo.saveEditOffline(draftId, content)
        _state.value = _state.value.copy(message = "Edit saved to offline copy.")
    }

    private suspend fun refreshAllInternal() {
        runCatching {
            val drafts = repo.refreshDrafts()
            val home = runCatching { repo.api.home() }.getOrNull()
            _state.value = _state.value.copy(
                home = home ?: _state.value.home,
                drafts = if (drafts.isNotEmpty()) drafts else _state.value.drafts,
            )
        }
    }

    // ---- Editing -------------------------------------------------------
    fun rewrite(draftId: Int, operation: String, instruction: String?, onDone: (DraftDetail) -> Unit) = run {
        val updated = repo.api.rewrite(draftId, RewriteOperation(operation, instruction = instruction))
        onDone(updated)
    }

    fun saveEdit(draftId: Int, content: String, expectedHash: String?, onDone: (DraftDetail) -> Unit) = run {
        repo.api.saveEdit(draftId, com.linkedincopilot.app.data.SaveEditRequest(content, expectedHash))
        onDone(repo.draftDetail(draftId))
    }

    fun selectVersion(draftId: Int, versionId: Int, onDone: (DraftDetail) -> Unit) = run {
        onDone(repo.api.selectVersion(draftId, versionId))
    }

    fun createIdea(
        topic: String,
        notes: String,
        category: String,
        scheduledAt: String? = null,
        onDone: (Int) -> Unit,
    ) = run {
        val draft = repo.api.createFromIdea(
            ManualIdeaRequest(
                topic = topic,
                notes = notes,
                category = category,
                scheduledAt = scheduledAt,
            )
        )
        _state.value = _state.value.copy(
            message = if (draft.status == "READY_FOR_REVIEW") "Draft ready for review."
            else "Draft was written but did not pass the quality gate (${draft.status.lowercase()})."
        )
        onDone(draft.id)
        refreshAllInternal()
    }

    // ---- Schedule / network / analytics --------------------------------
    fun reschedule(slotId: Int, newScheduledAt: String, onDone: () -> Unit = {}) = run {
        repo.api.reschedule(slotId, newScheduledAt)
        _state.value = _state.value.copy(
            message = "Post rescheduled.",
            calendar = repo.api.calendar(),
        )
        refreshAllInternal()
        onDone()
    }

    // ---- Schedule / network / analytics --------------------------------
    fun confirmPublished(slotId: Int) = run {
        repo.api.confirmPublished(slotId)
        _state.value = _state.value.copy(message = "Marked as published.")
        refreshAllInternal()
        _state.value = _state.value.copy(calendar = repo.api.calendar())
    }

    fun setConnectionStatus(id: Int, status: String) = run {
        repo.api.setConnectionStatus(id, status)
        _state.value = _state.value.copy(connections = repo.api.connections())
    }

    fun recordMetrics(postId: Int, metrics: MetricsInput) = run {
        repo.api.recordMetrics(postId, metrics)
        _state.value = _state.value.copy(analytics = repo.api.analytics(), message = "Metrics saved.")
    }

    fun runDiscovery() = run {
        repo.api.runJob("discover_topics")
        _state.value = _state.value.copy(message = "Looking for new ideas. Check back shortly.")
    }
}
