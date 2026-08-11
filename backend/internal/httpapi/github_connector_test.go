package httpapi

import (
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

const githubConnectorTestToken = "github-connector-test-token"

type githubConnectorHit struct {
	Method        string
	Path          string
	RawQuery      string
	Body          string
	RequestID     string
	Authorization string
	RemoteHost    string
}

func githubConnectorHandler(t *testing.T, workerURL, flag string) http.Handler {
	t.Helper()
	t.Setenv("KALIV_GITHUB_CONNECTOR_PILOT", flag)
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusTeapot)
	}))
	t.Cleanup(ollama.Close)
	st, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	if err := st.AddDevice(store.Device{
		ID: "github-connector-device", Name: "phone",
		TokenHash: auth.Hash(githubConnectorTestToken), CreatedAt: time.Now(), LastSeen: time.Now(),
	}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}
	worker := proxy.New(workerURL, 2*time.Second)
	return New(Deps{
		Cfg: config.Config{ClaimMax: 5, RequestTimeout: 2 * time.Second},
		Store: st, Ollama: proxy.New(ollama.URL, 2*time.Second),
		Worker: worker, WorkerSlow: worker,
	})
}

func doGitHubConnectorRequest(h http.Handler, method, path, token, body string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	req.Header.Set("X-Request-ID", "github-connector-request")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func TestGitHubConnectorRoutesAreDefaultOffAndUseWorkerFlagSemantics(t *testing.T) {
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Fatal("disabled GitHub connector API reached worker")
	}))
	defer worker.Close()

	for _, flag := range []string{"", "0", "false", "off", "garbage"} {
		t.Run("disabled="+flag, func(t *testing.T) {
			h := githubConnectorHandler(t, worker.URL, flag)
			rec := doGitHubConnectorRequest(h, http.MethodGet, "/api/v1/github-connector/grants", githubConnectorTestToken, "")
			if rec.Code != http.StatusNotFound {
				t.Fatalf("flag=%q: got %d, want 404", flag, rec.Code)
			}
		})
	}

	for _, flag := range []string{"1", "true", "TRUE", "on", " On "} {
		t.Run("enabled="+strings.TrimSpace(flag), func(t *testing.T) {
			hits := 0
			local := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				hits++
				w.Header().Set("Content-Type", "application/json")
				_, _ = io.WriteString(w, `{"connector":"github","production_activation":false}`)
			}))
			defer local.Close()
			h := githubConnectorHandler(t, local.URL, flag)
			rec := doGitHubConnectorRequest(h, http.MethodGet, "/api/v1/github-connector/grants", githubConnectorTestToken, "")
			if rec.Code != http.StatusOK || hits != 1 {
				t.Fatalf("flag=%q: code=%d hits=%d body=%s", flag, rec.Code, hits, rec.Body.String())
			}
		})
	}
}

func TestAllGitHubConnectorRoutesRequireBearerBeforeWorker(t *testing.T) {
	hits := 0
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits++
	}))
	defer worker.Close()
	h := githubConnectorHandler(t, worker.URL, "1")
	validID := "ghg_0123456789abcdef0123456789abcdef"
	routes := []struct{ method, path string }{
		{http.MethodGet, "/api/v1/github-connector/grants"},
		{http.MethodGet, "/api/v1/github-connector/audit"},
		{http.MethodPost, "/api/v1/github-connector/grants/preview"},
		{http.MethodPost, "/api/v1/github-connector/grants"},
		{http.MethodPost, "/api/v1/github-connector/grants/" + validID + "/revoke"},
	}
	for _, route := range routes {
		for _, token := range []string{"", "wrong"} {
			rec := doGitHubConnectorRequest(h, route.method, route.path, token, `{}`)
			if rec.Code != http.StatusUnauthorized {
				t.Fatalf("%s %s token=%q: got %d", route.method, route.path, token, rec.Code)
			}
		}
	}
	if hits != 0 {
		t.Fatalf("unauthenticated GitHub connector requests reached worker %d time(s)", hits)
	}
}

func TestGitHubConnectorProxyPreservesExactRoutesQueryAndBodyWithoutBearerLeak(t *testing.T) {
	var hits []githubConnectorHit
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		host, _, _ := net.SplitHostPort(r.RemoteAddr)
		hits = append(hits, githubConnectorHit{
			Method: r.Method, Path: r.URL.Path, RawQuery: r.URL.RawQuery, Body: string(body),
			RequestID: r.Header.Get("X-Request-ID"), Authorization: r.Header.Get("Authorization"), RemoteHost: host,
		})
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, `{"connector":"github","production_activation":false}`)
	}))
	defer worker.Close()
	h := githubConnectorHandler(t, worker.URL, "on")
	grantID := "ghg_0123456789abcdef0123456789abcdef"
	requests := []struct{ method, path, body, wantPath, wantQuery string }{
		{http.MethodGet, "/api/v1/github-connector/audit?repository=ternedal%2Fmodelrig&operation=issue&limit=10", "", "/github-connector/audit", "repository=ternedal%2Fmodelrig&operation=issue&limit=10"},
		{http.MethodGet, "/api/v1/github-connector/grants?include_revoked=true", "", "/github-connector/grants", "include_revoked=true"},
		{http.MethodPost, "/api/v1/github-connector/grants/preview", `{"repositories":["Ternedal/ModelRig"],"operations":["issue"]}`, "/github-connector/grants/preview", ""},
		{http.MethodPost, "/api/v1/github-connector/grants", `{"repositories":["Ternedal/ModelRig"],"operations":["issue"],"expected_scope_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}`, "/github-connector/grants", ""},
		{http.MethodPost, "/api/v1/github-connector/grants/" + grantID + "/revoke", `{"expected_scope_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","confirm_revoke":true}`, "/github-connector/grants/" + grantID + "/revoke", ""},
	}
	for i, tc := range requests {
		rec := doGitHubConnectorRequest(h, tc.method, tc.path, githubConnectorTestToken, tc.body)
		if rec.Code != http.StatusOK {
			t.Fatalf("request %d: %d %s", i, rec.Code, rec.Body.String())
		}
		hit := hits[i]
		if hit.Method != tc.method || hit.Path != tc.wantPath || hit.RawQuery != tc.wantQuery || hit.Body != tc.body {
			t.Fatalf("request %d mismatch: %+v", i, hit)
		}
		if hit.Authorization != "" {
			t.Fatalf("paired-device bearer leaked to worker on %s", hit.Path)
		}
		if hit.RequestID != "github-connector-request" {
			t.Fatalf("request id not propagated: %+v", hit)
		}
		if ip := net.ParseIP(hit.RemoteHost); ip == nil || !ip.IsLoopback() {
			t.Fatalf("worker caller was %q, want loopback", hit.RemoteHost)
		}
	}
}

func TestGitHubConnectorRefusesNonLoopbackWorkerBeforeForwardingBody(t *testing.T) {
	for _, workerURL := range []string{
		"http://192.0.2.1:9000", "http://10.0.0.8:9000", "https://example.com", "file:///tmp/worker", "not-a-url",
	} {
		t.Run(workerURL, func(t *testing.T) {
			h := githubConnectorHandler(t, workerURL, "1")
			rec := doGitHubConnectorRequest(h, http.MethodPost, "/api/v1/github-connector/grants/preview", githubConnectorTestToken,
				`{"repositories":["Ternedal/ModelRig"],"operations":["issue"]}`)
			if rec.Code != http.StatusServiceUnavailable || !strings.Contains(rec.Body.String(), "loopback worker") {
				t.Fatalf("worker=%q: %d %s", workerURL, rec.Code, rec.Body.String())
			}
		})
	}
}

func TestGitHubConnectorGrantIDValidationFailsBeforeWorker(t *testing.T) {
	hits := 0
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits++
	}))
	defer worker.Close()
	h := githubConnectorHandler(t, worker.URL, "1")

	// Go's ServeMux canonicalizes a double-slash path before route matching.
	// Empty ids therefore redirect rather than entering our revoke handler; the
	// security invariant is the same and is pinned explicitly: zero worker hits.
	empty := doGitHubConnectorRequest(
		h,
		http.MethodPost,
		"/api/v1/github-connector/grants//revoke",
		githubConnectorTestToken,
		`{}`,
	)
	if empty.Code != http.StatusMovedPermanently {
		t.Fatalf("empty id canonicalization: got %d, want 301", empty.Code)
	}

	for _, id := range []string{"ghg_short", "GHG_0123456789abcdef0123456789abcdef", "ghg_0123456789ABCDEF0123456789abcdef", "ghg_0123456789abcdef0123456789abcdeg"} {
		path := "/api/v1/github-connector/grants/" + id + "/revoke"
		rec := doGitHubConnectorRequest(h, http.MethodPost, path, githubConnectorTestToken, `{}`)
		if rec.Code != http.StatusBadRequest {
			t.Fatalf("id=%q: got %d body=%s", id, rec.Code, rec.Body.String())
		}
	}
	if hits != 0 {
		t.Fatalf("invalid grant ids reached worker %d time(s)", hits)
	}
}
