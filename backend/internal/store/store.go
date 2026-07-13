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

// TakePairing atomically removes and returns a pairing (single-use). It fails
// closed: if the removal cannot be persisted, the code is restored in memory and
// (Pairing{}, false, err) is returned, so the caller does NOT issue a token for a
// claim that was never durably recorded as used.
func (s *Store) TakePairing(code string) (Pairing, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	p, ok := s.d.Pairings[code]
	if !ok {
		return Pairing{}, false, nil
	}
	delete(s.d.Pairings, code)
	if err := s.persistLocked(); err != nil {
		s.d.Pairings[code] = p // roll back: the code was NOT consumed
		return Pairing{}, false, err
	}
	return p, true, nil
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

// DeleteDevice removes a device by ID (revoke). It fails closed: if the removal
// cannot be persisted, the device list is restored and (false, err) is returned,
// so a revoke can never report success while the device survives a restart.
// Returns (true, nil) only when a device was removed and the change hit disk.
func (s *Store) DeleteDevice(id string) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	idx := -1
	for i := range s.d.Devices {
		if s.d.Devices[i].ID == id {
			idx = i
			break
		}
	}
	if idx == -1 {
		return false, nil
	}
	old := s.d.Devices
	next := append(append([]Device{}, old[:idx]...), old[idx+1:]...)
	s.d.Devices = next
	if err := s.persistLocked(); err != nil {
		s.d.Devices = old // roll back: revoke did NOT durably happen
		return false, err
	}
	return true, nil
}

// LastSeenPersistInterval bounds how often TouchByTokenHash rewrites the store.
// LastSeen is best-effort telemetry, not security state, so persisting it on
// every authenticated request (a full-file rewrite each time) is wasteful; we
// coarsen it to this granularity.
const LastSeenPersistInterval = 5 * time.Minute

// TouchByTokenHash finds a device by constant-time hash comparison and records
// LastSeen. Comparison is constant-time to avoid leaking hash bytes via timing.
// LastSeen is coarsened to LastSeenPersistInterval and its persistence is
// best-effort: a write failure here never fails the caller's request, because
// LastSeen carries no security decision (auth reads TokenHash, not LastSeen).
func (s *Store) TouchByTokenHash(hash string, now time.Time) (Device, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i := range s.d.Devices {
		if subtle.ConstantTimeCompare([]byte(s.d.Devices[i].TokenHash), []byte(hash)) == 1 {
			if now.Sub(s.d.Devices[i].LastSeen) >= LastSeenPersistInterval {
				s.d.Devices[i].LastSeen = now
				_ = s.persistLocked()
			}
			return s.d.Devices[i], true
		}
	}
	return Device{}, false
}

// RotateToken replaces a device's token hash by ID (used when re-issuing a token
// without re-pairing). The old hash stops validating immediately. It fails
// closed: if the new hash cannot be persisted, the old hash is restored and
// (Device{}, false, err) is returned, so a rotation prompted by a suspected
// token leak can never silently fail to take effect on disk (which would leave
// the old, leaked token valid again after a restart).
func (s *Store) RotateToken(id, newHash string) (Device, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i := range s.d.Devices {
		if s.d.Devices[i].ID == id {
			oldHash := s.d.Devices[i].TokenHash
			s.d.Devices[i].TokenHash = newHash
			if err := s.persistLocked(); err != nil {
				s.d.Devices[i].TokenHash = oldHash // roll back: rotation did NOT persist
				return Device{}, false, err
			}
			return s.d.Devices[i], true, nil
		}
	}
	return Device{}, false, nil
}
