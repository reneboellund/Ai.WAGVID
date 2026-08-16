package com.boellund.wagvid.capture.runtime

import android.content.Context
import android.provider.Settings
import com.boellund.wagvid.capture.network.ApiFactory
import com.boellund.wagvid.capture.network.CaptureContextResponse
import com.boellund.wagvid.capture.network.PairingRepository
import com.boellund.wagvid.capture.security.BackendCredential
import com.boellund.wagvid.capture.security.CredentialStore

class CaptureRuntimeRepository(context: Context) {
    private val applicationContext = context.applicationContext
    private val credentialStore = CredentialStore(applicationContext)

    fun credential(): BackendCredential? = credentialStore.load()

    suspend fun pair(
        baseUrl: String,
        pairingId: String,
        code: String,
        deviceName: String,
    ): Pair<BackendCredential, CaptureContextResponse> {
        val androidId = Settings.Secure.getString(
            applicationContext.contentResolver,
            Settings.Secure.ANDROID_ID,
        ) ?: "unknown"
        val credential = PairingRepository(credentialStore).claim(
            normalizeBaseUrl(baseUrl),
            pairingId.trim(),
            code.trim(),
            PairingRepository.installationId(androidId),
            deviceName.trim().ifBlank { "Ai.WAGVID Android" },
        )
        return credential to captureContext(credential)
    }

    suspend fun captureContext(
        credential: BackendCredential = credential()
            ?: error("Device is not paired"),
    ): CaptureContextResponse {
        val api = ApiFactory.create(credential.baseUrl)
        return api.captureContext(
            credential.deviceKey,
            "Bearer ${credential.apiToken}",
        )
    }

    private fun normalizeBaseUrl(value: String): String {
        val trimmed = value.trim()
        require(trimmed.startsWith("https://") || trimmed.startsWith("http://")) {
            "Backend URL must start with http:// or https://"
        }
        return if (trimmed.endsWith("/")) trimmed else "$trimmed/"
    }
}
