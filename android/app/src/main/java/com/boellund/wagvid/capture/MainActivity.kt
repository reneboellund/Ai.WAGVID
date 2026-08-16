package com.boellund.wagvid.capture

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.lifecycleScope
import com.boellund.wagvid.capture.camera.CameraRecordingController
import com.boellund.wagvid.capture.data.CaptureEntity
import com.boellund.wagvid.capture.data.UploadQueueEntity
import com.boellund.wagvid.capture.upload.UploadWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest
import java.util.UUID

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { CaptureScreen() } }
    }

    private fun persist(file: File, captureId: String, startedAt: Long) {
        lifecycleScope.launch {
            val digest = withContext(Dispatchers.IO) {
                val hash = MessageDigest.getInstance("SHA-256")
                file.inputStream().use { input ->
                    val buffer = ByteArray(1024 * 1024)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        hash.update(buffer, 0, count)
                    }
                }
                hash.digest().joinToString("") { "%02x".format(it) }
            }
            val dao = (application as WagvidApplication).database.captures()
            dao.insertCapture(
                CaptureEntity(captureId, file.toURI().toString(), file.name, "unassigned", "Ikke valgt", "", "", "training", null, startedAt, System.currentTimeMillis() - startedAt, file.length(), digest)
            )
            dao.enqueueUpload(UploadQueueEntity(captureId))
            UploadWorker.schedule(this@MainActivity)
        }
    }

    @Composable
    private fun CaptureScreen() {
        val context = LocalContext.current
        val lifecycleOwner = LocalLifecycleOwner.current
        val controller = remember { CameraRecordingController(context) }
        var recording by remember { mutableStateOf(false) }
        var status by remember { mutableStateOf("KLAR") }
        val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { }
        DisposableEffect(lifecycleOwner) { controller.bind(lifecycleOwner); onDispose { controller.stop() } }
        Box(Modifier.fillMaxSize().background(Color(0xFF07101E))) {
            AndroidView(factory = { PreviewView(it).apply { this.controller = controller.camera } }, modifier = Modifier.fillMaxSize())
            Column(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.SpaceBetween) {
                Text("Backend: ikke parret · Uploadkø gemmes lokalt", color = Color.White)
                Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
                    Text(status, color = if (recording) Color.Red else Color.White)
                    Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                        Button(
                            modifier = Modifier.size(88.dp),
                            shape = CircleShape,
                            colors = ButtonDefaults.buttonColors(containerColor = if (recording) Color.Red else Color(0xFF18D4A3)),
                            onClick = {
                                if (recording) { controller.stop(); status = "GEMMER" }
                                else {
                                    val permissions = arrayOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO)
                                    if (permissions.any { ContextCompat.checkSelfPermission(context, it) != PackageManager.PERMISSION_GRANTED }) permissionLauncher.launch(permissions)
                                    else {
                                        val id = UUID.randomUUID().toString(); val started = System.currentTimeMillis()
                                        val directory = File(filesDir, "archive").apply { mkdirs() }
                                        controller.start(File(directory, "$id.mp4"), true) { event ->
                                            if (!event.hasError()) persist(File(directory, "$id.mp4"), id, started)
                                            recording = false; status = if (event.hasError()) "OPTAGELSE FEJLEDE" else "GEMT LOKALT"
                                        }
                                        recording = true; status = "OPTAGER"
                                    }
                                }
                            },
                        ) { Text(if (recording) "STOP" else "OPTAG") }
                    }
                    Text("Manuel stop virker også ved automatisk start", color = Color.White)
                }
            }
        }
    }
}
