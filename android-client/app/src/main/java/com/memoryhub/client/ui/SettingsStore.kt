package com.memoryhub.client.ui

import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import androidx.core.content.edit

data class Settings(
    val baseUrl: String,
    val wifiOnly: Boolean,
    val requiresCharging: Boolean,
    val deleteLocalOnSuccess: Boolean,
    val watchFolders: Set<String>,
)

class SettingsStore(context: Context) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences("memoryhub-settings", Context.MODE_PRIVATE)

    fun load(): Settings = Settings(
        baseUrl = prefs.getString(BASE_URL, "http://10.0.2.2:5000")!!,
        wifiOnly = prefs.getBoolean(WIFI_ONLY, true),
        requiresCharging = prefs.getBoolean(REQ_CHARGE, false),
        deleteLocalOnSuccess = prefs.getBoolean(DELETE_LOCAL, false),
        watchFolders = prefs.getStringSet(WATCH_FOLDERS, emptySet())!!.toSet(),
    )

    fun update(block: (Settings) -> Settings) {
        val current = load()
        val next = block(current)
        prefs.edit {
            putString(BASE_URL, next.baseUrl)
            putBoolean(WIFI_ONLY, next.wifiOnly)
            putBoolean(REQ_CHARGE, next.requiresCharging)
            putBoolean(DELETE_LOCAL, next.deleteLocalOnSuccess)
            putStringSet(WATCH_FOLDERS, next.watchFolders)
        }
    }

    fun addWatchFolder(uri: String) = update { it.copy(watchFolders = it.watchFolders + uri) }

    fun removeWatchFolder(uri: String) = update { it.copy(watchFolders = it.watchFolders - uri) }

    /**
     * Persist read permission for a document tree URI so it survives reboots.
     */
    fun persistUriPermission(context: Context, uri: android.net.Uri) {
        val flags = Intent.FLAG_GRANT_READ_URI_PERMISSION or
            Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
        context.contentResolver.takePersistableUriPermission(uri, flags)
    }

    companion object {
        private const val BASE_URL = "base_url"
        private const val WIFI_ONLY = "wifi_only"
        private const val REQ_CHARGE = "req_charge"
        private const val DELETE_LOCAL = "delete_local"
        private const val WATCH_FOLDERS = "watch_folders"
    }
}
