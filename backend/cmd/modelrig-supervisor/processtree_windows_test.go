//go:build windows

package main

import (
	"os/exec"
	"testing"
	"time"
)

// alive reports whether a pid is still running, without waiting on it.
func alive(t *testing.T, pid int) bool {
	t.Helper()
	out, err := exec.Command(
		"tasklist", "/FI", "PID eq "+itoa(pid), "/NH", "/FO", "CSV",
	).Output()
	if err != nil {
		t.Fatalf("tasklist: %v", err)
	}
	// tasklist prints an "INFO: No tasks..." line when nothing matches, so a
	// quoted CSV row is the only positive signal.
	return len(out) > 0 && out[0] == '"'
}

func itoa(v int) string {
	if v == 0 {
		return "0"
	}
	var b [20]byte
	i := len(b)
	for v > 0 {
		i--
		b[i] = byte('0' + v%10)
		v /= 10
	}
	return string(b[i:])
}

// Closing the job must kill the children inside it.
//
// This is the half that matters most and the half a taskkill in restart() could
// never provide: when the supervisor itself is killed from outside -- which is
// exactly what stranded two orphaned workers on the rig, with the PyInstaller
// child still holding port 8099 -- Windows closes its handles, the job closes,
// and everything in it dies.
func TestProcessTree_ClosingTheJobKillsItsChildren(t *testing.T) {
	tree, err := newProcessTree()
	if err != nil {
		t.Skipf("job objects unavailable here: %v", err)
	}

	// cmd.exe spawning ping.exe is a real parent/child pair, which is the shape
	// that broke: killing the parent alone leaves the child running. (timeout.exe
	// would be the obvious choice but refuses to run with stdin redirected, which
	// is how `go test` starts it.)
	cmd := exec.Command("cmd.exe", "/c", "ping", "-n", "30", "127.0.0.1")
	if err := cmd.Start(); err != nil {
		t.Fatalf("start: %v", err)
	}
	pid := cmd.Process.Pid
	// Give Windows a moment to register the process before asking about it.
	time.Sleep(300 * time.Millisecond)
	defer func() {
		_ = cmd.Process.Kill()
		_, _ = cmd.Process.Wait()
	}()

	if err := tree.adopt(cmd.Process); err != nil {
		t.Fatalf("adopt: %v", err)
	}
	if !alive(t, pid) {
		t.Fatal("child should be running before the job closes")
	}

	if err := tree.Close(); err != nil {
		t.Fatalf("close: %v", err)
	}

	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		if !alive(t, pid) {
			return // killed by the job closing, which is the whole point
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatal("child survived the job closing; it would outlive the supervisor")
}

// A nil tree must be usable, because newProcessTree is allowed to fail and the
// supervisor must still start. A supervisor that refuses to run is worse than
// one whose cleanup is weaker.
func TestProcessTree_NilIsSafe(t *testing.T) {
	var tree *processTree
	if err := tree.adopt(nil); err != nil {
		t.Fatalf("nil tree adopt: %v", err)
	}
	if err := tree.Close(); err != nil {
		t.Fatalf("nil tree close: %v", err)
	}
}
