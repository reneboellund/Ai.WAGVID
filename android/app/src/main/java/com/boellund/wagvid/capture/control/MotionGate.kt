package com.boellund.wagvid.capture.control

data class MotionGateConfig(
    val startThreshold: Double = 0.35,
    val stopThreshold: Double = 0.10,
    val startFrames: Int = 4,
    val quietFrames: Int = 75,
    val preRollMs: Long = 2_000,
    val postRollMs: Long = 1_500,
)

enum class MotionDecision { NONE, START, EXERCISE_ENDED }

class MotionGate(private val config: MotionGateConfig = MotionGateConfig()) {
    private var activeFrames = 0
    private var quietFrames = 0
    var recording = false
        private set

    fun observe(normalizedMotion: Double, gymnastPresent: Boolean): MotionDecision {
        require(normalizedMotion in 0.0..1.0)
        if (!recording) {
            activeFrames = if (gymnastPresent && normalizedMotion >= config.startThreshold) activeFrames + 1 else 0
            if (activeFrames >= config.startFrames) {
                recording = true; activeFrames = 0; quietFrames = 0
                return MotionDecision.START
            }
            return MotionDecision.NONE
        }
        quietFrames = if (!gymnastPresent || normalizedMotion <= config.stopThreshold) quietFrames + 1 else 0
        if (quietFrames >= config.quietFrames) {
            recording = false; quietFrames = 0
            return MotionDecision.EXERCISE_ENDED
        }
        return MotionDecision.NONE
    }

    fun manualStop() { recording = false; activeFrames = 0; quietFrames = 0 }
}
