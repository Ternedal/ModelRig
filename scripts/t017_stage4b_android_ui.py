#!/usr/bin/env python3
"""Apply only T-017 Android scheduler time presentation.

Temporary transport. This stage changes no backend, worker or scheduler runtime.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "android/app/src/main/java/dk/ternedal/modelrig/ui/ScheduleScreen.kt"


def replace_once(old: str, new: str) -> None:
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"ScheduleScreen.kt: expected one match, found {count}: {old[:220]!r}")
    TARGET.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    '''    var cadence by remember { mutableStateOf("daily:08:00") }\n    var ttlDays by remember { mutableStateOf("90") }\n''',
    '''    var cadence by remember { mutableStateOf("daily:08:00") }\n    var timezone by remember { mutableStateOf(ScheduleClient.DEFAULT_TIMEZONE) }\n    var ttlDays by remember { mutableStateOf("90") }\n''',
)

replace_once(
    '''            action = { client().preview(tool.trim(), args, cadence.trim(), ttl, runs) },\n''',
    '''            action = {\n                client().preview(\n                    tool = tool.trim(),\n                    args = args,\n                    cadence = cadence.trim(),\n                    ttlDays = ttl,\n                    maxRuns = runs,\n                    timezone = timezone.trim(),\n                    misfirePolicy = ScheduleClient.RUN_ONCE_MISFIRE_POLICY,\n                )\n            },\n''',
)

replace_once(
    '''                    "Du skal først previewe den præcise handling, kadence, udløb og budget.",\n''',
    '''                    "Du skal først previewe handling, kadence, timezone, udløb og budget.",\n''',
)

replace_once(
    '''                OutlinedTextField(\n                    value = cadence,\n                    onValueChange = { cadence = it; clearCreatePreview() },\n                    label = { Text("Kadence") },\n                    supportingText = { Text("every:3600 eller daily:08:00") },\n                    singleLine = true,\n                    modifier = Modifier.fillMaxWidth(),\n                )\n                Spacer(Modifier.height(7.dp))\n                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {\n''',
    '''                OutlinedTextField(\n                    value = cadence,\n                    onValueChange = { cadence = it; clearCreatePreview() },\n                    label = { Text("Kadence") },\n                    supportingText = { Text("every:3600 eller daily:08:00") },\n                    singleLine = true,\n                    modifier = Modifier.fillMaxWidth(),\n                )\n                Spacer(Modifier.height(7.dp))\n                OutlinedTextField(\n                    value = timezone,\n                    onValueChange = { timezone = it; clearCreatePreview() },\n                    label = { Text("Timezone") },\n                    supportingText = {\n                        Text("IANA-zone, fx Europe/Copenhagen. Misfire: kør én gang; ældre forfald registreres som missed.")\n                    },\n                    singleLine = true,\n                    modifier = Modifier.fillMaxWidth(),\n                )\n                Spacer(Modifier.height(7.dp))\n                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {\n''',
)

replace_once(
    '''                    enabled = !busy && tool.isNotBlank() && cadence.isNotBlank() && ttlDays.isNotBlank() && maxRuns.isNotBlank(),\n''',
    '''                    enabled = !busy && tool.isNotBlank() && cadence.isNotBlank() && timezone.isNotBlank() && ttlDays.isNotBlank() && maxRuns.isNotBlank(),\n''',
)

replace_once(
    '''        Text("Kadence: ${schedule.cadence}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)\n        Text("Næste: ${formatEpoch(schedule.dueAt)}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)\n        Text("Udløb: ${formatEpoch(schedule.expiresAt)}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)\n''',
    '''        Text("Kadence: ${schedule.cadence}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)\n        Text("Timezone: ${schedule.timezone}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)\n        Text("Misfire: ${scheduleMisfireLabel(schedule.misfirePolicy)}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)\n        Text("Næste: ${authoritativeScheduleTime(schedule.dueAtLocal, schedule.timezone)}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)\n        Text("Udløb: ${formatEpoch(schedule.expiresAt)}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)\n''',
)

replace_once(
    '''        ApprovalLine("Kadence", preview.cadence)\n        ApprovalLine("Risiko", preview.risk)\n        ApprovalLine("Følsomhed", preview.sensitivity)\n        ApprovalLine("Første/næste kørsel", formatEpoch(preview.dueAt))\n''',
    '''        ApprovalLine("Kadence", preview.cadence)\n        ApprovalLine("Timezone", preview.timezone)\n        ApprovalLine("Misfire", scheduleMisfireLabel(preview.misfirePolicy))\n        ApprovalLine("Risiko", preview.risk)\n        ApprovalLine("Følsomhed", preview.sensitivity)\n        ApprovalLine("Første/næste kørsel", authoritativeScheduleTime(preview.dueAtLocal, preview.timezone))\n''',
)

replace_once(
    '''private fun formatEpoch(seconds: Double): String {\n''',
    '''internal fun authoritativeScheduleTime(dueAtLocal: String, timezone: String): String {\n    val local = dueAtLocal.trim()\n    val zone = timezone.trim()\n    return when {\n        local.isNotEmpty() && zone.isNotEmpty() -> "$local · $zone"\n        local.isNotEmpty() -> local\n        zone.isNotEmpty() -> "ukendt · $zone"\n        else -> "ukendt"\n    }\n}\n\ninternal fun scheduleMisfireLabel(policy: String): String = when (policy) {\n    ScheduleClient.RUN_ONCE_MISFIRE_POLICY -> "Kør én gang; ældre forfald registreres som missed"\n    else -> policy.ifBlank { "ukendt" }\n}\n\nprivate fun formatEpoch(seconds: Double): String {\n''',
)

print("T-017 stage 4B Android time UI applied")
