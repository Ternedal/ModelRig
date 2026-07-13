package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
	"time"

	"modelrig/internal/config"
	"modelrig/internal/store"
)

func pairStartServer(t *testing.T) *server {
	t.Helper()
	st, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	return &server{Deps: Deps{
		Cfg:   config.Config{PairingTTL: 5 * time.Minute},
		Store: st,
	}}
}

// req builds a pair/start request from a chosen remote address, optionally with
// an admin-key header.
func pairStartReq(remoteAddr, adminKey string) *http.Request {
	r := httptest.NewRequest(http.MethodPost, "/api/v1/pair/start", nil)
	r.RemoteAddr = remoteAddr
	if adminKey != "" {
		r.Header.Set("X-Admin-Key", adminKey)
	}
	return r
}

func mintedCode(t *testing.T, rec *httptest.ResponseRecorder) string {
	t.Helper()
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v (%s)", err, rec.Body.String())
	}
	code, _ := body["code"].(string)
	return code
}

// No admin key set: a loopback caller (the -pair CLI on the rig) may mint a code.
func TestPairStart_NoKey_LoopbackAllowed(t *testing.T) {
	s := pairStartServer(t)
	for _, addr := range []string{"127.0.0.1:5000", "[::1]:5000", "127.0.0.5:41000"} {
		rec := httptest.NewRecorder()
		s.handlePairStart(rec, pairStartReq(addr, ""))
		if rec.Code != http.StatusOK {
			t.Fatalf("loopback %s: got %d, want 200 (%s)", addr, rec.Code, rec.Body.String())
		}
		if mintedCode(t, rec) == "" {
			t.Fatalf("loopback %s: 200 but no code minted", addr)
		}
	}
}

// No admin key set: a REMOTE caller must be refused -- this is the P0. Without
// this, anyone on the tailnet/LAN could mint a code and claim a device token.
func TestPairStart_NoKey_RemoteRefused(t *testing.T) {
	s := pairStartServer(t)
	for _, addr := range []string{"192.168.1.50:5000", "100.88.91.64:5000", "10.0.0.2:5000"} {
		rec := httptest.NewRecorder()
		s.handlePairStart(rec, pairStartReq(addr, ""))
		if rec.Code != http.StatusForbidden {
			t.Fatalf("remote %s: got %d, want 403 (fail closed)", addr, rec.Code)
		}
	}
}

// Admin key set: a remote caller WITH the correct key may mint a code.
func TestPairStart_Key_CorrectAllowsRemote(t *testing.T) {
	t.Setenv("MODELRIG_ADMIN_KEY", "s3cret")
	s := pairStartServer(t)
	rec := httptest.NewRecorder()
	s.handlePairStart(rec, pairStartReq("192.168.1.50:5000", "s3cret"))
	if rec.Code != http.StatusOK {
		t.Fatalf("remote+correct key: got %d, want 200 (%s)", rec.Code, rec.Body.String())
	}
	if mintedCode(t, rec) == "" {
		t.Fatal("remote+correct key: 200 but no code minted")
	}
}

// Admin key set: a caller with a wrong or missing key is refused (401), even
// from loopback -- the key is mandatory once configured.
func TestPairStart_Key_WrongOrMissingRefused(t *testing.T) {
	t.Setenv("MODELRIG_ADMIN_KEY", "s3cret")
	s := pairStartServer(t)
	cases := []struct {
		name, addr, key string
	}{
		{"wrong key, remote", "192.168.1.50:5000", "nope"},
		{"missing key, remote", "192.168.1.50:5000", ""},
		{"wrong key, loopback", "127.0.0.1:5000", "nope"},
	}
	for _, c := range cases {
		rec := httptest.NewRecorder()
		s.handlePairStart(rec, pairStartReq(c.addr, c.key))
		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("%s: got %d, want 401", c.name, rec.Code)
		}
	}
}
