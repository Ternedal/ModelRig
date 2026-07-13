// Package heartbeat is a tiny liveness signal shared by the supervisor and the
// updater. The supervisor writes a timestamp every supervision tick; the updater
// reads it after an update to confirm the supervisor is not merely started but
// still alive and looping. A supervisor that starts the children and then dies
// leaves the rig without crash-recovery even though both services still answer
// /healthz, so "backend + worker are up" is not enough on its own.
package heartbeat

import (
	"os"
	"strconv"
	"strings"
	"time"
)

// Write records the current time to path as unix seconds. Cheap enough to call
// on every tick.
func Write(path string) error {
	return os.WriteFile(path, []byte(strconv.FormatInt(time.Now().Unix(), 10)), 0o644)
}

// Read returns the time recorded in path.
func Read(path string) (time.Time, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return time.Time{}, err
	}
	sec, err := strconv.ParseInt(strings.TrimSpace(string(b)), 10, 64)
	if err != nil {
		return time.Time{}, err
	}
	return time.Unix(sec, 0), nil
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
