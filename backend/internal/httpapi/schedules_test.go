package httpapi

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"modelrig/internal/auth"
	"modelrig/internal/config"
	"modelrig/internal/proxy"
	"modelrig/internal/store"
)

const scheduleToken = "schedule-test-token"

type scheduleHit struct {
	Method        string
	Path          string
	Query         string
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
) (http.Handler, *[]string) {
	t.Helper()
	t.Setenv("KALIV_SCHEDULER_API", apiFlag)

	ollamaHits := []string{}
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ollamaHits = append(ollamaHits, r.URL.Path)
		w.WriteHeader(http.StatusTeapot)
	}))
	t.Cleanup(ollama.Close)

	st, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	if err := st.AddDevice(store.Device{
		ID: "schedule-device", Name: "phone", TokenHash: auth.Hash(scheduleToken),
		CreatedAt: time.Now(), LastSeen: time.Now(),
	}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}

	worker := proxy.New(workerURL, workerTimeout)
	return New(Deps{
		Cfg: config.Config{
			ClaimMax: 5, RequestTimeout: workerTimeout,
			SchedulerApprovalPrivateKey: os.Getenv("KALIV_SCHEDULER_APPROVAL_PRIVATE_KEY"),
		},
		Store:      st,
		Ollama:     proxy.New(ollama.URL, workerTimeout),
		Worker:     worker,
		WorkerSlow: worker,
	}), &ollamaHits
}

func scheduleHandler(t *testing.T, workerURL string, workerTimeout time.Duration) (http.Handler, *[]string) {
	t.Helper()
	return scheduleHandlerWithFlag(t, workerURL, workerTimeout, "1")
}

var scheduleRoutes = []struct {
	method string
	public string
	worker string
}{
	{http.MethodGet, "/api/v1/schedules/status", "/schedules/status"},
	{http.MethodPost, "/api/v1/schedules/preview", "/schedules/preview"},
	{http.MethodGet, "/api/v1/schedules", "/schedules"},
	{http.MethodPost, "/api/v1/schedules", "/schedules"},
	{http.MethodGet, "/api/v1/schedules/012345abcdef", "/schedules/012345abcdef"},
	{http.MethodPost, "/api/v1/schedules/012345abcdef/enabled", "/schedules/012345abcdef/enabled"},
	{http.MethodPost, "/api/v1/schedules/012345abcdef/renew/preview", "/schedules/012345abcdef/renew/preview"},
	{http.MethodPost, "/api/v1/schedules/012345abcdef/renew", "/schedules/012345abcdef/renew"},
}

var scheduleApprovalRoutes = []struct {
	method string
	public string
}{
	{http.MethodPost, "/api/v1/schedules/approve"},
	{http.MethodPost, "/api/v1/schedules/012345abcdef/renew/approve"},
}

func TestScheduleRoutesRequireSeparateExplicitOptIn(t *testing.T) {
	// Starting the local runner is not permission to expose standing-grant
	// administration to every paired device. Only the exact backend flag value
	// "1" registers the routes.
	t.Setenv("KALIV_SCHEDULER", "1")
	hits := 0
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits++
	}))
	defer worker.Close()

	for _, flag := range []string{"", "0", "false", "true", "on", "garbage"} {
		t.Run("flag="+flag, func(t *testing.T) {
			h, _ := scheduleHandlerWithFlag(t, worker.URL, 2*time.Second, flag)
			req := httptest.NewRequest(http.MethodGet, "/api/v1/schedules/status", nil)
			req.Header.Set("Authorization", "Bearer "+scheduleToken)
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, req)
			if rec.Code != http.StatusNotFound {
				t.Fatalf("KALIV_SCHEDULER_API=%q: got %d, want 404", flag, rec.Code)
			}
		})
	}
	if hits != 0 {
		t.Fatalf("disabled schedule API reached worker %d time(s)", hits)
	}
}

func TestScheduleRoutesRequireBearerBeforeWorker(t *testing.T) {
	hits := []scheduleHit{}
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits = append(hits, scheduleHit{Path: r.URL.Path})
		writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
	}))
	defer worker.Close()

	h, _ := scheduleHandler(t, worker.URL, 2*time.Second)
	for _, route := range scheduleRoutes {
		t.Run(route.method+" "+route.public, func(t *testing.T) {
			for _, header := range []string{"", "Bearer", "Basic nope", "Bearer wrong"} {
				req := httptest.NewRequest(route.method, route.public, strings.NewReader(`{"x":1}`))
				if header != "" {
					req.Header.Set("Authorization", header)
				}
				rec := httptest.NewRecorder()
				h.ServeHTTP(rec, req)
				if rec.Code != http.StatusUnauthorized {
					t.Fatalf("auth %q: got %d, want 401", header, rec.Code)
				}
			}
		})
	}
	for _, route := range scheduleApprovalRoutes {
		t.Run(route.method+" "+route.public, func(t *testing.T) {
			for _, header := range []string{"", "Bearer", "Basic nope", "Bearer wrong"} {
				req := httptest.NewRequest(route.method, route.public, strings.NewReader(`{"x":1}`))
				if header != "" {
					req.Header.Set("Authorization", header)
				}
				rec := httptest.NewRecorder()
				h.ServeHTTP(rec, req)
				if rec.Code != http.StatusUnauthorized {
					t.Fatalf("auth %q: got %d, want 401", header, rec.Code)
				}
			}
		})
	}
	if len(hits) != 0 {
		t.Fatalf("unauthenticated schedule requests reached worker: %+v", hits)
	}
}

func TestScheduleRoutesProxyExactContractToLoopbackWorkerOnly(t *testing.T) {
	hits := []scheduleHit{}
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		host, _, _ := net.SplitHostPort(r.RemoteAddr)
		hits = append(hits, scheduleHit{
			Method:        r.Method,
			Path:          r.URL.Path,
			Query:         r.URL.RawQuery,
			Body:          string(body),
			RequestID:     r.Header.Get("X-Request-ID"),
			Authorization: r.Header.Get("Authorization"),
			RemoteHost:    host,
		})
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"upstream":"worker"}`))
	}))
	defer worker.Close()

	h, ollamaHits := scheduleHandler(t, worker.URL, 2*time.Second)
	for i, route := range scheduleRoutes {
		body := `{"route":` + string(rune('0'+i)) + `}`
		requestURL := route.public + "?case=" + string(rune('0'+i))
		req := httptest.NewRequest(route.method, requestURL, strings.NewReader(body))
		req.Header.Set("Authorization", "Bearer "+scheduleToken)
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-Request-ID", "schedule-case-"+string(rune('0'+i)))
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)

		if rec.Code != http.StatusOK {
			t.Fatalf("%s %s: got %d body=%s", route.method, route.public, rec.Code, rec.Body.String())
		}
		var out map[string]string
		if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil || out["upstream"] != "worker" {
			t.Fatalf("%s: response did not come from worker: %s", route.public, rec.Body.String())
		}
	}

	if len(hits) != len(scheduleRoutes) {
		t.Fatalf("worker saw %d requests, want %d: %+v", len(hits), len(scheduleRoutes), hits)
	}
	for i, route := range scheduleRoutes {
		hit := hits[i]
		if hit.Method != route.method || hit.Path != route.worker {
			t.Errorf("%s: worker got %s %s, want %s %s", route.public, hit.Method, hit.Path, route.method, route.worker)
		}
		wantCase := string(rune('0' + i))
		if hit.Query != "case="+wantCase {
			t.Errorf("%s: query %q, want case=%s", route.public, hit.Query, wantCase)
		}
		if hit.Body != `{"route":`+wantCase+`}` {
			t.Errorf("%s: body %q", route.public, hit.Body)
		}
		if hit.RequestID != "schedule-case-"+wantCase {
			t.Errorf("%s: request id %q", route.public, hit.RequestID)
		}
		if hit.Authorization != "" {
			t.Errorf("%s: backend leaked device bearer token to worker", route.public)
		}
		ip := net.ParseIP(hit.RemoteHost)
		if ip == nil || !ip.IsLoopback() {
			t.Errorf("%s: worker caller was %q, want loopback", route.public, hit.RemoteHost)
		}
	}
	if len(*ollamaHits) != 0 {
		t.Fatalf("schedule administration reached Ollama: %v", *ollamaHits)
	}
}

func TestScheduleProxyPreservesWorkerRefusal(t *testing.T) {
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusConflict)
		_, _ = w.Write([]byte(`{"detail":"standing grant changed"}`))
	}))
	defer worker.Close()

	h, _ := scheduleHandler(t, worker.URL, 2*time.Second)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/schedules", strings.NewReader(`{}`))
	req.Header.Set("Authorization", "Bearer "+scheduleToken)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusConflict || !strings.Contains(rec.Body.String(), "standing grant changed") {
		t.Fatalf("worker refusal changed: status=%d body=%s", rec.Code, rec.Body.String())
	}
}

func TestScheduleProxyRejectsBadIDsBeforeWorker(t *testing.T) {
	hits := 0
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits++
	}))
	defer worker.Close()

	h, _ := scheduleHandler(t, worker.URL, 2*time.Second)
	for _, path := range []string{
		"/api/v1/schedules/too-short",
		"/api/v1/schedules/ABCDEF012345",
		"/api/v1/schedules/012345abcdeg/enabled",
	} {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		if strings.HasSuffix(path, "/enabled") {
			req = httptest.NewRequest(http.MethodPost, path, strings.NewReader(`{}`))
		}
		req.Header.Set("Authorization", "Bearer "+scheduleToken)
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusBadRequest {
			t.Errorf("%s: got %d, want 400", path, rec.Code)
		}
	}
	if hits != 0 {
		t.Fatalf("invalid IDs reached worker %d time(s)", hits)
	}
}

func TestScheduleProxyFailsClosedForNonLoopbackWorker(t *testing.T) {
	h, ollamaHits := scheduleHandler(t, "http://192.0.2.10:8099", 20*time.Millisecond)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/schedules/preview", strings.NewReader(`{"tool":"current_datetime"}`))
	req.Header.Set("Authorization", "Bearer "+scheduleToken)
	rec := httptest.NewRecorder()
	start := time.Now()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("got %d body=%s, want 503", rec.Code, rec.Body.String())
	}
	if time.Since(start) > time.Second {
		t.Fatal("non-loopback refusal attempted a network request instead of failing locally")
	}
	if len(*ollamaHits) != 0 {
		t.Fatalf("failed schedule proxy fell back to Ollama: %v", *ollamaHits)
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

func TestScheduleApprovalIsExplicitSignedAndBoundToWorkerPreview(t *testing.T) {
	seed := []byte("0123456789abcdef0123456789abcdef")
	privateKey := ed25519.NewKeyFromSeed(seed)
	t.Setenv("KALIV_SCHEDULER_APPROVAL_PRIVATE_KEY", base64.StdEncoding.EncodeToString(seed))
	binding := strings.Repeat("a", 64)
	var got scheduleHit
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		got = scheduleHit{
			Method: r.Method, Path: r.URL.Path, Body: string(body),
			RequestID:     r.Header.Get("X-Request-ID"),
			Authorization: r.Header.Get("Authorization"),
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"preview":{"requires_approval":true,"approval_binding":"` + binding + `","tool":"append_note"},"executed":false}`))
	}))
	defer worker.Close()

	h, _ := scheduleHandler(t, worker.URL, 2*time.Second)
	body := `{"tool":"append_note","args":{"text":"brew"},"cadence":"daily:03:00"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/schedules/approve", strings.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+scheduleToken)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Request-ID", "approve-1")
	rec := httptest.NewRecorder()
	before := time.Now().Unix()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("approval: got %d body=%s", rec.Code, rec.Body.String())
	}
	if got.Method != http.MethodPost || got.Path != "/schedules/preview" || got.Body != body {
		t.Fatalf("worker preview contract changed: %+v", got)
	}
	if got.Authorization != "" {
		t.Fatal("backend leaked the paired-device bearer token to the worker")
	}
	if got.RequestID != "approve-1" {
		t.Fatalf("request id did not survive: %q", got.RequestID)
	}
	var document map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &document); err != nil {
		t.Fatal(err)
	}
	preview := document["preview"].(map[string]any)
	token, _ := preview["approval_token"].(string)
	parts := strings.Split(token, ".")
	if len(parts) != 3 || parts[0] != scheduleApprovalTokenPrefix {
		t.Fatalf("bad token shape: %q", token)
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		t.Fatal(err)
	}
	signature, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil {
		t.Fatal(err)
	}
	if !ed25519.Verify(privateKey.Public().(ed25519.PublicKey), payload, signature) {
		t.Fatal("approval token was not signed by the configured backend key")
	}
	var claims scheduleApprovalClaims
	if err := json.Unmarshal(payload, &claims); err != nil {
		t.Fatal(err)
	}
	if claims.Binding != binding || claims.Audience != scheduleApprovalAudience || claims.Version != 1 {
		t.Fatalf("token is not bound to the worker preview: %+v", claims)
	}
	if claims.Expires < before+290 || claims.Expires > before+310 || claims.Nonce == "" {
		t.Fatalf("token is not short-lived/unique: %+v", claims)
	}
	if gotExp := int64(preview["approval_token_expires_at"].(float64)); gotExp != claims.Expires {
		t.Fatalf("visible expiry %d != signed expiry %d", gotExp, claims.Expires)
	}
}

func TestScheduleRenewApprovalRevalidatesTheExactExistingGrant(t *testing.T) {
	seed := []byte("abcdef0123456789abcdef0123456789")
	t.Setenv("KALIV_SCHEDULER_APPROVAL_PRIVATE_KEY", base64.StdEncoding.EncodeToString(seed))
	binding := strings.Repeat("b", 64)
	seen := ""
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = r.URL.Path
		_, _ = w.Write([]byte(`{"preview":{"requires_approval":true,"approval_binding":"` + binding + `"}}`))
	}))
	defer worker.Close()
	h, _ := scheduleHandler(t, worker.URL, 2*time.Second)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/schedules/012345abcdef/renew/approve", strings.NewReader(`{"ttl_days":30,"max_runs":5}`))
	req.Header.Set("Authorization", "Bearer "+scheduleToken)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK || seen != "/schedules/012345abcdef/renew/preview" {
		t.Fatalf("renew approval: status=%d path=%q body=%s", rec.Code, seen, rec.Body.String())
	}
}

func TestScheduleApprovalFailsClosedWithoutAValidBackendKey(t *testing.T) {
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"preview":{"requires_approval":true,"approval_binding":"` + strings.Repeat("c", 64) + `"}}`))
	}))
	defer worker.Close()
	for _, key := range []string{"", "not-base64", base64.StdEncoding.EncodeToString([]byte("too short"))} {
		t.Run(key, func(t *testing.T) {
			t.Setenv("KALIV_SCHEDULER_APPROVAL_PRIVATE_KEY", key)
			h, _ := scheduleHandler(t, worker.URL, 2*time.Second)
			req := httptest.NewRequest(http.MethodPost, "/api/v1/schedules/approve", strings.NewReader(`{}`))
			req.Header.Set("Authorization", "Bearer "+scheduleToken)
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, req)
			if rec.Code != http.StatusServiceUnavailable {
				t.Fatalf("key %q: got %d body=%s, want 503", key, rec.Code, rec.Body.String())
			}
		})
	}
}

func TestScheduleApprovalDoesNotMintTokensForReads(t *testing.T) {
	seed := []byte("0123456789abcdef0123456789abcdef")
	t.Setenv("KALIV_SCHEDULER_APPROVAL_PRIVATE_KEY", base64.StdEncoding.EncodeToString(seed))
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"preview":{"requires_approval":false,"tool":"read_clock"}}`))
	}))
	defer worker.Close()
	h, _ := scheduleHandler(t, worker.URL, 2*time.Second)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/schedules/approve", strings.NewReader(`{}`))
	req.Header.Set("Authorization", "Bearer "+scheduleToken)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnprocessableEntity || strings.Contains(rec.Body.String(), "approval_token") {
		t.Fatalf("read approval minted capability: status=%d body=%s", rec.Code, rec.Body.String())
	}
}
