package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.Agent4OperatorClient
import org.json.JSONObject

internal data class Agent4CampaignDetail(
    val workflow: String,
    val createdAt: String,
    val priority: Int,
    val maxAttempts: Int,
    val attempt: Int,
    val revision: Int,
    val updatedAt: String,
    val lastError: String?,
)

internal data class Agent4TimelineRow(
    val sequence: Int,
    val kind: String,
    val occurredAt: String,
    val eventId: String,
    val entryHash: String,
    val evidenceCount: Int,
)

internal data class Agent4EvidenceRow(
    val sequence: Int,
    val recordedAt: String,
    val evidenceId: String,
    val mediaType: String,
    val location: String,
    val sizeBytes: Long,
    val recordHash: String,
)

internal object Agent4OperatorPresentation {
    fun campaignDetail(value: Agent4OperatorClient.CanonicalJson): Agent4CampaignDetail {
        val record = objectValue(value)
        requireSchema(record, "modelrig-agent4/campaign-record/v1")
        val spec = record.requireObject("spec")
        val state = record.requireObject("state")
        return Agent4CampaignDetail(
            workflow = spec.requireText("workflow"),
            createdAt = spec.requireText("created_at"),
            priority = spec.requireNonNegativeInt("priority"),
            maxAttempts = spec.requirePositiveInt("max_attempts"),
            attempt = state.requireNonNegativeInt("attempt"),
            revision = state.requireNonNegativeInt("revision"),
            updatedAt = state.requireText("updated_at"),
            lastError = state.optionalText("last_error"),
        )
    }

    fun timelineRow(value: Agent4OperatorClient.CanonicalJson): Agent4TimelineRow {
        val entry = objectValue(value)
        requireSchema(entry, "modelrig-agent4/campaign-timeline-entry/v1")
        val event = entry.requireObject("event")
        return Agent4TimelineRow(
            sequence = event.requirePositiveInt("sequence"),
            kind = event.requireText("kind"),
            occurredAt = event.requireText("occurred_at"),
            eventId = event.requireText("event_id"),
            entryHash = entry.requireSha256("entry_hash"),
            evidenceCount = entry.requireArrayLength("evidence"),
        )
    }

    fun evidenceRow(value: Agent4OperatorClient.CanonicalJson): Agent4EvidenceRow {
        val record = objectValue(value)
        requireSchema(record, "modelrig-agent4/campaign-evidence-record/v1")
        val evidence = record.requireObject("evidence")
        return Agent4EvidenceRow(
            sequence = record.requirePositiveInt("sequence"),
            recordedAt = record.requireText("recorded_at"),
            evidenceId = evidence.requireText("evidence_id"),
            mediaType = evidence.requireText("media_type"),
            location = evidence.requireText("location"),
            sizeBytes = evidence.requireNonNegativeLong("size_bytes"),
            recordHash = record.requireSha256("record_hash"),
        )
    }

    private fun objectValue(value: Agent4OperatorClient.CanonicalJson): JSONObject =
        runCatching { JSONObject(value.value) }
            .getOrElse { throw IllegalArgumentException("Agent 4-data er ikke gyldig JSON", it) }

    private fun requireSchema(value: JSONObject, expected: String) {
        if (value.requireText("schema") != expected) {
            throw IllegalArgumentException("Agent 4-data har ukendt schema")
        }
    }

    private fun JSONObject.requireObject(name: String): JSONObject =
        optJSONObject(name) ?: throw IllegalArgumentException("Agent 4-data mangler $name")

    private fun JSONObject.requireText(name: String): String {
        if (!has(name) || isNull(name)) throw IllegalArgumentException("Agent 4-data mangler $name")
        val value = get(name)
        if (value !is String || value.isBlank()) {
            throw IllegalArgumentException("Agent 4-data har ugyldigt $name")
        }
        return value
    }

    private fun JSONObject.optionalText(name: String): String? {
        if (!has(name) || isNull(name)) return null
        val value = get(name)
        if (value !is String || value.isBlank()) {
            throw IllegalArgumentException("Agent 4-data har ugyldigt $name")
        }
        return value
    }

    private fun JSONObject.requirePositiveInt(name: String): Int {
        val value = requireNonNegativeInt(name)
        if (value < 1) throw IllegalArgumentException("Agent 4-data har ugyldigt $name")
        return value
    }

    private fun JSONObject.requireNonNegativeInt(name: String): Int {
        val value = requireNonNegativeLong(name)
        if (value > Int.MAX_VALUE) throw IllegalArgumentException("Agent 4-data har ugyldigt $name")
        return value.toInt()
    }

    private fun JSONObject.requireNonNegativeLong(name: String): Long {
        if (!has(name) || isNull(name)) throw IllegalArgumentException("Agent 4-data mangler $name")
        val raw = get(name)
        if (raw !is Number) throw IllegalArgumentException("Agent 4-data har ugyldigt $name")
        val value = raw.toLong()
        if (value < 0 || raw.toDouble() != value.toDouble()) {
            throw IllegalArgumentException("Agent 4-data har ugyldigt $name")
        }
        return value
    }

    private fun JSONObject.requireSha256(name: String): String {
        val value = requireText(name)
        if (!value.matches(Regex("sha256:[0-9a-f]{64}"))) {
            throw IllegalArgumentException("Agent 4-data har ugyldigt $name")
        }
        return value
    }

    private fun JSONObject.requireArrayLength(name: String): Int =
        optJSONArray(name)?.length()
            ?: throw IllegalArgumentException("Agent 4-data mangler $name")
}
