package com.junze.futureme.data.prefs

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import java.util.UUID

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "future_me_settings")

/**
 * Small persistent settings: device id (generated once), auth token,
 * logged-in account email, selected voice, cached daily sentence.
 * The backend address is built into the app (ApiClient.DEFAULT_BASE_URL)
 * and is deliberately NOT stored here — the user cannot change it.
 */
class SettingsStore(context: Context) {

    private val store = context.applicationContext.dataStore

    val deviceId: Flow<String> = store.data.map { prefs ->
        prefs[KEY_DEVICE_ID] ?: ""
    }

    val token: Flow<String?> = store.data.map { prefs -> prefs[KEY_TOKEN] }

    val accountEmail: Flow<String?> = store.data.map { prefs -> prefs[KEY_ACCOUNT_EMAIL] }

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

    suspend fun saveAccountEmail(email: String?) {
        store.edit { prefs ->
            if (email == null) prefs.remove(KEY_ACCOUNT_EMAIL) else prefs[KEY_ACCOUNT_EMAIL] = email
        }
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
        private val KEY_ACCOUNT_EMAIL = stringPreferencesKey("account_email")
        private val KEY_VOICE_ID = stringPreferencesKey("selected_voice_id")
        private val KEY_SENTENCE = stringPreferencesKey("daily_sentence")
    }
}
