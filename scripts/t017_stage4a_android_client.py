#!/usr/bin/env python3
"""Apply only T-017 Android ScheduleClient/model time fields.

Temporary transport. Compose UI remains unchanged until stage 4B.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected one match, found {count}: {old[:220]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


CLIENT = "android/app/src/main/java/dk/ternedal/modelrig/net/ScheduleClient.kt"
replace_once(
    CLIENT,
    '''class ScheduleClient(baseUrl: String, private val token: String) {\n    private val base = baseUrl.trimEnd('/')\n''',
    '''class ScheduleClient(baseUrl: String, private val token: String) {\n    companion object {\n        const val DEFAULT_TIMEZONE = "Europe/Copenhagen"\n        const val RUN_ONCE_MISFIRE_POLICY = "run_once"\n    }\n\n    private val base = baseUrl.trimEnd('/')\n''',
)
replace_once(
    CLIENT,
    '''        cadence: String,\n        ttlDays: Int,\n        maxRuns: Int,\n    ): SchedulePreview {\n''',
    '''        cadence: String,\n        ttlDays: Int,\n        maxRuns: Int,\n        timezone: String = DEFAULT_TIMEZONE,\n        misfirePolicy: String = RUN_ONCE_MISFIRE_POLICY,\n    ): SchedulePreview {\n''',
)
replace_once(
    CLIENT,
    '''            .put("cadence", cadence)\n            .put("ttl_days", ttlDays)\n''',
    '''            .put("cadence", cadence)\n            .put("timezone", timezone)\n            .put("misfire_policy", misfirePolicy)\n            .put("ttl_days", ttlDays)\n''',
)
replace_once(
    CLIENT,
    '''            .put("cadence", preview.cadence)\n            .put("ttl_days", preview.ttlDays)\n            .put("max_runs", preview.maxRuns)\n        approvalTokenForCreate(preview)?.let { body.put("approval_token", it) }\n''',
    '''            .put("cadence", preview.cadence)\n            .put("timezone", preview.timezone)\n            .put("misfire_policy", preview.misfirePolicy)\n            .put("ttl_days", preview.ttlDays)\n            .put("max_runs", preview.maxRuns)\n        approvalTokenForCreate(preview)?.let { body.put("approval_token", it) }\n''',
)
replace_once(
    CLIENT,
    '''            .put("cadence", preview.cadence)\n            .put("ttl_days", preview.ttlDays)\n            .put("max_runs", preview.maxRuns)\n            .put("preview_fingerprint", fingerprint)\n''',
    '''            .put("cadence", preview.cadence)\n            .put("timezone", preview.timezone)\n            .put("misfire_policy", preview.misfirePolicy)\n            .put("ttl_days", preview.ttlDays)\n            .put("max_runs", preview.maxRuns)\n            .put("preview_fingerprint", fingerprint)\n''',
)
replace_once(
    CLIENT,
    '''    private fun parsePreview(o: JSONObject) = SchedulePreview(\n        operation = o.optString("operation", "create"),\n        scheduleId = o.optString("schedule_id").takeUnless { it.isBlank() || it == "null" },\n        tool = o.getString("tool"),\n        argsJson = o.optJSONObject("args")?.toString() ?: "{}",\n        cadence = o.getString("cadence"),\n        risk = o.optString("risk"),\n''',
    '''    private fun parsePreview(o: JSONObject) = SchedulePreview(\n        operation = o.optString("operation", "create"),\n        scheduleId = o.optString("schedule_id").takeUnless { it.isBlank() || it == "null" },\n        tool = o.getString("tool"),\n        argsJson = o.optJSONObject("args")?.toString() ?: "{}",\n        cadence = o.getString("cadence"),\n        timezone = o.getString("timezone"),\n        misfirePolicy = o.getString("misfire_policy"),\n        dueAtLocal = o.getString("due_at_local"),\n        risk = o.optString("risk"),\n''',
)
replace_once(
    CLIENT,
    '''    private fun parseItem(o: JSONObject) = ScheduleItem(\n        id = o.getString("schedule_id"),\n        tool = o.getString("tool"),\n        argsJson = o.optJSONObject("args")?.toString() ?: "{}",\n        cadence = o.getString("cadence"),\n        risk = o.optString("risk"),\n''',
    '''    private fun parseItem(o: JSONObject) = ScheduleItem(\n        id = o.getString("schedule_id"),\n        tool = o.getString("tool"),\n        argsJson = o.optJSONObject("args")?.toString() ?: "{}",\n        cadence = o.getString("cadence"),\n        timezone = o.getString("timezone"),\n        misfirePolicy = o.getString("misfire_policy"),\n        dueAtLocal = o.getString("due_at_local"),\n        risk = o.optString("risk"),\n''',
)
replace_once(
    CLIENT,
    '''data class SchedulePreview(\n    val operation: String,\n    val scheduleId: String?,\n    val tool: String,\n    val argsJson: String,\n    val cadence: String,\n    val risk: String,\n''',
    '''data class SchedulePreview(\n    val operation: String,\n    val scheduleId: String?,\n    val tool: String,\n    val argsJson: String,\n    val cadence: String,\n    val timezone: String,\n    val misfirePolicy: String,\n    val dueAtLocal: String,\n    val risk: String,\n''',
)
replace_once(
    CLIENT,
    '''data class ScheduleItem(\n    val id: String,\n    val tool: String,\n    val argsJson: String,\n    val cadence: String,\n    val risk: String,\n''',
    '''data class ScheduleItem(\n    val id: String,\n    val tool: String,\n    val argsJson: String,\n    val cadence: String,\n    val timezone: String,\n    val misfirePolicy: String,\n    val dueAtLocal: String,\n    val risk: String,\n''',
)

TEST = "android/app/src/test/java/dk/ternedal/modelrig/net/ScheduleClientTest.kt"
replace_once(
    TEST,
    '''                cadence = "daily:08:00",\n                ttlDays = 30,\n                maxRuns = 5,\n            )\n            assertEquals(fingerprint, preview.approvalFingerprint)\n''',
    '''                cadence = "daily:08:00",\n                ttlDays = 30,\n                maxRuns = 5,\n                timezone = "America/New_York",\n                misfirePolicy = "run_once",\n            )\n            assertEquals(fingerprint, preview.approvalFingerprint)\n            assertEquals("America/New_York", preview.timezone)\n            assertEquals("run_once", preview.misfirePolicy)\n            assertEquals("2027-01-15T08:00:00-05:00", preview.dueAtLocal)\n''',
)
replace_once(
    TEST,
    '''            assertFalse(previewBody.has("approved_fingerprint"))\n            assertFalse(previewBody.has("approval_token"))\n''',
    '''            assertFalse(previewBody.has("approved_fingerprint"))\n            assertFalse(previewBody.has("approval_token"))\n            assertEquals("America/New_York", previewBody.getString("timezone"))\n            assertEquals("run_once", previewBody.getString("misfire_policy"))\n''',
)
replace_once(
    TEST,
    '''            assertEquals(fingerprint, approvalBody.getString("preview_fingerprint"))\n            assertEquals("Husk brygdag", approvalBody.getJSONObject("args").getString("text"))\n''',
    '''            assertEquals(fingerprint, approvalBody.getString("preview_fingerprint"))\n            assertEquals("Husk brygdag", approvalBody.getJSONObject("args").getString("text"))\n            assertEquals("America/New_York", approvalBody.getString("timezone"))\n            assertEquals("run_once", approvalBody.getString("misfire_policy"))\n''',
)
replace_once(
    TEST,
    '''            assertEquals(token, createBody.getString("approval_token"))\n            assertFalse(createBody.has("approved_fingerprint"))\n            assertEquals("Husk brygdag", createBody.getJSONObject("args").getString("text"))\n''',
    '''            assertEquals(token, createBody.getString("approval_token"))\n            assertFalse(createBody.has("approved_fingerprint"))\n            assertEquals("Husk brygdag", createBody.getJSONObject("args").getString("text"))\n            assertEquals("America/New_York", createBody.getString("timezone"))\n            assertEquals("run_once", createBody.getString("misfire_policy"))\n            assertEquals("2027-01-15T08:00:00-05:00", created.dueAtLocal)\n''',
)
replace_once(
    TEST,
    '''                cadence = "daily:08:00",\n                risk = "write",\n''',
    '''                cadence = "daily:08:00",\n                timezone = "Europe/Copenhagen",\n                misfirePolicy = "run_once",\n                dueAtLocal = "2027-01-15T08:00:00+01:00",\n                risk = "write",\n''',
)
replace_once(
    TEST,
    '''        requiresApproval: Boolean = true,\n        tool: String = "note_append",\n    ): String {\n''',
    '''        requiresApproval: Boolean = true,\n        tool: String = "note_append",\n        timezone: String = "America/New_York",\n        dueAtLocal: String = "2027-01-15T08:00:00-05:00",\n    ): String {\n''',
)
replace_once(
    TEST,
    '''            .put("cadence", if (tool == "note_append") "daily:08:00" else "every:60")\n            .put("risk", if (requiresApproval) "write" else "read")\n''',
    '''            .put("cadence", if (tool == "note_append") "daily:08:00" else "every:60")\n            .put("timezone", timezone)\n            .put("misfire_policy", "run_once")\n            .put("due_at_local", dueAtLocal)\n            .put("risk", if (requiresApproval) "write" else "read")\n''',
)
replace_once(
    TEST,
    '''            .put("cadence", if (tool == "note_append") "daily:08:00" else "every:60")\n            .put("risk", if (tool == "note_append") "write" else "read")\n''',
    '''            .put("cadence", if (tool == "note_append") "daily:08:00" else "every:60")\n            .put("timezone", "America/New_York")\n            .put("misfire_policy", "run_once")\n            .put("due_at_local", "2027-01-15T08:00:00-05:00")\n            .put("risk", if (tool == "note_append") "write" else "read")\n''',
)

print("T-017 stage 4A Android client applied")
