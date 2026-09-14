package dk.ternedal.modelrig.desktop.net

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class ToolsClientPrivacyTest {
    @Test
    fun serverFailurePresentationCarriesOnlyOperationAndStatus() {
        val rendered = toolsFailureMessage("tools chat", 500)
        assertEquals("tools chat failed (500)", rendered)
        assertFalse(rendered.contains("Bearer"))
        assertFalse(rendered.contains("/data/"))
        assertFalse(rendered.contains("token="))
    }

    @Test
    fun streamedFailurePresentationDoesNotNeedRawServerText() {
        assertEquals("tools chat failed", toolsFailureMessage("tools chat"))
    }
}
