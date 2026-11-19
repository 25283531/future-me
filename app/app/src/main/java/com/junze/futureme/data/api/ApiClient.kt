package com.junze.futureme.data.api

import com.google.gson.FieldNamingPolicy
import com.google.gson.GsonBuilder
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

/**
 * Builds Retrofit for a base URL that the user can change in 我的 -> 服务器地址.
 * All calls go to <baseUrl>/api/v1/… ; the auth token is passed per call
 * (see FutureMeRepository) so a base-url change never leaks a stale client.
 */
class ApiClient {

    @Volatile
    var baseUrl: String = DEFAULT_BASE_URL
        private set

    @Volatile
    private var service: ApiService = buildService(baseUrl)

    fun updateBaseUrl(url: String) {
        val normalized = url.trim().trimEnd('/')
        if (normalized.isNotEmpty() && normalized != baseUrl) {
            baseUrl = normalized
            service = buildService(normalized)
        }
    }

    fun service(): ApiService = service

    private fun buildService(baseUrl: String): ApiService {
        val gson = GsonBuilder()
            .setFieldNamingPolicy(FieldNamingPolicy.LOWER_CASE_WITH_UNDERSCORES)
            .create()
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        }
        val client = OkHttpClient.Builder()
            .addInterceptor(logging)
            .build()
        return Retrofit.Builder()
            .baseUrl("$baseUrl/api/v1/")
            .client(client)
            .addConverterFactory(GsonConverterFactory.create(gson))
            .build()
            .create(ApiService::class.java)
    }

    companion object {
        /** Tailscale IP of the home router backend; LAN fallback is 10.0.1.1:8000. */
        const val DEFAULT_BASE_URL = "http://100.72.221.19:8000"
        const val LAN_FALLBACK_BASE_URL = "http://10.0.1.1:8000"
    }
}
