package dk.ternedal.modelrig.ui.chat

import android.content.Context
import android.content.Intent
import dk.ternedal.modelrig.net.MediaGalleryException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.io.IOException
import java.io.OutputStream

/**
 * Save/share of a generated clip. The clip is streamed by a `copy` the caller
 * supplies, so what is checked here is the contract around it: the file name,
 * that the share copy is exactly what `copy` wrote and lands under the
 * FileProvider dir, that a failing copy leaves no file and starts no chooser,
 * the chooser intent (video/mp4, read grant, our authority), pruning, and the
 * words for a failed copy. MediaStore itself has no provider under Robolectric,
 * so save is exercised for its refusal path only, as [ImageExportTest] does.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class VideoExportTest {
    private lateinit var context: Context
    private val jobId = "0123456789abcdef0123456789abcdef"
    private val clip = ByteArray(4096) { (it % 251).toByte() }

    @Before
    fun setUp() {
        context = RuntimeEnvironment.getApplication()
        context.getExternalFilesDir(null)?.listFiles()?.forEach { it.delete() }
    }

    private fun writes(bytes: ByteArray): (OutputStream) -> Unit = { it.write(bytes) }

    private fun shareFiles() = context.getExternalFilesDir(null)!!.listFiles()!!.filter { it.name.startsWith("kaliv-video-") }

    @Test
    fun `file name carries job prefix, timestamp and mp4, no prompt text`() {
        val name = VideoExport.fileName(jobId, nowMillis = 0L)
        assertTrue(name, name.startsWith("kaliv-01234567-"))
        assertTrue(name, name.endsWith(".mp4"))
        assertEquals("kaliv-01234567-19700101-000000.mp4", name)
    }

    @Test
    fun `share writes exactly the streamed bytes under the FileProvider dir and starts a chooser with a read grant`() {
        assertTrue(VideoExport.share(context, jobId, writes(clip)))
        val files = shareFiles()
        assertEquals(1, files.size)
        assertTrue(clip.contentEquals(files.single().readBytes()))
        val started = shadowOf(RuntimeEnvironment.getApplication()).nextStartedActivity
        assertNotNull(started)
        assertEquals(Intent.ACTION_CHOOSER, started.action)
        val inner = started.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)!!
        assertEquals(Intent.ACTION_SEND, inner.action)
        assertEquals("video/mp4", inner.type)
        assertTrue(inner.flags and Intent.FLAG_GRANT_READ_URI_PERMISSION != 0)
        val uri = inner.getParcelableExtra<android.net.Uri>(Intent.EXTRA_STREAM)!!
        assertEquals("content", uri.scheme)
        assertEquals(context.packageName + ".fileprovider", uri.authority)
    }

    @Test
    fun `a copy that fails midway leaves no share file and starts nothing`() {
        val failing: (OutputStream) -> Unit = { out ->
            out.write(clip, 0, 100)
            throw MediaGalleryException(MediaGalleryException.Reason.NETWORK, "Forbindelsen til riggen blev afbrudt")
        }
        assertFalse(VideoExport.share(context, jobId, failing))
        assertTrue(shareFiles().isEmpty())
        assertNull(shadowOf(RuntimeEnvironment.getApplication()).nextStartedActivity)
        assertNull(VideoExport.shareFile(context, jobId, failing))
    }

    @Test
    fun `old share copies are pruned, newest kept`() {
        repeat(6) { i ->
            val f = VideoExport.shareFile(context, jobId, writes(clip), nowMillis = 1_000L * (i + 1))!!
            f.setLastModified(1_000L * (i + 1))
        }
        VideoExport.pruneShareFiles(context, keep = 3)
        val left = shareFiles()
        assertEquals(3, left.size)
        assertTrue(left.all { it.lastModified() >= 4_000L })
    }

    @Test
    fun `save without a gallery provider is refused, never reported as saved`() {
        val r = VideoExport.saveToGallery(context, jobId, writes(clip))
        assertTrue(r is VideoExport.SaveResult.Refused)
    }

    @Test
    fun `a failed copy is reported in the gallery's words when it has them`() {
        assertEquals(
            "For stort til at blive vist på telefonen",
            VideoExport.copyFailureText(MediaGalleryException(MediaGalleryException.Reason.TOO_LARGE, "For stort til at blive vist på telefonen")),
        )
        assertEquals("Videoen kunne ikke hentes fra riggen", VideoExport.copyFailureText(IOException("boom")))
        assertEquals("Videoen kunne ikke hentes fra riggen", VideoExport.copyFailureText(null))
    }
}
