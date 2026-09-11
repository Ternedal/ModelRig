package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Prove the safety-relevant raw checkpoint shape before kotlinx serialization
 * is allowed to coerce/default anything into the typed Apply result.
 */
internal fun validateReviewedReplanCheckpointShape(raw: JsonObject) {
    raw.requireReviewBoolean("enabled")
    val waiting = raw.requireReviewBoolean("waiting")
    raw.requireReviewStringArray("removable_step_ids")
    if (waiting) {
        raw.requireReviewInt("window_start")
        raw.requireReviewInt("window_end")
        raw.requireReviewNonBlankString("completed_step_id")
        raw.requireReviewNonBlankString("completed_tool")
    }
}

/**
 * Semantic post-Apply checkpoint binding for the standalone reviewed replanner.
 *
 * This surface does not carry immutable pre-Apply review-mode authority, so an
 * idle checkpoint may legitimately be enabled or disabled. A waiting checkpoint
 * is authoritative only when it exactly describes the returned run's pending
 * read window.
 */
internal fun validateReviewedReplanCheckpoint(
    raw: JsonObject,
    result: Agent3ReplanApplyResult,
) {
    val review = result.readReview
    val run = result.run
    val enabled = raw.requireReviewBoolean("enabled")
    val waiting = raw.requireReviewBoolean("waiting")
    val removableIds = raw.requireReviewStringArray("removable_step_ids")

    if (
        enabled != review.enabled ||
        waiting != review.waiting ||
        removableIds != review.removableStepIds
    ) {
        checkpointMismatch("read_review")
    }

    if (!waiting) {
        if (
            review.windowStart != null ||
            review.windowEnd != null ||
            removableIds.isNotEmpty() ||
            review.completedStepId != null ||
            review.completedTool != null
        ) {
            checkpointMismatch("cleared read_review checkpoint")
        }
        return
    }

    if (!enabled || run.state != "running") {
        checkpointMismatch("waiting read_review state")
    }

    val start = raw.requireReviewInt("window_start")
    val end = raw.requireReviewInt("window_end")
    if (
        review.windowStart != start ||
        review.windowEnd != end ||
        start != run.currentStep ||
        start < 0 ||
        end <= start ||
        end > run.steps.size
    ) {
        checkpointMismatch("read_review window")
    }

    val window = run.steps.subList(start, end)
    if (window.any { it.id.isNullOrBlank() || it.risk != "read" || it.state != "pending" }) {
        checkpointMismatch("read_review window steps")
    }
    val expectedIds = window.map { requireNotNull(it.id) }
    if (removableIds != expectedIds) {
        checkpointMismatch("read_review.removable_step_ids")
    }

    val completedStepId = raw.requireReviewNonBlankString("completed_step_id")
    val completedTool = raw.requireReviewNonBlankString("completed_tool")
    if (
        review.completedStepId != completedStepId ||
        review.completedTool != completedTool
    ) {
        checkpointMismatch("read_review completed checkpoint")
    }
}

private fun JsonObject.requireReviewBoolean(name: String): Boolean {
    val raw = this[name] as? JsonPrimitive
    val value = raw?.takeIf { !it.isString }?.content
    return when (value) {
        "true" -> true
        "false" -> false
        else -> checkpointMismatch("read_review.$name")
    }
}

private fun JsonObject.requireReviewInt(name: String): Int {
    val raw = this[name] as? JsonPrimitive
    return raw?.takeIf { !it.isString }?.content?.toIntOrNull()
        ?: checkpointMismatch("read_review.$name")
}

private fun JsonObject.requireReviewNonBlankString(name: String): String {
    val raw = this[name] as? JsonPrimitive
    return raw?.takeIf { it.isString }?.content?.takeIf { it.isNotBlank() }
        ?: checkpointMismatch("read_review.$name")
}

private fun JsonObject.requireReviewStringArray(name: String): List<String> {
    val raw = this[name] as? JsonArray
        ?: checkpointMismatch("read_review.$name")
    return raw.map { item ->
        (item as? JsonPrimitive)
            ?.takeIf { it.isString }
            ?.content
            ?.takeIf { it.isNotBlank() }
            ?: checkpointMismatch("read_review.$name")
    }
}

private fun checkpointMismatch(field: String): Nothing =
    throw Agent3Exception("Agent 3.0 replan Apply checkpoint authority mismatch: $field")
