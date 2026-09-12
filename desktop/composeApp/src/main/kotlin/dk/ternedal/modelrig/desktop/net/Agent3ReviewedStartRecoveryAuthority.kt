package dk.ternedal.modelrig.desktop.net

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
