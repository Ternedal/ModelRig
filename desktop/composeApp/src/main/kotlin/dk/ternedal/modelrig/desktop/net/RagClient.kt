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
private data class RagContentLine(val message: RagMsg = RagMsg())

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
        val delta = runCatching {
            json.decodeFromString(RagContentLine.serializer(), line).message.content
        }.getOrDefault("")
        return if (delta.isNotEmpty()) Event.Delta(delta) else Event.Ignored
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
        resp.body().forEach { line ->
            when (val event = RagStreamParser.parse(line)) {
                is RagStreamParser.Event.Sources -> onSources(event.names)
                is RagStreamParser.Event.Delta -> onDelta(event.text)
                RagStreamParser.Event.Ignored -> Unit
            }
        }
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
