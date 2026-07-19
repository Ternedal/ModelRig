package httpapi

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"modelrig/internal/auth"
	"modelrig/internal/config"
	"modelrig/internal/proxy"
	"modelrig/internal/store"
)

const agent3ApprovalTestSecret = "agent3-backend-approval-secret-32-bytes-minimum"

type approvalWorkerState struct {
	t            *testing.T
	tool         string
	args         map[string]any
	digest       string
	revision     int
	stepID       string
	runID        string
	hits         []string
	confirm      agent3WorkerConfirmRequest
	confirmCalls int
}

func (s *approvalWorkerState) handler(w http.ResponseWriter, r *http.Request) {
	s.hits = append(s.hits, r.Method+" "+r.URL.Path)
	w.Header().Set("Content-Type", "application/json")
	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/experimental/agent3/runs/"+s.runID:
		_ = json.NewEncoder(w).Encode(map[string]any{
			"run": map[string]any{
				"id": s.runID, "state": "waiting_confirmation", "current_step": 0,
				"steps": []any{map[string]any{
					"id": s.stepID, "tool": s.tool, "args": s.args, "risk": "write",
					"confirmation_digest": s.digest,
					"confirmation_expires_at": float64(time.Now().Add(90 * time.Second).Unix()),
				}},
			},
		})
	case r.Method == http.MethodGet && r.URL.Path == "/experimental/agent3/runs/"+s.runID+"/replans":
		_ = json.NewEncoder(w).Encode(map[string]any{"revision": s.revision})
	case r.Method == http.MethodPost && r.URL.Path == "/experimental/agent3/runs/"+s.runID+"/confirm":
		s.confirmCalls++
		if err := json.NewDecoder(r.Body).Decode(&s.confirm); err != nil {
			s.t.Fatalf("decode worker confirm: %v", err)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"run": map[string]any{"id": s.runID}})
	default:
		http.NotFound(w, r)
	}
}

func approvalBackend(t *testing.T, state *approvalWorkerState) http.Handler {
	t.Helper()
	worker := httptest.NewServer(http.HandlerFunc(state.handler))
	t.Cleanup(worker.Close)
	st, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	if err := st.AddDevice(store.Device{
		ID: "dev1", Name: "test", TokenHash: auth.Hash(testToken),
		CreatedAt: time.Now(), LastSeen: time.Now(),
	}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}
	d := Deps{
		Cfg:        config.Config{ClaimMax: 5, RequestTimeout: 5 * time.Second},
		Store:      st,
		Ollama:     proxy.New(worker.URL, 5*time.Second),
		Worker:     proxy.New(worker.URL, 5*time.Second),
		WorkerSlow: proxy.New(worker.URL, 30*time.Second),
	}
	return New(d)
}

func approvalRequest(t *testing.T, h http.Handler, state *approvalWorkerState, body string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(
		http.MethodPost,
		"/api/v1/experimental/agent3/runs/"+state.runID+"/confirm",
		strings.NewReader(body),
	)
	req.Header.Set("Authorization", "Bearer "+testToken)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func decodeApprovalClaims(t *testing.T, token string) agent3ApprovalClaims {
	t.Helper()
	parts := strings.Split(token, ".")
	if len(parts) != 2 {
		t.Fatalf("approval token is malformed: %q", token)
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		t.Fatalf("decode payload: %v", err)
	}
	signature, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		t.Fatalf("decode signature: %v", err)
	}
	mac := hmac.New(sha256.New, []byte(agent3ApprovalTestSecret))
	_, _ = mac.Write([]byte(parts[0]))
	if !hmac.Equal(mac.Sum(nil), signature) {
		t.Fatal("backend approval token signature is invalid")
	}
	var claims agent3ApprovalClaims
	if err := json.Unmarshal(payload, &claims); err != nil {
		t.Fatalf("decode claims: %v", err)
	}
	return claims
}

func defaultApprovalState(t *testing.T) *approvalWorkerState {
	return &approvalWorkerState{
		t: t, tool: "note_append", args: map[string]any{"text": "MARKER"},
		digest: strings.Repeat("a", 64), revision: 4, stepID: "step-1", runID: "run-1",
	}
}

func TestAgent3ApproveIsReboundToDeviceAndCurrentWorkerState(t *testing.T) {
	t.Setenv("KALIV_AGENT3_ENABLED", "1")
	t.Setenv(agent3ApprovalRequiredEnv, "1")
	t.Setenv(agent3ApprovalSecretEnv, agent3ApprovalTestSecret)
	state := defaultApprovalState(t)
	h := approvalBackend(t, state)
	rec := approvalRequest(t, h, state,
		`{"step_id":"step-1","decision":"approve","digest":"`+state.digest+`"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("approve: got %d: %s", rec.Code, rec.Body.String())
	}
	if state.confirmCalls != 1 || state.confirm.ApprovalToken == "" {
		t.Fatalf("worker confirmation did not receive one approval token: %+v", state.confirm)
	}
	claims := decodeApprovalClaims(t, state.confirm.ApprovalToken)
	if claims.DeviceID != "dev1" || claims.RunID != state.runID || claims.StepID != state.stepID {
		t.Fatalf("approval attribution mismatch: %+v", claims)
	}
	if claims.Tool != "note_append" || claims.PlanRevision != 4 || claims.ConfirmationDigest != state.digest {
		t.Fatalf("approval action/revision mismatch: %+v", claims)
	}
	wantArgs, _ := agent3ArgsSHA256(state.args)
	if claims.ArgsSHA256 != wantArgs {
		t.Fatalf("args digest = %q, want %q", claims.ArgsSHA256, wantArgs)
	}
	if claims.ExpiresAt <= claims.IssuedAt || claims.ExpiresAt-claims.IssuedAt > 120 {
		t.Fatalf("approval lifetime invalid: %+v", claims)
	}
	wantHits := []string{
		"GET /experimental/agent3/runs/run-1",
		"GET /experimental/agent3/runs/run-1/replans",
		"POST /experimental/agent3/runs/run-1/confirm",
	}
	if strings.Join(state.hits, "|") != strings.Join(wantHits, "|") {
		t.Fatalf("worker hits = %v, want %v", state.hits, wantHits)
	}
}

func TestAgent3DenyDoesNotMintOrFetchApproval(t *testing.T) {
	t.Setenv("KALIV_AGENT3_ENABLED", "1")
	t.Setenv(agent3ApprovalRequiredEnv, "1")
	t.Setenv(agent3ApprovalSecretEnv, agent3ApprovalTestSecret)
	state := defaultApprovalState(t)
	h := approvalBackend(t, state)
	rec := approvalRequest(t, h, state,
		`{"step_id":"step-1","decision":"deny","digest":"`+state.digest+`"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("deny: got %d: %s", rec.Code, rec.Body.String())
	}
	if state.confirm.ApprovalToken != "" {
		t.Fatal("deny carried an approval token")
	}
	if len(state.hits) != 1 || state.hits[0] != "POST /experimental/agent3/runs/run-1/confirm" {
		t.Fatalf("deny made approval reads: %v", state.hits)
	}
}

func TestAgent3RequiredApprovalFailsWhenSecretMissing(t *testing.T) {
	t.Setenv("KALIV_AGENT3_ENABLED", "1")
	t.Setenv(agent3ApprovalRequiredEnv, "1")
	t.Setenv(agent3ApprovalSecretEnv, "")
	state := defaultApprovalState(t)
	h := approvalBackend(t, state)
	rec := approvalRequest(t, h, state,
		`{"step_id":"step-1","decision":"approve","digest":"`+state.digest+`"}`)
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("missing secret: got %d, want 503: %s", rec.Code, rec.Body.String())
	}
	if len(state.hits) != 0 {
		t.Fatalf("missing secret reached worker: %v", state.hits)
	}
}

func TestAgent3ApprovalRejectsChangedDigestAndNonAppendTool(t *testing.T) {
	t.Setenv("KALIV_AGENT3_ENABLED", "1")
	t.Setenv(agent3ApprovalRequiredEnv, "1")
	t.Setenv(agent3ApprovalSecretEnv, agent3ApprovalTestSecret)

	state := defaultApprovalState(t)
	h := approvalBackend(t, state)
	rec := approvalRequest(t, h, state,
		`{"step_id":"step-1","decision":"approve","digest":"`+strings.Repeat("b", 64)+`"}`)
	if rec.Code != http.StatusConflict || state.confirmCalls != 0 {
		t.Fatalf("changed digest: status=%d confirms=%d body=%s", rec.Code, state.confirmCalls, rec.Body.String())
	}

	state2 := defaultApprovalState(t)
	state2.tool = "delete_model"
	state2.args = map[string]any{"name": "qwen"}
	h2 := approvalBackend(t, state2)
	rec2 := approvalRequest(t, h2, state2,
		`{"step_id":"step-1","decision":"approve","digest":"`+state2.digest+`"}`)
	if rec2.Code != http.StatusConflict || state2.confirmCalls != 0 {
		t.Fatalf("non-append: status=%d confirms=%d body=%s", rec2.Code, state2.confirmCalls, rec2.Body.String())
	}
}

func TestAgent3ConfirmRejectsClientSuppliedApprovalTokenAndUnknownFields(t *testing.T) {
	t.Setenv("KALIV_AGENT3_ENABLED", "1")
	t.Setenv(agent3ApprovalRequiredEnv, "0")
	t.Setenv(agent3ApprovalSecretEnv, "")
	state := defaultApprovalState(t)
	h := approvalBackend(t, state)
	rec := approvalRequest(t, h, state,
		`{"step_id":"step-1","decision":"approve","digest":"`+state.digest+`","approval_token":"attacker"}`)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("client token: got %d, want 400: %s", rec.Code, rec.Body.String())
	}
	if len(state.hits) != 0 {
		t.Fatalf("client token reached worker: %v", state.hits)
	}
}
