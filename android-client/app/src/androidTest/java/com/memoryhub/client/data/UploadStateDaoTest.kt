package com.memoryhub.client.data

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class UploadStateDaoTest {
    private lateinit var db: MemoryHubDatabase
    private lateinit var dao: UploadStateDao

    @Before
    fun setUp() {
        db = MemoryHubDatabase.inMemory(ApplicationProvider.getApplicationContext())
        dao = db.uploadStateDao()
    }

    @After
    fun tearDown() {
        db.close()
    }

    @Test
    fun upsertAndFetch() = runBlocking {
        dao.upsert(UploadState(uri = "content://foo", size = 42, state = "queued"))
        val loaded = dao.findByUri("content://foo")
        assertNotNull(loaded)
        assertEquals("queued", loaded!!.state)
        assertEquals(1, dao.pending().size)
    }

    @Test
    fun updatingStateHidesFromPending() = runBlocking {
        dao.upsert(UploadState(uri = "content://foo", size = 42, state = "queued"))
        dao.upsert(UploadState(uri = "content://foo", size = 42, state = "done"))
        assertEquals(0, dao.pending().size)
        assertEquals(1, dao.all().size)
    }
}
