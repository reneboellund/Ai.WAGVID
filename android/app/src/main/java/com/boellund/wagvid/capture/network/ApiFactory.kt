package com.boellund.wagvid.capture.network

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import okhttp3.CertificatePinner
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import java.util.concurrent.TimeUnit

object ApiFactory {
    internal fun client(baseUrl: String, certificatePin: String? = null): OkHttpClient {
        val url = baseUrl.toHttpUrl()
        val builder = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
        if (certificatePin != null) {
            require(url.scheme == "https") { "Certificate pinning requires HTTPS" }
            val pin = TlsPin.requireValid(certificatePin)
            builder.certificatePinner(
                CertificatePinner.Builder()
                    .add(url.host, pin)
                    .build(),
            )
        }
        return builder.build()
    }

    fun create(baseUrl: String, certificatePin: String? = null): WagvidApi {
        val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client(baseUrl, certificatePin))
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()
            .create(WagvidApi::class.java)
    }
}
