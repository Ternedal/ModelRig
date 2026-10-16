package dk.ternedal.modelrig.data

import android.content.Context
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment

/**
 * Android preference regression for fail-closed Nest Hub opt-out.
 * No Keystore access or network is required; disabling must never decrypt.
 */
@RunWith(RobolectricTestRunner::class)
class HubMirrorPreferencesTest {
    @Test fun disablingMirrorIsAlwaysPossibleEvenWithCorruptedKeyAndAddress() {
        val context = RuntimeEnvironment.getApplication()
        val prefs = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)
        prefs.edit().clear().commit()
        val store = TokenStore(context)
        assertFalse(store.hubMirrorEnabled)
        assertEquals(0L, store.hubMirrorGeneration)

        // Simulate corrupted ciphertext left after Android device restore.
        prefs.edit()
            .putBoolean("hub_mirror_enabled", true)
            .putString("hub_mirror_endpoint", "https://not-an-allowed-host.example")
            .putString("hub_mirror_secret_enc", "enc:v1:not-a-valid-ciphertext")
            .commit()
        assertTrue(store.saveHubMirrorConfig("broken URL", "too short", false))
        assertFalse(store.hubMirrorEnabled)
        assertEquals(1L, store.hubMirrorGeneration)

        // A second disable also invalidates any queued older reply.
        assertTrue(store.saveHubMirrorConfig("", null, false))
        assertEquals(2L, store.hubMirrorGeneration)
    }
}
