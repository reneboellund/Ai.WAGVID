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
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import com.boellund.wagvid.capture.control.CommandReceipt
import com.boellund.wagvid.capture.control.CommandReceiptStore
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

@Entity(tableName = "command_receipts", indices = [Index("executedAtEpochMs")])
data class CommandReceiptEntity(
    @PrimaryKey val commandId: String,
    val accepted: Boolean,
    val finalState: String,
    val rejectionCode: String,
    val executedAtEpochMs: Long,
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

@Dao
interface CommandReceiptDao {
    @Query("SELECT * FROM command_receipts WHERE commandId = :commandId LIMIT 1")
    suspend fun find(commandId: String): CommandReceiptEntity?

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(receipt: CommandReceiptEntity): Long

    @Query("DELETE FROM command_receipts WHERE executedAtEpochMs < :beforeEpochMs")
    suspend fun prune(beforeEpochMs: Long): Int
}

class RoomCommandReceiptStore(private val dao: CommandReceiptDao) : CommandReceiptStore {
    override suspend fun find(commandId: String): CommandReceipt? = dao.find(commandId)?.let {
        CommandReceipt(
            commandId = it.commandId,
            accepted = it.accepted,
            finalState = it.finalState,
            rejectionCode = it.rejectionCode,
            executedAtEpochMs = it.executedAtEpochMs,
        )
    }

    override suspend fun save(receipt: CommandReceipt) {
        val inserted = dao.insert(
            CommandReceiptEntity(
                commandId = receipt.commandId,
                accepted = receipt.accepted,
                finalState = receipt.finalState,
                rejectionCode = receipt.rejectionCode,
                executedAtEpochMs = receipt.executedAtEpochMs,
            ),
        )
        if (inserted == -1L) {
            val existing = dao.find(receipt.commandId)
            check(existing != null) { "Command receipt conflict without stored row" }
            check(
                existing.accepted == receipt.accepted &&
                    existing.finalState == receipt.finalState &&
                    existing.rejectionCode == receipt.rejectionCode
            ) { "Command receipt outcome changed for ${receipt.commandId}" }
        }
    }

    override suspend fun prune(beforeEpochMs: Long): Int = dao.prune(beforeEpochMs)
}

@Database(
    entities = [CaptureEntity::class, UploadQueueEntity::class, CommandReceiptEntity::class],
    version = 2,
    exportSchema = false,
)
abstract class CaptureDatabase : RoomDatabase() {
    abstract fun captures(): CaptureDao
    abstract fun commandReceipts(): CommandReceiptDao

    companion object {
        val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS command_receipts (" +
                        "commandId TEXT NOT NULL, " +
                        "accepted INTEGER NOT NULL, " +
                        "finalState TEXT NOT NULL, " +
                        "rejectionCode TEXT NOT NULL, " +
                        "executedAtEpochMs INTEGER NOT NULL, " +
                        "PRIMARY KEY(commandId))",
                )
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS index_command_receipts_executedAtEpochMs " +
                        "ON command_receipts(executedAtEpochMs)",
                )
            }
        }
    }
}
