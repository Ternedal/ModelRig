package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestScheduleRenewalApprovalInheritsPersistedTimeTerms(t *testing.T) {
	const id = "abcdef012345"
	const fingerprint = "fedcba0987654321fedcba0987654321"
	var renewHits int
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		switch r.URL.Path {
		case "/schedules/" + id + "/renew/preview":
			var terms map[string]any
			if err := json.Unmarshal(body, &terms); err != nil {
				t.Fatalf("renew preview body: %v", err)
			}
			if _, exists := terms["timezone"]; exists {
				t.Fatalf("client attempted to choose renewal timezone: %#v", terms)
			}
			enable := true
			writeJSON(w, http.StatusOK, map[string]any{
				"preview": map[string]any{
					"operation": "renew", "schedule_id": id,
					"tool": "note_append", "args": map[string]any{"text": "persisted"},
					"cadence": "daily:02:30", "timezone": "America/New_York",
					"misfire_policy": "run_once", "requires_approval": true,
					"action_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
					"approval_fingerprint": fingerprint, "ttl_days": 60,
					"max_runs": 2, "enable": &enable,
				},
			})
		case "/schedules/" + id + "/renew":
			renewHits++
			writeJSON(w, http.StatusOK, map[string]any{
				"schedule": map[string]any{
					"schedule_id": id, "timezone": "America/New_York",
					"misfire_policy": "run_once",
				},
			})
		default:
			http.NotFound(w, r)
		}
	}))
	defer worker.Close()

	h := scheduleHandler(t, worker.URL, 2*time.Second)
	approved := doScheduleRequest(
		h, http.MethodPost,
		"/api/v1/schedules/"+id+"/renew/approve",
		scheduleToken,
		`{"ttl_days":60,"max_runs":2,"enable":true,"preview_fingerprint":"`+fingerprint+`"}`,
	)
	if approved.Code != http.StatusOK {
		t.Fatalf("renew approve: %d %s", approved.Code, approved.Body.String())
	}
	var response struct {
		ApprovalToken string `json:"approval_token"`
	}
	if err := json.Unmarshal(approved.Body.Bytes(), &response); err != nil {
		t.Fatalf("renew approval response: %v", err)
	}
	claims, err := verifyScheduleApprovalToken(
		response.ApprovalToken, "schedule-device", time.Now(),
	)
	if err != nil {
		t.Fatalf("verify renewal token: %v", err)
	}
	if claims.Operation != "renew" || claims.ScheduleID == nil || *claims.ScheduleID != id {
		t.Fatalf("renew binding = %q/%v", claims.Operation, claims.ScheduleID)
	}
	if claims.Timezone != "America/New_York" || claims.MisfirePolicy != "run_once" {
		t.Fatalf("renew time claims = %q/%q", claims.Timezone, claims.MisfirePolicy)
	}

	changed := doScheduleRequest(
		h, http.MethodPost, "/api/v1/schedules/"+id+"/renew", scheduleToken,
		`{"ttl_days":60,"max_runs":2,"enable":false,"approval_token":"`+response.ApprovalToken+`"}`,
	)
	if changed.Code != http.StatusConflict || renewHits != 0 {
		t.Fatalf("changed renewal accepted: %d %s hits=%d", changed.Code, changed.Body.String(), renewHits)
	}

	exact := doScheduleRequest(
		h, http.MethodPost, "/api/v1/schedules/"+id+"/renew", scheduleToken,
		`{"ttl_days":60,"max_runs":2,"enable":true,"approval_token":"`+response.ApprovalToken+`"}`,
	)
	if exact.Code != http.StatusOK || renewHits != 1 {
		t.Fatalf("exact renewal: %d %s hits=%d", exact.Code, exact.Body.String(), renewHits)
	}
}
