package store

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"os"
	"sync"
	"time"
)

// Device is a paired client with a hashed token.
type Device struct {
	ID        string    `json:"id"`
	Name      string    `json:"name"`
	TokenHash string    `json:"token_hash"` // hex(sha256(token))
	CreatedAt time.Time `json:"created_at"`
	LastSeen  time.Time `json:"last_seen"`
}

// Pairing is a pending, single-use pairing code.
type Pairing struct {
	Code      string    `json:"code"`
	ExpiresAt time.Time `json:"expires_at"`
}

type data struct {
	Devices  []Device           `json:"devices"`
	Pairings map[string]Pairing `json:"pairings"`
}

// Store is a mutex-guarded JSON-file store.
//
// V1 tradeoff: a JSON file keeps the backend dependency-free (no cgo SQLite
// driver, no module downloads) and is trivially inspectable. It is fine for a
// handful of paired devices. Migrate to SQLite (modernc.org/sqlite, pure Go)
// when device counts or write frequency grow. See STATUS.md.
type Store struct {
	mu   sync.Mutex
	path string
	d    data
}

// Open loads the store from path, creating an empty file if absent.
func Open(path string) (*Store, error) {
	s := &Store{path: path, d: data{Pairings: map[string]Pairing{}}}
	b, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return s, s.persistLocked()
	}
	if err != nil {
		return nil, err
	}
	if err := json.Unmarshal(b, &s.d); err != nil {
		return nil, err
	}
	if s.d.Pairings == nil {
		s.d.Pairings = map[string]Pairing{}
	}
	return s, nil
}

func (s *Store) persistLocked() error {
	b, err := json.MarshalIndent(s.d, "", "  ")
	if err != nil {
		return err
	}
	tmp := s.path + ".tmp"
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, s.path)
}

// ---- Pairings ----

func (s *Store) PutPairing(p Pairing) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.d.Pairings[p.Code] = p
	return s.persistLocked()
}

// TakePairing atomically removes and returns a pairing (single-use).
func (s *Store) TakePairing(code string) (Pairing, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	p, ok := s.d.Pairings[code]
	if !ok {
		return Pairing{}, false
	}
	delete(s.d.Pairings, code)
	_ = s.persistLocked()
	return p, true
}

func (s *Store) PurgeExpiredPairings(now time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	changed := false
	for k, p := range s.d.Pairings {
		if now.After(p.ExpiresAt) {
			delete(s.d.Pairings, k)
			changed = true
		}
	}
	if changed {
		_ = s.persistLocked()
	}
}

// ---- Devices ----

func (s *Store) AddDevice(dv Device) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.d.Devices = append(s.d.Devices, dv)
	return s.persistLocked()
}

func (s *Store) Devices() []Device {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]Device, len(s.d.Devices))
	copy(out, s.d.Devices)
	return out
}

// DeleteDevice removes a device by ID (revoke). Returns true if one was removed.
func (s *Store) DeleteDevice(id string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i := range s.d.Devices {
		if s.d.Devices[i].ID == id {
			s.d.Devices = append(s.d.Devices[:i], s.d.Devices[i+1:]...)
			_ = s.persistLocked()
			return true
		}
	}
	return false
}

// TouchByTokenHash finds a device by constant-time hash comparison, updates its
// LastSeen, and returns it. Comparison is constant-time to avoid leaking hash
// bytes via timing.
func (s *Store) TouchByTokenHash(hash string, now time.Time) (Device, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i := range s.d.Devices {
		if subtle.ConstantTimeCompare([]byte(s.d.Devices[i].TokenHash), []byte(hash)) == 1 {
			s.d.Devices[i].LastSeen = now
			_ = s.persistLocked()
			return s.d.Devices[i], true
		}
	}
	return Device{}, false
}
