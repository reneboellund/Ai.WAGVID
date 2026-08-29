package com.boellund.wagvid.capture.control

import com.boellund.wagvid.capture.network.RemoteCommand
import com.boellund.wagvid.capture.security.BackendCredential
import java.time.Instant
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CommandCoordinatorTest {
    private class FakeStore : CommandReceiptStore {
        val values = linkedMapOf<String, CommandReceipt>()
        override suspend fun find(commandId: String): CommandReceipt? = values[commandId]
        override suspend fun save(receipt: CommandReceipt) {
            val existing = values[receipt.commandId]
            check(existing == null || existing == receipt)
            values.putIfAbsent(receipt.commandId, receipt)
        }
    }

    private class FakeControl : LocalCaptureControl {
        override var state: LocalCaptureState = LocalCaptureState.READY
        var starts = 0
        var stops = 0
        var arms = 0
        var disarms = 0

        override suspend fun arm(context: Map<String, Any?>) {
            arms += 1
            state = LocalCaptureState.ARMED
        }

        override suspend fun disarm() {
            disarms += 1
            state = LocalCaptureState.READY
        }

        override suspend fun start(context: Map<String, Any?>) {
            starts += 1
            state = LocalCaptureState.RECORDING
        }

        override suspend fun stop() {
            stops += 1
            state = LocalCaptureState.FINALIZING
        }
    }

    private class FakeTransport(
        var commands: List<RemoteCommand>,
        private var failAcks: Int = 0,
    ) : RemoteCommandTransport {
        val acks = mutableListOf<Pair<String, CommandReceipt>>()

        override suspend fun poll(): List<RemoteCommand> = commands

        override suspend fun acknowledge(commandId: String, receipt: CommandReceipt) {
            if (failAcks > 0) {
                failAcks -= 1
                error("simulated ACK loss")
            }
            acks += commandId to receipt
        }
    }

    private val credentials = BackendCredential(
        baseUrl = "https://example.invalid/",
        deviceId = "device-id",
        deviceKey = "device-key",
        apiToken = "token",
        certificateFingerprint = null,
    )
    private val now = Instant.parse("2026-08-17T08:00:00Z")

    private fun command(
        id: String = "command-1",
        name: String = "start",
        expected: String = "ready",
        expiresAt: String = "2026-08-17T08:05:00Z",
    ) = RemoteCommand(
        command_id = id,
        command = name,
        expected_device_state = expected,
        payload = mapOf("capture_id" to "capture-1"),
        expires_at = expiresAt,
    )

    @Test
    fun duplicateCommandIdExecutesExactlyOnceAndReplaysOriginalAck() = runBlocking {
        val control = FakeControl()
        val store = FakeStore()
        val transport = FakeTransport(listOf(command(), command()))
        val coordinator = CommandCoordinator(credentials, control, store, { now }, transport)

        coordinator.pollOnce()

        assertEquals(1, control.starts)
        assertEquals(2, transport.acks.size)
        assertTrue(transport.acks.all { it.second.accepted })
        assertTrue(transport.acks.all { it.second.finalState == "recording" })
        assertEquals(1, store.values.size)
    }

    @Test
    fun lostAckDoesNotRepeatCameraActionOnNextPoll() = runBlocking {
        val control = FakeControl()
        val store = FakeStore()
        val transport = FakeTransport(listOf(command()), failAcks = 1)
        val coordinator = CommandCoordinator(credentials, control, store, { now }, transport)

        val first = runCatching { coordinator.pollOnce() }
        assertTrue(first.isFailure)
        assertEquals(1, control.starts)
        assertTrue(store.values.containsKey("command-1"))

        coordinator.pollOnce()
        assertEquals(1, control.starts)
        assertEquals(1, transport.acks.size)
        assertTrue(transport.acks.single().second.accepted)
    }

    @Test
    fun stateConflictIsDurableAndCannotTurnIntoLaterExecution() = runBlocking {
        val control = FakeControl()
        val store = FakeStore()
        val transport = FakeTransport(listOf(command(expected = "armed")))
        val coordinator = CommandCoordinator(credentials, control, store, { now }, transport)

        coordinator.pollOnce()
        assertEquals(0, control.starts)
        assertFalse(transport.acks.single().second.accepted)
        assertEquals("STATE_CONFLICT", transport.acks.single().second.rejectionCode)

        control.state = LocalCaptureState.ARMED
        coordinator.pollOnce()
        assertEquals(0, control.starts)
        assertEquals(2, transport.acks.size)
        assertEquals("ready", transport.acks.last().second.finalState)
        assertEquals("STATE_CONFLICT", transport.acks.last().second.rejectionCode)
    }

    @Test
    fun expiredCommandIsRecordedWithoutLocalMutation() = runBlocking {
        val control = FakeControl()
        val store = FakeStore()
        val transport = FakeTransport(
            listOf(command(expiresAt = "2026-08-17T07:59:59Z")),
        )
        val coordinator = CommandCoordinator(credentials, control, store, { now }, transport)

        coordinator.pollOnce()
        assertEquals(0, control.starts)
        assertEquals("COMMAND_EXPIRED", transport.acks.single().second.rejectionCode)
        assertEquals("ready", store.values["command-1"]?.finalState)
    }
}
