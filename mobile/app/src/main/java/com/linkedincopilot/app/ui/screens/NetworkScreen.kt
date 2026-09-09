package com.linkedincopilot.app.ui.screens

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.linkedincopilot.app.ui.AppState
import com.linkedincopilot.app.ui.AppViewModel
import com.linkedincopilot.app.ui.components.EmptyState
import com.linkedincopilot.app.ui.components.SectionHeader

/**
 * Networking recommendations.
 *
 * "Open profile" hands off to LinkedIn and the user sends the invitation
 * themselves. The app has no way to connect on their behalf, and that is
 * stated on the screen rather than merely being true in the backend.
 */
@Composable
fun NetworkScreen(vm: AppViewModel, state: AppState) {
    val context = LocalContext.current
    LaunchedEffect(Unit) { vm.loadConnections() }

    if (state.connections.isEmpty() && !state.loading) {
        EmptyState(
            title = "No suggestions yet",
            body = "People worth connecting with will appear here, with a reason and a draft note. "
                + "You always send the invitation yourself.",
        )
        return
    }

    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Column {
                Text(
                    "People",
                    style = MaterialTheme.typography.headlineSmall,
                    modifier = Modifier.padding(top = 20.dp),
                )
                Text(
                    "You send every invitation yourself - the app never connects for you.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 4.dp, bottom = 4.dp),
                )
            }
        }
        items(state.connections, key = { it.id }) { person ->
            Card(
                Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant
                ),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Text(person.name, style = MaterialTheme.typography.titleMedium)
                    Text(
                        listOfNotNull(person.role, person.company).joinToString(" @ "),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )

                    SectionHeader("Why recommended")
                    Text(person.reason, style = MaterialTheme.typography.bodyMedium)

                    Text(
                        "Relevance ${(person.relevanceScore * 100).toInt()}%",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 8.dp),
                    )

                    person.suggestedNote?.takeIf { it.isNotBlank() }?.let { note ->
                        SectionHeader("Suggested note")
                        Text(note, style = MaterialTheme.typography.bodyMedium)
                    }

                    Row(
                        Modifier.fillMaxWidth().padding(top = 12.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Button(
                            onClick = {
                                vm.setConnectionStatus(person.id, "OPENED")
                                runCatching {
                                    context.startActivity(
                                        Intent(Intent.ACTION_VIEW, Uri.parse(person.profileUrl))
                                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                    )
                                }
                            },
                            modifier = Modifier.weight(1f),
                        ) { Text("Open profile") }

                        TextButton(
                            onClick = {
                                val clipboard =
                                    context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                                clipboard.setPrimaryClip(
                                    ClipData.newPlainText("note", person.suggestedNote.orEmpty())
                                )
                            },
                            modifier = Modifier.weight(1f),
                        ) { Text("Copy note") }
                    }
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        TextButton(
                            onClick = { vm.setConnectionStatus(person.id, "SKIPPED") },
                            modifier = Modifier.weight(1f),
                        ) { Text("Skip") }
                        TextButton(
                            onClick = { vm.setConnectionStatus(person.id, "MARKED_CONNECTED") },
                            modifier = Modifier.weight(1f),
                        ) { Text("I connected") }
                    }
                }
            }
        }
        item { Column(Modifier.padding(bottom = 24.dp)) {} }
    }
}
