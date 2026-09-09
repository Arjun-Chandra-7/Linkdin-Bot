package com.linkedincopilot.app.data

import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.engine.android.Android
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.plugins.defaultRequest
import io.ktor.client.request.delete
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.parameter
import io.ktor.client.request.post
import io.ktor.client.request.put
import io.ktor.client.request.setBody
import io.ktor.client.statement.HttpResponse
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.serialization.kotlinx.json.json
import kotlinx.serialization.json.Json
import java.io.IOException

/**
 * Typed error the UI can render as a sentence plus an action, instead of a
 * status code.
 */
class ApiException(
    val code: String,
    override val message: String,
    val recovery: String? = null,
    val status: Int? = null,
) : Exception(message)

/** Thrown when the backend simply cannot be reached (laptop asleep, wrong Wi-Fi). */
class OfflineException(message: String = "Backend unreachable") : IOException(message)

class ApiClient(private val store: SecureStore) {

    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        encodeDefaults = true
    }

    private val client = HttpClient(Android) {
        expectSuccess = false
        install(ContentNegotiation) { json(json) }
        install(HttpTimeout) {
            requestTimeoutMillis = 60_000
            connectTimeoutMillis = 8_000
            socketTimeoutMillis = 60_000
        }
        defaultRequest { contentType(ContentType.Application.Json) }
    }

    companion object {
        private const val TAG = "ApiClient"

        fun normalizeBaseUrl(input: String): String {
            val trimmed = input.trim()
            val withScheme = if (!trimmed.startsWith("http://", ignoreCase = true) &&
                !trimmed.startsWith("https://", ignoreCase = true)
            ) {
                "http://$trimmed"
            } else {
                trimmed
            }
            return withScheme.trimEnd('/')
        }
    }

    private fun url(path: String): String {
        val base = store.baseUrl?.let { normalizeBaseUrl(it) }
            ?: throw ApiException("not_paired", "This device is not paired yet.", "Pair with your laptop in Settings.")
        return "$base$path"
    }

    private suspend inline fun <reified T> handle(response: HttpResponse): T {
        if (response.status.isSuccess()) return response.body()
        val body = runCatching { response.body<ApiErrorBody>() }.getOrNull()
        if (response.status == HttpStatusCode.Unauthorized && body?.code != "invalid_pairing_code") {
            throw ApiException(
                body?.code ?: "unauthorized",
                body?.message ?: "This device is no longer paired.",
                body?.recovery ?: "Pair again from Settings.",
                response.status.value,
            )
        }
        throw ApiException(
            body?.code ?: "http_${response.status.value}",
            body?.message ?: "The backend returned an error.",
            body?.recovery,
            response.status.value,
        )
    }

    private suspend inline fun <reified T> request(crossinline block: suspend () -> HttpResponse): T =
        try {
            handle(block())
        } catch (e: ApiException) {
            throw e
        } catch (e: IOException) {
            android.util.Log.e(TAG, "Request IO error: ${e.javaClass.name}: ${e.message}", e)
            val msg = if (e.message?.contains("Cleartext", ignoreCase = true) == true) {
                "Cleartext HTTP traffic blocked by network security policy."
            } else {
                "Could not reach the backend."
            }
            throw OfflineException(msg)
        } catch (e: Exception) {
            // Ktor wraps connection failures in engine-specific types.
            if (e is kotlinx.coroutines.CancellationException) throw e
            android.util.Log.e(TAG, "Request generic error: ${e.javaClass.name}: ${e.message}", e)
            throw OfflineException("Could not reach the backend.")
        }

    // ---- Pairing -------------------------------------------------------
    suspend fun pair(baseUrl: String, code: String, deviceName: String): PairResponse {
        val clean = normalizeBaseUrl(baseUrl)
        android.util.Log.d(TAG, "Attempting pair to $clean/api/v1/auth/pair")
        val response = try {
            client.post("$clean/api/v1/auth/pair") {
                setBody(PairRequest(code = code.trim().uppercase(), deviceName = deviceName.trim()))
            }
        } catch (e: Exception) {
            if (e is kotlinx.coroutines.CancellationException) throw e
            android.util.Log.e(TAG, "Pair request failed to $clean: ${e.javaClass.name}: ${e.message}", e)
            val msg = if (e.message?.contains("Cleartext", ignoreCase = true) == true) {
                "Cleartext HTTP traffic to $clean not permitted by network security policy."
            } else {
                "Could not reach $clean. Check the address and that the backend is running."
            }
            throw OfflineException(msg)
        }
        return handle(response)
    }

    suspend fun health(baseUrl: String): Boolean = runCatching {
        client.get("${baseUrl.trimEnd('/')}/health").status.isSuccess()
    }.getOrDefault(false)

    // ---- Authenticated calls -------------------------------------------
    private fun io.ktor.client.request.HttpRequestBuilder.auth() {
        store.token?.let { header("Authorization", "Bearer $it") }
    }

    suspend fun me(): DeviceInfo = request { client.get(url("/api/v1/auth/me")) { auth() } }

    suspend fun home(): HomeSummary = request { client.get(url("/api/v1/system/home")) { auth() } }

    suspend fun systemStatus(): SystemStatus =
        request { client.get(url("/api/v1/system/status")) { auth() } }

    suspend fun drafts(statuses: List<String>? = null): DraftListResponse = request {
        client.get(url("/api/v1/drafts")) {
            auth()
            statuses?.forEach { parameter("status", it) }
        }
    }

    suspend fun draft(id: Int): DraftDetail = request { client.get(url("/api/v1/drafts/$id")) { auth() } }

    suspend fun submitApproval(body: ApprovalRequest): ApprovalResponse = request {
        client.post(url("/api/v1/approvals")) { auth(); setBody(body) }
    }

    suspend fun saveEdit(draftId: Int, body: SaveEditRequest): DraftVersion = request {
        client.put(url("/api/v1/drafts/$draftId/content")) { auth(); setBody(body) }
    }

    suspend fun rewrite(draftId: Int, body: RewriteOperation): DraftDetail = request {
        client.post(url("/api/v1/drafts/$draftId/rewrite")) { auth(); setBody(body) }
    }

    suspend fun selectVersion(draftId: Int, versionId: Int): DraftDetail = request {
        client.post(url("/api/v1/drafts/$draftId/versions/$versionId/select")) { auth() }
    }

    suspend fun createFromIdea(body: ManualIdeaRequest): DraftDetail = request {
        client.post(url("/api/v1/drafts/from-idea")) { auth(); setBody(body) }
    }

    suspend fun schedule(): List<ScheduledPost> =
        request { client.get(url("/api/v1/schedule")) { auth() } }

    suspend fun calendar(): List<CalendarEntry> =
        request { client.get(url("/api/v1/schedule/calendar")) { auth() } }

    suspend fun confirmPublished(slotId: Int, externalUrl: String? = null): ScheduledPost = request {
        client.post(url("/api/v1/schedule/$slotId/confirm-published")) {
            auth()
            externalUrl?.let { parameter("external_url", it) }
        }
    }

    suspend fun reschedule(slotId: Int, scheduledAt: String): ScheduledPost = request {
        client.post(url("/api/v1/schedule/$slotId/reschedule")) {
            auth()
            parameter("scheduled_at", scheduledAt)
        }
    }

    suspend fun cancelSchedule(slotId: Int): ScheduledPost =
        request { client.delete(url("/api/v1/schedule/$slotId")) { auth() } }

    suspend fun connections(status: String? = null): List<Connection> = request {
        client.get(url("/api/v1/network")) { auth(); status?.let { parameter("status", it) } }
    }

    suspend fun setConnectionStatus(id: Int, status: String): Connection = request {
        client.post(url("/api/v1/network/$id/status")) {
            auth(); setBody(ConnectionActionRequest(status))
        }
    }

    suspend fun analytics(): AnalyticsOverview =
        request { client.get(url("/api/v1/analytics/overview")) { auth() } }

    suspend fun recordMetrics(postId: Int, body: MetricsInput): PostMetrics = request {
        client.post(url("/api/v1/analytics/posts/$postId/metrics")) { auth(); setBody(body) }
    }

    suspend fun pendingNotifications(): List<AppNotification> =
        request { client.get(url("/api/v1/notifications/pending")) { auth() } }

    suspend fun settings(): SettingsPayload =
        request { client.get(url("/api/v1/settings")) { auth() } }

    suspend fun updateSettings(values: SettingsPayload): SettingsPayload = request {
        client.put(url("/api/v1/settings")) { auth(); setBody(values) }
    }

    suspend fun runJob(type: String): Unit = request {
        client.post(url("/api/v1/system/run/$type")) { auth() }
    }
}

private fun HttpStatusCode.isSuccess(): Boolean = value in 200..299
