package com.boellund.wagvid.capture.camera

import android.content.Context
import androidx.camera.view.CameraController
import androidx.camera.view.LifecycleCameraController
import androidx.camera.video.AudioConfig
import androidx.camera.video.FileOutputOptions
import androidx.camera.video.Recording
import androidx.camera.video.VideoRecordEvent
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import java.io.File

class CameraRecordingController(private val context: Context) {
    val camera = LifecycleCameraController(context).apply {
        setEnabledUseCases(CameraController.VIDEO_CAPTURE)
    }
    private var recording: Recording? = null

    fun bind(owner: LifecycleOwner) = camera.bindToLifecycle(owner)

    fun start(file: File, includeAudio: Boolean, onFinalized: (VideoRecordEvent.Finalize) -> Unit) {
        check(recording == null) { "A recording is already active" }
        recording = camera.startRecording(
            FileOutputOptions.Builder(file).build(),
            AudioConfig.create(includeAudio),
            ContextCompat.getMainExecutor(context),
        ) { event ->
            if (event is VideoRecordEvent.Finalize) {
                recording = null
                onFinalized(event)
            }
        }
    }

    fun stop() {
        recording?.stop()
        recording = null
    }

    val isRecording: Boolean get() = recording != null
}
