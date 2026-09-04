package dk.ternedal.modelrig.debug

import android.content.Context
import android.content.pm.ApplicationInfo
import android.os.Bundle
import androidx.activity.ComponentActivity
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.Agent4SnapshotOperatorClient
import okhttp3.CacheControl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.time.Instant
import java.util.concurrent.TimeUnit

/** A425f-only physical failure probe. No credential/root/cursor is accepted from adb. */
class Agent4PhysicalFailureProbeActivity : ComponentActivity() {
    companion object {
        const val EXTRA_STAGE = "stage"
        private const val SCHEMA = "modelrig-agent4/a4-25f-failure-probe/v1"
        private const val PREFS = "modelrig-a4-25f-probe"
        private val STAGES = setOf(
            "selected-root-404",
            "server-422",
            "current-unavailable-503",
            "expired-retained-410",
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
            File(filesDir, "a4-25f-failure-$safe.json")
                .writeText(receipt.toString(2) + "\n", Charsets.UTF_8)
            runOnUiThread { finishAndRemoveTask() }
        }.start()
    }

    private fun runStage(stage: String): JSONObject {
        require(stage in STAGES) { "unsupported A4-25f failure stage" }
        val store = TokenStore(this)
        val baseUrl = store.baseUrl?.trim()?.takeIf { it.isNotEmpty() }
            ?: error("paired rig base URL missing")
        val token = store.token?.takeIf { it.isNotEmpty() }
            ?: error("paired rig credential missing")
        val root = retainedRoot()
        val result = when (stage) {
            "selected-root-404" -> selectedRoot404(baseUrl, token, root)
            "server-422" -> server422(baseUrl, token, root)
            "current-unavailable-503" -> currentUnavailable503(baseUrl, token)
            "expired-retained-410" -> expiredRetained410(baseUrl, token, root)
            else -> error("unreachable")
        }
        return JSONObject()
            .put("schema", SCHEMA)
            .put("recorded_at", Instant.now().toString())
            .put("stage", stage)
            .put("success", true)
            .put("retained_snapshot_id", root.value)
            .put("backend_url_sha256", sha256(baseUrl))
            .put("http_status", result.statusCode)
            .put("error_kind", result.kind.name)
            .put("credential_in_receipt", false)
            .put("raw_cursor_in_receipt", false)
            .put("production_activation", false)
    }

    private fun selectedRoot404(
        baseUrl: String,
        token: String,
        root: Agent4SnapshotOperatorClient.SnapshotId,
    ): FailureResult {
        val client = Agent4SnapshotOperatorClient(baseUrl, token)
        val failure = runCatching {
            client.campaign("a4-25f-does-not-exist", root)
        }.exceptionOrNull() as? Agent4SnapshotOperatorClient.OperatorException
            ?: error("selected-root 404 unexpectedly succeeded")
        require(failure.kind == Agent4SnapshotOperatorClient.ErrorKind.NOT_FOUND)
        require(failure.statusCode == 404)
        return FailureResult(failure.kind, failure.statusCode)
    }

    private fun server422(
        baseUrl: String,
        token: String,
        root: Agent4SnapshotOperatorClient.SnapshotId,
    ): FailureResult {
        val url = (baseUrl.trimEnd('/') + "/api/v1/experimental/agent4/operator/campaigns")
            .toHttpUrl()
            .newBuilder()
            .addQueryParameter("snapshot_id", root.value)
            .addQueryParameter("after", "{}")
            .addQueryParameter("snapshot_head", "{}")
            .build()
        val request = Request.Builder()
            .url(url)
            .get()
            .cacheControl(CacheControl.Builder().noCache().noStore().build())
            .header("Authorization", "Bearer $token")
            .header("Accept", Agent4SnapshotOperatorClient.MEDIA_TYPE)
            .build()
        val http = OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            .build()
        http.newCall(request).execute().use { response ->
            require(response.code == 422) { "malformed bound cursor was not HTTP 422" }
            return FailureResult(
                Agent4SnapshotOperatorClient.ErrorKind.REQUEST_REJECTED,
                response.code,
            )
        }
    }

    private fun currentUnavailable503(baseUrl: String, token: String): FailureResult {
        val client = Agent4SnapshotOperatorClient(baseUrl, token)
        val failure = runCatching {
            client.listCampaigns(limit = 1)
        }.exceptionOrNull() as? Agent4SnapshotOperatorClient.OperatorException
            ?: error("missing current pointer unexpectedly succeeded")
        require(failure.kind == Agent4SnapshotOperatorClient.ErrorKind.UNAVAILABLE)
        require(failure.statusCode == 503)
        return FailureResult(failure.kind, failure.statusCode)
    }

    private fun expiredRetained410(
        baseUrl: String,
        token: String,
        root: Agent4SnapshotOperatorClient.SnapshotId,
    ): FailureResult {
        val client = Agent4SnapshotOperatorClient(baseUrl, token)
        val failure = runCatching {
            client.campaign("a4-25f-physical-primary", root)
        }.exceptionOrNull() as? Agent4SnapshotOperatorClient.OperatorException
            ?: error("expired retained root unexpectedly succeeded")
        require(failure.kind == Agent4SnapshotOperatorClient.ErrorKind.REFRESH_REQUIRED)
        require(failure.statusCode == 410)
        return FailureResult(failure.kind, failure.statusCode)
    }

    private fun retainedRoot(): Agent4SnapshotOperatorClient.SnapshotId {
        val prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val value = prefs.getString("detail.root.value", null)
            ?: prefs.getString("list.root.value", null)
            ?: error("no retained A4-25f root available")
        return Agent4SnapshotOperatorClient.SnapshotId(value)
    }

    private fun sha256(value: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(value.toByteArray(Charsets.UTF_8))
        return "sha256:" + digest.joinToString("") { "%02x".format(it) }
    }

    private data class FailureResult(
        val kind: Agent4SnapshotOperatorClient.ErrorKind,
        val statusCode: Int?,
    )
}
