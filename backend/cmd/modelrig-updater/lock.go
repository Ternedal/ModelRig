package main

// Single-instance lock. Two updaters running at once (a scheduled run plus a
// manual one) would interleave swaps, share .new/.old names, and race the
// journal -- so the whole run holds an exclusive lock file, created with
// O_EXCL (atomic: exactly one creator wins, on Windows too).
//
// Honest limitation: a hard crash (kill, power loss) strands the lock, and the
// next run fails closed with instructions rather than guessing staleness --
// after a crash you want to look anyway (the journal will also be present).
// A crash-proof Windows named mutex is the documented upgrade.

import (
	"fmt"
	"os"
	"time"
)

func acquireLock(path string) error {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
	if err != nil {
		info := ""
		if b, rerr := os.ReadFile(path); rerr == nil {
			info = " (" + string(b) + ")"
		}
		return fmt.Errorf("another updater appears to be running%s -- lock %s exists. If it crashed, delete the lock file and rerun", info, path)
	}
	fmt.Fprintf(f, "pid %d started %s", os.Getpid(), time.Now().Format(time.RFC3339))
	return f.Close()
}

func releaseLock(path string) { _ = os.Remove(path) }
