package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
	"time"

	"modelrig/internal/auth"
	"modelrig/internal/config"
	"modelrig/internal/proxy"
	"modelrig/internal/store"
)

const (
	grantAdminTestKey   = "separate-admin-authority"
	grantAdminTestToken = "paired-device-token"
)

func newAgent4GrantAdminTestHandler(
	t *testing.T,
	adminEnabled bool,
	adminKey string,
) (http.Handler, *store.Store) {
	t.Helper()
	if adminEnabled {
		t.Setenv(agent4GrantAdminFlag, "1")
	} else {
		t.Setenv(agent4GrantAdminFlag, "0")
	}
	t.Setenv("MODELRIG_ADMIN_KEY", adminKey)

	state, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	if err := state.AddDevice(store.Device{
		ID:        "device-1",
		Name:      "Pixel",
		TokenHash: auth.Hash(grantAdminTestToken),
		CreatedAt: time.Unix(1, 0).UTC(),
		LastSeen:  time.Now(),
	}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}

	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/vnd.modelrig.agent4.operator+json")
		_, _ = w.Write([]byte(`{"schema":"modelrig-agent4/operator-api/v1","campaigns":[]}`))
	}))
	t.Cleanup(worker.Close)

	handler := New(Deps{
		Cfg:        config.Config{ClaimMax: 5, RequestTimeout: 5 * time.Second},
		Store:      state,
		Worker:     proxy.New(worker.URL, 5*time.Second),
		WorkerSlow: proxy.New(worker.URL, 5*time.Second),
	})
	return handler, state
}

func agent4GrantRequest(
	handler http.Handler,
	method string,
	adminKey string,
	remoteAddr string,
) *httptest.ResponseRecorder {
	request := httptest.NewRequest(
		method,
		"/api/v1/admin/devices/device-1/grants/agent4-read",
		nil,
	)
	request.RemoteAddr = remoteAddr
	if adminKey != "" {
		request.Header.Set("X-Admin-Key", adminKey)
	}
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	return recorder
}

func TestAgent4GrantAdminIsExactOptInAndSeparateFromBearer(t *testing.T) {
	handler, _ := newAgent4GrantAdminTestHandler(t, false, grantAdminTestKey)
	response := agent4GrantRequest(
		handler,
		http.MethodPut,
		grantAdminTestKey,
		"127.0.0.1:1234",
	)
	if response.Code != http.StatusNotFound {
		t.Fatalf("flag off must mean no admin route: %d %s", response.Code, response.Body.String())
	}

	handler, _ = newAgent4GrantAdminTestHandler(t, true, grantAdminTestKey)
	request := httptest.NewRequest(
		http.MethodPut,
		"/api/v1/admin/devices/device-1/grants/agent4-read",
		nil,
	)
	request.RemoteAddr = "127.0.0.1:1234"
	request.Header.Set("Authorization", "Bearer "+grantAdminTestToken)
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("paired Bearer must not administer its own grant: %d %s", recorder.Code, recorder.Body.String())
	}
}

func TestAgent4GrantAdminRequiresLoopbackAndConfiguredKey(t *testing.T) {
	handler, _ := newAgent4GrantAdminTestHandler(t, true, grantAdminTestKey)

	response := agent4GrantRequest(
		handler,
		http.MethodPut,
		grantAdminTestKey,
		"192.0.2.10:1234",
	)
	if response.Code != http.StatusForbidden {
		t.Fatalf("remote grant admin must be forbidden: %d %s", response.Code, response.Body.String())
	}

	response = agent4GrantRequest(
		handler,
		http.MethodPut,
		"wrong-key",
		"127.0.0.1:1234",
	)
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("wrong admin key must be rejected: %d %s", response.Code, response.Body.String())
	}

	handler, _ = newAgent4GrantAdminTestHandler(t, true, "")
	response = agent4GrantRequest(
		handler,
		http.MethodPut,
		"anything",
		"127.0.0.1:1234",
	)
	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf("unconfigured admin authority must fail closed: %d %s", response.Code, response.Body.String())
	}
}

func TestAgent4ReadGrantTransitions403To200To403(t *testing.T) {
	t.Setenv("KALIV_AGENT4_OPERATOR_API", "1")
	handler, state := newAgent4GrantAdminTestHandler(t, true, grantAdminTestKey)

	read := func() *httptest.ResponseRecorder {
		request := httptest.NewRequest(
			http.MethodGet,
			"/api/v1/experimental/agent4/operator/campaigns",
			nil,
		)
		request.RemoteAddr = "127.0.0.1:1234"
		request.Header.Set("Authorization", "Bearer "+grantAdminTestToken)
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, request)
		return recorder
	}

	if response := read(); response.Code != http.StatusForbidden {
		t.Fatalf("read before grant must be 403: %d %s", response.Code, response.Body.String())
	}

	granted := agent4GrantRequest(
		handler,
		http.MethodPut,
		grantAdminTestKey,
		"127.0.0.1:1234",
	)
	if granted.Code != http.StatusOK {
		t.Fatalf("grant failed: %d %s", granted.Code, granted.Body.String())
	}
	var grantBody struct {
		Enabled bool `json:"enabled"`
		Changed bool `json:"changed"`
	}
	if err := json.Unmarshal(granted.Body.Bytes(), &grantBody); err != nil {
		t.Fatalf("decode grant response: %v", err)
	}
	if !grantBody.Enabled || !grantBody.Changed {
		t.Fatalf("unexpected grant response: %+v", grantBody)
	}
	if !state.Devices()[0].HasGrant(agent4ReadGrant) {
		t.Fatal("grant did not reach live store")
	}

	if response := read(); response.Code != http.StatusOK {
		t.Fatalf("read after grant must be 200: %d %s", response.Code, response.Body.String())
	}

	revoked := agent4GrantRequest(
		handler,
		http.MethodDelete,
		grantAdminTestKey,
		"127.0.0.1:1234",
	)
	if revoked.Code != http.StatusOK {
		t.Fatalf("revoke failed: %d %s", revoked.Code, revoked.Body.String())
	}
	if state.Devices()[0].HasGrant(agent4ReadGrant) {
		t.Fatal("revoke did not reach live store")
	}

	if response := read(); response.Code != http.StatusForbidden {
		t.Fatalf("read after revoke must return to 403: %d %s", response.Code, response.Body.String())
	}
}

func TestAgent4GrantAdminIsIdempotentAndUnknownDeviceFailsClosed(t *testing.T) {
	handler, _ := newAgent4GrantAdminTestHandler(t, true, grantAdminTestKey)

	first := agent4GrantRequest(handler, http.MethodPut, grantAdminTestKey, "127.0.0.1:1234")
	second := agent4GrantRequest(handler, http.MethodPut, grantAdminTestKey, "127.0.0.1:1234")
	if first.Code != http.StatusOK || second.Code != http.StatusOK {
		t.Fatalf("idempotent grant failed: first=%d second=%d", first.Code, second.Code)
	}
	var secondBody struct {
		Changed bool `json:"changed"`
	}
	if err := json.Unmarshal(second.Body.Bytes(), &secondBody); err != nil {
		t.Fatalf("decode second grant: %v", err)
	}
	if secondBody.Changed {
		t.Fatal("duplicate grant must report changed=false")
	}

	request := httptest.NewRequest(
		http.MethodPut,
		"/api/v1/admin/devices/missing/grants/agent4-read",
		nil,
	)
	request.RemoteAddr = "127.0.0.1:1234"
	request.Header.Set("X-Admin-Key", grantAdminTestKey)
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusNotFound {
		t.Fatalf("unknown device must be 404: %d %s", recorder.Code, recorder.Body.String())
	}
}
