package com.boellund.wagvid.capture

import android.app.Application
import androidx.room.Room
import com.boellund.wagvid.capture.data.CaptureDatabase
import com.boellund.wagvid.capture.upload.UploadWorker

class WagvidApplication : Application() {
    val database: CaptureDatabase by lazy {
        Room.databaseBuilder(this, CaptureDatabase::class.java, "wagvid-capture.db")
            .fallbackToDestructiveMigrationOnDowngrade()
            .build()
    }

    override fun onCreate() {
        super.onCreate()
        // WorkManager is durable, but scheduling again with the same unique-work ID also heals
        // the narrow crash window between a Room queue commit and the original schedule call.
        UploadWorker.schedule(this)
    }
}
