package dk.ternedal.modelrig.voice

import androidx.compose.runtime.mutableStateListOf
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

/** Codex #2360 4507627138: the voice turn must keep owning its bubble through equal-value updates. */
class OwnedReplySlotTest {
    private data class Bubble(val text: String, val streaming: Boolean = true)

    private fun lists(): List<MutableList<Bubble>> = listOf(mutableStateListOf(), mutableListOf())

    @Test fun anEqualUpdateKeepsOwnershipSoLaterTextStillArrives() {
        for (list in lists()) {
            list.add(Bubble("user"))
            val bubble = Bubble("Hej")
            list.add(bubble)
            var owned: Bubble? = bubble

            // A chunk that changes nothing visible, e.g. one that was only an emoji.
            owned = updateOwnedSlot(list, 1, owned) { it.copy(text = "Hej") }
            assertSame("the turn still owns the stored instance", list[1], owned)

            owned = updateOwnedSlot(list, 1, owned) { it.copy(text = "Hej med dig") }
            owned = updateOwnedSlot(list, 1, owned) { it.copy(streaming = false) }
            assertEquals(Bubble("Hej med dig", streaming = false), list[1])
            assertSame(list[1], owned)
        }
    }

    @Test fun aListRefilledByAnotherConversationIsNeverTouched() {
        for (list in lists()) {
            val bubble = Bubble("Hej")
            list.add(Bubble("user"))
            list.add(bubble)
            list.clear()
            list.add(Bubble("other user"))
            list.add(Bubble("Hej")) // equal to the turn's bubble, but not the turn's instance

            val owned = updateOwnedSlot(list, 1, bubble) { it.copy(text = "late chunk") }
            assertSame(bubble, owned)
            assertEquals(listOf(Bubble("other user"), Bubble("Hej")), list.toList())
        }
    }

    @Test fun removingTheBubbleEndsOwnership() {
        for (list in lists()) {
            val bubble = Bubble("")
            list.add(Bubble("user"))
            list.add(bubble)

            val owned = updateOwnedSlot(list, 1, bubble) { if (it.text.isBlank()) null else it }
            assertNull(owned)
            assertEquals(listOf(Bubble("user")), list.toList())
            assertNull(updateOwnedSlot(list, 1, owned) { error("no write without ownership") })
        }
    }

    @Test fun aRealChangeIsStoredAndOwned() {
        for (list in lists()) {
            val bubble = Bubble("Hej")
            list.add(bubble)
            val owned = updateOwnedSlot(list, 0, bubble) { it.copy(text = "Hej igen") }
            assertTrue(owned !== bubble)
            assertSame(list[0], owned)
        }
    }
}
