package dk.ternedal.modelrig.desktop.data

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertSame
import kotlin.test.assertTrue

class DesktopSettingPersistenceTest {
    @Test
    fun `successful write reports saved and forwards the exact setting once`() {
        val calls = mutableListOf<Pair<String, String>>()

        val result = DesktopSettingPersistence.save("localModel", "hermes3:8b") { key, value ->
            calls += key to value
        }

        assertSame(DesktopSettingSaveResult.Saved, result)
        assertEquals(listOf("localModel" to "hermes3:8b"), calls)
    }

    @Test
    fun `ordinary write failure is generic and never exposes value or exception text`() {
        val secretLikeValue = "internal-value-that-must-not-leak"
        val result = DesktopSettingPersistence.save("localUrl", secretLikeValue) { _, _ ->
            throw IllegalStateException("sqlite path and machine detail")
        }

        val failed = assertIs<DesktopSettingSaveResult.Failed>(result)
        assertEquals(
            "Indstillingen kunne ikke gemmes. Den tidligere værdi bruges stadig.",
            failed.userMessage,
        )
        assertFalse(failed.userMessage.contains(secretLikeValue))
        assertFalse(failed.userMessage.contains("sqlite"))
    }

    @Test
    fun `credential failure explicitly says secure save failed without exposing the credential`() {
        val credential = "super-secret-token"
        val result = DesktopSettingPersistence.save("deviceToken", credential) { _, _ ->
            throw IllegalArgumentException("DPAPI rejected super-secret-token")
        }

        val failed = assertIs<DesktopSettingSaveResult.Failed>(result)
        assertTrue(failed.userMessage.contains("sikkert"))
        assertTrue(failed.userMessage.contains("tidligere værdi"))
        assertFalse(failed.userMessage.contains(credential))
        assertFalse(failed.userMessage.contains("DPAPI"))
    }
}
