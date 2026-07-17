package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
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
		assertStatus(t, s.mux, http.MethodGet, "/api/v1/experimental/agent3/capabilities", http.StatusNotFound)
		assertStatus(t, s.mux, http.MethodPost, "/api/v1/experimental/agent3/routing-preview", http.StatusNotFound)
		assertStatus(t, s.mux, http.MethodGet, "/api/v1/experimental/agent3/memory", http.StatusNotFound)
		assertStatus(t, s.mux, http.MethodDelete, "/api/v1/experimental/agent3/memory/example", http.StatusNotFound)
		assertStatus(t, s.mux, http.MethodGet, "/api/v1/experimental/agent3/runs/example/capability-receipt", http.StatusNotFound)
		assertStatus(t, s.mux, http.MethodGet, "/api/v1/experimental/agent3/runs/example/replans", http.StatusNotFound)
		assertStatus(t, s.mux, http.MethodPost, "/api/v1/experimental/agent3/runs/example/replan", http.StatusNotFound)
		assertStatus(t, s.mux, http.MethodPost, "/api/v1/experimental/agent3/runs/example/replan-preview", http.StatusNotFound)
		assertStatus(t, s.mux, http.MethodPost, "/api/v1/experimental/agent3/runs/example/answer-preview", http.StatusNotFound)
		assertStatus(t, s.mux, http.MethodPost, "/api/v1/experimental/agent3/replan-previews/example/apply", http.StatusNotFound)
	})

	t.Run("flag on still requires bearer auth", func(t *testing.T) {
		t.Setenv("KALIV_AGENT3_ENABLED", "1")
		s := &server{mux: http.NewServeMux()}
		s.routes()

		assertStatus(t, s.mux, http.MethodGet, "/api/v1/experimental/agent3/status", http.StatusUnauthorized)
		assertStatus(t, s.mux, http.MethodGet, "/api/v1/experimental/agent3/capabilities", http.StatusUnauthorized)
		assertStatus(t, s.mux, http.MethodPost, "/api/v1/experimental/agent3/routing-preview", http.StatusUnauthorized)
		assertStatus(t, s.mux, http.MethodGet, "/api/v1/experimental/agent3/memory", http.StatusUnauthorized)
		assertStatus(t, s.mux, http.MethodPost, "/api/v1/experimental/agent3/memory/example/correct", http.StatusUnauthorized)
		assertStatus(t, s.mux, http.MethodGet, "/api/v1/experimental/agent3/runs/example/capability-receipt", http.StatusUnauthorized)
		assertStatus(t, s.mux, http.MethodGet, "/api/v1/experimental/agent3/runs/example/replans", http.StatusUnauthorized)
		assertStatus(t, s.mux, http.MethodPost, "/api/v1/experimental/agent3/runs/example/replan", http.StatusUnauthorized)
		assertStatus(t, s.mux, http.MethodPost, "/api/v1/experimental/agent3/runs/example/replan-preview", http.StatusUnauthorized)
		assertStatus(t, s.mux, http.MethodPost, "/api/v1/experimental/agent3/runs/example/answer-preview", http.StatusUnauthorized)
		assertStatus(t, s.mux, http.MethodPost, "/api/v1/experimental/agent3/replan-previews/example/apply", http.StatusUnauthorized)
	})
}

func TestAgent3CapabilitiesProxiesToWorkerOnly(t *testing.T) {
	t.Setenv("KALIV_AGENT3_ENABLED", "1")
	h, workerHits, ollamaHits := upstreams(t)

	req := httptest.NewRequest(
		http.MethodGet,
		"/api/v1/experimental/agent3/capabilities",
		nil,
	)
	req.Header.Set("Authorization", "Bearer "+testToken)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("capabilities: got %d, want 200: %s", rec.Code, rec.Body.String())
	}
	var body map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("capabilities returned invalid JSON: %v", err)
	}
	if body["upstream"] != "worker" {
		t.Fatalf("capabilities went to %q, want worker", body["upstream"])
	}
	if len(*workerHits) != 1 || (*workerHits)[0] != "/experimental/agent3/capabilities" {
		t.Fatalf("worker hits = %v, want capability worker path", *workerHits)
	}
	if len(*ollamaHits) != 0 {
		t.Fatalf("capabilities bypassed worker and reached Ollama: %v", *ollamaHits)
	}
}

func TestAgent3RoutingPreviewProxiesToWorkerOnly(t *testing.T) {
	t.Setenv("KALIV_AGENT3_ENABLED", "1")
	h, workerHits, ollamaHits := upstreams(t)

	payload := `{"message":"vis rig status","mode":"rig","tools":true}`
	req := httptest.NewRequest(
		http.MethodPost,
		"/api/v1/experimental/agent3/routing-preview",
		strings.NewReader(payload),
	)
	req.Header.Set("Authorization", "Bearer "+testToken)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("routing preview: got %d, want 200: %s", rec.Code, rec.Body.String())
	}
	var body map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("routing preview returned invalid JSON: %v", err)
	}
	if body["upstream"] != "worker" {
		t.Fatalf("routing preview went to %q, want worker", body["upstream"])
	}
	if len(*workerHits) != 1 || (*workerHits)[0] != "/experimental/agent3/routing-preview" {
		t.Fatalf("worker hits = %v, want routing-preview worker path", *workerHits)
	}
	if len(*ollamaHits) != 0 {
		t.Fatalf("routing preview bypassed worker and reached Ollama: %v", *ollamaHits)
	}
}

func TestAgent3RunCapabilityReceiptProxiesToWorkerOnly(t *testing.T) {
	t.Setenv("KALIV_AGENT3_ENABLED", "1")
	h, workerHits, ollamaHits := upstreams(t)

	req := httptest.NewRequest(
		http.MethodGet,
		"/api/v1/experimental/agent3/runs/run-1/capability-receipt",
		nil,
	)
	req.Header.Set("Authorization", "Bearer "+testToken)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("capability receipt: got %d, want 200: %s", rec.Code, rec.Body.String())
	}
	var body map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("capability receipt returned invalid JSON: %v", err)
	}
	if body["upstream"] != "worker" {
		t.Fatalf("capability receipt went to %q, want worker", body["upstream"])
	}
	want := "/experimental/agent3/runs/run-1/capability-receipt"
	if len(*workerHits) != 1 || (*workerHits)[0] != want {
		t.Fatalf("worker hits = %v, want %s", *workerHits, want)
	}
	if len(*ollamaHits) != 0 {
		t.Fatalf("capability receipt bypassed worker and reached Ollama: %v", *ollamaHits)
	}
}

func TestAgent3AnswerPreviewProxiesToWorkerOnly(t *testing.T) {
	t.Setenv("KALIV_AGENT3_ENABLED", "1")
	h, workerHits, ollamaHits := upstreams(t)

	req := httptest.NewRequest(
		http.MethodPost,
		"/api/v1/experimental/agent3/runs/run-1/answer-preview",
		strings.NewReader(`{"answer_model":"local-answer-model"}`),
	)
	req.Header.Set("Authorization", "Bearer "+testToken)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("answer preview: got %d, want 200: %s", rec.Code, rec.Body.String())
	}
	var body map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("answer preview returned invalid JSON: %v", err)
	}
	if body["upstream"] != "worker" {
		t.Fatalf("answer preview went to %q, want worker", body["upstream"])
	}
	if len(*workerHits) != 1 || (*workerHits)[0] != "/experimental/agent3/runs/run-1/answer-preview" {
		t.Fatalf("worker hits = %v, want answer-preview worker path", *workerHits)
	}
	if len(*ollamaHits) != 0 {
		t.Fatalf("answer preview bypassed worker and reached Ollama: %v", *ollamaHits)
	}
}
