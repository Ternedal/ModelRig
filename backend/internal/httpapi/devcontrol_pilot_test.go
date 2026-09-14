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
	"modelrig/internal/store"
)

const devControlPilotTestToken = "devcontrol-pilot-test-token"

func devControlPilotTestHandler(t *testing.T, flag string) http.Handler {
	t.Helper()
	t.Setenv(devControlPilotFlag, flag)
	st, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	if err := st.AddDevice(store.Device{
		ID: "devcontrol-pilot-device", Name: "desktop",
		TokenHash: auth.Hash(devControlPilotTestToken), CreatedAt: time.Now(), LastSeen: time.Now(),
	}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}
	return New(Deps{
		Cfg:   config.Config{ClaimMax: 5, RequestTimeout: 2 * time.Second},
		Store: st,
	})
}

func devControlPilotRequest(h http.Handler, method, token string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, "/api/v1/experimental/devcontrol-pilot/status", nil)
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func TestDevControlPilotStatusIsExactDefaultOff(t *testing.T) {
	for _, flag := range []string{"", "0", "true", "TRUE", "on", " On ", "garbage"} {
		t.Run("disabled="+flag, func(t *testing.T) {
			h := devControlPilotTestHandler(t, flag)
			rec := devControlPilotRequest(h, http.MethodGet, devControlPilotTestToken)
			if rec.Code != http.StatusNotFound {
				t.Fatalf("flag=%q: got %d, want 404; body=%s", flag, rec.Code, rec.Body.String())
			}
		})
	}
}

func TestDevControlPilotStatusRequiresBearer(t *testing.T) {
	h := devControlPilotTestHandler(t, "1")
	for _, token := range []string{"", "wrong"} {
		rec := devControlPilotRequest(h, http.MethodGet, token)
		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("token=%q: got %d, want 401; body=%s", token, rec.Code, rec.Body.String())
		}
	}
}

func TestDevControlPilotStatusIsReadOnlyAndNonAuthorizing(t *testing.T) {
	h := devControlPilotTestHandler(t, "1")
	rec := devControlPilotRequest(h, http.MethodGet, devControlPilotTestToken)
	if rec.Code != http.StatusOK {
		t.Fatalf("got %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	if got := rec.Header().Get("Cache-Control"); got != "no-store" {
		t.Fatalf("Cache-Control=%q, want no-store", got)
	}

	var payload map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if payload["schema"] != "kaliv-devcontrol-pilot-status/v1" {
		t.Fatalf("unexpected schema: %#v", payload["schema"])
	}
	if payload["feature_flag"] != devControlPilotFlag || payload["enabled"] != true {
		t.Fatalf("unexpected flag state: %#v", payload)
	}
	if payload["operator_surface"] != "desktop.control-center" || payload["route_scope"] != "read-only-status-only" {
		t.Fatalf("unexpected surface: %#v", payload)
	}
	if payload["manual_refresh_only"] != true {
		t.Fatalf("manual_refresh_only must be true")
	}
	for _, key := range []string{
		"automatic_polling",
		"unattended_cadence",
		"task_registry_ready",
		"runtime_preflight_satisfied",
		"pilot_start_authorized",
		"product_pilot_started",
		"local_commit_authorized",
		"remote_transport_available",
		"remote_write_authorized",
		"push_authorized",
		"pr_mutation_authorized",
		"merge_authorized",
		"release_authorized",
		"deploy_authorized",
		"production_activation_authorized",
	} {
		if payload[key] != false {
			t.Fatalf("%s=%#v, want false", key, payload[key])
		}
	}
	if payload["authority"] != "dc-l16-product-status-observation-only" {
		t.Fatalf("unexpected authority: %#v", payload["authority"])
	}

	post := devControlPilotRequest(h, http.MethodPost, devControlPilotTestToken)
	if post.Code != http.StatusMethodNotAllowed {
		t.Fatalf("POST got %d, want 405; body=%s", post.Code, post.Body.String())
	}
}
