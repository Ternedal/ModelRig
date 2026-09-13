package dk.ternedal.modelrig.data

import android.content.Context
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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
    fun `authority reservation is compare-and-set across store instances`() {
        val rigA = "https://rig-a.example:8443/"
        val rigB = "https://rig-b.example:8443"
        val first = "{\"schema\":\"authority-a\"}"
        val second = "{\"schema\":\"authority-b\"}"

        val storeA = Agent3ReviewedStartRecoveryStore(context)
        val storeB = Agent3ReviewedStartRecoveryStore(context)
        assertTrue(storeA.reserve(rigA, first))
        assertFalse(storeB.reserve(rigA, second))
        assertEquals(first, storeB.read("https://rig-a.example:8443"))
        assertFalse(storeB.clearIfMatches(rigA, second))
        assertEquals(first, storeA.read(rigA))
        assertNull(storeA.read(rigB))
        assertTrue(storeA.clearIfMatches(rigA, first))
        assertNull(storeB.read(rigA))
    }
}
