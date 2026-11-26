package main

// The supervisor's executor tests use a helper process: they prove the policy
// (which exit code restarts, which holds), not that the command the supervisor
// builds starts the MEDIA EXECUTOR. That link -- an env file, the supervisor's
// own parsing and child construction, `python -u -m app.media_executor_main
// --device cuda:N` in KALIV_MEDIA_EXECUTOR_APP_DIR -- had only ever been made
// by hand at the rig, from a PowerShell window.
//
// Here it is made for real: the env file is written to disk, read by
// loadEnvFile, turned into children by executorsFrom, and the real Python
// module is started from the repository's worker folder. No GPU is needed: the
// executor refuses its configuration before it looks at one, and WHICH refusal
// it gives shows what reached it.

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// realPython is an interpreter that can run the worker's code, or "" with the
// reason. In CI a missing interpreter is a failure, not a skip: a skipped link
// test is the gap this file closes.
func realPython(t *testing.T) string {
	t.Helper()
	for _, name := range []string{"python3", "python"} {
		path, err := exec.LookPath(name)
		if err != nil {
			continue
		}
		if abs, err := filepath.Abs(path); err == nil {
			path = abs
		}
		if exec.Command(path, "-B", "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)").Run() == nil {
			return path
		}
	}
	if os.Getenv("CI") != "" {
		t.Fatal("no Python >= 3.11 on PATH: the supervisor-to-executor link cannot be tested")
	}
	t.Skip("no Python >= 3.11 on PATH")
	return ""
}

// startFromEnvFile writes lines as an env file and starts what the supervisor
// would start from it. It returns the executor after it has exited, and what it
// wrote to its log.
func startFromEnvFile(t *testing.T, lines []string) (*executorChild, string) {
	t.Helper()
	dir, err := os.MkdirTemp("", "executor-real")
	if err != nil {
		t.Fatal(err)
	}
	// Not t.TempDir: on Windows the log may be held a moment after the exit is recorded.
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	envFile := filepath.Join(dir, "modelrig.env")
	// A BOM, a comment, a blank line and CRLF: the file as an operator's editor on Windows leaves it.
	text := "\ufeff# appliance\r\n\r\n" + strings.Join(lines, "\r\n") + "\r\n"
	if err := os.WriteFile(envFile, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	childEnv, err := loadEnvFile(envFile)
	if err != nil {
		t.Fatal(err)
	}
	logs := filepath.Join(dir, "logs")
	if err := os.MkdirAll(logs, 0o755); err != nil {
		t.Fatal(err)
	}
	execs, err := executorsFrom(childEnv, noEnv, logs, 20, nil)
	if err != nil || len(execs) != 1 {
		t.Fatalf("executorsFrom: %d child(ren), %v", len(execs), err)
	}
	e := execs[0]
	if err := e.restart(); err != nil {
		t.Fatalf("the supervisor could not start the executor: %v", err)
	}
	deadline := time.Now().Add(120 * time.Second)
	for e.running() {
		if time.Now().After(deadline) {
			t.Fatal("the executor neither refused nor exited within 120 s")
		}
		time.Sleep(20 * time.Millisecond)
	}
	var raw []byte
	for attempt := 0; attempt < 50; attempt++ { // the log is flushed by the reaper
		raw, _ = os.ReadFile(filepath.Join(logs, "executor-cuda0.log"))
		if strings.Contains(string(raw), "media executor:") {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	return e, string(raw)
}

func exitCode(e *executorChild) (int, int) {
	e.p.mu.Lock()
	defer e.p.mu.Unlock()
	return e.p.lastCode, e.p.runs
}

func TestSupervisorStartsTheRealMediaExecutorFromAnEnvFile(t *testing.T) {
	python := realPython(t)
	appDir, err := filepath.Abs(filepath.Join("..", "..", "..", "worker"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(appDir, "app", "media_executor_main.py")); err != nil {
		t.Fatalf("the worker's executor module is not where the test expects it: %v", err)
	}
	cache := filepath.Join(appDir, "app", "__pycache__")
	_, cacheErr := os.Stat(cache)
	hadCache := cacheErr == nil
	base := []string{
		"KALIV_MEDIA_EXECUTOR=1",
		"KALIV_MEDIA_EXECUTOR_DEVICES=cuda:0",
		"KALIV_MEDIA_EXECUTOR_PYTHON=" + python,
		"KALIV_MEDIA_EXECUTOR_APP_DIR=" + appDir + "   # a trailing comment, as in the example file",
		"PYTHONDONTWRITEBYTECODE=1", // the test must not leave __pycache__ in the checkout
	}
	const orderRule = "CUDA_DEVICE_ORDER=PCI_BUS_ID is required"

	// 1. The four keys alone: the module is found and imported in the app dir, it is given
	//    the device, and the switch from the FILE reached it -- it gets past "the media
	//    executor is off" and stops at the next rule, which the supervisor does not satisfy
	//    for it. Exit 78 is "configuration refused".
	e, log := startFromEnvFile(t, base)
	code, runs := exitCode(e)
	if code != 78 || runs != 1 {
		t.Fatalf("exit %d after %d run(s), want 78 after 1; log:\n%s", code, runs, log)
	}
	if !strings.Contains(log, "media executor: configuration refused:") || !strings.Contains(log, orderRule) {
		t.Fatalf("the executor did not reach its own configuration check with the file's switch; log:\n%s", log)
	}
	if strings.Contains(log, "Traceback") || strings.Contains(log, "No module named") {
		t.Fatalf("the executor module did not import cleanly in its app dir; log:\n%s", log)
	}

	// 2. A refused configuration is held: the supervisor does not start it again, however
	//    long it waits. (A restart loop here would be a GPU process flapping on the rig.)
	var restarted []string
	fails := map[string]int{}
	for tick := 0; tick < 5; tick++ {
		fails = superviseOnce([]child{e}, fails, 3, &restarted)
	}
	if _, runs := exitCode(e); len(restarted) != 0 || runs != 1 {
		t.Fatalf("a refused executor was started again: restarted=%v runs=%d", restarted, runs)
	}

	// 3. One more line in the file changes the executor's answer: a value from the env file
	//    reaches the Python process as its environment, not only the four keys the
	//    supervisor reads itself.
	e, log = startFromEnvFile(t, append(append([]string{}, base...), "CUDA_DEVICE_ORDER=PCI_BUS_ID"))
	if code, _ := exitCode(e); code != 78 {
		t.Fatalf("exit %d, want 78; log:\n%s", code, log)
	}
	if !strings.Contains(log, "refused:") || strings.Contains(log, orderRule) {
		t.Fatalf("CUDA_DEVICE_ORDER from the env file did not reach the executor; log:\n%s", log)
	}

	// 4. The switch off in the file: the supervisor builds no executor at all.
	off := append([]string{"KALIV_MEDIA_EXECUTOR=0"}, base[1:]...)
	if execs, err := executorsFrom(off, noEnv, t.TempDir(), 20, nil); execs != nil || err != nil {
		t.Fatalf("off must build nothing: %v %v", execs, err)
	}

	// The run left nothing in the checkout.
	if _, err := os.Stat(cache); err == nil && !hadCache {
		t.Fatal("the executor wrote __pycache__ into the checkout")
	}
}
