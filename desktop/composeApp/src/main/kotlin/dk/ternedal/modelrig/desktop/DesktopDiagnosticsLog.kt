package dk.ternedal.modelrig.desktop

import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption
import java.sql.SQLException
import java.time.Instant

/**
 * A local file for failures the panels deliberately do not show.
 *
 * #2451 and #2453 replaced `Throwable.message` in the conversation and preset
 * panels with fixed sentences, on the grounds that a SQLite path or a lock name
 * "belongs in the log, not in the panel". There was no log: the exception was
 * dropped, and a real database failure left nothing to debug with.
 *
 * **What is written, and what cannot be.** Per failure: the time, the operation
 * name, and for the exception and up to three causes its class name, its first
 * frames, and -- for a `java.sql.SQLException` -- the driver's numeric error
 * code and five-character SQLSTATE. Every one of those is produced by code.
 *
 * An exception's *message* is never written. A message is free text chosen by
 * whoever threw it: a driver can quote a value, the clipboard path of the copy
 * operation is not database code at all, and nothing guarantees that a
 * conversation title, a prompt or a token is not in it. The operation name is
 * restricted to `[a-z0-9._-]` for the same reason -- it is meant to be a
 * constant, and a caller that passes anything else gets it flattened.
 *
 * **Bounds.** The file never exceeds [maxBytes]: an entry is cut to that size in
 * UTF-8 bytes before it is written, and when the file would pass the limit it
 * becomes `<name>.1` (replacing the previous one) and a new file starts. The
 * file stays on this machine, next to the database.
 *
 * Recording never throws -- a log that can fail the operation it describes is
 * worse than no log.
 */
internal class DesktopDiagnosticsLog(
    private val file: File,
    private val maxBytes: Long = DEFAULT_MAX_BYTES,
    private val now: () -> Instant = Instant::now,
) {
    @Synchronized
    fun record(operation: String, error: Throwable) {
        runCatching {
            if (maxBytes <= 0) return
            val entry = boundedUtf8(format(now(), operation, error), maxBytes)
            file.parentFile?.mkdirs()
            if (file.exists() && file.length() + entry.size > maxBytes) {
                Files.move(
                    file.toPath(),
                    File(file.path + ".1").toPath(),
                    StandardCopyOption.REPLACE_EXISTING,
                )
            }
            Files.write(file.toPath(), entry, StandardOpenOption.CREATE, StandardOpenOption.APPEND)
        }
    }

    companion object {
        const val DEFAULT_MAX_BYTES: Long = 1_000_000
        const val MAX_OPERATION_CHARS = 64
        const val MAX_FRAMES = 8
        const val MAX_CAUSES = 3
        private val SQL_STATE = Regex("[0-9A-Z]{5}")
        private val NOT_OPERATION_CHAR = Regex("[^a-z0-9._-]")

        /** One line per fact, so the file can be read and grepped as it is. */
        internal fun format(at: Instant, operation: String, error: Throwable): String = buildString {
            append(at).append(" operation=").append(operationName(operation)).append('\n')
            var current: Throwable? = error
            var depth = 0
            val seen = HashSet<Throwable>()
            while (current != null && depth <= MAX_CAUSES && seen.add(current)) {
                append(if (depth == 0) "  error: " else "  cause: ")
                append(current.javaClass.name)
                append(sqlCodes(current))
                append('\n')
                if (depth == 0) {
                    current.stackTrace.take(MAX_FRAMES).forEach { append("    at ").append(frame(it)).append('\n') }
                }
                current = current.cause
                depth++
            }
        }

        /** The two structured values a JDBC driver attaches; both are validated, neither is free text. */
        private fun sqlCodes(error: Throwable): String {
            if (error !is SQLException) return ""
            val state = error.sqlState?.takeIf { SQL_STATE.matches(it) }
            return " code=${error.errorCode}" + (state?.let { " sqlState=$it" } ?: "")
        }

        /** Class, method, file and line as the JVM recorded them -- not `toString()`, which a frame cannot override but which also carries module and loader names. */
        private fun frame(element: StackTraceElement): String =
            "${element.className}.${element.methodName}(${element.fileName ?: "Unknown Source"}:${element.lineNumber})"

        internal fun operationName(operation: String): String =
            NOT_OPERATION_CHAR.replace(operation.lowercase(), "_").take(MAX_OPERATION_CHARS).ifEmpty { "unknown" }

        /** At most [maxBytes] bytes; when cut, never inside a UTF-8 sequence, and ending in a newline. */
        internal fun boundedUtf8(text: String, maxBytes: Long): ByteArray {
            val bytes = text.toByteArray(Charsets.UTF_8)
            if (bytes.size <= maxBytes) return bytes
            if (maxBytes <= 0) return ByteArray(0)
            // Keep one byte for the newline, then step back to the start of a character:
            // a byte of the form 10xxxxxx continues the character before it.
            var end = (maxBytes - 1).toInt()
            while (end > 0 && (bytes[end].toInt() and 0xC0) == 0x80) end--
            return bytes.copyOf(end) + '\n'.code.toByte()
        }

        fun defaultFile(): File = File(File(System.getProperty("user.home"), ".modelrig"), "desktop.log")
    }
}

/**
 * Opens the log on first use, inside the same guarantee as recording: if the
 * log cannot be opened (no home directory, say), the failure being recorded is
 * dropped and the caller never sees a second one. The next record tries again.
 */
internal class LazyDiagnostics(private val open: () -> DesktopDiagnosticsLog) {
    private var log: DesktopDiagnosticsLog? = null

    @Synchronized
    fun record(operation: String, error: Throwable) {
        runCatching { (log ?: open().also { log = it }).record(operation, error) }
    }
}

/** The process-wide log. */
internal object DesktopDiagnostics {
    private val sink = LazyDiagnostics { DesktopDiagnosticsLog(DesktopDiagnosticsLog.defaultFile()) }

    fun record(operation: String, error: Throwable) = sink.record(operation, error)
}
