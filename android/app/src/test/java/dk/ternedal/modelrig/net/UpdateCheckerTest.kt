package dk.ternedal.modelrig.net

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdateCheckerTest {

    @Test
    fun `opgradering fra 1_58_x til 2_0_0 tilbydes`() {
        assertTrue(UpdateChecker.isNewer("1.58.153", "2.0.0"))
    }

    @Test
    fun `samme version tilbydes ikke`() {
        assertFalse(UpdateChecker.isNewer("2.0.0", "2.0.0"))
    }

    @Test
    fun `nedgradering tilbydes aldrig`() {
        assertFalse(UpdateChecker.isNewer("2.0.0", "1.58.153"))
        assertFalse(UpdateChecker.isNewer("2.1.0", "2.0.9"))
    }

    @Test
    fun `patch og minor op tilbydes`() {
        assertTrue(UpdateChecker.isNewer("2.0.0", "2.0.1"))
        assertTrue(UpdateChecker.isNewer("2.0.9", "2.1.0"))
    }

    @Test
    fun `v-praefiks haandteres`() {
        assertTrue(UpdateChecker.isNewer("v2.0.0", "v2.0.1"))
    }

    @Test
    fun `misdannede versioner tilbydes aldrig`() {
        assertFalse(UpdateChecker.isNewer("2.0.0", "ikke-en-version"))
        assertFalse(UpdateChecker.isNewer("snavs", "2.0.1"))
        assertFalse(UpdateChecker.isNewer("2.0", "2.0.1.4"))
    }
}
