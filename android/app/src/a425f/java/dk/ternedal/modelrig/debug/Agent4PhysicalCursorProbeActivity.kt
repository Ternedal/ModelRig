package dk.ternedal.modelrig.debug

import android.content.Context
import android.content.pm.ApplicationInfo
import android.os.Bundle
import androidx.activity.ComponentActivity
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.Agent4OperatorClient
import dk.ternedal.modelrig.net.Agent4SnapshotOperatorClient
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.Instant

/** A425f-only proof that mismatched server cursors are rejected locally. */
class Agent4PhysicalCursorProbeActivity : ComponentActivity() {
    companion object {
        const val EXTRA_STAGE = "stage"
        private const val SCHEMA = "modelrig-agent4/a4-25f-cursor-probe/v1"
        private const val PREFS = "modelrig-a4-25f-probe"
        private const val CAMPAIGN_ID = "a4-25f-physical-primary"
        private val STAGES = setOf(
            "root-mismatch",
            "resource-mismatch",
            "filter-mismatch",
            "campaign-mismatch",
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
            val receipt = runCatching { runStage(stage) }.fold(
                onSuccess = { it },
                onFailure = { failure ->
                    JSONObject()
                        .put("schema", SCHEMA)
                        .put("recorded_at", Instant.now().toString())
                        .put("stage", stage.ifBlank { "invalid" })
                        .put("success", false)
                        .put("failure_type", failure::class.java.simpleName)
                        .put("credential_in_receipt", false)
                        .put("raw_cursor_in_receipt", false)
                        .put("production_activation", false)
                },
            )
            val safe = stage.takeIf { it in STAGES } ?: "invalid"
            File(filesDir, "a4-25f-cursor-$safe.json")
                .writeText(receipt.toString(2) + "\n", Charsets.UTF_8)
            runOnUiThread { finishAndRemoveTask() }
        }.start()
    }

    private fun runStage(stage: String): JSONObject {
        require(stage in STAGES) { "unsupported A4-25f cursor stage" }
        val store = TokenStore(this)
        val baseUrl = store.baseUrl?.trim()?.takeIf { it.isNotEmpty() }
            ?: error("paired rig base URL missing")
        val token = store.token?.takeIf { it.isNotEmpty() }
            ?: error("paired rig credential missing")
        val client = Agent4SnapshotOperatorClient(baseUrl, token)
        when (stage) {
            "root-mismatch" -> rootMismatch(client)
            "resource-mismatch" -> resourceMismatch(client)
            "filter-mismatch" -> filterMismatch(client)
            "campaign-mismatch" -> campaignMismatch(client)
        }
        return JSONObject()
            .put("schema", SCHEMA)
            .put("recorded_at", Instant.now().toString())
            .put("stage", stage)
            .put("success", true)
            .put("error_kind", Agent4SnapshotOperatorClient.ErrorKind.PROTOCOL.name)
            .put("local_rejection", true)
            .put("credential_in_receipt", false)
            .put("raw_cursor_in_receipt", false)
            .put("production_activation", false)
    }

    private fun rootMismatch(client: Agent4SnapshotOperatorClient) {
        val root = loadSnapshot("list.root")
        val after = loadCursor("list.next")
        val head = loadCursor("list.head")
        val replacement = if (root.value[0] == '0') '1' else '0'
        val wrong = Agent4SnapshotOperatorClient.SnapshotId(replacement + root.value.substring(1))
        expectProtocol {
            client.listCampaigns(
                snapshotId = root,
                after = after.copy(snapshotId = wrong),
                snapshotHead = head,
                limit = 25,
            )
        }
    }

    private fun resourceMismatch(client: Agent4SnapshotOperatorClient) {
        val root = loadSnapshot("list.root")
        val after = loadCursor("list.next")
        val head = loadCursor("list.head")
        expectProtocol {
            client.listCampaigns(
                snapshotId = root,
                after = after.copy(kind = Agent4SnapshotOperatorClient.CursorKind.TIMELINE),
                snapshotHead = head,
                limit = 25,
            )
        }
    }

    private fun filterMismatch(client: Agent4SnapshotOperatorClient) {
        val root = loadSnapshot("list.root")
        val after = loadCursor("list.next")
        val head = loadCursor("list.head")
        expectProtocol {
            client.listCampaigns(
                statuses = setOf(Agent4OperatorClient.CampaignStatus.RUNNING),
                snapshotId = root,
                after = after,
                snapshotHead = head,
                limit = 25,
            )
        }
    }

    private fun campaignMismatch(client: Agent4SnapshotOperatorClient) {
        val root = loadSnapshot("detail.root")
        val after = loadCursor("detail.timeline.next")
        expectProtocol {
            client.timeline(
                CAMPAIGN_ID,
                root,
                after = after.copy(campaignId = "a4-25f-other-campaign"),
                limit = 25,
            )
        }
    }

    private fun expectProtocol(block: () -> Unit) {
        val failure = runCatching(block).exceptionOrNull()
            as? Agent4SnapshotOperatorClient.OperatorException
            ?: error("mismatched cursor unexpectedly succeeded")
        require(failure.kind == Agent4SnapshotOperatorClient.ErrorKind.PROTOCOL) {
            "mismatched cursor did not fail as protocol error"
        }
    }

    private fun prefs() = getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    private fun loadSnapshot(key: String): Agent4SnapshotOperatorClient.SnapshotId =
        Agent4SnapshotOperatorClient.SnapshotId(
            prefs().getString("$key.value", null) ?: error("A4-25f snapshot state missing"),
        )

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
}
