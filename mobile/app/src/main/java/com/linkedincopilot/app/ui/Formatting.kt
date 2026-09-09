package com.linkedincopilot.app.ui

import java.time.Instant
import java.time.ZoneId
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
