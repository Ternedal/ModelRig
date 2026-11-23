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

/**
 * #2419: save a generated picture to the phone's gallery, or hand it to another
 * app. Both work on the bytes the bubble already fetched -- no second request to
 * the rig, nothing uploaded anywhere by this code.
 *
 * Save goes through MediaStore into `Pictures/Kaliv` (API 29+, scoped storage;
 * no storage permission needed). Share writes a copy under the app's external
 * files dir -- the one directory `kaliv_file_paths.xml` exposes through the
 * existing FileProvider -- and starts a chooser with a read grant on that URI
 * only. The share copy is the user's choice to send; what the receiving app does
 * with it is theirs.
 */
object ImageExport {
    const val ALBUM = "Kaliv"
    private const val SHARE_PREFIX = "kaliv-billede-"

    /** PNG or JPEG by magic bytes; anything else is refused rather than mislabelled. */
    fun mimeOf(bytes: ByteArray): String? = when {
        bytes.size >= 8 && bytes[0] == 0x89.toByte() && bytes[1] == 0x50.toByte() &&
            bytes[2] == 0x4E.toByte() && bytes[3] == 0x47.toByte() -> "image/png"
        bytes.size >= 3 && bytes[0] == 0xFF.toByte() && bytes[1] == 0xD8.toByte() && bytes[2] == 0xFF.toByte() -> "image/jpeg"
        else -> null
    }

    fun extensionOf(mime: String): String = if (mime == "image/jpeg") "jpg" else "png"

    /** `kaliv-<jobid-prefix>-<yyyyMMdd-HHmmss>.<ext>`: sortable, no prompt text, no PII. */
    fun fileName(jobId: String, mime: String, nowMillis: Long = System.currentTimeMillis()): String {
        val stamp = java.text.SimpleDateFormat("yyyyMMdd-HHmmss", java.util.Locale.ROOT).format(java.util.Date(nowMillis))
        return "kaliv-${jobId.take(8)}-$stamp.${extensionOf(mime)}"
    }

    sealed class SaveResult {
        data class Saved(val uri: Uri) : SaveResult()
        data class Refused(val reason: String) : SaveResult()
    }

    /** Insert into the gallery album. Pending until the bytes are written, so a half-written row never shows. */
    fun saveToGallery(context: Context, bytes: ByteArray, jobId: String): SaveResult {
        val mime = mimeOf(bytes) ?: return SaveResult.Refused("Ukendt billedformat")
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return SaveResult.Refused("Kræver Android 10 eller nyere")
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, fileName(jobId, mime))
            put(MediaStore.Images.Media.MIME_TYPE, mime)
            put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/" + ALBUM)
            put(MediaStore.Images.Media.IS_PENDING, 1)
        }
        val uri = runCatching { resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values) }.getOrNull()
            ?: return SaveResult.Refused("Galleriet afviste billedet")
        val written = runCatching {
            resolver.openOutputStream(uri)?.use { it.write(bytes) } ?: error("no stream")
        }.isSuccess
        if (!written) {
            runCatching { resolver.delete(uri, null, null) }
            return SaveResult.Refused("Billedet kunne ikke skrives til galleriet")
        }
        runCatching {
            resolver.update(uri, ContentValues().apply { put(MediaStore.Images.Media.IS_PENDING, 0) }, null, null)
        }
        return SaveResult.Saved(uri)
    }

    /** The share copy on disk, inside the FileProvider-exposed directory. */
    fun shareFile(context: Context, bytes: ByteArray, jobId: String, nowMillis: Long = System.currentTimeMillis()): File? {
        val mime = mimeOf(bytes) ?: return null
        val dir = context.getExternalFilesDir(null) ?: return null
        val file = File(dir, SHARE_PREFIX + fileName(jobId, mime, nowMillis))
        return runCatching { file.writeBytes(bytes); file }.getOrNull()
    }

    /** Older share copies, so the app's own files dir does not grow with every share. */
    fun pruneShareFiles(context: Context, keep: Int = 5) {
        val dir = context.getExternalFilesDir(null) ?: return
        dir.listFiles { f -> f.isFile && f.name.startsWith(SHARE_PREFIX) }
            ?.sortedByDescending { it.lastModified() }
            ?.drop(keep)
            ?.forEach { runCatching { it.delete() } }
    }

    fun shareIntent(context: Context, file: File, mime: String): Intent {
        val uri = FileProvider.getUriForFile(context, context.packageName + ".fileprovider", file)
        val send = Intent(Intent.ACTION_SEND).apply {
            type = mime
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        return Intent.createChooser(send, "Del billede").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }

    /** Write the copy, prune, start the chooser. False when there was nothing shareable. */
    fun share(context: Context, bytes: ByteArray, jobId: String): Boolean {
        val mime = mimeOf(bytes) ?: return false
        val file = shareFile(context, bytes, jobId) ?: return false
        pruneShareFiles(context)
        return runCatching { context.startActivity(shareIntent(context, file, mime)) }.isSuccess
    }
}
