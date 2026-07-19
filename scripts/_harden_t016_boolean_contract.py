#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one target, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_once(
    "android/app/src/main/java/dk/ternedal/modelrig/net/ModelRigClient.kt",
    '''                enabled = t.optBoolean("enabled", false),
                impact = t.optString("impact").takeUnless { it.isBlank() || it == "null" },
                schedulable = t.optBoolean("schedulable", false),''',
    '''                // These contract fields are type-strict. Only an actual
                // JSON boolean is accepted; strings and numbers use the default.
                enabled = t.opt("enabled") == true,
                impact = t.optString("impact").takeUnless { it.isBlank() || it == "null" },
                schedulable = t.opt("schedulable") == true,''',
)
replace_once(
    "android/app/src/main/java/dk/ternedal/modelrig/net/ModelRigClient.kt",
    '''                idempotent = if (t.has("idempotent") && !t.isNull("idempotent")) {
                    t.getBoolean("idempotent")
                } else {
                    null
                },''',
    '''                idempotent = t.opt("idempotent") as? Boolean,''',
)

path = "android/app/src/test/java/dk/ternedal/modelrig/net/ToolRegistryContractTest.kt"
replace_once(
    path,
    '''                        {
                          "name": "disabled_read",
                          "risk": "read",
                          "description": "disabled",
                          "enabled": false,
                          "schedulable": true
                        }
                      ]''',
    '''                        {
                          "name": "disabled_read",
                          "risk": "read",
                          "description": "disabled",
                          "enabled": false,
                          "schedulable": true
                        },
                        {
                          "name": "string_flags",
                          "risk": "read",
                          "description": "malformed",
                          "enabled": "true",
                          "schedulable": "true",
                          "idempotent": "true"
                        }
                      ]''',
)
replace_once(
    path,
    '''            val request = server.takeRequest()
            assertEquals("/api/v1/tools", request.path)''',
    '''            val stringFlags = tools.getValue("string_flags")
            assertFalse(stringFlags.enabled)
            assertFalse(stringFlags.schedulable)
            assertFalse(stringFlags.canSchedule)
            assertNull(stringFlags.idempotent)
            assertEquals(
                "Riggen har ikke markeret værktøjet som planlægbart.",
                stringFlags.scheduleBlockReason,
            )

            val request = server.takeRequest()
            assertEquals("/api/v1/tools", request.path)''',
)
