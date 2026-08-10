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
 * Dormant Android client for ADR-A4-005's immutable Agent 4 operator API v2.
 *
 * This class is deliberately parallel to [Agent4OperatorClient]. The qualified
 * v1 production path is unchanged until a later explicit activation decision.
 */
class Agent4SnapshotOperatorClient(
    baseUrl: String,
    private val token: String,
) {
    companion object {
        const val SCHEMA = "modelrig-agent4/operator-api/v2"
        const val MEDIA_TYPE = "application/vnd.modelrig.agent4.operator+json"
        const val SNAPSHOT_CURSOR_SCHEMA = "modelrig-agent4/snapshot-bound-cursor/v1"
        private const val CAMPAIGN_CURSOR_SCHEMA = "modelrig-agent4/campaign-list-query-cursor/v1"
        private const val TIMELINE_CURSOR_SCHEMA = "modelrig-agent4/campaign-timeline-query-cursor/v1"
        private const val EVIDENCE_CURSOR_SCHEMA = "modelrig-agent4/campaign-evidence-query-cursor/v1"
        private const val CAMPAIGN_RECORD_SCHEMA = "modelrig-agent4/campaign-record/v1"
        private const val TIMELINE_ENTRY_SCHEMA = "modelrig-agent4/campaign-timeline-entry/v1"
        private const val EVIDENCE_RECORD_SCHEMA = "modelrig-agent4/campaign-evidence-record/v1"
        private const val OPERATOR_PATH = "api/v1/experimental/agent4/operator"
        private const val DEFAULT_LIMIT = 100
        private const val MAX_LIMIT = 1_000
        private val SNAPSHOT_ID = Regex("[0-9a-f]{64}")
        private val HASH = Regex("sha256:[0-9a-f]{64}")
    }

    enum class ErrorKind {
        AUTH_REQUIRED,
        GRANT_REQUIRED,
        REFRESH_REQUIRED,
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

    data class SnapshotId internal constructor(val value: String) {
        init {
            require(SNAPSHOT_ID.matches(value)) { "invalid Agent 4 snapshot id" }
        }
    }

    enum class CursorKind {
        CAMPAIGN_LIST,
        TIMELINE,
        EVIDENCE,
    }

    /** Server-owned opaque cursor envelope. Never synthesized by Android. */
    data class SnapshotCursor internal constructor(
        internal val encoded: String,
        val snapshotId: SnapshotId,
        val kind: CursorKind,
        val sequence: Int? = null,
        val hash: String? = null,
        val campaignId: String? = null,
        val statusValues: List<String>? = null,
    )

    data class CampaignList(
        val snapshotId: SnapshotId,
        val campaigns: List<Agent4OperatorClient.CampaignOverview>,
        val startCursor: SnapshotCursor,
        val nextCursor: SnapshotCursor,
        val headCursor: SnapshotCursor,
        val hasMore: Boolean,
    )

    data class CampaignDetail(
        val snapshotId: SnapshotId,
        val campaign: Agent4OperatorClient.CampaignOverview,
    )

    data class TimelinePage(
        val snapshotId: SnapshotId,
        val campaignId: String,
        val entries: List<Agent4OperatorClient.CanonicalJson>,
        val startCursor: SnapshotCursor,
        val nextCursor: SnapshotCursor,
        val headCursor: SnapshotCursor,
        val hasMore: Boolean,
    )

    data class EvidencePage(
        val snapshotId: SnapshotId,
        val campaignId: String,
        val records: List<Agent4OperatorClient.CanonicalJson>,
        val startCursor: SnapshotCursor,
        val nextCursor: SnapshotCursor,
        val headCursor: SnapshotCursor,
        val hasMore: Boolean,
    )

    data class EvidenceVerification(
        val snapshotId: SnapshotId,
        val campaignId: String,
        val recordCount: Int,
        val headHash: String?,
        val latestTimelineHeadHash: String?,
    )

    data class EvidenceDetail(
        val snapshotId: SnapshotId,
        val evidence: Agent4OperatorClient.CanonicalJson,
    )

    private data class BoundRecord(
        val sequence: Int,
        val hash: String,
        val canonical: Agent4OperatorClient.CanonicalJson,
    )

    private val base: HttpUrl = baseUrl.trimEnd('/').toHttpUrl()
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()
    private val noStore = CacheControl.Builder().noCache().noStore().build()

    fun listCampaigns(
        statuses: Set<Agent4OperatorClient.CampaignStatus> = emptySet(),
        snapshotId: SnapshotId? = null,
        after: SnapshotCursor? = null,
        snapshotHead: SnapshotCursor? = null,
        limit: Int = DEFAULT_LIMIT,
    ): CampaignList {
        validateLimit(limit)
        if ((after == null) != (snapshotHead == null)) {
            throw protocol("Campaign paging kræver både after og snapshotHead")
        }
        val orderedStatuses = statuses.sortedBy { it.wireValue }
        val expectedStatuses = orderedStatuses.map { it.wireValue }
        if (after != null) {
            requireContinuation(
                snapshotId,
                after,
                CursorKind.CAMPAIGN_LIST,
                expectedStatuses = expectedStatuses,
            )
            requireContinuation(
                snapshotId,
                snapshotHead!!,
                CursorKind.CAMPAIGN_LIST,
                expectedStatuses = expectedStatuses,
            )
        }
        val builder = operatorUrl("campaigns").addQueryParameter("limit", limit.toString())
        orderedStatuses.forEach { builder.addQueryParameter("status", it.wireValue) }
        snapshotId?.let { builder.addQueryParameter("snapshot_id", it.value) }
        after?.let { builder.addQueryParameter("after", it.encoded) }
        snapshotHead?.let { builder.addQueryParameter("snapshot_head", it.encoded) }
        val root = execute(builder.build(), snapshotId)
        val actual = root.snapshotId()
        return CampaignList(
            snapshotId = actual,
            campaigns = root.requireArray("campaigns").objects("campaigns").map(::parseOverview),
            startCursor = root.requireSnapshotCursor(
                "start_cursor",
                actual,
                CursorKind.CAMPAIGN_LIST,
                expectedStatuses = expectedStatuses,
            ),
            nextCursor = root.requireSnapshotCursor(
                "next_cursor",
                actual,
                CursorKind.CAMPAIGN_LIST,
                expectedStatuses = expectedStatuses,
            ),
            headCursor = root.requireSnapshotCursor(
                "head_cursor",
                actual,
                CursorKind.CAMPAIGN_LIST,
                expectedStatuses = expectedStatuses,
            ),
            hasMore = root.requireBoolean("has_more"),
        )
    }

    fun campaign(campaignId: String, snapshotId: SnapshotId? = null): CampaignDetail {
        val requested = requireSegment(campaignId, "campaign id")
        val builder = operatorUrl("campaigns", requested)
        snapshotId?.let { builder.addQueryParameter("snapshot_id", it.value) }
        val root = execute(builder.build(), snapshotId)
        val actual = root.snapshotId()
        val overview = parseOverview(root.requireObject("campaign"))
        if (overview.campaignId != requested) throw protocol("Campaign-detail matcher ikke requestet")
        return CampaignDetail(actual, overview)
    }

    fun timeline(
        campaignId: String,
        snapshotId: SnapshotId,
        after: SnapshotCursor? = null,
        limit: Int = DEFAULT_LIMIT,
    ): TimelinePage {
        validateLimit(limit)
        val requested = requireSegment(campaignId, "campaign id")
        after?.let {
            requireContinuation(
                snapshotId,
                it,
                CursorKind.TIMELINE,
                expectedCampaignId = requested,
            )
        }
        val builder = operatorUrl("campaigns", requested, "timeline")
            .addQueryParameter("snapshot_id", snapshotId.value)
            .addQueryParameter("limit", limit.toString())
        after?.let { builder.addQueryParameter("after", it.encoded) }
        val root = execute(builder.build(), snapshotId)
        val actual = root.snapshotId()
        val page = root.requireObject("page")
        val returned = page.requireText("campaign_id")
        if (returned != requested) throw protocol("Timeline matcher ikke requestet campaign")
        val records = page.requireArray("entries").objects("entries").map { parseTimeline(it, returned) }
        val start = page.requireSnapshotCursor(
            "start_cursor",
            actual,
            CursorKind.TIMELINE,
            expectedCampaignId = returned,
        )
        val next = page.requireSnapshotCursor(
            "next_cursor",
            actual,
            CursorKind.TIMELINE,
            expectedCampaignId = returned,
        )
        val head = page.requireSnapshotCursor(
            "head_cursor",
            actual,
            CursorKind.TIMELINE,
            expectedCampaignId = returned,
        )
        val hasMore = page.requireBoolean("has_more")
        validatePage("timeline", records, start, next, head, hasMore)
        return TimelinePage(actual, returned, records.map { it.canonical }, start, next, head, hasMore)
    }

    fun evidencePage(
        campaignId: String,
        snapshotId: SnapshotId,
        after: SnapshotCursor? = null,
        limit: Int = DEFAULT_LIMIT,
    ): EvidencePage {
        validateLimit(limit)
        val requested = requireSegment(campaignId, "campaign id")
        after?.let {
            requireContinuation(
                snapshotId,
                it,
                CursorKind.EVIDENCE,
                expectedCampaignId = requested,
            )
        }
        val builder = operatorUrl("campaigns", requested, "evidence")
            .addQueryParameter("snapshot_id", snapshotId.value)
            .addQueryParameter("limit", limit.toString())
        after?.let { builder.addQueryParameter("after", it.encoded) }
        val root = execute(builder.build(), snapshotId)
        val actual = root.snapshotId()
        val page = root.requireObject("page")
        val returned = page.requireText("campaign_id")
        if (returned != requested) throw protocol("Evidence matcher ikke requestet campaign")
        val records = page.requireArray("records").objects("records").map { parseEvidence(it, returned) }
        val start = page.requireSnapshotCursor(
            "start_cursor",
            actual,
            CursorKind.EVIDENCE,
            expectedCampaignId = returned,
        )
        val next = page.requireSnapshotCursor(
            "next_cursor",
            actual,
            CursorKind.EVIDENCE,
            expectedCampaignId = returned,
        )
        val head = page.requireSnapshotCursor(
            "head_cursor",
            actual,
            CursorKind.EVIDENCE,
            expectedCampaignId = returned,
        )
        val hasMore = page.requireBoolean("has_more")
        validatePage("evidence", records, start, next, head, hasMore)
        return EvidencePage(actual, returned, records.map { it.canonical }, start, next, head, hasMore)
    }

    fun evidenceVerification(campaignId: String, snapshotId: SnapshotId): EvidenceVerification {
        val requested = requireSegment(campaignId, "campaign id")
        val root = execute(
            operatorUrl("campaigns", requested, "evidence", "verification")
                .addQueryParameter("snapshot_id", snapshotId.value)
                .build(),
            snapshotId,
        )
        val actual = root.snapshotId()
        val value = root.requireObject("verification")
        val returned = value.requireText("campaign_id")
        if (returned != requested) throw protocol("Verification matcher ikke requestet campaign")
        return EvidenceVerification(
            actual,
            returned,
            value.requireNonNegativeInt("record_count"),
            value.optionalHash("head_hash"),
            value.optionalHash("latest_timeline_head_hash"),
        )
    }

    fun evidence(campaignId: String, evidenceId: String, snapshotId: SnapshotId): EvidenceDetail {
        val campaign = requireSegment(campaignId, "campaign id")
        val evidence = requireSegment(evidenceId, "evidence id")
        val root = execute(
            operatorUrl("campaigns", campaign, "evidence", evidence)
                .addQueryParameter("snapshot_id", snapshotId.value)
                .build(),
            snapshotId,
        )
        val actual = root.snapshotId()
        val value = root.requireObject("evidence")
        if (value.requireText("schema") != EVIDENCE_RECORD_SCHEMA || value.requireText("campaign_id") != campaign) {
            throw protocol("Evidence matcher ikke valgt snapshot/campaign")
        }
        if (value.requireObject("evidence").requireText("evidence_id") != evidence) {
            throw protocol("Evidence matcher ikke requestet evidence id")
        }
        return EvidenceDetail(actual, Agent4OperatorClient.CanonicalJson(value.toString()))
    }

    private fun execute(url: HttpUrl, expectedSnapshot: SnapshotId?): JSONObject {
        val request = Request.Builder().url(url).get().cacheControl(noStore)
            .header("Authorization", "Bearer $token").header("Accept", MEDIA_TYPE).build()
        try {
            http.newCall(request).execute().use { response ->
                val text = response.body?.string().orEmpty()
                if (!response.isSuccessful) throw classifyFailure(response.code, text)
                val type = response.header("Content-Type")?.substringBefore(';')?.trim()
                if (type != MEDIA_TYPE) throw protocol("Ukendt Agent 4-medietype: ${type ?: "mangler"}")
                val root = parseObject(text)
                if (root.requireText("schema") != SCHEMA) throw protocol("Ukendt Agent 4 v2-schema")
                val actual = root.snapshotId()
                if (expectedSnapshot != null && actual != expectedSnapshot) {
                    throw protocol("Agent 4-svar skiftede snapshot_id midt i flowet")
                }
                return root
            }
        } catch (known: OperatorException) {
            throw known
        } catch (failure: IOException) {
            throw OperatorException(ErrorKind.UNAVAILABLE, message = "Agent 4 kan ikke nås", cause = failure)
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
            } else OperatorException(ErrorKind.AUTH_REQUIRED, status, "Adgang til Agent 4 blev afvist")
            404 -> OperatorException(ErrorKind.NOT_FOUND, status, "Data findes ikke i valgt snapshot")
            410 -> OperatorException(ErrorKind.REFRESH_REQUIRED, status, "Agent 4-snapshot er udløbet; opdatér visningen")
            405, 422 -> OperatorException(ErrorKind.REQUEST_REJECTED, status, detail)
            503 -> OperatorException(ErrorKind.UNAVAILABLE, status, "Agent 4-read er midlertidigt utilgængelig")
            else -> OperatorException(ErrorKind.UNAVAILABLE, status, "Agent 4 fejlede: $detail")
        }
    }

    private fun requireContinuation(
        snapshotId: SnapshotId?,
        cursor: SnapshotCursor,
        kind: CursorKind,
        expectedCampaignId: String? = null,
        expectedStatuses: List<String>? = null,
    ) {
        if (snapshotId == null) throw protocol("Paging kræver eksplicit snapshot_id")
        if (cursor.snapshotId != snapshotId) throw protocol("Cursor tilhører et andet snapshot")
        if (cursor.kind != kind) throw protocol("Cursor har forkert ressource-type")
        if (expectedCampaignId != null && cursor.campaignId != expectedCampaignId) {
            throw protocol("Cursor tilhører en anden campaign")
        }
        if (expectedStatuses != null && cursor.statusValues != expectedStatuses) {
            throw protocol("Cursor tilhører et andet statusfilter")
        }
    }

    private fun JSONObject.requireSnapshotCursor(
        name: String,
        snapshotId: SnapshotId,
        kind: CursorKind,
        expectedCampaignId: String? = null,
        expectedStatuses: List<String>? = null,
    ): SnapshotCursor {
        val envelope = requireObject(name)
        if (envelope.requireText("schema") != SNAPSHOT_CURSOR_SCHEMA) throw protocol("Ukendt snapshot-cursor-schema")
        val cursorSnapshot = SnapshotId(envelope.requireSnapshotId("snapshot_id"))
        if (cursorSnapshot != snapshotId) throw protocol("Cursor og svar har forskellig snapshot_id")
        val inner = envelope.requireObject("cursor")
        val expectedSchema = when (kind) {
            CursorKind.CAMPAIGN_LIST -> CAMPAIGN_CURSOR_SCHEMA
            CursorKind.TIMELINE -> TIMELINE_CURSOR_SCHEMA
            CursorKind.EVIDENCE -> EVIDENCE_CURSOR_SCHEMA
        }
        if (inner.requireText("schema") != expectedSchema) throw protocol("Snapshot-cursor har forkert inner schema")

        var sequence: Int? = null
        var hash: String? = null
        var campaignId: String? = null
        var statusValues: List<String>? = null
        if (kind == CursorKind.CAMPAIGN_LIST) {
            val statuses = inner.requireTextList("statuses")
            if (statuses.distinct().size != statuses.size) {
                throw protocol("Campaign-cursor har dublerede statusfiltre")
            }
            val normalized = statuses.map { status ->
                Agent4OperatorClient.CampaignStatus.entries.firstOrNull { it.wireValue == status }
                    ?: throw protocol("Campaign-cursor har ukendt statusfilter")
            }.sortedBy { it.wireValue }.map { it.wireValue }
            if (statuses != normalized) throw protocol("Campaign-cursor statusfiltre er ikke canonical")
            if (expectedStatuses != null && statuses != expectedStatuses) {
                throw protocol("Campaign-cursor matcher ikke requestet statusfilter")
            }
            val position = inner.requireNonNegativeInt("position")
            val total = inner.requireNonNegativeInt("total")
            if (position > total) throw protocol("Campaign-cursor position overstiger total")
            val lastCampaignId = inner.optionalCursorText("last_campaign_id")
            if ((position == 0 && lastCampaignId != null) || (position > 0 && lastCampaignId == null)) {
                throw protocol("Campaign-cursor har ugyldig last_campaign_id-binding")
            }
            inner.requireHash("snapshot_sha256")
            statusValues = statuses
        } else {
            campaignId = inner.requireText("campaign_id")
            if (expectedCampaignId != null && campaignId != expectedCampaignId) {
                throw protocol("Snapshot-cursor tilhører en anden campaign")
            }
            sequence = inner.requireNonNegativeInt("sequence")
            val field = if (kind == CursorKind.TIMELINE) "entry_hash" else "record_hash"
            hash = inner.optionalHash(field)
            if ((sequence == 0 && hash != null) || (sequence > 0 && hash == null)) {
                throw protocol("Snapshot-cursor har ugyldig hash-binding")
            }
        }
        return SnapshotCursor(
            encoded = envelope.toString(),
            snapshotId = cursorSnapshot,
            kind = kind,
            sequence = sequence,
            hash = hash,
            campaignId = campaignId,
            statusValues = statusValues,
        )
    }

    private fun validatePage(
        label: String,
        records: List<BoundRecord>,
        start: SnapshotCursor,
        next: SnapshotCursor,
        head: SnapshotCursor,
        hasMore: Boolean,
    ) {
        val startSeq = start.sequence ?: throw protocol("$label start-cursor mangler sequence")
        val nextSeq = next.sequence ?: throw protocol("$label next-cursor mangler sequence")
        val headSeq = head.sequence ?: throw protocol("$label head-cursor mangler sequence")
        if (startSeq > nextSeq || nextSeq > headSeq) throw protocol("$label-cursors har ugyldig rækkefølge")
        if (records.size != nextSeq - startSeq) throw protocol("$label-side matcher ikke cursor-intervallet")
        records.forEachIndexed { index, record ->
            if (record.sequence != startSeq + index + 1) throw protocol("$label-side har sequence-tab eller overlap")
        }
        if (records.isEmpty() && next.encoded != start.encoded) throw protocol("Tom $label-side må ikke flytte cursor")
        if (records.isNotEmpty() && next.hash != records.last().hash) throw protocol("$label-side matcher ikke next-cursor hash")
        if (hasMore != (nextSeq < headSeq)) throw protocol("$label-side har modstridende has_more")
    }

    private fun parseOverview(value: JSONObject): Agent4OperatorClient.CampaignOverview {
        val record = value.requireObject("record")
        if (record.requireText("schema") != CAMPAIGN_RECORD_SCHEMA) throw protocol("Ukendt campaign-record-schema")
        val spec = record.requireObject("spec")
        val state = record.requireObject("state")
        val id = spec.requireText("campaign_id")
        if (state.requireText("campaign_id") != id) throw protocol("Campaign-record har modstridende id'er")
        val statusText = state.requireText("status")
        val status = Agent4OperatorClient.CampaignStatus.entries.firstOrNull { it.wireValue == statusText }
            ?: throw protocol("Ukendt Agent 4-status: $statusText")
        return Agent4OperatorClient.CampaignOverview(
            id,
            spec.requireText("name"),
            status,
            value.requireNonNegativeInt("timeline_entries"),
            value.requireNonNegativeInt("event_entries"),
            value.requireNonNegativeInt("evidence_entries"),
            value.optionalHash("latest_timeline_hash"),
            Agent4OperatorClient.CanonicalJson(record.toString()),
        )
    }

    private fun parseTimeline(value: JSONObject, campaignId: String): BoundRecord {
        if (value.requireText("schema") != TIMELINE_ENTRY_SCHEMA) throw protocol("Ukendt timeline-entry-schema")
        val event = value.requireObject("event")
        if (event.requireText("campaign_id") != campaignId) throw protocol("Timeline-entry tilhører anden campaign")
        return BoundRecord(event.requirePositiveInt("sequence"), value.requireHash("entry_hash"), Agent4OperatorClient.CanonicalJson(value.toString()))
    }

    private fun parseEvidence(value: JSONObject, campaignId: String): BoundRecord {
        if (value.requireText("schema") != EVIDENCE_RECORD_SCHEMA || value.requireText("campaign_id") != campaignId) {
            throw protocol("Evidence-record tilhører anden campaign")
        }
        return BoundRecord(value.requirePositiveInt("sequence"), value.requireHash("record_hash"), Agent4OperatorClient.CanonicalJson(value.toString()))
    }

    private fun operatorUrl(vararg segments: String): HttpUrl.Builder {
        val builder = base.newBuilder().addPathSegments(OPERATOR_PATH)
        segments.forEach(builder::addPathSegment)
        return builder
    }

    private fun validateLimit(limit: Int) {
        if (limit !in 1..MAX_LIMIT) throw protocol("Agent 4-limit skal være mellem 1 og $MAX_LIMIT")
    }

    private fun requireSegment(value: String, label: String): String {
        val normalized = value.trim()
        if (normalized.isEmpty() || normalized != value || normalized.length > 512) throw protocol("Ugyldigt $label")
        return normalized
    }

    private fun JSONObject.snapshotId(): SnapshotId = SnapshotId(requireSnapshotId("snapshot_id"))

    private fun JSONObject.requireSnapshotId(name: String): String {
        val value = requireText(name)
        if (!SNAPSHOT_ID.matches(value)) throw protocol("Agent 4-svaret har ugyldigt $name")
        return value
    }

    private fun JSONObject.requireObject(name: String): JSONObject = optJSONObject(name) ?: throw protocol("Agent 4-svaret mangler $name")
    private fun JSONObject.requireArray(name: String): JSONArray = optJSONArray(name) ?: throw protocol("Agent 4-svaret mangler $name")
    private fun JSONObject.requireText(name: String): String {
        if (!has(name) || isNull(name)) throw protocol("Agent 4-svaret mangler $name")
        val value = get(name)
        if (value !is String || value.isBlank()) throw protocol("Agent 4-svaret har ugyldigt $name")
        return value
    }
    private fun JSONObject.strictOptionalText(name: String): String? {
        if (!has(name) || isNull(name)) return null
        val value = get(name)
        return if (value is String && value.isNotBlank()) value else null
    }
    private fun JSONObject.requireNonNegativeInt(name: String): Int {
        if (!has(name) || isNull(name)) throw protocol("Agent 4-svaret mangler $name")
        val raw = get(name)
        if (raw !is Number) throw protocol("Agent 4-svaret har ugyldigt $name")
        val value = raw.toLong()
        if (raw.toDouble() != value.toDouble() || value !in 0..Int.MAX_VALUE.toLong()) throw protocol("Agent 4-svaret har ugyldigt $name")
        return value.toInt()
    }
    private fun JSONObject.requirePositiveInt(name: String): Int = requireNonNegativeInt(name).also {
        if (it < 1) throw protocol("Agent 4-svaret har ugyldigt $name")
    }
    private fun JSONObject.requireBoolean(name: String): Boolean {
        if (!has(name) || isNull(name) || get(name) !is Boolean) throw protocol("Agent 4-svaret har ugyldigt $name")
        return getBoolean(name)
    }
    private fun JSONObject.optionalText(name: String): String? {
        if (!has(name) || isNull(name)) return null
        val value = get(name)
        if (value !is String || value.isBlank()) throw protocol("Agent 4-svaret har ugyldigt $name")
        return value
    }
    private fun JSONObject.optionalCursorText(name: String): String? {
        if (!has(name) || isNull(name)) return null
        val value = get(name)
        if (value !is String || value.isBlank() || value != value.trim()) {
            throw protocol("Agent 4-svaret har ugyldigt $name")
        }
        return value
    }
    private fun JSONObject.requireHash(name: String): String = optionalHash(name) ?: throw protocol("Agent 4-svaret mangler $name")
    private fun JSONObject.optionalHash(name: String): String? {
        val value = optionalText(name) ?: return null
        if (!HASH.matches(value)) throw protocol("Agent 4-svaret har ugyldigt $name")
        return value
    }
    private fun JSONObject.requireTextList(name: String): List<String> {
        val array = requireArray(name)
        return buildList {
            for (index in 0 until array.length()) {
                val value = array.get(index)
                if (value !is String || value.isBlank() || value != value.trim()) {
                    throw protocol("Agent 4-svaret har ugyldig $name-post")
                }
                add(value)
            }
        }
    }
    private fun JSONArray.objects(label: String): List<JSONObject> = buildList {
        for (index in 0 until length()) add(optJSONObject(index) ?: throw protocol("Agent 4-$label indeholder ugyldig post"))
    }
    private fun parseObject(text: String): JSONObject = runCatching { JSONObject(text) }
        .getOrElse { throw protocol("Agent 4 returnerede ugyldig JSON", it) }
    private fun protocol(message: String, cause: Throwable? = null): OperatorException = OperatorException(ErrorKind.PROTOCOL, message = message, cause = cause)
}
