package com.linkedincopilot.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.linkedincopilot.app.data.DraftDetail
import com.linkedincopilot.app.ui.AppState
import com.linkedincopilot.app.ui.AppViewModel
import com.linkedincopilot.app.ui.components.ErrorState
import com.linkedincopilot.app.ui.components.KeyValueRow
import com.linkedincopilot.app.ui.components.LoadingState
import com.linkedincopilot.app.ui.components.ScheduleTimeSelector
import com.linkedincopilot.app.ui.components.SectionHeader
import com.linkedincopilot.app.ui.components.StatusPill
import com.linkedincopilot.app.ui.components.postTypeLabel
import com.linkedincopilot.app.ui.components.statusColor
import com.linkedincopilot.app.ui.components.statusLabel
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive

private val REJECTION_REASONS = listOf(
    "TOO_GENERIC" to "Too generic",
    "SOUNDS_AI_GENERATED" to "Sounds AI-generated",
    "BAD_HOOK" to "Bad hook",
    "INCORRECT" to "Incorrect",
    "TOO_LONG" to "Too long",
    "NOT_INTERESTING" to "Not interesting",
    "TOO_CRINGE" to "Too cringe",
    "ALREADY_POSTED_SIMILAR" to "Already posted something similar",
    "OTHER" to "Other",
)

private val REWRITES = listOf(
    "shorten" to "Shorten",
    "expand" to "Expand",
    "more_technical" to "More technical",
    "more_casual" to "More casual",
    "rewrite_hook" to "New hook",
    "regenerate" to "Regenerate",
)

/**
 * The most important screen in the app: everything needed to judge a post,
 * and nothing else.
 *
 * The approval always carries the hash of the exact text on screen, so the
 * server can refuse it if the draft changed underneath - approving one post
 * and publishing another is impossible by construction.
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun ApprovalDetailScreen(
    draftId: Int,
    vm: AppViewModel,
    state: AppState,
    onBack: () -> Unit,
) {
    var detail by remember { mutableStateOf<DraftDetail?>(null) }
    var selectedScheduledAt by remember { mutableStateOf<String?>(null) }
    var originalContent by remember { mutableStateOf<String?>(null) }
    var editing by remember { mutableStateOf(false) }
    var editedText by remember { mutableStateOf("") }
    var showReject by remember { mutableStateOf(false) }
    var rejectReason by remember { mutableStateOf("TOO_GENERIC") }
    var rejectNote by remember { mutableStateOf("") }
    var loadError by remember { mutableStateOf<String?>(null) }

    val pending = state.pendingActionMap[draftId]

    suspend fun load() {
        runCatching { vm.draftDetail(draftId) }
            .onSuccess {
                detail = it
                editedText = it.currentVersion?.content.orEmpty()
                originalContent = it.currentVersion?.content
                if (selectedScheduledAt == null) {
                    selectedScheduledAt = it.proposedPublishAt
                }
                loadError = null
            }
            .onFailure { loadError = it.message }
    }

    LaunchedEffect(draftId) { load() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (editing) "Edit post" else "Review post") },
                navigationIcon = {
                    IconButton(onClick = { if (editing) editing = false else onBack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        }
    ) { padding ->
        val current = detail
        when {
            loadError != null -> Box(Modifier.padding(padding)) {
                ErrorState(loadError!!, "Pull back and try again.")
            }
            current == null -> Box(Modifier.padding(padding)) { LoadingState() }
            else -> {
                val version = current.currentVersion
                val quality = version?.quality
                Column(
                    Modifier
                        .fillMaxSize()
                        .padding(padding)
                        .verticalScroll(rememberScrollState())
                        .padding(horizontal = 16.dp),
                ) {
                    Row(
                        Modifier.fillMaxWidth().padding(top = 8.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        StatusPill(postTypeLabel(current.postType), MaterialTheme.colorScheme.secondary)
                        if (pending != null) {
                            when (pending.action) {
                                "APPROVE" -> StatusPill("Queued for sync", MaterialTheme.colorScheme.tertiary)
                                "REJECT" -> StatusPill("Rejection queued", MaterialTheme.colorScheme.error)
                                "SAVE_FOR_LATER" -> StatusPill("Save queued", MaterialTheme.colorScheme.secondary)
                                else -> StatusPill("Action queued", MaterialTheme.colorScheme.outline)
                            }
                        } else {
                            StatusPill(statusLabel(current.status), statusColor(current.status))
                        }
                        if (version?.id == -1) {
                            StatusPill("Offline copy", MaterialTheme.colorScheme.error)
                        }
                    }

                    if (pending != null) {
                        Card(
                            Modifier.fillMaxWidth().padding(top = 12.dp),
                            colors = CardDefaults.cardColors(
                                containerColor = MaterialTheme.colorScheme.tertiaryContainer
                            ),
                        ) {
                            Column(Modifier.padding(14.dp)) {
                                Text(
                                    when (pending.action) {
                                        "APPROVE" -> "Approval is queued locally. It will sync automatically when your laptop is reachable."
                                        "REJECT" -> "Rejection is queued locally. It will sync automatically when your laptop is reachable."
                                        else -> "Decision is queued locally."
                                    },
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onTertiaryContainer,
                                )
                                TextButton(
                                    onClick = { vm.cancelPending(draftId) },
                                    modifier = Modifier.padding(top = 4.dp),
                                ) {
                                    Text("Cancel queued decision", color = MaterialTheme.colorScheme.onTertiaryContainer)
                                }
                            }
                        }
                    } else if (version?.id == -1) {
                        Card(
                            Modifier.fillMaxWidth().padding(top = 12.dp),
                            colors = CardDefaults.cardColors(
                                containerColor = MaterialTheme.colorScheme.errorContainer
                            ),
                        ) {
                            Text(
                                "The backend is not reachable, so this is the copy saved on your "
                                    + "phone. You can still approve or reject it - the decision is "
                                    + "queued and sent once your laptop is back.",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onErrorContainer,
                                modifier = Modifier.padding(14.dp),
                            )
                        }
                    }

                    // ---- The post itself ----
                    if (editing) {
                        OutlinedTextField(
                            value = editedText,
                            onValueChange = { editedText = it },
                            label = { Text("Post text") },
                            modifier = Modifier.fillMaxWidth().padding(top = 16.dp),
                            minLines = 12,
                        )
                        Text(
                            "${editedText.length} characters",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 4.dp),
                        )
                    } else {
                        Card(
                            Modifier.fillMaxWidth().padding(top = 16.dp),
                            colors = CardDefaults.cardColors(
                                containerColor = MaterialTheme.colorScheme.surfaceVariant
                            ),
                        ) {
                            Text(
                                version?.content.orEmpty(),
                                style = MaterialTheme.typography.bodyLarge,
                                modifier = Modifier.padding(16.dp),
                            )
                        }
                    }

                    // ---- Variants ----
                    if (current.versions.size > 1 && !editing) {
                        SectionHeader("Versions")
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            current.versions.forEach { candidate ->
                                FilterChip(
                                    selected = candidate.id == version?.id,
                                    onClick = {
                                        vm.selectVersion(draftId, candidate.id) {
                                            detail = it
                                            editedText = it.currentVersion?.content.orEmpty()
                                        }
                                    },
                                    label = { Text("${candidate.label} · ${candidate.charCount}") },
                                )
                            }
                        }
                    }

                    // ---- Why this exists ----
                    SectionHeader("Why this was written")
                    Text(
                        current.generationReason ?: "Added from your own notes.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )

                    // ---- Quality, honestly reported ----
                    if (quality != null) {
                        SectionHeader("Quality check")
                        fun field(key: String): String? =
                            quality[key]?.let { element ->
                                runCatching { element.jsonPrimitive.content }.getOrNull()
                            }
                        KeyValueRow("Quality score", field("quality") ?: "—")
                        KeyValueRow("AI-slop probability", field("ai_slop_probability") ?: "—")
                        KeyValueRow("Originality", field("originality") ?: "—")

                        // Issues are the actionable part: say what is wrong with it.
                        val issues = quality["issues"]
                            ?.let { runCatching { it.jsonArray }.getOrNull() }
                            ?.mapNotNull { runCatching { it.jsonPrimitive.content }.getOrNull() }
                            .orEmpty()
                        issues.forEach { issue ->
                            Text(
                                "\u2022 $issue",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.error,
                                modifier = Modifier.padding(top = 2.dp),
                            )
                        }
                    }

                    // ---- Sources ----
                    if (current.sources.isNotEmpty()) {
                        SectionHeader("Sources")
                        current.sources.forEach { source ->
                            Text(
                                source.title ?: source.url.orEmpty(),
                                style = MaterialTheme.typography.bodyMedium,
                            )
                            source.url?.let {
                                Text(
                                    it,
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }

                    // A relative estimate from this account's own history, shown
                    // only when there is enough data. Never framed as reach.
                    current.predictedPerformance?.let { prediction ->
                        val expected = prediction["expected"]
                            ?.let { runCatching { it.jsonPrimitive.content }.getOrNull() }
                        if (expected != null && expected != "UNKNOWN") {
                            SectionHeader("Expected performance")
                            Text(expected, style = MaterialTheme.typography.titleMedium)
                            val confidence = prediction["confidence"]
                                ?.let { runCatching { it.jsonPrimitive.content }.getOrNull() }
                            if (confidence != null) {
                                Text(
                                    "Confidence: ${confidence.lowercase().replace('_', ' ')}",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            prediction["reasons"]
                                ?.let { runCatching { it.jsonArray }.getOrNull() }
                                ?.mapNotNull { runCatching { it.jsonPrimitive.content }.getOrNull() }
                                ?.forEach { reason ->
                                    Text(
                                        reason,
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        modifier = Modifier.padding(top = 2.dp),
                                    )
                                }
                        }
                    }

                    current.uncertaintyNotes?.let { note ->
                        SectionHeader("Not verified")
                        Text(
                            note,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }

                    // ---- Rewrite tools ----
                    if (!editing && version?.id != -1) {
                        SectionHeader("Rewrite")
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            REWRITES.forEach { (op, label) ->
                                AssistChip(
                                    onClick = {
                                        vm.rewrite(draftId, op, null) {
                                            detail = it
                                            editedText = it.currentVersion?.content.orEmpty()
                                        }
                                    },
                                    label = { Text(label) },
                                )
                            }
                        }
                    }

                    // ---- Reject flow ----
                    if (showReject) {
                        SectionHeader("Why are you rejecting it?")
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            REJECTION_REASONS.forEach { (value, label) ->
                                FilterChip(
                                    selected = rejectReason == value,
                                    onClick = { rejectReason = value },
                                    label = { Text(label) },
                                )
                            }
                        }
                        OutlinedTextField(
                            value = rejectNote,
                            onValueChange = { rejectNote = it },
                            label = { Text("Optional note") },
                            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                        )
                        Row(
                            Modifier.fillMaxWidth().padding(top = 8.dp),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Button(
                                onClick = {
                                    version?.let {
                                        vm.reject(draftId, it.contentHash, rejectReason,
                                            rejectNote.ifBlank { null }) { onBack() }
                                    }
                                },
                                modifier = Modifier.weight(1f),
                            ) { Text("Confirm rejection") }
                            OutlinedButton(
                                onClick = { showReject = false },
                                modifier = Modifier.weight(1f),
                            ) { Text("Cancel") }
                        }
                    }

                    // ---- Schedule Time Frame ----
                    if (!showReject && pending == null) {
                        SectionHeader("Scheduled publish time")
                        ScheduleTimeSelector(
                            selectedIso = selectedScheduledAt,
                            onSelected = { selectedScheduledAt = it },
                            label = "Select time frame to post",
                        )
                    }

                    // ---- Primary actions ----
                    if (!showReject) {
                        if (pending != null) {
                            Row(
                                Modifier.fillMaxWidth().padding(top = 24.dp, bottom = 32.dp),
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                Button(
                                    onClick = { vm.cancelPending(draftId) },
                                    modifier = Modifier.weight(1f),
                                ) { Text("Cancel queued decision") }
                                OutlinedButton(
                                    onClick = onBack,
                                    modifier = Modifier.weight(1f),
                                ) { Text("Back to queue") }
                            }
                        } else {
                            Row(
                                Modifier.fillMaxWidth().padding(top = 24.dp),
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                Button(
                                    onClick = {
                                        val hash = version?.contentHash ?: return@Button
                                        val edited = editedText.takeIf {
                                            editing && it != (originalContent ?: version.content)
                                        }
                                        vm.approve(draftId, hash, edited, scheduledAt = selectedScheduledAt) { onBack() }
                                    },
                                    enabled = !state.loading && version != null,
                                    modifier = Modifier.weight(1f),
                                ) { Text(if (editing) "Approve edit" else "Approve") }

                                OutlinedButton(
                                    onClick = {
                                        if (editing) {
                                            version?.let {
                                                if (version.id == -1) {
                                                    detail = detail?.copy(
                                                        currentVersion = version.copy(
                                                            content = editedText,
                                                            charCount = editedText.length,
                                                        )
                                                    )
                                                    vm.saveEditOffline(draftId, editedText)
                                                    editing = false
                                                } else {
                                                    vm.saveEdit(draftId, editedText, it.contentHash) { updated ->
                                                        detail = updated
                                                        editedText = updated.currentVersion?.content.orEmpty()
                                                        originalContent = updated.currentVersion?.content
                                                        editing = false
                                                    }
                                                }
                                            }
                                        } else {
                                            editing = true
                                        }
                                    },
                                    modifier = Modifier.weight(1f),
                                ) { Text(if (editing) "Save edit" else "Edit") }
                            }

                            Row(
                                Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 32.dp),
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                TextButton(
                                    onClick = { showReject = true },
                                    modifier = Modifier.weight(1f),
                                ) { Text("Reject") }
                                TextButton(
                                    onClick = {
                                        version?.let {
                                            vm.saveForLater(draftId, it.contentHash) { onBack() }
                                        }
                                    },
                                    modifier = Modifier.weight(1f),
                                ) { Text("Save for later") }
                            }
                        }
                    }
                }
            }
        }
    }
}
