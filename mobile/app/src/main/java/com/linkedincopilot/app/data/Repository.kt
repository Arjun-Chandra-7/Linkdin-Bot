package com.linkedincopilot.app.data

import android.content.Context
import androidx.room.Room
import com.linkedincopilot.app.data.local.CachedDraft
import com.linkedincopilot.app.data.local.CopilotDatabase
import com.linkedincopilot.app.data.local.PendingAction
import kotlinx.coroutines.flow.Flow
import java.util.UUID

/**
 * Single source of truth for the UI.
 *
 * The server is authoritative for publication state. The phone only ever
 * queues *intent* - and every queued decision carries the content hash the
 * user actually saw, so a stale approval is refused rather than applied.
 */
class Repository(private val context: Context, val store: SecureStore) {

    val api = ApiClient(store)

    private val db = Room.databaseBuilder(
        context.applicationContext, CopilotDatabase::class.java, "copilot.db"
    ).fallbackToDestructiveMigration().build()

    private val dao = db.dao()

    val cachedDrafts: Flow<List<CachedDraft>> = dao.observeDrafts()
    val pendingCount: Flow<Int> = dao.pendingCount()
    val pendingActions: Flow<List<PendingAction>> = dao.observePending()

    val isPaired: Boolean get() = store.isPaired

    suspend fun pair(baseUrl: String, code: String, deviceName: String): PairResponse {
        val clean = ApiClient.normalizeBaseUrl(baseUrl)
        val response = api.pair(clean, code, deviceName)
        store.baseUrl = clean
        store.token = response.token
        store.deviceId = response.deviceId
        store.serverName = response.serverName
        return response
    }

    fun unpair() {
        store.clear()
    }

    /** Refresh the review queue and cache it for offline reading. */
    suspend fun refreshDrafts(): List<DraftSummary> = try {
        val response = api.drafts()
        val cached = response.items.map { summary ->
            val existing = dao.draft(summary.id)
            CachedDraft(
                id = summary.id,
                title = summary.title,
                postType = summary.postType,
                status = summary.status,
                qualityScore = summary.qualityScore,
                aiSlopProbability = summary.aiSlopProbability,
                charCount = summary.charCount ?: existing?.charCount,
                hook = summary.hook ?: existing?.hook,
                preview = summary.preview ?: existing?.preview,
                versionCount = summary.versionCount,
                contentHash = existing?.contentHash,
                content = existing?.content,
            )
        }
        dao.upsertDrafts(cached)
        dao.pruneDrafts(cached.map { it.id }.ifEmpty { listOf(-1) })

        // Pull the full text of everything awaiting review while the backend
        // is reachable. Without this the queue is readable offline but each
        // draft is not, so the approve button can never be reached - which
        // makes the offline queue pointless.
        for (summary in response.items.take(PREFETCH_LIMIT)) {
            runCatching { draftDetail(summary.id) }.getOrNull() ?: break
        }
        response.items
    } catch (offline: OfflineException) {
        val cached = dao.getCachedDrafts()
        if (cached.isNotEmpty()) {
            cached.map { it.toSummary() }
        } else {
            throw offline
        }
    }

    /**
     * Full draft, from the server when reachable and from the cache when not.
     *
     * The cached copy carries the content hash the user is shown, so a
     * decision taken offline is still bound to exact bytes and the server can
     * refuse it later if the draft moved on.
     */
    suspend fun draftDetail(id: Int): DraftDetail = try {
        fetchAndCacheDetail(id)
    } catch (offline: OfflineException) {
        cachedDetail(id) ?: throw offline
    }

    private suspend fun cachedDetail(id: Int): DraftDetail? {
        val cached = dao.draft(id) ?: return null
        val content = cached.content ?: return null
        val hash = cached.contentHash ?: return null
        val version = DraftVersion(
            id = -1,
            label = "cached",
            content = content,
            hook = cached.hook,
            charCount = cached.charCount ?: content.length,
            contentHash = hash,
            origin = "LLM",
            createdAt = "",
        )
        return DraftDetail(
            id = cached.id,
            title = cached.title,
            postType = cached.postType,
            category = "",
            status = cached.status,
            createdAt = "",
            qualityScore = cached.qualityScore,
            aiSlopProbability = cached.aiSlopProbability,
            charCount = cached.charCount,
            hook = cached.hook,
            preview = cached.preview,
            versionCount = cached.versionCount,
            generationReason = "Showing the saved copy - the backend is not reachable.",
            currentVersion = version,
            versions = listOf(version),
        )
    }

    private suspend fun fetchAndCacheDetail(id: Int): DraftDetail {
        val detail = api.draft(id)
        detail.currentVersion?.let { version ->
            dao.upsertDrafts(
                listOf(
                    CachedDraft(
                        id = detail.id, title = detail.title, postType = detail.postType,
                        status = detail.status, qualityScore = detail.qualityScore,
                        aiSlopProbability = detail.aiSlopProbability, charCount = version.charCount,
                        hook = version.hook, preview = detail.preview,
                        versionCount = detail.versionCount, contentHash = version.contentHash,
                        content = version.content,
                    )
                )
            )
        }
        return detail
    }

    suspend fun cachedDraft(id: Int): CachedDraft? = dao.draft(id)

    suspend fun pendingFor(draftId: Int): PendingAction? = dao.pendingFor(draftId)

    suspend fun cancelPending(draftId: Int) {
        val pending = dao.pendingFor(draftId) ?: return
        dao.removePending(pending.clientActionId)
    }

    suspend fun saveEditOffline(draftId: Int, content: String) {
        val cached = dao.draft(draftId) ?: return
        dao.upsertDrafts(
            listOf(
                cached.copy(
                    content = content,
                    charCount = content.length,
                    updatedAt = System.currentTimeMillis(),
                )
            )
        )
    }

    /**
     * Record a decision. Tries the server first; if the phone is offline the
     * action is queued and synced later, exactly once.
     *
     * Returns null when the decision was queued rather than sent.
     */
    suspend fun submitDecision(
        draftId: Int,
        action: String,
        expectedContentHash: String?,
        editedContent: String? = null,
        rejectionReason: String? = null,
        note: String? = null,
    ): ApprovalResponse? {
        val clientActionId = UUID.randomUUID().toString()
        val request = ApprovalRequest(
            draftId = draftId,
            action = action,
            expectedContentHash = expectedContentHash,
            editedContent = editedContent,
            rejectionReason = rejectionReason,
            note = note,
            clientActionId = clientActionId,
        )
        return try {
            api.submitApproval(request)
        } catch (offline: OfflineException) {
            dao.enqueue(
                PendingAction(
                    clientActionId = clientActionId,
                    draftId = draftId,
                    action = action,
                    expectedContentHash = expectedContentHash,
                    editedContent = editedContent,
                    rejectionReason = rejectionReason,
                    note = note,
                )
            )
            com.linkedincopilot.app.notifications.NotificationWorker.triggerImmediateSync(context)
            null
        }
    }

    /**
     * Flush queued decisions.
     *
     * A rejection from the server (409, the draft changed) is terminal: the
     * action is dropped so the user is asked to review the new version,
     * rather than retried forever against content they never saw.
     */
    suspend fun syncPending(): SyncResult {
        var sent = 0
        var conflicted = 0
        for (action in dao.pendingActions()) {
            try {
                api.submitApproval(
                    ApprovalRequest(
                        draftId = action.draftId,
                        action = action.action,
                        expectedContentHash = action.expectedContentHash,
                        editedContent = action.editedContent,
                        rejectionReason = action.rejectionReason,
                        note = action.note,
                        clientActionId = action.clientActionId,
                    )
                )
                dao.removePending(action.clientActionId)
                val cached = dao.draft(action.draftId)
                if (cached != null) {
                    val newStatus = when (action.action) {
                        "APPROVE" -> "SCHEDULED"
                        "REJECT" -> "REJECTED"
                        "SAVE_FOR_LATER" -> "SAVED_FOR_LATER"
                        else -> cached.status
                    }
                    dao.upsertDrafts(listOf(cached.copy(status = newStatus)))
                }
                sent++
            } catch (e: ApiException) {
                if (e.status == 409 || e.status == 404 || e.status == 422) {
                    dao.removePending(action.clientActionId)
                    conflicted++
                } else {
                    dao.markFailed(action.clientActionId, e.message)
                }
            } catch (e: OfflineException) {
                break // still offline; try again next time
            }
        }
        return SyncResult(sent = sent, conflicted = conflicted)
    }

    data class SyncResult(val sent: Int, val conflicted: Int)

    private companion object {
        // Enough to cover a normal review queue without a slow refresh.
        const val PREFETCH_LIMIT = 10
    }
}

private fun CachedDraft.toSummary(): DraftSummary = DraftSummary(
    id = id,
    title = title,
    postType = postType,
    category = "",
    status = status,
    createdAt = "",
    proposedPublishAt = null,
    qualityScore = qualityScore,
    aiSlopProbability = aiSlopProbability,
    charCount = charCount,
    hook = hook,
    preview = preview,
    versionCount = versionCount,
)
