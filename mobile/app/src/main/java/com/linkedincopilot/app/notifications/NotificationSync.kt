package com.linkedincopilot.app.notifications

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.linkedincopilot.app.R
import com.linkedincopilot.app.data.Repository
import com.linkedincopilot.app.data.SecureStore
import java.util.concurrent.TimeUnit

/**
 * Notification delivery.
 *
 * There is no cloud push service here by design: the backend runs on the
 * user's laptop on their local network. This worker polls while the phone can
 * reach it, raises a *local* notification, and flushes any decisions made
 * offline. The trade-off is that notifications arrive on a poll interval
 * rather than instantly - documented rather than papered over.
 */
class NotificationWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val store = SecureStore(applicationContext)
        if (!store.isPaired) return Result.success()

        val repo = Repository(applicationContext, store)
        return try {
            // Flush anything approved while offline before pulling new work.
            repo.syncPending()

            val pending = repo.api.pendingNotifications()
            pending.forEach { notification ->
                show(
                    applicationContext,
                    id = notification.id,
                    title = notification.title,
                    body = notification.body,
                    highPriority = notification.priority == "HIGH",
                )
            }
            Result.success()
        } catch (e: Exception) {
            // Backend asleep or off-network is the normal case, not an error.
            Result.success()
        }
    }

    companion object {
        const val CHANNEL_ID = "copilot_updates"
        private const val WORK_NAME = "copilot_notification_sync"

        fun ensureChannel(context: Context) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val channel = NotificationChannel(
                    CHANNEL_ID,
                    "Copilot updates",
                    NotificationManager.IMPORTANCE_DEFAULT,
                ).apply {
                    description = "Drafts ready for review, publishing reminders and failures."
                }
                context.getSystemService(NotificationManager::class.java)
                    ?.createNotificationChannel(channel)
            }
        }

        fun show(
            context: Context,
            id: Int,
            title: String,
            body: String,
            highPriority: Boolean,
        ) {
            ensureChannel(context)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
            ) return

            val notification = NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_launcher_foreground)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(NotificationCompat.BigTextStyle().bigText(body))
                .setPriority(
                    if (highPriority) NotificationCompat.PRIORITY_HIGH
                    else NotificationCompat.PRIORITY_DEFAULT
                )
                .setAutoCancel(true)
                .build()

            runCatching {
                NotificationManagerCompat.from(context).notify(id, notification)
            }
        }

        /**
         * 15 minutes is WorkManager's minimum periodic interval. The app also
         * syncs whenever it is opened, so this is a backstop rather than the
         * main path.
         */
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<NotificationWorker>(15, TimeUnit.MINUTES)
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build()
                )
                .build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                request,
            )
        }

        /**
         * Fire an immediate sync when network is connected.
         * Enqueued as soon as an offline action is taken so it syncs automatically
         * the moment the connection is re-established, even if app is closed.
         */
        fun triggerImmediateSync(context: Context) {
            val request = OneTimeWorkRequestBuilder<NotificationWorker>()
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build()
                )
                .build()
            WorkManager.getInstance(context).enqueue(request)
        }
    }
}
