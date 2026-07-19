package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.ToolInfo

internal data class ScheduleToolOptions(
    val selectable: List<ToolInfo>,
    val blocked: List<ToolInfo>,
)

/**
 * Derive the picker entirely from the backend-owned ToolInfo contract.
 * Unknown or duplicate entries never become a second local permission list.
 */
internal fun scheduleToolOptions(tools: List<ToolInfo>): ScheduleToolOptions {
    val unique = tools
        .filter { it.name.isNotBlank() }
        .distinctBy { it.name }
    return ScheduleToolOptions(
        selectable = unique.filter { it.canSchedule },
        blocked = unique.filterNot { it.canSchedule },
    )
}
