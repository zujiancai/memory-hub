package com.memoryhub.client.api

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path

interface ApiService {
    @POST("/api/user/signup")
    suspend fun signup(@Body body: SignupRequest): Response<TokenResponse>

    @POST("/api/user/login")
    suspend fun login(@Body body: LoginRequest): Response<TokenResponse>

    @POST("/api/user/refresh")
    suspend fun refresh(@Body body: RefreshRequest): Response<TokenResponse>

    @POST("/api/user/logout")
    suspend fun logout(@Body body: RefreshRequest): Response<Unit>

    @GET("/api/user/me")
    suspend fun me(): Response<UserResponse>

    @POST("/api/user/oauth/google/callback")
    suspend fun googleCallback(@Body body: OAuthGoogleCallbackRequest): Response<TokenResponse>

    @POST("/api/asset/precheck")
    suspend fun precheck(@Body body: PrecheckRequest): Response<PrecheckResponse>

    @POST("/api/asset/upload-url")
    suspend fun uploadUrl(@Body body: UploadUrlRequest): Response<UploadUrlResponse>

    @POST("/api/asset")
    suspend fun createAsset(@Body body: CreateAssetRequest): Response<AssetResponse>

    @GET("/api/asset/{id}")
    suspend fun getAsset(@Path("id") id: String): Response<AssetResponse>
}
