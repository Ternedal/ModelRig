package dk.ternedal.modelrig.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Det vigtigste her er ikke at et "true" bliver til true. Det er at ALT ANDET
 * end et udtrykkeligt "false" bliver til true — så en rig der ikke svarer,
 * svarer forkert eller er ældre end feltet, ikke får appen til at slukke
 * funktioner der virker.
 */
@RunWith(RobolectricTestRunner::class)
class WorkerCapabilitiesTest {

    private val fuld = """
        {"asr":true,"tts":true,"pdf":true,"docx":true,"pptx":true,"html":true,"cuda":true}
    """.trimIndent()

    private val core = """
        {"asr":false,"tts":false,"pdf":false,"docx":false,"pptx":false,"html":true,"cuda":false}
    """.trimIndent()

    @Test
    fun `en fuld rig understoetter alt`() {
        val c = WorkerCapabilities.parse(fuld)
        assertTrue(c.known)
        assertTrue(c.supports(WorkerCapabilities.PDF))
        assertTrue(c.supports(WorkerCapabilities.ASR))
        assertEquals(emptyList<String>(), c.explicitlyMissing())
    }

    @Test
    fun `en core-worker siger fra paa de valgfrie`() {
        val c = WorkerCapabilities.parse(core)
        assertFalse(c.supports(WorkerCapabilities.PDF))
        assertFalse(c.supports(WorkerCapabilities.ASR))
        // html foelger med Python og er derfor sand selv paa en core-worker
        assertTrue(c.supports(WorkerCapabilities.HTML))
        assertEquals(
            listOf("asr", "cuda", "docx", "pdf", "pptx", "tts"),
            c.explicitlyMissing(),
        )
    }

    @Test
    fun `intet hentet betyder tilgaengelig, ikke utilgaengelig`() {
        val c = WorkerCapabilities.UNKNOWN
        assertFalse(c.known)
        assertTrue(c.supports(WorkerCapabilities.PDF))
        assertTrue(c.supports(WorkerCapabilities.ASR))
        assertEquals(emptyList<String>(), c.explicitlyMissing())
    }

    @Test
    fun `en aeldre rig uden pptx-noeglen regnes som havende pptx`() {
        // Praecis situationen foer #619: rigge der kun rapporterede fem noegler.
        // De KUNNE indlaese pptx; de sagde det bare ikke. At gate paa fravaer
        // ville amputere en rig der virker.
        val c = WorkerCapabilities.parse(
            """{"asr":true,"tts":true,"pdf":true,"docx":true,"cuda":true}"""
        )
        assertTrue(c.known)
        assertTrue(c.supports(WorkerCapabilities.PPTX))
        assertFalse(c.explicitlyMissing().contains("pptx"))
    }

    @Test
    fun `ulaeseligt svar giver ukendt, ikke et nej`() {
        for (skrald in listOf(null, "", "   ", "ikke json", "[1,2,3]", "<html>502</html>")) {
            val c = WorkerCapabilities.parse(skrald)
            assertFalse("skulle vaere ukendt: $skrald", c.known)
            assertTrue("skulle understoette alt: $skrald", c.supports(WorkerCapabilities.PDF))
        }
    }

    @Test
    fun `en noegle der ikke er boolean er ikke et nej`() {
        // "pdf":"nej" er et svar vi ikke forstaar. Vi gaetter ikke paa at det
        // betyder falsk -- vi lader vaere med at gate.
        val c = WorkerCapabilities.parse("""{"pdf":"nej","asr":0,"tts":null,"docx":true}""")
        assertTrue(c.supports(WorkerCapabilities.PDF))
        assertTrue(c.supports(WorkerCapabilities.ASR))
        assertTrue(c.supports(WorkerCapabilities.TTS))
        assertTrue(c.supports(WorkerCapabilities.DOCX))
        assertEquals(emptyList<String>(), c.explicitlyMissing())
    }

    @Test
    fun `en ukendt fremtidig evne kan slaas op uden at vaere kendt paa forhaand`() {
        val c = WorkerCapabilities.parse("""{"pdf":true,"ocr":false}""")
        assertFalse(c.supports("ocr"))
        assertTrue(c.supports("noget-der-ikke-findes"))
    }
}
