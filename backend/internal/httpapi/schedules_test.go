package httpapi

import (
	"encoding/json"
	"errors"
	"io"
	"net"
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

const (
	scheduleToken       = "schedule-test-token"
	scheduleSecondToken = "schedule-second-token"
	scheduleTestSecret  = "0123456789abcdef0123456789abcdef-test-secret"
)

type scheduleHit struct {
	Method        string
	Path          string
	Body          string
	RequestID     string
	Authorization string
	RemoteHost    string
}

func scheduleHandlerWithFlag(
	t *testing.T,
	workerURL string,
	workerTimeout time.Duration,
	apiFlag string,
) http.Handler {
	t.Helper()
	t.Setenv("KALIV_SCHEDULER_API", apiFlag)
	t.Setenv(scheduleApprovalSecretEnv, scheduleTestSecret)

	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusTeapot)
	}))
	t.Cleanup(ollama.Close)

	st, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	for _, dv := range []store.Device{
		{ID: "schedule-device", Name: "phone", TokenHash: auth.Hash(scheduleToken), CreatedAt: time.Now(), LastSeen: time.Now()},
		{ID: "second-device", Name: "tablet", TokenHash: auth.Hash(scheduleSecondToken), CreatedAt: time.Now(), LastSeen: time.Now()},
	} {
		if err := st.AddDevice(dv); err != nil {
			t.Fatalf("AddDevice: %v", err)
		}
	}

	worker := proxy.New(workerURL, workerTimeout)
	return New(Deps{
		Cfg:        config.Config{ClaimMax: 5, RequestTimeout: workerTimeout},
		Store:      st,
		Ollama:     proxy.New(ollama.URL, workerTimeout),
		Worker:     worker,
		WorkerSlow: worker,
	})
}

func scheduleHandler(t *testing.T, workerURL string, workerTimeout time.Duration) http.Handler {
	t.Helper()
	return scheduleHandlerWithFlag(t, workerURL, workerTimeout, "1")
}

func doScheduleRequest(h http.Handler, method, path, token, body string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func writePreview(w http.ResponseWriter, operation string, scheduleID *string, tool string, args map[string]any, cadence string, ttl, runs int, enable *bool, fingerprint string) {
	writeJSON(w, http.StatusOK, map[string]any{
		"preview": map[string]any{
			"operation":            operation,
			"schedule_id":          scheduleID,
			"tool":                 tool,
			"args":                 args,
			"cadence":              cadence,
			"requires_approval":    true,
			"action_fingerprint":   "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
			"approval_fingerprint": fingerprint,
			"ttl_days":             ttl,
			"max_runs":             runs,
			"enable":               enable,
		},
		"executed":           false,
		"schedule_persisted": false,
	})
}

func TestScheduleRoutesRequireSeparateExplicitOptIn(t *testing.T) {
	t.Setenv("KALIV_SCHEDULER", "1")
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Fatal("disabled schedule API reached worker")
	}))
	defer worker.Close()

	for _, flag := range []string{"", "0", "false", "true", "on", "garbage"} {
		t.Run("flag="+flag, func(t *testing.T) {
			h := scheduleHandlerWithFlag(t, worker.URL, 2*time.Second, flag)
			rec := doScheduleRequest(h, http.MethodGet, "/api/v1/schedules/status", scheduleToken, "")
			if rec.Code != http.StatusNotFound {
				t.Fatalf("KALIV_SCHEDULER_API=%q: got %d, want 404", flag, rec.Code)
			}
		})
	}
}

func TestAllScheduleRoutesRequireBearerBeforeWorker(t *testing.T) {
	hits := 0
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits++
	}))
	defer worker.Close()
	h := scheduleHandler(t, worker.URL, 2*time.Second)

	routes := []struct{ method, path string }{
		{http.MethodGet, "/api/v1/schedules/status"},
		{http.MethodPost, "/api/v1/schedules/preview"},
		{http.MethodPost, "/api/v1/schedules/approve"},
		{http.MethodGet, "/api/v1/schedules"},
		{http.MethodPost, "/api/v1/schedules"},
		{http.MethodGet, "/api/v1/schedules/012345abcdef"},
		{http.MethodPost, "/api/v1/schedules/012345abcdef/enabled"},
		{http.MethodPost, "/api/v1/schedules/012345abcdef/renew/preview"},
		{http.MethodPost, "/api/v1/schedules/012345abcdef/renew/approve"},
		{http.MethodPost, "/api/v1/schedules/012345abcdef/renew"},
	}
	for _, route := range routes {
		for _, token := range []string{"", "wrong"} {
			rec := doScheduleRequest(h, route.method, route.path, token, `{}`)
			if rec.Code != http.StatusUnauthorized {
				t.Fatalf("%s %s token=%q: got %d", route.method, route.path, token, rec.Code)
			}
		}
	}
	if hits != 0 {
		t.Fatalf("unauthenticated requests reached worker %d time(s)", hits)
	}
}

func TestScheduleApprovalIsBackendIssuedDeviceBoundAndExact(t *testing.T) {
	const fingerprint = "1234567890abcdef1234567890abcdef"
	var hits []scheduleHit
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		host, _, _ := net.SplitHostPort(r.RemoteAddr)
		hits = append(hits, scheduleHit{
			Method: r.Method, Path: r.URL.Path, Body: string(body),
			RequestID: r.Header.Get("X-Request-ID"), Authorization: r.Header.Get("Authorization"), RemoteHost: host,
		})
		switch r.URL.Path {
		case "/schedules/preview":
			writePreview(w, "create", nil, "note_append", map[string]any{"text": "Husk brygdag"}, "daily:08:00", 30, 5, boolPtr(true), fingerprint)
		case "/schedules":
			writeJSON(w, http.StatusOK, map[string]any{"schedule": map[string]any{"schedule_id": "012345abcdef"}, "executed": false})
		default:
			http.NotFound(w, r)
		}
	}))
	defer worker.Close()
	h := scheduleHandler(t, worker.URL, 2*time.Second)

	approvalBody := `{"tool":"note_append","args":{"text":"Husk brygdag"},"cadence":"daily:08:00","ttl_days":30,"max_runs":5,"preview_fingerprint":"` + fingerprint + `"}`
	approved := doScheduleRequest(h, http.MethodPost, "/api/v1/schedules/approve", scheduleToken, approvalBody)
	if approved.Code != http.StatusOK {
		t.Fatalf("approval: %d %s", approved.Code, approved.Body.String())
	}
	var issued struct {
		ApprovalToken string `json:"approval_token"`
	}
	if err := json.Unmarshal(approved.Body.Bytes(), &issued); err != nil || issued.ApprovalToken == "" {
		t.Fatalf("missing approval token: %v body=%s", err, approved.Body.String())
	}

	createBody := `{"tool":"note_append","args":{"text":"Husk brygdag"},"cadence":"daily:08:00","ttl_days":30,"max_runs":5,"approval_token":"` + issued.ApprovalToken + `"}`
	created := doScheduleRequest(h, http.MethodPost, "/api/v1/schedules", scheduleToken, createBody)
	if created.Code != http.StatusOK {
		t.Fatalf("create: %d %s", created.Code, created.Body.String())
	}
	if len(hits) != 2 || hits[0].Path != "/schedules/preview" || hits[1].Path != "/schedules" {
		t.Fatalf("unexpected worker calls: %+v", hits)
	}
	for _, hit := range hits {
		if hit.Authorization != "" {
			t.Fatalf("device bearer leaked to worker on %s", hit.Path)
		}
		if ip := net.ParseIP(hit.RemoteHost); ip == nil || !ip.IsLoopback() {
			t.Fatalf("worker caller was %q, want loopback", hit.RemoteHost)
		}
	}
	if !strings.Contains(hits[1].Body, `"approval_token"`) || strings.Contains(hits[1].Body, "approved_fingerprint") {
		t.Fatalf("worker create body did not carry only opaque token: %s", hits[1].Body)
	}

	wrongDevice := doScheduleRequest(h, http.MethodPost, "/api/v1/schedules", scheduleSecondToken, createBody)
	if wrongDevice.Code != http.StatusConflict || !strings.Contains(wrongDevice.Body.String(), "another paired device") {
		t.Fatalf("device binding: %d %s", wrongDevice.Code, wrongDevice.Body.String())
	}
	if len(hits) != 2 {
		t.Fatalf("wrong-device token reached worker: %+v", hits)
	}

	tampered := strings.Replace(createBody, "Husk brygdag", "En anden note", 1)
	tamperResp := doScheduleRequest(h, http.MethodPost, "/api/v1/schedules", scheduleToken, tampered)
	if tamperResp.Code != http.StatusConflict || !strings.Contains(tamperResp.Body.String(), "does not match") {
		t.Fatalf("tamper: %d %s", tamperResp.Code, tamperResp.Body.String())
	}
	if len(hits) != 2 {
		t.Fatalf("tampered request reached worker: %+v", hits)
	}
}

func TestRenewalApprovalBindsScheduleAndEnableState(t *testing.T) {
	const id = "abcdef012345"
	const fingerprint = "fedcba0987654321fedcba0987654321"
	var renewBodies []string
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		switch r.URL.Path {
		case "/schedules/" + id + "/renew/preview":
			writePreview(w, "renew", stringPtr(id), "note_append", map[string]any{"text": "Husk brygdag"}, "daily:08:00", 60, 2, boolPtr(true), fingerprint)
		case "/schedules/" + id + "/renew":
			renewBodies = append(renewBodies, string(body))
			writeJSON(w, http.StatusOK, map[string]any{"schedule": map[string]any{"schedule_id": id}})
		default:
			http.NotFound(w, r)
		}
	}))
	defer worker.Close()
	h := scheduleHandler(t, worker.URL, 2*time.Second)

	approvalBody := `{"ttl_days":60,"max_runs":2,"enable":true,"preview_fingerprint":"` + fingerprint + `"}`
	approved := doScheduleRequest(h, http.MethodPost, "/api/v1/schedules/"+id+"/renew/approve", scheduleToken, approvalBody)
	var issued struct {
		ApprovalToken string `json:"approval_token"`
	}
	_ = json.Unmarshal(approved.Body.Bytes(), &issued)
	if approved.Code != http.StatusOK || issued.ApprovalToken == "" {
		t.Fatalf("renew approval: %d %s", approved.Code, approved.Body.String())
	}

	changed := `{"ttl_days":60,"max_runs":2,"enable":false,"approval_token":"` + issued.ApprovalToken + `"}`
	bad := doScheduleRequest(h, http.MethodPost, "/api/v1/schedules/"+id+"/renew", scheduleToken, changed)
	if bad.Code != http.StatusConflict || len(renewBodies) != 0 {
		t.Fatalf("changed enable accepted: %d %s bodies=%v", bad.Code, bad.Body.String(), renewBodies)
	}

	exact := `{"ttl_days":60,"max_runs":2,"enable":true,"approval_token":"` + issued.ApprovalToken + `"}`
	ok := doScheduleRequest(h, http.MethodPost, "/api/v1/schedules/"+id+"/renew", scheduleToken, exact)
	if ok.Code != http.StatusOK || len(renewBodies) != 1 {
		t.Fatalf("exact renewal: %d %s bodies=%v", ok.Code, ok.Body.String(), renewBodies)
	}
}

func TestScheduleApprovalTokenRejectsExpiryAndInvalidSecret(t *testing.T) {
	t.Setenv(scheduleApprovalSecretEnv, scheduleTestSecret)
	preview := scheduleApprovalPreview{
		Operation: "create", Tool: "note_append", Args: map[string]any{"text": "x"},
		Cadence: "daily:08:00", RequiresApproval: true,
		ActionFingerprint:   "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		ApprovalFingerprint: stringPtr("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
		TTLDays:             30, MaxRuns: 1, Enable: boolPtr(true),
	}
	now := time.Unix(1_800_000_000, 0)
	token, _, err := issueScheduleApprovalToken(preview, "schedule-device", now)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := verifyScheduleApprovalToken(token, "schedule-device", now.Add(scheduleApprovalTTL+time.Second)); err == nil || !strings.Contains(err.Error(), "expired") {
		t.Fatalf("expired token accepted: %v", err)
	}

	t.Setenv(scheduleApprovalSecretEnv, "too-short")
	if _, _, err := issueScheduleApprovalToken(preview, "schedule-device", now); !errors.Is(err, errScheduleApprovalUnavailable) {
		t.Fatalf("short secret did not fail closed: %v", err)
	}
}

func TestScheduleReadCreateStillNeedsNoWriteToken(t *testing.T) {
	var body string
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		body = string(b)
		writeJSON(w, http.StatusOK, map[string]any{"schedule": map[string]any{"schedule_id": "012345abcdef"}})
	}))
	defer worker.Close()
	h := scheduleHandler(t, worker.URL, 2*time.Second)
	rec := doScheduleRequest(h, http.MethodPost, "/api/v1/schedules", scheduleToken, `{"tool":"current_datetime","args":{},"cadence":"every:60","ttl_days":10,"max_runs":0}`)
	if rec.Code != http.StatusOK || strings.Contains(body, "approval_token") {
		t.Fatalf("read create changed: %d %s worker=%s", rec.Code, rec.Body.String(), body)
	}
}

func TestScheduleProxyRejectsBadIDsAndNonLoopbackWorker(t *testing.T) {
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Fatal("invalid id reached worker")
	}))
	defer worker.Close()
	h := scheduleHandler(t, worker.URL, 2*time.Second)
	for _, path := range []string{
		"/api/v1/schedules/too-short",
		"/api/v1/schedules/ABCDEF012345",
		"/api/v1/schedules/012345abcdeg/renew/approve",
	} {
		method := http.MethodGet
		if strings.Contains(path, "approve") {
			method = http.MethodPost
		}
		rec := doScheduleRequest(h, method, path, scheduleToken, `{}`)
		if rec.Code != http.StatusBadRequest {
			t.Fatalf("%s: got %d", path, rec.Code)
		}
	}

	h = scheduleHandler(t, "http://192.0.2.10:8099", 20*time.Millisecond)
	rec := doScheduleRequest(h, http.MethodPost, "/api/v1/schedules/approve", scheduleToken, `{}`)
	if rec.Code != http.StatusBadRequest { // malformed body is rejected before any upstream decision
		t.Fatalf("malformed approval got %d", rec.Code)
	}
	rec = doScheduleRequest(h, http.MethodPost, "/api/v1/schedules/preview", scheduleToken, `{"tool":"current_datetime"}`)
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("non-loopback worker got %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestScheduleWorkerLoopbackURLParser(t *testing.T) {
	for _, tc := range []struct {
		url  string
		want bool
	}{
		{"http://127.0.0.1:8099", true},
		{"http://127.42.1.9", true},
		{"https://localhost:8099", true},
		{"http://localhost.:8099", true},
		{"http://[::1]:8099", true},
		{"http://192.168.1.20:8099", false},
		{"http://localhost.evil.example", false},
		{"http://127.0.0.1@evil.example", false},
		{"file:///tmp/worker.sock", false},
		{"not a url", false},
	} {
		if got := scheduleWorkerIsLoopback(tc.url); got != tc.want {
			t.Errorf("scheduleWorkerIsLoopback(%q)=%v, want %v", tc.url, got, tc.want)
		}
	}
}

func boolPtr(v bool) *bool       { return &v }
func stringPtr(v string) *string { return &v }
