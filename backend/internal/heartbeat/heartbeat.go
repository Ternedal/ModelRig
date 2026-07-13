// Package heartbeat is a tiny liveness signal shared by the supervisor and the
// updater. The supervisor writes a timestamp every supervision tick; the updater
// reads it after an update to confirm the supervisor is not merely started but
// still alive and looping. A supervisor that starts the children and then dies
// leaves the rig without crash-recovery even though both services still answer
// /healthz, so "backend + worker are up" is not enough on its own.
package heartbeat

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// Write records the current time to path as unix seconds. Cheap enough to call
// on every tick.
func Write(path string) error {
	return os.WriteFile(path, []byte(strconv.FormatInt(time.Now().UnixMilli(), 10)), 0o644)
}

// Read returns the time recorded in path.
func Read(path string) (time.Time, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return time.Time{}, err
	}
	ms, err := strconv.ParseInt(strings.TrimSpace(string(b)), 10, 64)
	if err != nil {
		return time.Time{}, err
	}
	return time.UnixMilli(ms), nil
}

// Fresh reports whether the heartbeat at path was written within maxAge of now.
// A missing or malformed file returns (false, err): treat "can't tell" as "not
// alive", not as healthy.
func Fresh(path string, maxAge time.Duration) (bool, error) {
	t, err := Read(path)
	if err != nil {
		return false, err
	}
	return time.Since(t) <= maxAge, nil
}

// Remove deletes the heartbeat file if present. Used before a restart so a stale
// timestamp from the previous process can't be mistaken for the new one's.
func Remove(path string) error {
	err := os.Remove(path)
	if os.IsNotExist(err) {
		return nil
	}
	return err
}

// ProveLooping confirms the writer is alive AND still looping after a restart --
// a stronger check than Fresh, which a stale pre-restart file or a
// write-once-then-die process would both pass. It polls up to `settle` for a
// heartbeat written at/after `after` (so the previous process's file doesn't
// count), then waits `interval` and requires the heartbeat to have ADVANCED (a
// process that writes one heartbeat at startup and then dies does not pass).
// Returns (true, nil) only if both hold.
func ProveLooping(path string, after time.Time, interval, settle time.Duration) (bool, error) {
	deadline := time.Now().Add(settle)
	var first time.Time
	for {
		t, err := Read(path)
		if err == nil && !t.Before(after) {
			first = t
			break
		}
		if time.Now().After(deadline) {
			return false, fmt.Errorf("no heartbeat newer than the restart within %s", settle)
		}
		time.Sleep(500 * time.Millisecond)
	}
	time.Sleep(interval)
	second, err := Read(path)
	if err != nil {
		return false, err
	}
	if !second.After(first) {
		return false, fmt.Errorf("heartbeat did not advance: supervisor started but is not looping")
	}
	return true, nil
}
