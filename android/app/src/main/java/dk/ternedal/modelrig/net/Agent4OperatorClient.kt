package dk.ternedal.modelrig.net

import okhttp3.CacheControl
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Read-only Android transport for ADR-A4-007's backend-proxied Agent 4 operator
 * surface. It has no write method and never talks directly to the worker.
 */
class Agent4OperatorClient(
    baseUrl: String,
    private val token: String,
) {
    companion object {
        const val SCHEMA = "modelrig-agent4/operator-api/v1"
        const val MEDIA_TYPE = "application/vnd.modelrig.agent4.operator+json"
        private const val DEFAULT_LIMIT = 100
        private const val MAX_LIMIT = 1_000
        private const val OPERATOR_PATH = "api/v1/experimental/agent4/operator"
    }

    enum class CampaignStatus(val wireValue: String) {
        QUEUED("queued"),
        SCHEDULED("scheduled"),
        RUNNING("running"),
        PAUSING("pausing"),
        PAUSED("paused"),
        CANCELLING("cancelling"),
        CANCELLED("cancelled"),
        SUCCEEDED("succeeded"),
        FAILED("failed"),
    }

    enum class ErrorKind {
        AUTH_REQUIRED,
        GRANT_REQUIRED,
        NOT_FOUND,
        REQUEST_REJECTED,
        UNAVAILABLE,
        PROTOCOL,
    }

    class OperatorException(
        val kind: ErrorKind,
        val statusCode: Int? = null,
        message: String,
        cause: Throwable? = null,
    ) : RuntimeException(message, cause)

    /** Canonical server-owned JSON. The client displays it but does not own it. */
    data class CanonicalJson(val value: String)

    /** Opaque hash-bound cursor; callers may only pass it back to this client. */
    data class Cursor internal constructor(internal val encoded: String)

    data class CampaignOverview(
        val campaignId: String,
        val name: String,
        val status: CampaignStatus,
        val timelineEntries: Int,
        val eventEntries: Int,
        val evidenceEntries: Int,
        val latestTimelineHash: String?,
        val record: CanonicalJson,
    )

    data class CampaignList(
        val campaigns: List<CampaignOverview>,
    )

    data class TimelinePage(
        val campaignId: String,
        val entries: List<CanonicalJson>,
        val startCursor: Cursor,
        val nextCursor: Cursor,
        val headCursor: Cursor,
        val hasMore: Boolean,
    )

    data class EvidencePage(
        val campaignId: String,
        val records: List<CanonicalJson>,
        val startCursor: Cursor,
        val nextCursor: Cursor,
        val headCursor: Cursor,
        val hasMore: Boolean,
    )

    data class EvidenceVerification(
        val campaignId: String,
        val recordCount: Int,
        val headHash: String?,
        val latestTimelineHeadHash: String?,
    )

    private val base: HttpUrl = baseUrl.trimEnd('/').toHttpUrl()
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()
    private val noStore = CacheControl.Builder().noCache().noStore().build()

    fun listCampaigns(
        statuses: Set<CampaignStatus> = emptySet(),
        limit: Int = DEFAULT_LIMIT,
    ): CampaignList {
        validateLimit(limit)
        val builder = operatorUrl("campaigns")
            .addQueryParameter("limit", limit.toString())
        statuses.sortedBy { it.wireValue }.forEach {
            builder.addQueryParameter("status", it.wireValue)
        }
        val root = execute(builder.build())
        val values = root.requireArray("campaigns")
        return CampaignList(
            campaigns = values.objects("campaigns").map(::parseOverview),
        )
    }

    fun campaign(campaignId: String): CampaignOverview {
        val root = execute(operatorUrl("campaigns", requireSegment(campaignId, "campaign id")).build())
        return parseOverview(root.requireObject("campaign"))
    }

    fun timeline(
        campaignId: String,
        after: Cursor? = null,
        snapshotHead: Cursor? = null,
        limit: Int = DEFAULT_LIMIT,
    ): TimelinePage {
        validateLimit(limit)
        val builder = operatorUrl(
            "campaigns",
            requireSegment(campaignId, "campaign id"),
            "timeline",
        ).addQueryParameter("limit", limit.toString())
        after?.let { builder.addQueryParameter("after", it.encoded) }
        snapshotHead?.let { builder.addQueryParameter("snapshot_head", it.encoded) }
        val page = execute(builder.build()).requireObject("page")
        return TimelinePage(
            campaignId = page.requireText("campaign_id"),
            entries = page.requireArray("entries").objects("entries").map {
                CanonicalJson(it.toString())
            },
            startCursor = page.requireCursor("start_cursor"),
            nextCursor = page.requireCursor("next_cursor"),
            headCursor = page.requireCursor("head_cursor"),
            hasMore = page.requireBoolean("has_more"),
        )
    }

    fun evidencePage(
        campaignId: String,
        after: Cursor? = null,
        snapshotHead: Cursor? = null,
        limit: Int = DEFAULT_LIMIT,
    ): EvidencePage {
        validateLimit(limit)
        val builder = operatorUrl(
            "campaigns",
            requireSegment(campaignId, "campaign id"),
            "evidence",
        ).addQueryParameter("limit", limit.toString())
        after?.let { builder.addQueryParameter("after", it.encoded) }
        snapshotHead?.let { builder.addQueryParameter("snapshot_head", it.encoded) }
        val page = execute(builder.build()).requireObject("page")
        return EvidencePage(
            campaignId = page.requireText("campaign_id"),
            records = page.requireArray("records").objects("records").map {
                CanonicalJson(it.toString())
            },
            startCursor = page.requireCursor("start_cursor"),
            nextCursor = page.requireCursor("next_cursor"),
            headCursor = page.requireCursor("head_cursor"),
            hasMore = page.requireBoolean("has_more"),
        )
    }

    fun evidenceVerification(campaignId: String): EvidenceVerification {
        val verification = execute(
            operatorUrl(
                "campaigns",
                requireSegment(campaignId, "campaign id"),
                "evidence",
                "verification",
            ).build(),
        ).requireObject("verification")
        return EvidenceVerification(
            campaignId = verification.requireText("campaign_id"),
            recordCount = verification.requireNonNegativeInt("record_count"),
            headHash = verification.optionalHash("head_hash"),
            latestTimelineHeadHash = verification.optionalHash("latest_timeline_head_hash"),
        )
    }

    fun evidence(campaignId: String, evidenceId: String): CanonicalJson {
        val value = execute(
            operatorUrl(
                "campaigns",
                requireSegment(campaignId, "campaign id"),
                "evidence",
                requireSegment(evidenceId, "evidence id"),
            ).build(),
        ).requireObject("evidence")
        return CanonicalJson(value.toString())
    }

    private fun operatorUrl(vararg segments: String): HttpUrl.Builder {
        val builder = base.newBuilder().addPathSegments(OPERATOR_PATH)
        segments.forEach(builder::addPathSegment)
        return builder
    }

    private fun execute(url: HttpUrl): JSONObject {
        val request = Request.Builder()
            .url(url)
            .get()
            .cacheControl(noStore)
            .header("Authorization", "Bearer $token")
            .header("Accept", MEDIA_TYPE)
            .build()
        try {
            http.newCall(request).execute().use { response ->
                val text = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    throw classifyFailure(response.code, text)
                }
                val responseType = response.header("Content-Type")
                    ?.substringBefore(';')
                    ?.trim()
                if (responseType != MEDIA_TYPE) {
                    throw protocol("Ukendt Agent 4-medietype: ${responseType ?: "mangler"}")
                }
                val root = parseObject(text, "Agent 4 returnerede ugyldig JSON")
                val schema = root.optString("schema")
                if (schema != SCHEMA) {
                    throw protocol("Ukendt Agent 4-schema: $schema")
                }
                return root
            }
        } catch (known: OperatorException) {
            throw known
        } catch (failure: IOException) {
            throw OperatorException(
                ErrorKind.UNAVAILABLE,
                message = "Agent 4 kan ikke nås",
                cause = failure,
            )
        }
    }

    private fun classifyFailure(status: Int, body: String): OperatorException {
        val detail = runCatching {
            val root = JSONObject(body)
            root.optString("error").ifBlank { root.optString("detail") }
        }.getOrNull()?.ifBlank { null } ?: "HTTP $status"
        return when (status) {
            401 -> OperatorException(ErrorKind.AUTH_REQUIRED, status, "Parringen skal fornyes")
            403 -> if (detail == "agent4 read grant required") {
                OperatorException(ErrorKind.GRANT_REQUIRED, status, "Enheden mangler agent4:read")
            } else {
                OperatorException(ErrorKind.AUTH_REQUIRED, status, "Adgang til Agent 4 blev afvist")
            }
            404 -> OperatorException(ErrorKind.NOT_FOUND, status, "Agent 4-data findes ikke")
            405, 422 -> OperatorException(ErrorKind.REQUEST_REJECTED, status, detail)
            503 -> OperatorException(ErrorKind.UNAVAILABLE, status, "Agent 4-read er midlertidigt utilgængelig")
            else -> OperatorException(ErrorKind.UNAVAILABLE, status, "Agent 4 fejlede: $detail")
        }
    }

    private fun parseOverview(value: JSONObject): CampaignOverview {
        val record = value.requireObject("record")
        val spec = record.requireObject("spec")
        val statusText = record.requireText("status")
        val status = CampaignStatus.entries.firstOrNull { it.wireValue == statusText }
            ?: throw protocol("Ukendt Agent 4-status: $statusText")
        return CampaignOverview(
            campaignId = spec.requireText("campaign_id"),
            name = spec.requireText("name"),
            status = status,
            timelineEntries = value.requireNonNegativeInt("timeline_entries"),
            eventEntries = value.requireNonNegativeInt("event_entries"),
            evidenceEntries = value.requireNonNegativeInt("evidence_entries"),
            latestTimelineHash = value.optionalHash("latest_timeline_hash"),
            record = CanonicalJson(record.toString()),
        )
    }

    private fun validateLimit(limit: Int) {
        if (limit !in 1..MAX_LIMIT) {
            throw protocol("Agent 4-limit skal være mellem 1 og $MAX_LIMIT")
        }
    }

    private fun requireSegment(value: String, label: String): String {
        val normalized = value.trim()
        if (normalized.isEmpty() || normalized != value || normalized.length > 512) {
            throw protocol("Ugyldigt $label")
        }
        return normalized
    }

    private fun JSONObject.requireObject(name: String): JSONObject =
        optJSONObject(name) ?: throw protocol("Agent 4-svaret mangler $name")

    private fun JSONObject.requireArray(name: String): JSONArray =
        optJSONArray(name) ?: throw protocol("Agent 4-svaret mangler $name")

    private fun JSONObject.requireText(name: String): String =
        optString(name).takeIf { it.isNotBlank() }
            ?: throw protocol("Agent 4-svaret mangler $name")

    private fun JSONObject.requireNonNegativeInt(name: String): Int {
        if (!has(name) || isNull(name)) throw protocol("Agent 4-svaret mangler $name")
        val value = optInt(name, -1)
        if (value < 0) throw protocol("Agent 4-svaret har ugyldigt $name")
        return value
    }

    private fun JSONObject.requireBoolean(name: String): Boolean {
        if (!has(name) || isNull(name) || get(name) !is Boolean) {
            throw protocol("Agent 4-svaret har ugyldigt $name")
        }
        return getBoolean(name)
    }

    private fun JSONObject.requireCursor(name: String): Cursor =
        Cursor(requireObject(name).toString())

    private fun JSONObject.optionalHash(name: String): String? {
        if (!has(name) || isNull(name)) return null
        val value = optString(name)
        if (!value.startsWith("sha256:") || value.length != 71) {
            throw protocol("Agent 4-svaret har ugyldigt $name")
        }
        return value
    }

    private fun JSONArray.objects(label: String): List<JSONObject> = buildList {
        for (index in 0 until length()) {
            add(optJSONObject(index) ?: throw protocol("Agent 4-$label indeholder en ugyldig post"))
        }
    }

    private fun parseObject(text: String, message: String): JSONObject =
        runCatching { JSONObject(text) }.getOrElse { throw protocol(message, it) }

    private fun protocol(message: String, cause: Throwable? = null): OperatorException =
        OperatorException(ErrorKind.PROTOCOL, message = message, cause = cause)
}
