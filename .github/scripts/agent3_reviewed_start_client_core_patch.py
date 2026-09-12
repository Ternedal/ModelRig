from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"anchor missing in {path}: {old[:120]!r}")
    if text.count(old) != 1:
        raise SystemExit(f"anchor not unique in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def write_new(path: str, content: str) -> None:
    target = ROOT / path
    if target.exists():
        if target.read_text(encoding="utf-8") != content:
            raise SystemExit(f"refusing to overwrite unexpected existing file: {path}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


# Android: reviewed Start gets a narrow transport that preserves the worker reason header.
android_client = "android/app/src/main/java/dk/ternedal/modelrig/net/Agent3Client.kt"
replace_once(
    android_client,
    '        val root = post("/api/v1/experimental/agent3/plans/${seg(planId)}/start", JSONObject())\n        if (expectedCapabilityReceiptPresent != null) {',
    '        val root = postReviewedStart("/api/v1/experimental/agent3/plans/${seg(planId)}/start", JSONObject())\n        if (expectedCapabilityReceiptPresent != null) {',
)
replace_once(
    android_client,
    '''    private fun post(path: String, payload: JSONObject): JSONObject = execute(\n        Request.Builder()\n            .url(base + path)\n            .post(payload.toString().toRequestBody(jsonType))\n            .header("Authorization", "Bearer $token")\n            .build(),\n    )\n\n    private fun execute(request: Request): JSONObject {''',
    '''    private fun post(path: String, payload: JSONObject): JSONObject = execute(\n        Request.Builder()\n            .url(base + path)\n            .post(payload.toString().toRequestBody(jsonType))\n            .header("Authorization", "Bearer $token")\n            .build(),\n    )\n\n    private fun postReviewedStart(path: String, payload: JSONObject): JSONObject {\n        val request = Request.Builder()\n            .url(base + path)\n            .post(payload.toString().toRequestBody(jsonType))\n            .header("Authorization", "Bearer $token")\n            .build()\n        try {\n            http.newCall(request).execute().use { response ->\n                val text = response.body?.string().orEmpty()\n                if (!response.isSuccessful) {\n                    val detail = runCatching {\n                        val root = JSONObject(text)\n                        root.optString("error").ifBlank { root.optString("detail") }\n                    }.getOrNull()?.ifBlank { null } ?: text.take(500)\n                    throw Agent3ReviewedStartHttpException(\n                        statusCode = response.code,\n                        reasonCode = response.header("X-ModelRig-Agent3-Reason")\n                            ?.trim()\n                            ?.takeIf { it.isNotEmpty() },\n                        message = "Agent 3.0 failed (${response.code}): $detail",\n                    )\n                }\n                return runCatching { JSONObject(text) }\n                    .getOrElse { throw ModelRigException("Agent 3.0 returned invalid JSON") }\n            }\n        } catch (failure: Agent3ReviewedStartHttpException) {\n            throw failure\n        } catch (failure: java.io.IOException) {\n            throw Agent3ReviewedStartHttpException(\n                statusCode = null,\n                reasonCode = null,\n                message = "Agent 3.0 reviewed Start transport failed: ${failure.message ?: failure::class.simpleName}",\n                cause = failure,\n            )\n        }\n    }\n\n    private fun execute(request: Request): JSONObject {''',
)

android_authority = r'''package dk.ternedal.modelrig.net

import org.json.JSONArray
import org.json.JSONObject

internal class Agent3ReviewedStartHttpException(
    val statusCode: Int?,
    val reasonCode: String?,
    message: String,
    cause: Throwable? = null,
) : RuntimeException(message, cause)

/** Minimal operator-reviewed authority retained only while Start outcome is ambiguous. */
internal data class Agent3ReviewedStartRecoveryAuthority(
    val planId: String,
    val expectedReviewReads: Boolean,
    val expectedCapabilityReceipt: Agent3Client.CapabilityReceipt?,
) {
    fun encode(): String {
        val root = JSONObject()
            .put("schema", SCHEMA)
            .put("plan_id", planId)
            .put("review_reads", expectedReviewReads)
        val receipt = expectedCapabilityReceipt
        root.put("capability_receipt", receipt?.toRecoveryJson() ?: JSONObject.NULL)
        return root.toString()
    }

    companion object {
        private const val SCHEMA = "kaliv-agent3-reviewed-start-recovery/v1"
        private val SHA256 = Regex("^[0-9a-f]{64}$")

        fun capture(
            planId: String,
            expectedReviewReads: Boolean,
            expectedCapabilityReceipt: Agent3Client.CapabilityReceipt?,
        ): Agent3ReviewedStartRecoveryAuthority? {
            val normalizedPlanId = planId.trim().takeIf { it.isNotEmpty() } ?: return null
            if (expectedCapabilityReceipt != null && !validReceipt(expectedCapabilityReceipt)) return null
            return Agent3ReviewedStartRecoveryAuthority(
                planId = normalizedPlanId,
                expectedReviewReads = expectedReviewReads,
                expectedCapabilityReceipt = expectedCapabilityReceipt,
            )
        }

        fun decode(raw: String?): Agent3ReviewedStartRecoveryAuthority? {
            if (raw.isNullOrBlank()) return null
            return runCatching {
                val root = JSONObject(raw)
                if (root.opt("schema") !is String || root.getString("schema") != SCHEMA) return null
                val plan = root.opt("plan_id") as? String ?: return null
                val review = root.opt("review_reads") as? Boolean ?: return null
                if (!root.has("capability_receipt")) return null
                val receipt = when (val value = root.opt("capability_receipt")) {
                    null, JSONObject.NULL -> null
                    is JSONObject -> decodeReceipt(value) ?: return null
                    else -> return null
                }
                capture(plan, review, receipt)
            }.getOrNull()
        }

        private fun decodeReceipt(root: JSONObject): Agent3Client.CapabilityReceipt? {
            fun string(name: String): String? = (root.opt(name) as? String)?.takeIf { it.isNotBlank() }
            fun bool(name: String): Boolean? = root.opt(name) as? Boolean
            val schema = string("schema") ?: return null
            val graph = string("graph_sha256") ?: return null
            val plan = string("plan_sha256") ?: return null
            val route = string("route") ?: return null
            val allowed = bool("allowed") ?: return null
            val production = bool("production_activation") ?: return null
            val requiredRaw = root.opt("required_capability_ids") as? JSONArray ?: return null
            val required = buildList {
                for (index in 0 until requiredRaw.length()) {
                    val value = requiredRaw.opt(index) as? String ?: return null
                    if (value.isBlank()) return null
                    add(value)
                }
            }
            val blockerRaw = root.opt("blockers") as? JSONArray ?: return null
            val blockers = buildList {
                for (index in 0 until blockerRaw.length()) {
                    val item = blockerRaw.opt(index) as? JSONObject ?: return null
                    add(
                        Agent3Client.CapabilityBlocker(
                            capabilityId = (item.opt("capability_id") as? String)?.takeIf { it.isNotBlank() } ?: return null,
                            state = (item.opt("state") as? String)?.takeIf { it.isNotBlank() } ?: return null,
                            reason = (item.opt("reason") as? String)?.takeIf { it.isNotBlank() } ?: return null,
                        )
                    )
                }
            }
            val receipt = Agent3Client.CapabilityReceipt(
                schema = schema,
                graphSha256 = graph,
                planSha256 = plan,
                route = route,
                allowed = allowed,
                requiredCapabilityIds = required,
                blockers = blockers,
                productionActivation = production,
            )
            return receipt.takeIf(::validReceipt)
        }

        private fun validReceipt(receipt: Agent3Client.CapabilityReceipt): Boolean =
            receipt.schema == "kaliv-agent3-capability-receipt/v1" &&
                !receipt.productionActivation &&
                SHA256.matches(receipt.graphSha256) &&
                SHA256.matches(receipt.planSha256) &&
                receipt.route.isNotBlank() &&
                receipt.requiredCapabilityIds.all { it.isNotBlank() } &&
                receipt.requiredCapabilityIds.distinct().size == receipt.requiredCapabilityIds.size &&
                receipt.blockers.all {
                    it.capabilityId.isNotBlank() && it.state.isNotBlank() && it.reason.isNotBlank()
                } &&
                (!receipt.allowed || receipt.blockers.isEmpty())
    }
}

private fun Agent3Client.CapabilityReceipt.toRecoveryJson(): JSONObject = JSONObject()
    .put("schema", schema)
    .put("graph_sha256", graphSha256)
    .put("plan_sha256", planSha256)
    .put("route", route)
    .put("allowed", allowed)
    .put("required_capability_ids", JSONArray(requiredCapabilityIds))
    .put(
        "blockers",
        JSONArray().also { array ->
            blockers.forEach { blocker ->
                array.put(
                    JSONObject()
                        .put("capability_id", blocker.capabilityId)
                        .put("state", blocker.state)
                        .put("reason", blocker.reason)
                )
            }
        },
    )
    .put("production_activation", productionActivation)

internal fun shouldRetainReviewedStartRecovery(failure: Throwable): Boolean =
    (failure as? Agent3ReviewedStartHttpException)?.reasonCode != "reviewed_start_refused"
'''
write_new(
    "android/app/src/main/java/dk/ternedal/modelrig/net/Agent3ReviewedStartRecoveryAuthority.kt",
    android_authority,
)

android_store = r'''package dk.ternedal.modelrig.data

import android.content.Context

/** URL-scoped storage for the opaque reviewed-Start recovery authority record. */
class Agent3ReviewedStartRecoveryStore(context: Context) {
    private val prefs = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)

    fun read(baseUrl: String?): String? = agent3ReviewedStartRecoveryStorageKey(baseUrl)
        ?.let { prefs.getString(it, null) }
        ?.trim()
        ?.takeIf { it.isNotEmpty() }

    fun write(baseUrl: String?, encodedAuthority: String?): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        val normalized = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() }
        val editor = prefs.edit()
        if (normalized == null) editor.remove(key) else editor.putString(key, normalized)
        return editor.commit()
    }
}

internal fun agent3ReviewedStartRecoveryStorageKey(baseUrl: String?): String? =
    baseUrl
        ?.trim()
        ?.trimEnd('/')
        ?.takeIf { it.isNotEmpty() }
        ?.let { "$REVIEWED_START_RECOVERY_KEY_PREFIX:$it" }

private const val REVIEWED_START_RECOVERY_KEY_PREFIX = "agent3_reviewed_start_recovery"
'''
write_new(
    "android/app/src/main/java/dk/ternedal/modelrig/data/Agent3ReviewedStartRecoveryStore.kt",
    android_store,
)

android_test = r'''package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReviewedStartDurableRecoveryTest {
    private val digestA = "a".repeat(64)
    private val digestB = "b".repeat(64)

    private fun receipt() = Agent3Client.CapabilityReceipt(
        schema = "kaliv-agent3-capability-receipt/v1",
        graphSha256 = digestA,
        planSha256 = digestB,
        route = "rig",
        allowed = true,
        requiredCapabilityIds = listOf("rig.read"),
        blockers = emptyList(),
        productionActivation = false,
    )

    @Test
    fun `recovery authority round trips the exact reviewed contract`() {
        val original = Agent3ReviewedStartRecoveryAuthority.capture(" plan-1 ", true, receipt())
        assertNotNull(original)
        val decoded = Agent3ReviewedStartRecoveryAuthority.decode(original!!.encode())
        assertEquals("plan-1", decoded?.planId)
        assertEquals(true, decoded?.expectedReviewReads)
        assertEquals(receipt(), decoded?.expectedCapabilityReceipt)
    }

    @Test
    fun `malformed or production activating recovery authority fails closed`() {
        assertNull(Agent3ReviewedStartRecoveryAuthority.decode("{}"))
        val unsafe = receipt().copy(productionActivation = true)
        assertNull(Agent3ReviewedStartRecoveryAuthority.capture("plan-1", true, unsafe))
    }

    @Test
    fun `only explicit reviewed Start refusal clears retained authority`() {
        assertFalse(
            shouldRetainReviewedStartRecovery(
                Agent3ReviewedStartHttpException(409, "reviewed_start_refused", "refused")
            )
        )
        assertTrue(
            shouldRetainReviewedStartRecovery(
                Agent3ReviewedStartHttpException(409, "reviewed_start_pending", "pending")
            )
        )
        assertTrue(
            shouldRetainReviewedStartRecovery(
                Agent3ReviewedStartHttpException(501, "reviewed_start_executor_unavailable", "offline")
            )
        )
        assertTrue(shouldRetainReviewedStartRecovery(IllegalStateException("lost response")))
    }

    @Test
    fun `reviewed Start transport preserves machine readable refusal reason`() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse()
                .setResponseCode(409)
                .addHeader("X-ModelRig-Agent3-Reason", "reviewed_start_refused")
                .setBody("{\"detail\":\"reviewed Start is no longer recoverable\"}")
        )
        server.start()
        try {
            val failure = runCatching {
                Agent3Client(server.url("/").toString(), "token")
                    .startReviewedPlanEnvelope("plan-1", true, null)
            }.exceptionOrNull()
            assertTrue(failure is Agent3ReviewedStartHttpException)
            failure as Agent3ReviewedStartHttpException
            assertEquals(409, failure.statusCode)
            assertEquals("reviewed_start_refused", failure.reasonCode)
            assertTrue(failure.message.orEmpty().contains("reviewed Start is no longer recoverable"))
        } finally {
            server.shutdown()
        }
    }
}
'''
write_new(
    "android/app/src/test/java/dk/ternedal/modelrig/net/Agent3ReviewedStartDurableRecoveryTest.kt",
    android_test,
)

android_store_test = r'''package dk.ternedal.modelrig.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Test

class Agent3ReviewedStartRecoveryStoreTest {
    @Test
    fun `reviewed recovery key is normalized and rig scoped`() {
        assertEquals(
            agent3ReviewedStartRecoveryStorageKey(" https://rig.example/ "),
            agent3ReviewedStartRecoveryStorageKey("https://rig.example"),
        )
        assertNotEquals(
            agent3ReviewedStartRecoveryStorageKey("https://rig-a.example"),
            agent3ReviewedStartRecoveryStorageKey("https://rig-b.example"),
        )
        assertNull(agent3ReviewedStartRecoveryStorageKey("  "))
    }
}
'''
write_new(
    "android/app/src/test/java/dk/ternedal/modelrig/data/Agent3ReviewedStartRecoveryStoreTest.kt",
    android_store_test,
)

# Desktop transport and mirrored authority/store.
desktop_client = "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/net/Agent3Client.kt"
replace_once(
    desktop_client,
    '        val body = post("/api/v1/experimental/agent3/plans/${seg(planId)}/start", "{}")\n        val root = runCatching { json.parseToJsonElement(body) as? JsonObject }.getOrNull()',
    '        val body = postReviewedStart("/api/v1/experimental/agent3/plans/${seg(planId)}/start", "{}")\n        val root = runCatching { json.parseToJsonElement(body) as? JsonObject }.getOrNull()',
)
replace_once(
    desktop_client,
    '''    private fun post(path: String, body: String): String = send(\n        builder(path).POST(HttpRequest.BodyPublishers.ofString(body)).build()\n    )\n\n    private fun send(request: HttpRequest): String {''',
    '''    private fun post(path: String, body: String): String = send(\n        builder(path).POST(HttpRequest.BodyPublishers.ofString(body)).build()\n    )\n\n    private fun postReviewedStart(path: String, body: String): String {\n        val request = builder(path).POST(HttpRequest.BodyPublishers.ofString(body)).build()\n        try {\n            val response = http.send(request, HttpResponse.BodyHandlers.ofString())\n            if (response.statusCode() !in 200..299) {\n                throw Agent3ReviewedStartHttpException(\n                    statusCode = response.statusCode(),\n                    reasonCode = response.headers()\n                        .firstValue("X-ModelRig-Agent3-Reason")\n                        .orElse(null)\n                        ?.trim()\n                        ?.takeIf { it.isNotEmpty() },\n                    message = "Agent 3.0 failed (${response.statusCode()}): ${response.body().take(500)}",\n                )\n            }\n            return response.body()\n        } catch (failure: Agent3ReviewedStartHttpException) {\n            throw failure\n        } catch (failure: java.io.IOException) {\n            throw Agent3ReviewedStartHttpException(\n                statusCode = null,\n                reasonCode = null,\n                message = "Agent 3.0 reviewed Start transport failed: ${failure.message ?: failure::class.simpleName}",\n                cause = failure,\n            )\n        } catch (failure: InterruptedException) {\n            Thread.currentThread().interrupt()\n            throw Agent3ReviewedStartHttpException(\n                statusCode = null,\n                reasonCode = null,\n                message = "Agent 3.0 reviewed Start transport interrupted",\n                cause = failure,\n            )\n        }\n    }\n\n    private fun send(request: HttpRequest): String {''',
)

desktop_authority = r'''package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

internal class Agent3ReviewedStartHttpException(
    val statusCode: Int?,
    val reasonCode: String?,
    message: String,
    cause: Throwable? = null,
) : RuntimeException(message, cause)

internal data class Agent3ReviewedStartRecoveryAuthority(
    val planId: String,
    val expectedReviewReads: Boolean,
    val expectedCapabilityReceipt: Agent3CapabilityReceipt?,
) {
    fun encode(): String = codec.encodeToString(
        Wire(
            planId = planId,
            reviewReads = expectedReviewReads,
            capabilityReceipt = expectedCapabilityReceipt,
        )
    )

    companion object {
        private const val SCHEMA = "kaliv-agent3-reviewed-start-recovery/v1"
        private val SHA256 = Regex("^[0-9a-f]{64}$")
        private val codec = Json {
            ignoreUnknownKeys = false
            explicitNulls = true
            encodeDefaults = true
        }

        fun capture(
            planId: String,
            expectedReviewReads: Boolean,
            expectedCapabilityReceipt: Agent3CapabilityReceipt?,
        ): Agent3ReviewedStartRecoveryAuthority? {
            val normalizedPlanId = planId.trim().takeIf { it.isNotEmpty() } ?: return null
            if (expectedCapabilityReceipt != null && !validReceipt(expectedCapabilityReceipt)) return null
            return Agent3ReviewedStartRecoveryAuthority(
                planId = normalizedPlanId,
                expectedReviewReads = expectedReviewReads,
                expectedCapabilityReceipt = expectedCapabilityReceipt,
            )
        }

        fun decode(raw: String?): Agent3ReviewedStartRecoveryAuthority? {
            if (raw.isNullOrBlank()) return null
            val wire = runCatching { codec.decodeFromString<Wire>(raw) }.getOrNull() ?: return null
            if (wire.schema != SCHEMA) return null
            return capture(wire.planId, wire.reviewReads, wire.capabilityReceipt)
        }

        private fun validReceipt(receipt: Agent3CapabilityReceipt): Boolean =
            receipt.schema == "kaliv-agent3-capability-receipt/v1" &&
                !receipt.productionActivation &&
                SHA256.matches(receipt.graphSha256) &&
                SHA256.matches(receipt.planSha256) &&
                receipt.route.isNotBlank() &&
                receipt.requiredCapabilityIds.all { it.isNotBlank() } &&
                receipt.requiredCapabilityIds.distinct().size == receipt.requiredCapabilityIds.size &&
                receipt.blockers.all {
                    it.capabilityId.isNotBlank() && it.state.isNotBlank() && it.reason.isNotBlank()
                } &&
                (!receipt.allowed || receipt.blockers.isEmpty())
    }

    @Serializable
    private data class Wire(
        val schema: String = SCHEMA,
        @SerialName("plan_id") val planId: String,
        @SerialName("review_reads") val reviewReads: Boolean,
        @SerialName("capability_receipt") val capabilityReceipt: Agent3CapabilityReceipt?,
    )
}

internal fun shouldRetainReviewedStartRecovery(failure: Throwable): Boolean =
    (failure as? Agent3ReviewedStartHttpException)?.reasonCode != "reviewed_start_refused"
'''
write_new(
    "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/net/Agent3ReviewedStartRecoveryAuthority.kt",
    desktop_authority,
)

desktop_store = r'''package dk.ternedal.modelrig.desktop.data

/** Separate URL-scoped persistence for reviewed Start; task-surface authority is never reused. */
class Agent3ReviewedStartRecoveryStore(private val db: DesktopChatDb) {
    fun read(baseUrl: String?): String? = agent3ReviewedStartRecoveryStorageKey(baseUrl)
        ?.let(db::getSetting)
        ?.trim()
        ?.takeIf { it.isNotEmpty() }

    fun write(baseUrl: String?, encodedAuthority: String?): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        val normalized = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() }
        return runCatching {
            db.putSetting(key, normalized.orEmpty())
            true
        }.getOrDefault(false)
    }
}

internal fun agent3ReviewedStartRecoveryStorageKey(baseUrl: String?): String? =
    baseUrl
        ?.trim()
        ?.trimEnd('/')
        ?.takeIf { it.isNotEmpty() }
        ?.let { "$REVIEWED_START_RECOVERY_KEY_PREFIX:$it" }

private const val REVIEWED_START_RECOVERY_KEY_PREFIX = "agent3ReviewedStartRecovery"
'''
write_new(
    "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/data/Agent3ReviewedStartRecoveryStore.kt",
    desktop_store,
)

desktop_test = r'''package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3ReviewedStartDurableRecoveryTest {
    private val digestA = "a".repeat(64)
    private val digestB = "b".repeat(64)

    private fun receipt() = Agent3CapabilityReceipt(
        schema = "kaliv-agent3-capability-receipt/v1",
        graphSha256 = digestA,
        planSha256 = digestB,
        route = "rig",
        allowed = true,
        requiredCapabilityIds = listOf("rig.read"),
        blockers = emptyList(),
        productionActivation = false,
    )

    @Test
    fun recoveryAuthorityRoundTripsExactReviewedContract() {
        val original = Agent3ReviewedStartRecoveryAuthority.capture(" plan-1 ", true, receipt())
        assertNotNull(original)
        val decoded = Agent3ReviewedStartRecoveryAuthority.decode(original.encode())
        assertEquals("plan-1", decoded?.planId)
        assertEquals(true, decoded?.expectedReviewReads)
        assertEquals(receipt(), decoded?.expectedCapabilityReceipt)
    }

    @Test
    fun malformedOrProductionActivatingAuthorityFailsClosed() {
        assertNull(Agent3ReviewedStartRecoveryAuthority.decode("{}"))
        assertNull(
            Agent3ReviewedStartRecoveryAuthority.capture(
                "plan-1",
                true,
                receipt().copy(productionActivation = true),
            )
        )
    }

    @Test
    fun onlyExplicitRefusalClearsRetainedAuthority() {
        assertFalse(
            shouldRetainReviewedStartRecovery(
                Agent3ReviewedStartHttpException(409, "reviewed_start_refused", "refused")
            )
        )
        assertTrue(
            shouldRetainReviewedStartRecovery(
                Agent3ReviewedStartHttpException(409, "reviewed_start_pending", "pending")
            )
        )
        assertTrue(
            shouldRetainReviewedStartRecovery(
                Agent3ReviewedStartHttpException(501, "reviewed_start_executor_unavailable", "offline")
            )
        )
        assertTrue(shouldRetainReviewedStartRecovery(IllegalStateException("lost response")))
    }

    @Test
    fun reviewedStartTransportPreservesMachineReadableRefusalReason() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/api/v1/experimental/agent3/plans/plan-1/start") { exchange ->
            val body = "{\"detail\":\"reviewed Start is no longer recoverable\"}".toByteArray()
            exchange.responseHeaders.add("Content-Type", "application/json")
            exchange.responseHeaders.add("X-ModelRig-Agent3-Reason", "reviewed_start_refused")
            exchange.sendResponseHeaders(409, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        server.start()
        try {
            val failure = runCatching {
                Agent3Client("http://127.0.0.1:${server.address.port}", "token")
                    .startReviewedPlanEnvelope("plan-1", true, null)
            }.exceptionOrNull()
            assertTrue(failure is Agent3ReviewedStartHttpException)
            failure as Agent3ReviewedStartHttpException
            assertEquals(409, failure.statusCode)
            assertEquals("reviewed_start_refused", failure.reasonCode)
            assertTrue(failure.message.orEmpty().contains("reviewed Start is no longer recoverable"))
        } finally {
            server.stop(0)
        }
    }
}
'''
write_new(
    "desktop/composeApp/src/test/kotlin/dk/ternedal/modelrig/desktop/net/Agent3ReviewedStartDurableRecoveryTest.kt",
    desktop_test,
)

desktop_store_test = r'''package dk.ternedal.modelrig.desktop.data

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertNull

class Agent3ReviewedStartRecoveryStoreTest {
    @Test
    fun reviewedRecoveryKeyIsNormalizedAndRigScoped() {
        assertEquals(
            agent3ReviewedStartRecoveryStorageKey(" https://rig.example/ "),
            agent3ReviewedStartRecoveryStorageKey("https://rig.example"),
        )
        assertNotEquals(
            agent3ReviewedStartRecoveryStorageKey("https://rig-a.example"),
            agent3ReviewedStartRecoveryStorageKey("https://rig-b.example"),
        )
        assertNull(agent3ReviewedStartRecoveryStorageKey("  "))
    }
}
'''
write_new(
    "desktop/composeApp/src/test/kotlin/dk/ternedal/modelrig/desktop/data/Agent3ReviewedStartRecoveryStoreTest.kt",
    desktop_store_test,
)

print("reviewed Start client core patch applied")
