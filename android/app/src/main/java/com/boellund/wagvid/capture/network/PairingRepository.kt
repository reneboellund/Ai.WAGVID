package com.boellund.wagvid.capture.network

import com.boellund.wagvid.capture.BuildConfig
import com.boellund.wagvid.capture.security.BackendCredential
import com.boellund.wagvid.capture.security.CredentialStore

class PairingRepository(
    private val store: CredentialStore,
    private val pinProbe: CertificatePinProbe = CertificatePinProbe(),
) {
    suspend fun claim(
        baseUrl: String,
        pairingId: String,
        code: String,
        installationId: String,
        deviceName: String,
    ): BackendCredential {
        require(code.matches(Regex("^[0-9]{6}$"))) { "Pairing code must contain six digits" }
        val certificatePin = pinProbe.probe(baseUrl)
        val api = ApiFactory.create(baseUrl, certificatePin)
        val response = api.claimPairing(
            pairingId,
            PairingClaimRequest(code, installationId, deviceName, BuildConfig.VERSION_NAME),
        )
        val credential = BackendCredential(
            baseUrl,
            response.device_id,
            response.device_key,
            response.api_token,
            certificatePin,
        )
        store.save(credential)
        return credential
    }

    companion object {
        fun installationId(androidId: String): String = "android-$androidId"
    }
}
