package httpapi

import (
    "context"
    "net/http"
    "net/http/httptest"
    "testing"

    "modelrig/internal/proxy"
    "modelrig/internal/store"
)

func TestImageMediaPilotDefaultOff(t *testing.T) {
    t.Setenv("KALIV_IMAGE_MEDIA_PILOT", "")
    if imageMediaPilotEnabled() { t.Fatal("image media must default off") }
    t.Setenv("KALIV_IMAGE_MEDIA_PILOT", "1")
    if !imageMediaPilotEnabled() { t.Fatal("explicit pilot switch should enable routes") }
}

func TestImageMediaFailsClosedWithoutSecret(t *testing.T) {
    t.Setenv("KALIV_IMAGE_INTERNAL_SECRET", "")
    s := &server{Deps: Deps{Worker: proxy.New("http://127.0.0.1:8099", 0)}}
    request := httptest.NewRequest(http.MethodPost, "/api/v1/media/images/jobs", nil)
    response := httptest.NewRecorder()
    s.handleImageMedia(response, request)
    if response.Code != http.StatusServiceUnavailable {
        t.Fatalf("expected 503, got %d", response.Code)
    }
}

func TestImageMediaRequiresLoopbackWorker(t *testing.T) {
    t.Setenv("KALIV_IMAGE_INTERNAL_SECRET", "01234567890123456789012345678901")
    s := &server{Deps: Deps{Worker: proxy.New("http://example.com:8099", 0)}}
    request := httptest.NewRequest(http.MethodPost, "/api/v1/media/images/jobs", nil)
    response := httptest.NewRecorder()
    s.handleImageMedia(response, request)
    if response.Code != http.StatusServiceUnavailable {
        t.Fatalf("expected 503, got %d", response.Code)
    }
}

func TestImageMediaIDValidation(t *testing.T) {
    if !imageMediaID.MatchString("0123456789abcdef0123456789abcdef") {
        t.Fatal("valid image id rejected")
    }
    for _, id := range []string{"../other", "ABCDEF0123456789ABCDEF0123456789", "a", ""} {
        if imageMediaID.MatchString(id) { t.Fatalf("accepted invalid id %q", id) }
    }
}

func TestImageMediaForwardsVerifiedDeviceAndDisablesCaching(t *testing.T) {
    t.Setenv("KALIV_IMAGE_INTERNAL_SECRET", "01234567890123456789012345678901")
    worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        if r.URL.Path != "/internal/media/images/assets/0123456789abcdef0123456789abcdef" {
            t.Errorf("unexpected worker path %s", r.URL.Path)
        }
        if r.Header.Get("X-Verified-Owner") != "paired-device" {
            t.Errorf("untrusted device identity forwarded: %q", r.Header.Get("X-Verified-Owner"))
        }
        if r.Header.Get("X-Internal-Media-Secret") != "01234567890123456789012345678901" {
            t.Error("internal secret not attached by gateway")
        }
        w.Header().Set("Content-Type", "image/png")
        w.WriteHeader(http.StatusOK)
        _, _ = w.Write([]byte("image-fixture"))
    }))
    defer worker.Close()

    s := &server{Deps: Deps{Worker: proxy.New(worker.URL, 0)}}
    request := httptest.NewRequest(http.MethodGet, "/api/v1/media/images/assets/0123456789abcdef0123456789abcdef", nil)
    request.SetPathValue("id", "0123456789abcdef0123456789abcdef")
    request.Header.Set("X-Verified-Owner", "attacker")
    request.Header.Set("X-Internal-Media-Secret", "attacker")
    request = request.WithContext(context.WithValue(request.Context(), deviceKey, store.Device{ID: "paired-device"}))
    response := httptest.NewRecorder()
    s.handleImageMedia(response, request)
    if response.Code != http.StatusOK {
        t.Fatalf("expected 200, got %d: %s", response.Code, response.Body.String())
    }
    if response.Header().Get("Cache-Control") != "private, no-store" {
        t.Fatal("private image response is cacheable")
    }
    if response.Header().Get("X-Content-Type-Options") != "nosniff" {
        t.Fatal("image response lacks nosniff")
    }
}
