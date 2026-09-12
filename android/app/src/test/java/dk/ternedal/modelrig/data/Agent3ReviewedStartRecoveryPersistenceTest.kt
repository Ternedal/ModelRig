package dk.ternedal.modelrig.data

import android.content.Context
import org.junit.Assert.assertEquals
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
    fun `authority survives a new store instance and remains rig scoped`() {
        val rigA = "https://rig-a.example:8443/"
        val rigB = "https://rig-b.example:8443"
        val encoded = "{\"schema\":\"test-authority\"}"

        val firstProcessStore = Agent3ReviewedStartRecoveryStore(context)
        assertTrue(firstProcessStore.write(rigA, encoded))

        val restartedProcessStore = Agent3ReviewedStartRecoveryStore(context)
        assertEquals(encoded, restartedProcessStore.read("https://rig-a.example:8443"))
        assertNull(restartedProcessStore.read(rigB))

        assertTrue(restartedProcessStore.write(rigA, null))
        assertNull(Agent3ReviewedStartRecoveryStore(context).read(rigA))
    }
}
