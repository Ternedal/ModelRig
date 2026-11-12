package httpapi

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// WorkerMediaCatalog is the production MediaCatalog (#2275 6819704169, design 6817417307).
//
// Go never reads the media volume itself. The worker (worker/app/media_gallery_api.py) is the
// only reader, because it holds both facts that decide what may be shown:
//
//   - ownership: only assets of the installation's completed jobs, from the job database;
//   - the volume: the production MountedMediaVolume (marker id, pinned identity, no network or
//     subst drive, not the system disk), with every file checked by require_descriptor.
//
// This adapter lists through GET /internal/media/assets and serves bytes through ranged GETs of
// /internal/media/assets/{id}, both loopback-only and with the internal secret. The worker's
// three states map one to one: 200/206 served, 404 ErrMediaNotFound (the same for "not yours"
// and "unknown"), anything else ErrMediaUnavailable (503). A 401 from the worker is a wrong
// internal secret, never a device pairing problem, so it is 503 here too.
type WorkerMediaCatalog struct {
	baseURL string
	secret  string
	client  *http.Client
}

// ErrMediaBadRequest is a refused query the device can fix (an unknown cursor): 400.
var ErrMediaBadRequest = errors.New("media query refused")

const (
	mediaWorkerListMaxBytes = 4 << 20
	mediaWorkerMetaTimeout  = 10 * time.Second
)

var mediaGalleryItemKeys = map[string]bool{
	"id": true, "kind": true, "mime_type": true, "created_at": true, "size_bytes": true, "width": true,
	"height": true, "duration_seconds": true, "projection": true, "stereo": true, "thumbnail_id": true,
	"thumbnail_url": true, "url": true, "playback": true,
}

var mediaServedTypes = map[string]bool{"video/mp4": true, "image/png": true, "image/jpeg": true, "image/webp": true}

var (
	mediaProjections = map[any]bool{"flat": true, "equirectangular_180": true, "equirectangular_360": true}
	mediaStereo      = map[any]bool{"mono": true, "left_right": true, "top_bottom": true}
	mediaCreatedAt   = regexp.MustCompile(`^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?Z$`)
)

// mediaWholeNumber: a JSON number that is a whole number within [min, max] (decoded as float64).
func mediaWholeNumber(value any, min, max float64) bool {
	number, ok := value.(float64)
	return ok && number >= min && number <= max && number == math.Trunc(number)
}

// NewWorkerMediaCatalog refuses a non-loopback worker or an unusable secret (nil, false).
func NewWorkerMediaCatalog(workerBaseURL, secret string) (*WorkerMediaCatalog, bool) {
	base := strings.TrimRight(strings.TrimSpace(workerBaseURL), "/")
	if !githubConnectorWorkerIsLoopback(base) || len(secret) < mediaJobsMinSecret || strings.ContainsAny(secret, "\r\n") {
		return nil, false
	}
	transport := &http.Transport{
		Proxy:                 nil, // loopback only: never through an environment proxy
		DialContext:           (&net.Dialer{Timeout: 2 * time.Second}).DialContext,
		ResponseHeaderTimeout: mediaWorkerMetaTimeout,
		IdleConnTimeout:       30 * time.Second,
		MaxIdleConnsPerHost:   4,
	}
	return &WorkerMediaCatalog{baseURL: base, secret: secret, client: &http.Client{
		Transport: transport,
		// The body of an asset streams for as long as the device reads; only the headers are
		// bounded (ResponseHeaderTimeout). Redirects are never followed.
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}}, true
}

// MediaCatalogFromEnv is what modelrig-server wires: the worker-backed catalog when the media API
// is switched on (KALIV_MEDIA_JOBS_API=1) with a usable KALIV_MEDIA_INTERNAL_SECRET and a loopback
// worker; otherwise nil, and the gallery routes answer 503.
func MediaCatalogFromEnv(workerBaseURL string) MediaCatalog {
	if !mediaJobsAPIEnabled() {
		return nil
	}
	secret, ok := mediaJobsSecret()
	if !ok {
		return nil
	}
	catalog, ok := NewWorkerMediaCatalog(workerBaseURL, secret)
	if !ok {
		return nil
	}
	return catalog
}

func (c *WorkerMediaCatalog) request(method, path string, header map[string]string) (*http.Response, error) {
	req, err := http.NewRequest(method, c.baseURL+path, nil)
	if err != nil {
		return nil, ErrMediaUnavailable
	}
	req.Header.Set(mediaJobsSecretHeader, c.secret)
	for name, value := range header {
		req.Header.Set(name, value)
	}
	resp, err := c.client.Do(req)
	if err != nil {
		return nil, ErrMediaUnavailable
	}
	return resp, nil
}

func drain(resp *http.Response) {
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 64<<10))
	_ = resp.Body.Close()
}

func (c *WorkerMediaCatalog) ListMedia(owner string, limit int, cursor string) ([]map[string]any, *string, error) {
	if owner != mediaInstallationOwner || limit < 1 || limit > 100 || validateMediaCursor(cursor) != nil {
		return nil, nil, ErrMediaUnavailable
	}
	query := url.Values{"limit": {strconv.Itoa(limit)}}
	if cursor != "" {
		query.Set("cursor", cursor)
	}
	resp, err := c.request(http.MethodGet, "/internal/media/assets?"+query.Encode(), map[string]string{"Accept": "application/json"})
	if err != nil {
		return nil, nil, err
	}
	defer drain(resp)
	switch resp.StatusCode {
	case http.StatusOK:
	case http.StatusBadRequest:
		return nil, nil, ErrMediaBadRequest
	default:
		return nil, nil, ErrMediaUnavailable
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, mediaWorkerListMaxBytes+1))
	if err != nil || len(body) > mediaWorkerListMaxBytes {
		return nil, nil, ErrMediaUnavailable
	}
	var page struct {
		Schema     string           `json:"schema"`
		Items      []map[string]any `json:"items"`
		NextCursor *string          `json:"next_cursor"`
	}
	decoder := json.NewDecoder(strings.NewReader(string(body)))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&page) != nil || page.Schema != "kaliv-media-gallery/v1" || page.Items == nil || len(page.Items) > limit {
		return nil, nil, ErrMediaUnavailable
	}
	// Exactly one document: anything after it (a second page, trailing garbage) is refused.
	if err := decoder.Decode(new(json.RawMessage)); !errors.Is(err, io.EOF) {
		return nil, nil, ErrMediaUnavailable
	}
	for _, item := range page.Items {
		if !validWorkerGalleryItem(item) {
			return nil, nil, ErrMediaUnavailable
		}
	}
	if page.NextCursor != nil && (!validMediaID(*page.NextCursor) || len(page.Items) == 0 ||
		page.Items[len(page.Items)-1]["id"] != *page.NextCursor) {
		return nil, nil, ErrMediaUnavailable
	}
	return page.Items, page.NextCursor, nil
}

// validWorkerGalleryItem checks the shape Android requires (MediaGalleryContract.parseItem) and that
// every link is the same-origin one for its own id: the worker never supplies another location.
func validWorkerGalleryItem(item map[string]any) bool {
	if len(item) != len(mediaGalleryItemKeys) {
		return false
	}
	for key := range item {
		if !mediaGalleryItemKeys[key] {
			return false
		}
	}
	id, ok := item["id"].(string)
	if !ok || !validMediaID(id) || item["url"] != "/api/v1/media/"+id {
		return false
	}
	mime, ok := item["mime_type"].(string)
	if !ok || !mediaServedTypes[mime] {
		return false
	}
	// The same rules as the worker's index check (worker/app/media_gallery_catalog.py _index) and
	// Android's parser: a worker regression is refused here, never passed on to the device.
	kind, ok := item["kind"].(string)
	if !ok || (kind != "image" && kind != "video") || (kind == "video") != (mime == "video/mp4") {
		return false
	}
	if !mediaWholeNumber(item["size_bytes"], 0, 1<<53-1) {
		return false
	}
	created, ok := item["created_at"].(string)
	if !ok || !mediaCreatedAt.MatchString(created) {
		return false
	}
	if parsed, err := time.Parse(time.RFC3339Nano, created); err != nil || parsed.Location() != time.UTC {
		return false
	}
	for _, key := range []string{"width", "height"} {
		if item[key] != nil && !mediaWholeNumber(item[key], 0, 2147483647) {
			return false
		}
	}
	switch duration := item["duration_seconds"].(type) {
	case nil:
	case float64:
		if kind == "image" || duration < 0 || math.IsInf(duration, 0) || math.IsNaN(duration) {
			return false
		}
	default:
		return false
	}
	if !mediaProjections[item["projection"]] || !mediaStereo[item["stereo"]] {
		return false
	}
	switch thumb := item["thumbnail_id"].(type) {
	case nil:
		if item["thumbnail_url"] != nil {
			return false
		}
	case string:
		if !validMediaID(thumb) || item["thumbnail_url"] != "/api/v1/media/"+thumb {
			return false
		}
	default:
		return false
	}
	playback, ok := item["playback"].(map[string]any)
	if !ok || len(playback) != 1 {
		return false
	}
	_, ok = playback["supports_range"].(bool)
	return ok
}

func (c *WorkerMediaCatalog) OpenMedia(owner, id string) (io.ReadSeekCloser, string, int64, error) {
	if owner != mediaInstallationOwner || !validMediaID(id) {
		return nil, "", 0, ErrMediaNotFound
	}
	resp, err := c.request(http.MethodHead, "/internal/media/assets/"+id, nil)
	if err != nil {
		return nil, "", 0, err
	}
	drain(resp)
	switch resp.StatusCode {
	case http.StatusOK:
	case http.StatusNotFound:
		return nil, "", 0, ErrMediaNotFound
	default:
		return nil, "", 0, ErrMediaUnavailable
	}
	mime := resp.Header.Get("Content-Type")
	size, err := strconv.ParseInt(resp.Header.Get("Content-Length"), 10, 64)
	if !mediaServedTypes[mime] || err != nil || size < 0 {
		return nil, "", 0, ErrMediaUnavailable
	}
	return &workerMediaAsset{catalog: c, id: id, mime: mime, size: size}, mime, size, nil
}

// workerMediaAsset reads one asset through ranged worker GETs. A Seek asks the worker for exactly
// bytes offset..size-1 and refuses any answer that is not that range of this size and type. A body
// that ends early is an error, never a short file.
type workerMediaAsset struct {
	catalog *WorkerMediaCatalog
	id      string
	mime    string
	size    int64
	offset  int64
	body    io.ReadCloser
}

var errSeekOutside = errors.New("seek outside the asset")

func (a *workerMediaAsset) Seek(offset int64, whence int) (int64, error) {
	// Bounds are checked before any addition (ChatGPT 6821058128): a.offset and a.size are in
	// [0, MaxInt64], so these comparisons cannot overflow, and an offset near MaxInt64 or
	// MinInt64 is refused instead of wrapping into an apparently valid position.
	var target int64
	switch whence {
	case io.SeekStart:
		if offset < 0 || offset > a.size {
			return a.offset, errSeekOutside
		}
		target = offset
	case io.SeekCurrent:
		if offset < -a.offset || offset > a.size-a.offset {
			return a.offset, errSeekOutside
		}
		target = a.offset + offset
	case io.SeekEnd:
		if offset > 0 || offset < -a.size {
			return a.offset, errSeekOutside
		}
		target = a.size + offset
	default:
		return a.offset, errors.New("invalid whence")
	}
	if target != a.offset && a.body != nil {
		_ = a.body.Close()
		a.body = nil
	}
	a.offset = target
	// The handler seeks before it commits any header: the ranged answer is fetched and checked
	// here, so a worker that cannot serve exactly this range is a 503, not a truncated 200.
	if a.body == nil && a.offset < a.size {
		if err := a.open(); err != nil {
			return a.offset, err
		}
	}
	return target, nil
}

func (a *workerMediaAsset) open() error {
	want := fmt.Sprintf("bytes %d-%d/%d", a.offset, a.size-1, a.size)
	resp, err := a.catalog.request(http.MethodGet, "/internal/media/assets/"+a.id,
		map[string]string{"Range": fmt.Sprintf("bytes=%d-%d", a.offset, a.size-1)})
	if err != nil {
		return err
	}
	if resp.StatusCode != http.StatusPartialContent || resp.Header.Get("Content-Range") != want ||
		resp.Header.Get("Content-Type") != a.mime ||
		resp.Header.Get("Content-Length") != strconv.FormatInt(a.size-a.offset, 10) {
		drain(resp)
		return ErrMediaUnavailable
	}
	a.body = resp.Body
	return nil
}

func (a *workerMediaAsset) Read(p []byte) (int, error) {
	if a.offset >= a.size {
		return 0, io.EOF
	}
	if a.body == nil {
		if err := a.open(); err != nil {
			return 0, err
		}
	}
	if remaining := a.size - a.offset; int64(len(p)) > remaining {
		p = p[:remaining]
	}
	n, err := a.body.Read(p)
	a.offset += int64(n)
	if errors.Is(err, io.EOF) && a.offset < a.size {
		return n, io.ErrUnexpectedEOF
	}
	if errors.Is(err, io.EOF) {
		err = nil
		if a.offset >= a.size {
			err = io.EOF
		}
	}
	return n, err
}

func (a *workerMediaAsset) Close() error {
	if a.body != nil {
		err := a.body.Close()
		a.body = nil
		return err
	}
	return nil
}
