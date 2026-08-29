package com.boellund.wagvid.capture.upload

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.boellund.wagvid.capture.WagvidApplication
import com.boellund.wagvid.capture.data.CaptureEntity
import com.boellund.wagvid.capture.data.UploadQueueEntity
import com.boellund.wagvid.capture.network.ApiFactory
import com.boellund.wagvid.capture.network.UploadOpenRequest
import com.boellund.wagvid.capture.security.BackendCredential
import com.boellund.wagvid.capture.security.CredentialStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File
import java.io.InputStream
import java.time.Instant
import java.util.concurrent.TimeUnit

class UploadWorker(context: Context, parameters: WorkerParameters) : CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val app = applicationContext as WagvidApplication
        val dao = app.database.captures()
        val credentials = CredentialStore(applicationContext).load() ?: return@withContext Result.retry()

        while (true) {
            val queued = dao.nextUpload(System.currentTimeMillis()) ?: break
            val capture = dao.capture(queued.captureId)
            if (capture == null) {
                dao.updateUpload(queued.copy(state = "failed", lastError = "LOCAL_CAPTURE_MISSING"))
                continue
            }
            val file = runCatching { File(java.net.URI(capture.localUri)) }.getOrNull()
            if (file == null || !file.exists()) {
                dao.updateUpload(queued.copy(state = "failed", lastError = "LOCAL_FILE_MISSING"))
                continue
            }

            try {
                uploadOne(credentials, capture, queued, file)
            } catch (error: Exception) {
                val attempts = queued.attempts + 1
                dao.updateUpload(
                    queued.copy(
                        state = "retry-wait",
                        attempts = attempts,
                        lastError = error.javaClass.simpleName,
                        nextAttemptAtEpochMs = System.currentTimeMillis() + retryDelayMs(attempts),
                    ),
                )
                return@withContext Result.retry()
            }
        }
        Result.success()
    }

    private suspend fun uploadOne(
        credentials: BackendCredential,
        capture: CaptureEntity,
        queued: UploadQueueEntity,
        file: File,
    ) {
        val dao = (applicationContext as WagvidApplication).database.captures()
        val api = ApiFactory.create(credentials.baseUrl, credentials.certificateFingerprint)
        val token = "Bearer ${credentials.apiToken}"
        val opened = api.openUpload(
            credentials.deviceKey,
            token,
            UploadOpenRequest(
                capture.captureId,
                "android:${capture.captureId}",
                capture.localFilename,
                capture.sizeBytes,
                capture.sha256,
                capture.gymnastId,
                capture.kind,
                Instant.ofEpochMilli(capture.recordedAtEpochMs).toString(),
            ),
        )
        require(opened.received_bytes in 0L..capture.sizeBytes) { "Invalid server upload offset" }
        var offset = opened.received_bytes
        file.inputStream().use { stream ->
            skipExactly(stream, offset)
            val buffer = ByteArray(CHUNK_BYTES)
            while (true) {
                val count = stream.read(buffer)
                if (count < 0) break
                val body = buffer.copyOf(count)
                    .toRequestBody("application/octet-stream".toMediaType())
                val response = api.uploadChunk(
                    credentials.deviceKey,
                    token,
                    offset,
                    opened.upload_id,
                    body,
                )
                if (!response.isSuccessful) error("chunk upload failed: ${response.code()}")
                offset += count
                dao.updateUpload(
                    queued.copy(
                        state = "uploading",
                        uploadedBytes = offset,
                        lastError = null,
                    ),
                )
            }
        }
        check(offset == capture.sizeBytes) { "Upload byte count does not match local file" }
        val completed = api.finalizeUpload(credentials.deviceKey, token, opened.upload_id)
        dao.updateUpload(
            queued.copy(
                state = "uploaded",
                uploadedBytes = capture.sizeBytes,
                remoteMediaId = completed.media_id,
                lastError = null,
                nextAttemptAtEpochMs = 0,
            ),
        )
    }

    private fun skipExactly(stream: InputStream, requested: Long) {
        var remaining = requested
        while (remaining > 0) {
            val skipped = stream.skip(remaining)
            if (skipped > 0) {
                remaining -= skipped
                continue
            }
            if (stream.read() < 0) error("Local file ended before resume offset")
            remaining -= 1
        }
    }

    companion object {
        private const val CHUNK_BYTES = 4 * 1024 * 1024

        private fun retryDelayMs(attempts: Int): Long = 30_000L * attempts.coerceIn(1, 20)

        fun schedule(context: Context) {
            val request = OneTimeWorkRequestBuilder<UploadWorker>()
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build(),
                )
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(
                "wagvid-upload-queue",
                ExistingWorkPolicy.KEEP,
                request,
            )
        }
    }
}
