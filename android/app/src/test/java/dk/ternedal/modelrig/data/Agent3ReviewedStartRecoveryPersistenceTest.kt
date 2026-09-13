package dk.ternedal.modelrig.data

import android.content.Context
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment

@RunWith(RobolectricTestRunner::class)
class Agent3ReviewedStartRecoveryPersistenceTest {
    private lateinit var context: Context

    @Before
    fun resetPreferences() {
        context = RuntimeEnvironment.getApplication().applicationContext
        context.getSharedPreferences("modelrig", Context.MODE_PRIVATE).edit().clear().commit()
    }

    @Test
    fun `authority reservation is CAS and credential bound across store instances`() {
        val rigA = "https://rig-a.example:8443/"
        val rigB = "https://rig-b.example:8443"
        val first = "{\"schema\":\"authority-a-${System.nanoTime()}\"}"
        val second = "{\"schema\":\"authority-b-${System.nanoTime()}\"}"
        var token = "token-a"

        val storeA = Agent3ReviewedStartRecoveryStore(context) { token }
        val storeB = Agent3ReviewedStartRecoveryStore(context) { token }
        assertTrue(storeA.reserve(rigA, first))
        assertFalse(storeB.reserve(rigA, second))
        assertEquals(first, storeB.read("https://rig-a.example:8443"))
        assertFalse(storeB.clearIfMatches(rigA, second))
        assertEquals(first, storeA.read(rigA))
        assertNull(storeA.read(rigB))

        token = "token-b"
        val mismatched = storeB.read(rigA)
        assertNotNull(mismatched)
        assertNotEquals(first, mismatched)

        token = "token-a"
        assertEquals(first, storeA.read(rigA))
        assertTrue(storeA.clearIfMatches(rigA, first))
        assertNull(storeB.read(rigA))
    }

    @Test
    fun `stale completion cannot clear identical authority with a newer reservation generation`() {
        val rig = "https://aba-rig-${System.nanoTime()}.example"
        val authority = "{\"schema\":\"same-authority-${System.nanoTime()}\"}"
        val store = Agent3ReviewedStartRecoveryStore(context) { "token-a" }
        val prefs = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)
        val key = requireNotNull(agent3ReviewedStartRecoveryStorageKey(rig))

        assertTrue(store.reserve(rig, authority))
        val originalEnvelope = requireNotNull(prefs.getString(key, null))
        val parts = originalEnvelope.split('\n', limit = 4)
        assertEquals(4, parts.size)
        assertEquals("kaliv-agent3-reviewed-start-storage/v3", parts[0])

        val replacementGeneration = if (parts[2] == "11111111-1111-4111-8111-111111111111") {
            "22222222-2222-4222-8222-222222222222"
        } else {
            "11111111-1111-4111-8111-111111111111"
        }
        val replacementEnvelope = listOf(parts[0], parts[1], replacementGeneration, parts[3]).joinToString("\n")

        // Simulate another process clearing the old slot and re-reserving the exact
        // same encoded authority. This process still holds the old origin envelope.
        assertTrue(prefs.edit().remove(key).commit())
        assertTrue(prefs.edit().putString(key, replacementEnvelope).commit())

        assertFalse(store.clearIfMatches(rig, authority))
        assertEquals(replacementEnvelope, prefs.getString(key, null))

        // Once this process explicitly reads the newer generation it owns that
        // exact envelope and can clear it normally.
        assertEquals(authority, store.read(rig))
        assertTrue(store.clearIfMatches(rig, authority))
        assertNull(prefs.getString(key, null))
    }

    @Test
    fun `legacy v2 credential-bound authority stays unresolved instead of being adopted`() {
        val rig = "https://legacy-v2-${System.nanoTime()}.example"
        val encoded = "{\"schema\":\"legacy-v2-authority\"}"
        val key = requireNotNull(agent3ReviewedStartRecoveryStorageKey(rig))
        val raw = "kaliv-agent3-reviewed-start-storage/v2\n${"a".repeat(64)}\n$encoded"
        val prefs = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)
        assertTrue(prefs.edit().putString(key, raw).commit())

        val store = Agent3ReviewedStartRecoveryStore(context) { "token-a" }
        val visible = store.read(rig)
        assertNotNull(visible)
        assertNotEquals(encoded, visible)
        assertFalse(store.clearIfMatches(rig, encoded))
        assertEquals(raw, prefs.getString(key, null))
    }

    @Test
    fun `legacy unbound authority stays unresolved and is never adopted by current credential`() {
        val rig = "https://legacy-rig-${System.nanoTime()}.example"
        val encoded = "{\"schema\":\"legacy-authority\"}"
        val key = requireNotNull(agent3ReviewedStartRecoveryStorageKey(rig))
        assertTrue(
            context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)
                .edit()
                .putString(key, encoded)
                .commit()
        )

        val visible = Agent3ReviewedStartRecoveryStore(context) { "token-a" }.read(rig)
        assertNotNull(visible)
        assertNotEquals(encoded, visible)
        assertFalse(Agent3ReviewedStartRecoveryStore(context) { "token-a" }.clearIfMatches(rig, encoded))

        val persisted = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE).getString(key, null)
        assertEquals(encoded, persisted)
    }
}
