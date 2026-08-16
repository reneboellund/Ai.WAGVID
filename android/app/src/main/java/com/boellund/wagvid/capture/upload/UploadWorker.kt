package com.boellund.wagvid.capture.upload

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.Constraints
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.boellund.wagvid.capture.WagvidApplication
import com.boellund.wagvid.capture.network.ApiFactory
import com.boellund.wagvid.capture.network.UploadOpenRequest
import com.boellund.wagvid.capture.security.CredentialStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File
import java.time.Instant

class UploadWorker(context: Context, parameters: WorkerParameters) : CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val app = applicationContext as WagvidApplication
        val dao = app.database.captures()
        val queued = dao.nextUpload() ?: return@withContext Result.success()
        val capture = dao.capture(queued.captureId) ?: return@withContext Result.failure()
        val credentials = CredentialStore(applicationContext).load() ?: return@withContext Result.retry()
        val file = File(java.net.URI(capture.localUri))
        if (!file.exists()) return@withContext Result.failure()
        val api = ApiFactory.create(credentials.baseUrl)
        val token = "Bearer ${credentials.apiToken}"
        try {
            val opened = api.openUpload(
                credentials.deviceKey,
                token,
                UploadOpenRequest(capture.captureId, "android:${capture.captureId}", capture.localFilename, capture.sizeBytes, capture.sha256, capture.gymnastId, capture.kind, Instant.ofEpochMilli(capture.recordedAtEpochMs).toString()),
            )
            var offset = opened.received_bytes
            file.inputStream().use { stream ->
                stream.skip(offset)
                val buffer = ByteArray(4 * 1024 * 1024)
                while (true) {
                    val count = stream.read(buffer)
                    if (count < 0) break
                    val body = buffer.copyOf(count).toRequestBody("application/octet-stream".toMediaType())
                    val response = api.uploadChunk(credentials.deviceKey, token, offset, opened.upload_id, body)
                    if (!response.isSuccessful) error("chunk upload failed: ${response.code()}")
                    offset += count
                    dao.updateUpload(queued.copy(state = "uploading", uploadedBytes = offset))
                }
            }
            val completed = api.finalizeUpload(credentials.deviceKey, token, opened.upload_id)
            dao.updateUpload(queued.copy(state = "uploaded", uploadedBytes = capture.sizeBytes, remoteMediaId = completed.media_id, lastError = null))
            Result.success()
        } catch (error: Exception) {
            val attempts = queued.attempts + 1
            dao.updateUpload(queued.copy(state = "retry-wait", attempts = attempts, lastError = error.javaClass.simpleName, nextAttemptAtEpochMs = System.currentTimeMillis() + (30_000L * attempts.coerceAtMost(20))))
            Result.retry()
        }
    }

    companion object {
        fun schedule(context: Context) {
            val request = OneTimeWorkRequestBuilder<UploadWorker>()
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork("wagvid-upload-queue", ExistingWorkPolicy.KEEP, request)
        }
    }
}
