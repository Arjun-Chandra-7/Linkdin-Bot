package com.linkedincopilot.app.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.linkedincopilot.app.ui.Fmt
import java.time.ZonedDateTime

/**
 * Reusable control to choose or edit when a post publishes.
 *
 * Supports:
 * - Next available slot (auto)
 * - Quick presets: Today 5 PM, Tomorrow 9 AM, Tomorrow 5 PM
 * - Custom Date & Time via native picker
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ScheduleTimeSelector(
    selectedIso: String?,
    onSelected: (String?) -> Unit,
    modifier: Modifier = Modifier,
    label: String = "Scheduled publish time",
) {
    val context = LocalContext.current

    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(label, style = MaterialTheme.typography.labelMedium)
                if (selectedIso != null) {
                    IconButton(onClick = { onSelected(null) }) {
                        Icon(Icons.Filled.Clear, contentDescription = "Reset to auto slot")
                    }
                }
            }

            Text(
                if (selectedIso != null) Fmt.relativeDay(selectedIso)
                else "Next available slot (auto)",
                style = MaterialTheme.typography.titleMedium,
                color = if (selectedIso != null) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.padding(vertical = 4.dp),
            )

            FlowRow(
                modifier = Modifier.padding(top = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                FilterChip(
                    selected = selectedIso == null,
                    onClick = { onSelected(null) },
                    label = { Text("Auto slot") },
                )

                // Today 5:00 PM if still in future
                val today5pm = Fmt.todayAt(17, 0)
                if (today5pm.isAfter(ZonedDateTime.now())) {
                    val iso = Fmt.toIso(today5pm)
                    FilterChip(
                        selected = selectedIso == iso,
                        onClick = { onSelected(iso) },
                        label = { Text("Today 5 PM") },
                    )
                }

                // Tomorrow 9:00 AM
                val tom9am = Fmt.tomorrowAt(9, 0)
                val tom9Iso = Fmt.toIso(tom9am)
                FilterChip(
                    selected = selectedIso == tom9Iso,
                    onClick = { onSelected(tom9Iso) },
                    label = { Text("Tomorrow 9 AM") },
                )

                // Tomorrow 5:00 PM
                val tom5pm = Fmt.tomorrowAt(17, 0)
                val tom5Iso = Fmt.toIso(tom5pm)
                FilterChip(
                    selected = selectedIso == tom5Iso,
                    onClick = { onSelected(tom5Iso) },
                    label = { Text("Tomorrow 5 PM") },
                )
            }

            OutlinedButton(
                onClick = {
                    Fmt.pickDateTime(context, selectedIso) { picked ->
                        onSelected(picked)
                    }
                },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            ) {
                Icon(
                    Icons.Filled.CalendarMonth,
                    contentDescription = null,
                    modifier = Modifier.padding(end = 6.dp),
                )
                Text(if (selectedIso != null) "Change custom date & time" else "Pick custom date & time")
            }
        }
    }
}
