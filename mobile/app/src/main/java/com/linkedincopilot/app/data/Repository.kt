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
class Repository(context: Context, val store: SecureStore) {

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
        val response = api.pair(baseUrl, code, deviceName)
        store.baseUrl = baseUrl.trimEnd('/')
        store.token = response.token
        store.deviceId = response.deviceId
        store.serverName = response.serverName
        return response
    }

    fun unpair() {
        store.clear()
    }

    /** Refresh the review queue and cache it for offline reading. */
    suspend fun refreshDrafts(): List<DraftSummary> {
        val response = api.drafts()
        val cached = response.items.map {
            CachedDraft(
                id = it.id, title = it.title, postType = it.postType, status = it.status,
                qualityScore = it.qualityScore, aiSlopProbability = it.aiSlopProbability,
                charCount = it.charCount, hook = it.hook, preview = it.preview,
                versionCount = it.versionCount, contentHash = null, content = null,
            )
        }
        dao.upsertDrafts(cached)
        dao.pruneDrafts(cached.map { it.id }.ifEmpty { listOf(-1) })
        return response.items
    }

    suspend fun draftDetail(id: Int): DraftDetail {
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
}
