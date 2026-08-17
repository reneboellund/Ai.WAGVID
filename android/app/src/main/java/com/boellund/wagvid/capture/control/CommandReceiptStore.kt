package com.boellund.wagvid.capture.control

data class CommandReceipt(
    val commandId: String,
    val accepted: Boolean,
    val finalState: String,
    val rejectionCode: String,
    val executedAtEpochMs: Long,
)

interface CommandReceiptStore {
    suspend fun find(commandId: String): CommandReceipt?
    suspend fun save(receipt: CommandReceipt)
    suspend fun prune(beforeEpochMs: Long): Int = 0
}
