package com.boellund.wagvid.capture.control

data class MotionGateConfig(
    val startThreshold: Double = 0.35,
    val stopThreshold: Double = 0.10,
    val startFrames: Int = 4,
    val quietFrames: Int = 75,
    val preRollMs: Long = 2_000,
    val postRollMs: Long = 1_500,
) {
    init {
        require(startThreshold in 0.0..1.0)
        require(stopThreshold in 0.0..1.0)
        require(stopThreshold <= startThreshold)
        require(startFrames > 0)
        require(quietFrames > 0)
        require(preRollMs >= 0)
        require(postRollMs >= 0)
    }
}

enum class MotionDecision { NONE, START, EXERCISE_ENDED }

class MotionGate(private val config: MotionGateConfig = MotionGateConfig()) {
    private var activeFrames = 0
    private var quietFrames = 0
    private var manualStopLatched = false
    var recording = false
        private set

    val automaticStartSuppressed: Boolean get() = manualStopLatched

    fun observe(normalizedMotion: Double, gymnastPresent: Boolean): MotionDecision {
        require(normalizedMotion in 0.0..1.0)
        if (!recording) {
            if (manualStopLatched) {
                // Local STOP is authoritative. Motion cannot restart the same armed session until
                // an explicit disarm/re-arm cycle clears the latch.
                activeFrames = 0
                return MotionDecision.NONE
            }
            activeFrames =
                if (gymnastPresent && normalizedMotion >= config.startThreshold) activeFrames + 1
                else 0
            if (activeFrames >= config.startFrames) {
                recording = true
                activeFrames = 0
                quietFrames = 0
                return MotionDecision.START
            }
            return MotionDecision.NONE
        }
        quietFrames =
            if (!gymnastPresent || normalizedMotion <= config.stopThreshold) quietFrames + 1
            else 0
        if (quietFrames >= config.quietFrames) {
            recording = false
            quietFrames = 0
            activeFrames = 0
            return MotionDecision.EXERCISE_ENDED
        }
        return MotionDecision.NONE
    }

    fun manualStop() {
        recording = false
        manualStopLatched = true
        activeFrames = 0
        quietFrames = 0
    }

    fun rearm() {
        recording = false
        manualStopLatched = false
        activeFrames = 0
        quietFrames = 0
    }

    fun disarm() {
        recording = false
        manualStopLatched = true
        activeFrames = 0
        quietFrames = 0
    }
}
