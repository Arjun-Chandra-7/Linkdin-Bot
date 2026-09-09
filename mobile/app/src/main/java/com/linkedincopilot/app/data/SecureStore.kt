package com.linkedincopilot.app.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Device token storage.
 *
 * The bearer token is the only credential in the system, so it lives in
 * EncryptedSharedPreferences (AES-256, key held in the Android Keystore)
 * rather than plain prefs. It is written once at pairing and never logged.
 */
class SecureStore(context: Context) {

    /** False when the Keystore was unavailable and we fell back to plain prefs. */
    var isHardwareBacked: Boolean = true
        private set

    private val prefs: SharedPreferences = runCatching {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            "copilot_secure",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        ) as SharedPreferences
    }.getOrElse {
        // Keystore can be unavailable on some devices/emulators. Falling back
        // keeps the app usable; the token is still device-local and Settings
        // tells the user it is not hardware-backed.
        isHardwareBacked = false
        context.getSharedPreferences("copilot_fallback", Context.MODE_PRIVATE)
    }

    var token: String?
        get() = prefs.getString(KEY_TOKEN, null)
        set(value) = prefs.edit().apply { if (value == null) remove(KEY_TOKEN) else putString(KEY_TOKEN, value) }.apply()

    var baseUrl: String?
        get() = prefs.getString(KEY_BASE_URL, null)
        set(value) = prefs.edit().apply { if (value == null) remove(KEY_BASE_URL) else putString(KEY_BASE_URL, value) }.apply()

    var deviceId: String?
        get() = prefs.getString(KEY_DEVICE_ID, null)
        set(value) = prefs.edit().apply { if (value == null) remove(KEY_DEVICE_ID) else putString(KEY_DEVICE_ID, value) }.apply()

    var serverName: String?
        get() = prefs.getString(KEY_SERVER_NAME, null)
        set(value) = prefs.edit().putString(KEY_SERVER_NAME, value).apply()

    val isPaired: Boolean get() = !token.isNullOrBlank() && !baseUrl.isNullOrBlank()

    fun clear() {
        prefs.edit().clear().apply()
    }

    private companion object {
        const val KEY_TOKEN = "device_token"
        const val KEY_BASE_URL = "base_url"
        const val KEY_DEVICE_ID = "device_id"
        const val KEY_SERVER_NAME = "server_name"
    }
}
