package dk.ternedal.modelrig.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class VoiceCapabilityTest {

    private fun caps(json: String) = WorkerCapabilities.parse(json)

    @Test
    fun `en rig med asr og tts kan foere en talt tur`() {
        val v = VoiceCapability.check(caps("""{"asr":true,"tts":true,"pdf":false}"""))
        assertEquals(VoiceCapability.Verdict.Allowed, v)
    }

    @Test
    fun `core-worker uden begge dele blokeres med begge navngivet`() {
        val v = VoiceCapability.check(caps("""{"asr":false,"tts":false}"""))
        assertTrue(v is VoiceCapability.Verdict.Blocked)
        v as VoiceCapability.Verdict.Blocked
        assertEquals(listOf("asr", "tts"), v.missing)
        assertTrue(v.reason.contains("faster-whisper"))
        assertTrue(v.reason.contains("piper-tts"))
    }

    @Test
    fun `kun asr mangler er stadig et nej`() {
        // En halv pipeline er ikke en delvis funktion -- turen er umulig.
        val v = VoiceCapability.check(caps("""{"asr":false,"tts":true}"""))
        assertTrue(v is VoiceCapability.Verdict.Blocked)
        v as VoiceCapability.Verdict.Blocked
        assertEquals(listOf("asr"), v.missing)
        assertTrue(v.reason.contains("tale-til-tekst"))
        assertTrue("maa ikke naevne piper naar kun asr mangler",
            !v.reason.contains("piper-tts"))
    }

    @Test
    fun `kun tts mangler er ogsaa et nej`() {
        val v = VoiceCapability.check(caps("""{"asr":true,"tts":false}"""))
        assertTrue(v is VoiceCapability.Verdict.Blocked)
        v as VoiceCapability.Verdict.Blocked
        assertEquals(listOf("tts"), v.missing)
        assertTrue(v.reason.contains("tekst-til-tale"))
    }

    @Test
    fun `begrundelsen siger at cloud ikke redder det`() {
        // Den vigtigste saetning i hele fladen: voice_pipeline.converse siger
        // selv "ASR/TTS cannot move: the models live here". Uden den linje
        // vil folk saette en cloud-noegle og undre sig.
        val v = VoiceCapability.check(caps("""{"asr":false,"tts":false}""")) as VoiceCapability.Verdict.Blocked
        assertTrue(v.reason.contains("Cloud hjælper ikke"))
    }

    @Test
    fun `en rig der ikke har svaret blokerer ikke stemme`() {
        assertEquals(
            VoiceCapability.Verdict.Allowed,
            VoiceCapability.check(WorkerCapabilities.UNKNOWN),
        )
    }

    @Test
    fun `en aeldre rig uden noeglerne blokerer ikke stemme`() {
        assertEquals(
            VoiceCapability.Verdict.Allowed,
            VoiceCapability.check(caps("""{"pdf":true,"docx":true}""")),
        )
    }
}
