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
    fun aFailureIsWrittenWithItsTimeOperationClassesFramesAndSqlCodes() {
        val dir = tempDir()
        val error = IllegalStateException("database is locked", java.sql.SQLException("[SQLITE_BUSY] locked", "HY000", 5))
        logIn(dir).record("conversation.load", error)
        val text = File(dir, "desktop.log").readText()
        assertTrue(text.startsWith("2026-11-26T09:00:00Z operation=conversation.load\n"), text)
        assertTrue("  error: java.lang.IllegalStateException\n" in text, text)
        assertTrue("  cause: java.sql.SQLException code=5 sqlState=HY000\n" in text, text)
        val frames = text.lines().filter { it.startsWith("    at ") }
        assertTrue(frames.isNotEmpty() && frames.size <= DesktopDiagnosticsLog.MAX_FRAMES, text)
        assertTrue(frames.first().contains("DesktopDiagnosticsLogTest"), "the first frame says where it was thrown")
    }

    @Test
    fun noExceptionMessageReachesTheFile() {
        // The review's case: whatever a thrower puts in a message -- a prompt, a
        // conversation title, a token -- must not be written, at any depth.
        val prompt = "skriv et digt om min eks Sofie"
        val title = "Samtale: lønforhandling 2026"
        val token = "mr_live_7f3c9a1e55d04b6d"
        val pairing = "481-205"
        val driver = java.sql.SQLException("near \"$title\": syntax error in INSERT VALUES ('$prompt')", "Bearer $token", 1)
        val clipboard = IllegalStateException("cannot open clipboard while copying '$prompt'", driver)
        val outer = RuntimeException("copy failed for $title with $token and code $pairing", clipboard)
        val dir = tempDir()
        logIn(dir).record("conversation.copy", outer)
        val text = File(dir, "desktop.log").readText()
        for (secret in listOf(prompt, title, token, pairing, "Sofie", "lønforhandling", "syntax error", "Bearer", "clipboard while")) {
            assertFalse(secret in text, "'$secret' was written:\n$text")
        }
        assertTrue("  error: java.lang.RuntimeException\n" in text, text)
        assertTrue("  cause: java.lang.IllegalStateException\n" in text, text)
        assertTrue("  cause: java.sql.SQLException code=1\n" in text, "an SQLSTATE that is not five [0-9A-Z] is dropped, the code kept:\n$text")
    }

    @Test
    fun anExceptionClassCannotSmuggleTextThroughToStringOrLocalizedMessage() {
        class Loud : RuntimeException("hemmelig besked") {
            override fun toString() = "hemmelig toString"
            override fun getLocalizedMessage() = "hemmelig lokaliseret"
        }
        val text = DesktopDiagnosticsLog.format(at, "preset.save", Loud())
        assertFalse("hemmelig" in text, text)
        assertTrue("Loud" in text.lines()[1], text)
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
    fun theOperationNameIsFlattenedToAFixedAlphabetAndCannotForgeALine() {
        assertEquals("conversation.load", DesktopDiagnosticsLog.operationName("conversation.load"))
        assertEquals("preset.save", DesktopDiagnosticsLog.operationName("PRESET.SAVE"))
        assertEquals("a_b_c", DesktopDiagnosticsLog.operationName("a\nb c"))
        assertEquals("unknown", DesktopDiagnosticsLog.operationName(""))
        assertEquals(DesktopDiagnosticsLog.MAX_OPERATION_CHARS, DesktopDiagnosticsLog.operationName("x".repeat(500)).length)
        val forged = "load\n2026-01-01T00:00:00Z operation=forged min hemmelige titel"
        val text = DesktopDiagnosticsLog.format(at, forged, RuntimeException("x"))
        assertEquals(1, text.lines().count { " operation=" in it }, text)
        assertFalse(" " in text.lines().first().substringAfter("operation="), text)
    }

    @Test
    fun aSingleEntryLargerThanTheLimitIsCutInANewFile() {
        val dir = tempDir()
        val log = logIn(dir, maxBytes = 120)
        log.record("conversation.load", RuntimeException("x"))
        val current = File(dir, "desktop.log")
        assertTrue(current.length() in 1..120, "one oversized entry wrote ${current.length()} bytes with a 120-byte limit")
        assertTrue(current.readText().startsWith("2026-11-26T09:00:00Z operation=conversation.load\n"))
        assertTrue(current.readText().endsWith("\n"))
        assertEquals(listOf("desktop.log"), dir.list()!!.toList())
    }

    @Test
    fun aSingleEntryLargerThanTheLimitIsCutWhenItRotates() {
        val dir = tempDir()
        val log = logIn(dir, maxBytes = 120)
        repeat(3) { log.record("preset.save", RuntimeException("x")) }
        val current = File(dir, "desktop.log")
        val previous = File(dir, "desktop.log.1")
        assertTrue(current.length() in 1..120, "current is ${current.length()} bytes")
        assertTrue(previous.exists() && previous.length() in 1..120, "previous is ${previous.length()} bytes")
        assertEquals(setOf("desktop.log", "desktop.log.1"), dir.list()!!.toSet())
    }

    @Test
    fun theByteLimitIsOnUtf8BytesAndNeverSplitsACharacter() {
        val text = "æøå".repeat(40) // two bytes each
        for (limit in 1L..30L) {
            val bytes = DesktopDiagnosticsLog.boundedUtf8(text, limit)
            assertTrue(bytes.size <= limit, "limit $limit gave ${bytes.size} bytes")
            assertFalse('\uFFFD' in String(bytes, Charsets.UTF_8), "limit $limit split a character")
        }
        assertEquals(text, String(DesktopDiagnosticsLog.boundedUtf8(text, 10_000), Charsets.UTF_8))
        val dir = tempDir()
        logIn(dir, maxBytes = 0).record("preset.load", RuntimeException("x"))
        assertFalse(File(dir, "desktop.log").exists(), "a zero limit writes nothing")
    }

    @Test
    fun openingTheLogIsInsideTheNeverThrowsGuaranteeAndIsRetried() {
        var attempts = 0
        val dir = tempDir()
        val diagnostics = LazyDiagnostics {
            attempts++
            if (attempts == 1) error("no home directory") else logIn(dir)
        }
        diagnostics.record("conversation.load", RuntimeException("first is lost"))
        assertFalse(File(dir, "desktop.log").exists())
        diagnostics.record("conversation.load", RuntimeException("second is written"))
        diagnostics.record("conversation.load", RuntimeException("third reuses the log"))
        assertEquals(2, attempts)
        assertEquals(2, File(dir, "desktop.log").readLines().count { " operation=" in it })
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
        val kept = (previous.readText() + current.readText()).lines().count { " operation=" in it }
        assertTrue(kept in 1 until 60, "the oldest of 60 entries are gone, the newest are kept: $kept")
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
        // (the helpers pass the Throwable on; what the log keeps of it is tested above)

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
