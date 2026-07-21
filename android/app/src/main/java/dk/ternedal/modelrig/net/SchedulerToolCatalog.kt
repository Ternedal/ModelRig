package dk.ternedal.modelrig.net

import org.json.JSONArray
import org.json.JSONObject

/**
 * Typed projection of the worker-owned scheduling contract.
 *
 * Android never infers unattended safety from risk and keeps no local allowlist.
 * Missing or malformed metadata stays visible as a disabled row with a reason.
 */
data class SchedulerToolCatalog(
    val enabled: Boolean,
    val metadataError: String?,
    val tools: List<SchedulerToolInfo>,
)

data class SchedulerToolInfo(
    val name: String,
    val description: String,
    val registryEnabled: Boolean,
    val enabled: Boolean,
    val schedulable: Boolean?,
    val unschedulableReason: String?,
    val metadataError: String?,
) {
    val selectable: Boolean
        get() = metadataError == null && registryEnabled && enabled && schedulable == true

    val disabledReason: String?
        get() = when {
            metadataError != null -> metadataError
            !registryEnabled -> "Værktøjslaget er slået fra på riggen."
            !enabled -> "Værktøjet er slået fra på riggen."
            schedulable != true -> unschedulableReason
                ?: "Riggen har ikke forklaret, hvorfor værktøjet ikke kan planlægges."
            else -> null
        }
}

internal fun parseSchedulerToolCatalog(root: JSONObject): SchedulerToolCatalog {
    val registryValue = root.opt("enabled")
    val registryEnabled = registryValue is Boolean && registryValue
    val registryError = if (registryValue is Boolean) null
    else "Riggen mangler gyldig global tool-status; planlægning er blokeret."

    val rawTools = root.opt("tools")
    if (rawTools !is JSONArray) {
        return SchedulerToolCatalog(
            enabled = false,
            metadataError = "Riggen mangler en gyldig tool-liste; planlægning er blokeret.",
            tools = emptyList(),
        )
    }

    val tools = (0 until rawTools.length()).map { index ->
        val raw = rawTools.opt(index)
        if (raw !is JSONObject) {
            SchedulerToolInfo(
                name = "Ukendt værktøj ${index + 1}",
                description = "",
                registryEnabled = registryEnabled,
                enabled = false,
                schedulable = null,
                unschedulableReason = null,
                metadataError = "Tool-posten er ugyldig og kan ikke planlægges.",
            )
        } else {
            parseSchedulerToolInfo(raw, index, registryEnabled, registryError)
        }
    }

    return SchedulerToolCatalog(registryEnabled, registryError, tools)
}

private fun parseSchedulerToolInfo(
    raw: JSONObject,
    index: Int,
    registryEnabled: Boolean,
    registryError: String?,
): SchedulerToolInfo {
    val rawName = raw.optString("name").trim()
    val name = rawName.ifBlank { "Ukendt værktøj ${index + 1}" }
    val enabledValue = raw.opt("enabled")
    val schedulableValue = raw.opt("schedulable")
    val schedulable = schedulableValue as? Boolean
    val reason = raw.optString("unschedulable_reason")
        .trim()
        .takeIf { it.isNotEmpty() && it != "null" }

    val localError = when {
        rawName.isBlank() -> "Tool-posten mangler et navn; den kan ikke planlægges."
        enabledValue !is Boolean -> "Riggen mangler gyldig enabled-metadata for $name."
        schedulableValue !is Boolean -> "Riggen mangler schedulable-metadata for $name."
        schedulable == false && reason == null ->
            "Riggen mangler en forklaring på, hvorfor $name ikke kan planlægges."
        else -> null
    }

    return SchedulerToolInfo(
        name = name,
        description = raw.optString("description").trim(),
        registryEnabled = registryEnabled,
        enabled = enabledValue == true,
        schedulable = schedulable,
        unschedulableReason = reason,
        metadataError = registryError ?: localError,
    )
}
