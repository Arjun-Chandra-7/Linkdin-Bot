package com.linkedincopilot.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.linkedincopilot.app.ui.AppState
import com.linkedincopilot.app.ui.AppViewModel
import com.linkedincopilot.app.ui.Fmt
import com.linkedincopilot.app.ui.components.KeyValueRow
import com.linkedincopilot.app.ui.components.SectionHeader
import com.linkedincopilot.app.ui.components.StatusPill

/** Settings doubles as the system-status view, so problems are diagnosable
 *  from the phone rather than from terminal logs. */
@Composable
fun SettingsScreen(vm: AppViewModel, state: AppState, onUnpaired: () -> Unit) {
    LaunchedEffect(Unit) { vm.loadStatus() }
    val status = state.status

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
    ) {
        Text(
            "Settings",
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(top = 20.dp),
        )

        SectionHeader("Connection")
        KeyValueRow("Backend", vm.baseUrl ?: "not set")
        KeyValueRow("Server", vm.serverName ?: "—")
        KeyValueRow(
            "Token storage",
            if (vm.hardwareBackedKeystore) "Encrypted (Keystore)" else "Encrypted (software)",
        )
        if (state.pendingSync > 0) {
            KeyValueRow("Waiting to sync", "${state.pendingSync} decision(s)")
        }

        SectionHeader("System status")
        if (status == null) {
            Text(
                "Could not read backend status.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            listOf(
                "Backend" to status.backend,
                "Database" to status.database,
                "Scheduler" to status.scheduler,
                "AI provider" to status.aiProvider,
                "LinkedIn" to status.linkedin,
            ).forEach { (label, component) ->
                Card(
                    Modifier.fillMaxWidth().padding(vertical = 3.dp),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant
                    ),
                ) {
                    Column(Modifier.padding(12.dp)) {
                        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text(label, style = MaterialTheme.typography.titleMedium)
                            StatusPill(
                                component.status.replace('_', ' '),
                                when (component.status) {
                                    "ok" -> MaterialTheme.colorScheme.primary
                                    "not_configured", "disabled" -> MaterialTheme.colorScheme.onSurfaceVariant
                                    else -> MaterialTheme.colorScheme.error
                                },
                            )
                            component.detail?.let {
                                Text(
                                    it,
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
            }
            KeyValueRow("Timezone", status.timezone)
            KeyValueRow("Failed jobs", status.failedJobs.toString())
            status.nextScheduledJobAt?.let { KeyValueRow("Next job", Fmt.dateTime(it)) }
            status.lastDiscoveryAt?.let { KeyValueRow("Last discovery", Fmt.ago(it)) }
        }

        SectionHeader("Safety")
        Text(
            "This app never sends connection requests, messages, likes or comments on your "
                + "behalf, and it never publishes anything you have not approved. In manual "
                + "publishing mode it prepares the post and reminds you; you post it yourself.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        SectionHeader("Device")
        OutlinedButton(
            onClick = { vm.unpair(); onUnpaired() },
            modifier = Modifier.fillMaxWidth().padding(bottom = 32.dp),
        ) { Text("Unpair this device") }
    }
}
