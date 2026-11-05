package main

// Media executors (G2b, ModelRig #2296 6636146026): one Python process per
// configured GPU, `python -m app.media_executor_main --device cuda:N`, started
// and kept up by this supervisor next to the worker and the server.
//
// Why here and not in the worker: an executor must be able to die -- exit 70
// is how it hands retained VRAM and the GPU lease back to the OS -- without
// taking the API down. The worker entry point is forbidden to import the
// generation layer (tests/workflow_media_generation_boundary.py).
//
// Default off. Without KALIV_MEDIA_EXECUTOR=1 nothing here starts anything,
// and a refused configuration starts no executor while the worker and the
// server are supervised exactly as before.
//
// An executor has no HTTP endpoint: alive is healthy. What it does have is an
// exit code with a meaning (app/media_executor.py), and the restart decision
// is keyed on it -- executorRestartPolicy is the whole policy, as a pure
// function, so every code is unit-tested.

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

const (
	executorSwitchEnv  = "KALIV_MEDIA_EXECUTOR"
	executorDevicesEnv = "KALIV_MEDIA_EXECUTOR_DEVICES"
	// The media runtime (torch, diffusers) is not in the frozen worker, so the
	// operator names the interpreter of the media environment and the source
	// directory that contains app/media_executor_main.py.
	executorPythonEnv = "KALIV_MEDIA_EXECUTOR_PYTHON"
	executorAppDirEnv = "KALIV_MEDIA_EXECUTOR_APP_DIR"

	executorMaxDevices = 8
	executorBackoffCap = 5 * time.Minute
	// A run at least this long resets the back-off: it was working.
	executorStableRun = 5 * time.Minute
)

// Exit codes of app/media_executor.py (EXIT_*). Kept in step by hand; the
// Python side is the source of truth.
const (
	executorExitDone            = 0
	executorExitGPURetained     = 70
	executorExitDuplicate       = 73
	executorExitSinkUnavailable = 75
	executorExitUnrecorded      = 76
	executorExitConfig          = 78
)

var executorDevicePattern = regexp.MustCompile(`^cuda:(0|[1-9][0-9]?)$`)

type executorConfig struct {
	python  string
	appDir  string
	devices []string
}

// lookupChildEnv returns the value a child will see: the env file's last entry
// wins over the supervisor's own environment, exactly as exec does when
// procChild appends the file to os.Environ().
func lookupChildEnv(childEnv []string, getenv func(string) string, key string) string {
	for i := len(childEnv) - 1; i >= 0; i-- {
		if k, v, ok := strings.Cut(childEnv[i], "="); ok && k == key {
			return v
		}
	}
	return getenv(key)
}

// executorConfigFrom reads the executor configuration. (nil, nil) means off.
// Every error refuses ALL executors: a half-understood configuration must not
// start a process that holds a GPU.
func executorConfigFrom(childEnv []string, getenv func(string) string) (*executorConfig, error) {
	get := func(key string) string { return strings.TrimSpace(lookupChildEnv(childEnv, getenv, key)) }
	if get(executorSwitchEnv) != "1" {
		return nil, nil
	}
	var devices []string
	seen := map[string]bool{}
	for _, raw := range strings.Split(get(executorDevicesEnv), ",") {
		d := strings.TrimSpace(raw)
		if d == "" {
			continue
		}
		if !executorDevicePattern.MatchString(d) {
			return nil, fmt.Errorf("%s: %q is not cuda:N", executorDevicesEnv, d)
		}
		if seen[d] {
			return nil, fmt.Errorf("%s: %s is listed twice (one executor per GPU)", executorDevicesEnv, d)
		}
		seen[d] = true
		devices = append(devices, d)
	}
	if len(devices) == 0 {
		return nil, fmt.Errorf("%s=1 needs %s (for example cuda:0)", executorSwitchEnv, executorDevicesEnv)
	}
	if len(devices) > executorMaxDevices {
		return nil, fmt.Errorf("%s: at most %d devices", executorDevicesEnv, executorMaxDevices)
	}
	python := get(executorPythonEnv)
	if !filepath.IsAbs(python) {
		return nil, fmt.Errorf("%s must be an absolute path to the media environment's python", executorPythonEnv)
	}
	if info, err := os.Stat(python); err != nil || !info.Mode().IsRegular() {
		return nil, fmt.Errorf("%s: %s is not a file", executorPythonEnv, python)
	}
	appDir := get(executorAppDirEnv)
	if !filepath.IsAbs(appDir) {
		return nil, fmt.Errorf("%s must be an absolute path", executorAppDirEnv)
	}
	entry := filepath.Join(appDir, "app", "media_executor_main.py")
	if info, err := os.Stat(entry); err != nil || !info.Mode().IsRegular() {
		return nil, fmt.Errorf("%s: %s is missing", executorAppDirEnv, entry)
	}
	return &executorConfig{python: python, appDir: appDir, devices: devices}, nil
}

// executorDecision is what one exit means for the next start.
type executorDecision struct {
	restart bool
	delay   time.Duration
	why     string
}

// executorRestartPolicy maps an exit code, and how many restartable exits
// happened in a row (1 for the first), to the restart decision.
//
//	0   done: not restarted until the supervisor itself restarts
//	70  GPU memory not proven free: the OS freed it with the process; 5 s
//	73  another executor holds this GPU: never (a second one would fight it)
//	75  media volume unavailable: 30 s, doubling to 5 min; the executor
//	    re-verifies the volume on every start and exits 75 again at once
//	76  a publication was not recorded: 5 s; recovery marks the job
//	    "interrupted during publication" for reconciliation
//	78  configuration refused: never (restarting cannot fix it)
//	any other code, or killed: 5 s, doubling to 5 min
//
// Every restartable code doubles per consecutive exit and caps at 5 min, so a
// persistent fault cannot spin a GPU-loading process every tick.
func executorRestartPolicy(code, consecutive int) executorDecision {
	var base time.Duration
	var why string
	switch code {
	case executorExitDone:
		return executorDecision{why: "finished (exit 0); not restarted until the supervisor restarts"}
	case executorExitDuplicate:
		return executorDecision{why: "exit 73: another executor already holds this GPU; NOT restarted"}
	case executorExitConfig:
		return executorDecision{why: "exit 78: configuration refused (see its log); NOT restarted -- fix the configuration, then restart the supervisor"}
	case executorExitGPURetained:
		base, why = 5*time.Second, "exit 70: GPU memory was not proven free"
	case executorExitSinkUnavailable:
		base, why = 30*time.Second, "exit 75: the external media volume is not available"
	case executorExitUnrecorded:
		base, why = 5*time.Second, "exit 76: a publication was not recorded"
	default:
		base, why = 5*time.Second, fmt.Sprintf("exit %d: unexpected", code)
	}
	delay := base
	for i := 1; i < consecutive && delay < executorBackoffCap; i++ {
		delay *= 2
	}
	if delay > executorBackoffCap {
		delay = executorBackoffCap
	}
	return executorDecision{restart: true, delay: delay, why: why}
}

// executorChild is a procChild plus the exit-code policy. Its policy state is
// touched only by the supervision loop; the process state it reads is guarded
// by the procChild's mutex.
type executorChild struct {
	p   *procChild
	now func() time.Time

	seenRun     int // the procChild run whose exit was last decided
	consecutive int
	restartable bool
	notBefore   time.Time
}

func executorLabel(device string) string {
	// No ':' in a Windows file name, and the label names the log file.
	return "executor-" + strings.ReplaceAll(device, ":", "")
}

func newExecutorChild(cfg *executorConfig, device, logDir string, logMaxMB int64, childEnv []string, tree *processTree) *executorChild {
	label := executorLabel(device)
	return &executorChild{
		p: &procChild{
			label:    label,
			exePath:  cfg.python,
			args:     []string{"-u", "-m", "app.media_executor_main", "--device", device},
			workDir:  cfg.appDir,
			logPath:  filepath.Join(logDir, label+".log"),
			logMaxMB: logMaxMB,
			extraEnv: childEnv,
			tree:     tree,
		},
		now: time.Now,
	}
}

func (e *executorChild) name() string     { return e.p.name() }
func (e *executorChild) running() bool    { return e.p.running() }
func (e *executorChild) healthy() bool    { return true } // no endpoint: alive is healthy
func (e *executorChild) restart() error   { return e.p.restart() }
func (e *executorChild) exitNote() string { return e.p.exitNote() }

// restartHeld is called by superviseOnce for a child that is not running. It
// decides each exit once (and returns a line to log only then), and afterwards
// holds the restart until the back-off has passed -- or for good.
func (e *executorChild) restartHeld() (bool, string) {
	e.p.mu.Lock()
	runs, code, started, exited := e.p.runs, e.p.lastCode, e.p.startedAt, e.p.exitedAt
	e.p.mu.Unlock()
	if runs == 0 {
		return false, "" // never started: start it
	}
	now := e.now()
	if runs != e.seenRun {
		e.seenRun = runs
		if exited.Sub(started) >= executorStableRun {
			e.consecutive = 0
		}
		e.consecutive++
		d := executorRestartPolicy(code, e.consecutive)
		e.restartable = d.restart
		if !d.restart {
			return true, d.why
		}
		e.notBefore = exited.Add(d.delay)
		if !now.Before(e.notBefore) {
			return false, d.why + "; restarting"
		}
		return true, fmt.Sprintf("%s; restart in %s", d.why, e.notBefore.Sub(now).Round(time.Second))
	}
	if !e.restartable {
		return true, ""
	}
	return now.Before(e.notBefore), ""
}

// executorsFrom builds the executor children, or none. A refused configuration
// is returned as an error for the supervisor to log; it never stops the
// supervisor, whose first job is the worker and the server.
func executorsFrom(childEnv []string, getenv func(string) string, logDir string, logMaxMB int64, tree *processTree) ([]*executorChild, error) {
	cfg, err := executorConfigFrom(childEnv, getenv)
	if err != nil || cfg == nil {
		return nil, err
	}
	out := make([]*executorChild, 0, len(cfg.devices))
	for _, d := range cfg.devices {
		out = append(out, newExecutorChild(cfg, d, logDir, logMaxMB, childEnv, tree))
	}
	return out, nil
}
