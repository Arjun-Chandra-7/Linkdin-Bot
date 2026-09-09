package com.linkedincopilot.app.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.linkedincopilot.app.data.DraftSummary
import com.linkedincopilot.app.data.local.PendingAction
import com.linkedincopilot.app.ui.AppState
import com.linkedincopilot.app.ui.AppViewModel
import com.linkedincopilot.app.ui.Fmt
import com.linkedincopilot.app.ui.components.CreateIdeaDialog
import com.linkedincopilot.app.ui.components.EmptyState
import com.linkedincopilot.app.ui.components.StatusPill
import com.linkedincopilot.app.ui.components.postTypeLabel
import com.linkedincopilot.app.ui.components.statusColor
import com.linkedincopilot.app.ui.components.statusLabel

@Composable
fun ApprovalsScreen(
    vm: AppViewModel,
    state: AppState,
    onOpen: (Int) -> Unit,
) {
    var showCreateDialog by remember { mutableStateOf(false) }

    if (showCreateDialog) {
        CreateIdeaDialog(
            vm = vm,
            onDismiss = { showCreateDialog = false },
            onDraftCreated = { draftId -> onOpen(draftId) },
        )
    }

    Scaffold(
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { showCreateDialog = true },
                icon = { Icon(Icons.Filled.Add, contentDescription = "Add custom idea") },
                text = { Text("New Idea") },
            )
        }
    ) { padding ->
        if (state.drafts.isEmpty() && !state.loading) {
            Box(Modifier.fillMaxSize().padding(padding)) {
                EmptyState(
                    title = "Nothing to review",
                    body = "When the copilot writes something worth your time, it will appear here. "
                        + "You can also write custom posts around your own ideas.",
                    actionLabel = "Create custom idea",
                    onAction = { showCreateDialog = true },
                )
            }
            return@Scaffold
        }

        LazyColumn(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item {
                Row(
                    Modifier.fillMaxWidth().padding(top = 20.dp, bottom = 4.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(
                        "Approvals",
                        style = MaterialTheme.typography.headlineSmall,
                    )
                }
            }
            items(state.drafts, key = { it.id }) { draft ->
                val pending = state.pendingActionMap[draft.id]
                DraftCard(draft, pending) { onOpen(draft.id) }
            }
            item { Column(Modifier.padding(bottom = 80.dp)) {} }
        }
    }
}

@Composable
private fun DraftCard(draft: DraftSummary, pending: PendingAction?, onClick: () -> Unit) {
    Card(
        Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                StatusPill(postTypeLabel(draft.postType), MaterialTheme.colorScheme.secondary)
                if (pending != null) {
                    when (pending.action) {
                        "APPROVE" -> StatusPill("Queued for sync", MaterialTheme.colorScheme.tertiary)
                        "REJECT" -> StatusPill("Rejection queued", MaterialTheme.colorScheme.error)
                        "SAVE_FOR_LATER" -> StatusPill("Save queued", MaterialTheme.colorScheme.secondary)
                        else -> StatusPill("Action queued", MaterialTheme.colorScheme.outline)
                    }
                } else {
                    StatusPill(statusLabel(draft.status), statusColor(draft.status))
                }
            }

            Text(
                draft.hook ?: draft.title,
                style = MaterialTheme.typography.titleMedium,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(top = 10.dp),
            )
            draft.preview?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 6.dp),
                )
            }

            Row(
                Modifier.fillMaxWidth().padding(top = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                draft.qualityScore?.let {
                    Text(
                        "Quality $it",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                draft.charCount?.let {
                    Text(
                        "$it chars",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (draft.versionCount > 1) {
                    Text(
                        "${draft.versionCount} versions",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text(
                    Fmt.ago(draft.createdAt),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}
