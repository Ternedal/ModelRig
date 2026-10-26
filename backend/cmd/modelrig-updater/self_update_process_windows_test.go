//go:build windows

package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

func replacementFixture(t *testing.T) (string, string, string, string) {
	t.Helper()
	root := filepath.Join(t.TempDir(), "Anders's Rig")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	live := filepath.Join(root, updaterAssetName)
	pending := live + ".pending"
	lock := filepath.Join(root, "updater.lock")
	for path, value := range map[string]string{live: "original updater", pending: "verified replacement", lock: "owned by updater parent"} {
		if err := os.WriteFile(path, []byte(value), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	return live, pending, lock, filepath.Join(root, "logs", "updater-replacement.log")
}

func deadReplacementParent(t *testing.T) int {
	t.Helper()
	cmd := exec.Command("cmd.exe", "/c", "exit", "0")
	if err := cmd.Run(); err != nil {
		t.Fatal(err)
	}
	return cmd.Process.Pid
}

func waitForReplacementLog(t *testing.T, path, marker string) {
	t.Helper()
	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		b, _ := os.ReadFile(path)
		if strings.Contains(string(b), marker) {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	b, _ := os.ReadFile(path)
	t.Fatalf("replacement helper did not log %q; output: %s", marker, b)
}

func assertReplacementResult(t *testing.T, live, pending, lock string) {
	t.Helper()
	b, err := os.ReadFile(live)
	if err != nil || string(b) != "verified replacement" {
		t.Fatalf("installed updater = %q, %v", b, err)
	}
	for _, path := range []string{pending, lock} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Fatalf("completed replacement retained %s: %v", path, err)
		}
	}
	backups, err := filepath.Glob(live + ".previous-*")
	if err != nil || len(backups) != 1 {
		t.Fatalf("original updater backup = %v, %v", backups, err)
	}
	b, err = os.ReadFile(backups[0])
	if err != nil || string(b) != "original updater" {
		t.Fatalf("backup = %q, %v", b, err)
	}
}

func TestNativeReplacementHelperRetainsOriginalAndUnlocks(t *testing.T) {
	live, pending, lock, output := replacementFixture(t)
	parent := exec.Command(os.Args[0], "-test.run=^TestReplacementLauncherProcess$")
	parent.Env = append(os.Environ(), "MODELRIG_TEST_REPLACEMENT_ROOT="+filepath.Dir(live))
	if b, err := parent.CombinedOutput(); err != nil {
		t.Fatalf("replacement launcher failed: %v, %s", err, b)
	}
	waitForReplacementLog(t, output, "Updater replacement complete")
	assertReplacementResult(t, live, pending, lock)
}

func TestReplacementLauncherProcess(t *testing.T) {
	root := os.Getenv("MODELRIG_TEST_REPLACEMENT_ROOT")
	if root == "" {
		return
	}
	live := filepath.Join(root, updaterAssetName)
	if err := spawnWindowsReplacementHelper(os.Getpid(), live+".pending", live, filepath.Join(root, "updater.lock")); err != nil {
		t.Fatal(err)
	}
	os.Exit(0)
}

func TestNativeReplacementHelperRetriesWindowsSharingViolation(t *testing.T) {
	live, pending, lock, output := replacementFixture(t)
	path, err := syscall.UTF16PtrFromString(live)
	if err != nil {
		t.Fatal(err)
	}
	handle, err := syscall.CreateFile(path, syscall.GENERIC_READ, syscall.FILE_SHARE_READ|syscall.FILE_SHARE_WRITE, nil, syscall.OPEN_EXISTING, syscall.FILE_ATTRIBUTE_NORMAL, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer func() {
		if handle != syscall.InvalidHandle {
			_ = syscall.CloseHandle(handle)
		}
	}()
	if err := spawnWindowsReplacementHelper(deadReplacementParent(t), pending, live, lock); err != nil {
		t.Fatal(err)
	}
	waitForReplacementLog(t, output, "Replacement waiting for file handle release")
	if _, err := os.Stat(lock); err != nil {
		t.Fatalf("helper released lock before replacement: %v", err)
	}
	if err := syscall.CloseHandle(handle); err != nil {
		t.Fatal(err)
	}
	handle = syscall.InvalidHandle
	waitForReplacementLog(t, output, "Updater replacement complete")
	assertReplacementResult(t, live, pending, lock)
}

func TestNativeReplacementHelperLogsFailureAndKeepsLock(t *testing.T) {
	live, pending, lock, output := replacementFixture(t)
	if err := os.Remove(pending); err != nil {
		t.Fatal(err)
	}
	if err := spawnWindowsReplacementHelper(deadReplacementParent(t), pending, live, lock); err != nil {
		t.Fatal(err)
	}
	waitForReplacementLog(t, output, "Updater replacement failed")
	b, err := os.ReadFile(live)
	if err != nil || string(b) != "original updater" {
		t.Fatalf("failed helper changed live updater: %q, %v", b, err)
	}
	if _, err := os.Stat(lock); err != nil {
		t.Fatalf("failed helper lost lock evidence: %v", err)
	}
}
