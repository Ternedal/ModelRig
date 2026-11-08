package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.MediaGalleryContract
import dk.ternedal.modelrig.net.MediaGalleryContractTest.Companion.image
import dk.ternedal.modelrig.net.MediaGalleryContractTest.Companion.video
import dk.ternedal.modelrig.net.MediaGalleryException.Reason
import dk.ternedal.modelrig.net.MediaPage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId

class MediaGalleryPresentationTest {
    private fun item(id: String) = MediaGalleryContract.parseItem(image(id))!!

    @Test
    fun `refresh replaces, load-more appends and drops ids already shown`() {
        var state = MediaGalleryPaging.refreshed(MediaPage(listOf(item("a"), item("b")), "c1", skipped = 1))
        assertTrue(state.canLoadMore)
        state = MediaGalleryPaging.startLoadMore(state)
        assertFalse(state.canLoadMore)
        state = MediaGalleryPaging.appended(state, MediaPage(listOf(item("b"), item("c")), null, skipped = 2))
        assertEquals(listOf("a", "b", "c"), state.items.map { it.id })
        assertEquals(3, state.skipped)
        assertTrue(state.endReached)
        assertFalse(state.canLoadMore)
        state = MediaGalleryPaging.refreshed(MediaPage(listOf(item("z")), null, skipped = 0))
        assertEquals(listOf("z"), state.items.map { it.id })
        assertEquals(0, state.skipped)
    }

    @Test
    fun `a failed page keeps what is shown and blocks paging until retried`() {
        val loaded = MediaGalleryPaging.refreshed(MediaPage(listOf(item("a")), "c1", 0))
        val failed = MediaGalleryPaging.failed(MediaGalleryPaging.startLoadMore(loaded), Reason.NETWORK)
        assertEquals(listOf("a"), failed.items.map { it.id })
        assertEquals("c1", failed.nextCursor)
        assertFalse(failed.canLoadMore)
        assertEquals(Reason.NETWORK, failed.error)
    }

    @Test
    fun `empty only after a successful first page`() {
        assertFalse(MediaGalleryState().isEmpty)
        assertTrue(MediaGalleryPaging.refreshed(MediaPage(emptyList(), null, 0)).isEmpty)
        assertFalse(MediaGalleryPaging.failed(MediaGalleryState(), Reason.NETWORK).isEmpty)
    }

    @Test
    fun `a page of only invalid items with a cursor is not the end`() {
        // Review 5684792570: later valid pages must stay reachable.
        val state = MediaGalleryPaging.refreshed(MediaPage(emptyList(), "c1", skipped = 2))
        assertFalse(state.isEmpty)
        assertTrue(state.canLoadMore)
        assertEquals(2, state.skipped)
    }

    @Test
    fun `only transient failures are retryable`() {
        val retryable = Reason.entries.filter(::isRetryable).toSet()
        assertEquals(setOf(Reason.NETWORK, Reason.HTTP, Reason.STORAGE_UNAVAILABLE), retryable)
    }

    @Test
    fun `every reason has its own danish text without server detail`() {
        val texts = Reason.entries.map(::mediaGalleryMessage)
        assertEquals(texts.size, texts.toSet().size)
        assertTrue(texts.none { it.isBlank() })
    }

    @Test
    fun `formatting helpers`() {
        assertNull(skippedMessage(0))
        assertEquals("1 medie kunne ikke vises.", skippedMessage(1))
        assertEquals("3 medier kunne ikke vises.", skippedMessage(3))
        assertEquals("1:05", mediaDuration(65.5))
        assertEquals("1:02:03", mediaDuration(3723.0))
        assertNull(mediaDuration(null))
        assertEquals("999 B", mediaSize(999))
        assertEquals("1,2 MB", mediaSize(1_234_567))
        assertEquals("28. okt. 2026, 13:00", mediaCreated(item("a"), ZoneId.of("Europe/Copenhagen")))
        assertNull(mediaLayoutNote(item("flat")))
        val vr = MediaGalleryContract.parseItem(video("vr"))!!
        assertEquals("Vises fladt: equirectangular 360, top bottom.", mediaLayoutNote(vr))
        assertEquals("Video", mediaKindLabel(vr))
    }
}
