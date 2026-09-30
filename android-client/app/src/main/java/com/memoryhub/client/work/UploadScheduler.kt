package com.memoryhub.client.work

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

object UploadScheduler {
    fun enqueue(
        context: Context,
        uri: String,
        mime: String,
        kind: String,
        wifiOnly: Boolean,
        requiresCharging: Boolean,
        deleteLocalOnSuccess: Boolean,
        baseUrl: String,
    ) {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(if (wifiOnly) NetworkType.UNMETERED else NetworkType.CONNECTED)
            .setRequiresCharging(requiresCharging)
            .build()
        val data = Data.Builder()
            .putString("uri", uri)
            .putString("mime", mime)
            .putString("kind", kind)
            .putBoolean("delete_local_on_success", deleteLocalOnSuccess)
            .putString("base_url", baseUrl)
            .build()
        val req = OneTimeWorkRequestBuilder<UploadWorker>()
            .setConstraints(constraints)
            .setInputData(data)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS)
            .addTag("upload")
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            "upload:$uri",
            ExistingWorkPolicy.KEEP,
            req,
        )
    }
}
