package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestAgent3ReadonlyTaskControlRoutesRequireFlagAndBearer(t *testing.T) {
	routes := []struct {
		method string
		path   string
	}{
		{http.MethodGet, "/api/v1/experimental/agent3/task/runs/run-1"},
		{http.MethodPost, "/api/v1/experimental/agent3/task/runs/run-1/cancel"},
	}

	t.Run("flag off leaves no control route", func(t *testing.T) {
		t.Setenv("KALIV_AGENT3_ENABLED", "0")
		s := &server{mux: http.NewServeMux()}
		s.routes()
		for _, route := range routes {
			assertStatus(t, s.mux, route.method, route.path, http.StatusNotFound)
		}
	})

	t.Run("flag on still requires bearer auth", func(t *testing.T) {
		t.Setenv("KALIV_AGENT3_ENABLED", "1")
		s := &server{mux: http.NewServeMux()}
		s.routes()
		for _, route := range routes {
			assertStatus(t, s.mux, route.method, route.path, http.StatusUnauthorized)
		}
	})
}

func TestAgent3ReadonlyTaskControlProxiesToWorkerOnly(t *testing.T) {
	t.Setenv("KALIV_AGENT3_ENABLED", "1")
	h, workerHits, ollamaHits := upstreams(t)

	routes := []struct {
		name       string
		method     string
		publicPath string
		workerPath string
	}{
		{
			name:       "status",
			method:     http.MethodGet,
			publicPath: "/api/v1/experimental/agent3/task/runs/run-1?source=android",
			workerPath: "/experimental/agent3/task/runs/run-1",
		},
		{
			name:       "cancel",
			method:     http.MethodPost,
			publicPath: "/api/v1/experimental/agent3/task/runs/run-1/cancel",
			workerPath: "/experimental/agent3/task/runs/run-1/cancel",
		},
	}

	for _, route := range routes {
		t.Run(route.name, func(t *testing.T) {
			req := httptest.NewRequest(route.method, route.publicPath, nil)
			req.Header.Set("Authorization", "Bearer "+testToken)
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, req)

			if rec.Code != http.StatusOK {
				t.Fatalf("%s: got %d, want 200: %s", route.name, rec.Code, rec.Body.String())
			}
			var body map[string]string
			if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
				t.Fatalf("%s returned invalid JSON: %v", route.name, err)
			}
			if body["upstream"] != "worker" {
				t.Fatalf("%s went to %q, want worker", route.name, body["upstream"])
			}
		})
	}

	if len(*workerHits) != len(routes) {
		t.Fatalf("worker hits = %v, want %d requests", *workerHits, len(routes))
	}
	for index, route := range routes {
		if (*workerHits)[index] != route.workerPath {
			t.Errorf("%s forwarded to %q, want %q", route.name, (*workerHits)[index], route.workerPath)
		}
	}
	if len(*ollamaHits) != 0 {
		t.Fatalf("task control bypassed worker and reached Ollama: %v", *ollamaHits)
	}
}
