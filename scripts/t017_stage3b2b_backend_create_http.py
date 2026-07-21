#!/usr/bin/env python3
"""Apply only T-017 backend create-approval time forwarding and matching.

Temporary transport. Renewal request semantics and Android remain unchanged.
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
            f"{path}: expected one match, found {count}: {old[:200]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


GO = "backend/internal/httpapi/schedule_approvals.go"

replace_once(
    GO,
    '''\tscheduleApprovalTTL       = 2 * time.Minute\n\tmaxScheduleBodyBytes      = 64 << 10\n''',
    '''\tscheduleApprovalTTL       = 2 * time.Minute\n\tmaxScheduleBodyBytes      = 64 << 10\n\tdefaultScheduleTimezone   = "Europe/Copenhagen"\n\tdefaultScheduleMisfire    = "run_once"\n''',
)
replace_once(
    GO,
    '''type scheduleCreateTerms struct {\n\tTool    string         `json:"tool"`\n\tArgs    map[string]any `json:"args"`\n\tCadence string         `json:"cadence"`\n\tTTLDays int            `json:"ttl_days"`\n\tMaxRuns int            `json:"max_runs"`\n}\n''',
    '''type scheduleCreateTerms struct {\n\tTool          string         `json:"tool"`\n\tArgs          map[string]any `json:"args"`\n\tCadence       string         `json:"cadence"`\n\tTimezone      string         `json:"timezone"`\n\tMisfirePolicy string         `json:"misfire_policy"`\n\tTTLDays       int            `json:"ttl_days"`\n\tMaxRuns       int            `json:"max_runs"`\n}\n''',
)
replace_once(
    GO,
    '''type scheduleCreateApprovalRequest struct {\n\tTool               string         `json:"tool"`\n\tArgs               map[string]any `json:"args"`\n\tCadence            string         `json:"cadence"`\n\tTTLDays            int            `json:"ttl_days"`\n\tMaxRuns            int            `json:"max_runs"`\n\tPreviewFingerprint string         `json:"preview_fingerprint"`\n}\n''',
    '''type scheduleCreateApprovalRequest struct {\n\tTool               string         `json:"tool"`\n\tArgs               map[string]any `json:"args"`\n\tCadence            string         `json:"cadence"`\n\tTimezone           string         `json:"timezone"`\n\tMisfirePolicy      string         `json:"misfire_policy"`\n\tTTLDays            int            `json:"ttl_days"`\n\tMaxRuns            int            `json:"max_runs"`\n\tPreviewFingerprint string         `json:"preview_fingerprint"`\n}\n''',
)
replace_once(
    GO,
    '''type scheduleCreateCommitRequest struct {\n\tTool          string         `json:"tool"`\n\tArgs          map[string]any `json:"args"`\n\tCadence       string         `json:"cadence"`\n\tTTLDays       int            `json:"ttl_days"`\n\tMaxRuns       int            `json:"max_runs"`\n\tApprovalToken string         `json:"approval_token,omitempty"`\n}\n''',
    '''type scheduleCreateCommitRequest struct {\n\tTool          string         `json:"tool"`\n\tArgs          map[string]any `json:"args"`\n\tCadence       string         `json:"cadence"`\n\tTimezone      string         `json:"timezone"`\n\tMisfirePolicy string         `json:"misfire_policy"`\n\tTTLDays       int            `json:"ttl_days"`\n\tMaxRuns       int            `json:"max_runs"`\n\tApprovalToken string         `json:"approval_token,omitempty"`\n}\n''',
)
replace_once(
    GO,
    '''type scheduleRenewTerms struct {\n''',
    '''func normalizeScheduleTimeTerms(timezone, policy string) (string, string) {\n\tif strings.TrimSpace(timezone) == "" {\n\t\ttimezone = defaultScheduleTimezone\n\t}\n\tif strings.TrimSpace(policy) == "" {\n\t\tpolicy = defaultScheduleMisfire\n\t}\n\treturn timezone, policy\n}\n\ntype scheduleRenewTerms struct {\n''',
)

# Approval route: normalize legacy omissions, forward exact fields and verify the
# worker preview describes the same terms before issuing a token.
replace_once(
    GO,
    '''\tif strings.TrimSpace(approval.Tool) == "" || strings.TrimSpace(approval.Cadence) == "" ||\n\t\tstrings.TrimSpace(approval.PreviewFingerprint) == "" {\n''',
    '''\tapproval.Timezone, approval.MisfirePolicy = normalizeScheduleTimeTerms(\n\t\tapproval.Timezone, approval.MisfirePolicy)\n\tif strings.TrimSpace(approval.Tool) == "" || strings.TrimSpace(approval.Cadence) == "" ||\n\t\tstrings.TrimSpace(approval.PreviewFingerprint) == "" {\n''',
)
replace_once(
    GO,
    '''\tpreviewBody, _ := json.Marshal(scheduleCreateTerms{\n\t\tTool: approval.Tool, Args: approval.Args, Cadence: approval.Cadence,\n\t\tTTLDays: approval.TTLDays, MaxRuns: approval.MaxRuns,\n\t})\n''',
    '''\tpreviewBody, _ := json.Marshal(scheduleCreateTerms{\n\t\tTool: approval.Tool, Args: approval.Args, Cadence: approval.Cadence,\n\t\tTimezone: approval.Timezone, MisfirePolicy: approval.MisfirePolicy,\n\t\tTTLDays: approval.TTLDays, MaxRuns: approval.MaxRuns,\n\t})\n''',
)
replace_once(
    GO,
    '''\t\tpreview.Cadence != approval.Cadence || preview.TTLDays != approval.TTLDays ||\n\t\tpreview.MaxRuns != approval.MaxRuns || preview.Enable == nil || !*preview.Enable {\n''',
    '''\t\tpreview.Cadence != approval.Cadence || preview.Timezone != approval.Timezone ||\n\t\tpreview.MisfirePolicy != approval.MisfirePolicy || preview.TTLDays != approval.TTLDays ||\n\t\tpreview.MaxRuns != approval.MaxRuns || preview.Enable == nil || !*preview.Enable {\n''',
)

replace_once(
    GO,
    '''func claimsMatchCreate(claims scheduleApprovalClaims, req scheduleCreateCommitRequest) bool {\n\treturn claims.Operation == "create" && claims.ScheduleID == nil &&\n\t\tclaims.Tool == req.Tool && reflect.DeepEqual(claims.Args, req.Args) &&\n\t\tclaims.Cadence == req.Cadence && claims.TTLDays == req.TTLDays &&\n\t\tclaims.MaxRuns == req.MaxRuns && claims.Enable != nil && *claims.Enable\n}\n''',
    '''func claimsMatchCreate(claims scheduleApprovalClaims, req scheduleCreateCommitRequest) bool {\n\treturn claims.Operation == "create" && claims.ScheduleID == nil &&\n\t\tclaims.Tool == req.Tool && reflect.DeepEqual(claims.Args, req.Args) &&\n\t\tclaims.Cadence == req.Cadence && claims.Timezone == req.Timezone &&\n\t\tclaims.MisfirePolicy == req.MisfirePolicy && claims.TTLDays == req.TTLDays &&\n\t\tclaims.MaxRuns == req.MaxRuns && claims.Enable != nil && *claims.Enable\n}\n''',
)

# Commit route: strict-decode first, then normalize compatibility defaults before
# claim comparison and before the canonical body is forwarded to the worker.
replace_once(
    GO,
    '''\tif req.ApprovalToken != "" {\n\t\tif err := decodeScheduleJSON(body, &req); err != nil {\n\t\t\twriteErr(w, http.StatusBadRequest, "invalid schedule create request: "+err.Error())\n\t\t\treturn\n\t\t}\n\t\tdeviceID, ok := scheduleDeviceID(r)\n''',
    '''\tif req.ApprovalToken != "" {\n\t\tif err := decodeScheduleJSON(body, &req); err != nil {\n\t\t\twriteErr(w, http.StatusBadRequest, "invalid schedule create request: "+err.Error())\n\t\t\treturn\n\t\t}\n\t\treq.Timezone, req.MisfirePolicy = normalizeScheduleTimeTerms(\n\t\t\treq.Timezone, req.MisfirePolicy)\n\t\tdeviceID, ok := scheduleDeviceID(r)\n''',
)

# A direct token-unit fixture bypasses the worker preview helper; it must now be
# explicit too, otherwise normal `go test ./...` would correctly fail closed.
TESTS = "backend/internal/httpapi/schedules_test.go"
replace_once(
    TESTS,
    '''\t\tCadence: "daily:08:00", RequiresApproval: true,\n\t\tActionFingerprint:   "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",\n''',
    '''\t\tCadence: "daily:08:00", Timezone: defaultScheduleTimezone,\n\t\tMisfirePolicy: defaultScheduleMisfire, RequiresApproval: true,\n\t\tActionFingerprint:   "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",\n''',
)

print("T-017 stage 3B2b backend create HTTP applied")
