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
        const val CAMPAIGN_CURSOR_SCHEMA = "modelrig-agent4/campaign-list-query-cursor/v1"
        private const val CAMPAIGN_RECORD_SCHEMA = "modelrig-agent4/campaign-record/v1"
        private const val TIMELINE_ENTRY_SCHEMA = "modelrig-agent4/campaign-timeline-entry/v1"
        private const val EVIDENCE_RECORD_SCHEMA = "modelrig-agent4/campaign-evidence-record/v1"
        private const val TIMELINE_CURSOR_SCHEMA = "modelrig-agent4/campaign-timeline-query-cursor/v1"
        private const val EVIDENCE_CURSOR_SCHEMA = "modelrig-agent4/campaign-evidence-query-cursor/v1"
        private const val DEFAULT_LIMIT = 100
        private const val MAX_LIMIT = 1_000
        private const val OPERATOR_PATH = "api/v1/experimental/agent4/operator"
        private val SHA256 = Regex("sha256:[0-9a-f]{64}")
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
        FEATURE_DISABLED,
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

    /** Opaque campaign-list cursor with validated relationship metadata. */
    data class CampaignCursor internal constructor(
        internal val encoded: String,
        internal val position: Int,
        internal val total: Int,
        internal val snapshotSha256: String,
        internal val lastCampaignId: String?,
    ) {
        internal constructor(encoded: String) : this(encoded, -1, -1, "", null)
    }

    /** Opaque campaign-local cursor with validated ordering metadata. */
    data class Cursor internal constructor(
        internal val encoded: String,
        internal val sequence: Int,
        internal val hash: String?,
    )

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
        val startCursor: CampaignCursor,
        val nextCursor: CampaignCursor,
        val headCursor: CampaignCursor,
        val hasMore: Boolean,
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

    private data class BoundRecord(
        val sequence: Int,
        val hash: String,
        val canonical: CanonicalJson,
    )

    private val base: HttpUrl = baseUrl.trimEnd('/').toHttpUrl()
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()
    private val noStore = CacheControl.Builder().noCache().noStore().build()

    fun listCampaigns(
        statuses: Set<CampaignStatus> = emptySet(),
        after: CampaignCursor? = null,
        snapshotHead: CampaignCursor? = null,
        limit: Int = DEFAULT_LIMIT,
    ): CampaignList {
        validateLimit(limit)
        if ((after == null) != (snapshotHead == null)) {
            throw protocol("Campaign paging kræver både after og snapshotHead")
        }
        val orderedStatuses = statuses.sortedBy { it.wireValue }
        val builder = operatorUrl("campaigns")
            .addQueryParameter("limit", limit.toString())
        orderedStatuses.forEach { builder.addQueryParameter("status", it.wireValue) }
        after?.let { builder.addQueryParameter("after", it.encoded) }
        snapshotHead?.let { builder.addQueryParameter("snapshot_head", it.encoded) }
        val root = try {
            execute(builder.build())
        } catch (failure: OperatorException) {
            if (failure.kind == ErrorKind.NOT_FOUND && after == null) {
                throw OperatorException(
                    ErrorKind.FEATURE_DISABLED,
                    failure.statusCode,
                    "Agent 4-read er ikke slået til på riggen",
                    failure,
                )
            }
            throw failure
        }
        val expectedStatuses = orderedStatuses.map { it.wireValue }
        val campaigns = root.requireArray("campaigns").objects("campaigns").map(::parseOverview)
        val start = root.requireCampaignCursor("start_cursor", expectedStatuses)
        val next = root.requireCampaignCursor("next_cursor", expectedStatuses)
        val head = root.requireCampaignCursor("head_cursor", expectedStatuses)
        val hasMore = root.requireBoolean("has_more")
        validateCampaignPageRelationships(campaigns, start, next, head, hasMore)
        return CampaignList(
            campaigns = campaigns,
            startCursor = start,
            nextCursor = next,
            headCursor = head,
            hasMore = hasMore,
        )
    }

    fun campaign(campaignId: String): CampaignOverview {
        val requestedId = requireSegment(campaignId, "campaign id")
        val root = execute(operatorUrl("campaigns", requestedId).build())
        val overview = parseOverview(root.requireObject("campaign"))
        if (overview.campaignId != requestedId) {
            throw protocol("Agent 4 campaign-detail matcher ikke requestet")
        }
        return overview
    }

    fun timeline(
        campaignId: String,
        after: Cursor? = null,
        snapshotHead: Cursor? = null,
        limit: Int = DEFAULT_LIMIT,
    ): TimelinePage {
        validateLimit(limit)
        if ((after == null) != (snapshotHead == null)) {
            throw protocol("Timeline paging kræver både after og snapshotHead")
        }
        val requestedId = requireSegment(campaignId, "campaign id")
        val builder = operatorUrl("campaigns", requestedId, "timeline")
            .addQueryParameter("limit", limit.toString())
        after?.let { builder.addQueryParameter("after", it.encoded) }
        snapshotHead?.let { builder.addQueryParameter("snapshot_head", it.encoded) }
        val page = execute(builder.build()).requireObject("page")
        val returnedId = page.requireText("campaign_id")
        if (returnedId != requestedId) {
            throw protocol("Agent 4 timeline matcher ikke requestet campaign")
        }
        val records = page.requireArray("entries").objects("entries").map {
            parseTimelineRecord(it, returnedId)
        }
        val start = page.requireCursor("start_cursor", returnedId, TIMELINE_CURSOR_SCHEMA, "entry_hash")
        val next = page.requireCursor("next_cursor", returnedId, TIMELINE_CURSOR_SCHEMA, "entry_hash")
        val head = page.requireCursor("head_cursor", returnedId, TIMELINE_CURSOR_SCHEMA, "entry_hash")
        val hasMore = page.requireBoolean("has_more")
        validatePageRelationships("timeline", records, start, next, head, hasMore)
        return TimelinePage(
            campaignId = returnedId,
            entries = records.map { it.canonical },
            startCursor = start,
            nextCursor = next,
            headCursor = head,
            hasMore = hasMore,
        )
    }

    fun evidencePage(
        campaignId: String,
        after: Cursor? = null,
        snapshotHead: Cursor? = null,
        limit: Int = DEFAULT_LIMIT,
    ): EvidencePage {
        validateLimit(limit)
        if ((after == null) != (snapshotHead == null)) {
            throw protocol("Evidence paging kræver både after og snapshotHead")
        }
        val requestedId = requireSegment(campaignId, "campaign id")
        val builder = operatorUrl("campaigns", requestedId, "evidence")
            .addQueryParameter("limit", limit.toString())
        after?.let { builder.addQueryParameter("after", it.encoded) }
        snapshotHead?.let { builder.addQueryParameter("snapshot_head", it.encoded) }
        val page = execute(builder.build()).requireObject("page")
        val returnedId = page.requireText("campaign_id")
        if (returnedId != requestedId) {
            throw protocol("Agent 4 evidence-side matcher ikke requestet campaign")
        }
        val records = page.requireArray("records").objects("records").map {
            parseEvidenceRecord(it, returnedId)
        }
        val start = page.requireCursor("start_cursor", returnedId, EVIDENCE_CURSOR_SCHEMA, "record_hash")
        val next = page.requireCursor("next_cursor", returnedId, EVIDENCE_CURSOR_SCHEMA, "record_hash")
        val head = page.requireCursor("head_cursor", returnedId, EVIDENCE_CURSOR_SCHEMA, "record_hash")
        val hasMore = page.requireBoolean("has_more")
        validatePageRelationships("evidence", records, start, next, head, hasMore)
        return EvidencePage(
            campaignId = returnedId,
            records = records.map { it.canonical },
            startCursor = start,
            nextCursor = next,
            headCursor = head,
            hasMore = hasMore,
        )
    }

    fun evidenceVerification(campaignId: String): EvidenceVerification {
        val requestedId = requireSegment(campaignId, "campaign id")
        val verification = execute(
            operatorUrl("campaigns", requestedId, "evidence", "verification").build(),
        ).requireObject("verification")
        val returnedId = verification.requireText("campaign_id")
        if (returnedId != requestedId) {
            throw protocol("Agent 4 verification matcher ikke requestet campaign")
        }
        return EvidenceVerification(
            campaignId = returnedId,
            recordCount = verification.requireNonNegativeInt("record_count"),
            headHash = verification.optionalHash("head_hash"),
            latestTimelineHeadHash = verification.optionalHash("latest_timeline_head_hash"),
        )
    }

    fun evidence(campaignId: String, evidenceId: String): CanonicalJson {
        val requestedCampaignId = requireSegment(campaignId, "campaign id")
        val requestedEvidenceId = requireSegment(evidenceId, "evidence id")
        val value = execute(
            operatorUrl("campaigns", requestedCampaignId, "evidence", requestedEvidenceId).build(),
        ).requireObject("evidence")
        if (value.requireText("schema") != EVIDENCE_RECORD_SCHEMA) {
            throw protocol("Ukendt Agent 4 evidence-record-schema")
        }
        if (value.requireText("campaign_id") != requestedCampaignId) {
            throw protocol("Agent 4 evidence matcher ikke requestet campaign")
        }
        if (value.requireObject("evidence").requireText("evidence_id") != requestedEvidenceId) {
            throw protocol("Agent 4 evidence matcher ikke requestet evidence id")
        }
        return CanonicalJson(value.toString())
    }

    private fun parseTimelineRecord(value: JSONObject, campaignId: String): BoundRecord {
        if (value.requireText("schema") != TIMELINE_ENTRY_SCHEMA) {
            throw protocol("Ukendt Agent 4 timeline-entry-schema")
        }
        val event = value.requireObject("event")
        if (event.requireText("campaign_id") != campaignId) {
            throw protocol("Agent 4 timeline-entry tilhører en anden campaign")
        }
        return BoundRecord(
            sequence = event.requirePositiveInt("sequence"),
            hash = value.requireHash("entry_hash"),
            canonical = CanonicalJson(value.toString()),
        )
    }

    private fun parseEvidenceRecord(value: JSONObject, campaignId: String): BoundRecord {
        if (value.requireText("schema") != EVIDENCE_RECORD_SCHEMA) {
            throw protocol("Ukendt Agent 4 evidence-record-schema")
        }
        if (value.requireText("campaign_id") != campaignId) {
            throw protocol("Agent 4 evidence-record tilhører en anden campaign")
        }
        return BoundRecord(
            sequence = value.requirePositiveInt("sequence"),
            hash = value.requireHash("record_hash"),
            canonical = CanonicalJson(value.toString()),
        )
    }

    private fun validateCampaignPageRelationships(
        campaigns: List<CampaignOverview>,
        start: CampaignCursor,
        next: CampaignCursor,
        head: CampaignCursor,
        hasMore: Boolean,
    ) {
        if (start.total != next.total || next.total != head.total) {
            throw protocol("Agent 4 campaign-cursors har modstridende total")
        }
        if (start.snapshotSha256 != next.snapshotSha256 || next.snapshotSha256 != head.snapshotSha256) {
            throw protocol("Agent 4 campaign-cursors tilhører forskellige snapshots")
        }
        if (head.position != head.total) {
            throw protocol("Agent 4 campaign head-cursor matcher ikke snapshot-total")
        }
        if (start.position > next.position || next.position > head.position) {
            throw protocol("Agent 4 campaign-cursors har ugyldig rækkefølge")
        }
        if (campaigns.size != next.position - start.position) {
            throw protocol("Agent 4 campaign-side matcher ikke cursor-intervallet")
        }
        if (campaigns.isEmpty()) {
            if (next.position != start.position || next.lastCampaignId != start.lastCampaignId) {
                throw protocol("Agent 4 tom campaign-side må ikke flytte cursor")
            }
        } else if (next.lastCampaignId != campaigns.last().campaignId) {
            throw protocol("Agent 4 campaign-side matcher ikke next-cursor identitet")
        }
        if (hasMore != (next.position < head.position)) {
            throw protocol("Agent 4 campaign-side har modstridende has_more")
        }
    }

    private fun validatePageRelationships(
        label: String,
        records: List<BoundRecord>,
        start: Cursor,
        next: Cursor,
        head: Cursor,
        hasMore: Boolean,
    ) {
        if (start.sequence > next.sequence || next.sequence > head.sequence) {
            throw protocol("Agent 4 $label-cursors har ugyldig rækkefølge")
        }
        if (records.size != next.sequence - start.sequence) {
            throw protocol("Agent 4 $label-side matcher ikke cursor-intervallet")
        }
        records.forEachIndexed { index, record ->
            val expectedSequence = start.sequence + index + 1
            if (record.sequence != expectedSequence) {
                throw protocol("Agent 4 $label-side har sequence-tab eller overlap")
            }
        }
        if (records.isEmpty()) {
            if (next != start) {
                throw protocol("Agent 4 tom $label-side må ikke flytte cursor")
            }
        } else if (next.hash != records.last().hash) {
            throw protocol("Agent 4 $label-side matcher ikke next-cursor hash")
        }
        if (hasMore != (next.sequence < head.sequence)) {
            throw protocol("Agent 4 $label-side har modstridende has_more")
        }
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
                val schema = root.requireText("schema")
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
            root.strictOptionalText("error") ?: root.strictOptionalText("detail")
        }.getOrNull() ?: "HTTP $status"
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
        if (record.requireText("schema") != CAMPAIGN_RECORD_SCHEMA) {
            throw protocol("Ukendt Agent 4 campaign-record-schema")
        }
        val spec = record.requireObject("spec")
        val state = record.requireObject("state")
        val campaignId = spec.requireText("campaign_id")
        if (state.requireText("campaign_id") != campaignId) {
            throw protocol("Agent 4 campaign-record har modstridende id'er")
        }
        val statusText = state.requireText("status")
        val status = CampaignStatus.entries.firstOrNull { it.wireValue == statusText }
            ?: throw protocol("Ukendt Agent 4-status: $statusText")
        return CampaignOverview(
            campaignId = campaignId,
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

    private fun JSONObject.requireText(name: String): String {
        if (!has(name) || isNull(name)) throw protocol("Agent 4-svaret mangler $name")
        val value = get(name)
        if (value !is String || value.isBlank()) {
            throw protocol("Agent 4-svaret har ugyldigt $name")
        }
        return value
    }

    private fun JSONObject.strictOptionalText(name: String): String? {
        if (!has(name) || isNull(name)) return null
        val value = get(name)
        return if (value is String && value.isNotBlank()) value else null
    }

    private fun JSONObject.requirePositiveInt(name: String): Int {
        val value = requireNonNegativeInt(name)
        if (value < 1) throw protocol("Agent 4-svaret har ugyldigt $name")
        return value
    }

    private fun JSONObject.requireNonNegativeInt(name: String): Int {
        if (!has(name) || isNull(name)) throw protocol("Agent 4-svaret mangler $name")
        val raw = get(name)
        if (raw !is Number) throw protocol("Agent 4-svaret har ugyldigt $name")
        val asDouble = raw.toDouble()
        val asLong = raw.toLong()
        if (!asDouble.isFinite() || asDouble != asLong.toDouble() || asLong !in 0..Int.MAX_VALUE.toLong()) {
            throw protocol("Agent 4-svaret har ugyldigt $name")
        }
        return asLong.toInt()
    }

    private fun JSONObject.requireBoolean(name: String): Boolean {
        if (!has(name) || isNull(name) || get(name) !is Boolean) {
            throw protocol("Agent 4-svaret har ugyldigt $name")
        }
        return getBoolean(name)
    }

    private fun JSONObject.requireCampaignCursor(
        name: String,
        expectedStatuses: List<String>,
    ): CampaignCursor {
        val cursor = requireObject(name)
        if (cursor.requireText("schema") != CAMPAIGN_CURSOR_SCHEMA) {
            throw protocol("Agent 4-svaret har ukendt $name-schema")
        }
        val statuses = cursor.requireArray("statuses").strings("$name.statuses")
        if (statuses != expectedStatuses || statuses != statuses.sorted() || statuses.distinct().size != statuses.size) {
            throw protocol("Agent 4-svaret har cursor med forkert statusfilter")
        }
        val position = cursor.requireNonNegativeInt("position")
        val total = cursor.requireNonNegativeInt("total")
        if (position > total) throw protocol("Agent 4-svaret har cursor uden for snapshot")
        val lastId = cursor.optionalText("last_campaign_id")
        if ((position == 0 && lastId != null) || (position > 0 && lastId == null)) {
            throw protocol("Agent 4-svaret har ugyldig campaign cursor-identitet")
        }
        val snapshotSha256 = cursor.requireHash("snapshot_sha256")
        return CampaignCursor(
            encoded = cursor.toString(),
            position = position,
            total = total,
            snapshotSha256 = snapshotSha256,
            lastCampaignId = lastId,
        )
    }

    private fun JSONObject.requireCursor(
        name: String,
        campaignId: String,
        expectedSchema: String,
        hashField: String,
    ): Cursor {
        val cursor = requireObject(name)
        if (cursor.requireText("schema") != expectedSchema) {
            throw protocol("Agent 4-svaret har ukendt $name-schema")
        }
        if (cursor.requireText("campaign_id") != campaignId) {
            throw protocol("Agent 4-svaret har cursor for en anden campaign")
        }
        val sequence = cursor.requireNonNegativeInt("sequence")
        val hash = cursor.optionalHash(hashField)
        if ((sequence == 0 && hash != null) || (sequence > 0 && hash == null)) {
            throw protocol("Agent 4-svaret har ugyldig hash-binding i $name")
        }
        return Cursor(cursor.toString(), sequence, hash)
    }

    private fun JSONObject.optionalText(name: String): String? {
        if (!has(name) || isNull(name)) return null
        val value = get(name)
        if (value !is String || value.isBlank()) {
            throw protocol("Agent 4-svaret har ugyldigt $name")
        }
        return value
    }

    private fun JSONObject.requireHash(name: String): String =
        optionalHash(name) ?: throw protocol("Agent 4-svaret mangler $name")

    private fun JSONObject.optionalHash(name: String): String? {
        val value = optionalText(name) ?: return null
        if (!SHA256.matches(value)) {
            throw protocol("Agent 4-svaret har ugyldigt $name")
        }
        return value
    }

    private fun JSONArray.objects(label: String): List<JSONObject> = buildList {
        for (index in 0 until length()) {
            add(optJSONObject(index) ?: throw protocol("Agent 4-$label indeholder en ugyldig post"))
        }
    }

    private fun JSONArray.strings(label: String): List<String> = buildList {
        for (index in 0 until this@strings.length()) {
            val value = this@strings.get(index)
            if (value !is String || value.isBlank()) {
                throw protocol("Agent 4-$label indeholder ugyldig tekst")
            }
            add(value)
        }
    }

    private fun parseObject(text: String, message: String): JSONObject =
        runCatching { JSONObject(text) }.getOrElse { throw protocol(message, it) }

    private fun protocol(message: String, cause: Throwable? = null): OperatorException =
        OperatorException(ErrorKind.PROTOCOL, message = message, cause = cause)
}
