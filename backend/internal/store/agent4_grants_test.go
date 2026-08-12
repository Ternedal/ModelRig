package store

import (
	"path/filepath"
	"testing"
	"time"
)

func openAgent4GrantTestStore(t *testing.T) *Store {
	t.Helper()
	store, err := Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	if err := store.AddDevice(Device{
		ID:        "device-1",
		Name:      "Pixel",
		TokenHash: "hash",
		CreatedAt: time.Unix(1, 0).UTC(),
		LastSeen:  time.Unix(1, 0).UTC(),
		Grants:    []string{"other:read"},
	}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}
	return store
}

func deviceByID(t *testing.T, store *Store, id string) Device {
	t.Helper()
	for _, device := range store.Devices() {
		if device.ID == id {
			return device
		}
	}
	t.Fatalf("device %q not found", id)
	return Device{}
}

func TestSetAgent4ReadGrantAddRevokeAndPersist(t *testing.T) {
	path := filepath.Join(t.TempDir(), "state.json")
	store, err := Open(path)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	if err := store.AddDevice(Device{
		ID:        "device-1",
		Name:      "Pixel",
		TokenHash: "hash",
		CreatedAt: time.Unix(1, 0).UTC(),
		LastSeen:  time.Unix(1, 0).UTC(),
		Grants:    []string{"other:read"},
	}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}

	device, found, changed, err := store.SetAgent4ReadGrant("device-1", true)
	if err != nil || !found || !changed {
		t.Fatalf("grant: device=%+v found=%v changed=%v err=%v", device, found, changed, err)
	}
	if !device.HasGrant(agent4ReadGrant) || !device.HasGrant("other:read") {
		t.Fatalf("grant result lost expected grants: %+v", device.Grants)
	}

	_, found, changed, err = store.SetAgent4ReadGrant("device-1", true)
	if err != nil || !found || changed {
		t.Fatalf("duplicate grant must be idempotent: found=%v changed=%v err=%v", found, changed, err)
	}

	reopened, err := Open(path)
	if err != nil {
		t.Fatalf("reopen after grant: %v", err)
	}
	persisted := deviceByID(t, reopened, "device-1")
	if !persisted.HasGrant(agent4ReadGrant) || !persisted.HasGrant("other:read") {
		t.Fatalf("grant did not persist: %+v", persisted.Grants)
	}

	device, found, changed, err = reopened.SetAgent4ReadGrant("device-1", false)
	if err != nil || !found || !changed {
		t.Fatalf("revoke: device=%+v found=%v changed=%v err=%v", device, found, changed, err)
	}
	if device.HasGrant(agent4ReadGrant) || !device.HasGrant("other:read") {
		t.Fatalf("revoke changed wrong grants: %+v", device.Grants)
	}

	_, found, changed, err = reopened.SetAgent4ReadGrant("device-1", false)
	if err != nil || !found || changed {
		t.Fatalf("duplicate revoke must be idempotent: found=%v changed=%v err=%v", found, changed, err)
	}

	reopenedAgain, err := Open(path)
	if err != nil {
		t.Fatalf("reopen after revoke: %v", err)
	}
	persisted = deviceByID(t, reopenedAgain, "device-1")
	if persisted.HasGrant(agent4ReadGrant) || !persisted.HasGrant("other:read") {
		t.Fatalf("revoke did not persist exactly: %+v", persisted.Grants)
	}
}

func TestSetAgent4ReadGrantUnknownDeviceIsFailClosed(t *testing.T) {
	store := openAgent4GrantTestStore(t)
	device, found, changed, err := store.SetAgent4ReadGrant("missing", true)
	if err != nil || found || changed || device.ID != "" {
		t.Fatalf("unknown device result drifted: device=%+v found=%v changed=%v err=%v", device, found, changed, err)
	}
}

func TestSetAgent4ReadGrantRollsBackOnPersistenceFailure(t *testing.T) {
	store := openAgent4GrantTestStore(t)
	store.path = filepath.Join(t.TempDir(), "missing-parent", "state.json")

	_, found, changed, err := store.SetAgent4ReadGrant("device-1", true)
	if err == nil || !found || changed {
		t.Fatalf("persistence failure must fail closed: found=%v changed=%v err=%v", found, changed, err)
	}
	device := deviceByID(t, store, "device-1")
	if device.HasGrant(agent4ReadGrant) || !device.HasGrant("other:read") {
		t.Fatalf("in-memory grants were not rolled back: %+v", device.Grants)
	}
}
