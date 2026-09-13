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
        val firstReservation = requireNotNull(storeA.reserve(rigA, first))
        assertNull(storeB.reserve(rigA, second))
        assertEquals(first, storeB.read("https://rig-a.example:8443"))
        assertNull(storeA.read(rigB))
        val otherRigReservation = requireNotNull(storeB.reserve(rigB, second))
        assertFalse(storeB.clearIfMatches(rigA, otherRigReservation))
        assertEquals(first, storeA.read(rigA))

        token = "token-b"
        val mismatched = storeB.read(rigA)
        assertNotNull(mismatched)
        assertNotEquals(first, mismatched)
        assertNull(storeB.readReservation(rigA))

        token = "token-a"
        assertEquals(first, storeA.read(rigA))
        assertTrue(storeA.clearIfMatches(rigA, firstReservation))
        assertNull(storeB.read(rigA))
    }

    @Test
    fun `stale generation handle cannot clear newer reused authority after newer read`() {
        val rig = "https://aba-rig-${System.nanoTime()}.example"
        val authority = "{\"schema\":\"same-authority-${System.nanoTime()}\"}"
        val store = Agent3ReviewedStartRecoveryStore(context) { "token-a" }
        val prefs = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)
        val key = requireNotNull(agent3ReviewedStartRecoveryStorageKey(rig))

        val staleReservation = requireNotNull(store.reserve(rig, authority))
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

        assertTrue(prefs.edit().remove(key).commit())
        assertTrue(prefs.edit().putString(key, replacementEnvelope).commit())

        val freshReservation = requireNotNull(store.readReservation(rig))
        assertEquals(authority, freshReservation.encodedAuthority)
        assertFalse(store.clearIfMatches(rig, staleReservation))
        assertEquals(replacementEnvelope, prefs.getString(key, null))
        assertTrue(store.clearIfMatches(rig, freshReservation))
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
        assertNull(store.readReservation(rig))
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

        val store = Agent3ReviewedStartRecoveryStore(context) { "token-a" }
        val visible = store.read(rig)
        assertNotNull(visible)
        assertNotEquals(encoded, visible)
        assertNull(store.readReservation(rig))
        val persisted = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE).getString(key, null)
        assertEquals(encoded, persisted)
    }
}
