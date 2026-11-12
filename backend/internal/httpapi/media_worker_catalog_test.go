package httpapi

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
)

// The shared kaliv-media-gallery/v1 fixture (#2374), served by a fake worker that follows
// worker/app/media_gallery_api.py: list, HEAD and single-range GET, 404/400/503 as the worker
// answers them. These run on every platform; nothing touches a real volume.

const testMediaSecret = "m-0123456789-0123456789-0123456789"

type galleryFixture struct {
	Page struct {
		Schema     string           `json:"schema"`
		Items      []map[string]any `json:"items"`
		NextCursor *string          `json:"next_cursor"`
	} `json:"page"`
}

func loadGalleryFixture(t *testing.T) galleryFixture {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "contracts", "kaliv-media-gallery-v1-fixtures.json"))
	if err != nil {
		t.Fatalf("shared fixture: %v", err)
	}
	var fixture galleryFixture
	if err := json.Unmarshal(raw, &fixture); err != nil {
		t.Fatal(err)
	}
	return fixture
}

type fakeWorker struct {
	t        *testing.T
	items    []map[string]any
	bytes    map[string][]byte
	status   int // when set, every answer is this status
	requests atomic.Int64
	heads    atomic.Int64
	gets     atomic.Int64
	mu       sync.Mutex
	ranges   []string
	override func(w http.ResponseWriter, r *http.Request) bool // a test may answer instead
}

func (f *fakeWorker) setOverride(o func(w http.ResponseWriter, r *http.Request) bool) {
	f.mu.Lock()
	f.override = o
	f.mu.Unlock()
}

func newFakeWorker(t *testing.T) (*fakeWorker, *httptest.Server) {
	fixture := loadGalleryFixture(t)
	f := &fakeWorker{t: t, items: fixture.Page.Items, bytes: map[string][]byte{}}
	for i, item := range f.items {
		size := int(item["size_bytes"].(float64))
		if size > 4096 {
			size = 4096 + i // keep the test data small; the fake answers with its own size
		}
		data := make([]byte, size)
		for j := range data {
			data[j] = byte((j + i) % 251)
		}
		f.bytes[item["id"].(string)] = data
	}
	server := httptest.NewServer(f)
	t.Cleanup(server.Close)
	return f, server
}

func (f *fakeWorker) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.requests.Add(1)
	if r.Header.Get(mediaJobsSecretHeader) != testMediaSecret {
		http.Error(w, `{"detail":"internal_authentication_required"}`, http.StatusUnauthorized)
		return
	}
	f.mu.Lock()
	override := f.override
	f.mu.Unlock()
	if override != nil && override(w, r) {
		return
	}
	if f.status != 0 {
		http.Error(w, `{"detail":"media_volume_lost"}`, f.status)
		return
	}
	if r.URL.Path == "/internal/media/assets" {
		f.list(w, r)
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/internal/media/assets/")
	data, ok := f.bytes[id]
	if !ok {
		http.Error(w, `{"detail":"asset_not_found"}`, http.StatusNotFound)
		return
	}
	mime := ""
	for _, item := range f.items {
		if item["id"] == id {
			mime = item["mime_type"].(string)
		}
	}
	w.Header().Set("Content-Type", mime)
	w.Header().Set("Accept-Ranges", "bytes")
	if r.Method == http.MethodHead {
		f.heads.Add(1)
		w.Header().Set("Content-Length", strconv.Itoa(len(data)))
		return
	}
	f.gets.Add(1)
	f.mu.Lock()
	f.ranges = append(f.ranges, r.Header.Get("Range"))
	f.mu.Unlock()
	var start, end int
	if _, err := fmt.Sscanf(r.Header.Get("Range"), "bytes=%d-%d", &start, &end); err != nil || end >= len(data) || start > end {
		http.Error(w, "bad range", http.StatusRequestedRangeNotSatisfiable)
		return
	}
	w.Header().Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", start, end, len(data)))
	w.Header().Set("Content-Length", strconv.Itoa(end-start+1))
	w.WriteHeader(http.StatusPartialContent)
	_, _ = w.Write(data[start : end+1])
}

func (f *fakeWorker) list(w http.ResponseWriter, r *http.Request) {
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	start := 0
	if cursor := r.URL.Query().Get("cursor"); cursor != "" {
		start = -1
		for i, item := range f.items {
			if item["id"] == cursor {
				start = i + 1
			}
		}
		if start < 0 {
			http.Error(w, `{"detail":"unknown_cursor"}`, http.StatusBadRequest)
			return
		}
	}
	end := start + limit
	if end > len(f.items) {
		end = len(f.items)
	}
	page := f.items[start:end]
	var next any
	if end < len(f.items) && len(page) > 0 {
		next = page[len(page)-1]["id"]
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"schema": "kaliv-media-gallery/v1", "items": page, "next_cursor": next})
}

func galleryServer(t *testing.T, workerURL string) *server {
	t.Helper()
	catalog, ok := NewWorkerMediaCatalog(workerURL, testMediaSecret)
	if !ok {
		t.Fatalf("catalog refused %s", workerURL)
	}
	return &server{Deps: Deps{Media: catalog}}
}

func listThrough(s *server, query string) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	s.handleMediaList(rec, httptest.NewRequest(http.MethodGet, "/api/v1/media"+query, nil))
	return rec
}

func assetThrough(s *server, method, id, rangeHeader string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, "/api/v1/media/"+id, nil)
	req.SetPathValue("id", id)
	if rangeHeader != "" {
		req.Header.Set("Range", rangeHeader)
	}
	rec := httptest.NewRecorder()
	s.handleMediaAsset(rec, req)
	return rec
}

func TestWorkerCatalogListIsTheFixturePage(t *testing.T) {
	fixture := loadGalleryFixture(t)
	_, worker := newFakeWorker(t)
	rec := listThrough(galleryServer(t, worker.URL), "?limit=100")
	if rec.Code != http.StatusOK || rec.Header().Get("Cache-Control") != "private, no-store" {
		t.Fatalf("list: %d %v %s", rec.Code, rec.Header(), rec.Body.String())
	}
	var got, want any
	_ = json.Unmarshal(rec.Body.Bytes(), &got)
	wantRaw, _ := json.Marshal(map[string]any{"schema": fixture.Page.Schema, "items": fixture.Page.Items, "next_cursor": nil})
	_ = json.Unmarshal(wantRaw, &want)
	gotRaw, _ := json.Marshal(got)
	if !bytes.Equal(gotRaw, mustJSON(t, want)) {
		t.Fatalf("device page differs from the fixture:\n got %s\nwant %s", gotRaw, mustJSON(t, want))
	}
	if strings.Contains(rec.Body.String(), testMediaSecret) {
		t.Fatal("the internal secret reached the device")
	}
}

func mustJSON(t *testing.T, v any) []byte {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func TestWorkerCatalogPaginatesByCursorAndAnUnknownCursorIs400(t *testing.T) {
	fixture := loadGalleryFixture(t)
	_, worker := newFakeWorker(t)
	s := galleryServer(t, worker.URL)
	var ids []string
	cursor, pages := "", 0
	for {
		query := "?limit=2"
		if cursor != "" {
			query += "&cursor=" + cursor
		}
		rec := listThrough(s, query)
		if rec.Code != http.StatusOK {
			t.Fatalf("page %d: %d %s", pages, rec.Code, rec.Body.String())
		}
		var page struct {
			Items      []map[string]any `json:"items"`
			NextCursor *string          `json:"next_cursor"`
		}
		_ = json.Unmarshal(rec.Body.Bytes(), &page)
		for _, item := range page.Items {
			ids = append(ids, item["id"].(string))
		}
		pages++
		if page.NextCursor == nil {
			break
		}
		cursor = *page.NextCursor
	}
	if pages != 3 || len(ids) != len(fixture.Page.Items) {
		t.Fatalf("pages=%d ids=%v", pages, ids)
	}
	if rec := listThrough(s, "?limit=2&cursor=not_in_the_gallery"); rec.Code != http.StatusBadRequest {
		t.Fatalf("unknown cursor: %d", rec.Code)
	}
}

func TestWorkerCatalogServesFullRangedSuffixHeadAndRefusesPastTheEnd(t *testing.T) {
	f, worker := newFakeWorker(t)
	s := galleryServer(t, worker.URL)
	data := f.bytes["img_png_1024"]
	size := len(data)
	cases := []struct {
		method, rangeHeader string
		status              int
		body                []byte
		contentRange        string
	}{
		{http.MethodGet, "", 200, data, ""},
		{http.MethodGet, "bytes=2-5", 206, data[2:6], fmt.Sprintf("bytes 2-5/%d", size)},
		{http.MethodGet, "bytes=-3", 206, data[size-3:], fmt.Sprintf("bytes %d-%d/%d", size-3, size-1, size)},
		{http.MethodGet, fmt.Sprintf("bytes=%d-", size), 416, nil, fmt.Sprintf("bytes */%d", size)},
		{http.MethodGet, "bytes=1-2,4-5", 200, data, ""},
		{http.MethodHead, "bytes=2-5", 206, nil, fmt.Sprintf("bytes 2-5/%d", size)},
	}
	for _, tc := range cases {
		rec := assetThrough(s, tc.method, "img_png_1024", tc.rangeHeader)
		if rec.Code != tc.status || !bytes.Equal(rec.Body.Bytes(), tc.body) || rec.Header().Get("Content-Range") != tc.contentRange {
			t.Errorf("%s %q: %d len=%d range=%q", tc.method, tc.rangeHeader, rec.Code, rec.Body.Len(), rec.Header().Get("Content-Range"))
		}
		if rec.Header().Get("Cache-Control") != "private, no-store" {
			t.Errorf("%s %q: Cache-Control %q", tc.method, tc.rangeHeader, rec.Header().Get("Cache-Control"))
		}
		if tc.status != 416 && rec.Header().Get("Content-Type") != "image/png" {
			t.Errorf("%s %q: Content-Type %q", tc.method, tc.rangeHeader, rec.Header().Get("Content-Type"))
		}
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	for _, sent := range f.ranges {
		if !strings.HasPrefix(sent, "bytes=") || strings.Contains(sent, ",") {
			t.Errorf("the worker was asked %q: always one explicit range", sent)
		}
	}
}

func TestWorkerCatalogMapsTheWorkersThreeStates(t *testing.T) {
	f, worker := newFakeWorker(t)
	s := galleryServer(t, worker.URL)
	if rec := assetThrough(s, http.MethodGet, "not_owned_or_unknown", ""); rec.Code != http.StatusNotFound {
		t.Fatalf("worker 404: device %d", rec.Code)
	}
	for _, status := range []int{http.StatusServiceUnavailable, http.StatusUnauthorized, http.StatusForbidden,
		http.StatusInternalServerError, http.StatusBadGateway, http.StatusFound} {
		f.status = status
		list := listThrough(s, "")
		asset := assetThrough(s, http.MethodGet, "img_png_1024", "")
		if list.Code != http.StatusServiceUnavailable || asset.Code != http.StatusServiceUnavailable {
			t.Errorf("worker %d: list %d asset %d (want 503: never a pairing error, never a redirect)", status, list.Code, asset.Code)
		}
	}
}

func TestWorkerCatalogIsUnavailableWhenTheWorkerIsDownOrTheSecretIsWrong(t *testing.T) {
	_, worker := newFakeWorker(t)
	down := httptest.NewServer(http.NotFoundHandler())
	downURL := down.URL
	down.Close()
	for label, s := range map[string]*server{
		"down": galleryServer(t, downURL),
		"wrong secret": func() *server {
			c, _ := NewWorkerMediaCatalog(worker.URL, strings.Repeat("x", 40))
			return &server{Deps: Deps{Media: c}}
		}(),
	} {
		if rec := listThrough(s, ""); rec.Code != http.StatusServiceUnavailable {
			t.Errorf("%s: list %d", label, rec.Code)
		}
		if rec := assetThrough(s, http.MethodGet, "img_png_1024", ""); rec.Code != http.StatusServiceUnavailable {
			t.Errorf("%s: asset %d", label, rec.Code)
		}
	}
}

func TestWorkerCatalogRefusesAnAnswerThatIsNotTheContract(t *testing.T) {
	f, worker := newFakeWorker(t)
	s := galleryServer(t, worker.URL)
	page := func(items []map[string]any, next any) func(http.ResponseWriter, *http.Request) bool {
		return func(w http.ResponseWriter, r *http.Request) bool {
			if r.URL.Path != "/internal/media/assets" {
				return false
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"schema": "kaliv-media-gallery/v1", "items": items, "next_cursor": next})
			return true
		}
	}
	clone := func(change func(map[string]any)) []map[string]any {
		raw, _ := json.Marshal(f.items[:1])
		var items []map[string]any
		_ = json.Unmarshal(raw, &items)
		change(items[0])
		return items
	}
	bad := map[string]func(http.ResponseWriter, *http.Request) bool{
		"a location elsewhere":  page(clone(func(i map[string]any) { i["url"] = "https://example.invalid/x" }), nil),
		"an extra field":        page(clone(func(i map[string]any) { i["path"] = "Z:/media/x.png" }), nil),
		"a field missing":       page(clone(func(i map[string]any) { delete(i, "projection") }), nil),
		"a thumbnail elsewhere": page(clone(func(i map[string]any) { i["thumbnail_id"] = "t"; i["thumbnail_url"] = "/api/v1/media/u" }), nil),
		"an unserved type":      page(clone(func(i map[string]any) { i["mime_type"] = "text/html" }), nil),
		"a cursor not its last": page(f.items[:2], "img_png_1024x"),
		"more items than asked": page(f.items, nil),
		"another schema": func(w http.ResponseWriter, r *http.Request) bool {
			_, _ = io.WriteString(w, `{"schema":"kaliv-media-gallery/v2","items":[],"next_cursor":null}`)
			return true
		},
		"not JSON": func(w http.ResponseWriter, r *http.Request) bool { _, _ = io.WriteString(w, "<html>"); return true },
	}
	for label, override := range bad {
		f.setOverride(override)
		query := "?limit=100"
		if label == "more items than asked" || label == "a cursor not its last" {
			query = "?limit=2"
		}
		if rec := listThrough(s, query); rec.Code != http.StatusServiceUnavailable {
			t.Errorf("%s: device %d %s", label, rec.Code, rec.Body.String())
		}
	}
}

func TestWorkerCatalogRefusesARangeAnswerThatIsNotExactlyTheOneAsked(t *testing.T) {
	f, worker := newFakeWorker(t)
	s := galleryServer(t, worker.URL)
	answers := map[string]func(w http.ResponseWriter){
		"200 instead of 206": func(w http.ResponseWriter) { w.Header().Set("Content-Type", "image/png"); w.WriteHeader(200) },
		"another range": func(w http.ResponseWriter) {
			w.Header().Set("Content-Type", "image/png")
			w.Header().Set("Content-Range", "bytes 0-1/9999")
			w.WriteHeader(206)
		},
		"another type":         func(w http.ResponseWriter) { w.Header().Set("Content-Type", "text/html"); w.WriteHeader(206) },
		"404 after a 200 HEAD": func(w http.ResponseWriter) { w.WriteHeader(404) },
	}
	for label, answer := range answers {
		answer := answer
		// HEAD comes from the fake; the ranged GET gets the broken answer.
		f.setOverride(func(w http.ResponseWriter, r *http.Request) bool {
			if r.Method != http.MethodGet || r.URL.Path != "/internal/media/assets/img_png_1024" {
				return false
			}
			answer(w)
			return true
		})
		rec := assetThrough(s, http.MethodGet, "img_png_1024", "bytes=2-5")
		if rec.Code != http.StatusServiceUnavailable || rec.Body.Len() > len("media unavailable\n") {
			t.Errorf("%s: device %d len=%d (want 503 before any byte)", label, rec.Code, rec.Body.Len())
		}
	}
}

func TestWorkerCatalogShortBodyIsAnErrorNeverAShortFile(t *testing.T) {
	f, worker := newFakeWorker(t)
	f.setOverride(func(w http.ResponseWriter, r *http.Request) bool {
		if r.Method == http.MethodGet && r.URL.Path == "/internal/media/assets/img_png_1024" {
			data := f.bytes["img_png_1024"]
			w.Header().Set("Content-Type", "image/png")
			w.Header().Set("Content-Range", fmt.Sprintf("bytes 0-%d/%d", len(data)-1, len(data)))
			w.Header().Set("Content-Length", strconv.Itoa(len(data)))
			w.WriteHeader(206)
			_, _ = w.Write(data[:10]) // then the connection ends
			w.(http.Flusher).Flush()
			if conn, _, err := w.(http.Hijacker).Hijack(); err == nil {
				_ = conn.Close()
			}
			return true
		}
		return false
	})
	catalog, _ := NewWorkerMediaCatalog(worker.URL, testMediaSecret)
	asset, _, size, err := catalog.OpenMedia(mediaInstallationOwner, "img_png_1024")
	if err != nil {
		t.Fatal(err)
	}
	defer asset.Close()
	if _, err := asset.Seek(0, io.SeekStart); err != nil {
		t.Fatal(err)
	}
	read, err := io.ReadAll(asset) // what any reader sees, not only the handler's CopyN
	if !errors.Is(err, io.ErrUnexpectedEOF) || int64(len(read)) >= size {
		t.Fatalf("a body that ended after %d of %d bytes read as %v, want io.ErrUnexpectedEOF", len(read), size, err)
	}
}

func TestWorkerCatalogHeadNeverReadsTheBody(t *testing.T) {
	f, worker := newFakeWorker(t)
	s := galleryServer(t, worker.URL)
	if rec := assetThrough(s, http.MethodHead, "img_png_1024", ""); rec.Code != http.StatusOK || rec.Body.Len() != 0 ||
		rec.Header().Get("Content-Length") != strconv.Itoa(len(f.bytes["img_png_1024"])) {
		t.Fatalf("HEAD: %d len=%d CL=%s", rec.Code, rec.Body.Len(), rec.Header().Get("Content-Length"))
	}
	if f.heads.Load() != 1 {
		t.Fatalf("heads=%d", f.heads.Load())
	}
}

func TestWorkerCatalogConcurrentRequestsShareNothing(t *testing.T) {
	f, worker := newFakeWorker(t)
	s := galleryServer(t, worker.URL)
	data := f.bytes["vid_vr180_lr"]
	var wg sync.WaitGroup
	errs := make(chan string, 64)
	for i := 0; i < 32; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			start := i % 50
			rec := assetThrough(s, http.MethodGet, "vid_vr180_lr", fmt.Sprintf("bytes=%d-%d", start, start+9))
			if rec.Code != 206 || !bytes.Equal(rec.Body.Bytes(), data[start:start+10]) {
				errs <- fmt.Sprintf("request %d: %d", i, rec.Code)
			}
			if i%4 == 0 {
				if rec := listThrough(s, "?limit=2"); rec.Code != 200 {
					errs <- fmt.Sprintf("list %d: %d", i, rec.Code)
				}
			}
		}(i)
	}
	wg.Wait()
	close(errs)
	for e := range errs {
		t.Error(e)
	}
}

func TestMediaCatalogFromEnvIsOffUnlessSwitchedOnWithASecretAndALoopbackWorker(t *testing.T) {
	t.Setenv("KALIV_MEDIA_INTERNAL_SECRET", testMediaSecret)
	t.Setenv("KALIV_MEDIA_JOBS_API", "")
	if MediaCatalogFromEnv("http://127.0.0.1:8000") != nil {
		t.Fatal("on without the switch")
	}
	t.Setenv("KALIV_MEDIA_JOBS_API", "1")
	if MediaCatalogFromEnv("http://127.0.0.1:8000") == nil {
		t.Fatal("off with the switch, a secret and a loopback worker")
	}
	for _, url := range []string{"http://192.168.1.10:8000", "http://example.com", "file:///etc"} {
		if MediaCatalogFromEnv(url) != nil {
			t.Errorf("on for a non-loopback worker %s", url)
		}
	}
	t.Setenv("KALIV_MEDIA_INTERNAL_SECRET", "short")
	if MediaCatalogFromEnv("http://127.0.0.1:8000") != nil {
		t.Fatal("on with an unusable secret")
	}
	// Off means the routes answer 503, never a 200 from an empty catalog.
	s := &server{Deps: Deps{Media: MediaCatalogFromEnv("http://127.0.0.1:8000")}}
	if rec := listThrough(s, ""); rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("off: %d", rec.Code)
	}
}
