package dk.ternedal.modelrig.ui.chat

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.core.content.FileProvider
import java.io.File
import java.io.OutputStream

/**
 * The video twin of [ImageExport]: save a generated clip to the phone's gallery
 * (`Movies/Kaliv`) or hand a copy to another app.
 *
 * Unlike a picture, the clip is not in memory -- the bubble streams it. So both
 * paths take a `copy: (OutputStream) -> Unit` that the caller backs with the
 * gallery client's bounded download ([dk.ternedal.modelrig.net.MediaGallerySource.videoInto]);
 * the bytes go straight from the rig into the MediaStore row or the share file,
 * never into a heap buffer. A failed copy leaves nothing behind: the pending
 * MediaStore row is deleted, the half-written share file removed.
 */
object VideoExport {
    const val ALBUM = ImageExport.ALBUM
    const val MIME = "video/mp4"
    private const val SHARE_PREFIX = "kaliv-video-"

    /** `kaliv-<jobid-prefix>-<yyyyMMdd-HHmmss>.mp4`: sortable, no prompt text, no PII. */
    fun fileName(jobId: String, nowMillis: Long = System.currentTimeMillis()): String {
        val stamp = java.text.SimpleDateFormat("yyyyMMdd-HHmmss", java.util.Locale.ROOT).format(java.util.Date(nowMillis))
        return "kaliv-${jobId.take(8)}-$stamp.mp4"
    }

    sealed class SaveResult {
        data class Saved(val uri: Uri) : SaveResult()
        data class Refused(val reason: String) : SaveResult()
    }

    /** Insert into the gallery album; pending until [copy] has written the whole clip, so a half clip never shows. */
    fun saveToGallery(context: Context, jobId: String, copy: (OutputStream) -> Unit): SaveResult {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return SaveResult.Refused("Kræver Android 10 eller nyere")
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Video.Media.DISPLAY_NAME, fileName(jobId))
            put(MediaStore.Video.Media.MIME_TYPE, MIME)
            put(MediaStore.Video.Media.RELATIVE_PATH, Environment.DIRECTORY_MOVIES + "/" + ALBUM)
            put(MediaStore.Video.Media.IS_PENDING, 1)
        }
        val uri = runCatching { resolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values) }.getOrNull()
            ?: return SaveResult.Refused("Galleriet afviste videoen")
        val written = runCatching {
            resolver.openOutputStream(uri)?.use(copy) ?: error("no stream")
        }
        if (written.isFailure) {
            runCatching { resolver.delete(uri, null, null) }
            return SaveResult.Refused(copyFailureText(written.exceptionOrNull()))
        }
        runCatching {
            resolver.update(uri, ContentValues().apply { put(MediaStore.Video.Media.IS_PENDING, 0) }, null, null)
        }
        return SaveResult.Saved(uri)
    }

    /** The share copy on disk, inside the FileProvider-exposed directory; null (and no file) when the copy failed. */
    fun shareFile(context: Context, jobId: String, copy: (OutputStream) -> Unit, nowMillis: Long = System.currentTimeMillis()): File? {
        val dir = context.getExternalFilesDir(null) ?: return null
        val file = File(dir, SHARE_PREFIX + fileName(jobId, nowMillis))
        val result = runCatching { file.outputStream().use(copy) }
        if (result.isFailure) {
            runCatching { file.delete() }
            return null
        }
        return file
    }

    /** Older share copies, so the app's own files dir does not grow with every share. */
    fun pruneShareFiles(context: Context, keep: Int = 3) {
        val dir = context.getExternalFilesDir(null) ?: return
        dir.listFiles { f -> f.isFile && f.name.startsWith(SHARE_PREFIX) }
            ?.sortedByDescending { it.lastModified() }
            ?.drop(keep)
            ?.forEach { runCatching { it.delete() } }
    }

    fun shareIntent(context: Context, file: File): Intent {
        val uri = FileProvider.getUriForFile(context, context.packageName + ".fileprovider", file)
        val send = Intent(Intent.ACTION_SEND).apply {
            type = MIME
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        return Intent.createChooser(send, "Del video").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }

    /** Write the copy, prune, start the chooser. False when there was nothing shareable. */
    fun share(context: Context, jobId: String, copy: (OutputStream) -> Unit): Boolean {
        val file = shareFile(context, jobId, copy) ?: return false
        pruneShareFiles(context)
        return runCatching { context.startActivity(shareIntent(context, file)) }.isSuccess
    }

    /** The gallery's own words when it refused; otherwise one neutral line. */
    fun copyFailureText(error: Throwable?): String =
        (error as? dk.ternedal.modelrig.net.MediaGalleryException)?.message ?: "Videoen kunne ikke hentes fra riggen"
}
