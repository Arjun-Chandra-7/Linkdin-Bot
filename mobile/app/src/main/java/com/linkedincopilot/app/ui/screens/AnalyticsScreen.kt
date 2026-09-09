package com.linkedincopilot.app.ui.screens

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
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import com.linkedincopilot.app.data.MetricsInput
import com.linkedincopilot.app.ui.AppState
import com.linkedincopilot.app.ui.AppViewModel
import com.linkedincopilot.app.ui.Fmt
import com.linkedincopilot.app.ui.components.EmptyState
import com.linkedincopilot.app.ui.components.Metric
import com.linkedincopilot.app.ui.components.SectionHeader
import com.linkedincopilot.app.ui.components.StatusPill
import com.linkedincopilot.app.ui.components.postTypeLabel

/**
 * Analytics.
 *
 * Two rules on this screen: never show a number that was not measured, and
 * never state a pattern the sample size cannot support. Confidence is printed
 * next to every insight.
 */
@Composable
fun AnalyticsScreen(vm: AppViewModel, state: AppState) {
    LaunchedEffect(Unit) { vm.loadAnalytics() }
    val analytics = state.analytics

    if (analytics == null && state.loading) return
    if (analytics == null || analytics.publishedCount == 0) {
        EmptyState(
            title = "No analytics yet",
            body = analytics?.emptyState
                ?: "Publish your first post to begin learning what works.",
        )
        return
    }

    var editingPost by remember { mutableStateOf<Int?>(null) }
    var impressions by remember { mutableStateOf("") }
    var reactions by remember { mutableStateOf("") }
    var comments by remember { mutableStateOf("") }

    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item {
            Text(
                "Analytics",
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.padding(top = 20.dp),
            )
        }

        item {
            Row(
                Modifier.fillMaxWidth().padding(top = 8.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Metric("Published", analytics.publishedCount.toString())
                Metric("With metrics", analytics.postsWithMetrics.toString())
                Metric("Best format", analytics.bestFormat?.let { postTypeLabel(it) })
            }
        }

        analytics.emptyState?.let { note ->
            item {
                Card(
                    Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant
                    ),
                ) {
                    Text(
                        note,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(16.dp),
                    )
                }
            }
        }

        if (analytics.insights.isNotEmpty()) {
            item { SectionHeader("What the data suggests") }
            items(analytics.insights, key = { it.dimension + it.segment }) { insight ->
                Card(
                    Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant
                    ),
                ) {
                    Column(Modifier.padding(16.dp)) {
                        Text(insight.statement, style = MaterialTheme.typography.bodyMedium)
                        Row(
                            Modifier.fillMaxWidth().padding(top = 8.dp),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            StatusPill(
                                insight.confidence.lowercase().replace('_', ' '),
                                when (insight.confidence) {
                                    "STRONG_SIGNAL" -> MaterialTheme.colorScheme.primary
                                    "MODERATE_CONFIDENCE" -> MaterialTheme.colorScheme.secondary
                                    else -> MaterialTheme.colorScheme.onSurfaceVariant
                                },
                            )
                            Text(
                                "n=${insight.sampleSize}",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            }
        }

        item { SectionHeader("Published posts") }
        items(analytics.posts, key = { it.publishedPostId }) { post ->
            Card(
                Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant
                ),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Text(post.title, style = MaterialTheme.typography.titleMedium, maxLines = 2)
                    Text(
                        "${postTypeLabel(post.postType)} · ${Fmt.day(post.publishedAt)}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 4.dp),
                    )

                    if (post.hasData) {
                        Row(
                            Modifier.fillMaxWidth().padding(top = 12.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Metric("Impressions", post.impressions?.toString())
                            Metric("Reactions", post.reactions?.toString())
                            Metric("Comments", post.comments?.toString())
                        }
                    } else if (editingPost == post.publishedPostId) {
                        Text(
                            "Copy the numbers from LinkedIn:",
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.padding(top = 8.dp),
                        )
                        Row(
                            Modifier.fillMaxWidth().padding(top = 8.dp),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            OutlinedTextField(
                                value = impressions, onValueChange = { impressions = it },
                                label = { Text("Views") }, singleLine = true,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                modifier = Modifier.weight(1f),
                            )
                            OutlinedTextField(
                                value = reactions, onValueChange = { reactions = it },
                                label = { Text("Reactions") }, singleLine = true,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                modifier = Modifier.weight(1f),
                            )
                            OutlinedTextField(
                                value = comments, onValueChange = { comments = it },
                                label = { Text("Comments") }, singleLine = true,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                modifier = Modifier.weight(1f),
                            )
                        }
                        TextButton(onClick = {
                            vm.recordMetrics(
                                post.publishedPostId,
                                MetricsInput(
                                    impressions = impressions.toIntOrNull(),
                                    reactions = reactions.toIntOrNull(),
                                    comments = comments.toIntOrNull(),
                                ),
                            )
                            editingPost = null
                            impressions = ""; reactions = ""; comments = ""
                        }) { Text("Save metrics") }
                    } else {
                        TextButton(onClick = { editingPost = post.publishedPostId }) {
                            Text("Add metrics")
                        }
                    }
                }
            }
        }
        item { Column(Modifier.padding(bottom = 24.dp)) {} }
    }
}
