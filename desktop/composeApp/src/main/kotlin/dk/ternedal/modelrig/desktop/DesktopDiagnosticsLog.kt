package dk.ternedal.modelrig.desktop

import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.time.Instant

/**
 * A local file for failures the panels deliberately do not show.
 *
 * #2451 and #2453 replaced `Throwable.message` in the conversation and preset
 * panels with fixed sentences, on the grounds that a SQLite path or a lock name
 * "belongs in the log, not in the panel". There was no log: the exception was
 * dropped, and a real database failure left nothing to debug with.
 *
 * What is written, per failure: the time, the name of the operation that failed,
 * and the exception's class, message and first frames, with its causes. The
 * operation name is chosen by the caller in code. Nothing a user typed or
 * received is passed in, so no conversation text, prompt, token or pairing code
 * can reach the file through this API; an exception message is the one free
 * text, and for the store operations it is the database driver's.
 *
 * The file stays on this machine, next to the database. It is bounded: when it
 * would pass [maxBytes] it becomes `<name>.1`, replacing the previous one, and a
 * new file starts. Recording never throws -- a log that can fail the operation
 * it describes is worse than no log.
 */
internal class DesktopDiagnosticsLog(
    private val file: File,
    private val maxBytes: Long = DEFAULT_MAX_BYTES,
    private val now: () -> Instant = Instant::now,
) {
    @Synchronized
    fun record(operation: String, error: Throwable) {
        runCatching {
            val entry = format(now(), operation, error).toByteArray(Charsets.UTF_8)
            file.parentFile?.mkdirs()
            if (file.exists() && file.length() + entry.size > maxBytes) {
                Files.move(
                    file.toPath(),
                    File(file.path + ".1").toPath(),
                    StandardCopyOption.REPLACE_EXISTING,
                )
            }
            Files.write(
                file.toPath(),
                entry,
                java.nio.file.StandardOpenOption.CREATE,
                java.nio.file.StandardOpenOption.APPEND,
            )
        }
    }

    companion object {
        const val DEFAULT_MAX_BYTES: Long = 1_000_000
        const val MAX_MESSAGE_CHARS = 500
        const val MAX_FRAMES = 8
        const val MAX_CAUSES = 3

        /** One line per fact, so the file can be read and grepped as it is. */
        internal fun format(at: Instant, operation: String, error: Throwable): String = buildString {
            append(at).append(" operation=").append(oneLine(operation)).append('\n')
            var current: Throwable? = error
            var depth = 0
            val seen = HashSet<Throwable>()
            while (current != null && depth <= MAX_CAUSES && seen.add(current)) {
                append(if (depth == 0) "  error: " else "  cause: ")
                append(current.javaClass.name)
                current.message?.let { append(": ").append(oneLine(it).take(MAX_MESSAGE_CHARS)) }
                append('\n')
                if (depth == 0) {
                    current.stackTrace.take(MAX_FRAMES).forEach { append("    at ").append(it).append('\n') }
                }
                current = current.cause
                depth++
            }
        }

        private fun oneLine(text: String): String = text.replace(Regex("[\\r\\n\\t]+"), " ").trim()

        fun defaultFile(): File = File(File(System.getProperty("user.home"), ".modelrig"), "desktop.log")
    }
}

/** The process-wide log. One place to point somewhere else in a test. */
internal object DesktopDiagnostics {
    @Volatile
    var log: DesktopDiagnosticsLog = DesktopDiagnosticsLog(DesktopDiagnosticsLog.defaultFile())

    fun record(operation: String, error: Throwable) = log.record(operation, error)
}
