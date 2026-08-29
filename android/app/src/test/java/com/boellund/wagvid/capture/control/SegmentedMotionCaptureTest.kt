package com.boellund.wagvid.capture.control

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SegmentedMotionCaptureTest {
    private fun segment(id: Int, start: Long, end: Long, bytes: Long = 10L) = LocalVideoSegment(
        segmentId = "segment-$id",
        localUri = "file:///segment-$id.mp4",
        startedAtEpochMs = start,
        endedAtEpochMs = end,
        sizeBytes = bytes,
        sha256 = "a".repeat(64),
    )

    @Test
    fun rollingBufferEvictsOldSegmentsWhenNoCapturePinsThem() {
        val buffer = SegmentRingBuffer(
            SegmentBufferConfig(retainMs = 2_000, maximumBytes = 1_000, maximumSegments = 10),
        )
        buffer.add(segment(1, 0, 1_000), 1_000)
        buffer.add(segment(2, 1_000, 2_000), 2_000)
        val result = buffer.add(segment(3, 2_000, 3_000), 3_000)
        assertEquals(listOf("segment-1"), result.evicted.map { it.segmentId })
        assertEquals(listOf("segment-2", "segment-3"), result.retained.map { it.segmentId })
    }

    @Test
    fun activeCapturePinsPreRollAndExerciseSegmentsUntilFinalization() {
        val config = MotionGateConfig(
            startThreshold = 0.5,
            stopThreshold = 0.1,
            startFrames = 1,
            quietFrames = 2,
            preRollMs = 2_000,
            postRollMs = 1_500,
        )
        val planner = SegmentedMotionCapturePlanner(
            MotionGate(config),
            SegmentRingBuffer(SegmentBufferConfig(retainMs = 3_000, maximumBytes = 30, maximumSegments = 3)),
            config,
            captureIdFactory = { "capture-1" },
        )
        planner.recordSegment(segment(1, 7_000, 8_000), 8_000)
        planner.recordSegment(segment(2, 8_000, 9_000), 9_000)
        planner.recordSegment(segment(3, 9_000, 10_000), 10_000)

        val started = planner.observe(10_000, 0.9, true) as MotionCaptureAction.Started
        assertEquals(8_000, started.window.requestedStartEpochMs)
        planner.recordSegment(segment(4, 10_000, 11_000), 11_000)
        planner.recordSegment(segment(5, 11_000, 12_000), 12_000)
        val pinned = planner.recordSegment(segment(6, 12_000, 13_000), 13_000)
        assertTrue(pinned.retained.any { it.segmentId == "segment-2" })
        assertTrue(pinned.retained.size > 3)

        assertEquals(MotionCaptureAction.None, planner.observe(12_500, 0.0, false))
        val postRoll = planner.observe(13_000, 0.0, false) as MotionCaptureAction.EnteredPostRoll
        assertEquals(14_500, postRoll.window.requestedEndEpochMs)
        planner.recordSegment(segment(7, 13_000, 14_000), 14_000)
        planner.recordSegment(segment(8, 14_000, 15_000), 15_000)

        // Motion during post-roll belongs to the current capture and must not trigger a new START.
        assertEquals(MotionCaptureAction.None, planner.observe(14_000, 1.0, true))
        val final = planner.tick(14_500) as MotionCaptureAction.Finalize
        assertTrue(final.plan.readyForAssembly)
        assertEquals(
            listOf("segment-2", "segment-3", "segment-4", "segment-5", "segment-6", "segment-7", "segment-8"),
            final.plan.segments.map { it.segmentId },
        )
        assertEquals(500, final.plan.trimEndMs)

        val cleanup = planner.finalizationComplete(15_000)
        assertEquals(MotionCapturePhase.ARMED, planner.phase)
        assertTrue(cleanup.evicted.isNotEmpty())
    }

    @Test
    fun manualStopFinalizesImmediatelyAndSuppressesRestartUntilRearm() {
        val config = MotionGateConfig(startFrames = 1, quietFrames = 2, preRollMs = 1_000, postRollMs = 2_000)
        val planner = SegmentedMotionCapturePlanner(
            MotionGate(config),
            SegmentRingBuffer(SegmentBufferConfig(retainMs = 5_000)),
            config,
            captureIdFactory = { "capture-stop" },
        )
        planner.recordSegment(segment(1, 9_000, 10_000), 10_000)
        planner.observe(10_000, 1.0, true)
        planner.recordSegment(segment(2, 10_000, 11_000), 11_000)

        val stop = planner.manualStop(10_500) as MotionCaptureAction.Finalize
        assertTrue(stop.plan.manualStop)
        assertEquals(10_500, stop.plan.requestedEndEpochMs)
        planner.finalizationComplete(11_000)
        assertEquals(MotionCapturePhase.DISARMED, planner.phase)
        assertEquals(MotionCaptureAction.None, planner.observe(12_000, 1.0, true))

        planner.rearm()
        assertTrue(planner.observe(13_000, 1.0, true) is MotionCaptureAction.Started)
    }

    @Test
    fun assemblyPlanFailsClosedWhenSegmentTimelineHasGap() {
        val config = MotionGateConfig(startFrames = 1, quietFrames = 1, preRollMs = 2_000, postRollMs = 0)
        val planner = SegmentedMotionCapturePlanner(
            MotionGate(config),
            SegmentRingBuffer(SegmentBufferConfig(retainMs = 10_000)),
            config,
            captureIdFactory = { "capture-gap" },
        )
        planner.recordSegment(segment(1, 8_000, 9_000), 9_000)
        planner.recordSegment(segment(2, 10_000, 11_000), 11_000)
        planner.observe(10_000, 1.0, true)
        val action = planner.observe(11_000, 0.0, false) as MotionCaptureAction.Finalize
        assertFalse(action.plan.readyForAssembly)
        assertTrue("segment-timeline-gap" in action.plan.blockers)
    }

    @Test
    fun emptyBufferDoesNotInventVideoForTriggeredCapture() {
        val config = MotionGateConfig(startFrames = 1, quietFrames = 1, preRollMs = 1_000, postRollMs = 0)
        val planner = SegmentedMotionCapturePlanner(
            MotionGate(config),
            SegmentRingBuffer(SegmentBufferConfig()),
            config,
            captureIdFactory = { "capture-empty" },
        )
        planner.observe(5_000, 1.0, true)
        val final = planner.observe(6_000, 0.0, false) as MotionCaptureAction.Finalize
        assertFalse(final.plan.readyForAssembly)
        assertEquals(listOf("no-video-segments-overlap-capture-window"), final.plan.blockers)
    }
}
