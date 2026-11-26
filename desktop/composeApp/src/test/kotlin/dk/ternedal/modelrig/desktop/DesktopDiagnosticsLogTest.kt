package dk.ternedal.modelrig.desktop

import java.io.File
import java.nio.file.Files
import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class DesktopDiagnosticsLogTest {
    private val at = Instant.parse("2026-11-26T09:00:00Z")
    private fun tempDir(): File = Files.createTempDirectory("kaliv-diag").toFile().also { it.deleteOnExit() }
    private fun logIn(dir: File, maxBytes: Long = DesktopDiagnosticsLog.DEFAULT_MAX_BYTES) =
        DesktopDiagnosticsLog(File(dir, "desktop.log"), maxBytes) { at }

    @Test
    fun aFailureIsWrittenWithItsTimeOperationClassMessageAndCause() {
        val dir = tempDir()
        val error = IllegalStateException("database is locked", java.sql.SQLException("SQLITE_BUSY"))
        logIn(dir).record("conversation.load", error)
        val text = File(dir, "desktop.log").readText()
        assertTrue(text.startsWith("2026-11-26T09:00:00Z operation=conversation.load\n"), text)
        assertTrue("  error: java.lang.IllegalStateException: database is locked\n" in text, text)
        assertTrue("  cause: java.sql.SQLException: SQLITE_BUSY\n" in text, text)
        assertTrue("    at " in text, "the first frames say where it was thrown")
        assertTrue(text.lines().count { it.startsWith("    at ") } <= DesktopDiagnosticsLog.MAX_FRAMES)
    }

    @Test
    fun entriesAreAppendedInOrder() {
        val dir = tempDir()
        val log = logIn(dir)
        log.record("preset.save", RuntimeException("first"))
        log.record("preset.delete", RuntimeException("second"))
        val text = File(dir, "desktop.log").readText()
        assertTrue(text.indexOf("operation=preset.save") in 0 until text.indexOf("operation=preset.delete"), text)
    }

    @Test
    fun aMessageCannotForgeALineAndIsCutAtItsLimit() {
        val forged = "boom\n2026-01-01T00:00:00Z operation=forged\r\n\tmore"
        val text = DesktopDiagnosticsLog.format(at, "preset.load", RuntimeException(forged + "x".repeat(2000)))
        assertEquals(1, text.lines().count { " operation=" in it && !it.startsWith("  ") }, text)
        val errorLine = text.lines().first { it.startsWith("  error: ") }
        assertTrue(errorLine.length <= "  error: java.lang.RuntimeException: ".length + DesktopDiagnosticsLog.MAX_MESSAGE_CHARS)
        val operation = DesktopDiagnosticsLog.format(at, "a\nb", RuntimeException("x")).lines().first()
        assertEquals("2026-11-26T09:00:00Z operation=a b", operation)
    }

    @Test
    fun aCauseChainIsBoundedAndACycleEnds() {
        var deep: Throwable = RuntimeException("level 0")
        repeat(10) { deep = RuntimeException("level ${it + 1}", deep) }
        val text = DesktopDiagnosticsLog.format(at, "conversation.delete", deep)
        assertEquals(DesktopDiagnosticsLog.MAX_CAUSES, text.lines().count { it.startsWith("  cause: ") })
        val a = RuntimeException("a")
        val b = RuntimeException("b", a)
        a.initCause(b)
        assertTrue(DesktopDiagnosticsLog.format(at, "conversation.copy", a).isNotEmpty(), "a cyclic cause chain terminates")
    }

    @Test
    fun theFileIsBoundedAndKeepsExactlyOnePredecessor() {
        val dir = tempDir()
        val log = logIn(dir, maxBytes = 2_000)
        repeat(60) { log.record("conversation.load", RuntimeException("failure number $it")) }
        val current = File(dir, "desktop.log")
        val previous = File(dir, "desktop.log.1")
        assertTrue(current.length() <= 2_000, "current file is ${current.length()} bytes")
        assertTrue(previous.exists() && previous.length() <= 2_000)
        assertEquals(setOf("desktop.log", "desktop.log.1"), dir.list()!!.toSet())
        assertTrue("failure number 59" in current.readText(), "the newest entry is in the current file")
        assertFalse("failure number 0\n" in current.readText() + previous.readText(), "the oldest entries are gone")
    }

    @Test
    fun recordingNeverThrowsEvenWhenTheFileCannotBeWritten() {
        val dir = tempDir()
        val blocker = File(dir, "not-a-directory").apply { writeText("x") }
        DesktopDiagnosticsLog(File(blocker, "desktop.log")) { at }.record("preset.save", RuntimeException("x"))
        assertEquals(listOf("not-a-directory"), dir.list()!!.toList())
    }

    @Test
    fun aMissingDirectoryIsCreated() {
        val dir = File(tempDir(), "nested/.modelrig")
        DesktopDiagnosticsLog(File(dir, "desktop.log")) { at }.record("preset.load", RuntimeException("x"))
        assertTrue(File(dir, "desktop.log").exists())
    }

    @Test
    fun theDefaultFileSitsBesideTheDatabase() {
        // The directory DesktopChatDb.defaultDbPath() uses; named here rather than called,
        // because that function creates the directory in the real home.
        assertEquals(File(System.getProperty("user.home"), ".modelrig"), DesktopDiagnosticsLog.defaultFile().parentFile)
        assertEquals("desktop.log", DesktopDiagnosticsLog.defaultFile().name)
    }

    @Test
    fun operationNamesAreFixedByTheCodeNotByContent() {
        assertEquals(
            listOf("conversation.load", "conversation.rename", "conversation.copy", "conversation.delete"),
            ConversationStoreOperation.entries.map { it.diagnosticName },
        )
        assertEquals(listOf("preset.load", "preset.save", "preset.delete"), PresetStoreOperation.entries.map { it.diagnosticName })
    }

    @Test
    fun theStoreHelpersHandTheirFailuresToTheCallerAndOnlyTheirFailures() {
        val seen = mutableListOf<String>()
        val record = { operation: PresetStoreOperation, error: Throwable -> seen += "${operation.diagnosticName}:${error.message}"; Unit }

        mutatePresetsThenReload(PresetStoreOperation.SAVE, { error("disk full") }, { emptyList() }, record)
        mutatePresetsThenReload(PresetStoreOperation.DELETE, {}, { error("locked") }, record)
        mutatePresetsThenReload(PresetStoreOperation.SAVE, {}, { emptyList() }, record)
        assertEquals(listOf("preset.save:disk full", "preset.load:locked"), seen)

        val loads = mutableListOf<String?>()
        assertEquals(ConversationListState.Failed, loadConversationList({ loads += it.message }) { error("corrupt") })
        assertEquals(ConversationListState.Loaded(emptyList()), loadConversationList({ loads += it.message }) { emptyList() })
        assertEquals(listOf<String?>("corrupt"), loads)
    }
}
