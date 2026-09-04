//go:build windows

package main

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestWindowsAtomicRenameKeepsLivePresentUntilReplace(t *testing.T) {
	dir := t.TempDir()
	live := filepath.Join(dir, "app.exe")
	old := live + ".old"
	staged := live + ".new"
	if err := os.WriteFile(live, []byte("OLD"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(staged, []byte("NEW"), 0o644); err != nil {
		t.Fatal(err)
	}

	if err := windowsAtomicRename(live, old); err != nil {
		t.Fatal(err)
	}
	if got, err := os.ReadFile(live); err != nil || string(got) != "OLD" {
		t.Fatalf("live name disappeared or changed during backup: %q, %v", got, err)
	}
	if got, err := os.ReadFile(old); err != nil || string(got) != "OLD" {
		t.Fatalf("rollback copy missing or wrong: %q, %v", got, err)
	}

	if err := windowsAtomicRename(staged, live); err != nil {
		t.Fatal(err)
	}
	if got, err := os.ReadFile(live); err != nil || string(got) != "NEW" {
		t.Fatalf("live replacement missing or wrong: %q, %v", got, err)
	}
	if _, err := os.Stat(staged); !os.IsNotExist(err) {
		t.Fatalf("ReplaceFileW did not consume staged file: %v", err)
	}
	if got, err := os.ReadFile(old); err != nil || string(got) != "OLD" {
		t.Fatalf("explicit rollback copy was not preserved: %q, %v", got, err)
	}
}

func TestWindowsAtomicRenameRestoresOldOverExistingLive(t *testing.T) {
	dir := t.TempDir()
	live := filepath.Join(dir, "app.exe")
	old := live + ".old"
	if err := os.WriteFile(live, []byte("MIXED"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(old, []byte("OLD"), 0o644); err != nil {
		t.Fatal(err)
	}

	if err := windowsAtomicRename(old, live); err != nil {
		t.Fatal(err)
	}
	if got, err := os.ReadFile(live); err != nil || string(got) != "OLD" {
		t.Fatalf("rollback did not restore the original: %q, %v", got, err)
	}
	if _, err := os.Stat(old); !os.IsNotExist(err) {
		t.Fatalf("rollback source should be consumed after replacement: %v", err)
	}
}

func TestWindowsAtomicRenameRestoresOldWhenLiveIsMissing(t *testing.T) {
	dir := t.TempDir()
	live := filepath.Join(dir, "app.exe")
	old := live + ".old"
	if err := os.WriteFile(old, []byte("OLD"), 0o644); err != nil {
		t.Fatal(err)
	}

	if err := windowsAtomicRename(old, live); err != nil {
		t.Fatal(err)
	}
	if got, err := os.ReadFile(live); err != nil || string(got) != "OLD" {
		t.Fatalf("missing live name was not recovered: %q, %v", got, err)
	}
}

func TestAtomicSwapTreatsUnchangedLiveAsSuccessfulRollback(t *testing.T) {
	dir := t.TempDir()
	live := filepath.Join(dir, "app.exe")
	incoming := filepath.Join(dir, "incoming.exe")
	if err := os.WriteFile(live, []byte("OLD"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(incoming, []byte("NEW"), 0o644); err != nil {
		t.Fatal(err)
	}

	oldReplace := replaceFileFn
	replaceFileFn = func(replaced, replacement string) error {
		return errors.New("sharing violation")
	}
	defer func() { replaceFileFn = oldReplace }()

	err := atomicSwapInto(incoming, live)
	if err == nil {
		t.Fatal("swap should still report the original replacement failure")
	}
	if errors.Is(err, errRollbackFailed) {
		t.Fatalf("intact original was falsely reported as failed rollback: %v", err)
	}
	if got, readErr := os.ReadFile(live); readErr != nil || string(got) != "OLD" {
		t.Fatalf("live original was not preserved: %q, %v", got, readErr)
	}
	if _, statErr := os.Stat(live + ".old"); !os.IsNotExist(statErr) {
		t.Fatalf("proven duplicate rollback copy should be consumed: %v", statErr)
	}
	if _, statErr := os.Stat(live + ".new"); !os.IsNotExist(statErr) {
		t.Fatalf("failed staged replacement should be removed after safe rollback: %v", statErr)
	}
}
