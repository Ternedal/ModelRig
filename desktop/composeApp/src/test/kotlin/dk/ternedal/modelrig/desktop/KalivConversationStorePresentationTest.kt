package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.data.DesktopChatDb
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
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

    private val preset = DesktopChatDb.PresetMeta(7, "rig", "Kort", "Svar kort")

    @Test
    fun aSaveThatSucceedsIsNotReportedAsFailedWhenTheReloadFails() {
        var saves = 0
        val outcome = mutatePresetsThenReload(
            PresetStoreOperation.SAVE,
            mutate = { saves++ },
            reload = { error("database is locked") },
        )
        assertEquals(1, saves)
        assertTrue(outcome.mutated, "the save happened; the form must close so it cannot be inserted twice")
        assertEquals(PresetStoreOperation.LOAD, outcome.error, "the failure to report is the reload, not the save")
        assertNull(outcome.presets, "no fresh list: the caller keeps what it shows")
    }

    @Test
    fun aFailedMutationNamesItselfAndNeverReloads() {
        var reloads = 0
        for (operation in listOf(PresetStoreOperation.SAVE, PresetStoreOperation.DELETE)) {
            val outcome = mutatePresetsThenReload(operation, mutate = { error("disk full") }, reload = { reloads++; listOf(preset) })
            assertFalse(outcome.mutated)
            assertEquals(operation, outcome.error)
            assertNull(outcome.presets)
        }
        assertEquals(0, reloads, "nothing changed, so there is nothing to read back")
    }

    @Test
    fun aMutationAndReloadThatBothSucceedGiveTheFreshListAndNoError() {
        val outcome = mutatePresetsThenReload(PresetStoreOperation.DELETE, mutate = {}, reload = { listOf(preset) })
        assertTrue(outcome.mutated)
        assertEquals(listOf(preset), outcome.presets)
        assertNull(outcome.error)
        val empty = mutatePresetsThenReload(PresetStoreOperation.DELETE, mutate = {}, reload = { emptyList() })
        assertEquals(emptyList(), empty.presets, "an empty store after a delete is a loaded list, not a missing one")
    }

    @Test
    fun togglingTheSaveFormKeepsAFailedLoadAndDropsAFailedMutation() {
        assertEquals(PresetStoreOperation.LOAD, presetErrorAfterFormToggle(PresetStoreOperation.LOAD))
        assertNull(presetErrorAfterFormToggle(PresetStoreOperation.SAVE))
        assertNull(presetErrorAfterFormToggle(PresetStoreOperation.DELETE))
        assertNull(presetErrorAfterFormToggle(null))
    }
}
