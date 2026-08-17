package com.boellund.wagvid.capture.network

import java.security.MessageDigest
import java.security.cert.X509Certificate
import java.util.Base64
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request

object TlsPin {
    private val pinPattern = Regex("^sha256/[A-Za-z0-9+/]{43}=$")

    fun requireValid(value: String): String {
        require(pinPattern.matches(value)) { "Certificate pin must be an OkHttp SHA-256 SPKI pin" }
        return value
    }

    fun fromCertificate(certificate: X509Certificate): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(certificate.publicKey.encoded)
        return "sha256/${Base64.getEncoder().encodeToString(digest)}"
    }
}

class CertificatePinProbe(
    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .retryOnConnectionFailure(false)
        .followRedirects(false)
        .followSslRedirects(false)
        .build(),
) {
    suspend fun probe(baseUrl: String): String? {
        val url = baseUrl.toHttpUrl()
        if (url.scheme != "https") return null
        return withContext(Dispatchers.IO) {
            val request = Request.Builder().url(url).head().build()
            client.newCall(request).execute().use { response ->
                val certificate = response.handshake?.peerCertificates?.firstOrNull() as? X509Certificate
                    ?: error("HTTPS pairing endpoint did not expose a peer certificate")
                TlsPin.fromCertificate(certificate)
            }
        }
    }
}
