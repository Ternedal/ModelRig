package httpapi

import (
	"io"
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
	mediaJobsTestToken  = "media-jobs-test-token"
	mediaJobsTestSecret = "0123456789abcdef0123456789abcdef-secret"
	mediaJobsTestID     = "0123456789abcdef0123456789abcdef"
)

type mediaJobsHit struct {
	Method, Path, RawQuery, Body, Secret, Owner, ContentType string
}

func mediaJobsHandler(t *testing.T, workerURL, flag, secret string) http.Handler {
	t.Helper()
	t.Setenv("KALIV_MEDIA_JOBS_API", flag)
	t.Setenv("KALIV_MEDIA_INTERNAL_SECRET", secret)
	st, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	if err := st.AddDevice(store.Device{
		ID: "media-jobs-device", Name: "phone",
		TokenHash: auth.Hash(mediaJobsTestToken), CreatedAt: time.Now(), LastSeen: time.Now(),
	}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}
	worker := proxy.New(workerURL, 2*time.Second)
	return New(Deps{
		Cfg:   config.Config{ClaimMax: 5, RequestTimeout: 2 * time.Second},
		Store: st, Ollama: worker, Worker: worker, WorkerSlow: worker,
	})
}

func mediaJobsWorker(t *testing.T, hits *[]mediaJobsHit) *httptest.Server {
	t.Helper()
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		*hits = append(*hits, mediaJobsHit{r.Method, r.URL.Path, r.URL.RawQuery, string(body),
			r.Header.Get("X-Internal-Media-Secret"), r.Header.Get("X-Verified-Owner"), r.Header.Get("Content-Type")})
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "public, max-age=3600") // must never reach the device
		w.WriteHeader(http.StatusAccepted)
		_, _ = io.WriteString(w, `{"id":"`+mediaJobsTestID+`","state":"queued"}`)
	}))
	t.Cleanup(worker.Close)
	return worker
}

func doMediaJobs(h http.Handler, method, path, token, body string, header map[string]string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	for k, v := range header {
		req.Header.Set(k, v)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func TestMediaJobRoutesAreOffUnlessTheSwitchIsExactlyOne(t *testing.T) {
	var hits []mediaJobsHit
	worker := mediaJobsWorker(t, &hits)
	for _, flag := range []string{"", "0", "true", "on", " 1"} {
		h := mediaJobsHandler(t, worker.URL, flag, mediaJobsTestSecret)
		rec := doMediaJobs(h, http.MethodPost, "/api/v1/media/jobs", mediaJobsTestToken, `{"profile_id":"sdxl-a","prompt":"x"}`, nil)
		if rec.Code != http.StatusNotFound && rec.Code != http.StatusMethodNotAllowed {
			t.Fatalf("flag %q: %d, want the route to be absent", flag, rec.Code)
		}
	}
	if len(hits) != 0 {
		t.Fatalf("a disabled route reached the worker: %+v", hits)
	}
}

func TestMediaJobRoutesRequireTheBearerAndNeverCache(t *testing.T) {
	var hits []mediaJobsHit
	h := mediaJobsHandler(t, mediaJobsWorker(t, &hits).URL, "1", mediaJobsTestSecret)
	for _, tc := range []struct{ method, path, body string }{
		{http.MethodPost, "/api/v1/media/jobs", `{"profile_id":"sdxl-a","prompt":"x"}`},
		{http.MethodGet, "/api/v1/media/jobs/" + mediaJobsTestID, ""},
		{http.MethodPost, "/api/v1/media/jobs/" + mediaJobsTestID + "/cancel", ""},
	} {
		for _, token := range []string{"", "wrong-token"} {
			rec := doMediaJobs(h, tc.method, tc.path, token, tc.body, nil)
			if rec.Code != http.StatusUnauthorized {
				t.Fatalf("%s %s token=%q: %d", tc.method, tc.path, token, rec.Code)
			}
			if rec.Header().Get("Cache-Control") != "private, no-store" {
				t.Fatalf("%s %s: 401 without no-store", tc.method, tc.path)
			}
		}
	}
	if len(hits) != 0 {
		t.Fatalf("an unauthenticated request reached the worker: %+v", hits)
	}
}

func TestMediaJobRoutesForwardWithTheSecretOnlyAndNoOwnerClaim(t *testing.T) {
	var hits []mediaJobsHit
	h := mediaJobsHandler(t, mediaJobsWorker(t, &hits).URL, "1", mediaJobsTestSecret)
	spoof := map[string]string{"X-Verified-Owner": "someone-else", "X-Internal-Media-Secret": "client-guess"}
	body := `{"profile_id":"sdxl-a","prompt":"a red bicycle"}`
	for _, tc := range []struct{ method, path, body, upstream string }{
		{http.MethodPost, "/api/v1/media/jobs?owner=x", body, "/internal/media/jobs"},
		{http.MethodPost, "/api/v1/media/jobs", body, "/internal/media/jobs"}, // with an explicit utf-8 charset below
		{http.MethodGet, "/api/v1/media/jobs/" + mediaJobsTestID + "?x=1", "", "/internal/media/jobs/" + mediaJobsTestID},
		{http.MethodPost, "/api/v1/media/jobs/" + mediaJobsTestID + "/cancel", "", "/internal/media/jobs/" + mediaJobsTestID + "/cancel"},
	} {
		hits = hits[:0]
		headers := spoof
		if tc.path == "/api/v1/media/jobs" {
			headers = map[string]string{"Content-Type": "application/json; charset=UTF-8"}
		}
		rec := doMediaJobs(h, tc.method, tc.path, mediaJobsTestToken, tc.body, headers)
		if rec.Code != http.StatusAccepted {
			t.Fatalf("%s %s: %d %s", tc.method, tc.path, rec.Code, rec.Body.String())
		}
		if len(hits) != 1 {
			t.Fatalf("%s %s: %d worker hits", tc.method, tc.path, len(hits))
		}
		hit := hits[0]
		if hit.Method != tc.method || hit.Path != tc.upstream || hit.RawQuery != "" || hit.Body != tc.body {
			t.Fatalf("%s %s forwarded as %+v", tc.method, tc.path, hit)
		}
		if hit.Secret != mediaJobsTestSecret || hit.Owner != "" {
			t.Fatalf("headers reaching the worker: secret=%q owner=%q", hit.Secret, hit.Owner)
		}
		if rec.Header().Get("Cache-Control") != "private, no-store" {
			t.Fatalf("%s %s: Cache-Control %q", tc.method, tc.path, rec.Header().Get("Cache-Control"))
		}
		if strings.Contains(rec.Body.String(), mediaJobsTestSecret) {
			t.Fatal("the internal secret reached the device")
		}
	}
}

func TestMediaJobRoutesFailClosedWithoutASecretOrALoopbackWorker(t *testing.T) {
	var hits []mediaJobsHit
	worker := mediaJobsWorker(t, &hits)
	for _, secret := range []string{"", "short", strings.Repeat("s", 31), strings.Repeat("s", 40) + "\n"} {
		h := mediaJobsHandler(t, worker.URL, "1", secret)
		rec := doMediaJobs(h, http.MethodGet, "/api/v1/media/jobs/"+mediaJobsTestID, mediaJobsTestToken, "", nil)
		if rec.Code != http.StatusServiceUnavailable {
			t.Fatalf("secret %q: %d", secret, rec.Code)
		}
	}
	h := mediaJobsHandler(t, "http://192.0.2.10:8090", "1", mediaJobsTestSecret)
	rec := doMediaJobs(h, http.MethodGet, "/api/v1/media/jobs/"+mediaJobsTestID, mediaJobsTestToken, "", nil)
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("non-loopback worker: %d", rec.Code)
	}
	if len(hits) != 0 {
		t.Fatalf("reached the worker: %+v", hits)
	}
}

func TestMediaJobRoutesRefuseBadIDsAndBodiesBeforeTheWorker(t *testing.T) {
	var hits []mediaJobsHit
	h := mediaJobsHandler(t, mediaJobsWorker(t, &hits).URL, "1", mediaJobsTestSecret)
	for _, id := range []string{"0123456789ABCDEF0123456789ABCDEF", "abc", mediaJobsTestID + "0", "..%2f" + mediaJobsTestID[5:]} {
		rec := doMediaJobs(h, http.MethodGet, "/api/v1/media/jobs/"+id, mediaJobsTestToken, "", nil)
		if rec.Code != http.StatusNotFound {
			t.Fatalf("id %q: %d", id, rec.Code)
		}
	}
	big := `{"profile_id":"sdxl-a","prompt":"` + strings.Repeat("x", mediaJobsMaxBody) + `"}`
	if rec := doMediaJobs(h, http.MethodPost, "/api/v1/media/jobs", mediaJobsTestToken, big, nil); rec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("oversized body: %d", rec.Code)
	}
	// Chunked (unknown length) and over the cap: refused whole, the worker never sees a part.
	chunked := httptest.NewRequest(http.MethodPost, "/api/v1/media/jobs", io.MultiReader(strings.NewReader(big)))
	chunked.ContentLength = -1
	chunked.Header.Set("Authorization", "Bearer "+mediaJobsTestToken)
	chunked.Header.Set("Content-Type", "application/json")
	chunkedRec := httptest.NewRecorder()
	h.ServeHTTP(chunkedRec, chunked)
	if chunkedRec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("chunked oversized body: %d", chunkedRec.Code)
	}
	for _, ct := range []string{"application/jsonp", "application/jsonanything", "application/json; charset=latin-1",
		"application/json; boundary=x", "text/json", ""} {
		r := httptest.NewRequest(http.MethodPost, "/api/v1/media/jobs", strings.NewReader(`{"profile_id":"sdxl-a","prompt":"x"}`))
		r.Header.Set("Authorization", "Bearer "+mediaJobsTestToken)
		if ct != "" {
			r.Header.Set("Content-Type", ct)
		}
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, r)
		if rec.Code != http.StatusUnsupportedMediaType {
			t.Fatalf("Content-Type %q: %d", ct, rec.Code)
		}
	}
	req := httptest.NewRequest(http.MethodPost, "/api/v1/media/jobs", strings.NewReader("prompt=x"))
	req.Header.Set("Authorization", "Bearer "+mediaJobsTestToken)
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnsupportedMediaType {
		t.Fatalf("form body: %d", rec.Code)
	}
	if len(hits) != 0 {
		t.Fatalf("reached the worker: %+v", hits)
	}
}

func TestMediaJobProfilesRouteRequiresBearerAndIsDefaultOff(t *testing.T) {
	var hits []mediaJobsHit
	worker := mediaJobsWorker(t, &hits)
	off := mediaJobsHandler(t, worker.URL, "0", mediaJobsTestSecret)
	rec := doMediaJobs(off, http.MethodGet, "/api/v1/media/jobs/profiles", mediaJobsTestToken, "", nil)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("disabled profile route: %d", rec.Code)
	}
	on := mediaJobsHandler(t, worker.URL, "1", mediaJobsTestSecret)
	for _, token := range []string{"", "wrong-token"} {
		rec = doMediaJobs(on, http.MethodGet, "/api/v1/media/jobs/profiles", token, "", nil)
		if rec.Code != http.StatusUnauthorized || rec.Header().Get("Cache-Control") != "private, no-store" {
			t.Fatalf("unauthorized profile route: %d, cache=%q", rec.Code, rec.Header().Get("Cache-Control"))
		}
	}
	if len(hits) != 0 {
		t.Fatalf("profile route forwarded without authentication: %+v", hits)
	}
	rec = doMediaJobs(on, http.MethodGet, "/api/v1/media/jobs/profiles?owner=spoof", mediaJobsTestToken, "", nil)
	if rec.Code != http.StatusAccepted || len(hits) != 1 {
		t.Fatalf("profile route: status=%d hits=%d", rec.Code, len(hits))
	}
	hit := hits[0]
	if hit.Method != http.MethodGet || hit.Path != "/internal/media/jobs/profiles" || hit.RawQuery != "" ||
		hit.Secret != mediaJobsTestSecret || hit.Owner != "" {
		t.Fatalf("profile forwarding boundary: %+v", hit)
	}
	if rec.Header().Get("Cache-Control") != "private, no-store" {
		t.Fatalf("profile route cache=%q", rec.Header().Get("Cache-Control"))
	}
}

func TestMediaJobWorkerAuthFailuresDoNotMasqueradeAsDevicePairingFailures(t *testing.T) {
	for _, status := range []int{http.StatusUnauthorized, http.StatusForbidden} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(status)
				_, _ = io.WriteString(w, `{"detail":"internal secret rejected"}`)
			}))
			defer worker.Close()
			h := mediaJobsHandler(t, worker.URL, "1", mediaJobsTestSecret)
			rec := doMediaJobs(h, http.MethodGet, "/api/v1/media/jobs/"+mediaJobsTestID, mediaJobsTestToken, "", nil)
			if rec.Code != http.StatusServiceUnavailable {
				t.Fatalf("worker status %d leaked as %d", status, rec.Code)
			}
			if strings.Contains(rec.Body.String(), "internal secret") || strings.Contains(rec.Body.String(), "rejected") {
				t.Fatalf("internal worker error body leaked: %s", rec.Body.String())
			}
			if rec.Header().Get("Cache-Control") != "private, no-store" {
				t.Fatalf("no-store missing: %q", rec.Header().Get("Cache-Control"))
			}
			unauthenticated := doMediaJobs(h, http.MethodGet, "/api/v1/media/jobs/"+mediaJobsTestID, "", "", nil)
			if unauthenticated.Code != http.StatusUnauthorized {
				t.Fatalf("device Bearer 401 was changed: %d", unauthenticated.Code)
			}
		})
	}
}

func TestMediaJobWorkerOutageDoesNotLeakLoopbackURL(t *testing.T) {
	// A refused loopback connection makes the generic proxy include its target
	// URL in the 502 body. The paired-device media boundary must redact it.
	workerURL := "http://127.0.0.1:1"
	h := mediaJobsHandler(t, workerURL, "1", mediaJobsTestSecret)
	rec := doMediaJobs(h, http.MethodGet, "/api/v1/media/jobs/"+mediaJobsTestID, mediaJobsTestToken, "", nil)
	if rec.Code != http.StatusBadGateway {
		t.Fatalf("worker outage: status=%d body=%q", rec.Code, rec.Body.String())
	}
	if strings.Contains(rec.Body.String(), workerURL) || strings.Contains(rec.Body.String(), "/internal/media/jobs") {
		t.Fatalf("worker internal URL leaked: %q", rec.Body.String())
	}
	if rec.Body.String() != "media jobs unavailable\n" {
		t.Fatalf("unexpected device error: %q", rec.Body.String())
	}
	if rec.Header().Get("Cache-Control") != "private, no-store" {
		t.Fatalf("outage response cache=%q", rec.Header().Get("Cache-Control"))
	}
}


func TestMediaJobUpstreamBadGatewayBodyIsRedacted(t *testing.T) {
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)
		_, _ = io.WriteString(w, "{\"detail\":\"http://127.0.0.1:8099/internal/media/jobs/secret\"}")
	}))
	defer worker.Close()
	h := mediaJobsHandler(t, worker.URL, "1", mediaJobsTestSecret)
	rec := doMediaJobs(h, http.MethodGet, "/api/v1/media/jobs/"+mediaJobsTestID, mediaJobsTestToken, "", nil)
	if rec.Code != http.StatusBadGateway || rec.Body.String() != "media jobs unavailable\n" {
		t.Fatalf("upstream 502 leaked or changed: status=%d body=%q", rec.Code, rec.Body.String())
	}
	if got := rec.Header().Get("Cache-Control"); got != "private, no-store" {
		t.Fatalf("upstream 502 cache=%q", got)
	}
}
