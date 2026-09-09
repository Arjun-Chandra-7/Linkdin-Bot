package com.linkedincopilot.app.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.item
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.linkedincopilot.app.ui.AppState
import com.linkedincopilot.app.ui.AppViewModel
import com.linkedincopilot.app.ui.Fmt
import com.linkedincopilot.app.ui.components.Metric
import com.linkedincopilot.app.ui.components.SectionHeader
import com.linkedincopilot.app.ui.components.postTypeLabel

/**
 * The dashboard shows only things that are true right now.
 *
 * There are no vanity metrics and no invented percentages: if nothing has been
 * published, it says so rather than filling the screen with zeros dressed up
 * as insights.
 */
@Composable
fun HomeScreen(
    vm: AppViewModel,
    state: AppState,
    onOpenApprovals: () -> Unit,
    onOpenCalendar: () -> Unit,
    onOpenNetwork: () -> Unit,
    onOpenAnalytics: () -> Unit,
) {
    val home = state.home

    LazyColumn(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        item {
            Text(
                "LinkedIn Copilot",
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.padding(top = 20.dp),
            )
        }

        // The single most useful line on the screen.
        item {
            val pending = home?.pendingApprovals ?: 0
            Card(
                Modifier.fillMaxWidth().padding(top = 12.dp).clickable(onClick = onOpenApprovals),
                colors = CardDefaults.cardColors(
                    containerColor = if (pending > 0) MaterialTheme.colorScheme.primaryContainer
                    else MaterialTheme.colorScheme.surfaceVariant
                ),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Text(
                        when (pending) {
                            0 -> "Nothing waiting on you"
                            1 -> "1 draft needs approval"
                            else -> "$pending drafts need approval"
                        },
                        style = MaterialTheme.typography.titleMedium,
                        color = if (pending > 0) MaterialTheme.colorScheme.onPrimaryContainer
                        else MaterialTheme.colorScheme.onSurface,
                    )
                    if (pending > 0) {
                        Text(
                            "Review them before they can be scheduled.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.8f),
                            modifier = Modifier.padding(top = 2.dp),
                        )
                    }
                }
            }
        }

        item {
            Row(
                Modifier.fillMaxWidth().padding(top = 16.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Metric("Scheduled", home?.scheduledPosts?.toString())
                Metric("Published this week", home?.publishedThisWeek?.toString())
                Metric("People to review", home?.suggestedConnections?.toString())
            }
        }

        if (home?.nextScheduledAt != null) {
            item {
                SectionHeader("Next scheduled")
                Card(
                    Modifier.fillMaxWidth().clickable(onClick = onOpenCalendar),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant
                    ),
                ) {
                    Column(Modifier.padding(16.dp)) {
                        Text(Fmt.relativeDay(home.nextScheduledAt), style = MaterialTheme.typography.titleMedium)
                        home.nextScheduledTitle?.let {
                            Text(
                                it,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(top = 4.dp),
                            )
                        }
                    }
                }
            }
        }

        // Only shown once there is enough history for it to mean something.
        home?.bestRecentFormat?.let { format ->
            item {
                SectionHeader("What is working")
                Card(
                    Modifier.fillMaxWidth().clickable(onClick = onOpenAnalytics),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant
                    ),
                ) {
                    Column(Modifier.padding(16.dp)) {
                        Text("Best recent format", style = MaterialTheme.typography.labelSmall)
                        Text(
                            postTypeLabel(format),
                            style = MaterialTheme.typography.titleMedium,
                            modifier = Modifier.padding(top = 2.dp),
                        )
                    }
                }
            }
        }

        item {
            SectionHeader("Backend")
            Card(
                Modifier.fillMaxWidth(),
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
                            if (state.error?.offline == true) "Not reachable" else "Connected",
                            style = MaterialTheme.typography.titleMedium,
                            color = if (state.error?.offline == true) MaterialTheme.colorScheme.error
                            else MaterialTheme.colorScheme.primary,
                        )
                        Text(
                            vm.serverName ?: vm.baseUrl.orEmpty(),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    if (state.pendingSync > 0) {
                        Text(
                            "${state.pendingSync} decision(s) waiting to sync",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 6.dp),
                        )
                    }
                }
            }
        }

        item {
            Row(Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 24.dp)) {
                TextButton(onClick = { vm.runDiscovery() }) { Text("Look for ideas now") }
                TextButton(onClick = onOpenNetwork) { Text("People") }
            }
        }
    }
}
