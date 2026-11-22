package dk.ternedal.modelrig.ui.chat

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import org.junit.Assert.assertEquals
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
import org.robolectric.annotation.GraphicsMode
import java.io.ByteArrayOutputStream

/**
 * #2419: save/share of a generated picture. The pure parts (format sniffing, file
 * name) and the share path (file under the FileProvider dir, chooser intent with a
 * read grant, pruning) are checked here; the MediaStore insert is exercised only
 * for its refusal paths, since Robolectric has no gallery provider to accept it.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [35])
class ImageExportTest {
    private lateinit var context: Context
    private val jobId = "0123456789abcdef0123456789abcdef"

    @Before
    fun setUp() {
        context = RuntimeEnvironment.getApplication()
        context.getExternalFilesDir(null)?.listFiles()?.forEach { it.delete() }
    }

    private fun png(): ByteArray {
        val bmp = Bitmap.createBitmap(8, 8, Bitmap.Config.ARGB_8888)
        return ByteArrayOutputStream().also { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
    }

    private fun jpeg(): ByteArray {
        val bmp = Bitmap.createBitmap(8, 8, Bitmap.Config.ARGB_8888)
        return ByteArrayOutputStream().also { bmp.compress(Bitmap.CompressFormat.JPEG, 90, it) }.toByteArray()
    }

    @Test
    fun `format is read from the bytes, never assumed`() {
        assertEquals("image/png", ImageExport.mimeOf(png()))
        assertEquals("image/jpeg", ImageExport.mimeOf(jpeg()))
        assertNull(ImageExport.mimeOf("not an image".toByteArray()))
        assertNull(ImageExport.mimeOf(ByteArray(0)))
    }

    @Test
    fun `file name carries job prefix and timestamp, no prompt text`() {
        val name = ImageExport.fileName(jobId, "image/png", nowMillis = 0L)
        assertTrue(name, name.startsWith("kaliv-01234567-"))
        assertTrue(name, name.endsWith(".png"))
        assertEquals("jpg", ImageExport.extensionOf("image/jpeg"))
    }

    @Test
    fun `share writes one copy under the FileProvider dir and starts a chooser with a read grant`() {
        val ok = ImageExport.share(context, png(), jobId)
        assertTrue(ok)
        val files = context.getExternalFilesDir(null)!!.listFiles()!!.filter { it.name.startsWith("kaliv-billede-") }
        assertEquals(1, files.size)
        val started = shadowOf(RuntimeEnvironment.getApplication()).nextStartedActivity
        assertNotNull(started)
        assertEquals(Intent.ACTION_CHOOSER, started.action)
        val inner = started.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)!!
        assertEquals(Intent.ACTION_SEND, inner.action)
        assertEquals("image/png", inner.type)
        assertTrue(inner.flags and Intent.FLAG_GRANT_READ_URI_PERMISSION != 0)
        val uri = inner.getParcelableExtra<android.net.Uri>(Intent.EXTRA_STREAM)!!
        assertEquals("content", uri.scheme)
        assertEquals(context.packageName + ".fileprovider", uri.authority)
    }

    @Test
    fun `share refuses bytes that are not an image`() {
        assertEquals(false, ImageExport.share(context, "nope".toByteArray(), jobId))
        assertNull(shadowOf(RuntimeEnvironment.getApplication()).nextStartedActivity)
    }

    @Test
    fun `old share copies are pruned, newest kept`() {
        repeat(8) { i ->
            val f = ImageExport.shareFile(context, png(), jobId, nowMillis = 1_000L * (i + 1))!!
            f.setLastModified(1_000L * (i + 1))
        }
        ImageExport.pruneShareFiles(context, keep = 3)
        val left = context.getExternalFilesDir(null)!!.listFiles()!!.filter { it.name.startsWith("kaliv-billede-") }
        assertEquals(3, left.size)
    }

    @Test
    fun `save refuses an unknown format before touching MediaStore`() {
        val r = ImageExport.saveToGallery(context, "nope".toByteArray(), jobId)
        assertTrue(r is ImageExport.SaveResult.Refused)
    }
}
