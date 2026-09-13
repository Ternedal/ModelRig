package dk.ternedal.modelrig.net

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
