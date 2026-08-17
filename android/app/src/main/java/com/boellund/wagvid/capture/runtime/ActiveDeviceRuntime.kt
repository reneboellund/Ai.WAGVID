package com.boellund.wagvid.capture.runtime

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import com.boellund.wagvid.capture.BuildConfig
import com.boellund.wagvid.capture.WagvidApplication
import com.boellund.wagvid.capture.control.CommandCoordinator
import com.boellund.wagvid.capture.control.LocalCaptureControl
import com.boellund.wagvid.capture.network.ApiFactory
import com.boellund.wagvid.capture.network.HeartbeatRequest
import com.boellund.wagvid.capture.security.BackendCredential
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive

class ActiveDeviceRuntime(
    context: Context,
    private val credential: BackendCredential,
    control: LocalCaptureControl,
    private val activeCaptureId: () -> String?,
) {
    private val applicationContext = context.applicationContext
    private val api = ApiFactory.create(credential.baseUrl)
    private val bearer = "Bearer ${credential.apiToken}"
    private val coordinator = CommandCoordinator(credential, control)
    private val controlState = control
    private val dao = (applicationContext as WagvidApplication).database.captures()
    private val batteryManager = applicationContext.getSystemService(BatteryManager::class.java)
    private val connectivityManager =
        applicationContext.getSystemService(ConnectivityManager::class.java)

    suspend fun runWhileActive(
        onConnected: () -> Unit,
        onConnectionError: (String) -> Unit,
    ) {
        var lastHeartbeatAt = 0L
        while (currentCoroutineContext().isActive) {
            var connected = false
            var lastError: String? = null

            try {
                coordinator.pollOnce()
                connected = true
            } catch (error: Exception) {
                lastError = error.message ?: error.javaClass.simpleName
            }

            val now = System.currentTimeMillis()
            if (now - lastHeartbeatAt >= HEARTBEAT_INTERVAL_MS) {
                try {
                    sendHeartbeat()
                    lastHeartbeatAt = now
                    connected = true
                } catch (error: Exception) {
                    lastError = error.message ?: error.javaClass.simpleName
                }
            }

            if (connected) onConnected() else onConnectionError(lastError ?: "Backend unavailable")
            delay(POLL_INTERVAL_MS)
        }
    }

    private suspend fun sendHeartbeat() {
        val response = api.heartbeat(
            credential.deviceKey,
            bearer,
            HeartbeatRequest(
                state = controlState.state.wire,
                battery_percent = batteryPercent(),
                free_storage_bytes = applicationContext.filesDir.usableSpace,
                queued_uploads = dao.queuedCountSnapshot(),
                network_type = networkType(),
                app_version = BuildConfig.VERSION_NAME,
                active_capture_id = activeCaptureId(),
            ),
        )
        check(response.isSuccessful) { "Heartbeat failed (${response.code()})" }
    }

    private fun batteryPercent(): Int? =
        batteryManager?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
            ?.takeIf { it in 0..100 }

    private fun networkType(): String {
        val network = connectivityManager?.activeNetwork ?: return "offline"
        val capabilities = connectivityManager.getNetworkCapabilities(network) ?: return "unknown"
        return when {
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN) -> "vpn"
            else -> "other"
        }
    }

    private companion object {
        const val POLL_INTERVAL_MS = 2_000L
        const val HEARTBEAT_INTERVAL_MS = 15_000L
    }
}
