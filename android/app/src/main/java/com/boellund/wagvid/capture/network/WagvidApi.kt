package com.boellund.wagvid.capture.network

import com.squareup.moshi.JsonClass
import okhttp3.RequestBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path

@JsonClass(generateAdapter = true)
data class PairingClaimRequest(val code: String, val device_key: String, val device_name: String, val app_version: String)
@JsonClass(generateAdapter = true)
data class PairingClaimResponse(val device_id: String, val device_key: String, val api_token: String, val organization_id: String)
@JsonClass(generateAdapter = true)
data class HeartbeatRequest(
    val state: String,
    val battery_percent: Int?,
    val free_storage_bytes: Long?,
    val queued_uploads: Int,
    val network_type: String,
    val app_version: String,
    val active_capture_id: String?,
)
@JsonClass(generateAdapter = true)
data class RemoteCommand(
    val command_id: String,
    val command: String,
    val expected_device_state: String,
    val payload: Map<String, Any?>,
    val expires_at: String,
)
@JsonClass(generateAdapter = true)
data class CommandEnvelope(val commands: List<RemoteCommand>)
@JsonClass(generateAdapter = true)
data class GymnastContext(val gymnast_id: String, val display_name: String, val license_number: String, val level: String, val discipline: String)
@JsonClass(generateAdapter = true)
data class CaptureContextResponse(val organization_id: String, val gymnasts: List<GymnastContext>, val media_kinds: List<String>)
@JsonClass(generateAdapter = true)
data class CommandAck(val accepted: Boolean, val resulting_state: String, val rejection_code: String = "")
@JsonClass(generateAdapter = true)
data class UploadOpenRequest(
    val capture_id: String,
    val idempotency_key: String,
    val local_filename: String,
    val expected_bytes: Long,
    val expected_sha256: String,
    val gymnast_id: String,
    val kind: String,
    val recorded_at: String,
)
@JsonClass(generateAdapter = true)
data class UploadOpenResponse(val upload_id: String, val state: String, val received_bytes: Long)
@JsonClass(generateAdapter = true)
data class UploadFinalizeResponse(val media_id: String, val state: String)

interface WagvidApi {
    @POST("api/device/pairing/{pairingId}/claim/")
    suspend fun claimPairing(@Path("pairingId") pairingId: String, @Body body: PairingClaimRequest): PairingClaimResponse

    @POST("api/device/heartbeat/")
    suspend fun heartbeat(@Header("X-WAGVID-Device") key: String, @Header("Authorization") token: String, @Body body: HeartbeatRequest): Response<Unit>

    @GET("api/device/commands/")
    suspend fun commands(@Header("X-WAGVID-Device") key: String, @Header("Authorization") token: String): CommandEnvelope

    @GET("api/device/capture-context/")
    suspend fun captureContext(@Header("X-WAGVID-Device") key: String, @Header("Authorization") token: String): CaptureContextResponse

    @POST("api/device/commands/{commandId}/ack/")
    suspend fun acknowledge(@Header("X-WAGVID-Device") key: String, @Header("Authorization") token: String, @Path("commandId") commandId: String, @Body body: CommandAck): Response<Unit>

    @POST("api/device/uploads/open/")
    suspend fun openUpload(@Header("X-WAGVID-Device") key: String, @Header("Authorization") token: String, @Body body: UploadOpenRequest): UploadOpenResponse

    @PUT("api/device/uploads/{uploadId}/chunk/")
    suspend fun uploadChunk(@Header("X-WAGVID-Device") key: String, @Header("Authorization") token: String, @Header("X-Upload-Offset") offset: Long, @Path("uploadId") uploadId: String, @Body bytes: RequestBody): Response<Unit>

    @POST("api/device/uploads/{uploadId}/finalize/")
    suspend fun finalizeUpload(@Header("X-WAGVID-Device") key: String, @Header("Authorization") token: String, @Path("uploadId") uploadId: String): UploadFinalizeResponse
}
