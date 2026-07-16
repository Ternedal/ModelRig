package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

@Serializable
data class Agent3CapabilityNode(
    val id: String,
    val kind: String,
    val state: String,
    val reason: String,
    val metadata: JsonObject = JsonObject(emptyMap()),
)

@Serializable
data class Agent3CapabilityEdge(
    val source: String,
    val target: String,
    val relation: String = "depends_on",
)

@Serializable
data class Agent3CapabilityGraph(
    val schema: String,
    val nodes: List<Agent3CapabilityNode> = emptyList(),
    val edges: List<Agent3CapabilityEdge> = emptyList(),
    @SerialName("production_activation") val productionActivation: Boolean = false,
)

/** Read-only transport for the experimental Capability Graph. */
class Agent3CapabilityClient(baseUrl: String, private val bearer: String) {
    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true }
    private val http: HttpClient = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(10))
        .build()

    fun graph(): Agent3CapabilityGraph {
        val request = HttpRequest.newBuilder(
            URI.create(base + "/api/v1/experimental/agent3/capabilities")
        )
            .header("Authorization", "Bearer $bearer")
            .timeout(Duration.ofSeconds(20))
            .GET()
            .build()
        val response = http.send(request, HttpResponse.BodyHandlers.ofString())
        if (response.statusCode() !in 200..299) {
            throw Agent3Exception(
                "Agent 3.0 capability graph failed (${response.statusCode()}): " +
                    response.body().take(500)
            )
        }
        val graph = try {
            json.decodeFromString<Agent3CapabilityGraph>(response.body())
        } catch (e: Exception) {
            throw Agent3Exception("Agent 3.0 capability graph returned invalid JSON: ${e.message}")
        }
        if (graph.schema != "kaliv-agent3-capability-graph/v1") {
            throw Agent3Exception("Unsupported Agent 3.0 capability graph schema: ${graph.schema}")
        }
        if (graph.productionActivation) {
            throw Agent3Exception("Invalid capability graph: it must never activate production")
        }
        val ids = graph.nodes.map { it.id }
        if (ids.size != ids.toSet().size) {
            throw Agent3Exception("Invalid capability graph: duplicate node ids")
        }
        val known = ids.toSet()
        if (graph.edges.any { it.source !in known || it.target !in known }) {
            throw Agent3Exception("Invalid capability graph: edge references an unknown node")
        }
        return graph
    }
}
