package com.junze.futureme.data.prefs

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.junze.futureme.data.api.ApiClient
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import java.util.UUID

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "future_me_settings")

/**
 * Small persistent settings: device id (generated once), auth token,
 * backend base URL, selected voice, cached daily sentence.
 */
class SettingsStore(context: Context) {

    private val store = context.applicationContext.dataStore

    val deviceId: Flow<String> = store.data.map { prefs ->
        prefs[KEY_DEVICE_ID] ?: ""
    }

    val token: Flow<String?> = store.data.map { prefs -> prefs[KEY_TOKEN] }

    val baseUrl: Flow<String> = store.data.map { prefs ->
        prefs[KEY_BASE_URL] ?: ApiClient.DEFAULT_BASE_URL
    }

    val selectedVoiceId: Flow<String?> = store.data.map { prefs -> prefs[KEY_VOICE_ID] }

    val cachedDailySentence: Flow<String?> = store.data.map { prefs -> prefs[KEY_SENTENCE] }

    /** Returns the stored device id, generating + persisting one on first run. */
    suspend fun getOrCreateDeviceId(): String {
        val existing = store.data.map { it[KEY_DEVICE_ID] }.first()
        if (!existing.isNullOrBlank()) return existing
        val created = UUID.randomUUID().toString()
        store.edit { it[KEY_DEVICE_ID] = created }
        return created
    }

    suspend fun saveToken(token: String?) {
        store.edit { prefs ->
            if (token == null) prefs.remove(KEY_TOKEN) else prefs[KEY_TOKEN] = token
        }
    }

    suspend fun saveBaseUrl(url: String) {
        store.edit { it[KEY_BASE_URL] = url.trim().trimEnd('/') }
    }

    suspend fun saveSelectedVoiceId(voiceId: String?) {
        store.edit { prefs ->
            if (voiceId == null) prefs.remove(KEY_VOICE_ID) else prefs[KEY_VOICE_ID] = voiceId
        }
    }

    suspend fun saveDailySentence(text: String) {
        store.edit { it[KEY_SENTENCE] = text }
    }

    companion object {
        private val KEY_DEVICE_ID = stringPreferencesKey("device_id")
        private val KEY_TOKEN = stringPreferencesKey("auth_token")
        private val KEY_BASE_URL = stringPreferencesKey("base_url")
        private val KEY_VOICE_ID = stringPreferencesKey("selected_voice_id")
        private val KEY_SENTENCE = stringPreferencesKey("daily_sentence")
    }
}
