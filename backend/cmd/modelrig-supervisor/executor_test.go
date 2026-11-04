package main

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// --- the policy, as a pure function -------------------------------------------

func TestExecutorRestartPolicy_EveryCode(t *testing.T) {
	cases := []struct {
		code    int
		restart bool
		first   time.Duration
		mention string
	}{
		{0, false, 0, "exit 0"},
		{70, true, 5 * time.Second, "GPU memory"},
		{73, false, 0, "another executor"},
		{75, true, 30 * time.Second, "media volume"},
		{76, true, 5 * time.Second, "not recorded"},
		{78, false, 0, "configuration refused"},
		{1, true, 5 * time.Second, "exit 1: unexpected"},
		{-1, true, 5 * time.Second, "exit -1: unexpected"}, // killed by a signal
		{3221225477, true, 5 * time.Second, "unexpected"},  // a Windows crash (0xC0000005)
	}
	for _, c := range cases {
		d := executorRestartPolicy(c.code, 1)
		if d.restart != c.restart || d.delay != c.first || !strings.Contains(d.why, c.mention) {
			t.Errorf("code %d: got %+v, want restart=%v delay=%s mentioning %q", c.code, d, c.restart, c.first, c.mention)
		}
	}
}

func TestExecutorRestartPolicy_BackoffDoublesAndCaps(t *testing.T) {
	want := map[int][]time.Duration{
		75: {30 * time.Second, time.Minute, 2 * time.Minute, 4 * time.Minute, 5 * time.Minute, 5 * time.Minute},
		70: {5 * time.Second, 10 * time.Second, 20 * time.Second, 40 * time.Second, 80 * time.Second, 160 * time.Second, 5 * time.Minute},
		1:  {5 * time.Second, 10 * time.Second},
	}
	for code, delays := range want {
		for i, w := range delays {
			if got := executorRestartPolicy(code, i+1).delay; got != w {
				t.Errorf("code %d, exit %d in a row: delay %s, want %s", code, i+1, got, w)
			}
		}
	}
	// A huge streak must neither overflow nor exceed the cap.
	if got := executorRestartPolicy(1, 1<<30).delay; got != executorBackoffCap {
		t.Fatalf("long streak: %s, want the cap %s", got, executorBackoffCap)
	}
}

// --- configuration ------------------------------------------------------------

type executorFixture struct {
	python, appDir string
}

func newExecutorFixture(t *testing.T) executorFixture {
	t.Helper()
	dir := t.TempDir()
	python := filepath.Join(dir, "venv", "python.exe")
	appDir := filepath.Join(dir, "worker")
	for _, d := range []string{filepath.Dir(python), filepath.Join(appDir, "app")} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	for _, f := range []string{python, filepath.Join(appDir, "app", "media_executor_main.py")} {
		if err := os.WriteFile(f, []byte("x"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return executorFixture{python: python, appDir: appDir}
}

func (f executorFixture) env(extra ...string) []string {
	return append([]string{
		"KALIV_MEDIA_EXECUTOR=1",
		"KALIV_MEDIA_EXECUTOR_DEVICES=cuda:0",
		"KALIV_MEDIA_EXECUTOR_PYTHON=" + f.python,
		"KALIV_MEDIA_EXECUTOR_APP_DIR=" + f.appDir,
	}, extra...)
}

func noEnv(string) string { return "" }

func TestExecutorConfig_OffUnlessExactlyOne(t *testing.T) {
	f := newExecutorFixture(t)
	for _, v := range []string{"", "0", "true", "yes", "on", "01"} {
		env := f.env("KALIV_MEDIA_EXECUTOR=" + v)
		cfg, err := executorConfigFrom(env, noEnv)
		if cfg != nil || err != nil {
			t.Errorf("switch %q: cfg=%v err=%v, want off", v, cfg, err)
		}
	}
	if cfg, err := executorConfigFrom(nil, noEnv); cfg != nil || err != nil {
		t.Fatalf("no configuration at all must be off, got %v %v", cfg, err)
	}
}

func TestExecutorConfig_Valid(t *testing.T) {
	f := newExecutorFixture(t)
	cfg, err := executorConfigFrom(f.env("KALIV_MEDIA_EXECUTOR_DEVICES= cuda:0 , cuda:1 ,"), noEnv)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.python != f.python || cfg.appDir != f.appDir || strings.Join(cfg.devices, ",") != "cuda:0,cuda:1" {
		t.Fatalf("unexpected configuration %+v", cfg)
	}
}

func TestExecutorConfig_RefusedConfigurations(t *testing.T) {
	f := newExecutorFixture(t)
	nine := make([]string, 9)
	for i := range nine {
		nine[i] = "cuda:" + strconv.Itoa(i)
	}
	cases := map[string][]string{
		"no devices":        {"KALIV_MEDIA_EXECUTOR_DEVICES="},
		"only commas":       {"KALIV_MEDIA_EXECUTOR_DEVICES=,,"},
		"not cuda:N":        {"KALIV_MEDIA_EXECUTOR_DEVICES=gpu0"},
		"leading zero":      {"KALIV_MEDIA_EXECUTOR_DEVICES=cuda:01"},
		"negative":          {"KALIV_MEDIA_EXECUTOR_DEVICES=cuda:-1"},
		"cpu":               {"KALIV_MEDIA_EXECUTOR_DEVICES=cpu"},
		"duplicate":         {"KALIV_MEDIA_EXECUTOR_DEVICES=cuda:0,cuda:0"},
		"too many":          {"KALIV_MEDIA_EXECUTOR_DEVICES=" + strings.Join(nine, ",")},
		"relative python":   {"KALIV_MEDIA_EXECUTOR_PYTHON=python.exe"},
		"empty python":      {"KALIV_MEDIA_EXECUTOR_PYTHON="},
		"missing python":    {"KALIV_MEDIA_EXECUTOR_PYTHON=" + filepath.Join(f.appDir, "nope.exe")},
		"python is a dir":   {"KALIV_MEDIA_EXECUTOR_PYTHON=" + f.appDir},
		"relative app dir":  {"KALIV_MEDIA_EXECUTOR_APP_DIR=worker"},
		"app dir no module": {"KALIV_MEDIA_EXECUTOR_APP_DIR=" + filepath.Dir(f.python)},
	}
	for name, extra := range cases {
		cfg, err := executorConfigFrom(f.env(extra...), noEnv)
		if err == nil || cfg != nil {
			t.Errorf("%s: cfg=%+v err=%v, want refused", name, cfg, err)
		}
	}
}

func TestExecutorConfig_EnvFileWinsOverTheSupervisorsEnvironment(t *testing.T) {
	f := newExecutorFixture(t)
	process := map[string]string{
		"KALIV_MEDIA_EXECUTOR":         "1",
		"KALIV_MEDIA_EXECUTOR_DEVICES": "cuda:0",
		"KALIV_MEDIA_EXECUTOR_PYTHON":  f.python,
		"KALIV_MEDIA_EXECUTOR_APP_DIR": f.appDir,
	}
	getenv := func(k string) string { return process[k] }
	// Only in the supervisor's environment: the children inherit it, so it counts.
	if cfg, err := executorConfigFrom(nil, getenv); err != nil || cfg == nil {
		t.Fatalf("process environment ignored: %v %v", cfg, err)
	}
	// The env file switches it off: the file is what the children see last.
	if cfg, err := executorConfigFrom([]string{"KALIV_MEDIA_EXECUTOR=0"}, getenv); cfg != nil || err != nil {
		t.Fatalf("env file did not win: %v %v", cfg, err)
	}
	// Last entry in the file wins, as exec does with duplicate keys.
	if v := lookupChildEnv([]string{"K=a", "OTHER=x", "K=b"}, noEnv, "K"); v != "b" {
		t.Fatalf("lookupChildEnv = %q, want the last entry", v)
	}
}

func TestExecutorsFrom_OneChildPerDeviceWithItsOwnLog(t *testing.T) {
	f := newExecutorFixture(t)
	logs := t.TempDir()
	env := f.env("KALIV_MEDIA_EXECUTOR_DEVICES=cuda:0,cuda:1")
	execs, err := executorsFrom(env, noEnv, logs, 20, nil)
	if err != nil || len(execs) != 2 {
		t.Fatalf("executorsFrom: %d %v", len(execs), err)
	}
	for i, e := range execs {
		dev := "cuda:" + strconv.Itoa(i)
		if e.name() != "executor-cuda"+strconv.Itoa(i) || strings.Contains(e.name(), ":") {
			t.Errorf("label %q (no ':' allowed: it names a Windows log file)", e.name())
		}
		want := []string{"-u", "-m", "app.media_executor_main", "--device", dev}
		if strings.Join(e.p.args, " ") != strings.Join(want, " ") || e.p.exePath != f.python || e.p.workDir != f.appDir {
			t.Errorf("command %s %v in %s", e.p.exePath, e.p.args, e.p.workDir)
		}
		if e.p.logPath != filepath.Join(logs, e.name()+".log") {
			t.Errorf("log %s", e.p.logPath)
		}
		if strings.Join(e.p.extraEnv, "\n") != strings.Join(env, "\n") {
			t.Errorf("the executor must get the same env file as the worker")
		}
	}
	if execs, err := executorsFrom(nil, noEnv, logs, 20, nil); execs != nil || err != nil {
		t.Fatalf("off must build nothing: %v %v", execs, err)
	}
	if execs, err := executorsFrom(f.env("KALIV_MEDIA_EXECUTOR_DEVICES=gpu0"), noEnv, logs, 20, nil); execs != nil || err == nil {
		t.Fatalf("refused must build nothing and say why: %v %v", execs, err)
	}
}

// --- restartHeld over recorded process state, with a controlled clock ----------

type clock struct{ t time.Time }

func (c *clock) now() time.Time { return c.t }

func exitedExecutor(c *clock) *executorChild {
	return &executorChild{p: &procChild{label: "executor-cuda0"}, now: c.now}
}

// exit records "run number runs ended with code after lasting d" -- what the
// reaper goroutine records for a real process.
func (e *executorChild) exit(code int, lasted time.Duration, at time.Time) {
	e.p.mu.Lock()
	defer e.p.mu.Unlock()
	e.p.runs++
	e.p.alive = false
	e.p.lastCode = code
	e.p.startedAt = at.Add(-lasted)
	e.p.exitedAt = at
}

func TestExecutorChild_NeverStartedIsStarted(t *testing.T) {
	c := &clock{time.Unix(1_000_000, 0)}
	if held, why := exitedExecutor(c).restartHeld(); held || why != "" {
		t.Fatalf("a never-started executor must start: held=%v %q", held, why)
	}
}

func TestExecutorChild_NeverRestartCodesHoldForGoodAndLogOnce(t *testing.T) {
	for _, code := range []int{0, 73, 78} {
		c := &clock{time.Unix(1_000_000, 0)}
		e := exitedExecutor(c)
		e.exit(code, time.Second, c.t)
		held, why := e.restartHeld()
		if !held || why == "" {
			t.Fatalf("code %d: held=%v why=%q", code, held, why)
		}
		c.t = c.t.Add(24 * time.Hour)
		if held, why := e.restartHeld(); !held || why != "" {
			t.Fatalf("code %d a day later: held=%v why=%q (held for good, logged once)", code, held, why)
		}
	}
}

func TestExecutorChild_BackoffHoldsThenReleasesAndGrows(t *testing.T) {
	c := &clock{time.Unix(1_000_000, 0)}
	e := exitedExecutor(c)
	e.exit(75, time.Second, c.t)
	if held, why := e.restartHeld(); !held || !strings.Contains(why, "restart in 30s") {
		t.Fatalf("first 75: held=%v %q", held, why)
	}
	c.t = c.t.Add(29 * time.Second)
	if held, _ := e.restartHeld(); !held {
		t.Fatal("released before 30 s")
	}
	c.t = c.t.Add(time.Second)
	if held, why := e.restartHeld(); held || why != "" {
		t.Fatalf("not released at 30 s: held=%v %q", held, why)
	}
	// It restarts, fails again quickly: the hold doubles.
	e.exit(75, 2*time.Second, c.t)
	if held, why := e.restartHeld(); !held || !strings.Contains(why, "restart in 1m0s") {
		t.Fatalf("second 75 in a row: held=%v %q", held, why)
	}
	c.t = c.t.Add(time.Minute)
	if held, _ := e.restartHeld(); held {
		t.Fatal("not released after the doubled back-off")
	}
	// A run that lasted (it was working) resets the streak.
	e.exit(75, executorStableRun, c.t)
	if _, why := e.restartHeld(); !strings.Contains(why, "restart in 30s") {
		t.Fatalf("a stable run must reset the back-off: %q", why)
	}
}

func TestExecutorChild_DecidesFromWhenItExitedNotWhenItWasNoticed(t *testing.T) {
	c := &clock{time.Unix(1_000_000, 0)}
	e := exitedExecutor(c)
	e.exit(70, time.Second, c.t)
	c.t = c.t.Add(10 * time.Second) // the next supervision tick, after the 5 s
	if held, why := e.restartHeld(); held || !strings.Contains(why, "restarting") {
		t.Fatalf("exit 70 seen after its delay must restart at once: held=%v %q", held, why)
	}
}

// --- the loop ------------------------------------------------------------------

type heldChild struct {
	fakeChild
	held bool
}

func (h *heldChild) restartHeld() (bool, string) { return h.held, "" }

func TestSuperviseOnce_AHeldChildIsNotRestartedAndOthersAre(t *testing.T) {
	held := &heldChild{fakeChild: fakeChild{nm: "executor-cuda0"}, held: true}
	dead := &fakeChild{nm: "worker"}
	var restarted []string
	superviseOnce([]child{held, dead}, nil, 3, &restarted)
	if held.restarts != 0 || dead.restarts != 1 || strings.Join(restarted, ",") != "worker" {
		t.Fatalf("held=%d dead=%d restarted=%v", held.restarts, dead.restarts, restarted)
	}
	held.held = false
	superviseOnce([]child{held}, nil, 3, nil)
	if held.restarts != 1 {
		t.Fatal("a released child must be restarted")
	}
}

// --- real processes: the exit code the policy sees is the one the child gave ----

// TestExecutorHelperProcess is not a test: it is the child process, started
// from this test binary, that exits with the code its ARGUMENTS name (so a
// child started without its arguments is caught: it exits 99).
func TestExecutorHelperProcess(t *testing.T) {
	if os.Getenv("KALIV_TEST_EXECUTOR_HELPER") != "1" {
		return
	}
	for _, a := range os.Args {
		if v, ok := strings.CutPrefix(a, "exit="); ok {
			code, _ := strconv.Atoi(v)
			os.Exit(code)
		}
	}
	os.Exit(99)
}

func helperExecutor(t *testing.T, code int, c *clock) *executorChild {
	t.Helper()
	logs, err := os.MkdirTemp("", "executor-logs")
	if err != nil {
		t.Fatal(err)
	}
	// Not t.TempDir: on Windows the reaper may still hold the log open for a
	// moment after the exit is recorded, and a failed cleanup fails the test.
	t.Cleanup(func() { _ = os.RemoveAll(logs) })
	return &executorChild{
		p: &procChild{
			label:    "executor-cuda0",
			exePath:  os.Args[0],
			args:     []string{"-test.run=^TestExecutorHelperProcess$", "--", "exit=" + strconv.Itoa(code)},
			workDir:  logs,
			logPath:  filepath.Join(logs, "executor-cuda0.log"),
			extraEnv: []string{"KALIV_TEST_EXECUTOR_HELPER=1"},
		},
		now: c.now,
	}
}

func waitExited(t *testing.T, e *executorChild) {
	t.Helper()
	deadline := time.Now().Add(30 * time.Second)
	for e.running() {
		if time.Now().After(deadline) {
			t.Fatal("helper process did not exit")
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func TestExecutorChild_RealExitCodesDriveTheLoop(t *testing.T) {
	for _, tc := range []struct {
		code      int
		restarted bool
	}{{78, false}, {73, false}, {0, false}, {75, false}, {70, true}} {
		c := &clock{time.Now()}
		e := helperExecutor(t, tc.code, c)
		if err := e.restart(); err != nil {
			t.Fatal(err)
		}
		waitExited(t, e)
		e.p.mu.Lock()
		got, runs := e.p.lastCode, e.p.runs
		e.p.mu.Unlock()
		if got != tc.code || runs != 1 {
			t.Fatalf("recorded exit %d after %d run(s), want %d after 1", got, runs, tc.code)
		}
		// One tick 10 s later: 70 (5 s) is due, 75 (30 s) is not, the rest never are.
		c.t = c.t.Add(10 * time.Second)
		var restarted []string
		superviseOnce([]child{e}, nil, 3, &restarted)
		if (len(restarted) == 1) != tc.restarted {
			t.Fatalf("code %d: restarted=%v, want %v", tc.code, restarted, tc.restarted)
		}
		if tc.restarted {
			waitExited(t, e)
		}
	}
}

func TestExecutorChild_ARunningExecutorIsNeverBouncedForHealth(t *testing.T) {
	e := &executorChild{p: &procChild{label: "executor-cuda0", alive: true}, now: time.Now}
	fails := map[string]int{}
	var restarted []string
	for i := 0; i < 10; i++ {
		fails = superviseOnce([]child{e}, fails, 3, &restarted)
	}
	if len(restarted) != 0 || fails[e.name()] != 0 {
		t.Fatalf("a live executor was restarted: %v (fails %d)", restarted, fails[e.name()])
	}
}
