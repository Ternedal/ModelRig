package proxy

import (
    "net/http"
    "net/http/httptest"
    "testing"
    "time"
)

func TestForwardWithHeadersDoesNotFollowRedirect(t *testing.T) {
    visited := false
    target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        visited = true
        if r.Header.Get("X-Internal-Media-Secret") != "" {
            t.Error("internal secret leaked to redirect target")
        }
        w.WriteHeader(http.StatusOK)
    }))
    defer target.Close()

    source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        http.Redirect(w, r, target.URL+"/stolen", http.StatusTemporaryRedirect)
    }))
    defer source.Close()

    client := New(source.URL, 5*time.Second)
    response := httptest.NewRecorder()
    request := httptest.NewRequest(http.MethodGet, "/media", nil)
    client.ForwardWithHeaders(response, request, "/internal/media/images/jobs", map[string]string{
        "X-Internal-Media-Secret": "private-secret",
        "X-Verified-Owner": "device-1",
    })
    if visited { t.Fatal("followed redirect with trusted internal headers") }
    if response.Code != http.StatusTemporaryRedirect {
        t.Fatalf("expected redirect refusal status 307, got %d", response.Code)
    }
}
