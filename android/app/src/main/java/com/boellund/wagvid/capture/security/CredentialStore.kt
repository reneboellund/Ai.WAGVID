package com.boellund.wagvid.capture.security

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

data class BackendCredential(
    val baseUrl: String,
    val deviceId: String,
    val deviceKey: String,
    val apiToken: String,
    val certificateFingerprint: String?,
)

class CredentialStore(context: Context) {
    private val masterKey = MasterKey.Builder(context)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()
    private val preferences = EncryptedSharedPreferences.create(
        context,
        "wagvid-secure",
        masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun save(value: BackendCredential) {
        preferences.edit()
            .putString("base_url", value.baseUrl)
            .putString("device_id", value.deviceId)
            .putString("device_key", value.deviceKey)
            .putString("api_token", value.apiToken)
            .putString("certificate_fingerprint", value.certificateFingerprint)
            .apply()
    }

    fun load(): BackendCredential? {
        val baseUrl = preferences.getString("base_url", null) ?: return null
        return BackendCredential(
            baseUrl,
            preferences.getString("device_id", null) ?: return null,
            preferences.getString("device_key", null) ?: return null,
            preferences.getString("api_token", null) ?: return null,
            preferences.getString("certificate_fingerprint", null),
        )
    }

    fun clear() {
        preferences.edit().clear().apply()
    }
}
