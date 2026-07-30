package dk.ternedal.modelrig.desktop.net

import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * Pinner at `/rag/chat`-stroemmen afkodes efter FORM, ikke efter position.
 *
 * Den vigtigste test er [sourcesHeaderSurvivesAPrecedingUnknownLine]: med den
 * gamle `if (first)`-loekke ville en ukendt linje foerst i stroemmen forbruge
 * `first`, hvorefter kildehovedet faldt igennem til indholdsgrenen og
 * kildechipsene forsvandt uden en fejl. Fase-signalet (ROADMAP) er praecis en
 * saadan linje.
 */
class RagStreamParserTest {

    @Test
    fun sourcesHeaderIsRecognised() {
        val event = RagStreamParser.parse(
            """{"sources":[{"source":"noter.pdf"},{"source":"cv.docx"}]}""",
        )
        assertEquals(RagStreamParser.Event.Sources(listOf("noter.pdf", "cv.docx")), event)
    }

    @Test
    fun contentLineBecomesADelta() {
        val event = RagStreamParser.parse("""{"message":{"content":"hej"}}""")
        assertEquals(RagStreamParser.Event.Delta("hej"), event)
    }

    @Test
    fun sourcesHeaderSurvivesAPrecedingUnknownLine() {
        // Den regression, formbaseret dispatch findes for at forhindre.
        val stream = listOf(
            """{"phase":"searching"}""",
            """{"sources":[{"source":"noter.pdf"}]}""",
            """{"message":{"content":"svar"}}""",
        )
        val events = stream.map { RagStreamParser.parse(it) }
        assertEquals(RagStreamParser.Event.Ignored, events[0])
        assertEquals(RagStreamParser.Event.Sources(listOf("noter.pdf")), events[1])
        assertEquals(RagStreamParser.Event.Delta("svar"), events[2])
    }

    @Test
    fun unknownEventsAreIgnoredNotShownAsText() {
        // Bagudkompatibilitet: en ny event-type maa aldrig lande i chatteksten.
        assertEquals(
            RagStreamParser.Event.Ignored,
            RagStreamParser.parse("""{"phase":"tool_run","tool":"rig_status"}"""),
        )
    }

    @Test
    fun blankAndMalformedLinesAreIgnored() {
        assertEquals(RagStreamParser.Event.Ignored, RagStreamParser.parse(""))
        assertEquals(RagStreamParser.Event.Ignored, RagStreamParser.parse("   "))
        assertEquals(RagStreamParser.Event.Ignored, RagStreamParser.parse("ikke json"))
        assertEquals(RagStreamParser.Event.Ignored, RagStreamParser.parse("""{"message":{"content":""}}"""))
    }

    @Test
    fun emptySourceNamesAreDroppedButTheHeaderStillCounts() {
        val event = RagStreamParser.parse("""{"sources":[{"source":""},{"source":"a.md"}]}""")
        assertEquals(RagStreamParser.Event.Sources(listOf("a.md")), event)
        assertEquals(RagStreamParser.Event.Sources(emptyList()), RagStreamParser.parse("""{"sources":[]}"""))
    }
}
