// modelrig-supervisor keeps the Kaliv rig up without a person watching a
// terminal. It starts the worker and the server (in that order -- the server
// proxies the worker), then supervises both: if one exits or stops answering
// /healthz, it is restarted. Child output goes to size-rotated log files.
//
// It is a plain console exe so it fits the "prebuilt exe, no runtime on the rig"
// model. Task Scheduler runs it hidden at logon (scripts/kaliv-autostart.ps1),
// which is what makes Kaliv survive a reboot. This binary owns the "stays up"
// half of the appliance goal; controlled-update-with-rollback is a separate
// tool.
//
// The supervision DECISION (restart when dead-or-unhealthy, with a failure
// tolerance so one slow health poll doesn't bounce a healthy process) lives in
// superviseOnce, which is unit-tested against fakes. The process/HTTP wiring
// around it is thin and is verified on the rig.
package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"sync"
	"time"
)

// child is the seam that makes the loop testable: the real implementation shells
// out and polls HTTP; the test implementation is a controllable fake.
type child interface {
	name() string
	running() bool  // is the process currently alive?
	healthy() bool  // does its health endpoint answer OK?
	restart() error // (re)start it, replacing any previous process
}

// superviseOnce runs one supervision pass. A child is restarted when it is not
// running, or when it has been unhealthy for maxFails consecutive passes (a
// single failed poll -- a GC pause, a busy moment -- must not bounce a process
// that is actually fine). Returns the updated failure counters. Pure enough to
// test: it calls only the child interface and reports what it did.
func superviseOnce(children []child, fails map[string]int, maxFails int, restarted *[]string) map[string]int {
	if fails == nil {
		fails = map[string]int{}
	}
	for _, c := range children {
		if !c.running() {
			fails[c.name()] = 0
			if err := c.restart(); err != nil {
				log.Printf("supervisor: restart %s failed: %v", c.name(), err)
			} else {
				log.Printf("supervisor: %s was not running -> restarted", c.name())
				if restarted != nil {
					*restarted = append(*restarted, c.name())
				}
			}
			continue
		}
		if c.healthy() {
			fails[c.name()] = 0
			continue
		}
		fails[c.name()]++
		log.Printf("supervisor: %s unhealthy (%d/%d)", c.name(), fails[c.name()], maxFails)
		if fails[c.name()] >= maxFails {
			fails[c.name()] = 0
			if err := c.restart(); err != nil {
				log.Printf("supervisor: restart %s failed: %v", c.name(), err)
			} else {
				log.Printf("supervisor: %s unhealthy -> restarted", c.name())
				if restarted != nil {
					*restarted = append(*restarted, c.name())
				}
			}
		}
	}
	return fails
}

// --- real child: an exe with a /healthz, output to a rotating log ------------

type procChild struct {
	label     string
	exePath   string
	workDir   string
	healthURL string
	logPath   string
	logMaxMB  int64
	extraEnv  []string

	mu  sync.Mutex
	cmd *exec.Cmd
}

func (p *procChild) name() string { return p.label }

func (p *procChild) running() bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.cmd == nil || p.cmd.Process == nil {
		return false
	}
	// ProcessState is set once the process has exited (we Wait in a goroutine).
	return p.cmd.ProcessState == nil
}

func (p *procChild) healthy() bool {
	client := http.Client{Timeout: 4 * time.Second}
	resp, err := client.Get(p.healthURL)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, resp.Body)
	return resp.StatusCode == http.StatusOK
}

func (p *procChild) restart() error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.cmd != nil && p.cmd.Process != nil && p.cmd.ProcessState == nil {
		_ = p.cmd.Process.Kill()
	}
	if err := rotateLog(p.logPath, p.logMaxMB*1024*1024); err != nil {
		log.Printf("supervisor: log rotate for %s: %v", p.label, err)
	}
	f, err := os.OpenFile(p.logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return fmt.Errorf("open log: %w", err)
	}
	cmd := exec.Command(p.exePath)
	cmd.Dir = p.workDir
	if len(p.extraEnv) > 0 {
		cmd.Env = append(os.Environ(), p.extraEnv...)
	}
	cmd.Stdout = f
	cmd.Stderr = f
	if err := cmd.Start(); err != nil {
		f.Close()
		return fmt.Errorf("start %s: %w", p.exePath, err)
	}
	p.cmd = cmd
	// Reap the process so ProcessState is set on exit (running() reads it), and
	// close this run's log handle when the process ends.
	go func() { _ = cmd.Wait(); f.Close() }()
	return nil
}

// rotateLog renames path -> path.1 when it exceeds maxBytes, so an always-on
// process can't fill the disk with one ever-growing log. One generation is
// enough for "what just happened"; it is not an archive.
func rotateLog(path string, maxBytes int64) error {
	if maxBytes <= 0 {
		return nil
	}
	info, err := os.Stat(path)
	if err != nil {
		return nil // no file yet, nothing to rotate
	}
	if info.Size() < maxBytes {
		return nil
	}
	// Windows Rename won't overwrite an existing target, so a second rotation
	// would fail and the log would grow unbounded. Drop the old .1 first.
	_ = os.Remove(path + ".1")
	return os.Rename(path, path+".1")
}

func main() {
	root, _ := os.Getwd()
	serverExe := flag.String("server", filepath.Join(root, "modelrig-server-windows-x64.exe"), "path to the server exe")
	workerExe := flag.String("worker", filepath.Join(root, "worker", "modelrig-worker-windows-x64.exe"), "path to the worker exe")
	serverHealth := flag.String("server-health", "http://127.0.0.1:8080/healthz", "server health URL")
	workerHealth := flag.String("worker-health", "http://127.0.0.1:8099/healthz", "worker health URL")
	logDir := flag.String("logs", filepath.Join(root, "logs"), "directory for child logs")
	envFile := flag.String("env", filepath.Join(root, "modelrig.env"), "KEY=VALUE file of env vars for the children (e.g. MODELRIG_HOST=0.0.0.0)")
	every := flag.Duration("interval", 10*time.Second, "supervision interval")
	maxFails := flag.Int("max-fails", 3, "consecutive unhealthy polls before restart")
	logMB := flag.Int64("log-max-mb", 20, "rotate a child log when it passes this size (MB)")
	minFreeGB := flag.Float64("min-free-gb", 5, "warn when free disk falls below this (GB)")
	vramPct := flag.Float64("vram-warn-pct", 95, "warn when VRAM usage exceeds this (%)")
	resEvery := flag.Duration("resource-cooldown", 10*time.Minute, "minimum gap between repeats of the same resource warning")
	flag.Parse()

	if err := os.MkdirAll(*logDir, 0o755); err != nil {
		log.Fatalf("supervisor: cannot create log dir %s: %v", *logDir, err)
	}
	log.SetPrefix("supervisor: ")
	log.SetFlags(log.LstdFlags)
	// The supervisor's OWN log. A hidden Scheduled Task discards stderr, so
	// without this its warnings and restart notices go nowhere (the child logs
	// only hold the children's output). Rotated like them; also mirrored to
	// stderr for when the supervisor is run in a console.
	supLog := filepath.Join(*logDir, "supervisor.log")
	_ = rotateLog(supLog, *logMB*1024*1024)
	if lf, err := os.OpenFile(supLog, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644); err == nil {
		log.SetOutput(io.MultiWriter(lf, os.Stderr))
	}

	childEnv, err := loadEnvFile(*envFile)
	if err != nil {
		log.Fatalf("supervisor: bad env file %s: %v", *envFile, err)
	}
	if len(childEnv) > 0 {
		log.Printf("loaded %d env var(s) from %s for the children", len(childEnv), *envFile)
	} else {
		log.Printf("no env file at %s; children inherit the supervisor's environment (MODELRIG_HOST must be set for remote access)", *envFile)
	}
	worker := &procChild{
		label: "worker", exePath: *workerExe, workDir: filepath.Dir(*workerExe),
		healthURL: *workerHealth, logPath: filepath.Join(*logDir, "worker.log"), logMaxMB: *logMB,
		extraEnv: childEnv,
	}
	server := &procChild{
		label: "server", exePath: *serverExe, workDir: filepath.Dir(*serverExe),
		healthURL: *serverHealth, logPath: filepath.Join(*logDir, "server.log"), logMaxMB: *logMB,
		extraEnv: childEnv,
	}

	// Start the worker first and give it a moment to bind before the server
	// (which proxies it) comes up -- same ordering the manual launcher used.
	log.Printf("starting worker: %s", worker.exePath)
	if err := worker.restart(); err != nil {
		log.Printf("initial worker start failed: %v (the loop will retry)", err)
	}
	time.Sleep(2 * time.Second)
	log.Printf("starting server: %s", server.exePath)
	if err := server.restart(); err != nil {
		log.Printf("initial server start failed: %v (the loop will retry)", err)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()

	children := []child{worker, server}
	fails := map[string]int{}
	res := &resourceState{minFreeGB: *minFreeGB, vramWarnPct: *vramPct, cooldown: *resEvery, timeout: 3 * time.Second}
	ticker := time.NewTicker(*every)
	defer ticker.Stop()
	log.Printf("supervising every %s (restart after %d unhealthy polls); warn under %.0f GB free or over %.0f%% VRAM",
		*every, *maxFails, *minFreeGB, *vramPct)
	for {
		select {
		case <-ctx.Done():
			log.Printf("stopping; killing children")
			for _, c := range []*procChild{server, worker} {
				c.mu.Lock()
				if c.cmd != nil && c.cmd.Process != nil {
					_ = c.cmd.Process.Kill()
				}
				c.mu.Unlock()
			}
			return
		case <-ticker.C:
			fails = superviseOnce(children, fails, *maxFails, nil)
			res.run(time.Now()) // off the watchdog path; can't block health/restart
		}
	}
}
