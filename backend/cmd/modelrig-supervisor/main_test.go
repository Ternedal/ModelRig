package main

import (
	"os"
	"path/filepath"
	"testing"
)

// fakeChild is a controllable stand-in for a real process, so the restart
// decision can be tested without spawning anything or opening a socket.
type fakeChild struct {
	nm        string
	run, hlth bool
	restarts  int
}

func (f *fakeChild) name() string { return f.nm }
func (f *fakeChild) running() bool { return f.run }
func (f *fakeChild) healthy() bool { return f.hlth }
func (f *fakeChild) restart() error {
	f.restarts++
	f.run, f.hlth = true, true
	return nil
}

func TestSuperviseOnce_HealthyStaysUp(t *testing.T) {
	c := &fakeChild{nm: "w", run: true, hlth: true}
	fails := superviseOnce([]child{c}, map[string]int{"w": 2}, 3, nil)
	if c.restarts != 0 {
		t.Fatalf("healthy child restarted %d times", c.restarts)
	}
	if fails["w"] != 0 {
		t.Fatalf("healthy child should reset fail count, got %d", fails["w"])
	}
}

func TestSuperviseOnce_DeadRestartsImmediately(t *testing.T) {
	c := &fakeChild{nm: "w", run: false, hlth: false}
	var restarted []string
	superviseOnce([]child{c}, nil, 3, &restarted)
	if c.restarts != 1 {
		t.Fatalf("dead child should restart once, got %d", c.restarts)
	}
	if len(restarted) != 1 || restarted[0] != "w" {
		t.Fatalf("restart not reported: %v", restarted)
	}
}

func TestSuperviseOnce_UnhealthyToleratedThenRestarts(t *testing.T) {
	c := &fakeChild{nm: "w", run: true, hlth: false}
	fails := map[string]int{}
	// A running-but-unhealthy child is tolerated up to maxFails (a single slow
	// poll must not bounce a healthy process).
	fails = superviseOnce([]child{c}, fails, 3, nil)
	fails = superviseOnce([]child{c}, fails, 3, nil)
	if c.restarts != 0 {
		t.Fatalf("restarted before maxFails: restarts=%d fails=%d", c.restarts, fails["w"])
	}
	if fails["w"] != 2 {
		t.Fatalf("fail count = %d, want 2", fails["w"])
	}
	// The third consecutive failure crosses the threshold.
	fails = superviseOnce([]child{c}, fails, 3, nil)
	if c.restarts != 1 {
		t.Fatalf("should restart at maxFails, restarts=%d", c.restarts)
	}
	if fails["w"] != 0 {
		t.Fatalf("fail count should reset after restart, got %d", fails["w"])
	}
}

func TestRotateLog(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "x.log")
	if err := os.WriteFile(p, []byte("0123456789"), 0o644); err != nil { // 10 bytes
		t.Fatal(err)
	}
	// Below threshold: nothing happens.
	if err := rotateLog(p, 100); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(p + ".1"); !os.IsNotExist(err) {
		t.Fatalf("rotated a file below the threshold")
	}
	// Above threshold: the current log moves to .1.
	if err := rotateLog(p, 5); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(p + ".1"); err != nil {
		t.Fatalf("expected %s.1 after rotation: %v", p, err)
	}
	if _, err := os.Stat(p); !os.IsNotExist(err) {
		t.Fatalf("original log should be moved after rotation")
	}
}

// A child that dies immediately after a successful Start() must leave a trace.
//
// On the rig, a supervisor logged "server was not running -> restarted" every
// 10 seconds for seven minutes while no server process existed, port 8080 was
// free, and the exe started fine by hand. restart() reports only whether
// Start() succeeded, so "died on startup" and "never started" produced the
// identical line -- and the log could not distinguish them. procChild now
// records how the previous child ended, and superviseOnce reads it BEFORE
// restarting (restart clears it for the new child).
func TestSuperviseOnce_ReportsHowThePreviousChildDied(t *testing.T) {
	p := &procChild{label: "server"}
	p.alive = false
	p.lastExit = "pid 4242: exit status 3"

	if got := exitNoteOf(p); got != "pid 4242: exit status 3" {
		t.Fatalf("exit note not surfaced to the loop: %q", got)
	}
	// A fake that cannot answer must not break the loop.
	if got := exitNoteOf(&fakeChild{nm: "w"}); got != "" {
		t.Fatalf("child without exitNote should report nothing, got %q", got)
	}
}

// running() must not consult cmd.ProcessState: Wait() writes it from the reaper
// goroutine without holding mu, which raced the restart decision itself.
func TestProcChild_RunningReadsGuardedState(t *testing.T) {
	p := &procChild{label: "worker"}
	if p.running() {
		t.Fatal("a child that was never started must not report running")
	}
	p.alive = true
	if !p.running() {
		t.Fatal("a started child must report running")
	}
	p.alive = false
	if p.running() {
		t.Fatal("a reaped child must not report running")
	}
}
