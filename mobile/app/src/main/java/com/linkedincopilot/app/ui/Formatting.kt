package com.linkedincopilot.app.ui

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.content.Context
import java.time.Instant
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit

/** Date formatting in the phone's own timezone. */
object Fmt {
    private val dayTime = DateTimeFormatter.ofPattern("EEE d MMM, h:mm a")
    private val timeOnly = DateTimeFormatter.ofPattern("h:mm a")
    private val dayOnly = DateTimeFormatter.ofPattern("EEE d MMM")

    private fun parse(iso: String?): Instant? =
        iso?.let { runCatching { Instant.parse(if (it.endsWith("Z")) it else "${it}Z") }.getOrNull() }
            ?: iso?.let { runCatching { Instant.parse(it) }.getOrNull() }

    fun parseZoned(iso: String?): ZonedDateTime? {
        val instant = parse(iso) ?: return null
        return instant.atZone(ZoneId.systemDefault())
    }

    fun toIso(zoned: ZonedDateTime): String {
        return DateTimeFormatter.ISO_INSTANT.format(zoned.toInstant())
    }

    fun todayAt(hour: Int, minute: Int = 0): ZonedDateTime {
        val now = ZonedDateTime.now()
        return now.withHour(hour).withMinute(minute).withSecond(0).withNano(0)
    }

    fun tomorrowAt(hour: Int, minute: Int = 0): ZonedDateTime {
        return todayAt(hour, minute).plusDays(1)
    }

    fun pickDateTime(
        context: Context,
        initialIso: String? = null,
        onPicked: (String) -> Unit,
    ) {
        val current = parseZoned(initialIso) ?: ZonedDateTime.now().plusHours(2)
        DatePickerDialog(
            context,
            { _, year, month, dayOfMonth ->
                TimePickerDialog(
                    context,
                    { _, hourOfDay, minute ->
                        val chosen = current
                            .withYear(year)
                            .withMonth(month + 1)
                            .withDayOfMonth(dayOfMonth)
                            .withHour(hourOfDay)
                            .withMinute(minute)
                            .withSecond(0)
                            .withNano(0)
                        onPicked(toIso(chosen))
                    },
                    current.hour,
                    current.minute,
                    false,
                ).show()
            },
            current.year,
            current.monthValue - 1,
            current.dayOfMonth,
        ).apply {
            datePicker.minDate = System.currentTimeMillis() - 1000
        }.show()
    }

    fun dateTime(iso: String?): String {
        val instant = parse(iso) ?: return "—"
        return dayTime.format(instant.atZone(ZoneId.systemDefault()))
    }

    fun day(iso: String?): String {
        val instant = parse(iso) ?: return "—"
        return dayOnly.format(instant.atZone(ZoneId.systemDefault()))
    }

    fun time(iso: String?): String {
        val instant = parse(iso) ?: return "—"
        return timeOnly.format(instant.atZone(ZoneId.systemDefault()))
    }

    /** "Tomorrow · 11:00 AM" style, which is what the dashboard wants. */
    fun relativeDay(iso: String?): String {
        val instant = parse(iso) ?: return "—"
        val zone = ZoneId.systemDefault()
        val target = instant.atZone(zone)
        val today = Instant.now().atZone(zone).toLocalDate()
        val days = ChronoUnit.DAYS.between(today, target.toLocalDate())
        val prefix = when (days) {
            0L -> "Today"
            1L -> "Tomorrow"
            in 2L..6L -> dayOnly.format(target)
            else -> dayOnly.format(target)
        }
        return "$prefix · ${timeOnly.format(target)}"
    }

    fun ago(iso: String?): String {
        val instant = parse(iso) ?: return "—"
        val minutes = ChronoUnit.MINUTES.between(instant, Instant.now())
        return when {
            minutes < 1 -> "just now"
            minutes < 60 -> "${minutes}m ago"
            minutes < 1440 -> "${minutes / 60}h ago"
            else -> "${minutes / 1440}d ago"
        }
    }
}
