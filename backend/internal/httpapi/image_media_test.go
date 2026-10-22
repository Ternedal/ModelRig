package httpapi

import (
    "net/http"
    "net/http/httptest"
    "testing"

    "modelrig/internal/proxy"
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
