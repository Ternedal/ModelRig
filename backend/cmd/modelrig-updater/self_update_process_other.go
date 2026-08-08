//go:build !windows

package main

import "fmt"

func spawnWindowsReplacementHelper(pid int, pending, live string) error {
	return fmt.Errorf("updater self-replacement requires Windows")
}
