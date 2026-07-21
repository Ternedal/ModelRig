#!/usr/bin/env python3
"""Apply only T-017 backend v2 claim issuance and verification.

Temporary transport. HTTP request fields, forwarding and commit matching remain
unchanged until stage 3B2b.
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
            f"{path}: expected one match, found {count}: {old[:180]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


GO = "backend/internal/httpapi/schedule_approvals.go"

replace_once(
    GO,
    '''\tCadence             string         `json:"cadence"`\n\tRequiresApproval    bool           `json:"requires_approval"`\n''',
    '''\tCadence             string         `json:"cadence"`\n\tTimezone            string         `json:"timezone"`\n\tMisfirePolicy       string         `json:"misfire_policy"`\n\tRequiresApproval    bool           `json:"requires_approval"`\n''',
)
replace_once(
    GO,
    '''\tCadence             string         `json:"cadence"`\n\tTTLDays             int            `json:"ttl_days"`\n''',
    '''\tCadence             string         `json:"cadence"`\n\tTimezone            string         `json:"timezone"`\n\tMisfirePolicy       string         `json:"misfire_policy"`\n\tTTLDays             int            `json:"ttl_days"`\n''',
)
replace_once(
    GO,
    '''\tif preview.ActionFingerprint == "" {\n\t\treturn "", scheduleApprovalClaims{}, errors.New("worker preview has no action fingerprint")\n\t}\n''',
    '''\tif preview.ActionFingerprint == "" {\n\t\treturn "", scheduleApprovalClaims{}, errors.New("worker preview has no action fingerprint")\n\t}\n\tif strings.TrimSpace(preview.Timezone) == "" || strings.TrimSpace(preview.MisfirePolicy) == "" {\n\t\treturn "", scheduleApprovalClaims{}, errors.New("worker preview has incomplete time terms")\n\t}\n''',
)
replace_once(GO, '''\t\tVersion:             1,\n''', '''\t\tVersion:             2,\n''')
replace_once(
    GO,
    '''\t\tCadence:             preview.Cadence,\n\t\tTTLDays:             preview.TTLDays,\n''',
    '''\t\tCadence:             preview.Cadence,\n\t\tTimezone:            preview.Timezone,\n\t\tMisfirePolicy:       preview.MisfirePolicy,\n\t\tTTLDays:             preview.TTLDays,\n''',
)
replace_once(
    GO,
    '''\tif claims.Version != 1 || claims.Nonce == "" || claims.DeviceID == "" {\n\t\treturn scheduleApprovalClaims{}, errors.New("schedule approval token claims are invalid")\n\t}\n''',
    '''\tif claims.Version != 2 || claims.Nonce == "" || claims.DeviceID == "" ||\n\t\tstrings.TrimSpace(claims.Timezone) == "" || strings.TrimSpace(claims.MisfirePolicy) == "" {\n\t\treturn scheduleApprovalClaims{}, errors.New("schedule approval token claims are invalid")\n\t}\n''',
)

# Existing backend route tests use one fake-worker preview helper. Production
# worker previews already include these fields after stage 3A; the fake now does
# the same without changing any request/route assertions.
TESTS = "backend/internal/httpapi/schedules_test.go"
replace_once(
    TESTS,
    '''\t\t\t"cadence":              cadence,\n\t\t\t"requires_approval":    true,\n''',
    '''\t\t\t"cadence":              cadence,\n\t\t\t"timezone":             "Europe/Copenhagen",\n\t\t\t"misfire_policy":       "run_once",\n\t\t\t"requires_approval":    true,\n''',
)

print("T-017 stage 3B2a backend v2 claims applied")
