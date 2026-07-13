package main

import (
	"context"
	"fmt"
	"log"
	"os/exec"
	"strconv"
	"strings"
	"sync/atomic"
	"time"
)

// Resource-pressure warnings. An unattended rig that quietly fills its disk
// (models, logs, RAG index) or pins its VRAM fails in confusing ways, so the
// supervisor watches for it. Two rules the watchdog must never break:
//   - The check runs OFF the supervision path (its own goroutine) with a
//     timeout, so a hung nvidia-smi or PowerShell can never freeze health
//     polling and restarts -- an observation feature must not be able to blind
//     the watchdog it supplements.
//   - Warnings are rate-limited per resource (a full disk stays full).
// The parts easy to get wrong -- parsing nvidia-smi, deciding "too low/high" --
// are pure and unit-tested.

type resourceState struct {
	minFreeGB   float64
	vramWarnPct float64
	cooldown    time.Duration
	timeout     time.Duration
	lastDisk    time.Time
	lastVram    time.Time
	busy        atomic.Bool
}

// run launches a check without blocking the caller. If a previous check is still
// in flight (a hung query being killed by its timeout), this tick is skipped so
// checks can't pile up.
func (rs *resourceState) run(now time.Time) {
	if !rs.busy.CompareAndSwap(false, true) {
		return
	}
	go func() {
		defer rs.busy.Store(false)
		rs.check(now)
	}()
}

func (rs *resourceState) check(now time.Time) {
	ctx, cancel := context.WithTimeout(context.Background(), rs.timeout)
	defer cancel()
	if freeGB, err := freeDiskGB(ctx); err == nil {
		if warn, msg := shouldWarnDisk(freeGB, rs.minFreeGB); warn && now.Sub(rs.lastDisk) >= rs.cooldown {
			log.Printf("WARNING: %s", msg)
			rs.lastDisk = now
		}
	}
	if used, total, err := gpuMemory(ctx); err == nil {
		if warn, msg := shouldWarnVram(used, total, rs.vramWarnPct); warn && now.Sub(rs.lastVram) >= rs.cooldown {
			log.Printf("WARNING: %s", msg)
			rs.lastVram = now
		}
	}
}

// shouldWarnDisk decides whether free space on the ModelRig drive is low enough
// to act on. Below the floor, Ollama pulls and log writes start failing.
func shouldWarnDisk(freeGB, minFreeGB float64) (bool, string) {
	if freeGB < minFreeGB {
		return true, fmt.Sprintf(
			"low disk: %.1f GB free (< %.1f GB). Ollama pulls and log writes will start failing.",
			freeGB, minFreeGB)
	}
	return false, ""
}

// parseNvidiaSmi reads "used, total" (MiB) from the first line of nvidia-smi
// --query-gpu=memory.used,memory.total --format=csv,noheader,nounits.
func parseNvidiaSmi(out string) (used, total int, err error) {
	out = strings.TrimSpace(out)
	if out == "" {
		return 0, 0, fmt.Errorf("empty nvidia-smi output")
	}
	line := strings.SplitN(out, "\n", 2)[0]
	parts := strings.Split(line, ",")
	if len(parts) < 2 {
		return 0, 0, fmt.Errorf("unexpected nvidia-smi line: %q", line)
	}
	if used, err = strconv.Atoi(strings.TrimSpace(parts[0])); err != nil {
		return 0, 0, fmt.Errorf("used: %w", err)
	}
	if total, err = strconv.Atoi(strings.TrimSpace(parts[1])); err != nil {
		return 0, 0, fmt.Errorf("total: %w", err)
	}
	return used, total, nil
}

// shouldWarnVram decides whether VRAM usage is high enough to act on.
func shouldWarnVram(used, total int, warnPct float64) (bool, string) {
	if total <= 0 {
		return false, ""
	}
	pct := float64(used) / float64(total) * 100
	if pct >= warnPct {
		return true, fmt.Sprintf(
			"VRAM nearly full: %d/%d MiB (%.0f%%). A larger model may fail to load or fall back to CPU.",
			used, total, pct)
	}
	return false, ""
}

// --- the rig-side queries (Windows). exec.CommandContext bounds them, so a hung
// query is killed rather than freezing the caller. They only return real numbers
// on the rig; anywhere else they error and check() stays quiet. ---

func freeDiskGB(ctx context.Context) (float64, error) {
	out, err := exec.CommandContext(ctx, "powershell", "-NoProfile", "-Command",
		"[System.IO.DriveInfo]::new((Get-Location).Path).AvailableFreeSpace").Output()
	if err != nil {
		return 0, err
	}
	bytes, err := strconv.ParseFloat(strings.TrimSpace(string(out)), 64)
	if err != nil {
		return 0, err
	}
	return bytes / (1024 * 1024 * 1024), nil
}

func gpuMemory(ctx context.Context) (used, total int, err error) {
	out, err := exec.CommandContext(ctx, "nvidia-smi",
		"--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits").Output()
	if err != nil {
		return 0, 0, err
	}
	return parseNvidiaSmi(string(out))
}
