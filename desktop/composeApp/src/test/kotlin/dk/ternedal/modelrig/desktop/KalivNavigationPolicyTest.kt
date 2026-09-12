package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class KalivNavigationPolicyTest {
    @Test
    fun destinationsHaveOneCanonicalHumanLabelPerScreen() {
        assertEquals(KalivScreen.entries.toSet(), kalivNavDestinations.map { it.screen }.toSet())
        assertEquals(kalivNavDestinations.size, kalivNavDestinations.map { it.screen }.distinct().size)
        assertTrue(kalivNavDestinations.all { it.label.isNotBlank() })
    }

    @Test
    fun iconRailUsesExpectedCanonicalDestinationsAndLabels() {
        assertEquals(
            listOf(
                KalivScreen.CHAT,
                KalivScreen.AGENT,
                KalivScreen.COMPUTER,
                KalivScreen.MODELS,
                KalivScreen.SETTINGS,
            ),
            kalivIconRailDestinations.map { it.screen },
        )
        assertEquals(
            listOf("Chat", "Agent", "Computer-use", "Modeller", "Indstillinger"),
            kalivIconRailDestinations.map { it.label },
        )
    }

    @Test
    fun displayedSettingsPanelOverridesChatContentSelection() {
        assertEquals(
            KalivScreen.SETTINGS,
            desktopNavigationSelection(
                activeScreen = KalivScreen.CHAT,
                showSettings = true,
                showModels = false,
            ),
        )
    }

    @Test
    fun displayedModelsPanelOverridesChatContentSelection() {
        assertEquals(
            KalivScreen.MODELS,
            desktopNavigationSelection(
                activeScreen = KalivScreen.CHAT,
                showSettings = false,
                showModels = true,
            ),
        )
    }

    @Test
    fun normalContentScreensRemainTheirOwnSelection() {
        assertEquals(
            KalivScreen.CHAT,
            desktopNavigationSelection(KalivScreen.CHAT, showSettings = false, showModels = false),
        )
        assertEquals(
            KalivScreen.AGENT,
            desktopNavigationSelection(KalivScreen.AGENT, showSettings = false, showModels = false),
        )
        assertEquals(
            KalivScreen.COMPUTER,
            desktopNavigationSelection(KalivScreen.COMPUTER, showSettings = false, showModels = false),
        )
    }

    @Test
    fun latentPanelFlagsDoNotOverrideAgentOrComputerContent() {
        assertEquals(
            KalivScreen.AGENT,
            desktopNavigationSelection(KalivScreen.AGENT, showSettings = true, showModels = true),
        )
        assertEquals(
            KalivScreen.COMPUTER,
            desktopNavigationSelection(KalivScreen.COMPUTER, showSettings = true, showModels = true),
        )
    }

    @Test
    fun settingsPanelWinsIfImpossibleChatPanelStateLeaksThrough() {
        assertEquals(
            KalivScreen.SETTINGS,
            desktopNavigationSelection(KalivScreen.CHAT, showSettings = true, showModels = true),
        )
    }

    @Test
    fun iconGlyphsArePresentationOnlyAndNotHumanLabels() {
        kalivIconRailDestinations.forEach { destination ->
            assertTrue(destination.iconGlyph.isNotBlank())
            assertFalse(destination.iconGlyph == destination.label)
        }
    }
}
