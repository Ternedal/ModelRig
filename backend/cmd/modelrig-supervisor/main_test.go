package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// fakeChild is a controllable stand-in for a real process, so the restart
// decision can be tested without spawning anything or opening a socket.
type fakeChild struct {
	nm        string
	run, hlth bool
	restarts  int
}

func (f *fakeChild) name() string  { return f.nm }
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

func TestChildProcessEnvRemovesSchedulerPrivateKeyFromWorker(t *testing.T) {
	got := childProcessEnv(
		[]string{"PATH=C:\\bin", "KALIV_SCHEDULER_APPROVAL_PRIVATE_KEY=parent-secret"},
		[]string{
			"KALIV_SCHEDULER_APPROVAL_PRIVATE_KEY=file-secret",
			"KALIV_SCHEDULER_APPROVAL_PUBLIC_KEY=public-key",
			"KALIV_SCHEDULER=1",
		},
		[]string{"kaliv_scheduler_approval_private_key"},
	)
	joined := strings.Join(got, "\n")
	if strings.Contains(joined, "PRIVATE_KEY") || strings.Contains(joined, "secret") {
		t.Fatalf("worker inherited the backend signing seed: %q", joined)
	}
	if !strings.Contains(joined, "KALIV_SCHEDULER_APPROVAL_PUBLIC_KEY=public-key") {
		t.Fatalf("worker lost the verification key: %q", joined)
	}
	if !strings.Contains(joined, "KALIV_SCHEDULER=1") || !strings.Contains(joined, "PATH=C:\\bin") {
		t.Fatalf("worker lost unrelated environment: %q", joined)
	}
}
