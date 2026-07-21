package httpapi

import (
	"testing"
	"time"
)

const scheduleTimeClaimSecret = "0123456789abcdef0123456789abcdef-t017-claims"

func TestScheduleApprovalV2ClaimsBindTimeTerms(t *testing.T) {
	t.Setenv(scheduleApprovalSecretEnv, scheduleTimeClaimSecret)
	enable := true
	fingerprint := "1234567890abcdef1234567890abcdef"
	preview := scheduleApprovalPreview{
		Operation:           "create",
		ScheduleID:          nil,
		Tool:                "note_append",
		Args:                map[string]any{"text": "New York grant"},
		Cadence:             "daily:02:30",
		Timezone:            "America/New_York",
		MisfirePolicy:       "run_once",
		RequiresApproval:    true,
		ActionFingerprint:   "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		ApprovalFingerprint: &fingerprint,
		TTLDays:             30,
		MaxRuns:             5,
		Enable:              &enable,
	}
	now := time.Unix(1_800_000_000, 0)
	token, issued, err := issueScheduleApprovalToken(preview, "pixel-6a-t017", now)
	if err != nil {
		t.Fatalf("issueScheduleApprovalToken: %v", err)
	}
	if issued.Version != 2 {
		t.Fatalf("version=%d, want 2", issued.Version)
	}
	if issued.Timezone != preview.Timezone || issued.MisfirePolicy != preview.MisfirePolicy {
		t.Fatalf("issued time claims = %q/%q, want %q/%q", issued.Timezone, issued.MisfirePolicy, preview.Timezone, preview.MisfirePolicy)
	}

	verified, err := verifyScheduleApprovalToken(token, "pixel-6a-t017", now.Add(time.Second))
	if err != nil {
		t.Fatalf("verifyScheduleApprovalToken: %v", err)
	}
	if verified.Timezone != "America/New_York" || verified.MisfirePolicy != "run_once" {
		t.Fatalf("verified time claims = %q/%q", verified.Timezone, verified.MisfirePolicy)
	}

	req := scheduleCreateCommitRequest{
		Tool:          preview.Tool,
		Args:          preview.Args,
		Cadence:       preview.Cadence,
		Timezone:      preview.Timezone,
		MisfirePolicy: preview.MisfirePolicy,
		TTLDays:       preview.TTLDays,
		MaxRuns:       preview.MaxRuns,
		ApprovalToken: token,
	}
	if !claimsMatchCreate(verified, req) {
		t.Fatal("exact create terms did not match v2 claims")
	}

	changedZone := req
	changedZone.Timezone = "Europe/Copenhagen"
	if claimsMatchCreate(verified, changedZone) {
		t.Fatal("changed timezone matched signed claims")
	}
	changedPolicy := req
	changedPolicy.MisfirePolicy = "skip"
	if claimsMatchCreate(verified, changedPolicy) {
		t.Fatal("changed misfire policy matched signed claims")
	}
}

func TestScheduleApprovalV2RejectsIncompleteTimeClaims(t *testing.T) {
	t.Setenv(scheduleApprovalSecretEnv, scheduleTimeClaimSecret)
	enable := true
	fingerprint := "1234567890abcdef1234567890abcdef"
	for _, tc := range []struct {
		name     string
		timezone string
		policy   string
	}{
		{name: "missing timezone", timezone: "", policy: "run_once"},
		{name: "missing policy", timezone: "Europe/Copenhagen", policy: ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, _, err := issueScheduleApprovalToken(scheduleApprovalPreview{
				Operation:           "create",
				Tool:                "note_append",
				Args:                map[string]any{"text": "x"},
				Cadence:             "daily:08:00",
				Timezone:            tc.timezone,
				MisfirePolicy:       tc.policy,
				RequiresApproval:    true,
				ActionFingerprint:   "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
				ApprovalFingerprint: &fingerprint,
				TTLDays:             30,
				MaxRuns:             1,
				Enable:              &enable,
			}, "pixel-6a-t017", time.Unix(1_800_000_000, 0))
			if err == nil {
				t.Fatal("incomplete time claims were issued")
			}
		})
	}
}
