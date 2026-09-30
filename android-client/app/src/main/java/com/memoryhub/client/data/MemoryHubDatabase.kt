package com.memoryhub.client.data

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.Update

@Entity(tableName = "upload_state")
data class UploadState(
    @PrimaryKey val uri: String,
    val sha256: String? = null,
    val size: Long,
    val state: String,
    val lastError: String? = null,
    val attempts: Int = 0,
    val updatedAt: Long = System.currentTimeMillis(),
)

@Dao
interface UploadStateDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entry: UploadState)

    @Update
    suspend fun update(entry: UploadState)

    @Query("SELECT * FROM upload_state WHERE state != 'done' ORDER BY updatedAt DESC")
    suspend fun pending(): List<UploadState>

    @Query("SELECT * FROM upload_state WHERE uri = :uri")
    suspend fun findByUri(uri: String): UploadState?

    @Query("SELECT * FROM upload_state ORDER BY updatedAt DESC")
    suspend fun all(): List<UploadState>
}

@Database(entities = [UploadState::class], version = 1, exportSchema = false)
abstract class MemoryHubDatabase : RoomDatabase() {
    abstract fun uploadStateDao(): UploadStateDao

    companion object {
        fun create(context: Context): MemoryHubDatabase =
            Room.databaseBuilder(context, MemoryHubDatabase::class.java, "memoryhub.db")
                .fallbackToDestructiveMigration()
                .build()

        fun inMemory(context: Context): MemoryHubDatabase =
            Room.inMemoryDatabaseBuilder(context, MemoryHubDatabase::class.java)
                .allowMainThreadQueries()
                .build()
    }
}
