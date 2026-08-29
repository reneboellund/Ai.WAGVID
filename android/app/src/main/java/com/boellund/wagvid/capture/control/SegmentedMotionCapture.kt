package com.boellund.wagvid.capture.control

import java.util.UUID

/** Pure planning layer for motion-triggered segmented capture. */
data class LocalVideoSegment(
    val segmentId: String,
    val localUri: String,
    val startedAtEpochMs: Long,
    val endedAtEpochMs: Long,
    val sizeBytes: Long,
    val sha256: String,
) {
    init {
        require(segmentId.isNotBlank() && localUri.isNotBlank())
        require(startedAtEpochMs >= 0 && endedAtEpochMs > startedAtEpochMs)
        require(sizeBytes >= 0)
        require(sha256.matches(Regex("^[a-f0-9]{64}$")))
    }

    fun overlaps(startEpochMs: Long, endEpochMs: Long): Boolean =
        endedAtEpochMs > startEpochMs && startedAtEpochMs < endEpochMs
}

data class SegmentBufferConfig(
    val retainMs: Long = 5_000,
    val maximumBytes: Long = 256L * 1024L * 1024L,
    val maximumSegments: Int = 30,
) {
    init {
        require(retainMs >= 0 && maximumBytes > 0 && maximumSegments > 0)
    }
}

data class BufferMutation(
    val retained: List<LocalVideoSegment>,
    val evicted: List<LocalVideoSegment>,
)

class SegmentRingBuffer(private val config: SegmentBufferConfig) {
    private val segments = ArrayDeque<LocalVideoSegment>()
    private var retainedBytes = 0L

    fun snapshot(): List<LocalVideoSegment> = segments.toList()

    fun add(
        segment: LocalVideoSegment,
        nowEpochMs: Long,
        protectedFromEpochMs: Long? = null,
    ): BufferMutation {
        require(nowEpochMs >= segment.endedAtEpochMs)
        require(protectedFromEpochMs == null || protectedFromEpochMs >= 0)
        require(segments.none { it.segmentId == segment.segmentId })
        if (segments.isNotEmpty()) {
            require(segment.startedAtEpochMs >= segments.last().startedAtEpochMs) {
                "Segments must be inserted chronologically"
            }
        }
        segments.addLast(segment)
        retainedBytes += segment.sizeBytes
        return prune(nowEpochMs, protectedFromEpochMs)
    }

    fun prune(nowEpochMs: Long, protectedFromEpochMs: Long? = null): BufferMutation {
        require(nowEpochMs >= 0)
        val evicted = mutableListOf<LocalVideoSegment>()
        val earliestUseful = nowEpochMs - config.retainMs
        while (segments.isNotEmpty()) {
            val first = segments.first()
            if (protectedFromEpochMs != null && first.endedAtEpochMs > protectedFromEpochMs) break
            val shouldEvict =
                first.endedAtEpochMs <= earliestUseful ||
                    retainedBytes > config.maximumBytes ||
                    segments.size > config.maximumSegments
            if (!shouldEvict) break
            segments.removeFirst()
            retainedBytes -= first.sizeBytes
            evicted += first
        }
        return BufferMutation(segments.toList(), evicted)
    }

    fun overlapping(startEpochMs: Long, endEpochMs: Long): List<LocalVideoSegment> {
        require(endEpochMs > startEpochMs)
        return segments.filter { it.overlaps(startEpochMs, endEpochMs) }
    }
}

enum class MotionCapturePhase { ARMED, CAPTURING, POST_ROLL, FINALIZING, DISARMED }

data class MotionCaptureWindow(
    val captureId: String,
    val triggerAtEpochMs: Long,
    val requestedStartEpochMs: Long,
    val exerciseEndedAtEpochMs: Long? = null,
    val requestedEndEpochMs: Long? = null,
    val manualStop: Boolean = false,
)

data class SegmentAssemblyPlan(
    val captureId: String,
    val requestedStartEpochMs: Long,
    val requestedEndEpochMs: Long,
    val segments: List<LocalVideoSegment>,
    val trimStartMs: Long,
    val trimEndMs: Long,
    val manualStop: Boolean,
) {
    val blockers: List<String>
        get() = buildList {
            if (segments.isEmpty()) add("no-video-segments-overlap-capture-window")
            if (segments.zipWithNext().any { (left, right) -> left.endedAtEpochMs < right.startedAtEpochMs }) {
                add("segment-timeline-gap")
            }
        }
    val readyForAssembly: Boolean get() = blockers.isEmpty()
}

sealed interface MotionCaptureAction {
    data class Started(val window: MotionCaptureWindow) : MotionCaptureAction
    data class EnteredPostRoll(val window: MotionCaptureWindow) : MotionCaptureAction
    data class Finalize(val plan: SegmentAssemblyPlan) : MotionCaptureAction
    data object None : MotionCaptureAction
}

class SegmentedMotionCapturePlanner(
    private val motionGate: MotionGate,
    private val segmentBuffer: SegmentRingBuffer,
    private val config: MotionGateConfig,
    private val captureIdFactory: () -> String = { UUID.randomUUID().toString() },
) {
    var phase: MotionCapturePhase = MotionCapturePhase.ARMED
        private set
    var activeWindow: MotionCaptureWindow? = null
        private set

    val protectedFromEpochMs: Long? get() = activeWindow?.requestedStartEpochMs

    fun recordSegment(segment: LocalVideoSegment, nowEpochMs: Long): BufferMutation =
        segmentBuffer.add(segment, nowEpochMs, protectedFromEpochMs)

    fun observe(
        timestampEpochMs: Long,
        normalizedMotion: Double,
        gymnastPresent: Boolean,
    ): MotionCaptureAction {
        require(timestampEpochMs >= 0)
        if (phase == MotionCapturePhase.DISARMED || phase == MotionCapturePhase.FINALIZING) {
            return MotionCaptureAction.None
        }
        if (phase == MotionCapturePhase.POST_ROLL) {
            // Once exercise-end has fired, post-roll is a one-way phase. New motion belongs to
            // the current capture until it is finalized; it must not create a second START.
            return tick(timestampEpochMs)
        }

        return when (motionGate.observe(normalizedMotion, gymnastPresent)) {
            MotionDecision.START -> {
                check(phase == MotionCapturePhase.ARMED)
                val window = MotionCaptureWindow(
                    captureIdFactory(),
                    timestampEpochMs,
                    (timestampEpochMs - config.preRollMs).coerceAtLeast(0),
                )
                activeWindow = window
                phase = MotionCapturePhase.CAPTURING
                MotionCaptureAction.Started(window)
            }
            MotionDecision.EXERCISE_ENDED -> {
                val current = activeWindow ?: error("Exercise ended without active capture")
                check(phase == MotionCapturePhase.CAPTURING)
                val updated = current.copy(
                    exerciseEndedAtEpochMs = timestampEpochMs,
                    requestedEndEpochMs = timestampEpochMs + config.postRollMs,
                )
                activeWindow = updated
                phase = MotionCapturePhase.POST_ROLL
                if (config.postRollMs == 0L) finalizeAt(timestampEpochMs, false)
                else MotionCaptureAction.EnteredPostRoll(updated)
            }
            MotionDecision.NONE -> MotionCaptureAction.None
        }
    }

    fun tick(timestampEpochMs: Long): MotionCaptureAction {
        require(timestampEpochMs >= 0)
        val current = activeWindow ?: return MotionCaptureAction.None
        val deadline = current.requestedEndEpochMs ?: return MotionCaptureAction.None
        return if (phase == MotionCapturePhase.POST_ROLL && timestampEpochMs >= deadline) {
            finalizeAt(deadline, false)
        } else MotionCaptureAction.None
    }

    fun manualStop(timestampEpochMs: Long): MotionCaptureAction {
        require(timestampEpochMs >= 0)
        motionGate.manualStop()
        val current = activeWindow
        if (current == null) {
            phase = MotionCapturePhase.DISARMED
            return MotionCaptureAction.None
        }
        return finalizeAt(timestampEpochMs, true)
    }

    fun disarm(timestampEpochMs: Long): MotionCaptureAction {
        require(timestampEpochMs >= 0)
        motionGate.disarm()
        val current = activeWindow
        if (current == null) {
            phase = MotionCapturePhase.DISARMED
            return MotionCaptureAction.None
        }
        return finalizeAt(timestampEpochMs, true)
    }

    fun rearm() {
        check(phase != MotionCapturePhase.FINALIZING)
        activeWindow = null
        motionGate.rearm()
        phase = MotionCapturePhase.ARMED
    }

    fun finalizationComplete(nowEpochMs: Long): BufferMutation {
        check(phase == MotionCapturePhase.FINALIZING)
        activeWindow = null
        phase = if (motionGate.automaticStartSuppressed) MotionCapturePhase.DISARMED else MotionCapturePhase.ARMED
        return segmentBuffer.prune(nowEpochMs)
    }

    private fun finalizeAt(endEpochMs: Long, manualStop: Boolean): MotionCaptureAction.Finalize {
        val current = activeWindow ?: error("No active capture to finalize")
        val safeEnd = endEpochMs.coerceAtLeast(current.triggerAtEpochMs + 1)
        val finalized = current.copy(requestedEndEpochMs = safeEnd, manualStop = manualStop)
        activeWindow = finalized
        phase = MotionCapturePhase.FINALIZING
        val segments = segmentBuffer.overlapping(finalized.requestedStartEpochMs, safeEnd)
        val trimStart = segments.firstOrNull()?.let {
            (finalized.requestedStartEpochMs - it.startedAtEpochMs).coerceAtLeast(0)
        } ?: 0
        val trimEnd = segments.lastOrNull()?.let { (it.endedAtEpochMs - safeEnd).coerceAtLeast(0) } ?: 0
        return MotionCaptureAction.Finalize(
            SegmentAssemblyPlan(
                finalized.captureId,
                finalized.requestedStartEpochMs,
                safeEnd,
                segments,
                trimStart,
                trimEnd,
                manualStop,
            )
        )
    }
}
