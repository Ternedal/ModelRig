//go:build windows

package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"modelrig/internal/config"
	"modelrig/internal/heartbeat"
)

// The package CI supplies its real frozen EXE plus the just-built supervisor
// and server. The delay models unpacking/scanning before the worker binds;
// both the production watchdog and production updater verifier must accept it.
func TestFrozenVoiceWorkerSlowBootUnderSupervisor(t *testing.T) {
	workerExe := os.Getenv("MODELRIG_COLD_BOOT_WORKER_EXE")
	if workerExe == "" {
		t.Skip("requires the frozen Windows package; exercised by windows-worker-package")
	}
	supervisorExe := os.Getenv("MODELRIG_COLD_BOOT_SUPERVISOR_EXE")
	serverExe := os.Getenv("MODELRIG_COLD_BOOT_SERVER_EXE")
	for _, exe := range []string{workerExe, supervisorExe, serverExe} {
		if _, err := os.Stat(exe); err != nil {
			t.Fatalf("required appliance executable: %v", err)
		}
	}
	root := t.TempDir()
	source := filepath.Join(root, "slow-worker.go")
	shim := filepath.Join(root, "slow-worker.exe")
	code := `package main
import ("os"; "os/exec"; "time")
func main() {
    time.Sleep(65*time.Second)
    cmd := exec.Command(os.Getenv("MODELRIG_COLD_BOOT_WORKER_EXE"))
    cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
    if err := cmd.Run(); err != nil { os.Exit(1) }
}
`
	if err := os.WriteFile(source, []byte(code), 0600); err != nil {
		t.Fatal(err)
	}
	if out, err := exec.Command("go", "build", "-o", shim, source).CombinedOutput(); err != nil {
		t.Fatalf("build delayed launcher: %v\n%s", err, out)
	}
	logDir := filepath.Join(root, "logs")
	t.Setenv("MODELRIG_HOST", "127.0.0.1")
	t.Setenv("MODELRIG_PORT", "8080")
	t.Setenv("MODELRIG_WORKER_HOST", "127.0.0.1")
	t.Setenv("MODELRIG_WORKER_PORT", "8099")
	t.Setenv("MODELRIG_OLLAMA_URL", "http://127.0.0.1:9")
	t.Setenv("MODELRIG_DATA", filepath.Join(root, "data"))
	t.Setenv("PYTHONPATH", "")
	cmd := exec.Command(supervisorExe, "-worker", shim, "-server", serverExe,
		"-logs", logDir, "-env", filepath.Join(root, "absent.env"))
	cmd.Dir = root
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() {
		_ = exec.Command("taskkill.exe", "/PID", strconv.Itoa(cmd.Process.Pid), "/T", "/F").Run()
		_ = cmd.Wait()
		for _, name := range []string{"supervisor.log", "worker.log", "server.log"} {
			if data, err := os.ReadFile(filepath.Join(logDir, name)); err == nil {
				t.Logf("%s:\n%s", name, data)
			}
		}
	}()
	started := time.Now()
	if !verify("http://127.0.0.1:8080/healthz", config.Version) ||
		!verify("http://127.0.0.1:8099/healthz", config.Version) {
		t.Fatal("production updater verifier rejected the delayed appliance startup")
	}
	if elapsed := time.Since(started); elapsed < 65*time.Second {
		t.Fatalf("delayed worker was bypassed: readiness in %s", elapsed)
	} else {
		t.Logf("production updater accepted frozen worker after %s", elapsed)
	}
	if ok, err := heartbeat.ProveLooping(filepath.Join(logDir, "supervisor-heartbeat"), started, 10*time.Second, 45*time.Second); !ok {
		t.Fatalf("supervisor did not remain looping: %v", err)
	}
	data, err := os.ReadFile(filepath.Join(logDir, "supervisor.log"))
	if err != nil {
		t.Fatal(err)
	}
	log := string(data)
	if !strings.Contains(log, "worker starting; waiting within startup grace") ||
		strings.Contains(log, "worker unhealthy -> restarted") || strings.Contains(log, "worker was not running") {
		t.Fatalf("worker did not survive watched cold boot:\n%s", log)
	}
}
