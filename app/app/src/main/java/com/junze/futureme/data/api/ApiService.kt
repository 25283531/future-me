package com.junze.futureme.data.api

import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path

/**
 * Backend contract: base url is <server>/api/v1 (see ApiClient).
 * If the backend agent changes a field name, adjust the DTOs here —
 * the app never talks to model vendors directly.
 */

// ---------- Auth ----------

data class DeviceAuthRequest(val deviceId: String)

data class DeviceAuthResponse(val token: String)

// ---------- Wishes ----------

data class WishDto(
    val id: String,
    val text: String,
    val category: String,
    val days: Int,
    val targetDate: String,
    val status: String,
    val createdAt: String? = null
)

data class CreateWishRequest(
    val text: String,
    val category: String,
    val days: Int
)

// ---------- Letters ----------

data class LetterDto(
    val id: String,
    val wishId: String,
    val text: String,
    val voiceId: String? = null,
    /** Absolute URL, or a path / filename — resolved by the repository. */
    val audioUrl: String? = null,
    val audioFile: String? = null,
    val createdAt: String? = null
)

data class GenerateLetterRequest(
    val wishId: String,
    val voiceId: String? = null
)

// ---------- Voices ----------

data class VoiceDto(
    val id: String,
    val name: String,
    val provider: String,
    /** "free" or "member" (or any tier string the backend returns). */
    val tier: String,
    val description: String? = null
)

// ---------- Daily / check-in ----------

data class DailySentenceDto(
    val text: String,
    val date: String? = null
)

data class CheckinStatusDto(
    val streak: Int,
    val totalDays: Int,
    val checkedInToday: Boolean
)

// ---------- Membership / messages / activities ----------

data class MembershipStatusDto(
    /** "free" | "trial" | "active" | "expired" */
    val status: String,
    val trialDaysLeft: Int? = null,
    val plan: String? = null,
    val expiresAt: String? = null
)

data class MessageDto(
    val id: String,
    val title: String,
    val content: String,
    val type: String? = null,
    val createdAt: String? = null
)

data class ActivityDto(
    val id: String,
    val title: String,
    val content: String,
    val imageUrl: String? = null,
    val startAt: String? = null,
    val endAt: String? = null
)

interface ApiService {

    @POST("auth/device")
    suspend fun authDevice(@Body request: DeviceAuthRequest): DeviceAuthResponse

    @POST("wishes")
    suspend fun createWish(
        @Header("Authorization") token: String,
        @Body request: CreateWishRequest
    ): WishDto

    @GET("wishes")
    suspend fun getWishes(@Header("Authorization") token: String): List<WishDto>

    @POST("letters/generate")
    suspend fun generateLetter(
        @Header("Authorization") token: String,
        @Body request: GenerateLetterRequest
    ): LetterDto

    @GET("letters")
    suspend fun getLetters(@Header("Authorization") token: String): List<LetterDto>

    @GET("voices")
    suspend fun getVoices(@Header("Authorization") token: String): List<VoiceDto>

    @GET("daily-sentence")
    suspend fun getDailySentence(@Header("Authorization") token: String): DailySentenceDto

    @POST("checkin")
    suspend fun checkin(@Header("Authorization") token: String): CheckinStatusDto

    @GET("checkin/status")
    suspend fun getCheckinStatus(@Header("Authorization") token: String): CheckinStatusDto

    @GET("activities")
    suspend fun getActivities(@Header("Authorization") token: String): List<ActivityDto>

    @GET("messages")
    suspend fun getMessages(@Header("Authorization") token: String): List<MessageDto>

    @GET("membership/status")
    suspend fun getMembershipStatus(@Header("Authorization") token: String): MembershipStatusDto

    /** Audio files are streamed by URL (LetterDto.audioUrl), not via this call. */
    @GET("audio/{file}")
    suspend fun getAudio(@Path("file") file: String): okhttp3.ResponseBody
}
