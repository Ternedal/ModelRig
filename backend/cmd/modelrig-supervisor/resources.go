package main

import (
	"fmt"
	"log"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

// Resource-pressure warnings. An unattended rig that quietly fills its disk
// (models, logs, RAG index) or pins its VRAM (a model too large for 12 GB) fails
// in confusing ways -- a pull that errors, a model that silently falls back to
// CPU. The supervisor already runs a loop, so it is the natural place to notice
// and say so in the log. The queries are Windows commands that run on the rig;
// the parts that are easy to get wrong -- parsing nvidia-smi, deciding when a
// number is "too low/high" -- live in the pure helpers below and are unit-tested.
//
// Warnings are rate-limited per resource (a full disk stays full; saying so every
// 10 s only buries the log), so the loop can call check() every tick cheaply.

type resourceState struct {
	minFreeGB   float64
	vramWarnPct float64
	cooldown    time.Duration
	lastDisk    time.Time
	lastVram    time.Time
}

func (rs *resourceState) check(now time.Time) {
	if freeGB, err := freeDiskGB(); err == nil {
		if warn, msg := shouldWarnDisk(freeGB, rs.minFreeGB); warn && now.Sub(rs.lastDisk) >= rs.cooldown {
			log.Printf("WARNING: %s", msg)
			rs.lastDisk = now
		}
	}
	if used, total, err := gpuMemory(); err == nil {
		if warn, msg := shouldWarnVram(used, total, rs.vramWarnPct); warn && now.Sub(rs.lastVram) >= rs.cooldown {
			log.Printf("WARNING: %s", msg)
			rs.lastVram = now
		}
	}
}

// shouldWarnDisk decides whether the free space on the ModelRig drive is low
// enough to act on. Below the floor, Ollama pulls and log writes start failing.
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

// --- the rig-side queries (Windows). They compile everywhere but only return
// real numbers on the rig; anywhere else they error and check() stays quiet. ---

func freeDiskGB() (float64, error) {
	// AvailableFreeSpace on the drive holding the working directory.
	out, err := exec.Command("powershell", "-NoProfile", "-Command",
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

func gpuMemory() (used, total int, err error) {
	out, err := exec.Command("nvidia-smi",
		"--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits").Output()
	if err != nil {
		return 0, 0, err
	}
	return parseNvidiaSmi(string(out))
}
