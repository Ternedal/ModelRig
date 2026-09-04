package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"modelrig/internal/proxy"
)

// fakeOllama svarer som Ollama gør: /api/ps lister indlæste modeller,
// /api/generate accepterer keep_alive-direktivet.
func fakeOllama(t *testing.T, psBody string, failFor string) (*httptest.Server, *[]string) {
	t.Helper()
	var mu sync.Mutex
	unloadCalls := []string{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/ps":
			w.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(w, psBody)
		case "/api/generate":
			body, _ := io.ReadAll(r.Body)
			var req struct {
				Model     string `json:"model"`
				KeepAlive int    `json:"keep_alive"`
			}
			if err := json.Unmarshal(body, &req); err != nil {
				w.WriteHeader(http.StatusBadRequest)
				return
			}
			if req.KeepAlive != 0 {
				t.Errorf("keep_alive = %d, skal vaere 0 for at frigoere VRAM", req.KeepAlive)
			}
			if req.Model == failFor {
				w.WriteHeader(http.StatusInternalServerError)
				return
			}
			mu.Lock()
			unloadCalls = append(unloadCalls, req.Model)
			mu.Unlock()
			_, _ = io.WriteString(w, `{"done":true}`)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	return srv, &unloadCalls
}

func TestModelsUnloadReleasesEveryLoadedModel(t *testing.T) {
	ps := `{"models":[{"name":"qwen3:14b","size_vram":9663676416},{"name":"nomic-embed","size_vram":536870912}]}`
	up, calls := fakeOllama(t, ps, "")
	defer up.Close()

	s := &server{Deps: Deps{Ollama: proxy.New(up.URL, 3*time.Second)}}
	rec := httptest.NewRecorder()
	s.handleModelsUnload(rec, httptest.NewRequest(http.MethodPost, "/api/v1/models/unload", nil))

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d", rec.Code)
	}
	var body struct {
		Schema   string `json:"schema"`
		Unloaded []struct {
			Name  string `json:"name"`
			Bytes int64  `json:"size_vram_bytes"`
		} `json:"unloaded"`
		Freed  int64    `json:"freed_bytes"`
		Failed []string `json:"failed"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body.Schema != "kaliv-models-unload/v1" {
		t.Errorf("schema = %q", body.Schema)
	}
	if len(*calls) != 2 {
		t.Fatalf("unload-kald = %v, want begge modeller", *calls)
	}
	if len(body.Unloaded) != 2 || body.Freed != 9663676416+536870912 {
		t.Errorf("freed = %d, unloaded = %d", body.Freed, len(body.Unloaded))
	}
	if len(body.Failed) != 0 {
		t.Errorf("failed skal vaere tom, fik %v", body.Failed)
	}
}

func TestModelsUnloadReportsPartialFailureHonestly(t *testing.T) {
	ps := `{"models":[{"name":"a:1","size_vram":100},{"name":"b:2","size_vram":200}]}`
	up, calls := fakeOllama(t, ps, "b:2")
	defer up.Close()

	s := &server{Deps: Deps{Ollama: proxy.New(up.URL, 3*time.Second)}}
	rec := httptest.NewRecorder()
	s.handleModelsUnload(rec, httptest.NewRequest(http.MethodPost, "/api/v1/models/unload", nil))

	var body struct {
		Freed  int64    `json:"freed_bytes"`
		Failed []string `json:"failed"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if len(*calls) != 1 {
		t.Fatalf("kun den lykkede model skal taelle, fik %v", *calls)
	}
	// Den fejlede model maa ALDRIG tælle med i frigjort VRAM.
	if body.Freed != 100 {
		t.Errorf("freed = %d, want 100", body.Freed)
	}
	if len(body.Failed) != 1 || body.Failed[0] != "b:2" {
		t.Errorf("failed = %v, want [b:2]", body.Failed)
	}
}

func TestModelsUnloadWithNothingLoadedIsAnEmptySuccess(t *testing.T) {
	up, calls := fakeOllama(t, `{"models":[]}`, "")
	defer up.Close()

	s := &server{Deps: Deps{Ollama: proxy.New(up.URL, 3*time.Second)}}
	rec := httptest.NewRecorder()
	s.handleModelsUnload(rec, httptest.NewRequest(http.MethodPost, "/api/v1/models/unload", nil))

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d", rec.Code)
	}
	if len(*calls) != 0 {
		t.Errorf("ingen unload-kald forventet, fik %v", *calls)
	}
	if !strings.Contains(rec.Body.String(), `"freed_bytes":0`) {
		t.Errorf("body = %s", rec.Body.String())
	}
}

func TestModelsUnloadFailsClosedWhenOllamaIsUnreachable(t *testing.T) {
	s := &server{Deps: Deps{Ollama: proxy.New("http://127.0.0.1:9", time.Second)}}
	rec := httptest.NewRecorder()
	s.handleModelsUnload(rec, httptest.NewRequest(http.MethodPost, "/api/v1/models/unload", nil))
	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502", rec.Code)
	}
}

func TestModelsUnloadRouteRequiresBearerToken(t *testing.T) {
	handler, token := newAuthedTestHandler(t)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/models/unload", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("uden token: status = %d, want 401", rec.Code)
	}

	req = httptest.NewRequest(http.MethodPost, "/api/v1/models/unload", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code == http.StatusUnauthorized {
		t.Fatalf("med token blev kaldet stadig afvist som uautoriseret")
	}
}
