package com.boellund.wagvid.capture.network

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import com.boellund.wagvid.capture.BuildConfig
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

data class DiscoveredBackend(val name: String, val httpsUrl: String)

class BackendDiscovery(context: Context) {
    private val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager

    fun discover(): Flow<DiscoveredBackend> = callbackFlow {
        val listener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(type: String) = Unit
            override fun onDiscoveryStopped(type: String) = Unit
            override fun onStartDiscoveryFailed(type: String, code: Int) { close() }
            override fun onStopDiscoveryFailed(type: String, code: Int) { close() }
            override fun onServiceLost(service: NsdServiceInfo) = Unit
            override fun onServiceFound(service: NsdServiceInfo) {
                nsd.resolveService(service, object : NsdManager.ResolveListener {
                    override fun onResolveFailed(info: NsdServiceInfo, code: Int) = Unit
                    override fun onServiceResolved(info: NsdServiceInfo) {
                        val address = info.host.hostAddress ?: return
                        val host = if (':' in address && !address.startsWith("[")) "[$address]" else address
                        trySend(
                            DiscoveredBackend(
                                info.serviceName,
                                "https://$host:${info.port}/",
                            ),
                        )
                    }
                })
            }
        }
        nsd.discoverServices("_wagvid._tcp.", NsdManager.PROTOCOL_DNS_SD, listener)
        awaitClose { runCatching { nsd.stopServiceDiscovery(listener) } }
    }

    fun validateManualUrl(value: String): String {
        val normalized = value.trim().let { if (it.endsWith('/')) it else "$it/" }
        require(normalized.startsWith("https://") || (BuildConfig.DEBUG && normalized.startsWith("http://"))) {
            if (BuildConfig.DEBUG) {
                "Backend URL must use http:// or https://"
            } else {
                "Backend URL must use HTTPS"
            }
        }
        return normalized
    }
}
