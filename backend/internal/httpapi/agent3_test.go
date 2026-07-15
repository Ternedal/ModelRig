package httpapi

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func assertStatus(t *testing.T, handler http.Handler, method, path string, want int) {
	t.Helper()
	req := httptest.NewRequest(method, path, nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != want {
		t.Fatalf("%s %s: got status %d, want %d", method, path, rec.Code, want)
	}
}

func TestAgent3RoutesRequireFeatureFlagAndAuth(t *testing.T) {
	t.Run("flag off leaves no route", func(t *testing.T) {
		t.Setenv("KALIV_AGENT3_ENABLED", "0")
		s := &server{mux: http.NewServeMux()}
		s.routes()

		assertStatus(t, s.mux, http.MethodGet, "/api/v1/experimental/agent3/status", http.StatusNotFound)
		assertStatus(t, s.mux, http.MethodGet, "/api/v1/experimental/agent3/memory", http.StatusNotFound)
		assertStatus(t, s.mux, http.MethodDelete, "/api/v1/experimental/agent3/memory/example", http.StatusNotFound)
	})

	t.Run("flag on still requires bearer auth", func(t *testing.T) {
		t.Setenv("KALIV_AGENT3_ENABLED", "1")
		s := &server{mux: http.NewServeMux()}
		s.routes()

		assertStatus(t, s.mux, http.MethodGet, "/api/v1/experimental/agent3/status", http.StatusUnauthorized)
		assertStatus(t, s.mux, http.MethodGet, "/api/v1/experimental/agent3/memory", http.StatusUnauthorized)
		assertStatus(t, s.mux, http.MethodPost, "/api/v1/experimental/agent3/memory/example/correct", http.StatusUnauthorized)
	})
}
