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
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
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
import com.boellund.wagvid.capture.control.LocalCaptureControl
import com.boellund.wagvid.capture.control.LocalCaptureState
import com.boellund.wagvid.capture.data.CaptureEntity
import com.boellund.wagvid.capture.data.UploadQueueEntity
import com.boellund.wagvid.capture.network.CaptureContextResponse
import com.boellund.wagvid.capture.network.GymnastContext
import com.boellund.wagvid.capture.runtime.ActiveDeviceRuntime
import com.boellund.wagvid.capture.runtime.CaptureRuntimeRepository
import com.boellund.wagvid.capture.security.BackendCredential
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

    private fun persist(
        file: File,
        captureId: String,
        startedAt: Long,
        gymnast: GymnastContext,
        kind: String,
        apparatus: String?,
    ) {
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
                CaptureEntity(
                    captureId = captureId,
                    localUri = file.toURI().toString(),
                    localFilename = file.name,
                    gymnastId = gymnast.gymnast_id,
                    gymnastName = gymnast.display_name,
                    licenseNumber = gymnast.license_number,
                    level = gymnast.level,
                    kind = kind,
                    apparatus = apparatus,
                    recordedAtEpochMs = startedAt,
                    durationMs = System.currentTimeMillis() - startedAt,
                    sizeBytes = file.length(),
                    sha256 = digest,
                ),
            )
            dao.enqueueUpload(UploadQueueEntity(captureId))
            UploadWorker.schedule(this@MainActivity)
        }
    }

    @Composable
    private fun CaptureScreen() {
        val context = LocalContext.current
        val lifecycleOwner = LocalLifecycleOwner.current
        val coroutineScope = rememberCoroutineScope()
        val controller = remember { CameraRecordingController(context) }
        val runtime = remember { CaptureRuntimeRepository(context) }
        var credential by remember { mutableStateOf<BackendCredential?>(runtime.credential()) }
        var serverContext by remember { mutableStateOf<CaptureContextResponse?>(null) }
        var selectedGymnast by remember { mutableStateOf<GymnastContext?>(null) }
        var selectedKind by remember { mutableStateOf<String?>(null) }
        var captureState by remember { mutableStateOf(LocalCaptureState.READY) }
        var activeCaptureId by remember { mutableStateOf<String?>(null) }
        var status by remember { mutableStateOf("KLAR") }
        var backendStatus by remember {
            mutableStateOf(if (credential == null) "IKKE PARRET" else "FORBINDER")
        }
        val currentActiveCaptureId by rememberUpdatedState(activeCaptureId)
        val permissionLauncher = rememberLauncherForActivityResult(
            ActivityResultContracts.RequestMultiplePermissions(),
        ) { }

        val captureControl = remember(controller) {
            object : LocalCaptureControl {
                override val state: LocalCaptureState
                    get() = captureState

                override suspend fun arm(context: Map<String, Any?>) {
                    throw UnsupportedOperationException("Motion-triggered capture is not enabled")
                }

                override suspend fun disarm() {
                    throw UnsupportedOperationException("Motion-triggered capture is not enabled")
                }

                override suspend fun start(context: Map<String, Any?>) {
                    check(captureState == LocalCaptureState.READY) {
                        "Capture is ${captureState.wire}"
                    }
                    val permissions = arrayOf(
                        Manifest.permission.CAMERA,
                        Manifest.permission.RECORD_AUDIO,
                    )
                    if (permissions.any {
                            ContextCompat.checkSelfPermission(this@MainActivity, it) !=
                                PackageManager.PERMISSION_GRANTED
                        }
                    ) {
                        throw SecurityException("Camera/audio permission is required")
                    }
                    val captureId = context["capture_id"]?.toString()?.takeIf { it.isNotBlank() }
                        ?: error("Remote/manual capture context has no capture_id")
                    val gymnastId = context["gymnast_id"]?.toString()?.takeIf { it.isNotBlank() }
                        ?: error("Capture context has no gymnast_id")
                    val kind = context["kind"]?.toString()?.takeIf { it.isNotBlank() }
                        ?: error("Capture context has no media kind")
                    val gymnast = serverContext?.gymnasts?.firstOrNull {
                        it.gymnast_id == gymnastId
                    } ?: error("Gymnast is not present in current capture context")
                    if (kind !in (serverContext?.media_kinds ?: emptyList())) {
                        error("Media kind is not present in current capture context")
                    }
                    val apparatus = context["apparatus"]?.toString()?.takeIf { it.isNotBlank() }
                    val startedAt = System.currentTimeMillis()
                    val directory = File(filesDir, "archive").apply { mkdirs() }
                    val file = File(directory, "$captureId.mp4")
                    controller.start(file, true) { event ->
                        if (!event.hasError()) {
                            persist(file, captureId, startedAt, gymnast, kind, apparatus)
                        }
                        activeCaptureId = null
                        captureState = LocalCaptureState.READY
                        status = if (event.hasError()) {
                            "OPTAGELSE FEJLEDE"
                        } else {
                            "GEMT LOKALT · UPLOAD KØET"
                        }
                    }
                    selectedGymnast = gymnast
                    selectedKind = kind
                    activeCaptureId = captureId
                    captureState = LocalCaptureState.RECORDING
                    status = "OPTAGER · ${gymnast.display_name}"
                }

                override suspend fun stop() {
                    check(captureState == LocalCaptureState.RECORDING) {
                        "Capture is ${captureState.wire}"
                    }
                    captureState = LocalCaptureState.FINALIZING
                    status = "GEMMER"
                    controller.stop()
                }
            }
        }

        DisposableEffect(lifecycleOwner) {
            controller.bind(lifecycleOwner)
            onDispose { controller.stop() }
        }

        LaunchedEffect(credential?.deviceKey) {
            val paired = credential ?: return@LaunchedEffect
            backendStatus = "HENTER CONTEXT"
            try {
                val loaded = runtime.captureContext(paired)
                serverContext = loaded
                selectedGymnast = selectedGymnast
                    ?.let { current ->
                        loaded.gymnasts.firstOrNull { it.gymnast_id == current.gymnast_id }
                    }
                    ?: loaded.gymnasts.firstOrNull()
                selectedKind = selectedKind?.takeIf { it in loaded.media_kinds }
                    ?: loaded.media_kinds.firstOrNull()
                backendStatus = "PARRET"
            } catch (_: Exception) {
                backendStatus = "BACKEND UTILGÆNGELIG"
            }
        }

        LaunchedEffect(credential?.deviceKey, serverContext?.organization_id) {
            val paired = credential ?: return@LaunchedEffect
            if (serverContext == null) return@LaunchedEffect
            ActiveDeviceRuntime(
                context = context,
                credential = paired,
                control = captureControl,
                activeCaptureId = { currentActiveCaptureId },
            ).runWhileActive(
                onConnected = { backendStatus = "ONLINE · ${captureControl.state.wire.uppercase()}" },
                onConnectionError = { backendStatus = "BACKEND UTILGÆNGELIG" },
            )
        }

        if (credential == null) {
            PairingScreen(
                status = backendStatus,
                onPair = { baseUrl, pairingId, code, deviceName ->
                    coroutineScope.launch {
                        backendStatus = "PARRER"
                        try {
                            val (paired, loaded) = runtime.pair(
                                baseUrl,
                                pairingId,
                                code,
                                deviceName,
                            )
                            credential = paired
                            serverContext = loaded
                            selectedGymnast = loaded.gymnasts.firstOrNull()
                            selectedKind = loaded.media_kinds.firstOrNull()
                            backendStatus = "PARRET"
                        } catch (error: Exception) {
                            backendStatus =
                                "PAIRING FEJLEDE: ${error.message ?: error.javaClass.simpleName}"
                        }
                    }
                },
            )
            return
        }

        Box(Modifier.fillMaxSize().background(Color(0xFF07101E))) {
            AndroidView(
                factory = { PreviewView(it).apply { this.controller = controller.camera } },
                modifier = Modifier.fillMaxSize(),
            )
            Column(
                Modifier.fillMaxSize().padding(20.dp),
                verticalArrangement = Arrangement.SpaceBetween,
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Backend: $backendStatus", color = Color.White)
                    CaptureContextSelector(
                        serverContext = serverContext,
                        selectedGymnast = selectedGymnast,
                        selectedKind = selectedKind,
                        onGymnast = { selectedGymnast = it },
                        onKind = { selectedKind = it },
                        onRefresh = {
                            coroutineScope.launch {
                                backendStatus = "OPDATERER"
                                try {
                                    val loaded = runtime.captureContext()
                                    serverContext = loaded
                                    selectedGymnast = selectedGymnast
                                        ?.let { current ->
                                            loaded.gymnasts.firstOrNull {
                                                it.gymnast_id == current.gymnast_id
                                            }
                                        }
                                        ?: loaded.gymnasts.firstOrNull()
                                    selectedKind = selectedKind?.takeIf { it in loaded.media_kinds }
                                        ?: loaded.media_kinds.firstOrNull()
                                    backendStatus = "PARRET"
                                } catch (_: Exception) {
                                    backendStatus = "BACKEND UTILGÆNGELIG"
                                }
                            }
                        },
                    )
                }
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        status,
                        color = if (captureState == LocalCaptureState.RECORDING) Color.Red else Color.White,
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                        Button(
                            enabled = captureState == LocalCaptureState.RECORDING ||
                                (captureState == LocalCaptureState.READY &&
                                    selectedGymnast != null && selectedKind != null),
                            modifier = Modifier.size(88.dp),
                            shape = CircleShape,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = if (captureState == LocalCaptureState.RECORDING) {
                                    Color.Red
                                } else {
                                    Color(0xFF18D4A3)
                                },
                            ),
                            onClick = {
                                if (captureState == LocalCaptureState.RECORDING) {
                                    coroutineScope.launch { captureControl.stop() }
                                } else {
                                    val gymnast = selectedGymnast ?: return@Button
                                    val kind = selectedKind ?: return@Button
                                    val permissions = arrayOf(
                                        Manifest.permission.CAMERA,
                                        Manifest.permission.RECORD_AUDIO,
                                    )
                                    if (permissions.any {
                                            ContextCompat.checkSelfPermission(context, it) !=
                                                PackageManager.PERMISSION_GRANTED
                                        }
                                    ) {
                                        permissionLauncher.launch(permissions)
                                    } else {
                                        coroutineScope.launch {
                                            captureControl.start(
                                                mapOf(
                                                    "capture_id" to UUID.randomUUID().toString(),
                                                    "gymnast_id" to gymnast.gymnast_id,
                                                    "kind" to kind,
                                                ),
                                            )
                                        }
                                    }
                                }
                            },
                        ) {
                            Text(
                                if (captureState == LocalCaptureState.RECORDING) "STOP" else "OPTAG",
                            )
                        }
                    }
                    Text(
                        when (captureState) {
                            LocalCaptureState.FINALIZING -> "Gemmer optagelse…"
                            else -> if (selectedGymnast == null) {
                                "Vælg gymnast før optagelse"
                            } else {
                                "${selectedGymnast?.display_name} · ${selectedKind ?: "—"}"
                            }
                        },
                        color = Color.White,
                    )
                }
            }
        }
    }

    @Composable
    private fun PairingScreen(
        status: String,
        onPair: (String, String, String, String) -> Unit,
    ) {
        var baseUrl by remember { mutableStateOf("") }
        var pairingId by remember { mutableStateOf("") }
        var code by remember { mutableStateOf("") }
        var deviceName by remember { mutableStateOf("Ai.WAGVID Android") }
        Surface(Modifier.fillMaxSize(), color = Color(0xFF07101E)) {
            Column(
                Modifier.fillMaxSize().padding(28.dp),
                verticalArrangement = Arrangement.Center,
            ) {
                Text(
                    "Par enhed",
                    color = Color.White,
                    style = MaterialTheme.typography.headlineMedium,
                )
                Text(
                    "Brug backend-adressen, pairing-ID og 6-cifret kode fra Ai.WAGVID web-UI.",
                    color = Color.White,
                )
                OutlinedTextField(
                    value = baseUrl,
                    onValueChange = { baseUrl = it },
                    label = { Text("Backend URL") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = pairingId,
                    onValueChange = { pairingId = it },
                    label = { Text("Pairing-ID") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = code,
                    onValueChange = { code = it.filter(Char::isDigit).take(6) },
                    label = { Text("6-cifret kode") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = deviceName,
                    onValueChange = { deviceName = it },
                    label = { Text("Enhedsnavn") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(status, color = Color.White)
                Button(
                    enabled = baseUrl.isNotBlank() && pairingId.isNotBlank() && code.length == 6,
                    onClick = { onPair(baseUrl, pairingId, code, deviceName) },
                ) { Text("Par med Ai.WAGVID") }
            }
        }
    }

    @Composable
    private fun CaptureContextSelector(
        serverContext: CaptureContextResponse?,
        selectedGymnast: GymnastContext?,
        selectedKind: String?,
        onGymnast: (GymnastContext) -> Unit,
        onKind: (String) -> Unit,
        onRefresh: () -> Unit,
    ) {
        var gymnastMenu by remember { mutableStateOf(false) }
        var kindMenu by remember { mutableStateOf(false) }
        Surface(color = Color(0xCC07101E)) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (serverContext == null) {
                    Text("Ingen capture-context fra backend", color = Color.White)
                    Button(onClick = onRefresh) { Text("Prøv igen") }
                    return@Column
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Box {
                        Button(onClick = { gymnastMenu = true }) {
                            Text(selectedGymnast?.display_name ?: "Vælg gymnast")
                        }
                        DropdownMenu(
                            expanded = gymnastMenu,
                            onDismissRequest = { gymnastMenu = false },
                        ) {
                            serverContext.gymnasts.forEach { gymnast ->
                                DropdownMenuItem(
                                    text = { Text("${gymnast.display_name} · ${gymnast.level}") },
                                    onClick = {
                                        onGymnast(gymnast)
                                        gymnastMenu = false
                                    },
                                )
                            }
                        }
                    }
                    Box {
                        Button(onClick = { kindMenu = true }) {
                            Text(selectedKind ?: "Type")
                        }
                        DropdownMenu(
                            expanded = kindMenu,
                            onDismissRequest = { kindMenu = false },
                        ) {
                            serverContext.media_kinds.forEach { kind ->
                                DropdownMenuItem(
                                    text = { Text(kind) },
                                    onClick = {
                                        onKind(kind)
                                        kindMenu = false
                                    },
                                )
                            }
                        }
                    }
                    Button(onClick = onRefresh) { Text("↻") }
                }
                if (serverContext.gymnasts.isEmpty()) {
                    Text("Backend har ingen aktive gymnaster", color = Color.White)
                }
            }
        }
    }
}
