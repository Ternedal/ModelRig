package dk.ternedal.modelrig.ui.chat

import dk.ternedal.modelrig.net.UsedChunk
import org.junit.Assert.assertEquals
import org.junit.Test

class CitationsTest {

    @Test
    fun `metalinjen viser rigens egne tal`() {
        assertEquals("Udsnit 3 · 71 % match", citationMeta(UsedChunk("a.md", 2, 0.7123, "")))
    }

    @Test
    fun `uden udsnitsnummer nummererer vi ikke selv`() {
        // Et tal vi fandt på ville pege et andet sted end rigens eget.
        assertEquals("42 % match", citationMeta(UsedChunk("a.md", null, 0.4234, "")))
    }

    @Test
    fun `score klippes til et meningsfuldt interval`() {
        assertEquals("Udsnit 1 · 100 % match", citationMeta(UsedChunk("a.md", 0, 1.9, "")))
        assertEquals("Udsnit 1 · 0 % match", citationMeta(UsedChunk("a.md", 0, -0.5, "")))
    }
}
