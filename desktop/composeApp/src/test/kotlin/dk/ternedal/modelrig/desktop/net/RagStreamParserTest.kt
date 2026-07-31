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
        // Eksemplet var oprindeligt en fase-linje; den er siden blevet en del af
        // kontrakten, saa her staar nu en linje vi FAKTISK ikke kender.
        val stream = listOf(
            """{"keepalive":true}""",
            """{"sources":[{"source":"noter.pdf"}]}""",
            """{"message":{"content":"svar"}}""",
        )
        val events = stream.map { RagStreamParser.parse(it) }
        assertEquals(RagStreamParser.Event.Ignored, events[0])
        assertEquals(RagStreamParser.Event.Sources(listOf("noter.pdf")), events[1])
        assertEquals(RagStreamParser.Event.Delta("svar"), events[2])
    }

    @Test
    fun bareErrorLineBecomesAFailure() {
        // Den linje forsvandt tavst foer: ingen message.content -> tom delta.
        // Workeren udsender den netop for at efterlade en GRUND paa traaden.
        assertEquals(
            RagStreamParser.Event.Failure("ollama nede"),
            RagStreamParser.parse("""{"error":"ollama nede"}"""),
        )
    }

    @Test
    fun terminalLineIsRecognisedAndCanCarryTrailingText() {
        assertEquals(
            RagStreamParser.Event.Done(""),
            RagStreamParser.parse("""{"message":{"content":""},"done":true}"""),
        )
        assertEquals(
            RagStreamParser.Event.Done("sidste ord"),
            RagStreamParser.parse("""{"message":{"content":"sidste ord"},"done":true}"""),
        )
    }

    @Test
    fun terminalFailureDistinguishesTruncatedFromEmpty() {
        assertEquals(null, RagStreamParser.terminalFailure(sawTerminal = true, sawContent = true))
        assertEquals(null, RagStreamParser.terminalFailure(sawTerminal = true, sawContent = false))
        assertEquals(
            "svaret blev afbrudt undervejs — forbindelsen lukkede før modellen var færdig; prøv igen",
            RagStreamParser.terminalFailure(sawTerminal = false, sawContent = true),
        )
        assertEquals(
            "intet svar modtaget (tom stream) — prøv igen",
            RagStreamParser.terminalFailure(sawTerminal = false, sawContent = false),
        )
    }

    @Test
    fun phaseLineBecomesATypedPhaseEvent() {
        assertEquals(
            RagStreamParser.Event.Phase("searching"),
            RagStreamParser.parse("""{"phase":"searching"}"""),
        )
        assertEquals(
            RagStreamParser.Event.Phase("generating"),
            RagStreamParser.parse("""{"phase":"generating"}"""),
        )
    }

    @Test
    fun theSourcesHeaderStillSurvivesAPrecedingPhaseLine() {
        // Praecis den raekkefoelge workeren nu udsender. Med den gamle
        // positionsafhaengige loekke ville fase-linjen forbruge "first" og
        // kildechipsene ville forsvinde uden en fejl.
        val stream = listOf(
            """{"phase":"searching"}""",
            """{"sources":[{"source":"noter.pdf"}]}""",
            """{"phase":"generating"}""",
            """{"message":{"content":"svar"}}""",
        ).map { RagStreamParser.parse(it) }
        assertEquals(RagStreamParser.Event.Phase("searching"), stream[0])
        assertEquals(RagStreamParser.Event.Sources(listOf("noter.pdf")), stream[1])
        assertEquals(RagStreamParser.Event.Phase("generating"), stream[2])
        assertEquals(RagStreamParser.Event.Delta("svar"), stream[3])
    }

    @Test
    fun unknownEventsAreIgnoredNotShownAsText() {
        // Bagudkompatibilitet: en ny event-type maa aldrig lande i chatteksten.
        assertEquals(
            RagStreamParser.Event.Ignored,
            RagStreamParser.parse("""{"telemetry":{"tokens_per_second":42}}"""),
        )
    }

    @Test
    fun aPhaseLineWithExtraFieldsStillParsesAsThatPhase() {
        // Workeren maa gerne udvide fase-linjen senere uden at braekke klienten.
        assertEquals(
            RagStreamParser.Event.Phase("tool_run"),
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
