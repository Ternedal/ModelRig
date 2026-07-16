package dk.ternedal.modelrig.net

import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** Read-only transport for the experimental Agent 3.0 Capability Graph. */
class Agent3CapabilityClient(baseUrl: String, private val token: String) {
    private val base = baseUrl.trimEnd('/')
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    data class Node(
        val id: String,
        val kind: String,
        val state: String,
        val reason: String,
        val metadata: String,
    )

    data class Edge(
        val source: String,
        val target: String,
        val relation: String,
    )

    data class Graph(
        val schema: String,
        val nodes: List<Node>,
        val edges: List<Edge>,
        val productionActivation: Boolean,
    )

    fun graph(): Graph {
        val request = Request.Builder()
            .url(base + "/api/v1/experimental/agent3/capabilities")
            .get()
            .header("Authorization", "Bearer $token")
            .build()
        val root = execute(request)
        val schema = root.optString("schema")
        if (schema != "kaliv-agent3-capability-graph/v1") {
            throw ModelRigException("Ukendt Capability Graph-schema: $schema")
        }
        if (root.optBoolean("production_activation", true)) {
            throw ModelRigException("Ugyldig Capability Graph: produktion må aldrig aktiveres")
        }

        val nodesJson = root.optJSONArray("nodes")
            ?: throw ModelRigException("Capability Graph mangler nodes")
        val nodes = buildList {
            for (index in 0 until nodesJson.length()) {
                val item = nodesJson.optJSONObject(index)
                    ?: throw ModelRigException("Capability Graph indeholder en ugyldig node")
                add(
                    Node(
                        id = item.optString("id"),
                        kind = item.optString("kind"),
                        state = item.optString("state"),
                        reason = item.optString("reason"),
                        metadata = (item.optJSONObject("metadata") ?: JSONObject()).toString(),
                    )
                )
            }
        }
        if (nodes.any { it.id.isBlank() } || nodes.map { it.id }.distinct().size != nodes.size) {
            throw ModelRigException("Capability Graph har tomme eller dublerede node-id'er")
        }

        val known = nodes.map { it.id }.toSet()
        val edgesJson = root.optJSONArray("edges")
            ?: throw ModelRigException("Capability Graph mangler edges")
        val edges = buildList {
            for (index in 0 until edgesJson.length()) {
                val item = edgesJson.optJSONObject(index)
                    ?: throw ModelRigException("Capability Graph indeholder en ugyldig edge")
                val edge = Edge(
                    source = item.optString("source"),
                    target = item.optString("target"),
                    relation = item.optString("relation", "depends_on"),
                )
                if (edge.source !in known || edge.target !in known) {
                    throw ModelRigException("Capability Graph-edge peger på en ukendt node")
                }
                add(edge)
            }
        }
        return Graph(schema, nodes, edges, productionActivation = false)
    }

    private fun execute(request: Request): JSONObject {
        http.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val detail = runCatching {
                    val root = JSONObject(text)
                    root.optString("error").ifBlank { root.optString("detail") }
                }.getOrNull()?.ifBlank { null } ?: text.take(500)
                throw ModelRigException("Capability Graph fejlede (${response.code}): $detail")
            }
            return runCatching { JSONObject(text) }
                .getOrElse { throw ModelRigException("Capability Graph returnerede ugyldig JSON") }
        }
    }
}
