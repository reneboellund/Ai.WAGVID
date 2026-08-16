package com.boellund.wagvid.capture

import android.app.Application
import androidx.room.Room
import com.boellund.wagvid.capture.data.CaptureDatabase

class WagvidApplication : Application() {
    val database: CaptureDatabase by lazy {
        Room.databaseBuilder(this, CaptureDatabase::class.java, "wagvid-capture.db")
            .fallbackToDestructiveMigrationOnDowngrade()
            .build()
    }
}
