package com.boellund.wagvid.capture.control

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MotionGateTest {
    @Test
    fun startsOnlyAfterConfiguredConsecutiveMotionFrames() {
        val gate = MotionGate(
            MotionGateConfig(startThreshold = 0.5, stopThreshold = 0.1, startFrames = 3, quietFrames = 2),
        )
        assertEquals(MotionDecision.NONE, gate.observe(0.7, true))
        assertEquals(MotionDecision.NONE, gate.observe(0.2, true))
        assertEquals(MotionDecision.NONE, gate.observe(0.7, true))
        assertEquals(MotionDecision.NONE, gate.observe(0.7, true))
        assertEquals(MotionDecision.START, gate.observe(0.7, true))
        assertTrue(gate.recording)
    }

    @Test
    fun exerciseEndRequiresConfiguredQuietPeriod() {
        val gate = MotionGate(
            MotionGateConfig(startThreshold = 0.5, stopThreshold = 0.1, startFrames = 1, quietFrames = 3),
        )
        assertEquals(MotionDecision.START, gate.observe(0.8, true))
        assertEquals(MotionDecision.NONE, gate.observe(0.05, true))
        assertEquals(MotionDecision.NONE, gate.observe(0.05, true))
        assertEquals(MotionDecision.EXERCISE_ENDED, gate.observe(0.05, true))
        assertFalse(gate.recording)
    }

    @Test
    fun manualStopSuppressesAutomaticRestartUntilExplicitRearm() {
        val gate = MotionGate(
            MotionGateConfig(startThreshold = 0.5, stopThreshold = 0.1, startFrames = 1, quietFrames = 2),
        )
        assertEquals(MotionDecision.START, gate.observe(0.9, true))
        gate.manualStop()
        assertTrue(gate.automaticStartSuppressed)
        repeat(20) {
            assertEquals(MotionDecision.NONE, gate.observe(0.9, true))
        }
        assertFalse(gate.recording)

        gate.rearm()
        assertFalse(gate.automaticStartSuppressed)
        assertEquals(MotionDecision.START, gate.observe(0.9, true))
    }

    @Test
    fun disarmAlsoSuppressesMotionUntilRearm() {
        val gate = MotionGate(MotionGateConfig(startFrames = 1, quietFrames = 1))
        gate.disarm()
        assertEquals(MotionDecision.NONE, gate.observe(1.0, true))
        gate.rearm()
        assertEquals(MotionDecision.START, gate.observe(1.0, true))
    }

    @Test(expected = IllegalArgumentException::class)
    fun invalidHysteresisIsRejected() {
        MotionGateConfig(startThreshold = 0.2, stopThreshold = 0.3)
    }
}
