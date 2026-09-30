package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"modelrig/internal/auth"
	"modelrig/internal/config"
	"modelrig/internal/proxy"
	"modelrig/internal/store"
)

func validControlCenterPayload() string {
	return `{"schema":"kaliv-control-center-status/v1","overall":"healthy","green":true}`
}

func TestControlCenterStatusProxyStampsAndValidates(t *testing.T) {
	var calls atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.Method != http.MethodGet {
			t.Errorf("method = %s, want GET", r.Method)
		}
		if r.URL.Path != "/control-center/status" {
			t.Errorf("path = %q", r.URL.Path)
		}
		if r.URL.RawQuery != "" {
			t.Errorf("client query leaked upstream: %q", r.URL.RawQuery)
		}
		if got := r.Header.Get("X-Kaliv-Backend-Version"); got != config.Version {
			t.Errorf("backend version = %q, want %q", got, config.Version)
		}
		if got := r.Header.Get("X-Kaliv-Backend-Status"); got != "ok" {
			t.Errorf("backend status = %q, want ok", got)
		}
		observed, err := strconv.ParseFloat(r.Header.Get("X-Kaliv-Backend-Observed-At"), 64)
		if err != nil || time.Since(time.Unix(0, int64(observed*1e9))) > 5*time.Second {
			t.Errorf("invalid backend observation stamp %q", r.Header.Get("X-Kaliv-Backend-Observed-At"))
		}
		if got := r.Header.Get("X-Request-ID"); got != "req-control-center" {
			t.Errorf("request id = %q", got)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(validControlCenterPayload()))
	}))
	defer upstream.Close()

	s := &server{Deps: Deps{Worker: proxy.New(upstream.URL, time.Second)}}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/control-center/status?spoof=1", nil)
	req.Header.Set("X-Request-ID", "req-control-center")
	req.Header.Set("X-Kaliv-Backend-Version", "client-spoof")
	req.Header.Set("X-Kaliv-Backend-Status", "unavailable")
	req.Header.Set("X-Kaliv-Backend-Observed-At", "1")
	rec := httptest.NewRecorder()

	s.handleControlCenterStatus(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	if calls.Load() != 1 {
		t.Fatalf("worker calls = %d, want 1", calls.Load())
	}
	if got := rec.Header().Get("Cache-Control"); got != "no-store" {
		t.Errorf("Cache-Control = %q", got)
	}
	var payload map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &payload); err != nil {
		t.Fatalf("invalid response JSON: %v", err)
	}
	if payload["schema"] != controlCenterStatusSchema || payload["green"] != true {
		t.Fatalf("unexpected payload: %#v", payload)
	}
}

func TestControlCenterStatusProxyFailsClosed(t *testing.T) {
	tests := []struct {
		name   string
		status int
		body   string
		worker bool
	}{
		{name: "missing worker", worker: false},
		{name: "upstream error", worker: true, status: http.StatusInternalServerError, body: `secret worker failure`},
		{name: "malformed json", worker: true, status: http.StatusOK, body: `{not-json`},
		{name: "wrong schema", worker: true, status: http.StatusOK, body: `{"schema":"evil/v9","secret":"do not leak"}`},
		{name: "oversized", worker: true, status: http.StatusOK, body: strings.Repeat("x", maxControlCenterStatusBytes+1)},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			var upstream *httptest.Server
			s := &server{}
			if tc.worker {
				upstream = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
					w.WriteHeader(tc.status)
					_, _ = w.Write([]byte(tc.body))
				}))
				defer upstream.Close()
				s.Worker = proxy.New(upstream.URL, time.Second)
			}

			rec := httptest.NewRecorder()
			s.handleControlCenterStatus(rec, httptest.NewRequest(http.MethodGet, "/", nil))
			if rec.Code != http.StatusBadGateway {
				t.Fatalf("status = %d, want 502; body=%s", rec.Code, rec.Body.String())
			}
			if got := rec.Body.String(); !strings.Contains(got, "control center status unavailable") {
				t.Fatalf("generic error missing: %s", got)
			} else if strings.Contains(got, "secret") || strings.Contains(got, "evil/v9") {
				t.Fatalf("upstream detail leaked: %s", got)
			}
		})
	}
}

func TestControlCenterRouteRequiresBearerToken(t *testing.T) {
	var workerCalls atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		workerCalls.Add(1)
		_, _ = w.Write([]byte(validControlCenterPayload()))
	}))
	defer upstream.Close()

	st, err := store.Open(t.TempDir() + "/devices.json")
	if err != nil {
		t.Fatal(err)
	}
	const token = "paired-control-center-token"
	if err := st.AddDevice(store.Device{
		ID:        "control-center-device",
		Name:      "test phone",
		TokenHash: auth.Hash(token),
		CreatedAt: time.Now(),
		LastSeen:  time.Now(),
	}); err != nil {
		t.Fatal(err)
	}

	handler := New(Deps{
		Cfg:    config.Default(),
		Store:  st,
		Worker: proxy.New(upstream.URL, time.Second),
	})

	unauthorized := httptest.NewRecorder()
	handler.ServeHTTP(unauthorized, httptest.NewRequest(http.MethodGet, "/api/v1/control-center/status", nil))
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("unauthorized status = %d", unauthorized.Code)
	}
	if workerCalls.Load() != 0 {
		t.Fatalf("worker contacted before auth: %d calls", workerCalls.Load())
	}

	authorizedReq := httptest.NewRequest(http.MethodGet, "/api/v1/control-center/status", nil)
	authorizedReq.Header.Set("Authorization", "Bearer "+token)
	authorized := httptest.NewRecorder()
	handler.ServeHTTP(authorized, authorizedReq)
	if authorized.Code != http.StatusOK {
		t.Fatalf("authorized status = %d, body=%s", authorized.Code, authorized.Body.String())
	}
	if workerCalls.Load() != 1 {
		t.Fatalf("worker calls after auth = %d, want 1", workerCalls.Load())
	}
}


func validVisionControlPayload(sourceID string, enabled bool) string {
	return `{"schema":"kaliv-control-center-vision-control/v1","source_id":"` +
		sourceID +
		`","enabled":` + strconv.FormatBool(enabled) +
		`,"sensor_state_revision":10,"desired_revision":8,"production_activation":false}`
}

func TestControlCenterVisionEnabledProxyIsBoundedAndValidated(t *testing.T) {
	var calls atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.Method != http.MethodPost {
			t.Errorf("method = %s, want POST", r.Method)
		}
		if got := r.URL.EscapedPath(); got != "/control-center/vision/camera%20one/enabled" {
			t.Errorf("escaped path = %q", got)
		}
		if r.URL.RawQuery != "" {
			t.Errorf("client query leaked upstream: %q", r.URL.RawQuery)
		}
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatalf("invalid upstream JSON: %v", err)
		}
		if len(body) != 2 || body["enabled"] != false || body["expected_state_revision"] != float64(9) {
			t.Fatalf("unexpected upstream body: %#v", body)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(validVisionControlPayload("camera one", false)))
	}))
	defer upstream.Close()

	s := &server{Deps: Deps{Worker: proxy.New(upstream.URL, time.Second)}}
	req := httptest.NewRequest(
		http.MethodPost,
		"/api/v1/control-center/vision/camera%20one/enabled?spoof=1",
		strings.NewReader(`{"enabled":false,"expected_state_revision":9}`),
	)
	req.SetPathValue("source_id", "camera one")
	rec := httptest.NewRecorder()

	s.handleControlCenterVisionEnabled(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body=%s", rec.Code, rec.Body.String())
	}
	if calls.Load() != 1 {
		t.Fatalf("worker calls = %d, want 1", calls.Load())
	}
	if got := rec.Header().Get("Cache-Control"); got != "no-store" {
		t.Errorf("Cache-Control = %q", got)
	}
	var payload map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &payload); err != nil {
		t.Fatalf("invalid response JSON: %v", err)
	}
	if payload["schema"] != controlCenterVisionControlSchema ||
		payload["source_id"] != "camera one" ||
		payload["enabled"] != false ||
		payload["production_activation"] != false {
		t.Fatalf("unexpected payload: %#v", payload)
	}
}

func TestControlCenterVisionEnabledRejectsInvalidAndConflict(t *testing.T) {
	t.Run("unknown field rejected before worker", func(t *testing.T) {
		var calls atomic.Int32
		upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			calls.Add(1)
			_, _ = w.Write([]byte(validVisionControlPayload("camera", true)))
		}))
		defer upstream.Close()

		s := &server{Deps: Deps{Worker: proxy.New(upstream.URL, time.Second)}}
		req := httptest.NewRequest(
			http.MethodPost,
			"/",
			strings.NewReader(`{"enabled":true,"expected_state_revision":3,"extra":1}`),
		)
		req.SetPathValue("source_id", "camera")
		rec := httptest.NewRecorder()
		s.handleControlCenterVisionEnabled(rec, req)
		if rec.Code != http.StatusBadRequest {
			t.Fatalf("status = %d, want 400", rec.Code)
		}
		if calls.Load() != 0 {
			t.Fatalf("worker called for invalid body: %d", calls.Load())
		}
	})

	t.Run("revision conflict preserved without detail leak", func(t *testing.T) {
		upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(http.StatusConflict)
			_, _ = w.Write([]byte("secret upstream revision detail"))
		}))
		defer upstream.Close()

		s := &server{Deps: Deps{Worker: proxy.New(upstream.URL, time.Second)}}
		req := httptest.NewRequest(
			http.MethodPost,
			"/",
			strings.NewReader(`{"enabled":true,"expected_state_revision":3}`),
		)
		req.SetPathValue("source_id", "camera")
		rec := httptest.NewRecorder()
		s.handleControlCenterVisionEnabled(rec, req)
		if rec.Code != http.StatusConflict {
			t.Fatalf("status = %d, want 409; body=%s", rec.Code, rec.Body.String())
		}
		if strings.Contains(rec.Body.String(), "secret") {
			t.Fatalf("upstream detail leaked: %s", rec.Body.String())
		}
	})
}

func TestVisionRigControlRouteIsOptInAndAuthenticated(t *testing.T) {
	st, err := store.Open(t.TempDir() + "/devices.json")
	if err != nil {
		t.Fatal(err)
	}
	const token = "paired-vision-control-token"
	if err := st.AddDevice(store.Device{
		ID:        "vision-control-device",
		Name:      "test phone",
		TokenHash: auth.Hash(token),
		CreatedAt: time.Now(),
		LastSeen:  time.Now(),
	}); err != nil {
		t.Fatal(err)
	}

	var workerCalls atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		workerCalls.Add(1)
		_, _ = w.Write([]byte(validVisionControlPayload("kaliv-android", true)))
	}))
	defer upstream.Close()

	t.Run("default off", func(t *testing.T) {
		t.Setenv(visionRigControlAPIFlag, "0")
		handler := New(Deps{
			Cfg:    config.Default(),
			Store:  st,
			Worker: proxy.New(upstream.URL, time.Second),
		})
		req := httptest.NewRequest(
			http.MethodPost,
			"/api/v1/control-center/vision/kaliv-android/enabled",
			strings.NewReader(`{"enabled":true,"expected_state_revision":1}`),
		)
		req.Header.Set("Authorization", "Bearer "+token)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusNotFound {
			t.Fatalf("status = %d, want 404", rec.Code)
		}
	})

	t.Run("enabled still requires bearer", func(t *testing.T) {
		t.Setenv(visionRigControlAPIFlag, "1")
		handler := New(Deps{
			Cfg:    config.Default(),
			Store:  st,
			Worker: proxy.New(upstream.URL, time.Second),
		})

		unauthorized := httptest.NewRecorder()
		handler.ServeHTTP(
			unauthorized,
			httptest.NewRequest(
				http.MethodPost,
				"/api/v1/control-center/vision/kaliv-android/enabled",
				strings.NewReader(`{"enabled":true,"expected_state_revision":1}`),
			),
		)
		if unauthorized.Code != http.StatusUnauthorized {
			t.Fatalf("unauthorized status = %d", unauthorized.Code)
		}

		req := httptest.NewRequest(
			http.MethodPost,
			"/api/v1/control-center/vision/kaliv-android/enabled",
			strings.NewReader(`{"enabled":true,"expected_state_revision":1}`),
		)
		req.Header.Set("Authorization", "Bearer "+token)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("authorized status = %d, body=%s", rec.Code, rec.Body.String())
		}
	})
}
