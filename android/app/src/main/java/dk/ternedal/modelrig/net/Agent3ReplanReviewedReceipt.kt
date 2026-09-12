package dk.ternedal.modelrig.net

import org.json.JSONArray
import org.json.JSONObject

internal data class ReviewedReplanReceiptAuthority(
    val start: Int,
    val oldEnd: Int,
    val newEnd: Int,
    val removedStepIds: List<String>,
    val removedTools: List<String>,
    val addedStepIds: List<String>,
    val addedTools: List<String>,
    val immutablePrefixIds: List<String>,
    val immutableTailIds: List<String>,
)

/**
 * Bind every deterministic Apply-receipt field that the reviewed Preview can
 * prove before permissive JSONObject defaults reach operator-visible state.
 *
 * The reviewed Preview exposes removed step ids but not the original removed
 * tool names. For removed tools we therefore prove strict/nonblank shape,
 * cardinality, raw-to-typed preservation and the worker/run receipt boundary
 * without inventing exact old-name authority.
 *
 * Normal server-authored reviewed Previews expose replacement step ids. When
 * the complete ordered id list is present, Apply must preserve it exactly.
 * Directly constructed compatibility previews may omit ids; those retain the
 * existing cardinality plus committed-run binding fallback.
 */
internal fun validateReviewedReplanReceiptShape(
    raw: JSONObject,
    reviewed: Agent3ReplanClient.Preview,
): ReviewedReplanReceiptAuthority {
    val expectedStart = reviewed.window.start
    val expectedOldEnd = reviewed.window.end
    val expectedNewEndLong = expectedStart.toLong() + reviewed.plan.size.toLong()
    if (expectedNewEndLong !in Int.MIN_VALUE.toLong()..Int.MAX_VALUE.toLong()) {
        receiptMismatch("replan.new_end")
    }
    val expectedNewEnd = expectedNewEndLong.toInt()
    val expectedAddedTools = reviewed.plan.map { it.tool }
    val reviewedAddedStepIds = reviewed.plan.mapNotNull { step ->
        step.id?.takeIf { it.isNotBlank() }
    }
    val hasCompleteReviewedAddedStepIds = reviewedAddedStepIds.size == reviewed.plan.size

    val start = raw.requireReceiptInt("start")
    val oldEnd = raw.requireReceiptInt("old_end")
    val newEnd = raw.requireReceiptInt("new_end")
    val removedStepIds = raw.requireReceiptStringArray("removed_step_ids")
    val removedTools = raw.requireReceiptStringArray("removed_tools")
    val addedStepIds = raw.requireReceiptStringArray("added_step_ids")
    val addedTools = raw.requireReceiptStringArray("added_tools")
    val immutablePrefixIds = raw.requireReceiptStringArray("immutable_prefix_ids")
    val immutableTailIds = raw.requireReceiptStringArray("immutable_tail_ids")

    if (start != expectedStart) receiptMismatch("replan.start")
    if (oldEnd != expectedOldEnd) receiptMismatch("replan.old_end")
    if (newEnd != expectedNewEnd) receiptMismatch("replan.new_end")
    if (removedStepIds != reviewed.window.removableStepIds) {
        receiptMismatch("replan.removed_step_ids")
    }
    if (removedTools.size != removedStepIds.size) {
        receiptMismatch("replan.removed_tools")
    }
    if (immutablePrefixIds != reviewed.window.immutablePrefixIds) {
        receiptMismatch("replan.immutable_prefix_ids")
    }
    if (immutableTailIds != reviewed.window.immutableTailIds) {
        receiptMismatch("replan.immutable_tail_ids")
    }
    if (addedStepIds.size != reviewed.plan.size) {
        receiptMismatch("replan.added_step_ids")
    }
    if (hasCompleteReviewedAddedStepIds && addedStepIds != reviewedAddedStepIds) {
        receiptMismatch("replan.added_step_ids")
    }
    if (addedTools != expectedAddedTools) {
        receiptMismatch("replan.added_tools")
    }

    return ReviewedReplanReceiptAuthority(
        start = start,
        oldEnd = oldEnd,
        newEnd = newEnd,
        removedStepIds = removedStepIds,
        removedTools = removedTools,
        addedStepIds = addedStepIds,
        addedTools = addedTools,
        immutablePrefixIds = immutablePrefixIds,
        immutableTailIds = immutableTailIds,
    )
}

/** Prove raw receipt preservation and the exact committed replacement boundary. */
internal fun validateReviewedReplanReceiptBinding(
    authority: ReviewedReplanReceiptAuthority,
    result: Agent3ReplanClient.ApplyResult,
) {
    val receipt = result.replan
    if (
        receipt.start != authority.start ||
        receipt.oldEnd != authority.oldEnd ||
        receipt.newEnd != authority.newEnd ||
        receipt.removedStepIds != authority.removedStepIds ||
        receipt.removedTools != authority.removedTools ||
        receipt.addedStepIds != authority.addedStepIds ||
        receipt.addedTools != authority.addedTools ||
        receipt.immutablePrefixIds != authority.immutablePrefixIds ||
        receipt.immutableTailIds != authority.immutableTailIds
    ) {
        receiptMismatch("replan typed receipt")
    }

    val run = result.run
    if (
        run.currentStep != authority.start ||
        authority.start < 0 ||
        authority.newEnd < authority.start ||
        authority.newEnd > run.steps.size
    ) {
        receiptMismatch("run replacement window")
    }

    val prefixIds = run.steps.subList(0, authority.start).receiptStepIds("run immutable prefix")
    if (prefixIds != authority.immutablePrefixIds) {
        receiptMismatch("run immutable prefix")
    }

    val replacement = run.steps.subList(authority.start, authority.newEnd)
    val replacementIds = replacement.receiptStepIds("run replacement ids")
    val replacementTools = replacement.map { step ->
        step.tool.takeIf { it.isNotBlank() } ?: receiptMismatch("run replacement tools")
    }
    if (
        replacementIds != authority.addedStepIds ||
        replacementTools != authority.addedTools
    ) {
        receiptMismatch("run replacement slice")
    }

    val tailIds = run.steps.subList(authority.newEnd, run.steps.size)
        .receiptStepIds("run immutable tail")
    if (tailIds != authority.immutableTailIds) {
        receiptMismatch("run immutable tail")
    }
}

private fun JSONObject.requireReceiptInt(name: String): Int {
    val raw = if (has(name) && !isNull(name)) opt(name) else null
    return when (raw) {
        is Int -> raw
        is Long -> raw.takeIf { it in Int.MIN_VALUE.toLong()..Int.MAX_VALUE.toLong() }?.toInt()
        else -> null
    } ?: receiptMismatch("replan.$name")
}

private fun JSONObject.requireReceiptStringArray(name: String): List<String> {
    val raw = opt(name) as? JSONArray ?: receiptMismatch("replan.$name")
    return buildList {
        for (index in 0 until raw.length()) {
            val value = raw.opt(index) as? String
            if (value.isNullOrBlank()) receiptMismatch("replan.$name")
            add(value)
        }
    }
}

private fun List<Agent3Client.Step>.receiptStepIds(field: String): List<String> =
    map { step -> step.id?.takeIf { it.isNotBlank() } ?: receiptMismatch(field) }

private fun receiptMismatch(field: String): Nothing =
    throw ModelRigException("Agent 3.0 replan Apply receipt authority mismatch: $field")
