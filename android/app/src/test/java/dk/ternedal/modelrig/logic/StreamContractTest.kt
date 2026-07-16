package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The wire shapes the rig actually emits, and what each must mean. The named
 * rows at the bottom pin bugs that shipped: a stream reader that "worked" is
 * exactly what these lines looked like on the day it lied.
 */
class StreamContractTest {

    private fun parse(line: String) = StreamContract.parse(line)

    @Test
    fun ollamaChatShape() {
        assertEquals(
            StreamEvent.Delta("Hej"),
            parse("""{"message":{"role":"assistant","content":"Hej"},"done":false}"""),
        )
        assertEquals(
            StreamEvent.Done(trailingDelta = ""),
            parse("""{"message":{"content":""},"done":true}"""),
        )
    }

    @Test
    fun theTerminalLineMayCarryTheLastToken() {
        // If the reader only checked `done` it would drop this token; if it
        // only checked content it would never finish. Both, in order.
        val ev = parse("""{"message":{"content":"!"},"done":true}""")
        assertEquals(StreamEvent.Done(trailingDelta = "!"), ev)
    }

    @Test
    fun ragSourcesHeader() {
        val ev = parse("""{"sources":[{"source":"noter.pdf","score":0.7,"chunks":2},{"source":"cv.docx","score":0.4}]}""")
        assertEquals(StreamEvent.Sources(listOf("noter.pdf", "cv.docx")), ev)
    }

    @Test
    fun voiceTypedEvents() {
        assertEquals(StreamEvent.Transcript("hvad er klokken"), parse("""{"type":"transcript","text":"hvad er klokken"}"""))
        assertEquals(
            StreamEvent.Chunk(0, "Klokken er ti.", "QUJD"),
            parse("""{"type":"chunk","index":0,"text":"Klokken er ti.","audio_base64":"QUJD"}"""),
        )
        assertEquals(
            StreamEvent.Done(reply = "Klokken er ti.", model = "hermes3:8b", viaCloud = false),
            parse("""{"type":"done","reply":"Klokken er ti.","model":"hermes3:8b","via_cloud":false}"""),
        )
        assertEquals(
            StreamEvent.Failure("ASR-backend mangler", 503),
            parse("""{"type":"error","status":503,"detail":"ASR-backend mangler"}"""),
        )
    }

    @Test
    fun junkNeverCrashesTheReader() {
        assertEquals(StreamEvent.Ignored, parse("not json at all"))
        assertEquals(StreamEvent.Ignored, parse(""))
        assertEquals(StreamEvent.Ignored, parse("   "))
        assertEquals(StreamEvent.Ignored, parse("""{"keepalive":true}"""))
    }

    // --- historical bugs, pinned by name ------------------------------------

    @Test
    fun anInStreamErrorIsNeverAnEmptyDelta() {
        // The rig path swallowed this: no message.content -> scored as an empty
        // delta -> dropped -> the stream ended with nothing on screen and no
        // reason given. (Same shape fixed in CloudClient 1.58.33 and desktop
        // 1.58.46; the rig reader still had it until 1.58.49.)
        val ev = parse("""{"error":"model runner has crashed"}""")
        assertEquals(StreamEvent.Failure("model runner has crashed"), ev)
    }

    @Test
    fun eofWithoutTerminalIsNeverSuccess() {
        // The whole point. A proxy timeout ends the body exactly like a
        // finished answer does, so "the body ran out" must not mean "done".
        assertNull("a stream that said done is complete",
            StreamContract.terminalFailure(sawTerminal = true, sawContent = true))

        val truncated = StreamContract.terminalFailure(sawTerminal = false, sawContent = true)
        assertNotNull("content but no terminal marker = truncated, not complete", truncated)
        assertTrue("the message must say it was cut off", truncated!!.contains("afbrudt"))

        val empty = StreamContract.terminalFailure(sawTerminal = false, sawContent = false)
        assertNotNull("no content and no terminal marker = failure", empty)
        assertTrue("an empty stream must be named as such", empty!!.contains("tom stream"))
        assertTrue("truncated and empty are different failures", truncated != empty)
    }

    @Test
    fun aDoneMarkerWithoutContentStillCompletes() {
        // The RAG no-match branch answers "I don't know" and marks done in one
        // line; and an empty-but-terminated stream is a real (if useless)
        // answer, not a connection failure. Don't turn it into one.
        val ev = parse("""{"message":{"content":"Jeg kan ikke finde noget relevant."},"done":true}""")
        assertEquals(StreamEvent.Done(trailingDelta = "Jeg kan ikke finde noget relevant."), ev)
        assertNull(StreamContract.terminalFailure(sawTerminal = true, sawContent = false))
    }
}
