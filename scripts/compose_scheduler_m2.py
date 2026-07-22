#!/usr/bin/env python3
"""Temporary exact patcher for composing T-016 into the T-017 Android screen."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCREEN = ROOT / "android/app/src/main/java/dk/ternedal/modelrig/ui/ScheduleScreen.kt"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


text = SCREEN.read_text(encoding="utf-8")

text = replace_once(
    text,
    '''import dk.ternedal.modelrig.net.ModelRigClient
import dk.ternedal.modelrig.net.ScheduleClient
import dk.ternedal.modelrig.net.ScheduleItem
import dk.ternedal.modelrig.net.SchedulePreview
import dk.ternedal.modelrig.net.ScheduleRuntimeStatus
import dk.ternedal.modelrig.net.ToolInfo
''',
    '''import dk.ternedal.modelrig.net.ScheduleClient
import dk.ternedal.modelrig.net.ScheduleItem
import dk.ternedal.modelrig.net.SchedulePreview
import dk.ternedal.modelrig.net.ScheduleRuntimeStatus
import dk.ternedal.modelrig.net.SchedulerToolCatalogLoader
import dk.ternedal.modelrig.net.SchedulerToolInfo
''',
    "imports",
)
text = replace_once(
    text,
    '    var tools by remember { mutableStateOf<List<ToolInfo>>(emptyList()) }\n',
    '    var tools by remember { mutableStateOf<List<SchedulerToolInfo>>(emptyList()) }\n',
    "tool type",
)
text = replace_once(
    text,
    '    var tool by remember { mutableStateOf("current_datetime") }\n',
    '    var tool by remember { mutableStateOf("") }\n',
    "tool default",
)
text = replace_once(
    text,
    '''    fun client(): ScheduleClient {
        val base = store.baseUrl?.takeIf { it.isNotBlank() }
            ?: error("Ingen rig-URL er gemt")
        val token = store.token?.takeIf { it.isNotBlank() }
            ?: error("Ingen device-token er gemt")
        return ScheduleClient(base, token)
    }
''',
    '''    fun connection(): Pair<String, String> {
        val base = store.baseUrl?.takeIf { it.isNotBlank() }
            ?: error("Ingen rig-URL er gemt")
        val token = store.token?.takeIf { it.isNotBlank() }
            ?: error("Ingen device-token er gemt")
        return base to token
    }

    fun client(): ScheduleClient {
        val (base, token) = connection()
        return ScheduleClient(base, token)
    }
''',
    "connection helper",
)
text = replace_once(
    text,
    '''    fun load() {
        execute(
            action = {
                val api = client()
                Triple(
                    api.status(),
                    api.list(),
                    ModelRigClient(store.baseUrl ?: "", store.token).toolsList().tools,
                )
            },
            success = {
                runtime = it.first
                schedules = it.second
                tools = it.third.filter { info -> info.risk == "read" || info.risk == "write" }
                if (tools.none { info -> info.name == tool }) {
                    tool = tools.firstOrNull()?.name ?: tool
                }
                notice = "${schedules.size} planer hentet. Ingen handling er kørt."
            },
            fallback = "Planer kunne ikke hentes",
        )
    }
''',
    '''    fun load() {
        execute(
            action = {
                val (base, token) = connection()
                val api = ScheduleClient(base, token)
                Triple(
                    api.status(),
                    api.list(),
                    SchedulerToolCatalogLoader(base, token).load(),
                )
            },
            success = {
                runtime = it.first
                schedules = it.second
                val catalog = it.third
                tools = catalog.tools

                val currentStillValid = tools.any { info -> info.name == tool && info.selectable }
                if (!currentStillValid) {
                    tool = tools.firstOrNull { info -> info.selectable }?.name.orEmpty()
                    preview = null
                }

                when {
                    catalog.metadataError != null -> error = catalog.metadataError
                    !catalog.enabled -> error = "Værktøjslaget er slået fra på riggen; ingen ny plan kan oprettes."
                    tools.none { info -> info.selectable } ->
                        error = "Riggen rapporterer ingen aktiverede, planlægbare værktøjer."
                    else -> notice =
                        "${schedules.size} planer hentet · ${tools.count { info -> info.selectable }} værktøjer kan planlægges."
                }
            },
            fallback = "Planer kunne ikke hentes",
        )
    }
''',
    "load catalog",
)
text = replace_once(
    text,
    '''    fun previewCreate() {
        val ttl = ttlDays.toIntOrNull()
''',
    '''    fun previewCreate() {
        val selectedTool = tools.firstOrNull { info -> info.name == tool }
        if (selectedTool?.selectable != true) {
            preview = null
            error = selectedTool?.disabledReason ?: "Vælg et aktiveret, planlægbart værktøj fra listen."
            return
        }
        val ttl = ttlDays.toIntOrNull()
''',
    "preview policy",
)
text = replace_once(
    text,
    '''                client().preview(
                    tool = tool.trim(),
                    args = args,
                    cadence = cadence.trim(),
                    ttlDays = ttl,
                    maxRuns = runs,
                    timezone = timezone.trim(),
                    misfirePolicy = ScheduleClient.RUN_ONCE_MISFIRE_POLICY,
                )
''',
    '''                client().preview(
                    tool = selectedTool.name,
                    args = args,
                    cadence = cadence.trim(),
                    ttlDays = ttl,
                    maxRuns = runs,
                    timezone = timezone.trim(),
                    misfirePolicy = ScheduleClient.RUN_ONCE_MISFIRE_POLICY,
                )
''',
    "preview selected tool",
)
text = replace_once(
    text,
    '''                Text("Opret plan", fontWeight = FontWeight.SemiBold, color = KalivTheme.colors.textHigh)
                Text(
                    "Du skal først previewe handling, kadence, timezone, udløb og budget.",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 11.sp,
                )
                Spacer(Modifier.height(8.dp))
                if (tools.isNotEmpty()) {
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
                )
''',
    '''                Text("Opret plan", fontWeight = FontWeight.SemiBold, color = KalivTheme.colors.textHigh)
                Text(
                    "Vælg kun et værktøj, som riggens autoritative kontrakt tillader uden opsyn; preview binder også timezone, misfire, udløb og budget.",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 11.sp,
                )
                Spacer(Modifier.height(8.dp))
                if (tools.isEmpty()) {
                    Text("Ingen tool-metadata modtaget fra riggen.", color = KalivTheme.colors.danger, fontSize = 11.sp)
                } else {
                    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
                        tools.forEach { info ->
                            FilterChip(
                                selected = tool == info.name,
                                enabled = !busy && info.selectable,
                                onClick = { tool = info.name; clearCreatePreview() },
                                label = { Text(info.name, fontSize = 11.sp) },
                                modifier = Modifier.padding(end = 6.dp),
                            )
                        }
                    }
                    tools.filterNot { info -> info.selectable }.forEach { info ->
                        Text(
                            "${info.name}: ${info.disabledReason ?: "kan ikke planlægges"}",
                            color = KalivTheme.colors.danger,
                            fontSize = 11.sp,
                            modifier = Modifier.padding(top = 3.dp),
                        )
                    }
                }
                val selectedTool = tools.firstOrNull { info -> info.name == tool }
                OutlinedTextField(
                    value = tool.ifBlank { "Intet planlægbart værktøj" },
                    onValueChange = {},
                    readOnly = true,
                    label = { Text("Tool fra riggens kontrakt") },
                    supportingText = {
                        Text(
                            selectedTool?.description?.takeIf { it.isNotBlank() }
                                ?: "Vælg et aktiveret tool ovenfor; fri tekst er bevidst slået fra.",
                        )
                    },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
''',
    "picker UI",
)
text = replace_once(
    text,
    '                    enabled = !busy && tool.isNotBlank() && cadence.isNotBlank() && timezone.isNotBlank() && ttlDays.isNotBlank() && maxRuns.isNotBlank(),\n',
    '                    enabled = !busy && selectedTool?.selectable == true && cadence.isNotBlank() && timezone.isNotBlank() && ttlDays.isNotBlank() && maxRuns.isNotBlank(),\n',
    "preview button",
)

SCREEN.write_text(text, encoding="utf-8")
print("Scheduler M2 Android composition applied")
