package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.ToolInfo

internal data class ScheduleToolOptions(
    val selectable: List<ToolInfo>,
    val blocked: List<ToolInfo>,
)

/**
 * Derive the picker entirely from the backend-owned ToolInfo contract.
 * Blank names are discarded. A duplicate name is an ambiguous response, so no
 * entry with that name becomes selectable; the client never chooses which copy
 * to trust.
 */
internal fun scheduleToolOptions(tools: List<ToolInfo>): ScheduleToolOptions {
    val unique = tools
        .filter { it.name.isNotBlank() }
        .groupBy { it.name }
        .values
        .filter { entries -> entries.size == 1 }
        .map { entries -> entries.single() }
    return ScheduleToolOptions(
        selectable = unique.filter { it.canSchedule },
        blocked = unique.filterNot { it.canSchedule },
    )
}
