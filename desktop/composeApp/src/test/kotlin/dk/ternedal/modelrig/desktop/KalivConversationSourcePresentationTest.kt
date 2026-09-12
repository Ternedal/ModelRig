package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals

class KalivConversationSourcePresentationTest {
    @Test
    fun knownPersistedSourcesUseHumanLabels() {
        assertEquals("Rig", presentConversationSource("rig"))
        assertEquals("Cloud", presentConversationSource("cloud"))
        assertEquals("Dokumenter (RAG)", presentConversationSource("rag"))
        assertEquals("Værktøjer", presentConversationSource("tools"))
        assertEquals("Kilde ikke afgjort", presentConversationSource("pending"))
    }

    @Test
    fun knownValuesAreNormalizedWithoutExposingStorageFormatting() {
        assertEquals("Rig", presentConversationSource(" RIG "))
    }

    @Test
    fun unknownOrEmptySourcesFailClosedToNeutralCopy() {
        assertEquals("Kilde ukendt", presentConversationSource("future_internal_value"))
        assertEquals("Kilde ukendt", presentConversationSource(""))
    }
}
