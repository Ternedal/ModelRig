package dk.ternedal.modelrig.debug

import android.content.Context
import android.content.pm.ApplicationInfo
import android.os.Bundle
import androidx.activity.ComponentActivity
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.Agent4SnapshotOperatorClient
import dk.ternedal.modelrig.ui.Agent4SnapshotDetailPolicy
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.time.Instant

/**
 * Debug-only A4-25f physical probe.
 *
 * Invoke explicitly with adb using only the safe `stage` extra. The probe reads
 * the already-paired backend URL/token from private TokenStore and never accepts
 * credentials, roots or cursors through adb. Continuation state is app-private.
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
            "detail-start",
            "detail-continue",
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
            "detail-start" -> detailStart(client, baseUrl)
            "detail-continue" -> detailContinue(client, baseUrl)
            "fresh-root" -> freshRoot(client, baseUrl)
            "unknown-root" -> unknownRoot(client, baseUrl)
            else -> error("unreachable A4-25f probe stage")
        }
    }

    private fun listStart(
        client: Agent4SnapshotOperatorClient,
        baseUrl: String,
    ): JSONObject {
        clearPrefix("list.")
        val page = client.listCampaigns(limit = PAGE_LIMIT)
        require(page.hasMore) { "physical list fixture did not cross page boundary" }
        require(page.campaigns.size == PAGE_LIMIT) { "physical list first page size drifted" }
        val ids = page.campaigns.map { it.campaignId }
        require(ids.distinct().size == ids.size) { "physical list first page contains duplicates" }
        saveSnapshot("list.root", page.snapshotId)
        saveCursor("list.next", page.nextCursor)
        saveCursor("list.head", page.headCursor)
        prefs().edit().putString("list.ids", JSONArray(ids).toString()).commit().also {
            require(it) { "unable to persist A4-25f list ids" }
        }
        return success(stage = "list-start", baseUrl = baseUrl, snapshot = page.snapshotId)
            .put("page_count", page.campaigns.size)
            .put("has_more", page.hasMore)
            .put("next_cursor_sha256", sha256(page.nextCursor.encoded))
            .put("head_cursor_sha256", sha256(page.headCursor.encoded))
    }

    private fun listContinue(
        client: Agent4SnapshotOperatorClient,
        baseUrl: String,
    ): JSONObject {
        val root = loadSnapshot("list.root")
        val next = loadCursor("list.next")
        val head = loadCursor("list.head")
        val firstIds = jsonStringList(prefs().getString("list.ids", null) ?: error("list baseline ids missing"))
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
        return success(stage = "list-continue", baseUrl = baseUrl, snapshot = page.snapshotId)
            .put("first_page_count", firstIds.size)
            .put("second_page_count", secondIds.size)
            .put("combined_count", firstIds.size + secondIds.size)
            .put("has_more", page.hasMore)
            .put("next_cursor_sha256", sha256(page.nextCursor.encoded))
            .put("head_cursor_sha256", sha256(page.headCursor.encoded))
    }

    private fun detailStart(
        client: Agent4SnapshotOperatorClient,
        baseUrl: String,
    ): JSONObject {
        clearPrefix("detail.")
        val detail = client.campaign(SELECTED_CAMPAIGN_ID)
        val root = detail.snapshotId
        val timeline = client.timeline(SELECTED_CAMPAIGN_ID, root, limit = PAGE_LIMIT)
        val evidence = client.evidencePage(SELECTED_CAMPAIGN_ID, root, limit = PAGE_LIMIT)
        val verification = client.evidenceVerification(SELECTED_CAMPAIGN_ID, root)
        Agent4SnapshotDetailPolicy.requireConsistent(detail, timeline, evidence, verification)
        require(timeline.hasMore) { "physical timeline fixture did not cross page boundary" }
        require(evidence.hasMore) { "physical evidence fixture did not cross page boundary" }
        require(timeline.entries.size == PAGE_LIMIT) { "physical timeline first page size drifted" }
        require(evidence.records.size == PAGE_LIMIT) { "physical evidence first page size drifted" }
        saveSnapshot("detail.root", root)
        saveCursor("detail.timeline.next", timeline.nextCursor)
        saveCursor("detail.evidence.next", evidence.nextCursor)
        prefs().edit()
            .putInt("detail.timeline.first_count", timeline.entries.size)
            .putInt("detail.evidence.first_count", evidence.records.size)
            .commit().also { require(it) { "unable to persist A4-25f detail counts" } }
        return success(stage = "detail-start", baseUrl = baseUrl, snapshot = root)
            .put("campaign_revision_record_sha256", sha256(detail.campaign.record.json))
            .put("timeline_first_count", timeline.entries.size)
            .put("timeline_head_sequence", timeline.headCursor.sequence)
            .put("timeline_head_hash", timeline.headCursor.hash)
            .put("evidence_first_count", evidence.records.size)
            .put("evidence_head_sequence", evidence.headCursor.sequence)
            .put("evidence_head_hash", evidence.headCursor.hash)
            .put("verification_count", verification.recordCount)
            .put("verification_head_hash", verification.headHash)
    }

    private fun detailContinue(
        client: Agent4SnapshotOperatorClient,
        baseUrl: String,
    ): JSONObject {
        val root = loadSnapshot("detail.root")
        val timelineNext = loadCursor("detail.timeline.next")
        val evidenceNext = loadCursor("detail.evidence.next")
        val timeline = client.timeline(
            SELECTED_CAMPAIGN_ID,
            root,
            after = timelineNext,
            limit = PAGE_LIMIT,
        )
        val evidence = client.evidencePage(
            SELECTED_CAMPAIGN_ID,
            root,
            after = evidenceNext,
            limit = PAGE_LIMIT,
        )
        val verification = client.evidenceVerification(SELECTED_CAMPAIGN_ID, root)
        require(timeline.snapshotId == root && evidence.snapshotId == root && verification.snapshotId == root) {
            "detail continuation changed retained root"
        }
        require(!timeline.hasMore) { "physical timeline unexpectedly needs a third page" }
        require(!evidence.hasMore) { "physical evidence unexpectedly needs a third page" }
        val firstTimeline = prefs().getInt("detail.timeline.first_count", -1)
        val firstEvidence = prefs().getInt("detail.evidence.first_count", -1)
        require(firstTimeline == PAGE_LIMIT && firstEvidence == PAGE_LIMIT) { "detail baseline counts missing" }
        require(firstTimeline + timeline.entries.size == timeline.headCursor.sequence) {
            "timeline continuation does not close exactly at retained head"
        }
        require(firstEvidence + evidence.records.size == evidence.headCursor.sequence) {
            "evidence continuation does not close exactly at retained head"
        }
        require(verification.recordCount == evidence.headCursor.sequence) {
            "verification no longer matches retained evidence head"
        }
        require(verification.headHash == evidence.headCursor.hash) {
            "verification hash no longer matches retained evidence head"
        }
        return success(stage = "detail-continue", baseUrl = baseUrl, snapshot = root)
            .put("timeline_second_count", timeline.entries.size)
            .put("timeline_combined_count", firstTimeline + timeline.entries.size)
            .put("timeline_head_sequence", timeline.headCursor.sequence)
            .put("timeline_head_hash", timeline.headCursor.hash)
            .put("evidence_second_count", evidence.records.size)
            .put("evidence_combined_count", firstEvidence + evidence.records.size)
            .put("evidence_head_sequence", evidence.headCursor.sequence)
            .put("evidence_head_hash", evidence.headCursor.hash)
            .put("verification_count", verification.recordCount)
            .put("verification_head_hash", verification.headHash)
    }

    private fun freshRoot(
        client: Agent4SnapshotOperatorClient,
        baseUrl: String,
    ): JSONObject {
        val previous = prefs().getString("detail.root.value", null)
            ?: prefs().getString("list.root.value", null)
            ?: error("no retained baseline root is available")
        val fresh = client.campaign(SELECTED_CAMPAIGN_ID)
        require(fresh.snapshotId.value != previous) {
            "fresh flow did not observe a newer published root"
        }
        return success(stage = "fresh-root", baseUrl = baseUrl, snapshot = fresh.snapshotId)
            .put("previous_snapshot_id", previous)
            .put("root_changed", true)
            .put("campaign_record_sha256", sha256(fresh.campaign.record.json))
    }

    private fun unknownRoot(
        client: Agent4SnapshotOperatorClient,
        baseUrl: String,
    ): JSONObject {
        val unknown = Agent4SnapshotOperatorClient.SnapshotId("f".repeat(64))
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
        // Intentionally omit throwable.message: transport/server errors can carry
        // remote detail strings. Physical evidence only needs typed fail-closed state.
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
        val digest = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
        return "sha256:" + digest.joinToString("") { "%02x".format(it) }
    }
}
