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


func TestControlCenterVisionProxyValidatesSchema(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/control-center/vision" {
			t.Fatalf("path = %q", r.URL.Path)
		}
		_, _ = w.Write([]byte(`{"schema":"kaliv-control-center-vision/v1","available":true,"sensors":[],"production_activation":false}`))
	}))
	defer upstream.Close()

	s := &server{Deps: Deps{Worker: proxy.New(upstream.URL, time.Second)}}
	rec := httptest.NewRecorder()
	s.handleControlCenterVision(rec, httptest.NewRequest(http.MethodGet, "/", nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body=%s", rec.Code, rec.Body.String())
	}
	if got := rec.Header().Get("Cache-Control"); got != "no-store" {
		t.Fatalf("Cache-Control = %q", got)
	}
}

func TestControlCenterVisionProxyRejectsWrongSchema(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"schema":"visionrig/sensor-catalog/v4","sources":[]}`))
	}))
	defer upstream.Close()

	s := &server{Deps: Deps{Worker: proxy.New(upstream.URL, time.Second)}}
	rec := httptest.NewRecorder()
	s.handleControlCenterVision(rec, httptest.NewRequest(http.MethodGet, "/", nil))
	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status = %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestControlCenterVisionEnabledForwardsOnlyBooleanToLoopback(t *testing.T) {
	var seenPath, seenBody, seenRequestID string
	vision := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seenPath = r.URL.Path
		raw, _ := io.ReadAll(r.Body)
		seenBody = string(raw)
		seenRequestID = r.Header.Get("X-Request-ID")
		if r.Method != http.MethodPatch {
			t.Fatalf("method = %s", r.Method)
		}
		_, _ = w.Write([]byte(`{"schema":"visionrig/sensor-metadata/v1","metadata":{"source_id":"kinect-living-room","enabled":false}}`))
	}))
	defer vision.Close()
	t.Setenv("KALIV_VISIONRIG_URL", vision.URL)

	s := &server{}
	req := httptest.NewRequest(
		http.MethodPatch,
		"/api/v1/control-center/vision/sensors/kinect-living-room/enabled",
		strings.NewReader(`{"enabled":false}`),
	)
	req.SetPathValue("sourceID", "kinect-living-room")
	req.Header.Set("X-Request-ID", "req-vision-control")
	rec := httptest.NewRecorder()

	s.handleControlCenterVisionSensorEnabled(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body=%s", rec.Code, rec.Body.String())
	}
	if seenPath != "/api/v1/sensors/kinect-living-room/metadata" {
		t.Fatalf("VisionRig path = %q", seenPath)
	}
	if seenBody != `{"enabled":false}` {
		t.Fatalf("VisionRig body = %q", seenBody)
	}
	if seenRequestID != "req-vision-control" {
		t.Fatalf("request id = %q", seenRequestID)
	}
}

func TestControlCenterVisionEnabledRejectsExtraFieldsAndNonLoopbackTarget(t *testing.T) {
	s := &server{}

	t.Setenv("KALIV_VISIONRIG_URL", "http://127.0.0.1:8110")
	extra := httptest.NewRequest(http.MethodPatch, "/", strings.NewReader(`{"enabled":true,"location":"secret"}`))
	extra.SetPathValue("sourceID", "cam-a")
	extraRec := httptest.NewRecorder()
	s.handleControlCenterVisionSensorEnabled(extraRec, extra)
	if extraRec.Code != http.StatusBadRequest {
		t.Fatalf("extra-field status = %d", extraRec.Code)
	}

	t.Setenv("KALIV_VISIONRIG_URL", "https://example.com")
	remote := httptest.NewRequest(http.MethodPatch, "/", strings.NewReader(`{"enabled":true}`))
	remote.SetPathValue("sourceID", "cam-a")
	remoteRec := httptest.NewRecorder()
	s.handleControlCenterVisionSensorEnabled(remoteRec, remote)
	if remoteRec.Code != http.StatusBadGateway {
		t.Fatalf("remote-target status = %d", remoteRec.Code)
	}
}
