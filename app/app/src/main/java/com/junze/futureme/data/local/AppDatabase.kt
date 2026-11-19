package com.junze.futureme.data.local

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
import kotlinx.coroutines.flow.Flow

// ---------- Entities (offline cache) ----------

@Entity(tableName = "wishes")
data class WishEntity(
    @PrimaryKey val id: String,
    val text: String,
    val category: String,
    val days: Int,
    val targetDate: String,
    val status: String,
    val createdAt: String?
)

@Entity(tableName = "letters")
data class LetterEntity(
    @PrimaryKey val id: String,
    val wishId: String,
    val text: String,
    val voiceId: String?,
    val audioUrl: String?,
    val audioFile: String?,
    val createdAt: String?
)

// ---------- DAOs ----------

@Dao
interface WishDao {
    @Query("SELECT * FROM wishes ORDER BY createdAt DESC")
    fun observeAll(): Flow<List<WishEntity>>

    @Query("SELECT * FROM wishes WHERE id = :id")
    suspend fun getById(id: String): WishEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(wishes: List<WishEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(wish: WishEntity)
}

@Dao
interface LetterDao {
    @Query("SELECT * FROM letters ORDER BY createdAt DESC")
    fun observeAll(): Flow<List<LetterEntity>>

    @Query("SELECT * FROM letters WHERE wishId = :wishId ORDER BY createdAt DESC")
    fun observeByWish(wishId: String): Flow<List<LetterEntity>>

    @Query("SELECT * FROM letters WHERE id = :id")
    suspend fun getById(id: String): LetterEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(letters: List<LetterEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(letter: LetterEntity)
}

// ---------- Database ----------

@Database(entities = [WishEntity::class, LetterEntity::class], version = 1, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun wishDao(): WishDao
    abstract fun letterDao(): LetterDao

    companion object {
        @Volatile
        private var instance: AppDatabase? = null

        fun get(context: Context): AppDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "future-me.db"
                ).build().also { instance = it }
            }
    }
}
