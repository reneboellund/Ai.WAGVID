package com.boellund.wagvid.capture.control

import com.boellund.wagvid.capture.network.ApiFactory
import com.boellund.wagvid.capture.network.CommandAck
import com.boellund.wagvid.capture.network.RemoteCommand
import com.boellund.wagvid.capture.security.BackendCredential

enum class LocalCaptureState(val wire: String) { READY("ready"), ARMED("armed"), RECORDING("recording"), FINALIZING("finalizing") }

interface LocalCaptureControl {
    val state: LocalCaptureState
    suspend fun arm(context: Map<String, Any?>)
    suspend fun disarm()
    suspend fun start(context: Map<String, Any?>)
    suspend fun stop()
}

class CommandCoordinator(
    private val credentials: BackendCredential,
    private val control: LocalCaptureControl,
) {
    private val api = ApiFactory.create(credentials.baseUrl)
    private val bearer = "Bearer ${credentials.apiToken}"

    suspend fun pollOnce() {
        api.commands(credentials.deviceKey, bearer).commands.forEach { execute(it) }
    }

    private suspend fun execute(command: RemoteCommand) {
        if (command.expected_device_state != control.state.wire) {
            acknowledge(command, false, "STATE_CONFLICT")
            return
        }
        try {
            when (command.command) {
                "arm" -> control.arm(command.payload)
                "disarm" -> control.disarm()
                "start" -> control.start(command.payload)
                "stop" -> control.stop()
                else -> error("Unsupported command")
            }
            acknowledge(command, true, "")
        } catch (error: SecurityException) {
            acknowledge(command, false, "CAMERA_PERMISSION_DENIED")
        } catch (error: Exception) {
            acknowledge(command, false, "LOCAL_CAPTURE_ERROR")
        }
    }

    private suspend fun acknowledge(command: RemoteCommand, accepted: Boolean, code: String) {
        api.acknowledge(
            credentials.deviceKey,
            bearer,
            command.command_id,
            CommandAck(accepted, control.state.wire, code),
        )
    }
}
