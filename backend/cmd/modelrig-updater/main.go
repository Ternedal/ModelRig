// modelrig-updater is the "a bad update can be rolled back" half of the
// appliance goal. It checks the latest GitHub release, and if it is newer than
// what is running, downloads the Windows exes, backs up the current ones, swaps
// them in, restarts via the supervisor task, and verifies /healthz reports the
// new version. If verification fails, it restores the backup and restarts -- so
// a broken release never leaves the rig down.
//
// It is a plain console exe (prebuilt, no runtime on the rig). Run it by hand,
// or on a schedule. The Windows-specific coordination -- stopping the supervisor
// task, killing the worker/server so their exes are no longer locked, starting
// the task again -- is a thin exec layer verified on the rig. The parts that are
// easy to get wrong (is this version actually newer? did the backup/swap/restore
// move the right bytes? does the health check accept the right version?) live in
// the helpers below and are unit-tested.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"modelrig/internal/heartbeat"
)

// target is one binary the updater manages: its name on the release, and where
// it lives on disk (the server + supervisor sit in the root, the worker in
// worker/).
type target struct {
	asset string
	live  string
}

// isNewer reports whether latest is a strictly higher semver than current.
// Both may carry a leading "v". Missing components count as 0 (1.58 == 1.58.0).
func isNewer(current, latest string) (bool, error) {
	c, err := parseSemver(current)
	if err != nil {
		return false, fmt.Errorf("current %q: %w", current, err)
	}
	l, err := parseSemver(latest)
	if err != nil {
		return false, fmt.Errorf("latest %q: %w", latest, err)
	}
	for i := 0; i < 3; i++ {
		if l[i] != c[i] {
			return l[i] > c[i], nil
		}
	}
	return false, nil
}

func parseSemver(v string) ([3]int, error) {
	var out [3]int
	v = strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(v), "v"))
	parts := strings.SplitN(v, ".", 3)
	for i := 0; i < len(parts) && i < 3; i++ {
		n, err := strconv.Atoi(strings.TrimSpace(parts[i]))
		if err != nil {
			return out, fmt.Errorf("not semver")
		}
		out[i] = n
	}
	return out, nil
}

// selectAssets pulls the tag and the download URL for each wanted asset out of a
// GitHub release JSON payload. Missing wanted assets are an error -- a partial
// update (new server, old worker) is worse than no update.
func selectAssets(releaseJSON []byte, want []string) (tag string, urls map[string]string, err error) {
	var rel struct {
		TagName string `json:"tag_name"`
		Assets  []struct {
			Name string `json:"name"`
			URL  string `json:"browser_download_url"`
		} `json:"assets"`
	}
	if err = json.Unmarshal(releaseJSON, &rel); err != nil {
		return "", nil, err
	}
	byName := map[string]string{}
	for _, a := range rel.Assets {
		byName[a.Name] = a.URL
	}
	urls = map[string]string{}
	for _, w := range want {
		u, ok := byName[w]
		if !ok {
			return "", nil, fmt.Errorf("release %s is missing asset %q", rel.TagName, w)
		}
		urls[w] = u
	}
	return rel.TagName, urls, nil
}

// downloadClient bounds a stuck download so an unattended updater can't hang
// forever on a wedged connection.
var downloadClient = &http.Client{Timeout: 10 * time.Minute}

func download(url, dest string) error {
	resp, err := downloadClient.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("GET %s: %s", url, resp.Status)
	}
	f, err := os.Create(dest)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = io.Copy(f, resp.Body)
	return err
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	if _, err = io.Copy(out, in); err != nil {
		out.Close()
		return err
	}
	if err = out.Sync(); err != nil { // flush to disk before a caller renames it
		out.Close()
		return err
	}
	return out.Close()
}

// backupAndSwap copies each live file into backupDir, then atomically swaps the
// staged (downloaded) file into the live path. Every live change is an atomic
// rename (see atomicSwapInto), so a failure partway -- including mid-copy of a
// later target -- never leaves any live exe partially written; already-swapped
// targets are restored from backup. On success the caller can start the new
// binaries.
// errRollbackFailed marks that an automatic rollback did NOT succeed; callers
// must fail closed and must NOT restart the supervisor on a broken set.
var errRollbackFailed = fmt.Errorf("ROLLBACK FAILED")

// withRollback combines a swap failure with the result of the rollback attempt.
// If the rollback also failed, the returned error wraps errRollbackFailed so
// the caller can detect it (errors.Is) and never claims the rig was restored.
func withRollback(swapErr, restoreErr error) error {
	if restoreErr == nil {
		return swapErr
	}
	return fmt.Errorf("%v; %w (%v) -- rig may be on mixed versions, restore from backups by hand", swapErr, errRollbackFailed, restoreErr)
}

func backupAndSwap(targets []target, stagedDir, backupDir string, j *txJournal) error {
	if err := os.MkdirAll(backupDir, 0o755); err != nil {
		return err
	}
	// Phase 1: back up EVERY target before the FIRST swap, so any crash after
	// any swap always has a complete pre-transaction set to restore from --
	// there is no state where some targets were never captured.
	for _, t := range targets {
		if err := copyFile(t.live, filepath.Join(backupDir, t.asset)); err != nil {
			return fmt.Errorf("backup %s: %w", t.live, err) // nothing swapped yet
		}
	}
	if err := j.setState("backed_up"); err != nil {
		return fmt.Errorf("journal: %w", err)
	}
	// Phase 2: swap. Each completed swap is recorded in the journal, so a crash
	// here tells the whole-set recovery exactly what to undo.
	var swapped []target
	for _, t := range targets {
		if err := atomicSwapInto(filepath.Join(stagedDir, t.asset), t.live); err != nil {
			return withRollback(fmt.Errorf("swap %s: %w", t.live, err), restore(swapped, backupDir))
		}
		swapped = append(swapped, t)
		_ = j.addSwapped(t.asset)
	}
	return nil
}

func fileExists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}

// recoverTarget repairs the aftermath of a crashed prior swap for one target,
// BEFORE anything is deleted or overwritten. A crash between the two renames in
// atomicSwapInto can leave live missing with .old (the original) and/or .new
// (the update) beside it; proceeding blindly would let the next swap delete .old
// (its stale-temp cleanup) and destroy the only recovery copy. Recover, or fail
// closed on any state we can't safely resolve -- delete nothing.
func recoverTarget(live string) error {
	oldP, newP := live+".old", live+".new"
	switch {
	case fileExists(live):
		return nil // live is present; the swap manages its own temps
	case fileExists(oldP):
		// interrupted mid-swap: put the original back
		if err := os.Rename(oldP, live); err != nil {
			return fmt.Errorf("restore %s from %s: %w", live, oldP, err)
		}
		os.Remove(newP) // the interrupted update; the swap will re-stage it
		return nil
	case fileExists(newP):
		return fmt.Errorf("%s is missing; only %s survived a prior crash -- verify it and rename it by hand (cannot confirm it is intact)", live, newP)
	default:
		return fmt.Errorf("%s is missing with no .old/.new to recover from -- restore it by hand", live)
	}
}

// renameFn is os.Rename, indirected so tests can inject rename failures.
var renameFn = os.Rename

// atomicSwapInto replaces live with the contents of srcFile. It copies srcFile to
// live.exe.new (same volume) + fsync, then renames the original to .old and .new
// into place, putting .old back if the final rename fails. This makes a mid-COPY
// failure safe: live is never truncated in place, so a disk/I/O error or a bad
// download can't corrupt it.
//
// LIMITATION: this is not fully crash-atomic on Windows. os.Rename is not
// guaranteed atomic on non-Unix platforms, and there is a brief window between
// the two renames where the live name does not exist -- a power loss there leaves
// live missing (with .old/.new alongside) and nothing yet repairs it on startup.
// A Windows-native ReplaceFileW plus a startup recovery pass would close that
// (audit follow-up). For now the common failure -- I/O mid-copy -- is handled.
func atomicSwapInto(srcFile, live string) error {
	// Never proceed if live is missing: the .old removal below would destroy a
	// recovery copy left by a crashed prior swap. Recovery must run first.
	if !fileExists(live) {
		return fmt.Errorf("refusing to swap into %s: the live file is missing (recovery must run first)", live)
	}
	tmp := live + ".new"
	old := live + ".old"
	if err := copyFile(srcFile, tmp); err != nil {
		os.Remove(tmp)
		return err
	}
	_ = os.Remove(old)
	if err := renameFn(live, old); err != nil {
		os.Remove(tmp)
		return err
	}
	if err := renameFn(tmp, live); err != nil {
		// live currently does not exist (moved to old). Try to put the original
		// back; if THAT also fails, keep .old and .new for manual recovery and
		// surface both errors -- never claim the file is intact.
		if rerr := renameFn(old, live); rerr != nil {
			return fmt.Errorf("swap into %s failed (%v) AND restore of the original failed (%v) -- live file is missing; recover by hand from %s or %s", live, err, rerr, old, tmp)
		}
		os.Remove(tmp)
		return err
	}
	_ = os.Remove(old)
	return nil
}

// restore atomically swaps each target's backed-up binary back over the live
// path. Used both on a mid-swap failure and on a failed health check after the
// swap. Atomic so the undo path can't corrupt a live exe either.
func restore(targets []target, backupDir string) error {
	var firstErr error
	for _, t := range targets {
		bak := filepath.Join(backupDir, t.asset)
		if err := atomicSwapInto(bak, t.live); err != nil && firstErr == nil {
			firstErr = err
		}
	}
	return firstErr
}

// verify checks that the server answers /healthz with the expected version.
func verify(healthURL, wantVersion string) bool {
	client := http.Client{Timeout: 5 * time.Second}
	for i := 0; i < 15; i++ {
		resp, err := client.Get(healthURL)
		if err == nil {
			var body struct {
				Version string `json:"version"`
			}
			b, _ := io.ReadAll(resp.Body)
			resp.Body.Close()
			if json.Unmarshal(b, &body) == nil && body.Version == wantVersion {
				return true
			}
		}
		time.Sleep(2 * time.Second)
	}
	return false
}

func ps(args ...string) error {
	cmd := exec.Command("powershell", append([]string{"-NoProfile", "-Command"}, args...)...)
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	return cmd.Run()
}

// assetURL returns the download URL for one asset by name, or "" if absent.
func assetURL(releaseJSON []byte, name string) string {
	var rel struct {
		Assets []struct {
			Name string `json:"name"`
			URL  string `json:"browser_download_url"`
		} `json:"assets"`
	}
	if json.Unmarshal(releaseJSON, &rel) != nil {
		return ""
	}
	for _, a := range rel.Assets {
		if a.Name == name {
			return a.URL
		}
	}
	return ""
}

// parseSums reads a `sha256sum` file into name->hash. Lines are "<hex>  <name>"
// (two spaces); a leading "*" on the name (binary marker) is tolerated.
func parseSums(data []byte) map[string]string {
	out := map[string]string{}
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		f := strings.Fields(line)
		if len(f) < 2 {
			continue
		}
		out[strings.TrimPrefix(f[len(f)-1], "*")] = strings.ToLower(f[0])
	}
	return out
}

func fileSHA256(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func main() {
	dir, _ := os.Getwd()
	root := flag.String("dir", dir, "ModelRig root (where the exes live)")
	repo := flag.String("repo", "Ternedal/ModelRig", "owner/name of the GitHub repo")
	current := flag.String("current", "", "current version (default: read from the running server /healthz)")
	serverHealth := flag.String("server-health", "http://127.0.0.1:8080/healthz", "server health URL")
	workerHealth := flag.String("worker-health", "http://127.0.0.1:8099/healthz", "worker health URL")
	heartbeatPath := flag.String("heartbeat", "", "supervisor heartbeat file (default: <dir>/logs/supervisor-heartbeat)")
	superInterval := flag.Duration("supervisor-interval", 10*time.Second, "supervisor tick interval; used to prove the heartbeat advances after an update")
	noHeartbeat := flag.Bool("no-heartbeat-check", false, "skip the post-update supervisor-liveness check")
	task := flag.String("supervisor-task", "KalivSupervisor", "scheduled task that runs the supervisor")
	checkOnly := flag.Bool("check", false, "report whether an update is available and exit")
	recoverOnly := flag.Bool("recover", false, "repair a crashed prior swap (offline, no network) and exit")
	skipVerify := flag.Bool("insecure-skip-verify", false, "install without checking SHA256SUMS.txt (only for a release predating checksums)")
	flag.Parse()
	if *heartbeatPath == "" {
		*heartbeatPath = filepath.Join(*root, "logs", "supervisor-heartbeat")
	}
	log.SetPrefix("updater: ")
	log.SetFlags(log.LstdFlags)

	targets := []target{
		{"modelrig-server-windows-x64.exe", filepath.Join(*root, "modelrig-server-windows-x64.exe")},
		{"modelrig-supervisor-windows-x64.exe", filepath.Join(*root, "modelrig-supervisor-windows-x64.exe")},
		{"modelrig-worker-windows-x64.exe", filepath.Join(*root, "worker", "modelrig-worker-windows-x64.exe")},
	}

	// The whole run holds an exclusive lock: two updaters at once would
	// interleave swaps and race the journal. log.Fatalf skips defers, so fatal
	// paths below go through die(), which releases the lock first.
	lockPath := filepath.Join(*root, "updater.lock")
	if err := acquireLock(lockPath); err != nil {
		log.Fatalf("%v", err)
	}
	defer releaseLock(lockPath)
	die := func(format string, a ...any) {
		releaseLock(lockPath)
		log.Printf("FATAL: "+format, a...)
		os.Exit(1)
	}

	// Whole-set recovery FIRST: an uncommitted transaction journal means a
	// previous update crashed partway; restore EVERY target from that attempt's
	// backups so the rig can never keep running a mixed-version set.
	journalPath := filepath.Join(*root, "update-transaction.json")
	if err := recoverFromJournal(journalPath, targets); err != nil {
		die("%v", err)
	}

	// Recovery FIRST -- before reading the current version or any network call. A
	// crash can leave a live exe missing; if that's the server, its version can't
	// be read (the step below would exit here), so recovery must repair it before
	// anything else. Runs on every invocation, so simply running the updater --
	// or -recover, which needs no network -- heals a crashed rig.
	for _, t := range targets {
		if err := recoverTarget(t.live); err != nil {
			die("startup recovery for %s failed: %v", t.asset, err)
		}
	}
	if *recoverOnly {
		log.Printf("recovery complete (-recover); nothing else to do")
		return
	}

	cur := *current
	if cur == "" {
		cur = readRunningVersion(*serverHealth)
		if cur == "" {
			die("could not read current version from %s; pass -current", *serverHealth)
		}
	}

	relBody, err := httpGet(fmt.Sprintf("https://api.github.com/repos/%s/releases/latest", *repo))
	if err != nil {
		die("fetch latest release: %v", err)
	}
	tag, urls, err := selectAssets(relBody, assetNames(targets))
	if err != nil {
		die("%v", err)
	}
	newer, err := isNewer(cur, tag)
	if err != nil {
		die("version compare: %v", err)
	}
	if !newer {
		log.Printf("already up to date (running %s, latest %s)", cur, tag)
		return
	}
	newVersion := strings.TrimPrefix(tag, "v")
	log.Printf("update available: %s -> %s", cur, tag)
	if *checkOnly {
		return
	}

	sumsURL := assetURL(relBody, "SHA256SUMS.txt")
	if sumsURL == "" && !*skipVerify {
		die("release %s has no SHA256SUMS.txt -- refusing to install unverified (pass -insecure-skip-verify to override)", tag)
	}

	staged, err := os.MkdirTemp("", "kaliv-update-")
	if err != nil {
		die("staging dir: %v", err)
	}
	defer os.RemoveAll(staged)
	for _, t := range targets {
		dest := filepath.Join(staged, t.asset)
		log.Printf("downloading %s", t.asset)
		if err := download(urls[t.asset], dest); err != nil {
			die("download %s: %v", t.asset, err)
		}
	}

	// Verify integrity BEFORE touching the running system: a tampered or
	// truncated download must never reach the swap. Fail closed.
	if sumsURL != "" {
		sumsPath := filepath.Join(staged, "SHA256SUMS.txt")
		if err := download(sumsURL, sumsPath); err != nil {
			die("download SHA256SUMS.txt: %v", err)
		}
		data, err := os.ReadFile(sumsPath)
		if err != nil {
			die("read SHA256SUMS.txt: %v", err)
		}
		sums := parseSums(data)
		for _, t := range targets {
			want, ok := sums[t.asset]
			if !ok {
				die("SHA256SUMS.txt has no entry for %s -- refusing to install", t.asset)
			}
			got, err := fileSHA256(filepath.Join(staged, t.asset))
			if err != nil {
				die("hash %s: %v", t.asset, err)
			}
			if !strings.EqualFold(got, want) {
				die("checksum MISMATCH for %s (want %s, got %s) -- refusing to install", t.asset, want, got)
			}
		}
		log.Printf("checksums verified for %d exe(s)", len(targets))
	} else {
		log.Printf("WARNING: installing WITHOUT integrity verification (-insecure-skip-verify)")
	}

	// Immutable, per-attempt backup dir: a retry must not overwrite a good backup
	// from an earlier attempt with a now-damaged live file. Created atomically
	// (os.Mkdir fails if it exists) so two updaters started in the same second
	// can't both claim it -- the second fails closed rather than sharing it.
	backupDir := filepath.Join(*root, "backups",
		fmt.Sprintf("%s-%s-to-%s", time.Now().UTC().Format("20060102T150405Z"), cur, newVersion))
	if err := os.MkdirAll(filepath.Dir(backupDir), 0o755); err != nil {
		die("create backups dir: %v", err)
	}
	if err := os.Mkdir(backupDir, 0o755); err != nil {
		die("claim backup dir %s: %v", backupDir, err)
	}
	// The journal is written BEFORE the first mutation; its presence at next
	// start means this transaction did not commit and must be rolled back whole.
	journal, err := newJournal(journalPath, cur, newVersion, backupDir)
	if err != nil {
		die("%v", err)
	}
	log.Printf("stopping supervisor + processes so the exes unlock")
	_ = ps(fmt.Sprintf("Stop-ScheduledTask -TaskName '%s' -ErrorAction SilentlyContinue", *task))
	_ = ps("Get-Process modelrig-server,modelrig-worker,modelrig-supervisor -ErrorAction SilentlyContinue | Stop-Process -Force")
	time.Sleep(2 * time.Second)

	if err := backupAndSwap(targets, staged, backupDir, journal); err != nil {
		if errors.Is(err, errRollbackFailed) {
			// The set may be mixed/broken: keep the journal (next run's whole-set
			// recovery will finish the job) and do NOT start the supervisor on it.
			_ = journal.setState("manual_recovery")
			die("swap failed AND rollback failed: %v -- journal kept at %s, supervisor NOT started", err, journalPath)
		}
		log.Printf("swap failed: %v", err)
		_ = journal.archive("rolled_back")
		_ = ps(fmt.Sprintf("Start-ScheduledTask -TaskName '%s'", *task))
		die("update aborted (rolled back); backups at %s -- verify the rig is on %s", backupDir, cur)
	}
	_ = journal.setState("verifying")

	// Drop any pre-restart heartbeat and mark the restart instant, so the
	// liveness check below only accepts a heartbeat the NEW supervisor writes.
	_ = heartbeat.Remove(*heartbeatPath)
	restartAt := time.Now()
	log.Printf("swapped to %s; restarting via supervisor", tag)
	_ = ps(fmt.Sprintf("Start-ScheduledTask -TaskName '%s'", *task))

	// Both must report the new version. The backend's /healthz stays green even
	// if the worker is dead, so checking only the backend would bless a release
	// with a broken worker; require the worker too before keeping the swap.
	healthOK := verify(*serverHealth, newVersion) && verify(*workerHealth, newVersion)
	// A supervisor that started the children then died would still pass the
	// health checks above while leaving the rig with no crash-recovery. Require
	// proof it is alive AND looping: a heartbeat newer than the restart that then
	// advances. Treat "not proven" as a failed update, not merely a warning.
	superOK := true
	if healthOK && !*noHeartbeat {
		alive, herr := heartbeat.ProveLooping(*heartbeatPath, restartAt, *superInterval, 45*time.Second)
		superOK = alive
		if alive {
			log.Printf("supervisor heartbeat advanced past the restart -- crash-recovery is running")
		} else {
			log.Printf("supervisor is NOT proven looping after the update (%v)", herr)
		}
	}
	if healthOK && superOK {
		if err := journal.archive("committed"); err != nil {
			log.Printf("WARNING: update succeeded but the journal could not be archived (%v) -- remove %s by hand or the next run will roll this update back", err, journalPath)
		}
		log.Printf("update OK: backend + worker report %s and the supervisor is looping. Backup kept at %s", newVersion, backupDir)
		return
	}

	log.Printf("update did not come up healthy + alive on %s -- ROLLING BACK to %s", newVersion, cur)
	_ = journal.setState("rolling_back")
	_ = ps(fmt.Sprintf("Stop-ScheduledTask -TaskName '%s' -ErrorAction SilentlyContinue", *task))
	_ = ps("Get-Process modelrig-server,modelrig-worker,modelrig-supervisor -ErrorAction SilentlyContinue | Stop-Process -Force")
	time.Sleep(2 * time.Second)
	if err := restore(targets, backupDir); err != nil {
		// Broken set: keep the journal so the next run finishes the rollback,
		// and do NOT start the supervisor on it.
		_ = journal.setState("manual_recovery")
		die("ROLLBACK FAILED (%v). Journal kept at %s, backups at %s -- supervisor NOT started; restore by hand or rerun the updater.", err, journalPath, backupDir)
	}
	_ = journal.archive("rolled_back")
	_ = ps(fmt.Sprintf("Start-ScheduledTask -TaskName '%s'", *task))
	if verify(*serverHealth, cur) && verify(*workerHealth, cur) {
		log.Printf("rolled back to %s and both backend + worker are healthy again", cur)
	} else {
		log.Printf("rolled back to %s but health is still not confirmed -- check the rig", cur)
	}
}

func assetNames(targets []target) []string {
	out := make([]string, len(targets))
	for i, t := range targets {
		out[i] = t.asset
	}
	return out
}

// metaClient bounds the GitHub release-metadata fetch (small payload, short
// timeout) so a wedged connection can't block the updater before it even swaps.
var metaClient = &http.Client{Timeout: 30 * time.Second}

func httpGet(url string) ([]byte, error) {
	req, _ := http.NewRequest("GET", url, nil)
	req.Header.Set("Accept", "application/vnd.github+json")
	resp, err := metaClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("GET %s: %s", url, resp.Status)
	}
	return io.ReadAll(resp.Body)
}

func readRunningVersion(healthURL string) string {
	client := http.Client{Timeout: 4 * time.Second}
	resp, err := client.Get(healthURL)
	if err != nil {
		return ""
	}
	defer resp.Body.Close()
	var body struct {
		Version string `json:"version"`
	}
	b, _ := io.ReadAll(resp.Body)
	if json.Unmarshal(b, &body) != nil {
		return ""
	}
	return body.Version
}
