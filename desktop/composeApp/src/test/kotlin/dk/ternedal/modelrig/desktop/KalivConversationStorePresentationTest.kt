package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.data.DesktopChatDb
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** #973: storage failures in the conversation browser are states and fixed copy, never raw exception text. */
class KalivConversationStorePresentationTest {
    private val meta = DesktopChatDb.ConvMeta(1L, "titel", "rig", "local", 0L)

    @Test
    fun aFailedLoadIsAStateNotAnEmptyList() {
        val failed = loadConversationList { throw IllegalStateException("database is locked (/home/x/.kaliv/chat.db)") }
        assertTrue(failed is ConversationListState.Failed)
        assertEquals(emptyList(), failed.conversations)
        val loaded = loadConversationList { listOf(meta) }
        assertTrue(loaded is ConversationListState.Loaded)
        assertEquals(listOf(meta), loaded.conversations)
        val empty = loadConversationList { emptyList() }
        assertTrue(empty is ConversationListState.Loaded, "an empty store is a loaded state, not a failure")
    }

    @Test
    fun presetOperationsHaveFixedDanishCopyToo() {
        val all = PresetStoreOperation.values().map { presentPresetStoreError(it) }
        assertEquals(all.size, all.toSet().size)
        for (text in all) assertFalse(text.contains("Exception") || text.contains("/") || text.contains(":"), text)
        assertEquals("Forudindstillingen kunne ikke gemmes", presentPresetStoreError(PresetStoreOperation.SAVE))
    }

    @Test
    fun everyOperationHasFixedDanishCopyWithoutTechnicalDetail() {
        val all = ConversationStoreOperation.values().map { presentConversationStoreError(it) }
        assertEquals(all.size, all.toSet().size, "each operation names itself")
        for (text in all) {
            assertTrue(text.isNotBlank())
            assertFalse(text.contains("Exception") || text.contains("/") || text.contains("sqlite", ignoreCase = true) || text.contains("jdbc", ignoreCase = true), text)
        }
        assertEquals("Samtalerne kunne ikke indlæses fra den lokale database", presentConversationStoreError(ConversationStoreOperation.LOAD))
        assertEquals("Samtalen kunne ikke slettes", presentConversationStoreError(ConversationStoreOperation.DELETE))
    }
}
