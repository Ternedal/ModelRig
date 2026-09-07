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
    fun settingsSelectionComesFromActiveScreen() {
        val settings = kalivNavDestinations.single { it.screen == KalivScreen.SETTINGS }

        assertTrue(settings.isSelected(KalivScreen.SETTINGS))
        assertFalse(settings.isSelected(KalivScreen.CHAT))
    }

    @Test
    fun iconGlyphsArePresentationOnlyAndNotHumanLabels() {
        kalivIconRailDestinations.forEach { destination ->
            assertTrue(destination.iconGlyph.isNotBlank())
            assertFalse(destination.iconGlyph == destination.label)
        }
    }
}
