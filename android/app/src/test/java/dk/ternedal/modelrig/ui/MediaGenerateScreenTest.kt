package dk.ternedal.modelrig.ui

import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import dk.ternedal.modelrig.net.MediaJob
import dk.ternedal.modelrig.net.MediaJobCancel
import dk.ternedal.modelrig.net.MediaJobContractTest.Companion.JOB_ID
import dk.ternedal.modelrig.net.MediaJobContractTest.Companion.SDXL
import dk.ternedal.modelrig.net.MediaJobException
import dk.ternedal.modelrig.net.MediaJobException.Reason
import dk.ternedal.modelrig.net.MediaJobProfile
import dk.ternedal.modelrig.net.MediaJobRequest
import dk.ternedal.modelrig.net.MediaJobSource
import dk.ternedal.modelrig.net.MediaJobState
import dk.ternedal.modelrig.ui.theme.ModelRigTheme
import kotlinx.coroutines.Dispatchers
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** The generate screen against a fake rig; no network. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [36])
class MediaGenerateScreenTest {
    @get:Rule
    val compose = createComposeRule()

    private class FakeRig(
        private val profileList: () -> List<MediaJobProfile> = { listOf(SDXL) },
        private val submitResult: () -> MediaJob = { job(MediaJobState.QUEUED) },
        statuses: List<MediaJob> = emptyList(),
        /** Thrown instead of answering for poll number n (1-based), when it returns one. */
        private val statusError: (Int) -> MediaJobException? = { null },
        private val cancelResult: () -> MediaJobCancel = { MediaJobCancel("cancelled", job(MediaJobState.CANCELLED)) },
    ) : MediaJobSource {
        val submitted = mutableListOf<MediaJobRequest>()
        var polls = 0
        var cancels = 0
        private val queue = statuses.toMutableList()
        override fun profiles() = profileList()
        override fun submit(request: MediaJobRequest, profile: MediaJobProfile): MediaJob {
            submitted += request
            return submitResult()
        }
        override fun status(id: String): MediaJob {
            polls++
            statusError(polls)?.let { throw it }
            return if (queue.size > 1) queue.removeAt(0) else queue.firstOrNull() ?: job(MediaJobState.QUEUED)
        }
        override fun cancel(id: String): MediaJobCancel {
            cancels++
            return cancelResult()
        }
    }

    companion object {
        fun job(state: MediaJobState, assetId: String? = null, error: String? = null) =
            MediaJob(JOB_ID, state, "sdxl-a", assetId, error, false)
    }

    private var galleryOpened = 0

    private fun show(rig: MediaJobSource) {
        compose.setContent {
            ModelRigTheme(dark = true) {
                MediaGenerateContent(rig, onOpenGallery = { galleryOpened++ }, onClose = {}, io = Dispatchers.Unconfined,
                    pollMillis = 10)
            }
        }
        compose.waitForIdle()
    }

    private fun showRestorable(rig: MediaJobSource, pollMillis: Long = 10): StateRestorationTester {
        val tester = StateRestorationTester(compose)
        tester.setContent {
            ModelRigTheme(dark = true) {
                MediaGenerateContent(rig, onOpenGallery = { galleryOpened++ }, onClose = {}, io = Dispatchers.Unconfined,
                    pollMillis = pollMillis)
            }
        }
        compose.waitForIdle()
        return tester
    }

    @Test
    fun `a recreated screen picks the followed job up again, but never the prompt`() {
        // #2275 backlog task 4: rotation or a process restart must not leave the job running unseen.
        val polledIds = mutableListOf<String>()
        val rig = object : MediaJobSource by FakeRig(statuses = listOf(job(MediaJobState.RUNNING))) {
            override fun status(id: String): MediaJob { polledIds += id; return job(MediaJobState.RUNNING) }
        }
        val tester = showRestorable(rig)
        compose.onNodeWithTag("generate-prompt").performTextInput("secret-prompt-91 a red bicycle")
        compose.onNodeWithTag("generate-submit").performClick()
        compose.waitUntil(5_000) { compose.onAllNodesWithTagExists("generate-cancel") }
        val before = polledIds.size
        tester.emulateSavedInstanceStateRestore()
        compose.waitUntil(5_000) { compose.onAllNodesWithTagExists("generate-cancel") }
        assertTrue("the recreated screen asked the rig for the saved job", polledIds.size > before)
        assertTrue(polledIds.all { it == JOB_ID })
        compose.onNodeWithText("secret-prompt-91 a red bicycle", substring = true).assertDoesNotExist()
    }

    @Test
    fun `a saved job the rig no longer knows leaves the form usable and says so`() {
        var gone = false
        val rig = object : MediaJobSource by FakeRig() {
            override fun status(id: String): MediaJob {
                if (gone) throw MediaJobException(Reason.NOT_FOUND, "Jobbet findes ikke længere", "job_not_found")
                return job(MediaJobState.RUNNING)
            }
        }
        val tester = showRestorable(rig, pollMillis = 3_600_000)
        compose.onNodeWithTag("generate-prompt").performTextInput("a red bicycle")
        compose.onNodeWithTag("generate-submit").performClick()
        compose.waitUntil(5_000) { compose.onAllNodesWithTagExists("generate-cancel") }
        gone = true  // polls are an hour apart here, so only the restore can see this
        tester.emulateSavedInstanceStateRestore()
        compose.waitUntil(5_000) { compose.onAllNodesWithTagExists("generate-submit") }
        compose.onNodeWithText("Det tidligere job findes ikke længere på riggen").assertExists()
        compose.onNodeWithTag("generate-cancel").assertDoesNotExist()
    }

    @Test
    fun `a rig without the route says so and offers nothing`() {
        show(FakeRig(profileList = { throw MediaJobException(Reason.UNAVAILABLE, "Billedgenerering er ikke tilgængelig på denne rig") }))
        compose.onNodeWithText("Billedgenerering er ikke tilgængelig på denne rig").assertExists()
        compose.onNodeWithTag("generate-submit").assertDoesNotExist()
        compose.onNodeWithTag("generate-prompt").assertDoesNotExist()
    }

    @Test
    fun `a rig with no image profile says so and offers nothing`() {
        show(FakeRig(profileList = { emptyList() }))
        compose.onNodeWithText("Riggen har ingen billed- eller videoprofil slået til").assertExists()
        compose.onNodeWithTag("generate-submit").assertDoesNotExist()
    }

    @Test
    fun `an absent backend (404 from the real client) is unavailable, not an error loop`() {
        val server = okhttp3.mockwebserver.MockWebServer()
        server.start()
        try {
            server.enqueue(okhttp3.mockwebserver.MockResponse().setResponseCode(404)
                .setHeader("Content-Type", "application/json").setBody("""{"error":"not found"}"""))
            show(dk.ternedal.modelrig.net.MediaJobClient(server.url("/").toString().trimEnd('/'), "device-token"))
            compose.onNodeWithText("Billedgenerering er ikke tilgængelig på denne rig").assertExists()
            compose.onNodeWithTag("generate-submit").assertDoesNotExist()
            assertEquals("one request, no retry loop", 1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `the prompt never reaches the log, through a whole job and through every failure`() {
        val prompt = "secret-prompt-7f3a a red bicycle"
        org.robolectric.shadows.ShadowLog.clear()
        val rig = FakeRig(statuses = listOf(job(MediaJobState.RUNNING), job(MediaJobState.COMPLETED, assetId = "asset_1")))
        show(rig)
        compose.onNodeWithTag("generate-prompt").performTextInput(prompt)
        compose.onNodeWithTag("generate-submit").performClick()
        compose.waitUntil(5_000) { compose.onAllNodesWithTagExists("generate-open-gallery") }
        assertEquals(prompt, rig.submitted.single().prompt)
        for (reason in Reason.entries) {
            val e = MediaJobException(reason, "x", "queue_full")
            val texts = listOf(MediaGenerate.message(e), e.message.orEmpty(), e.toString())
            assertTrue(texts.none { it.contains("secret-prompt") })
        }
        val logged = org.robolectric.shadows.ShadowLog.getLogs().joinToString("\n") { "${it.tag} ${it.msg} ${it.throwable}" }
        assertTrue("prompt in log: $logged", !logged.contains("secret-prompt"))
    }

    @Test
    fun `generate follows the job to completion and only then offers the gallery`() {
        val rig = FakeRig(statuses = listOf(job(MediaJobState.RUNNING), job(MediaJobState.COMPLETED, assetId = "asset_1")))
        show(rig)
        compose.onNodeWithTag("generate-submit").assertIsNotEnabled()
        compose.onNodeWithTag("generate-prompt").performTextInput("a red bicycle")
        compose.onNodeWithTag("generate-submit").assertIsEnabled().performClick()
        compose.waitUntil(5_000) { compose.onAllNodesWithTagExists("generate-open-gallery") }
        compose.onNodeWithText("Færdig").assertExists()
        compose.onNodeWithTag("generate-cancel").assertDoesNotExist()
        compose.onNodeWithTag("generate-open-gallery").performScrollTo().performClick()
        compose.waitForIdle()
        assertEquals(1, galleryOpened)
        assertEquals("a red bicycle", rig.submitted.single().prompt)
        val pollsAtEnd = rig.polls
        Thread.sleep(100)
        compose.waitForIdle()
        assertEquals("polling stopped at the terminal state", pollsAtEnd, rig.polls)
    }

    @Test
    fun `cancel is offered while queued and shows the cancelled job`() {
        val rig = FakeRig()
        show(rig)
        compose.onNodeWithTag("generate-prompt").performTextInput("x")
        compose.onNodeWithTag("generate-submit").performClick()
        compose.onNodeWithTag("generate-cancel").assertIsEnabled().performClick()
        compose.waitUntil(5_000) { compose.onAllNodesWithTextExists("Annulleret") }
        assertEquals(1, rig.cancels)
        compose.onNodeWithTag("generate-open-gallery").assertDoesNotExist()
    }

    @Test
    fun `transient poll failures do not end the job, and it still completes`() {
        val rig = FakeRig(
            statuses = listOf(job(MediaJobState.RUNNING), job(MediaJobState.COMPLETED, assetId = "asset_1")),
            statusError = { n -> if (n in 1..3) MediaJobException(Reason.TRANSIENT, "Riggen svarer ikke lige nu", "upstream") else null },
        )
        show(rig)
        compose.onNodeWithTag("generate-prompt").performTextInput("x")
        compose.onNodeWithTag("generate-submit").performClick()
        compose.waitUntil(10_000) { compose.onAllNodesWithTagExists("generate-open-gallery") }
        compose.onNodeWithText("Færdig").assertExists()
        assertTrue("three failures, then two answers", rig.polls >= 5)
    }

    @Test
    fun `a rig that stays down stalls with the job kept, and Proev igen follows it again`() {
        var down = true
        val rig = FakeRig(statuses = listOf(job(MediaJobState.COMPLETED, assetId = "asset_1")),
            statusError = { if (down) MediaJobException(Reason.TRANSIENT, "Riggen svarer ikke lige nu") else null })
        show(rig)
        compose.onNodeWithTag("generate-prompt").performTextInput("x")
        compose.onNodeWithTag("generate-submit").performClick()
        compose.waitUntil(20_000) { compose.onAllNodesWithTagExists("generate-resume") }
        val pollsWhenStalled = rig.polls
        assertEquals("bounded: exactly MAX_POLL_FAILURES polls", MediaGenerate.MAX_POLL_FAILURES, pollsWhenStalled)
        Thread.sleep(150)
        compose.waitForIdle()
        assertEquals("no polling while stalled", pollsWhenStalled, rig.polls)
        down = false
        compose.onNodeWithTag("generate-resume").performScrollTo().performClick()
        compose.waitUntil(5_000) { compose.onAllNodesWithTagExists("generate-open-gallery") }
    }

    @Test
    fun `cancel answered too late shows it, drops Annulleres, and follows the job to Faerdig`() {
        // Deterministic: running until cancel is pressed, then publishing twice, then completed.
        var cancelled = false
        var after = 0
        val rig = object : MediaJobSource {
            var cancels = 0
            override fun profiles() = listOf(SDXL)
            override fun submit(request: MediaJobRequest, profile: MediaJobProfile) = job(MediaJobState.RUNNING)
            override fun status(id: String): MediaJob = when {
                !cancelled -> job(MediaJobState.RUNNING)
                ++after <= 2 -> job(MediaJobState.PUBLISHING)
                else -> job(MediaJobState.COMPLETED, assetId = "asset_1")
            }
            override fun cancel(id: String): MediaJobCancel {
                cancels++
                cancelled = true
                return MediaJobCancel("too_late", job(MediaJobState.PUBLISHING))
            }
        }
        show(rig)
        compose.onNodeWithTag("generate-prompt").performTextInput("x")
        compose.onNodeWithTag("generate-submit").performClick()
        compose.onNodeWithTag("generate-cancel").performClick()
        compose.waitUntil(5_000) { compose.onAllNodesWithTextExists(MediaGenerate.TOO_LATE_TEXT) }
        compose.onNodeWithText("Annulleres …").assertDoesNotExist()
        compose.waitUntil(5_000) { compose.onAllNodesWithTagExists("generate-open-gallery") }
        compose.onNodeWithText("Færdig").assertExists()
        assertEquals(1, rig.cancels)
    }

    @Test
    fun `a video profile is chosen, submitted as text_to_video and completes to the gallery`() {
        val rig = FakeRig(
            profileList = { listOf(SDXL, dk.ternedal.modelrig.net.MediaJobContractTest.WAN) },
            submitResult = { MediaJob(JOB_ID, MediaJobState.QUEUED, "wan-t2v", null, null, false) },
            statuses = listOf(MediaJob(JOB_ID, MediaJobState.COMPLETED, "wan-t2v", "asset_v1", null, false)),
        )
        show(rig)
        compose.onNodeWithText("Generér billede eller video").assertExists()
        compose.onNodeWithText("Video · wan-t2v").performClick()
        compose.onNodeWithText("832×480").assertExists()
        compose.onNodeWithTag("generate-prompt").performScrollTo().performTextInput("a dog running")
        compose.onNodeWithTag("generate-submit").performScrollTo().assertIsEnabled().performClick()
        compose.waitUntil(5_000) { rig.submitted.isNotEmpty() && compose.onAllNodesWithTagExists("generate-open-gallery") }
        val sent = rig.submitted.single()
        assertEquals("text_to_video" to "wan-t2v", sent.task to sent.profileId)
    }

    @Test
    fun `an expired job is shown as expired`() {
        show(FakeRig(statuses = listOf(job(MediaJobState.EXPIRED, error = "expired_unclaimed"))))
        compose.onNodeWithTag("generate-prompt").performTextInput("x")
        compose.onNodeWithTag("generate-submit").performClick()
        compose.waitUntil(5_000) {
            compose.onAllNodesWithTextExists("Udløbet: riggen nåede ikke at starte jobbet inden for et døgn")
        }
        compose.onNodeWithTag("generate-open-gallery").assertDoesNotExist()
    }

    @Test
    fun `a busy rig keeps the form and the prompt`() {
        show(FakeRig(submitResult = { throw MediaJobException(Reason.BUSY, "x", "queue_full") }))
        compose.onNodeWithTag("generate-prompt").performTextInput("keep me")
        compose.onNodeWithTag("generate-submit").performClick()
        compose.waitForIdle()
        compose.onNodeWithText("Riggens kø er fuld; prøv igen om lidt").assertExists()
        compose.onNodeWithText("keep me").assertExists()
        compose.onNodeWithTag("generate-submit").assertIsEnabled()
    }

    private fun androidx.compose.ui.test.junit4.ComposeContentTestRule.onAllNodesWithTagExists(tag: String) =
        onAllNodes(androidx.compose.ui.test.hasTestTag(tag)).fetchSemanticsNodes().isNotEmpty()

    private fun androidx.compose.ui.test.junit4.ComposeContentTestRule.onAllNodesWithTextExists(text: String) =
        onAllNodes(androidx.compose.ui.test.hasText(text)).fetchSemanticsNodes().isNotEmpty().also { assertTrue(true) }
}
