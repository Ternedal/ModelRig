package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.net.DesktopMediaException
import dk.ternedal.modelrig.desktop.net.DesktopMediaException.Reason
import dk.ternedal.modelrig.desktop.net.DesktopMediaJob
import dk.ternedal.modelrig.desktop.net.DesktopMediaJobState
import dk.ternedal.modelrig.desktop.net.DesktopMediaKind
import java.io.IOException
import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The rules of the desktop media bubble (#2419), without a window or a rig:
 * polling and backoff, what ends a job and what only pauses it, the words, the
 * viewer's zoom and pan bounds, and all-or-nothing saving.
 */
class KalivMediaJobPresentationTest {
    private val id = "0123456789abcdef0123456789abcdef"

    private fun job(state: DesktopMediaJobState, assetId: String? = null, error: String? = null, cancel: Boolean = false) =
        DesktopMediaJob(id, state, assetId, error, cancel)

    private fun failure(reason: Reason, message: String = "x") = DesktopMediaException(reason, message)

    @Test
    fun pollingBacksOffPerFailureInARowAndIsCapped() {
        val waits = (0..7).map { KalivMediaJob.delayMillis(DesktopMediaPhase.Following(null, it)) }
        assertEquals(listOf(2_000L, 4_000L, 8_000L, 16_000L, 30_000L, 30_000L, 30_000L, 30_000L), waits)
        assertEquals(2_000L, KalivMediaJob.delayMillis(DesktopMediaPhase.Ended("x")))
        assertEquals(5L, KalivMediaJob.delayMillis(KalivMediaJob.initial(), base = 5))
        // A huge failure count neither overflows nor goes below the base.
        assertEquals(30_000L, KalivMediaJob.delayMillis(DesktopMediaPhase.Following(null, 1_000)))
        assertEquals(60_000L, KalivMediaJob.delayMillis(DesktopMediaPhase.Following(null, 3), base = 60_000))
    }

    @Test
    fun aNonTerminalAnswerKeepsFollowingAndClearsTheFailures() {
        for (state in listOf(DesktopMediaJobState.QUEUED, DesktopMediaJobState.RUNNING, DesktopMediaJobState.PUBLISHING)) {
            val next = KalivMediaJob.polled(job(state), DesktopMediaKind.IMAGE)
            assertEquals(DesktopMediaPhase.Following(job(state), 0), next)
        }
    }

    @Test
    fun aCompletedJobHoldsItsResultAndOtherTerminalStatesEndInWords() {
        val done = job(DesktopMediaJobState.COMPLETED, assetId = "img_1")
        assertEquals(DesktopMediaPhase.Completed(done), KalivMediaJob.polled(done, DesktopMediaKind.IMAGE))
        // Cannot happen through the parser, and is still never shown as a result.
        assertIs<DesktopMediaPhase.Ended>(KalivMediaJob.polled(job(DesktopMediaJobState.COMPLETED), DesktopMediaKind.IMAGE))
        assertEquals(
            DesktopMediaPhase.Ended("Grafikkortet på riggen er ikke ledigt"),
            KalivMediaJob.polled(job(DesktopMediaJobState.FAILED, error = "gpu_unavailable"), DesktopMediaKind.IMAGE),
        )
        assertEquals(
            DesktopMediaPhase.Ended("Annulleret"),
            KalivMediaJob.polled(job(DesktopMediaJobState.CANCELLED), DesktopMediaKind.VIDEO),
        )
        val expired = KalivMediaJob.polled(job(DesktopMediaJobState.EXPIRED), DesktopMediaKind.IMAGE)
        assertTrue((expired as DesktopMediaPhase.Ended).text.startsWith("Udløbet"))
        assertFalse(expired.retryable)
    }

    @Test
    fun transientFailuresCountAndTheSixthStopsAskingButOffersRetry() {
        var phase: DesktopMediaPhase = DesktopMediaPhase.Following(job(DesktopMediaJobState.RUNNING), 0)
        repeat(KalivMediaJob.MAX_POLL_FAILURES - 1) { i ->
            phase = KalivMediaJob.pollFailed(phase, failure(if (i % 2 == 0) Reason.NETWORK else Reason.TRANSIENT))
            assertEquals(i + 1, (phase as DesktopMediaPhase.Following).failures)
            // The last good answer is kept, so the bubble keeps saying where the job was.
            assertEquals(DesktopMediaJobState.RUNNING, (phase as DesktopMediaPhase.Following).job?.state)
        }
        val gaveUp = KalivMediaJob.pollFailed(phase, failure(Reason.NETWORK))
        assertEquals(DesktopMediaPhase.Ended(KalivMediaJob.GAVE_UP_TEXT, retryable = true), gaveUp)
        // One good answer in between resets the count.
        val recovered = KalivMediaJob.polled(job(DesktopMediaJobState.RUNNING), DesktopMediaKind.IMAGE)
        assertEquals(1, (KalivMediaJob.pollFailed(recovered, failure(Reason.TRANSIENT)) as DesktopMediaPhase.Following).failures)
    }

    @Test
    fun aDefiniteAnswerEndsTheJobWithoutRetry() {
        val following = KalivMediaJob.initial()
        assertEquals(
            DesktopMediaPhase.Ended(KalivMediaJob.NOT_FOUND_TEXT),
            KalivMediaJob.pollFailed(following, failure(Reason.NOT_FOUND)),
        )
        for (reason in listOf(Reason.UNAUTHORIZED, Reason.UNAVAILABLE, Reason.REDIRECT_REFUSED, Reason.PROTOCOL, Reason.HTTP, Reason.TOO_LARGE)) {
            val ended = KalivMediaJob.pollFailed(following, failure(reason, "Klientens egne ord"))
            assertEquals(DesktopMediaPhase.Ended("Klientens egne ord"), ended, reason.name)
        }
        // Anything that is not the client's own exception is never shown raw.
        assertEquals(
            DesktopMediaPhase.Ended("Uventet svar fra riggen"),
            KalivMediaJob.pollFailed(following, IllegalStateException("stack trace text")),
        )
        // A bubble that is no longer following is left alone.
        val ended = DesktopMediaPhase.Ended("Annulleret")
        assertEquals(ended, KalivMediaJob.pollFailed(ended, failure(Reason.NETWORK)))
    }

    @Test
    fun theWordsFollowTheStateAndTheKind() {
        assertEquals("I kø på riggen", KalivMediaJob.label(KalivMediaJob.initial(), DesktopMediaKind.IMAGE))
        fun following(state: DesktopMediaJobState, cancel: Boolean = false) =
            DesktopMediaPhase.Following(job(state, cancel = cancel), 0)
        assertEquals("I kø på riggen", KalivMediaJob.label(following(DesktopMediaJobState.QUEUED), DesktopMediaKind.IMAGE))
        assertEquals("Genererer …", KalivMediaJob.label(following(DesktopMediaJobState.RUNNING), DesktopMediaKind.VIDEO))
        assertEquals("Gemmer billedet …", KalivMediaJob.label(following(DesktopMediaJobState.PUBLISHING), DesktopMediaKind.IMAGE))
        assertEquals("Gemmer videoen …", KalivMediaJob.label(following(DesktopMediaJobState.PUBLISHING), DesktopMediaKind.VIDEO))
        assertEquals("Annulleres …", KalivMediaJob.label(following(DesktopMediaJobState.RUNNING, cancel = true), DesktopMediaKind.IMAGE))
        val done = DesktopMediaPhase.Completed(job(DesktopMediaJobState.COMPLETED, assetId = "a"))
        assertEquals("Henter billedet …", KalivMediaJob.label(done, DesktopMediaKind.IMAGE))
        assertEquals("Klippet er færdigt", KalivMediaJob.label(done, DesktopMediaKind.VIDEO))
        assertEquals("Genereringen fejlede", KalivMediaJob.errorText("a_code_this_client_does_not_know"))
        assertEquals("Genereringen fejlede", KalivMediaJob.errorText(null))
        assertEquals("Kildebilledet findes ikke længere", KalivMediaJob.errorText("source_image_unavailable"))
    }

    @Test
    fun aFailedTransferIsSaidInTheClientsWordsOrOneNeutralLine() {
        assertEquals(
            "For stort til at blive hentet",
            KalivMediaJob.transferFailedText(failure(Reason.TOO_LARGE, "For stort til at blive hentet"), DesktopMediaKind.VIDEO),
        )
        assertEquals("Filen kunne ikke skrives", KalivMediaJob.transferFailedText(IOException("disk full"), DesktopMediaKind.VIDEO))
        assertEquals("Klippet kunne ikke hentes fra riggen", KalivMediaJob.transferFailedText(null, DesktopMediaKind.VIDEO))
        assertEquals(
            "Billedet kunne ikke hentes fra riggen",
            KalivMediaJob.transferFailedText(IllegalStateException("x"), DesktopMediaKind.IMAGE),
        )
    }

    @Test
    fun zoomStaysBetweenFitAndEightTimes() {
        assertEquals(1f, KalivMediaJob.nextScale(1f, -1f))
        assertEquals(1.2f, KalivMediaJob.nextScale(1f, 1f), 0.0001f)
        assertEquals(1f, KalivMediaJob.nextScale(1.2f, -1f), 0.0001f)
        assertEquals(8f, KalivMediaJob.nextScale(7.9f, 1f))
        // One wheel event never jumps more than eight steps, whatever delta the platform reports.
        assertEquals(KalivMediaJob.nextScale(1f, 8f), KalivMediaJob.nextScale(1f, 1_000f))
        assertEquals(KalivMediaJob.nextScale(8f, -8f), KalivMediaJob.nextScale(8f, -1_000f))
        var scale = 1f
        repeat(20) { scale = KalivMediaJob.nextScale(scale, 1f) }
        assertEquals(8f, scale)
        repeat(20) { scale = KalivMediaJob.nextScale(scale, -1f) }
        assertEquals(1f, scale)
        assertEquals(2f, KalivMediaJob.nextScale(2f, 0f))
        assertEquals(2f, KalivMediaJob.nextScale(2f, Float.NaN))
        assertEquals(8f, KalivMediaJob.nextScale(50f, 0f))
    }

    @Test
    fun panIsNothingAtFitSizeAndNeverLeavesTheZoomedPicture() {
        assertEquals(0f to 0f, KalivMediaJob.nextPan(40f, -30f, 10f, 10f, 1f, 800f, 600f))
        // At 2x an 800x600 view can move half a view in each direction: 400 / 300.
        assertEquals(50f to -20f, KalivMediaJob.nextPan(40f, -30f, 10f, 10f, 2f, 800f, 600f))
        assertEquals(400f to 300f, KalivMediaJob.nextPan(390f, 290f, 500f, 500f, 2f, 800f, 600f))
        assertEquals(-400f to -300f, KalivMediaJob.nextPan(0f, 0f, -9_999f, -9_999f, 2f, 800f, 600f))
        // Zooming out pulls an earlier pan back inside.
        val (x, y) = KalivMediaJob.nextPan(400f, 300f, 0f, 0f, 1.2f, 800f, 600f)
        assertEquals(80f, x, 0.01f)
        assertEquals(60f, y, 0.01f)
        assertEquals(0f to 0f, KalivMediaJob.nextPan(10f, 10f, 5f, 5f, 3f, 0f, 0f))
    }

    @Test
    fun theFormatIsReadFromTheBytesAndNamesCarryNoPromptText() {
        val png = byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0)
        val jpeg = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte(), 0xE0.toByte())
        val webp = "RIFF".toByteArray() + byteArrayOf(1, 2, 3, 4) + "WEBP".toByteArray()
        assertEquals("png", KalivMediaJob.imageExtension(png))
        assertEquals("jpg", KalivMediaJob.imageExtension(jpeg))
        assertEquals("webp", KalivMediaJob.imageExtension(webp))
        assertNull(KalivMediaJob.imageExtension("<svg/>".toByteArray()))
        assertNull(KalivMediaJob.imageExtension(ByteArray(0)))
        assertNull(KalivMediaJob.imageExtension("RIFF____WAVE".toByteArray()))

        val name = KalivMediaJob.fileName(id, "png", nowMillis = 1_800_000_000_000L)
        assertTrue(Regex("^kaliv-01234567-\\d{8}-\\d{6}\\.png$").matches(name), name)
        assertEquals("billede.png", KalivMediaJob.withExtension("billede", "png"))
        assertEquals("billede.png", KalivMediaJob.withExtension("billede.png", "png"))
        assertEquals("billede.PNG", KalivMediaJob.withExtension("billede.PNG", "png"))
        assertEquals("klip.mov.mp4", KalivMediaJob.withExtension("klip.mov", "mp4"))
        assertEquals("v1.2.mp4", KalivMediaJob.withExtension("v1.2", "mp4"))
    }

    @Test
    fun savingIsAllOrNothing() {
        val dir = Files.createTempDirectory("kaliv-media-save-")
        try {
            val target = dir.resolve("klip.mp4")
            val clip = ByteArray(10_000) { (it % 7).toByte() }
            val saved = KalivMediaJob.saveTo(target) { it.write(clip) }
            assertEquals(target, saved.getOrThrow())
            assertContentEquals(clip, Files.readAllBytes(target))
            assertFalse(Files.exists(dir.resolve("klip.mp4.part")))

            // A copy cut short leaves neither the final name nor the part file.
            val other = dir.resolve("afbrudt.mp4")
            val failed = KalivMediaJob.saveTo(other) { out ->
                out.write(clip, 0, 100)
                throw DesktopMediaException(Reason.NETWORK, "Forbindelsen til riggen blev afbrudt")
            }
            assertTrue(failed.isFailure)
            assertIs<DesktopMediaException>(failed.exceptionOrNull())
            assertFalse(Files.exists(other))
            assertFalse(Files.exists(dir.resolve("afbrudt.mp4.part")))

            // A failed save over an existing file leaves the existing file as it was.
            val again = KalivMediaJob.saveTo(target) { throw IOException("disk full") }
            assertTrue(again.isFailure)
            assertContentEquals(clip, Files.readAllBytes(target))

            // A good save replaces it (the system dialog has already asked).
            val replacement = ByteArray(10) { 9 }
            assertTrue(KalivMediaJob.saveTo(target) { it.write(replacement) }.isSuccess)
            assertContentEquals(replacement, Files.readAllBytes(target))
        } finally {
            dir.toFile().deleteRecursively()
        }
    }
}
