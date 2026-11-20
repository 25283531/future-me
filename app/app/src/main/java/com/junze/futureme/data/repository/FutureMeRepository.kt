package com.junze.futureme.data.repository

import com.junze.futureme.data.api.ActivityDto
import com.junze.futureme.data.api.ApiClient
import com.junze.futureme.data.api.ApiService
import com.junze.futureme.data.api.AuthResponse
import com.junze.futureme.data.api.CaptchaDto
import com.junze.futureme.data.api.ChangePasswordRequest
import com.junze.futureme.data.api.CheckinStatusDto
import com.junze.futureme.data.api.CodeRequest
import com.junze.futureme.data.api.CreateWishRequest
import com.junze.futureme.data.api.DailySentenceDto
import com.junze.futureme.data.api.DeleteAccountRequest
import com.junze.futureme.data.api.DeviceAuthRequest
import com.junze.futureme.data.api.EmailRequest
import com.junze.futureme.data.api.GenerateLetterRequest
import com.junze.futureme.data.api.GenericOkResponse
import com.junze.futureme.data.api.LetterDto
import com.junze.futureme.data.api.LoginRequest
import com.junze.futureme.data.api.MeResponse
import com.junze.futureme.data.api.MembershipStatusDto
import com.junze.futureme.data.api.MessageDto
import com.junze.futureme.data.api.PrivacyDto
import com.junze.futureme.data.api.RegisterRequest
import com.junze.futureme.data.api.ResetPasswordRequest
import com.junze.futureme.data.api.VerifyResponse
import com.junze.futureme.data.api.VoiceDto
import com.junze.futureme.data.api.WishDto
import com.junze.futureme.data.local.AppDatabase
import com.junze.futureme.data.local.LetterEntity
import com.junze.futureme.data.local.WishEntity
import com.junze.futureme.data.prefs.SettingsStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import retrofit2.HttpException

/**
 * Single source of truth for screens.
 *
 * - Wishes / letters: Room cache first, network refresh on top. Offline the
 *   cached rows are shown and a "showing cached content" flag is surfaced.
 * - Auth: device id (UUID, stored once) -> POST /auth/device -> Bearer token.
 *   On HTTP 401 the token is refreshed once and the call retried.
 * - Audio URLs: a letter may carry an absolute url, a "/api/v1/audio/…" path,
 *   or just a filename — all three are resolved against the current base URL.
 */
class FutureMeRepository(
    private val apiClient: ApiClient,
    private val settings: SettingsStore,
    private val db: AppDatabase
) {

    // ---------- Observables (Room cache) ----------

    val wishes: Flow<List<WishDto>> =
        db.wishDao().observeAll().map { rows -> rows.map { it.toDto() } }

    val letters: Flow<List<LetterDto>> =
        db.letterDao().observeAll().map { rows -> rows.map { it.toDto() } }

    fun lettersForWish(wishId: String): Flow<List<LetterDto>> =
        db.letterDao().observeByWish(wishId).map { rows -> rows.map { it.toDto() } }

    // ---------- Auth ----------

    private suspend fun authHeader(): String {
        var token = settings.token.first()
        if (token.isNullOrBlank()) {
            token = authenticate()
        }
        return "Bearer $token"
    }

    private suspend fun authenticate(): String {
        val deviceId = settings.getOrCreateDeviceId()
        val response = apiClient.service().authDevice(DeviceAuthRequest(deviceId))
        settings.saveToken(response.token)
        return response.token
    }

    /**
     * Runs [block] with a valid token; on 401 re-authenticates once and retries.
     * Returns Result.failure on any other error (callers show cached data).
     */
    private suspend fun <T> withAuth(block: suspend (ApiService, String) -> T): Result<T> {
        return try {
            val header = authHeader()
            Result.success(block(apiClient.service(), header))
        } catch (e: HttpException) {
            if (e.code() == 401) {
                return try {
                    settings.saveToken(null)
                    val header = "Bearer ${authenticate()}"
                    Result.success(block(apiClient.service(), header))
                } catch (retryError: Exception) {
                    Result.failure(retryError)
                }
            }
            Result.failure(e)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // ---------- Email accounts ----------

    /** The account token replaces the device token in the same slot:
     * it still authenticates this device, and additionally carries the
     * account id (membership becomes per-account). */
    private suspend fun saveAccountSession(response: AuthResponse) {
        settings.saveToken(response.token)
        response.user?.email?.let { settings.saveAccountEmail(it) }
    }

    suspend fun getCaptcha(): Result<CaptchaDto> = runCatching {
        apiClient.service().getCaptcha()
    }

    suspend fun register(
        email: String, password: String, captchaChallengeId: String, captchaAnswer: String
    ): Result<AuthResponse> = runCatching {
        val deviceId = settings.getOrCreateDeviceId()
        apiClient.service().register(
            RegisterRequest(email, password, deviceId, captchaChallengeId, captchaAnswer)
        ).also { saveAccountSession(it) }
    }

    suspend fun login(email: String, password: String): Result<AuthResponse> = runCatching {
        val deviceId = settings.getOrCreateDeviceId()
        apiClient.service().login(LoginRequest(email, password, deviceId))
            .also { saveAccountSession(it) }
    }

    /** Log out of the account and fall back to anonymous device auth. */
    suspend fun logout(): Result<Unit> = runCatching {
        settings.saveToken(null)
        settings.saveAccountEmail(null)
        authenticate()
        Unit
    }

    suspend fun getMe(): Result<MeResponse> =
        withAuth { api, header -> api.getMe(header) }

    suspend fun verifyEmail(code: String): Result<VerifyResponse> =
        withAuth { api, header -> api.verifyEmail(header, CodeRequest(code)) }

    suspend fun resendVerification(): Result<GenericOkResponse> =
        withAuth { api, header -> api.resendVerification(header) }

    suspend fun forgotPassword(email: String): Result<GenericOkResponse> = runCatching {
        apiClient.service().forgotPassword(EmailRequest(email))
    }

    suspend fun resetPassword(
        email: String, code: String, newPassword: String
    ): Result<GenericOkResponse> = runCatching {
        apiClient.service().resetPassword(ResetPasswordRequest(email, code, newPassword))
    }

    suspend fun changePassword(
        currentPassword: String, newPassword: String
    ): Result<GenericOkResponse> =
        withAuth { api, header ->
            api.changePassword(header, ChangePasswordRequest(currentPassword, newPassword))
        }

    suspend fun deleteAccount(password: String): Result<GenericOkResponse> =
        withAuth { api, header ->
            api.deleteAccount(header, DeleteAccountRequest(password))
        }.onSuccess {
            // The server deleted the account and this device's data;
            // drop back to a fresh anonymous device identity.
            settings.saveToken(null)
            settings.saveAccountEmail(null)
        }

    suspend fun getPrivacy(): Result<PrivacyDto> =
        withAuth { api, header -> api.getPrivacy(header) }

    // ---------- Wishes ----------

    suspend fun refreshWishes(): Result<Unit> =
        withAuth { api, header ->
            val remote = api.getWishes(header)
            db.wishDao().insertAll(remote.map { it.toEntity() })
        }

    suspend fun createWish(text: String, category: String, days: Int): Result<WishDto> =
        withAuth { api, header ->
            val created = api.createWish(header, CreateWishRequest(text, category, days))
            db.wishDao().insert(created.toEntity())
            created
        }

    suspend fun getWish(id: String): WishDto? = db.wishDao().getById(id)?.toDto()

    // ---------- Letters ----------

    suspend fun refreshLetters(): Result<Unit> =
        withAuth { api, header ->
            val remote = api.getLetters(header)
            db.letterDao().insertAll(remote.map { it.toEntity() })
        }

    suspend fun generateLetter(wishId: String, voiceId: String?): Result<LetterDto> =
        withAuth { api, header ->
            val created = api.generateLetter(header, GenerateLetterRequest(wishId, voiceId))
            db.letterDao().insert(created.toEntity())
            created
        }

    suspend fun getLetter(id: String): LetterDto? = db.letterDao().getById(id)?.toDto()

    // ---------- Voices ----------

    suspend fun getVoices(): Result<List<VoiceDto>> =
        withAuth { api, header -> api.getVoices(header) }

    // ---------- Daily / check-in ----------

    suspend fun getDailySentence(): Result<DailySentenceDto> =
        withAuth { api, header ->
            api.getDailySentence(header).also { settings.saveDailySentence(it.text) }
        }

    suspend fun getCheckinStatus(): Result<CheckinStatusDto> =
        withAuth { api, header -> api.getCheckinStatus(header) }

    suspend fun checkin(): Result<CheckinStatusDto> =
        withAuth { api, header -> api.checkin(header) }

    // ---------- Membership / messages / activities (fetch-on-open) ----------

    suspend fun getMembershipStatus(): Result<MembershipStatusDto> =
        withAuth { api, header -> api.getMembershipStatus(header) }

    suspend fun getMessages(): Result<List<MessageDto>> =
        withAuth { api, header -> api.getMessages(header) }

    suspend fun getActivities(): Result<List<ActivityDto>> =
        withAuth { api, header -> api.getActivities(header) }

    // ---------- Audio URL resolution ----------

    fun resolveAudioUrl(letter: LetterDto): String? {
        val raw = letter.audioUrl?.takeIf { it.isNotBlank() }
            ?: letter.audioFile?.takeIf { it.isNotBlank() }?.let { file ->
                if (file.startsWith("/")) file else "/api/v1/audio/$file"
            }
            ?: return null
        return when {
            raw.startsWith("http://") || raw.startsWith("https://") -> raw
            raw.startsWith("/") -> apiClient.baseUrl + raw
            else -> apiClient.baseUrl + "/api/v1/audio/" + raw
        }
    }

    // ---------- DTO <-> Entity mapping ----------

    private fun WishDto.toEntity() = WishEntity(
        id = id, text = text, category = category, days = days,
        targetDate = targetDate, status = status, createdAt = createdAt
    )

    private fun WishEntity.toDto() = WishDto(
        id = id, text = text, category = category, days = days,
        targetDate = targetDate, status = status, createdAt = createdAt
    )

    private fun LetterDto.toEntity() = LetterEntity(
        id = id, wishId = wishId, text = text, voiceId = voiceId,
        audioUrl = audioUrl, audioFile = audioFile, createdAt = createdAt
    )

    private fun LetterEntity.toDto() = LetterDto(
        id = id, wishId = wishId, text = text, voiceId = voiceId,
        audioUrl = audioUrl, audioFile = audioFile, createdAt = createdAt
    )
}
