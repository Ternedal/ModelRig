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
	"encoding/json"
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

func download(url, dest string) error {
	resp, err := http.Get(url)
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
	return out.Close()
}

// backupAndSwap copies each live file into backupDir, then moves the staged
// (downloaded) file into the live path. If any step fails partway, it restores
// whatever it already backed up, so the rig is never left with a half-swapped
// set. On success the caller can start the new binaries.
func backupAndSwap(targets []target, stagedDir, backupDir string) error {
	if err := os.MkdirAll(backupDir, 0o755); err != nil {
		return err
	}
	var swapped []target
	for _, t := range targets {
		bak := filepath.Join(backupDir, t.asset)
		if err := copyFile(t.live, bak); err != nil {
			restore(swapped, backupDir) // best-effort undo of what we swapped
			return fmt.Errorf("backup %s: %w", t.live, err)
		}
		staged := filepath.Join(stagedDir, t.asset)
		if err := replaceFile(staged, t.live); err != nil {
			restore(swapped, backupDir)
			return fmt.Errorf("swap %s: %w", t.live, err)
		}
		swapped = append(swapped, t)
	}
	return nil
}

// replaceFile overwrites dst with src's contents (copy, not rename, so it works
// across volumes and leaves the staged file for cleanup).
func replaceFile(src, dst string) error {
	return copyFile(src, dst)
}

// restore copies each target's backed-up binary back over the live path. Used
// both on a mid-swap failure and on a failed health check after the swap.
func restore(targets []target, backupDir string) error {
	var firstErr error
	for _, t := range targets {
		bak := filepath.Join(backupDir, t.asset)
		if err := copyFile(bak, t.live); err != nil && firstErr == nil {
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

func main() {
	dir, _ := os.Getwd()
	root := flag.String("dir", dir, "ModelRig root (where the exes live)")
	repo := flag.String("repo", "Ternedal/ModelRig", "owner/name of the GitHub repo")
	current := flag.String("current", "", "current version (default: read from the running server /healthz)")
	serverHealth := flag.String("server-health", "http://127.0.0.1:8080/healthz", "server health URL")
	workerHealth := flag.String("worker-health", "http://127.0.0.1:8099/healthz", "worker health URL")
	task := flag.String("supervisor-task", "KalivSupervisor", "scheduled task that runs the supervisor")
	checkOnly := flag.Bool("check", false, "report whether an update is available and exit")
	flag.Parse()
	log.SetPrefix("updater: ")
	log.SetFlags(log.LstdFlags)

	targets := []target{
		{"modelrig-server-windows-x64.exe", filepath.Join(*root, "modelrig-server-windows-x64.exe")},
		{"modelrig-supervisor-windows-x64.exe", filepath.Join(*root, "modelrig-supervisor-windows-x64.exe")},
		{"modelrig-worker-windows-x64.exe", filepath.Join(*root, "worker", "modelrig-worker-windows-x64.exe")},
	}

	cur := *current
	if cur == "" {
		cur = readRunningVersion(*serverHealth)
		if cur == "" {
			log.Fatalf("could not read current version from %s; pass -current", *serverHealth)
		}
	}

	relBody, err := httpGet(fmt.Sprintf("https://api.github.com/repos/%s/releases/latest", *repo))
	if err != nil {
		log.Fatalf("fetch latest release: %v", err)
	}
	tag, urls, err := selectAssets(relBody, assetNames(targets))
	if err != nil {
		log.Fatalf("%v", err)
	}
	newer, err := isNewer(cur, tag)
	if err != nil {
		log.Fatalf("version compare: %v", err)
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

	staged, err := os.MkdirTemp("", "kaliv-update-")
	if err != nil {
		log.Fatalf("staging dir: %v", err)
	}
	defer os.RemoveAll(staged)
	for _, t := range targets {
		dest := filepath.Join(staged, t.asset)
		log.Printf("downloading %s", t.asset)
		if err := download(urls[t.asset], dest); err != nil {
			log.Fatalf("download %s: %v", t.asset, err)
		}
	}

	backupDir := filepath.Join(*root, "backups", "exe-"+cur)
	log.Printf("stopping supervisor + processes so the exes unlock")
	_ = ps(fmt.Sprintf("Stop-ScheduledTask -TaskName '%s' -ErrorAction SilentlyContinue", *task))
	_ = ps("Get-Process modelrig-server,modelrig-worker,modelrig-supervisor -ErrorAction SilentlyContinue | Stop-Process -Force")
	time.Sleep(2 * time.Second)

	if err := backupAndSwap(targets, staged, backupDir); err != nil {
		log.Printf("swap failed and was rolled back: %v", err)
		_ = ps(fmt.Sprintf("Start-ScheduledTask -TaskName '%s'", *task))
		log.Fatalf("update aborted; still on %s", cur)
	}

	log.Printf("swapped to %s; restarting via supervisor", tag)
	_ = ps(fmt.Sprintf("Start-ScheduledTask -TaskName '%s'", *task))

	// Both must report the new version. The backend's /healthz stays green even
	// if the worker is dead, so checking only the backend would bless a release
	// with a broken worker; require the worker too before keeping the swap.
	if verify(*serverHealth, newVersion) && verify(*workerHealth, newVersion) {
		log.Printf("update OK: backend AND worker /healthz report %s. Backup kept at %s", newVersion, backupDir)
		return
	}

	log.Printf("backend or worker did not come up healthy on %s -- ROLLING BACK to %s", newVersion, cur)
	_ = ps(fmt.Sprintf("Stop-ScheduledTask -TaskName '%s' -ErrorAction SilentlyContinue", *task))
	_ = ps("Get-Process modelrig-server,modelrig-worker,modelrig-supervisor -ErrorAction SilentlyContinue | Stop-Process -Force")
	time.Sleep(2 * time.Second)
	if err := restore(targets, backupDir); err != nil {
		log.Fatalf("ROLLBACK FAILED (%v). Backup is at %s -- restore by hand.", err, backupDir)
	}
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

func httpGet(url string) ([]byte, error) {
	req, _ := http.NewRequest("GET", url, nil)
	req.Header.Set("Accept", "application/vnd.github+json")
	resp, err := http.DefaultClient.Do(req)
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
