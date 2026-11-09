package dk.ternedal.modelrig.ui

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.hasSetTextAction
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import androidx.lifecycle.compose.LocalLifecycleOwner
import dk.ternedal.modelrig.data.VisionRigSettings
import dk.ternedal.modelrig.net.VisionRigCameraProducer
import dk.ternedal.modelrig.net.VisionRigCameraProducerFactory
import dk.ternedal.modelrig.net.VisionRigConnection
import dk.ternedal.modelrig.net.VisionRigStep
import dk.ternedal.modelrig.ui.theme.ModelRigTheme
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.awaitCancellation
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.IOException

/** The approved limits of the VisionRig phone camera, against fakes; no camera, no network. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36])
class VisionRigCameraScreenTest {
    @get:Rule
    val compose = createComposeRule()

    private val token = "t".repeat(VisionRigConnection.MIN_TOKEN_CHARS)
    private val lan = VisionRigConnection.create("http://192.168.1.10:8111", token).getOrThrow()

    private class FakeSettings(var stored: VisionRigConnection?, var optIn: Boolean = false) : VisionRigSettings {
        var unreadable = false
        override fun connection() = stored
        override fun credentialUnreadable() = unreadable
        override fun cameraOptIn() = optIn
        override fun save(connection: VisionRigConnection): Boolean { stored = connection; return true }
        override fun setCameraOptIn(on: Boolean): Boolean { optIn = on; return true }
        override fun clear(): Boolean { stored = null; optIn = false; return true }
    }

    /** Emits the given steps, then runs until cancelled (like the real runner). */
    private class FakeProducer(private val steps: List<VisionRigStep>, private val failWith: Exception?) : VisionRigCameraProducer {
        var closed = false
        override suspend fun run(onStep: (VisionRigStep) -> Unit) {
            steps.forEach(onStep)
            failWith?.let { throw it }
            awaitCancellation()
        }
        override fun close() { closed = true }
    }

    private class FakeFactory(
        val steps: List<VisionRigStep> = listOf(VisionRigStep(desiredEnabled = true, captureActive = true, frameSent = true)),
        var failFirst: Exception? = null,
    ) : VisionRigCameraProducerFactory {
        val made = mutableListOf<FakeProducer>()
        val connections = mutableListOf<VisionRigConnection>()
        override fun create(context: android.content.Context, lifecycleOwner: LifecycleOwner, connection: VisionRigConnection, http: okhttp3.OkHttpClient): VisionRigCameraProducer {
            connections += connection
            return FakeProducer(steps, failFirst.also { failFirst = null }).also { made += it }
        }
    }

    private class Owner : LifecycleOwner {
        val registry = LifecycleRegistry(this)
        override val lifecycle: Lifecycle get() = registry
    }

    private fun show(settings: VisionRigSettings, factory: VisionRigCameraProducerFactory?, permission: Boolean = true, owner: Owner = Owner().apply { registry.currentState = Lifecycle.State.RESUMED }, onRequest: () -> Unit = {}): Owner {
        compose.setContent {
            CompositionLocalProvider(LocalLifecycleOwner provides owner) {
                ModelRigTheme(dark = true) {
                    VisionRigCameraContent(settings, factory, permission, onRequest, onClose = {}, io = Dispatchers.Main)
                }
            }
        }
        compose.waitForIdle()
        return owner
    }

    private fun bannerShown() = compose.onAllNodesWithText("Kamera sendes til riggen").fetchSemanticsNodes().isNotEmpty()

    @Test
    fun pairingRefusesTailscaleHttpAndSavesALanGateway() {
        val settings = FakeSettings(stored = null)
        show(settings, FakeFactory())
        compose.onNode(hasSetTextAction() and hasText("VisionRig-gateway")).performTextInput("http://100.101.50.10:8111")
        compose.onNode(hasSetTextAction() and hasText("Producer-token")).performTextInput(token)
        compose.onNodeWithText("Gem parring").performClick()
        compose.waitForIdle()
        compose.onNodeWithText("Kræver HTTPS", substring = true).assertIsDisplayed()
        assertEquals(null, settings.stored)
    }

    @Test
    fun pairingAcceptsALanGateway() {
        val settings = FakeSettings(stored = null)
        show(settings, FakeFactory())
        compose.onNode(hasSetTextAction() and hasText("VisionRig-gateway")).performTextInput("http://192.168.1.10:8111")
        compose.onNode(hasSetTextAction() and hasText("Producer-token")).performTextInput(token)
        compose.onNodeWithText("Gem parring").performClick()
        compose.waitForIdle()
        assertEquals("http://192.168.1.10:8111", settings.stored?.gatewayUrl)
        compose.onNodeWithText("Parret med 192.168.1.10:8111").assertIsDisplayed()
    }

    @Test
    fun withoutOptInNothingRuns() {
        val factory = FakeFactory()
        show(FakeSettings(stored = lan, optIn = false), factory)
        assertTrue(factory.made.isEmpty())
        assertFalse(bannerShown())
        compose.onNodeWithText("Send kameraet til VisionRig").assertIsDisplayed()
    }

    @Test
    fun optInWithPermissionRunsShowsTheBannerAndCountsFrames() {
        val factory = FakeFactory()
        show(FakeSettings(stored = lan, optIn = true), factory)
        assertEquals(1, factory.made.size)
        assertEquals(lan.gatewayUrl, factory.connections.single().gatewayUrl)
        assertTrue(bannerShown())
        compose.onNodeWithText("Sender billeder til VisionRig: 1 modtaget").assertIsDisplayed()
    }

    @Test
    fun rigDesiredStateOffMeansWaitingAndNothingSent() {
        val factory = FakeFactory(steps = listOf(VisionRigStep(desiredEnabled = false, captureActive = false, frameSent = false)))
        show(FakeSettings(stored = lan, optIn = true), factory)
        compose.onNodeWithText("VisionRig har ikke slået kameraet til. Intet sendes.").assertIsDisplayed()
    }

    @Test
    fun leavingTheForegroundStopsAndClosesTheProducer() {
        val factory = FakeFactory()
        val owner = show(FakeSettings(stored = lan, optIn = true), factory)
        assertTrue(bannerShown())
        compose.runOnIdle { owner.registry.currentState = Lifecycle.State.CREATED } // ON_STOP
        compose.waitForIdle()
        assertTrue("closed on ON_STOP", factory.made.single().closed)
        assertFalse(bannerShown())
        compose.runOnIdle { owner.registry.currentState = Lifecycle.State.RESUMED } // back in front
        compose.waitForIdle()
        assertEquals("a new session after returning", 2, factory.made.size)
    }

    @Test
    fun missingPermissionRunsNothingAndOffersTheRequest() {
        val factory = FakeFactory()
        var requested = 0
        show(FakeSettings(stored = lan, optIn = true), factory, permission = false, onRequest = { requested++ })
        assertTrue(factory.made.isEmpty())
        compose.onNodeWithText("Giv tilladelse").performClick()
        assertEquals(1, requested)
    }

    @Test
    fun withoutAProducerTheScreenSaysSoAndNothingRuns() {
        show(FakeSettings(stored = lan, optIn = true), factory = null)
        compose.onNodeWithText("VisionRig-producenten er ikke bygget ind i denne version endnu.").assertIsDisplayed()
        assertFalse(bannerShown())
    }

    @Test
    fun stoppingAndForgettingCloseTheProducer() {
        val factory = FakeFactory()
        val settings = FakeSettings(stored = lan, optIn = true)
        show(settings, factory)
        compose.onNodeWithText("Stop kameraet").performClick()
        compose.waitForIdle()
        assertTrue(factory.made.single().closed)
        assertFalse(settings.optIn)
        assertFalse(bannerShown())
        compose.onNodeWithText("Glem VisionRig-parring").performClick()
        compose.waitForIdle()
        assertEquals(null, settings.stored)
        compose.onNodeWithText("Gem parring").assertIsDisplayed()
    }

    @Test
    fun aFailureIsShownAndCanBeRetried() {
        val factory = FakeFactory(failFirst = IOException("gateway down"))
        show(FakeSettings(stored = lan, optIn = true), factory)
        compose.onNodeWithText("VisionRig kan ikke nås", substring = true).assertIsDisplayed()
        assertTrue(factory.made.single().closed)
        assertFalse(bannerShown())
        compose.onNodeWithText("Prøv igen").performClick()
        compose.waitForIdle()
        assertEquals(2, factory.made.size)
        assertTrue(bannerShown())
    }

    @Test
    fun unreadableStoredTokenAsksToRePair() {
        val settings = FakeSettings(stored = null).apply { unreadable = true }
        show(settings, FakeFactory())
        compose.onNodeWithText("Det gemte VisionRig-token kan ikke længere læses. Par igen.").assertIsDisplayed()
    }
}
