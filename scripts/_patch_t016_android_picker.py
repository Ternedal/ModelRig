#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one patch target, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_once(
    "android/app/src/main/java/dk/ternedal/modelrig/net/ModelRigClient.kt",
    '''            ToolInfo(
                name = t.optString("name"),
                risk = t.optString("risk"),
                description = t.optString("description"),
                enabled = t.optBoolean("enabled"),
            )''',
    '''            ToolInfo(
                name = t.optString("name"),
                risk = t.optString("risk"),
                description = t.optString("description"),
                enabled = t.optBoolean("enabled", false),
                impact = t.optString("impact").takeUnless { it.isBlank() || it == "null" },
                schedulable = t.optBoolean("schedulable", false),
                unschedulableReason = t.optString("unschedulable_reason")
                    .takeUnless { it.isBlank() || it == "null" },
                cancellation = t.optString("cancellation")
                    .takeUnless { it.isBlank() || it == "null" },
                idempotent = if (t.has("idempotent") && !t.isNull("idempotent")) {
                    t.getBoolean("idempotent")
                } else {
                    null
                },
            )''',
)

replace_once(
    "android/app/src/main/java/dk/ternedal/modelrig/net/ModelRigClient.kt",
    '''data class ToolInfo(
    val name: String,
    val risk: String,
    val description: String,
    val enabled: Boolean,
)''',
    '''data class ToolInfo(
    val name: String,
    val risk: String,
    val description: String,
    val enabled: Boolean,
    val impact: String? = null,
    val schedulable: Boolean = false,
    val unschedulableReason: String? = null,
    val cancellation: String? = null,
    val idempotent: Boolean? = null,
) {
    /**
     * The scheduler picker fails closed. Only an explicit backend declaration
     * may make a tool selectable; a missing field is not permission.
     */
    val scheduleBlockReason: String?
        get() = when {
            !schedulable -> unschedulableReason
                ?.takeIf { it.isNotBlank() }
                ?: "Riggen har ikke markeret værktøjet som planlægbart."
            !enabled -> "Værktøjet er slået fra på riggen."
            else -> null
        }

    val canSchedule: Boolean
        get() = scheduleBlockReason == null
}''',
)

replace_once(
    "android/app/src/main/java/dk/ternedal/modelrig/ui/ScheduleScreen.kt",
    '''    var tools by remember { mutableStateOf<List<ToolInfo>>(emptyList()) }
    var busy by remember { mutableStateOf(false) }''',
    '''    var tools by remember { mutableStateOf<List<ToolInfo>>(emptyList()) }
    var toolsLoaded by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }''',
)

replace_once(
    "android/app/src/main/java/dk/ternedal/modelrig/ui/ScheduleScreen.kt",
    '''                tools = it.third.filter { info -> info.risk == "read" || info.risk == "write" }
                if (tools.none { info -> info.name == tool }) {
                    tool = tools.firstOrNull()?.name ?: tool
                }''',
    '''                tools = it.third
                toolsLoaded = true
                if (tools.none { info -> info.name == tool && info.canSchedule }) {
                    tool = scheduleToolOptions(tools).selectable.firstOrNull()?.name.orEmpty()
                }''',
)

replace_once(
    "android/app/src/main/java/dk/ternedal/modelrig/ui/ScheduleScreen.kt",
    '''    fun previewCreate() {
        val ttl = ttlDays.toIntOrNull()''',
    '''    fun previewCreate() {
        val selected = tools.firstOrNull { it.name == tool }
        val blocked = selected?.scheduleBlockReason
        if (selected == null || blocked != null) {
            error = blocked ?: "Vælg et værktøj, som riggen har markeret som planlægbart."
            return
        }
        val ttl = ttlDays.toIntOrNull()''',
)

replace_once(
    "android/app/src/main/java/dk/ternedal/modelrig/ui/ScheduleScreen.kt",
    '''                if (tools.isNotEmpty()) {
                    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
                        tools.forEach { info ->
                            FilterChip(
                                selected = tool == info.name,
                                onClick = { tool = info.name; clearCreatePreview() },
                                label = { Text(info.name, fontSize = 11.sp) },
                                modifier = Modifier.padding(end = 6.dp),
                            )
                        }
                    }
                }
                OutlinedTextField(
                    value = tool,
                    onValueChange = { tool = it; clearCreatePreview() },
                    label = { Text("Tool") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )''',
    '''                val toolOptions = scheduleToolOptions(tools)
                when {
                    !toolsLoaded -> Text("Henter værktøjer…", color = KalivTheme.colors.textMuted)
                    toolOptions.selectable.isEmpty() -> Text(
                        "Ingen værktøjer er både slået til og godkendt til kørsel uden opsyn.",
                        color = KalivTheme.colors.danger,
                        fontSize = 11.sp,
                    )
                    else -> {
                        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
                            toolOptions.selectable.forEach { info ->
                                FilterChip(
                                    selected = tool == info.name,
                                    onClick = { tool = info.name; clearCreatePreview() },
                                    label = { Text(info.name, fontSize = 11.sp) },
                                    modifier = Modifier.padding(end = 6.dp),
                                )
                            }
                        }
                        tools.firstOrNull { it.name == tool }?.let { selected ->
                            Spacer(Modifier.height(6.dp))
                            Text(selected.description, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                        }
                    }
                }
                if (toolOptions.blocked.isNotEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "Ikke tilgængelige for planer",
                        color = KalivTheme.colors.textHigh,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
                    toolOptions.blocked.forEach { info ->
                        Text(
                            "${info.name}: ${info.scheduleBlockReason}",
                            color = KalivTheme.colors.textMuted,
                            fontSize = 10.sp,
                        )
                    }
                }
                OutlinedTextField(
                    value = tool,
                    onValueChange = {},
                    readOnly = true,
                    enabled = tool.isNotBlank(),
                    label = { Text("Valgt tool") },
                    supportingText = { Text("Valget kommer direkte fra riggens ToolInfo-kontrakt.") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )''',
)

replace_once(
    "android/app/src/main/java/dk/ternedal/modelrig/ui/ScheduleScreen.kt",
    '''                    enabled = !busy && tool.isNotBlank() && cadence.isNotBlank() && ttlDays.isNotBlank() && maxRuns.isNotBlank(),''',
    '''                    enabled = !busy && tools.any { it.name == tool && it.canSchedule } && cadence.isNotBlank() && ttlDays.isNotBlank() && maxRuns.isNotBlank(),''',
)

Path("android/app/src/main/java/dk/ternedal/modelrig/ui/ScheduleToolPolicy.kt").write_text(
    '''package dk.ternedal.modelrig.ui

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
''',
    encoding="utf-8",
)

Path("android/app/src/test/java/dk/ternedal/modelrig/net/ToolRegistryContractTest.kt").write_text(
    '''package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ToolRegistryContractTest {
    @Test
    fun registryParsesSchedulerAxesAndMissingMetadataFailsClosed() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .addHeader("Content-Type", "application/json")
                .setBody(
                    """{
                      "enabled": true,
                      "tools": [
                        {
                          "name": "current_datetime",
                          "risk": "read",
                          "description": "clock",
                          "enabled": true,
                          "impact": "read",
                          "schedulable": true,
                          "unschedulable_reason": "",
                          "cancellation": "none",
                          "idempotent": true
                        },
                        {
                          "name": "delete_model",
                          "risk": "write",
                          "description": "delete",
                          "enabled": true,
                          "impact": "destructive",
                          "schedulable": false,
                          "unschedulable_reason": "destruktive handlinger kræver et menneske",
                          "cancellation": "none",
                          "idempotent": false
                        },
                        {
                          "name": "legacy_tool",
                          "risk": "read",
                          "description": "old response",
                          "enabled": true
                        },
                        {
                          "name": "disabled_read",
                          "risk": "read",
                          "description": "disabled",
                          "enabled": false,
                          "schedulable": true
                        }
                      ]
                    }""".trimIndent(),
                ),
        )
        server.start()
        try {
            val registry = ModelRigClient(server.url("/").toString(), "device-token").toolsList()
            val tools = registry.tools.associateBy { it.name }

            val current = tools.getValue("current_datetime")
            assertTrue(current.schedulable)
            assertTrue(current.canSchedule)
            assertNull(current.scheduleBlockReason)
            assertEquals("read", current.impact)
            assertEquals("none", current.cancellation)
            assertEquals(true, current.idempotent)

            val destructive = tools.getValue("delete_model")
            assertFalse(destructive.canSchedule)
            assertEquals(
                "destruktive handlinger kræver et menneske",
                destructive.scheduleBlockReason,
            )

            val legacy = tools.getValue("legacy_tool")
            assertFalse(legacy.schedulable)
            assertFalse(legacy.canSchedule)
            assertEquals(
                "Riggen har ikke markeret værktøjet som planlægbart.",
                legacy.scheduleBlockReason,
            )
            assertNull(legacy.idempotent)

            val disabled = tools.getValue("disabled_read")
            assertFalse(disabled.canSchedule)
            assertEquals("Værktøjet er slået fra på riggen.", disabled.scheduleBlockReason)

            val request = server.takeRequest()
            assertEquals("/api/v1/tools", request.path)
            assertEquals("Bearer device-token", request.getHeader("Authorization"))
        } finally {
            server.shutdown()
        }
    }
}
''',
    encoding="utf-8",
)

Path("android/app/src/test/java/dk/ternedal/modelrig/ui/ScheduleToolPolicyTest.kt").parent.mkdir(
    parents=True,
    exist_ok=True,
)
Path("android/app/src/test/java/dk/ternedal/modelrig/ui/ScheduleToolPolicyTest.kt").write_text(
    '''package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.ToolInfo
import org.junit.Assert.assertEquals
import org.junit.Test

class ScheduleToolPolicyTest {
    @Test
    fun pickerOnlySelectsExplicitlySchedulableEnabledTools() {
        val options = scheduleToolOptions(
            listOf(
                tool("clock", schedulable = true, enabled = true),
                tool("delete", schedulable = false, enabled = true, reason = "destructive"),
                tool("disabled", schedulable = true, enabled = false),
                tool("missing-contract", enabled = true),
                tool("clock", schedulable = true, enabled = true),
                tool("", schedulable = true, enabled = true),
            ),
        )

        assertEquals(listOf("clock"), options.selectable.map { it.name })
        assertEquals(
            listOf("delete", "disabled", "missing-contract"),
            options.blocked.map { it.name },
        )
        assertEquals("destructive", options.blocked[0].scheduleBlockReason)
        assertEquals("Værktøjet er slået fra på riggen.", options.blocked[1].scheduleBlockReason)
        assertEquals(
            "Riggen har ikke markeret værktøjet som planlægbart.",
            options.blocked[2].scheduleBlockReason,
        )
    }

    private fun tool(
        name: String,
        schedulable: Boolean = false,
        enabled: Boolean,
        reason: String? = null,
    ) = ToolInfo(
        name = name,
        risk = "read",
        description = name,
        enabled = enabled,
        schedulable = schedulable,
        unschedulableReason = reason,
    )
}
''',
    encoding="utf-8",
)
