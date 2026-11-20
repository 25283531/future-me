package com.junze.futureme

import android.app.Application
import com.junze.futureme.data.api.ApiClient
import com.junze.futureme.data.audio.AudioPlayer
import com.junze.futureme.data.local.AppDatabase
import com.junze.futureme.data.prefs.SettingsStore
import com.junze.futureme.data.repository.FutureMeRepository
import com.junze.futureme.worker.ReminderWorker

/**
 * Manual DI container — no DI framework, everything is wired here and
 * passed to screens from MainActivity.
 *
 * The backend address is built into the app (ApiClient.DEFAULT_BASE_URL)
 * — the user cannot change it.
 */
class FutureMeApp : Application() {

    lateinit var settings: SettingsStore
        private set
    lateinit var apiClient: ApiClient
        private set
    lateinit var repository: FutureMeRepository
        private set
    lateinit var audioPlayer: AudioPlayer
        private set

    override fun onCreate() {
        super.onCreate()
        settings = SettingsStore(this)
        apiClient = ApiClient()
        repository = FutureMeRepository(
            apiClient = apiClient,
            settings = settings,
            db = AppDatabase.get(this)
        )
        audioPlayer = AudioPlayer(this)

        // Daily local reminders at 8:00 and 20:00.
        ReminderWorker.schedule(this)
    }
}
