package com.boellund.wagvid.capture.data

import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.RoomDatabase
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "captures", indices = [Index("recordedAtEpochMs")])
data class CaptureEntity(
    @PrimaryKey val captureId: String,
    val localUri: String,
    val localFilename: String,
    val gymnastId: String,
    val gymnastName: String,
    val licenseNumber: String,
    val level: String,
    val kind: String,
    val apparatus: String?,
    val recordedAtEpochMs: Long,
    val durationMs: Long,
    val sizeBytes: Long,
    val sha256: String,
    val localRetained: Boolean = true,
)

@Entity(tableName = "upload_queue", indices = [Index("state"), Index("nextAttemptAtEpochMs")])
data class UploadQueueEntity(
    @PrimaryKey val captureId: String,
    val state: String = "queued",
    val attempts: Int = 0,
    val uploadedBytes: Long = 0,
    val remoteMediaId: String? = null,
    val lastError: String? = null,
    val nextAttemptAtEpochMs: Long = 0,
)

data class CaptureArchiveRow(
    val captureId: String,
    val gymnastName: String,
    val kind: String,
    val recordedAtEpochMs: Long,
    val sizeBytes: Long,
    val uploadState: String?,
    val uploadedBytes: Long?,
    val lastError: String?,
)

@Dao
interface CaptureDao {
    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insertCapture(capture: CaptureEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun enqueueUpload(item: UploadQueueEntity)

    @Update suspend fun updateUpload(item: UploadQueueEntity)

    @Query("SELECT * FROM captures ORDER BY recordedAtEpochMs DESC")
    fun archive(): Flow<List<CaptureEntity>>

    @Query(
        "SELECT c.captureId, c.gymnastName, c.kind, c.recordedAtEpochMs, c.sizeBytes, " +
            "q.state AS uploadState, q.uploadedBytes AS uploadedBytes, q.lastError AS lastError " +
            "FROM captures c LEFT JOIN upload_queue q ON q.captureId = c.captureId " +
            "ORDER BY c.recordedAtEpochMs DESC LIMIT :limit",
    )
    fun archiveRows(limit: Int = 30): Flow<List<CaptureArchiveRow>>

    @Query(
        "SELECT * FROM upload_queue " +
            "WHERE state IN ('queued','uploading') " +
            "OR (state = 'retry-wait' AND nextAttemptAtEpochMs <= :nowEpochMs) " +
            "ORDER BY nextAttemptAtEpochMs, captureId LIMIT 1",
    )
    suspend fun nextUpload(nowEpochMs: Long): UploadQueueEntity?

    @Query("SELECT * FROM captures WHERE captureId = :captureId")
    suspend fun capture(captureId: String): CaptureEntity?

    @Query("SELECT COUNT(*) FROM upload_queue WHERE state IN ('queued','retry-wait','uploading')")
    fun queuedCount(): Flow<Int>

    @Query("SELECT COUNT(*) FROM upload_queue WHERE state IN ('queued','retry-wait','uploading')")
    suspend fun queuedCountSnapshot(): Int
}

@Database(entities = [CaptureEntity::class, UploadQueueEntity::class], version = 1, exportSchema = false)
abstract class CaptureDatabase : RoomDatabase() {
    abstract fun captures(): CaptureDao
}
