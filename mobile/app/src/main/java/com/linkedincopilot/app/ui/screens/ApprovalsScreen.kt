package com.linkedincopilot.app.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.linkedincopilot.app.data.DraftSummary
import com.linkedincopilot.app.ui.AppState
import com.linkedincopilot.app.ui.Fmt
import com.linkedincopilot.app.ui.components.EmptyState
import com.linkedincopilot.app.ui.components.StatusPill
import com.linkedincopilot.app.ui.components.postTypeLabel
import com.linkedincopilot.app.ui.components.statusColor
import com.linkedincopilot.app.ui.components.statusLabel

@Composable
fun ApprovalsScreen(state: AppState, onOpen: (Int) -> Unit) {
    if (state.drafts.isEmpty() && !state.loading) {
        EmptyState(
            title = "Nothing to review",
            body = "When the copilot writes something worth your time, it will appear here. "
                + "Weak drafts are rejected before they reach your phone.",
        )
        return
    }

    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Text(
                "Approvals",
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.padding(top = 20.dp, bottom = 4.dp),
            )
        }
        items(state.drafts, key = { it.id }) { draft ->
            DraftCard(draft) { onOpen(draft.id) }
        }
        item { Column(Modifier.padding(bottom = 24.dp)) {} }
    }
}

@Composable
private fun DraftCard(draft: DraftSummary, onClick: () -> Unit) {
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
                StatusPill(statusLabel(draft.status), statusColor(draft.status))
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
