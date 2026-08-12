package dk.ternedal.modelrig.debug

import android.content.Context
import android.content.pm.ApplicationInfo
import android.os.Bundle
import androidx.activity.ComponentActivity
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.Agent4OperatorClient
import dk.ternedal.modelrig.net.Agent4SnapshotOperatorClient
import dk.ternedal.modelrig.ui.Agent4SnapshotDetailPolicy
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.time.Instant

/**
 * A4-25f physical probe, compiled only into the isolated `a425f` app variant.
 *
 * Invoke explicitly with adb using only the safe `stage` extra. The probe reads
 * this variant's separately paired backend URL/token from private TokenStore and
 * never accepts credentials, roots or cursors through adb. Continuation state is
 * app-private, so the app/process may be restarted between stages without
 * weakening the test.
 */
class Agent4SnapshotPhysicalProbeActivity : ComponentActivity() {
    companion object {
        const val EXTRA_STAGE = "stage"
        const val SELECTED_CAMPAIGN_ID = "a4-25f-physical-primary"
        private const val SCHEMA = "modelrig-agent4/a4-25f-android-probe/v1"
        private const val STATE_PREFS = "modelrig-a4-25f-probe"
        private const val PAGE_LIMIT = 25
        private val ALLOWED_STAGES = setOf(
            "list-start",
            "list-continue",
            "detail-capture",
            "timeline-start",
            "timeline-continue",
            "evidence-start",
            "evidence-continue",
            "verification",
            "fresh-root",
            "unknown-root",
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE == 0) {
            finishAndRemoveTask()
            return
        }
        val stage = intent.getStringExtra(EXTRA_STAGE).orEmpty()
        Thread {
            val receipt = runCatching { runStage(stage) }
                .fold(
                    onSuccess = { it },
                    onFailure = { failureReceipt(stage, it) },
                )
            writeReceipt(stage, receipt)
            runOnUiThread { finishAndRemoveTask() }
        }.start()
    }

    private fun runStage(stage: String): JSONObject {
        require(stage in ALLOWED_STAGES) { "unsupported A4-25f probe stage" }
        val store = TokenStore(this)
        val baseUrl = store.baseUrl?.trim()?.takeIf { it.isNotEmpty() }
            ?: error("paired rig base URL is missing")
        val token = store.token?.takeIf { it.isNotEmpty() }
            ?: error("paired rig credential is missing or invalid")
        val client = Agent4SnapshotOperatorClient(baseUrl, token)
        return when (stage) {
            "list-start" -> listStart(client, baseUrl)
            "list-continue" -> listContinue(client, baseUrl)
            "detail-capture" -> detailCapture(client, baseUrl)
            "timeline-start" -> timelineStart(client, baseUrl)
            "timeline-continue" -> timelineContinue(client, baseUrl)
            "evidence-start" -> evidenceStart(client, baseUrl)
            "evidence-continue" -> evidenceContinue(client, baseUrl)
            "verification" -> verification(client, baseUrl)
            "fresh-root" -> freshRoot(client, baseUrl)
            "unknown-root" -> unknownRoot(client, baseUrl)
            else -> error("unreachable A4-25f probe stage")
        }
    }

    private fun listStart(client: Agent4SnapshotOperatorClient, baseUrl: String): JSONObject {
        clearPrefix("list.")
        val page = client.listCampaigns(limit = PAGE_LIMIT)
        require(page.hasMore) { "physical list fixture did not cross page boundary" }
        require(page.campaigns.size == PAGE_LIMIT) { "physical list first page size drifted" }
        val ids = page.campaigns.map { it.campaignId }
        require(ids.distinct().size == ids.size) { "physical list first page contains duplicates" }
        saveSnapshot("list.root", page.snapshotId)
        saveCursor("list.next", page.nextCursor)
        saveCursor("list.head", page.headCursor)
        require(prefs().edit().putString("list.ids", JSONArray(ids).toString()).commit()) {
            "unable to persist A4-25f list ids"
        }
        return success("list-start", baseUrl, page.snapshotId)
            .put("page_count", ids.size)
            .put("has_more", page.hasMore)
            .put("next_cursor_sha256", sha256(page.nextCursor.encoded))
            .put("head_cursor_sha256", sha256(page.headCursor.encoded))
    }

    private fun listContinue(client: Agent4SnapshotOperatorClient, baseUrl: String): JSONObject {
        val root = loadSnapshot("list.root")
        val next = loadCursor("list.next")
        val head = loadCursor("list.head")
        val firstIds = jsonStringList(
            prefs().getString("list.ids", null) ?: error("list baseline ids missing"),
        )
        val page = client.listCampaigns(
            snapshotId = root,
            after = next,
            snapshotHead = head,
            limit = PAGE_LIMIT,
        )
        require(page.snapshotId == root) { "list continuation changed root" }
        require(!page.hasMore) { "physical list fixture unexpectedly needs a third page" }
        val secondIds = page.campaigns.map { it.campaignId }
        require(secondIds.isNotEmpty()) { "physical list continuation is empty" }
        require(firstIds.toSet().intersect(secondIds.toSet()).isEmpty()) {
            "physical list continuation overlaps first page"
        }
        require((firstIds + secondIds).distinct().size == firstIds.size + secondIds.size) {
            "physical list continuation contains duplicate campaign ids"
        }
        return success("list-continue", baseUrl, page.snapshotId)
            .put("first_page_count", firstIds.size)
            .put("second_page_count", secondIds.size)
            .put("combined_count", firstIds.size + secondIds.size)
            .put("has_more", page.hasMore)
            .put("next_cursor_sha256", sha256(page.nextCursor.encoded))
            .put("head_cursor_sha256", sha256(page.headCursor.encoded))
    }

    private fun detailCapture(client: Agent4SnapshotOperatorClient, baseUrl: String): JSONObject {
        clearPrefix("detail.")
        val detail = client.campaign(SELECTED_CAMPAIGN_ID)
        val root = detail.snapshotId
        saveSnapshot("detail.root", root)
        val editor = prefs().edit()
            .putInt("detail.timeline.count", detail.campaign.timelineEntries)
            .putString("detail.timeline.hash", detail.campaign.latestTimelineHash)
            .putString("detail.status", detail.campaign.status.name)
            .putString("detail.record.sha256", sha256(detail.campaign.record.value))
        require(editor.commit()) { "unable to persist A4-25f detail baseline" }
        return success("detail-capture", baseUrl, root)
            .put("timeline_count", detail.campaign.timelineEntries)
            .put("timeline_head_hash", detail.campaign.latestTimelineHash)
            .put("campaign_status", detail.campaign.status.name)
            .put("campaign_record_sha256", sha256(detail.campaign.record.value))
    }

    private fun timelineStart(client: Agent4SnapshotOperatorClient, baseUrl: String): JSONObject {
        val root = loadSnapshot("detail.root")
        val page = client.timeline(SELECTED_CAMPAIGN_ID, root, limit = PAGE_LIMIT)
        require(page.snapshotId == root) { "timeline changed retained root" }
        require(page.hasMore) { "physical timeline fixture did not cross page boundary" }
        require(page.entries.size == PAGE_LIMIT) { "physical timeline first page size drifted" }
        require(page.headCursor.sequence == prefs().getInt("detail.timeline.count", -1)) {
            "A4-24 campaign/timeline count overlap changed under retained root"
        }
        require(page.headCursor.hash == prefs().getString("detail.timeline.hash", null)) {
            "A4-24 campaign/timeline hash overlap changed under retained root"
        }
        saveCursor("detail.timeline.next", page.nextCursor)
        saveCursor("detail.timeline.head", page.headCursor)
        require(prefs().edit().putInt("detail.timeline.first_count", page.entries.size).commit()) {
            "unable to persist A4-25f timeline baseline"
        }
        return success("timeline-start", baseUrl, page.snapshotId)
            .put("page_count", page.entries.size)
            .put("has_more", page.hasMore)
            .put("head_sequence", page.headCursor.sequence)
            .put("head_hash", page.headCursor.hash)
            .put("next_cursor_sha256", sha256(page.nextCursor.encoded))
    }

    private fun timelineContinue(client: Agent4SnapshotOperatorClient, baseUrl: String): JSONObject {
        val root = loadSnapshot("detail.root")
        val next = loadCursor("detail.timeline.next")
        val page = client.timeline(SELECTED_CAMPAIGN_ID, root, after = next, limit = PAGE_LIMIT)
        require(page.snapshotId == root) { "timeline continuation changed retained root" }
        require(!page.hasMore) { "physical timeline unexpectedly needs a third page" }
        val first = prefs().getInt("detail.timeline.first_count", -1)
        require(first == PAGE_LIMIT) { "timeline baseline count missing" }
        require(first + page.entries.size == page.headCursor.sequence) {
            "timeline continuation does not close at retained head"
        }
        require(page.headCursor.hash == prefs().getString("detail.timeline.hash", null)) {
            "timeline continuation head hash changed under retained root"
        }
        return success("timeline-continue", baseUrl, page.snapshotId)
            .put("second_page_count", page.entries.size)
            .put("combined_count", first + page.entries.size)
            .put("head_sequence", page.headCursor.sequence)
            .put("head_hash", page.headCursor.hash)
    }

    private fun evidenceStart(client: Agent4SnapshotOperatorClient, baseUrl: String): JSONObject {
        val root = loadSnapshot("detail.root")
        val page = client.evidencePage(SELECTED_CAMPAIGN_ID, root, limit = PAGE_LIMIT)
        require(page.snapshotId == root) { "evidence changed retained root" }
        require(page.hasMore) { "physical evidence fixture did not cross page boundary" }
        require(page.records.size == PAGE_LIMIT) { "physical evidence first page size drifted" }
        saveCursor("detail.evidence.next", page.nextCursor)
        saveCursor("detail.evidence.head", page.headCursor)
        require(
            prefs().edit()
                .putInt("detail.evidence.first_count", page.records.size)
                .putInt("detail.evidence.head.sequence", page.headCursor.sequence ?: -1)
                .putString("detail.evidence.head.hash", page.headCursor.hash)
                .commit(),
        ) { "unable to persist A4-25f evidence baseline" }
        return success("evidence-start", baseUrl, page.snapshotId)
            .put("page_count", page.records.size)
            .put("has_more", page.hasMore)
            .put("head_sequence", page.headCursor.sequence)
            .put("head_hash", page.headCursor.hash)
            .put("next_cursor_sha256", sha256(page.nextCursor.encoded))
    }

    private fun evidenceContinue(client: Agent4SnapshotOperatorClient, baseUrl: String): JSONObject {
        val root = loadSnapshot("detail.root")
        val next = loadCursor("detail.evidence.next")
        val page = client.evidencePage(SELECTED_CAMPAIGN_ID, root, after = next, limit = PAGE_LIMIT)
        require(page.snapshotId == root) { "evidence continuation changed retained root" }
        require(!page.hasMore) { "physical evidence unexpectedly needs a third page" }
        val first = prefs().getInt("detail.evidence.first_count", -1)
        require(first == PAGE_LIMIT) { "evidence baseline count missing" }
        require(first + page.records.size == page.headCursor.sequence) {
            "evidence continuation does not close at retained head"
        }
        require(page.headCursor.hash == prefs().getString("detail.evidence.head.hash", null)) {
            "evidence continuation head hash changed under retained root"
        }
        return success("evidence-continue", baseUrl, page.snapshotId)
            .put("second_page_count", page.records.size)
            .put("combined_count", first + page.records.size)
            .put("head_sequence", page.headCursor.sequence)
            .put("head_hash", page.headCursor.hash)
    }

    private fun verification(client: Agent4SnapshotOperatorClient, baseUrl: String): JSONObject {
        val root = loadSnapshot("detail.root")
        val result = client.evidenceVerification(SELECTED_CAMPAIGN_ID, root)
        require(result.snapshotId == root) { "verification changed retained root" }
        val evidenceHead = loadCursor("detail.evidence.head")
        require(result.recordCount == evidenceHead.sequence) {
            "A4-24 evidence count overlap changed under retained root"
        }
        require(result.headHash == evidenceHead.hash) {
            "A4-24 evidence hash overlap changed under retained root"
        }
        runFullA424Policy(root, result)
        return success("verification", baseUrl, result.snapshotId)
            .put("record_count", result.recordCount)
            .put("head_hash", result.headHash)
            .put("latest_timeline_head_hash", result.latestTimelineHeadHash)
            .put("a4_24_policy", "passed")
    }

    private fun runFullA424Policy(
        root: Agent4SnapshotOperatorClient.SnapshotId,
        verification: Agent4SnapshotOperatorClient.EvidenceVerification,
    ) {
        val timelineHead = loadCursor("detail.timeline.head")
        val evidenceHead = loadCursor("detail.evidence.head")
        val status = Agent4OperatorClient.CampaignStatus.valueOf(
            prefs().getString("detail.status", null) ?: error("detail status missing"),
        )
        val overview = Agent4OperatorClient.CampaignOverview(
            campaignId = SELECTED_CAMPAIGN_ID,
            name = "A4-25f physical snapshot primary",
            status = status,
            timelineEntries = prefs().getInt("detail.timeline.count", -1),
            eventEntries = prefs().getInt("detail.timeline.count", -1),
            evidenceEntries = verification.recordCount,
            latestTimelineHash = prefs().getString("detail.timeline.hash", null),
            record = Agent4OperatorClient.CanonicalJson("{}"),
        )
        val detail = Agent4SnapshotOperatorClient.CampaignDetail(root, overview)
        val timeline = Agent4SnapshotOperatorClient.TimelinePage(
            snapshotId = root,
            campaignId = SELECTED_CAMPAIGN_ID,
            entries = emptyList(),
            startCursor = timelineHead,
            nextCursor = timelineHead,
            headCursor = timelineHead,
            hasMore = false,
        )
        val evidence = Agent4SnapshotOperatorClient.EvidencePage(
            snapshotId = root,
            campaignId = SELECTED_CAMPAIGN_ID,
            records = emptyList(),
            startCursor = evidenceHead,
            nextCursor = evidenceHead,
            headCursor = evidenceHead,
            hasMore = false,
        )
        Agent4SnapshotDetailPolicy.requireConsistent(detail, timeline, evidence, verification)
    }

    private fun freshRoot(client: Agent4SnapshotOperatorClient, baseUrl: String): JSONObject {
        val previous = prefs().getString("detail.root.value", null)
            ?: prefs().getString("list.root.value", null)
            ?: error("no retained baseline root is available")
        val fresh = client.campaign(SELECTED_CAMPAIGN_ID)
        require(fresh.snapshotId.value != previous) { "fresh flow did not observe a newer published root" }
        return success("fresh-root", baseUrl, fresh.snapshotId)
            .put("previous_snapshot_id", previous)
            .put("root_changed", true)
            .put("campaign_record_sha256", sha256(fresh.campaign.record.value))
    }

    private fun unknownRoot(client: Agent4SnapshotOperatorClient, baseUrl: String): JSONObject {
        val retained = prefs().getString("detail.root.value", null)
            ?: prefs().getString("list.root.value", null)
            ?: error("no retained baseline root is available")
        val replacement = if (retained[0] == '0') '1' else '0'
        val unknown = Agent4SnapshotOperatorClient.SnapshotId(replacement + retained.substring(1))
        val failure = runCatching {
            client.campaign(SELECTED_CAMPAIGN_ID, unknown)
        }.exceptionOrNull() as? Agent4SnapshotOperatorClient.OperatorException
            ?: error("unknown root unexpectedly succeeded")
        require(failure.kind == Agent4SnapshotOperatorClient.ErrorKind.REFRESH_REQUIRED) {
            "unknown root did not map to refresh-required"
        }
        require(failure.statusCode == 410) { "unknown root did not return HTTP 410" }
        return baseReceipt("unknown-root", baseUrl)
            .put("success", true)
            .put("unknown_snapshot_id", unknown.value)
            .put("expected_error_kind", failure.kind.name)
            .put("http_status", failure.statusCode)
            .put("request_count_semantics", "single_no_fallback")
    }

    private fun success(
        stage: String,
        baseUrl: String,
        snapshot: Agent4SnapshotOperatorClient.SnapshotId,
    ): JSONObject = baseReceipt(stage, baseUrl)
        .put("success", true)
        .put("snapshot_id", snapshot.value)

    private fun failureReceipt(stage: String, failure: Throwable): JSONObject {
        val base = baseReceipt(stage.ifBlank { "invalid" }, null)
            .put("success", false)
            .put("failure_type", failure::class.java.simpleName)
        if (failure is Agent4SnapshotOperatorClient.OperatorException) {
            base.put("error_kind", failure.kind.name)
            failure.statusCode?.let { base.put("http_status", it) }
        }
        // Deliberately omit failure.message: remote details are not physical evidence.
        return base
    }

    private fun baseReceipt(stage: String, baseUrl: String?): JSONObject = JSONObject()
        .put("schema", SCHEMA)
        .put("recorded_at", Instant.now().toString())
        .put("stage", stage)
        .put("selected_campaign_id", SELECTED_CAMPAIGN_ID)
        .put("backend_url_sha256", baseUrl?.let(::sha256) ?: JSONObject.NULL)
        .put("credential_in_receipt", false)
        .put("raw_cursor_in_receipt", false)
        .put("production_activation", false)

    private fun prefs() = getSharedPreferences(STATE_PREFS, Context.MODE_PRIVATE)

    private fun clearPrefix(prefix: String) {
        val editor = prefs().edit()
        prefs().all.keys.filter { it.startsWith(prefix) }.forEach(editor::remove)
        require(editor.commit()) { "unable to clear stale A4-25f probe state" }
    }

    private fun saveSnapshot(key: String, value: Agent4SnapshotOperatorClient.SnapshotId) {
        require(prefs().edit().putString("$key.value", value.value).commit()) {
            "unable to persist A4-25f snapshot"
        }
    }

    private fun loadSnapshot(key: String): Agent4SnapshotOperatorClient.SnapshotId =
        Agent4SnapshotOperatorClient.SnapshotId(
            prefs().getString("$key.value", null) ?: error("A4-25f snapshot state missing"),
        )

    private fun saveCursor(key: String, cursor: Agent4SnapshotOperatorClient.SnapshotCursor) {
        val statuses = cursor.statusValues?.let { JSONArray(it).toString() }
        val editor = prefs().edit()
            .putString("$key.encoded", cursor.encoded)
            .putString("$key.snapshot", cursor.snapshotId.value)
            .putString("$key.kind", cursor.kind.name)
            .putString("$key.hash", cursor.hash)
            .putString("$key.campaign", cursor.campaignId)
            .putString("$key.statuses", statuses)
        cursor.sequence?.let { editor.putInt("$key.sequence", it) } ?: editor.remove("$key.sequence")
        require(editor.commit()) { "unable to persist A4-25f cursor" }
    }

    private fun loadCursor(key: String): Agent4SnapshotOperatorClient.SnapshotCursor {
        val p = prefs()
        return Agent4SnapshotOperatorClient.SnapshotCursor(
            encoded = p.getString("$key.encoded", null) ?: error("A4-25f cursor encoding missing"),
            snapshotId = Agent4SnapshotOperatorClient.SnapshotId(
                p.getString("$key.snapshot", null) ?: error("A4-25f cursor root missing"),
            ),
            kind = Agent4SnapshotOperatorClient.CursorKind.valueOf(
                p.getString("$key.kind", null) ?: error("A4-25f cursor kind missing"),
            ),
            sequence = if (p.contains("$key.sequence")) p.getInt("$key.sequence", -1) else null,
            hash = p.getString("$key.hash", null),
            campaignId = p.getString("$key.campaign", null),
            statusValues = p.getString("$key.statuses", null)?.let(::jsonStringList),
        )
    }

    private fun jsonStringList(raw: String): List<String> {
        val array = JSONArray(raw)
        return buildList {
            for (index in 0 until array.length()) add(array.getString(index))
        }
    }

    private fun writeReceipt(stage: String, receipt: JSONObject) {
        val safeStage = stage.takeIf { it in ALLOWED_STAGES } ?: "invalid"
        val bytes = (receipt.toString(2) + "\n").toByteArray(Charsets.UTF_8)
        File(filesDir, "a4-25f-probe-$safeStage.json").writeBytes(bytes)
        File(filesDir, "a4-25f-probe-last.json").writeBytes(bytes)
    }

    private fun sha256(value: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(value.toByteArray(Charsets.UTF_8))
        return "sha256:" + digest.joinToString("") { "%02x".format(it) }
    }
}
