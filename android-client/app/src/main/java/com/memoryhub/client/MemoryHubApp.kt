package com.memoryhub.client

import android.app.Application
import androidx.work.Configuration
import androidx.work.WorkManager
import com.memoryhub.client.data.MemoryHubDatabase

class MemoryHubApp : Application(), Configuration.Provider {
    lateinit var database: MemoryHubDatabase
        private set

    override fun onCreate() {
        super.onCreate()
        database = MemoryHubDatabase.create(this)
    }

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setMinimumLoggingLevel(android.util.Log.INFO)
            .build()
}
