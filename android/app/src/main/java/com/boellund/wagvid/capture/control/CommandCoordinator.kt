package com.boellund.wagvid.capture.control

import com.boellund.wagvid.capture.network.ApiFactory
import com.boellund.wagvid.capture.network.CommandAck
import com.boellund.wagvid.capture.network.RemoteCommand
import com.boellund.wagvid.capture.security.BackendCredential
import java.time.Instant

enum class LocalCaptureState(val wire: String) {
    READY("ready"),
    ARMED("armed"),
    RECORDING("recording"),
    FINALIZING("finalizing"),
}

interface LocalCaptureControl {
    val state: LocalCaptureState
    suspend fun arm(context: Map<String, Any?>)
    suspend fun disarm()
    suspend fun start(context: Map<String, Any?>)
    suspend fun stop()
}

interface RemoteCommandTransport {
    suspend fun poll(): List<RemoteCommand>
    suspend fun acknowledge(commandId: String, receipt: CommandReceipt)
}

class ApiRemoteCommandTransport(private val credentials: BackendCredential) : RemoteCommandTransport {
    private val api = ApiFactory.create(credentials.baseUrl)
    private val bearer = "Bearer ${credentials.apiToken}"

    override suspend fun poll(): List<RemoteCommand> =
        api.commands(credentials.deviceKey, bearer).commands

    override suspend fun acknowledge(commandId: String, receipt: CommandReceipt) {
        api.acknowledge(
            credentials.deviceKey,
            bearer,
            commandId,
            CommandAck(receipt.accepted, receipt.finalState, receipt.rejectionCode),
        )
    }
}

class CommandCoordinator(
    credentials: BackendCredential,
    private val control: LocalCaptureControl,
    private val receipts: CommandReceiptStore,
    private val now: () -> Instant = Instant::now,
    private val transport: RemoteCommandTransport = ApiRemoteCommandTransport(credentials),
) {
    suspend fun pollOnce() {
        transport.poll().forEach { execute(it) }
    }

    private suspend fun execute(command: RemoteCommand) {
        receipts.find(command.command_id)?.let { existing ->
            // ACK the original outcome. Never re-execute merely because the previous ACK was lost.
            transport.acknowledge(command.command_id, existing)
            return
        }

        val receipt = when {
            isExpired(command) -> rejected(command, "COMMAND_EXPIRED")
            command.expected_device_state != control.state.wire -> rejected(command, "STATE_CONFLICT")
            else -> executeNew(command)
        }
        // Persist the local outcome before the network ACK. If ACK fails, the next delivery sees
        // this receipt and re-ACKs without touching camera state again.
        receipts.save(receipt)
        transport.acknowledge(command.command_id, receipt)
    }

    private suspend fun executeNew(command: RemoteCommand): CommandReceipt {
        var accepted = false
        var code = ""
        try {
            when (command.command) {
                "arm" -> control.arm(command.payload)
                "disarm" -> control.disarm()
                "start" -> control.start(command.payload)
                "stop" -> control.stop()
                else -> throw UnsupportedOperationException("Unsupported command")
            }
            accepted = true
        } catch (error: UnsupportedOperationException) {
            code = "UNSUPPORTED_COMMAND"
        } catch (error: SecurityException) {
            code = "CAMERA_PERMISSION_DENIED"
        } catch (error: Exception) {
            code = "LOCAL_CAPTURE_ERROR"
        }
        return CommandReceipt(
            commandId = command.command_id,
            accepted = accepted,
            finalState = control.state.wire,
            rejectionCode = code,
            executedAtEpochMs = now().toEpochMilli(),
        )
    }

    private fun rejected(command: RemoteCommand, code: String) = CommandReceipt(
        commandId = command.command_id,
        accepted = false,
        finalState = control.state.wire,
        rejectionCode = code,
        executedAtEpochMs = now().toEpochMilli(),
    )

    private fun isExpired(command: RemoteCommand): Boolean {
        val expiry = runCatching { Instant.parse(command.expires_at) }.getOrNull() ?: return true
        return !expiry.isAfter(now())
    }
}
