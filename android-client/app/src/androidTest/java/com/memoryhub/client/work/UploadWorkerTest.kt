package com.memoryhub.client.work

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.work.Data
import androidx.work.ListenableWorker
import androidx.work.testing.TestListenableWorkerBuilder
import com.memoryhub.client.api.ApiService
import com.memoryhub.client.api.AssetResponse
import com.memoryhub.client.api.CreateAssetRequest
import com.memoryhub.client.api.LoginRequest
import com.memoryhub.client.api.OAuthGoogleCallbackRequest
import com.memoryhub.client.api.PrecheckRequest
import com.memoryhub.client.api.PrecheckResponse
import com.memoryhub.client.api.RefreshRequest
import com.memoryhub.client.api.SignupRequest
import com.memoryhub.client.api.TokenResponse
import com.memoryhub.client.api.TokenStore
import com.memoryhub.client.api.UploadUrlRequest
import com.memoryhub.client.api.UploadUrlResponse
import com.memoryhub.client.api.UserResponse
import com.memoryhub.client.data.MemoryHubDatabase
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import retrofit2.Response

/**
 * Unit-tests the [UploadWorker] without a real network by injecting a fake
 * [ApiService]. WorkManager runs the worker synchronously via
 * [TestListenableWorkerBuilder].
 */
@RunWith(AndroidJUnit4::class)
class UploadWorkerTest {
    private lateinit var putServer: MockWebServer

    @Before
    fun setUp() {
        putServer = MockWebServer().apply { start() }
    }

    @After
    fun tearDown() {
        putServer.shutdown()
    }

    @Test
    fun happyPathMarksUploadDone() = runBlocking {
        val ctx = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = MemoryHubDatabase.inMemory(ctx)
        val putUrl = putServer.url("/put").toString()
        putServer.enqueue(MockResponse().setResponseCode(201))

        val fakeApi = fakeApiReturningCreated(putUrl)

        // Prepare a temp file URI to feed to the worker.
        val file = java.io.File.createTempFile("photo", ".jpg", ctx.cacheDir)
        file.writeBytes(byteArrayOf(1, 2, 3, 4, 5))

        val worker = TestListenableWorkerBuilder<UploadWorker>(ctx)
            .setInputData(
                Data.Builder()
                    .putString("uri", android.net.Uri.fromFile(file).toString())
                    .putString("mime", "image/jpeg")
                    .putString("kind", "photo")
                    .build()
            )
            .setWorkerFactory(object : androidx.work.WorkerFactory() {
                override fun createWorker(
                    appContext: android.content.Context,
                    workerClassName: String,
                    workerParameters: androidx.work.WorkerParameters,
                ): androidx.work.ListenableWorker? = UploadWorker(
                    appContext,
                    workerParameters,
                    database = db,
                    tokenStore = TokenStore(appContext),
                    apiFactory = { _, _ -> fakeApi },
                )
            })
            .build()

        val result = worker.doWork()
        assertEquals(ListenableWorker.Result.success(), result)

        val row = db.uploadStateDao().findByUri(android.net.Uri.fromFile(file).toString())
        assertTrue(row?.state == "done")
    }

    private fun fakeApiReturningCreated(putUrl: String): ApiService = object : ApiService {
        override suspend fun signup(body: SignupRequest) = Response.error<TokenResponse>(500, emptyResponseBody())
        override suspend fun login(body: LoginRequest) = Response.error<TokenResponse>(500, emptyResponseBody())
        override suspend fun refresh(body: RefreshRequest) = Response.error<TokenResponse>(500, emptyResponseBody())
        override suspend fun logout(body: RefreshRequest) = Response.success(Unit)
        override suspend fun me() = Response.success(UserResponse("u1", "e", "n"))
        override suspend fun googleCallback(body: OAuthGoogleCallbackRequest) = Response.error<TokenResponse>(500, emptyResponseBody())
        override suspend fun precheck(body: PrecheckRequest) = Response.success(PrecheckResponse(false, putUrl))
        override suspend fun uploadUrl(body: UploadUrlRequest) = Response.success(UploadUrlResponse(putUrl))
        override suspend fun createAsset(body: CreateAssetRequest) = Response.success(AssetResponse("a1", "photo"))
        override suspend fun getAsset(id: String) = Response.success(AssetResponse(id, "photo"))
    }

    private fun emptyResponseBody() = okhttp3.ResponseBody.create(null, "")
}
