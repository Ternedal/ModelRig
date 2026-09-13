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
        assertFalse(storeB.clearIfMatches(rigA, first))

        token = "token-a"
        assertEquals(first, storeA.read(rigA))
        assertTrue(storeA.clearIfMatches(rigA, first))
        assertNull(storeB.read(rigA))
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
