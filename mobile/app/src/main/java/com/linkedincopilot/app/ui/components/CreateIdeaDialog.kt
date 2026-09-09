package com.linkedincopilot.app.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.linkedincopilot.app.ui.AppViewModel

private val CATEGORIES = listOf(
    "BUILD_LOG" to "Build Log",
    "TECHNICAL_LESSON" to "Technical Lesson",
    "AI_OBSERVATION" to "AI Observation",
    "MILESTONE" to "Milestone",
)

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CreateIdeaDialog(
    vm: AppViewModel,
    onDismiss: () -> Unit,
    onDraftCreated: (Int) -> Unit,
) {
    var topic by remember { mutableStateOf("") }
    var notes by remember { mutableStateOf("") }
    var category by remember { mutableStateOf("BUILD_LOG") }
    var scheduledAt by remember { mutableStateOf<String?>(null) }
    var isSubmitting by remember { mutableStateOf(false) }

    AlertDialog(
        onDismissRequest = { if (!isSubmitting) onDismiss() },
        title = {
            Text("Create post from idea", style = MaterialTheme.typography.titleLarge)
        },
        text = {
            Column(
                Modifier
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                OutlinedTextField(
                    value = topic,
                    onValueChange = { topic = it },
                    label = { Text("Topic / Title *") },
                    placeholder = { Text("e.g. Shipped offline queue with idempotency") },
                    enabled = !isSubmitting,
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                )

                OutlinedTextField(
                    value = notes,
                    onValueChange = { notes = it },
                    label = { Text("Context & Notes (optional)") },
                    placeholder = { Text("Key lessons, code snippets, numbers, or bullet points...") },
                    enabled = !isSubmitting,
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 3,
                    maxLines = 6,
                )

                Column {
                    Text(
                        "Category",
                        style = MaterialTheme.typography.labelMedium,
                        modifier = Modifier.padding(bottom = 6.dp),
                    )
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        CATEGORIES.forEach { (catKey, catLabel) ->
                            FilterChip(
                                selected = category == catKey,
                                onClick = { category = catKey },
                                label = { Text(catLabel) },
                                enabled = !isSubmitting,
                            )
                        }
                    }
                }

                ScheduleTimeSelector(
                    selectedIso = scheduledAt,
                    onSelected = { scheduledAt = it },
                    label = "When should this post?",
                )
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    if (topic.isNotBlank() && !isSubmitting) {
                        isSubmitting = true
                        vm.createIdea(
                            topic = topic.trim(),
                            notes = notes.trim(),
                            category = category,
                            scheduledAt = scheduledAt,
                        ) { newDraftId ->
                            isSubmitting = false
                            onDismiss()
                            onDraftCreated(newDraftId)
                        }
                    }
                },
                enabled = topic.isNotBlank() && !isSubmitting,
            ) {
                if (isSubmitting) {
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.onPrimary,
                        )
                        Text("Writing post...")
                    }
                } else {
                    Text("Generate post")
                }
            }
        },
        dismissButton = {
            OutlinedButton(
                onClick = onDismiss,
                enabled = !isSubmitting,
            ) {
                Text("Cancel")
            }
        },
    )
}
