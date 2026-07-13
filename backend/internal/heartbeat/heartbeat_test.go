package heartbeat

import (
	"os"
	"path/filepath"
	"strconv"
	"testing"
	"time"
)

func TestWriteReadRoundtrip(t *testing.T) {
	p := filepath.Join(t.TempDir(), "hb")
	if err := Write(p); err != nil {
		t.Fatal(err)
	}
	got, err := Read(p)
	if err != nil {
		t.Fatal(err)
	}
	if time.Since(got) > 5*time.Second {
		t.Errorf("read time is stale immediately after write: %v", got)
	}
}

func TestFresh(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "hb")

	// Just written -> fresh within a generous window.
	if err := Write(p); err != nil {
		t.Fatal(err)
	}
	if ok, err := Fresh(p, 30*time.Second); err != nil || !ok {
		t.Errorf("a just-written heartbeat should be fresh: ok=%v err=%v", ok, err)
	}

	// An old timestamp -> not fresh.
	old := time.Now().Add(-10 * time.Minute).Unix()
	os.WriteFile(p, []byte(strconv.FormatInt(old, 10)), 0o644)
	if ok, _ := Fresh(p, 30*time.Second); ok {
		t.Error("a 10-minute-old heartbeat should not be fresh")
	}

	// Missing file -> (false, error), i.e. "can't tell" counts as not alive.
	if ok, err := Fresh(filepath.Join(dir, "nope"), 30*time.Second); ok || err == nil {
		t.Errorf("a missing heartbeat should be not-fresh + error, got ok=%v err=%v", ok, err)
	}
}
