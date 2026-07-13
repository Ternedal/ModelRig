package store

import (
	"path/filepath"
	"testing"
	"time"
)

// breakPersistence repoints the store at a path whose parent is a regular file,
// so the next persistLocked() (WriteFile to path+".tmp") fails with ENOTDIR.
// This simulates a disk/rename failure without relying on filesystem
// permissions -- the suite may run as root, where a chmod'd read-only dir is
// ignored and would NOT trigger a write error.
func breakPersistence(s *Store) {
	s.path = filepath.Join(s.path, "not-a-dir", "store.json")
}

func newTestStore(t *testing.T) *Store {
	t.Helper()
	s, err := Open(filepath.Join(t.TempDir(), "store.json"))
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	return s
}

func TestDeleteDevice_FailsClosedOnPersistError(t *testing.T) {
	s := newTestStore(t)
	if err := s.AddDevice(Device{ID: "d1", TokenHash: "h1"}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}
	breakPersistence(s)

	ok, err := s.DeleteDevice("d1")
	if err == nil {
		t.Fatal("DeleteDevice: expected a persist error, got nil")
	}
	if ok {
		t.Fatal("DeleteDevice reported success despite a persist failure (fail-open)")
	}
	// Rollback: the device must still be present and still authenticate, so a
	// revoke that did not hit disk cannot appear to have happened.
	if got := len(s.Devices()); got != 1 {
		t.Fatalf("device dropped in memory despite failed persist: have %d, want 1", got)
	}
	if _, found := s.TouchByTokenHash("h1", time.Now()); !found {
		t.Fatal("device no longer authenticates after a failed revoke; rollback failed")
	}
}

func TestDeleteDevice_HappyPath(t *testing.T) {
	s := newTestStore(t)
	if err := s.AddDevice(Device{ID: "d1", TokenHash: "h1"}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}
	ok, err := s.DeleteDevice("d1")
	if err != nil || !ok {
		t.Fatalf("DeleteDevice: ok=%v err=%v, want ok=true err=nil", ok, err)
	}
	if got := len(s.Devices()); got != 0 {
		t.Fatalf("device survived a successful revoke: have %d, want 0", got)
	}
}

func TestRotateToken_FailsClosedOnPersistError(t *testing.T) {
	s := newTestStore(t)
	if err := s.AddDevice(Device{ID: "d1", TokenHash: "old"}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}
	breakPersistence(s)

	_, ok, err := s.RotateToken("d1", "new")
	if err == nil {
		t.Fatal("RotateToken: expected a persist error, got nil")
	}
	if ok {
		t.Fatal("RotateToken reported success despite a persist failure (fail-open)")
	}
	// Half-rotated state is the danger: the old (possibly leaked) hash must
	// still validate and the new hash must NOT, since the rotation never became
	// durable. The caller got an error and can retry.
	if _, found := s.TouchByTokenHash("old", time.Now()); !found {
		t.Fatal("old hash stopped validating after a failed rotation; rollback failed")
	}
	if _, found := s.TouchByTokenHash("new", time.Now()); found {
		t.Fatal("new hash validates even though the rotation was not persisted")
	}
}

func TestTakePairing_FailsClosedOnPersistError(t *testing.T) {
	s := newTestStore(t)
	if err := s.PutPairing(Pairing{Code: "AAAA-BBBB", ExpiresAt: time.Now().Add(time.Hour)}); err != nil {
		t.Fatalf("PutPairing: %v", err)
	}
	breakPersistence(s)

	_, ok, err := s.TakePairing("AAAA-BBBB")
	if err == nil {
		t.Fatal("TakePairing: expected a persist error, got nil")
	}
	if ok {
		t.Fatal("TakePairing reported the code consumed despite a persist failure (fail-open)")
	}
	// The code must remain claimable (a token was never issued for it), rather
	// than being silently lost.
	if _, stillThere := s.d.Pairings["AAAA-BBBB"]; !stillThere {
		t.Fatal("pairing code dropped in memory despite failed persist; rollback failed")
	}
}

func TestTakePairing_HappyPathIsSingleUse(t *testing.T) {
	s := newTestStore(t)
	if err := s.PutPairing(Pairing{Code: "AAAA-BBBB", ExpiresAt: time.Now().Add(time.Hour)}); err != nil {
		t.Fatalf("PutPairing: %v", err)
	}
	if _, ok, err := s.TakePairing("AAAA-BBBB"); err != nil || !ok {
		t.Fatalf("first TakePairing: ok=%v err=%v, want ok=true err=nil", ok, err)
	}
	if _, ok, _ := s.TakePairing("AAAA-BBBB"); ok {
		t.Fatal("the same code was consumed twice (not single-use)")
	}
}

func TestTouchByTokenHash_ThrottlesPersistence(t *testing.T) {
	s := newTestStore(t)
	base := time.Now()
	if err := s.AddDevice(Device{ID: "d1", TokenHash: "h1", LastSeen: base}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}
	// Break persistence after the device is on disk. LastSeen writes are
	// best-effort, so a broken path must never surface as an error or panic.
	breakPersistence(s)

	// Sub-interval touch: LastSeen must NOT advance (no persist attempted).
	if _, ok := s.TouchByTokenHash("h1", base.Add(time.Minute)); !ok {
		t.Fatal("device did not authenticate on sub-interval touch")
	}
	if got := s.Devices()[0].LastSeen; !got.Equal(base) {
		t.Fatalf("LastSeen advanced within throttle window: got %v, want %v", got, base)
	}

	// Past-interval touch: LastSeen advances; the (failing) persist is swallowed.
	adv := base.Add(LastSeenPersistInterval + time.Second)
	if _, ok := s.TouchByTokenHash("h1", adv); !ok {
		t.Fatal("device did not authenticate on past-interval touch")
	}
	if got := s.Devices()[0].LastSeen; !got.Equal(adv) {
		t.Fatalf("LastSeen did not advance past throttle window: got %v, want %v", got, adv)
	}
}
