package httpapi

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestAgent3RoutesRequireFeatureFlagAndAuth(t *testing.T) {
	t.Run("flag off leaves no route", func(t *testing.T) {
		t.Setenv("KALIV_AGENT3_ENABLED", "0")
		s := &server{mux: http.NewServeMux()}
		s.routes()

		req := httptest.NewRequest(http.MethodGet, "/api/v1/experimental/agent3/status", nil)
		rec := httptest.NewRecorder()
		s.mux.ServeHTTP(rec, req)
		if rec.Code != http.StatusNotFound {
			t.Fatalf("flag off: got status %d, want %d", rec.Code, http.StatusNotFound)
		}
	})

	t.Run("flag on still requires bearer auth", func(t *testing.T) {
		t.Setenv("KALIV_AGENT3_ENABLED", "1")
		s := &server{mux: http.NewServeMux()}
		s.routes()

		req := httptest.NewRequest(http.MethodGet, "/api/v1/experimental/agent3/status", nil)
		rec := httptest.NewRecorder()
		s.mux.ServeHTTP(rec, req)
		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("flag on without token: got status %d, want %d", rec.Code, http.StatusUnauthorized)
		}
	})
}
