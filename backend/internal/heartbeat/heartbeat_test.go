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
	old := time.Now().Add(-10 * time.Minute).UnixMilli()
	os.WriteFile(p, []byte(strconv.FormatInt(old, 10)), 0o644)
	if ok, _ := Fresh(p, 30*time.Second); ok {
		t.Error("a 10-minute-old heartbeat should not be fresh")
	}

	// Missing file -> (false, error), i.e. "can't tell" counts as not alive.
	if ok, err := Fresh(filepath.Join(dir, "nope"), 30*time.Second); ok || err == nil {
		t.Errorf("a missing heartbeat should be not-fresh + error, got ok=%v err=%v", ok, err)
	}
}

func TestProveLooping_alive(t *testing.T) {
	p := filepath.Join(t.TempDir(), "hb")
	after := time.Now()
	// A background writer that keeps ticking -> the heartbeat advances.
	stop := make(chan struct{})
	go func() {
		for {
			select {
			case <-stop:
				return
			default:
				_ = Write(p)
				time.Sleep(20 * time.Millisecond)
			}
		}
	}()
	defer close(stop)
	ok, err := ProveLooping(p, after, 100*time.Millisecond, 2*time.Second)
	if err != nil || !ok {
		t.Errorf("a looping writer should prove alive: ok=%v err=%v", ok, err)
	}
}

func TestProveLooping_startedThenDied(t *testing.T) {
	p := filepath.Join(t.TempDir(), "hb")
	after := time.Now().Add(-1 * time.Second)
	// One heartbeat, at/after `after`, then nothing more (startup-then-die).
	if err := Write(p); err != nil {
		t.Fatal(err)
	}
	ok, err := ProveLooping(p, after, 60*time.Millisecond, 300*time.Millisecond)
	if ok || err == nil {
		t.Errorf("a write-once-then-die heartbeat must NOT prove looping: ok=%v err=%v", ok, err)
	}
}

func TestProveLooping_staleBeforeRestart(t *testing.T) {
	p := filepath.Join(t.TempDir(), "hb")
	// Heartbeat written BEFORE the restart moment -> must not count.
	if err := Write(p); err != nil {
		t.Fatal(err)
	}
	time.Sleep(10 * time.Millisecond)
	after := time.Now() // restart happens now; the file above predates it
	ok, err := ProveLooping(p, after, 30*time.Millisecond, 250*time.Millisecond)
	if ok || err == nil {
		t.Errorf("a pre-restart heartbeat must not count as alive: ok=%v err=%v", ok, err)
	}
}

func TestRemove(t *testing.T) {
	p := filepath.Join(t.TempDir(), "hb")
	Write(p)
	if err := Remove(p); err != nil {
		t.Fatal(err)
	}
	if _, err := Read(p); err == nil {
		t.Error("heartbeat should be gone after Remove")
	}
	// Removing a missing file is not an error.
	if err := Remove(p); err != nil {
		t.Errorf("removing a missing heartbeat should be a no-op, got %v", err)
	}
}
