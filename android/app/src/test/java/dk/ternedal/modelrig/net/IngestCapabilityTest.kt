package dk.ternedal.modelrig.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class IngestCapabilityTest {

    private val coreWorker = WorkerCapabilities.parse(
        """{"asr":false,"tts":false,"pdf":false,"docx":false,"pptx":false,"html":true,"cuda":false}"""
    )
    private val fuldWorker = WorkerCapabilities.parse(
        """{"asr":true,"tts":true,"pdf":true,"docx":true,"pptx":true,"html":true,"cuda":true}"""
    )

    @Test
    fun `en fuld rig blokerer ingenting`() {
        for (f in IngestCapability.Format.values()) {
            assertEquals(
                "$f skulle vaere tilladt",
                IngestCapability.Verdict.Allowed,
                IngestCapability.check(f, fuldWorker),
            )
        }
    }

    @Test
    fun `en core-worker blokerer pdf docx og pptx`() {
        for (f in listOf(
            IngestCapability.Format.PDF,
            IngestCapability.Format.DOCX,
            IngestCapability.Format.PPTX,
        )) {
            val v = IngestCapability.check(f, coreWorker)
            assertTrue("$f skulle vaere blokeret", v is IngestCapability.Verdict.Blocked)
            v as IngestCapability.Verdict.Blocked
            assertEquals(f, v.format)
            assertTrue("begrundelsen skal naevne formatet", v.reason.contains(f.visesSom))
            assertTrue("begrundelsen skal sige hvad der kan goeres", v.reason.contains("pip install"))
        }
    }

    @Test
    fun `ren tekst kan aldrig blokeres`() {
        // Vigtigst i hele filen: ingestText kraever ingen dependency. Ville
        // gaten kunne spaerre for tekst, havde den gjort appen ringere end
        // foer den fandtes.
        for (caps in listOf(coreWorker, fuldWorker, WorkerCapabilities.UNKNOWN)) {
            assertEquals(
                IngestCapability.Verdict.Allowed,
                IngestCapability.check(IngestCapability.Format.TEXT, caps),
            )
        }
    }

    @Test
    fun `en rig der ikke har svaret blokerer ingenting`() {
        // Tilbageholdenheden er sikkerhedsmodellen: et mislykket probe maa
        // ikke kunne amputere en app der virker.
        for (f in IngestCapability.Format.values()) {
            assertEquals(
                "$f skulle vaere tilladt paa ukendt rig",
                IngestCapability.Verdict.Allowed,
                IngestCapability.check(f, WorkerCapabilities.UNKNOWN),
            )
        }
    }

    @Test
    fun `en aeldre rig uden pptx-noeglen blokerer ikke pptx`() {
        // Praecis rigge fra foer #619. De KUNNE laese pptx; de sagde det bare
        // ikke. At gate paa fravaer ville amputere en rig der virker.
        val foer619 = WorkerCapabilities.parse(
            """{"asr":true,"tts":true,"pdf":true,"docx":true,"cuda":true}"""
        )
        assertEquals(
            IngestCapability.Verdict.Allowed,
            IngestCapability.check(IngestCapability.Format.PPTX, foer619),
        )
    }

    @Test
    fun `html blokeres kun hvis riggen udtrykkeligt siger nej og siger det er uventet`() {
        val underlig = WorkerCapabilities.parse("""{"html":false}""")
        val v = IngestCapability.check(IngestCapability.Format.HTML, underlig)
        assertTrue(v is IngestCapability.Verdict.Blocked)
        v as IngestCapability.Verdict.Blocked
        assertTrue("skal sige at det er uventet", v.reason.contains("uventet"))
    }
}
