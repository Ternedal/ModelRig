package dk.ternedal.modelrig.data

import android.content.Context
import org.junit.Assert.assertEquals
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
    fun `authority survives a new store instance and remains rig and credential scoped`() {
        val rigA = "https://rig-a.example:8443/"
        val rigB = "https://rig-b.example:8443"
        val encoded = "{\"schema\":\"test-authority\"}"
        var currentToken = "token-a"

        val firstProcessStore = Agent3ReviewedStartRecoveryStore(context) { currentToken }
        assertTrue(firstProcessStore.write(rigA, encoded))

        val restartedProcessStore = Agent3ReviewedStartRecoveryStore(context) { currentToken }
        assertEquals(encoded, restartedProcessStore.read("https://rig-a.example:8443"))
        assertNull(restartedProcessStore.read(rigB))

        currentToken = "token-b"
        val mismatched = restartedProcessStore.read(rigA)
        assertNotNull(mismatched)
        assertNotEquals(encoded, mismatched)

        currentToken = "token-a"
        assertEquals(encoded, restartedProcessStore.read(rigA))

        assertTrue(restartedProcessStore.write(rigA, null))
        assertNull(Agent3ReviewedStartRecoveryStore(context) { currentToken }.read(rigA))
    }

    @Test
    fun `legacy unbound authority stays nonempty but cannot be recovered`() {
        val rig = "https://rig.example:8443"
        val encoded = "{\"schema\":\"test-authority\"}"
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
    }
}
