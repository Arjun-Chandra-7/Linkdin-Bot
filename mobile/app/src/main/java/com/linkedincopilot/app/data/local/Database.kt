package com.linkedincopilot.app.data.local

import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

/**
 * Offline cache and the outbound action queue.
 *
 * Two jobs:
 *  1. Keep the approval queue readable when the laptop is asleep.
 *  2. Hold decisions made offline until they can be sent - exactly once.
 */

@Entity(tableName = "cached_drafts")
data class CachedDraft(
    @PrimaryKey val id: Int,
    val title: String,
    val postType: String,
    val status: String,
    val qualityScore: Int?,
    val aiSlopProbability: Double?,
    val charCount: Int?,
    val hook: String?,
    val preview: String?,
    val versionCount: Int,
    val contentHash: String?,
    val content: String?,
    val updatedAt: Long = System.currentTimeMillis(),
)

/**
 * A decision taken on the phone that has not reached the server yet.
 *
 * [clientActionId] is generated once, when the user taps - not when the sync
 * runs - so a retry after a dropped response can never record a second
 * approval. [expectedContentHash] is what the user actually read, so if the
 * draft changed while the phone was offline the server refuses it rather than
 * approving text nobody saw.
 */
@Entity(tableName = "pending_actions")
data class PendingAction(
    @PrimaryKey val clientActionId: String,
    val draftId: Int,
    val action: String,
    val expectedContentHash: String?,
    val editedContent: String?,
    val rejectionReason: String?,
    val note: String?,
    val scheduledAt: String? = null,
    val createdAt: Long = System.currentTimeMillis(),
    val attempts: Int = 0,
    val lastError: String? = null,
)

@Dao
interface CopilotDao {
    @Query("SELECT * FROM cached_drafts ORDER BY updatedAt DESC")
    fun observeDrafts(): Flow<List<CachedDraft>>

    @Query("SELECT * FROM cached_drafts ORDER BY updatedAt DESC")
    suspend fun getCachedDrafts(): List<CachedDraft>

    @Query("SELECT * FROM cached_drafts WHERE id = :id")
    suspend fun draft(id: Int): CachedDraft?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertDrafts(drafts: List<CachedDraft>)

    @Query("DELETE FROM cached_drafts WHERE id NOT IN (:keepIds)")
    suspend fun pruneDrafts(keepIds: List<Int>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun enqueue(action: PendingAction)

    @Query("SELECT * FROM pending_actions ORDER BY createdAt")
    suspend fun pendingActions(): List<PendingAction>

    @Query("SELECT * FROM pending_actions ORDER BY createdAt")
    fun observePending(): Flow<List<PendingAction>>

    @Query("SELECT * FROM pending_actions WHERE draftId = :draftId LIMIT 1")
    suspend fun pendingFor(draftId: Int): PendingAction?

    @Query("DELETE FROM pending_actions WHERE clientActionId = :id")
    suspend fun removePending(id: String)

    @Query("UPDATE pending_actions SET attempts = attempts + 1, lastError = :error WHERE clientActionId = :id")
    suspend fun markFailed(id: String, error: String)

    @Query("SELECT COUNT(*) FROM pending_actions")
    fun pendingCount(): Flow<Int>
}

@Database(entities = [CachedDraft::class, PendingAction::class], version = 2, exportSchema = false)
abstract class CopilotDatabase : RoomDatabase() {
    abstract fun dao(): CopilotDao
}
