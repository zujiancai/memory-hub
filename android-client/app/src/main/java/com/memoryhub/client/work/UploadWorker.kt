package com.memoryhub.client.work

import android.content.Context
import android.net.Uri
import androidx.documentfile.provider.DocumentFile
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.memoryhub.client.MemoryHubApp
import com.memoryhub.client.api.ApiClient
import com.memoryhub.client.api.ApiService
import com.memoryhub.client.api.CreateAssetRequest
import com.memoryhub.client.api.PrecheckRequest
import com.memoryhub.client.api.TokenStore
import com.memoryhub.client.api.UploadUrlRequest
import com.memoryhub.client.data.MemoryHubDatabase
import com.memoryhub.client.data.UploadState
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.security.MessageDigest

/**
 * Uploads a single URI to the Memory Hub backend.
 *
 * Input data:
 *  - `uri`     — content:// URI or file path
 *  - `mime`    — MIME type (defaults to application/octet-stream)
 *  - `kind`    — "photo" or "video" (defaults to "photo")
 *  - `deleteLocalOnSuccess` — Boolean (defaults to false)
 *
 * The worker is testable via [runOnce], which is called by both [doWork] and
 * the WorkManager instrumentation tests. Networking is injected via [apiFactory]
 * so tests can swap in a fake.
 */
class UploadWorker(
    context: Context,
    params: WorkerParameters,
    private val database: MemoryHubDatabase =
        (context.applicationContext as MemoryHubApp).database,
    private val tokenStore: TokenStore = TokenStore(context),
    private val apiFactory: (String, TokenStore) -> ApiService = { base, ts -> ApiClient.build(base, ts) },
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val uri = inputData.getString("uri") ?: return Result.failure()
        val mime = inputData.getString("mime") ?: "application/octet-stream"
        val kind = inputData.getString("kind") ?: "photo"
        val deleteLocalOnSuccess = inputData.getBoolean("delete_local_on_success", false)
        val baseUrl = inputData.getString("base_url") ?: "http://10.0.2.2:5000"

        val api = apiFactory(baseUrl, tokenStore)
        val ctx = applicationContext
        val (bytes, filename) = readUri(ctx, Uri.parse(uri)) ?: return Result.failure()
        val sha = sha256Hex(bytes)
        val size = bytes.size.toLong()

        database.uploadStateDao().upsert(
            UploadState(uri = uri, sha256 = sha, size = size, state = "hashing")
        )

        val pre = api.precheck(PrecheckRequest(sha, size))
        if (!pre.isSuccessful) return retryOrFail(uri, "precheck failed ${pre.code()}")

        if (pre.body()?.exists == false) {
            val urlResp = api.uploadUrl(UploadUrlRequest(sha, size, mime))
            if (!urlResp.isSuccessful) return retryOrFail(uri, "upload-url ${urlResp.code()}")
            val putUrl = urlResp.body()?.uploadUrl ?: return Result.failure()
            val ok = OkHttpClient().newCall(
                Request.Builder()
                    .url(putUrl)
                    .header("x-ms-blob-type", "BlockBlob")
                    .put(bytes.toRequestBody())
                    .build()
            ).execute().use { it.isSuccessful }
            if (!ok) return retryOrFail(uri, "PUT failed")
        }

        val asset = api.createAsset(
            CreateAssetRequest(sha, size, filename, mime, kind)
        )
        if (!asset.isSuccessful) return retryOrFail(uri, "POST /api/asset ${asset.code()}")

        val assetId = asset.body()?.id ?: return Result.failure()

        val confirm = api.getAsset(assetId)
        if (!confirm.isSuccessful) return retryOrFail(uri, "confirm ${confirm.code()}")

        database.uploadStateDao().upsert(
            UploadState(uri = uri, sha256 = sha, size = size, state = "done")
        )
        if (deleteLocalOnSuccess) {
            runCatching { DocumentFile.fromSingleUri(ctx, Uri.parse(uri))?.delete() }
        }
        return Result.success()
    }

    private suspend fun retryOrFail(uri: String, err: String): Result {
        val existing = database.uploadStateDao().findByUri(uri)
        val attempts = (existing?.attempts ?: 0) + 1
        database.uploadStateDao().upsert(
            UploadState(
                uri = uri,
                sha256 = existing?.sha256,
                size = existing?.size ?: 0,
                state = if (attempts >= 5) "failed" else "queued",
                lastError = err,
                attempts = attempts,
            )
        )
        return if (attempts >= 5) Result.failure() else Result.retry()
    }

    private fun readUri(ctx: Context, uri: Uri): Pair<ByteArray, String>? {
        val name = DocumentFile.fromSingleUri(ctx, uri)?.name ?: uri.lastPathSegment ?: "unknown"
        val bytes = ctx.contentResolver.openInputStream(uri)?.use { it.readBytes() } ?: return null
        return bytes to name
    }

    private fun sha256Hex(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
        return digest.joinToString("") { "%02x".format(it) }
    }
}
