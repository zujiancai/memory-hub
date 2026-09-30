package com.memoryhub.client.api

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Response
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory

/**
 * Attaches the bearer access token to outgoing requests. On a 401 response,
 * blocks and refreshes the token synchronously via the refresh endpoint, then
 * replays the original request once. Refresh is serialised through a mutex so
 * concurrent 401s don't dogpile the refresh endpoint.
 */
class AuthInterceptor(
    private val tokenStore: TokenStore,
    private val refreshCall: suspend (String) -> TokenResponse?,
) : Interceptor {
    private val refreshMutex = Mutex()

    override fun intercept(chain: Interceptor.Chain): Response {
        val original = chain.request()
        val token = tokenStore.accessToken
        val request = if (token != null && original.header("Authorization") == null) {
            original.newBuilder().header("Authorization", "Bearer $token").build()
        } else original

        val response = chain.proceed(request)
        if (response.code != 401) return response

        val refresh = tokenStore.refreshToken ?: return response
        val newTokens = runBlocking {
            refreshMutex.withLock {
                if (tokenStore.accessToken != token) {
                    // Someone else already refreshed while we were waiting.
                    null
                } else {
                    runCatching { refreshCall(refresh) }.getOrNull()
                }
            }
        }
        if (newTokens == null) return response

        tokenStore.accessToken = newTokens.accessToken
        tokenStore.refreshToken = newTokens.refreshToken

        response.close()
        val retried = original.newBuilder()
            .header("Authorization", "Bearer ${newTokens.accessToken}")
            .build()
        return chain.proceed(retried)
    }
}

object ApiClient {
    val moshi: Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    fun buildBare(baseUrl: String): ApiService = Retrofit.Builder()
        .baseUrl(baseUrl)
        .client(OkHttpClient.Builder().build())
        .addConverterFactory(MoshiConverterFactory.create(moshi))
        .build()
        .create(ApiService::class.java)

    fun build(baseUrl: String, tokenStore: TokenStore): ApiService {
        val bare = buildBare(baseUrl)
        val interceptor = AuthInterceptor(tokenStore) { refresh ->
            bare.refresh(RefreshRequest(refresh)).body()
        }
        val client = OkHttpClient.Builder()
            .addInterceptor(interceptor)
            .build()
        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()
            .create(ApiService::class.java)
    }
}
