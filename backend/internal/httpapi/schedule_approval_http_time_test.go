package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestScheduleCreateApprovalForwardsAndMatchesTimeTerms(t *testing.T) {
	const fingerprint = "1234567890abcdef1234567890abcdef"
	var previewHits, createHits int
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var terms map[string]any
		if err := json.Unmarshal(body, &terms); err != nil {
			t.Fatalf("worker body: %v", err)
		}
		switch r.URL.Path {
		case "/schedules/preview":
			previewHits++
			if terms["timezone"] != "America/New_York" || terms["misfire_policy"] != "run_once" {
				t.Fatalf("preview time terms = %#v", terms)
			}
			enable := true
			writeJSON(w, http.StatusOK, map[string]any{
				"preview": map[string]any{
					"operation":            "create",
					"schedule_id":          nil,
					"tool":                 "note_append",
					"args":                 map[string]any{"text": "New York HTTP"},
					"cadence":              "daily:02:30",
					"timezone":             "America/New_York",
					"misfire_policy":       "run_once",
					"requires_approval":    true,
					"action_fingerprint":   "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
					"approval_fingerprint": fingerprint,
					"ttl_days":             30,
					"max_runs":             3,
					"enable":               &enable,
				},
				"executed":           false,
				"schedule_persisted": false,
			})
		case "/schedules":
			createHits++
			if terms["timezone"] != "America/New_York" || terms["misfire_policy"] != "run_once" {
				t.Fatalf("create time terms = %#v", terms)
			}
			writeJSON(w, http.StatusOK, map[string]any{
				"schedule": map[string]any{
					"schedule_id":     "t017newyork",
					"timezone":        "America/New_York",
					"misfire_policy":  "run_once",
					"due_at_local":    "2026-07-22T02:30:00-04:00",
				},
				"executed": false,
			})
		default:
			http.NotFound(w, r)
		}
	}))
	defer worker.Close()

	h := scheduleHandler(t, worker.URL, 2*time.Second)
	approvalBody := `{
		"tool":"note_append",
		"args":{"text":"New York HTTP"},
		"cadence":"daily:02:30",
		"timezone":"America/New_York",
		"misfire_policy":"run_once",
		"ttl_days":30,
		"max_runs":3,
		"preview_fingerprint":"` + fingerprint + `"
	}`
	approved := doScheduleRequest(
		h, http.MethodPost, "/api/v1/schedules/approve", scheduleToken, approvalBody,
	)
	if approved.Code != http.StatusOK {
		t.Fatalf("approve: %d %s", approved.Code, approved.Body.String())
	}
	var approvalResp struct {
		ApprovalToken string `json:"approval_token"`
	}
	if err := json.Unmarshal(approved.Body.Bytes(), &approvalResp); err != nil {
		t.Fatalf("approval response: %v", err)
	}
	claims, err := verifyScheduleApprovalToken(
		approvalResp.ApprovalToken, "schedule-device", time.Now(),
	)
	if err != nil {
		t.Fatalf("verify issued token: %v", err)
	}
	if claims.Version != 2 || claims.Timezone != "America/New_York" || claims.MisfirePolicy != "run_once" {
		t.Fatalf("claims = v%d %q/%q", claims.Version, claims.Timezone, claims.MisfirePolicy)
	}

	baseCreate := map[string]any{
		"tool":            "note_append",
		"args":            map[string]any{"text": "New York HTTP"},
		"cadence":         "daily:02:30",
		"timezone":        "America/New_York",
		"misfire_policy":  "run_once",
		"ttl_days":        30,
		"max_runs":        3,
		"approval_token":  approvalResp.ApprovalToken,
	}
	for name, mutate := range map[string]func(map[string]any){
		"timezone": func(body map[string]any) { body["timezone"] = "Europe/Copenhagen" },
		"policy":   func(body map[string]any) { body["misfire_policy"] = "skip" },
	} {
		t.Run("reject changed "+name, func(t *testing.T) {
			body := make(map[string]any, len(baseCreate))
			for key, value := range baseCreate {
				body[key] = value
			}
			mutate(body)
			raw, _ := json.Marshal(body)
			rec := doScheduleRequest(h, http.MethodPost, "/api/v1/schedules", scheduleToken, string(raw))
			if rec.Code != http.StatusConflict {
				t.Fatalf("got %d %s", rec.Code, rec.Body.String())
			}
		})
	}
	if createHits != 0 {
		t.Fatalf("tampered creates reached worker %d time(s)", createHits)
	}

	exactRaw, _ := json.Marshal(baseCreate)
	created := doScheduleRequest(
		h, http.MethodPost, "/api/v1/schedules", scheduleToken, string(exactRaw),
	)
	if created.Code != http.StatusOK {
		t.Fatalf("create: %d %s", created.Code, created.Body.String())
	}
	if previewHits != 1 || createHits != 1 {
		t.Fatalf("worker hits preview=%d create=%d", previewHits, createHits)
	}
}

func TestScheduleCreateApprovalNormalizesLegacyTimeDefaults(t *testing.T) {
	const fingerprint = "abcdefabcdefabcdefabcdefabcdefab"
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var terms map[string]any
		_ = json.Unmarshal(body, &terms)
		if terms["timezone"] != "Europe/Copenhagen" || terms["misfire_policy"] != "run_once" {
			t.Fatalf("legacy defaults not normalized: %#v", terms)
		}
		enable := true
		writeJSON(w, http.StatusOK, map[string]any{
			"preview": map[string]any{
				"operation": "create", "schedule_id": nil,
				"tool": "note_append", "args": map[string]any{"text": "legacy"},
				"cadence": "daily:08:00", "timezone": "Europe/Copenhagen",
				"misfire_policy": "run_once", "requires_approval": true,
				"action_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
				"approval_fingerprint": fingerprint, "ttl_days": 30,
				"max_runs": 1, "enable": &enable,
			},
		})
	}))
	defer worker.Close()
	h := scheduleHandler(t, worker.URL, 2*time.Second)
	rec := doScheduleRequest(
		h, http.MethodPost, "/api/v1/schedules/approve", scheduleToken,
		`{"tool":"note_append","args":{"text":"legacy"},"cadence":"daily:08:00","ttl_days":30,"max_runs":1,"preview_fingerprint":"`+fingerprint+`"}`,
	)
	if rec.Code != http.StatusOK {
		t.Fatalf("legacy approval: %d %s", rec.Code, rec.Body.String())
	}
}
