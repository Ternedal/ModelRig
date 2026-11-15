package dk.ternedal.modelrig.ui

import androidx.test.core.app.ApplicationProvider
import dk.ternedal.modelrig.MainActivity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The in-app "Medier" entry opens the generate screen (#2275 C6 G1). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36])
class MediaEntryTest {
    @Test
    fun `the entry opens MainActivity on the generate screen and nothing else`() {
        val intent = MediaEntry.intent(ApplicationProvider.getApplicationContext())
        assertEquals(MainActivity::class.java.name, intent.component?.className)
        assertTrue(intent.getBooleanExtra(MainActivity.EXTRA_MEDIA_GENERATE, false))
        assertFalse("the gallery is reached from the generate screen, not opened directly",
            intent.getBooleanExtra(MainActivity.EXTRA_MEDIA_GALLERY, false))
        assertEquals(setOf(MainActivity.EXTRA_MEDIA_GENERATE), intent.extras!!.keySet())
        assertEquals("Medier", MediaEntry.LABEL)
    }
}
