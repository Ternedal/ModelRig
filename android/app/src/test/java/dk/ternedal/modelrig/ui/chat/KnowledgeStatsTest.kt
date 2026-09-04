package dk.ternedal.modelrig.ui.chat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.TimeZone

class KnowledgeStatsTest {

    @Test
    fun `udsnit og dato skrives som rigen maaler dem`() {
        TimeZone.setDefault(TimeZone.getTimeZone("Europe/Copenhagen"))
        assertEquals("12 udsnit \u00b7 2/7 2026", knowledgeStatsLine(12, 1_783_000_000.0))
        assertEquals("1 udsnit \u00b7 2/7 2026", knowledgeStatsLine(1, 1_783_000_000.0))
    }

    @Test
    fun `manglende tidsstempel giver kun udsnit — ingen opdigtet dato`() {
        assertEquals("7 udsnit", knowledgeStatsLine(7, null))
        assertEquals("0 udsnit", knowledgeStatsLine(0, 0.0))
        assertEquals("3 udsnit", knowledgeStatsLine(3, Double.NaN))
    }

    @Test
    fun `datoformattering afviser ugyldige stempler`() {
        assertNull(formatIngestDate(null))
        assertNull(formatIngestDate(0.0))
        assertNull(formatIngestDate(-5.0))
        assertNull(formatIngestDate(Double.POSITIVE_INFINITY))
    }
}
