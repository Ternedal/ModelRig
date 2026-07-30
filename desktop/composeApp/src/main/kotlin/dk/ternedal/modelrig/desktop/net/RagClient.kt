package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

@Serializable
private data class RagChatRequest(
    val query: String,
    val top_k: Int = 4,
    val model: String? = null,
    val source: String? = null,
)

@Serializable
private data class RagSourceHit(val source: String = "")

@Serializable
private data class RagSourcesLine(val sources: List<RagSourceHit>? = null)

@Serializable
private data class RagMsg(val content: String = "")

@Serializable
private data class RagContentLine(
    val message: RagMsg = RagMsg(),
    val done: Boolean = false,
)

@Serializable
private data class RagErrorLine(val error: String = "")

@Serializable
private data class RagSourceEntry(val source: String = "")

@Serializable
private data class RagSourceListResponse(val sources: List<RagSourceEntry> = emptyList())

/**
 * Hvad en linje i `/rag/chat`-stroemmen ER -- afgjort af dens FORM, ikke dens
 * plads i stroemmen.
 *
 * Den tidligere loekke genkendte kildehovedet med `if (first)`. Det virkede,
 * fordi hovedet altid kom foerst, men det gjorde parseren afhaengig af
 * raekkefoelgen: den dag workeren udsender en linje foer hovedet -- fx
 * fase-signalet (ROADMAP, fase-signal) -- ville `first` blive brugt op paa den
 * linje, hovedet ville falde igennem til indholdsgrenen, og kildechipsene
 * ville forsvinde UDEN en fejl. En tavs forsvinding er den dyreste slags.
 *
 * Formbaseret dispatch gaer det umuligt og giver samtidig paritet med Androids
 * `StreamContract`, som allerede afgoer efter form. Ukendte linjer bliver
 * [Event.Ignored] -- praecis som Androids `StreamEvent.Ignored` -- saa nye
 * event-typer er additive og bagudkompatible.
 */
internal object RagStreamParser {
    private val json = Json { ignoreUnknownKeys = true }

    internal sealed interface Event {
        data class Sources(val names: List<String>) : Event
        data class Delta(val text: String) : Event

        /** Workerens terminale linje. `trailingDelta` kan baere sidste tekst. */
        data class Done(val trailingDelta: String = "") : Event

        /**
         * En bar `{"error": "..."}` fra workeren.
         *
         * Den linje forsvandt tavst her: den har ingen `message.content`, saa
         * den gamle afkodning gav en tom delta og droppede den. Workeren
         * udsender den netop for at efterlade en GRUND paa traaden naar Ollama
         * doer midt i et svar (`main_impl.py`, /rag/chat). Uden dette tilfaelde
         * saa brugeren et afbrudt svar uden aarsag.
         */
        data class Failure(val message: String) : Event

        data object Ignored : Event
    }

    fun parse(line: String): Event {
        if (line.isBlank()) return Event.Ignored
        val sources = runCatching {
            json.decodeFromString(RagSourcesLine.serializer(), line).sources
        }.getOrNull()
        if (sources != null) {
            return Event.Sources(sources.map { it.source }.filter { it.isNotEmpty() })
        }
        val error = runCatching {
            json.decodeFromString(RagErrorLine.serializer(), line).error
        }.getOrDefault("")
        if (error.isNotEmpty()) return Event.Failure(error)
        val content = runCatching {
            json.decodeFromString(RagContentLine.serializer(), line)
        }.getOrNull() ?: return Event.Ignored
        if (content.done) return Event.Done(content.message.content)
        return if (content.message.content.isNotEmpty()) {
            Event.Delta(content.message.content)
        } else {
            Event.Ignored
        }
    }

    /**
     * Hvad en udtoemt stroem betyder. Null = en aegte fuldfoerelse.
     *
     * Samme ordlyd som Androids `StreamContract.terminalFailure`, saa de to
     * klienter siger det samme til den samme bruger: et afbrudt svar og et
     * svar der aldrig startede er forskellige fejl, og ingen af dem er succes.
     */
    fun terminalFailure(sawTerminal: Boolean, sawContent: Boolean): String? = when {
        sawTerminal -> null
        sawContent -> "svaret blev afbrudt undervejs — forbindelsen lukkede før modellen var færdig; prøv igen"
        else -> "intet svar modtaget (tom stream) — prøv igen"
    }
}

/**
 * Client for the ModelRig backend's RAG endpoints (`/api/v1/rag/chat`,
 * `/api/v1/rag/sources`). Deliberately separate from `OllamaClient`/
 * `ChatRouter`: RAG only makes sense against the backend+worker, never local
 * Ollama directly or Ollama Cloud, so it isn't part of the local/cloud
 * auto-fallback -- it's its own explicit mode.
 *
 * Mirrors Android's `ModelRigClient.ragChatStream()` / `listRagSources()`
 * exactly (same request/response shapes, already verified against the
 * worker's actual contract there): first NDJSON line is a sources header
 * (`{"sources":[{"source":...}]}`), then chat-shaped lines
 * (`{"message":{"content":...}}`).
 *
 * Known simplification (same as Android): single-shot per question -- the
 * worker's `/rag/chat` takes one `query` string, not a message list, so prior
 * conversation turns aren't fed back in as context.
 */
class RagClient(private val baseUrl: String, private val bearer: String?) {
    private val http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build()
    private val json = Json { ignoreUnknownKeys = true }

    fun chatStream(
        query: String,
        model: String?,
        sourceFilter: String?,
        onSources: (List<String>) -> Unit,
        onDelta: (String) -> Unit,
    ) {
        val payload = json.encodeToString(
            RagChatRequest.serializer(),
            RagChatRequest(query = query, model = model, source = sourceFilter),
        )
        val builder = HttpRequest.newBuilder()
            .uri(URI.create(baseUrl.trimEnd('/') + "/api/v1/rag/chat"))
            .timeout(Duration.ofSeconds(120))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(payload))
        bearer?.let { builder.header("Authorization", "Bearer $it") }

        val resp = try {
            http.send(builder.build(), HttpResponse.BodyHandlers.ofLines())
        } catch (e: Exception) {
            throw OllamaException("cannot reach $baseUrl: ${e.message}")
        }
        if (resp.statusCode() !in 200..299) {
            throw OllamaException("rag chat failed (${resp.statusCode()})")
        }
        // Fail-closed, som OllamaClient.chatStream (F-005) og som Androids
        // ragChatStream: EOF er ikke succes. Et droppet socket eller en
        // proxy-timeout afslutter ogsaa sekvensen paent, saa fuldfoerelse
        // kraever workerens terminale linje -- og et afbrudt svar skal
        // skelnes fra et der aldrig startede.
        var sawDone = false
        var sawContent = false
        resp.body().forEach { line ->
            when (val event = RagStreamParser.parse(line)) {
                is RagStreamParser.Event.Sources -> onSources(event.names)
                is RagStreamParser.Event.Delta -> {
                    sawContent = true
                    onDelta(event.text)
                }
                is RagStreamParser.Event.Done -> {
                    if (event.trailingDelta.isNotEmpty()) {
                        sawContent = true
                        onDelta(event.trailingDelta)
                    }
                    sawDone = true
                }
                is RagStreamParser.Event.Failure ->
                    throw OllamaException("rag chat: ${event.message}")
                RagStreamParser.Event.Ignored -> Unit
            }
        }
        RagStreamParser.terminalFailure(sawDone, sawContent)?.let { throw OllamaException(it) }
    }

    /** Lists ingested RAG source names, for the source-filter picker. */
    fun listSources(): List<String> {
        val builder = HttpRequest.newBuilder()
            .uri(URI.create(baseUrl.trimEnd('/') + "/api/v1/rag/sources"))
            .timeout(Duration.ofSeconds(10))
            .GET()
        bearer?.let { builder.header("Authorization", "Bearer $it") }
        val resp = try {
            http.send(builder.build(), HttpResponse.BodyHandlers.ofString())
        } catch (e: Exception) {
            throw OllamaException("cannot reach $baseUrl: ${e.message}")
        }
        if (resp.statusCode() !in 200..299) {
            throw OllamaException("rag sources failed (${resp.statusCode()})")
        }
        return json.decodeFromString(RagSourceListResponse.serializer(), resp.body())
            .sources.map { it.source }.filter { it.isNotEmpty() }
    }
}
