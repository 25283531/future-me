package com.junze.futureme

import android.app.Application
import com.junze.futureme.data.api.ApiClient
import com.junze.futureme.data.audio.AudioPlayer
import com.junze.futureme.data.local.AppDatabase
import com.junze.futureme.data.prefs.SettingsStore
import com.junze.futureme.data.repository.FutureMeRepository
import com.junze.futureme.worker.ReminderWorker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Manual DI container — no DI framework, everything is wired here and
 * passed to screens from MainActivity.
 */
class FutureMeApp : Application() {

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

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

        // Apply the saved backend address before the first request.
        appScope.launch {
            val savedUrl = settings.baseUrl.first()
            apiClient.updateBaseUrl(savedUrl)
        }

        // Daily local reminders at 8:00 and 20:00.
        ReminderWorker.schedule(this)
    }
}
