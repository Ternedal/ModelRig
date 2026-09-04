package dk.ternedal.modelrig

import android.content.Context
import android.content.Intent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment

/**
 * The bridge hands Kaliv's rig and token to Kaliv Body and to nothing else:
 * no launch without both, no launch when the app is absent, and the intent
 * is pinned to the package with the two extras BodyRigRigLink reads.
 */
@RunWith(RobolectricTestRunner::class)
class KalivBodyBridgeTest {
    private val context: Context get() = RuntimeEnvironment.getApplication()

    @Test
    fun `nothing to hand over means no launch`() {
        val launch = Intent(Intent.ACTION_MAIN)
        assertNull(KalivBodyBridge.carry(launch, "", "tok"))
        assertNull(KalivBodyBridge.carry(launch, "http://rig:8080", ""))
    }

    @Test
    fun `absent app means no launch, never a crash`() {
        assertNull(KalivBodyBridge.carry(null, "http://rig:8080", "tok"))
        assertNull(KalivBodyBridge.launchIntent(context, "http://rig:8080", "tok"))
    }

    @Test
    fun `installed app gets exactly the rig and the token, pinned to its package`() {
        val launch = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
            .setClassName(KalivBodyBridge.PACKAGE, "com.unity3d.player.UnityPlayerActivity")
        val intent = KalivBodyBridge.carry(launch, "http://192.168.1.33:8080/", "device-token")
        assertTrue(intent != null)
        assertEquals(KalivBodyBridge.PACKAGE, intent!!.`package`)
        assertEquals("http://192.168.1.33:8080", intent.getStringExtra(KalivBodyBridge.EXTRA_RIG_URL))
        assertEquals("device-token", intent.getStringExtra(KalivBodyBridge.EXTRA_RIG_TOKEN))
        assertTrue(intent.flags and Intent.FLAG_ACTIVITY_NEW_TASK != 0)
        assertTrue(intent.extras!!.keySet().none { it != KalivBodyBridge.EXTRA_RIG_URL && it != KalivBodyBridge.EXTRA_RIG_TOKEN })
    }
}
