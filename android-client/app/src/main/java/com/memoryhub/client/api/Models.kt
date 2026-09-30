package com.memoryhub.client.api

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class LoginRequest(
    val email: String,
    val password: String,
)

@JsonClass(generateAdapter = true)
data class SignupRequest(
    val email: String,
    val password: String,
    @Json(name = "friendly_name") val friendlyName: String,
)

@JsonClass(generateAdapter = true)
data class TokenResponse(
    @Json(name = "access_token") val accessToken: String,
    @Json(name = "refresh_token") val refreshToken: String,
    val user: UserResponse,
)

@JsonClass(generateAdapter = true)
data class UserResponse(
    val id: String,
    val email: String,
    @Json(name = "friendly_name") val friendlyName: String,
)

@JsonClass(generateAdapter = true)
data class RefreshRequest(@Json(name = "refresh_token") val refreshToken: String)

@JsonClass(generateAdapter = true)
data class PrecheckRequest(val sha256: String, val size: Long)

@JsonClass(generateAdapter = true)
data class PrecheckResponse(
    val exists: Boolean,
    @Json(name = "upload_url") val uploadUrl: String? = null,
)

@JsonClass(generateAdapter = true)
data class UploadUrlRequest(
    val sha256: String,
    val size: Long,
    @Json(name = "mime_type") val mimeType: String,
)

@JsonClass(generateAdapter = true)
data class UploadUrlResponse(@Json(name = "upload_url") val uploadUrl: String)

@JsonClass(generateAdapter = true)
data class CreateAssetRequest(
    val sha256: String,
    val size: Long,
    @Json(name = "original_filename") val originalFilename: String,
    @Json(name = "mime_type") val mimeType: String,
    val kind: String,
)

@JsonClass(generateAdapter = true)
data class AssetResponse(
    val id: String,
    val kind: String,
    @Json(name = "capture_ts") val captureTs: String? = null,
)

@JsonClass(generateAdapter = true)
data class OAuthGoogleCallbackRequest(
    val code: String,
    @Json(name = "code_verifier") val codeVerifier: String,
)
