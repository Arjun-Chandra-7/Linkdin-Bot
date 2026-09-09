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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.linkedincopilot.app.ui.AppState
import com.linkedincopilot.app.ui.AppViewModel
import com.linkedincopilot.app.ui.Fmt
import com.linkedincopilot.app.ui.components.EmptyState
import com.linkedincopilot.app.ui.components.StatusPill
import com.linkedincopilot.app.ui.components.postTypeLabel
import com.linkedincopilot.app.ui.components.statusColor
import com.linkedincopilot.app.ui.components.statusLabel

@Composable
fun CalendarScreen(vm: AppViewModel, state: AppState, onOpen: (Int) -> Unit) {
    LaunchedEffect(Unit) { vm.loadCalendar() }

    if (state.calendar.isEmpty() && !state.loading) {
        EmptyState(
            title = "Nothing on the calendar",
            body = "Approved posts appear here with their scheduled time.",
        )
        return
    }

    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Text(
                "Calendar",
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.padding(top = 20.dp, bottom = 4.dp),
            )
        }
        items(state.calendar, key = { it.draftId }) { entry ->
            Card(
                Modifier.fillMaxWidth().clickable { onOpen(entry.draftId) },
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant
                ),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text(
                            when {
                                entry.publishedAt != null -> "Published ${Fmt.day(entry.publishedAt)}"
                                entry.scheduledAt != null -> Fmt.relativeDay(entry.scheduledAt)
                                else -> "Not scheduled"
                            },
                            style = MaterialTheme.typography.titleMedium,
                        )
                        StatusPill(statusLabel(entry.status), statusColor(entry.status))
                    }
                    Text(
                        entry.title,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.padding(top = 6.dp),
                    )
                    Text(
                        postTypeLabel(entry.postType),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 6.dp),
                    )
                }
            }
        }
        item { Column(Modifier.padding(bottom = 24.dp)) {} }
    }
}
