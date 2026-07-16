package dk.ternedal.modelrig.logic

import org.json.JSONObject

/**
 * The rig's NDJSON streams, as typed events -- and the rule that a stream is
 * only complete when it SAYS so.
 *
 * Every stream reader on the client used to end the same way: loop until the
 * body runs out, then return normally. But a proxy timeout, a dropped Tailscale
 * link or a crashed upstream ends the body exactly the same way a finished
 * answer does. So a truncated answer looked complete (and got persisted as a
 * finished turn), a failed pull said "Færdig" (1.58.39), a cloud turn showed a
 * blank bubble (1.58.36), and an interrupted voice turn silently never called
 * onDone at all. Same bug class, four places, three of them fixed one at a time.
 *
 * This is that rule in ONE place, as pure logic: [parse] turns a line into an
 * event, and [terminalFailure] states what an EOF without a terminal event
 * means. The readers keep only the transport. Table-tested (StreamContractTest)
 * with the historical bugs pinned by name.
 *
 * Two wire shapes, deliberately handled by one parser: Ollama's chat NDJSON
 * (`message.content`, `done`, `error`) as it passes through /chat and
 * /rag/chat, and the worker's typed voice events (`type: transcript|chunk|
 * done|error`). The rig already emits a terminal marker on all three -- this
 * side simply stops assuming one arrived.
 */
sealed class StreamEvent {
    /** A piece of the answer. */
    data class Delta(val text: String) : StreamEvent()

    /** RAG's leading header: which sources grounded the answer. */
    data class Sources(val names: List<String>) : StreamEvent()

    /** Voice: what the rig heard. */
    data class Transcript(val text: String) : StreamEvent()

    /** Voice: one spoken sentence, text + audio, in order. */
    data class Chunk(val index: Int, val text: String, val audioB64: String) : StreamEvent()

    /**
     * The stream said it finished. [trailingDelta] carries content that rode
     * along on the terminal line (Ollama may put the last token there); the
     * reader must emit it before finishing, or the answer loses its tail.
     */
    data class Done(
        val reply: String = "",
        val model: String? = null,
        val viaCloud: Boolean = false,
        val trailingDelta: String = "",
    ) : StreamEvent()

    /** The stream reported a failure in-band. Terminal. */
    data class Failure(val message: String, val status: Int = 0) : StreamEvent()

    /** Not part of the contract (keep-alives, unknown shapes, junk). */
    object Ignored : StreamEvent()
}

object StreamContract {
    fun parse(line: String): StreamEvent {
        val t = line.trim()
        if (t.isEmpty()) return StreamEvent.Ignored
        val o = runCatching { JSONObject(t) }.getOrNull() ?: return StreamEvent.Ignored

        // Voice's typed events come first: they are unambiguous.
        when (o.optString("type")) {
            "transcript" -> return StreamEvent.Transcript(o.optString("text"))
            "chunk" -> return StreamEvent.Chunk(
                o.optInt("index"), o.optString("text"), o.optString("audio_base64"),
            )
            "done" -> return StreamEvent.Done(
                reply = o.optString("reply"),
                model = o.optString("model").ifBlank { null },
                viaCloud = o.optBoolean("via_cloud", false),
            )
            "error" -> return StreamEvent.Failure(
                o.optString("detail").ifBlank { "ukendt fejl" }, o.optInt("status"),
            )
        }

        // A bare {"error": "..."} line. This is the one that used to vanish:
        // it has no message.content, so the old readers scored it as an empty
        // delta and dropped it, ending the stream with nothing to show.
        val err = o.optString("error")
        if (err.isNotEmpty()) return StreamEvent.Failure(err)

        if (o.optJSONArray("sources") != null) {
            val arr = o.getJSONArray("sources")
            val names = mutableListOf<String>()
            for (i in 0 until arr.length()) {
                val s = arr.optJSONObject(i)?.optString("source").orEmpty()
                if (s.isNotEmpty()) names.add(s)
            }
            return StreamEvent.Sources(names)
        }

        val content = o.optJSONObject("message")?.optString("content").orEmpty()
        if (o.optBoolean("done", false)) return StreamEvent.Done(trailingDelta = content)
        if (content.isNotEmpty()) return StreamEvent.Delta(content)
        return StreamEvent.Ignored
    }

    /**
     * What an exhausted stream means. Null = a real completion.
     *
     * The distinction matters to the person reading the screen: a truncated
     * answer and an answer that never started are different failures, and
     * neither is success.
     */
    fun terminalFailure(sawTerminal: Boolean, sawContent: Boolean): String? = when {
        sawTerminal -> null
        sawContent -> "svaret blev afbrudt undervejs — forbindelsen lukkede før modellen var færdig; prøv igen"
        else -> "intet svar modtaget (tom stream) — prøv igen"
    }
}
