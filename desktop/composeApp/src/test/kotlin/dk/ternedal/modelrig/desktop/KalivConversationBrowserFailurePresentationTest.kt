package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals

class KalivConversationBrowserFailurePresentationTest {
    @Test
    fun browserFailuresUseOperationSpecificHumanCopy() {
        assertEquals(
            "Kunne ikke hente samtaler.",
            presentConversationBrowserFailure(KalivConversationBrowserFailure.LOAD),
        )
        assertEquals(
            "Kunne ikke omdøbe samtalen.",
            presentConversationBrowserFailure(KalivConversationBrowserFailure.RENAME),
        )
        assertEquals(
            "Kunne ikke kopiere samtalen.",
            presentConversationBrowserFailure(KalivConversationBrowserFailure.COPY),
        )
        assertEquals(
            "Kunne ikke slette samtalen.",
            presentConversationBrowserFailure(KalivConversationBrowserFailure.DELETE),
        )
    }
}
