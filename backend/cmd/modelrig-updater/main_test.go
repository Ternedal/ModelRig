package main

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestIsNewer(t *testing.T) {
	cases := []struct {
		cur, latest string
		want        bool
	}{
		{"1.58.8", "1.58.9", true},
		{"1.58.9", "1.58.8", false},
		{"1.58.8", "1.58.8", false},
		{"v1.58.8", "v1.58.9", true},
		{"1.58.9", "1.59.0", true},
		{"1.59.0", "1.58.9", false},
		{"1.58", "1.58.1", true}, // missing patch counts as 0
		{"2.0.0", "1.99.99", false},
	}
	for _, c := range cases {
		got, err := isNewer(c.cur, c.latest)
		if err != nil {
			t.Fatalf("isNewer(%q,%q) error: %v", c.cur, c.latest, err)
		}
		if got != c.want {
			t.Errorf("isNewer(%q,%q) = %v, want %v", c.cur, c.latest, got, c.want)
		}
	}
	if _, err := isNewer("1.0.0", "not-a-version"); err == nil {
		t.Error("expected error on a non-semver latest")
	}
}

func TestSelectAssets(t *testing.T) {
	rel := []byte(`{"tag_name":"v1.58.9","assets":[
		{"name":"modelrig-server-windows-x64.exe","browser_download_url":"http://x/server"},
		{"name":"modelrig-worker-windows-x64.exe","browser_download_url":"http://x/worker"},
		{"name":"kaliv-latest.apk","browser_download_url":"http://x/apk"}]}`)
	tag, urls, err := selectAssets(rel, []string{"modelrig-server-windows-x64.exe", "modelrig-worker-windows-x64.exe"})
	if err != nil {
		t.Fatal(err)
	}
	if tag != "v1.58.9" {
		t.Errorf("tag = %q", tag)
	}
	if urls["modelrig-server-windows-x64.exe"] != "http://x/server" {
		t.Errorf("server url = %q", urls["modelrig-server-windows-x64.exe"])
	}
	// A missing wanted asset must be an error -- no partial update.
	if _, _, err := selectAssets(rel, []string{"modelrig-supervisor-windows-x64.exe"}); err == nil {
		t.Error("expected an error for a missing asset")
	}
}

func TestBackupAndSwapThenRestore(t *testing.T) {
	root := t.TempDir()
	staged := filepath.Join(root, "staged")
	backup := filepath.Join(root, "backup")
	if err := os.MkdirAll(staged, 0o755); err != nil {
		t.Fatal(err)
	}

	live := filepath.Join(root, "app.exe")
	if err := os.WriteFile(live, []byte("OLD"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(staged, "app.exe"), []byte("NEW"), 0o644); err != nil {
		t.Fatal(err)
	}
	targets := []target{{asset: "app.exe", live: live}}

	if err := backupAndSwap(targets, staged, backup, nil); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(live); string(b) != "NEW" {
		t.Fatalf("after swap live = %q, want NEW", b)
	}
	if b, _ := os.ReadFile(filepath.Join(backup, "app.exe")); string(b) != "OLD" {
		t.Fatalf("backup = %q, want OLD (the pre-swap binary)", b)
	}

	// Rollback restores the OLD binary over live.
	if err := restore(targets, backup); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(live); string(b) != "OLD" {
		t.Fatalf("after restore live = %q, want OLD", b)
	}
}

func TestParseSums(t *testing.T) {
	data := []byte("abc123  modelrig-server-windows-x64.exe\ndef456 *modelrig-worker-windows-x64.exe\n\n")
	m := parseSums(data)
	if m["modelrig-server-windows-x64.exe"] != "abc123" {
		t.Errorf("server hash = %q, want abc123", m["modelrig-server-windows-x64.exe"])
	}
	if m["modelrig-worker-windows-x64.exe"] != "def456" {
		t.Errorf("worker hash = %q, want def456 (the '*' marker should be stripped)", m["modelrig-worker-windows-x64.exe"])
	}
}

func TestFileSHA256(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "x")
	if err := os.WriteFile(p, []byte("abc"), 0o644); err != nil {
		t.Fatal(err)
	}
	got, err := fileSHA256(p)
	if err != nil {
		t.Fatal(err)
	}
	// Known SHA-256 of "abc".
	if want := "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"; got != want {
		t.Fatalf("sha256(abc) = %s, want %s", got, want)
	}
}

func TestAssetURL(t *testing.T) {
	rel := []byte(`{"tag_name":"v1","assets":[
		{"name":"SHA256SUMS.txt","browser_download_url":"http://x/sums"},
		{"name":"a.exe","browser_download_url":"http://x/a"}]}`)
	if assetURL(rel, "SHA256SUMS.txt") != "http://x/sums" {
		t.Error("SHA256SUMS.txt url wrong")
	}
	if assetURL(rel, "missing.txt") != "" {
		t.Error("a missing asset should return empty string")
	}
}

func hbWrite(t *testing.T, p, content string) {
	t.Helper()
	if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}
func hbRead(t *testing.T, p string) string {
	t.Helper()
	b, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}
func noTemp(t *testing.T, live string) {
	t.Helper()
	for _, ext := range []string{".new", ".old"} {
		if _, err := os.Stat(live + ext); !os.IsNotExist(err) {
			t.Errorf("temp file %s%s left behind", live, ext)
		}
	}
}

func TestAtomicSwapInto(t *testing.T) {
	dir := t.TempDir()
	live := filepath.Join(dir, "app.exe")
	src := filepath.Join(dir, "src")
	hbWrite(t, live, "OLD")
	hbWrite(t, src, "NEW")
	if err := atomicSwapInto(src, live); err != nil {
		t.Fatal(err)
	}
	if hbRead(t, live) != "NEW" {
		t.Errorf("live not swapped: %q", hbRead(t, live))
	}
	noTemp(t, live)
	// missing src -> error, live untouched (never truncated)
	if err := atomicSwapInto(filepath.Join(dir, "nope"), live); err == nil {
		t.Error("swap from a missing source should error")
	}
	if hbRead(t, live) != "NEW" {
		t.Errorf("live changed on a failed swap: %q", hbRead(t, live))
	}
	noTemp(t, live)
}

func TestBackupAndSwapAtomicOnMidFailure(t *testing.T) {
	// The audit's scenario: target 2's staged file is missing, so its swap
	// fails. Target 1 (already swapped) must be restored and NO live file left
	// partially written.
	liveDir, stagedDir, backupDir := t.TempDir(), t.TempDir(), t.TempDir()
	t1 := target{asset: "a.exe", live: filepath.Join(liveDir, "a.exe")}
	t2 := target{asset: "b.exe", live: filepath.Join(liveDir, "b.exe")}
	hbWrite(t, t1.live, "OLD_A")
	hbWrite(t, t2.live, "OLD_B")
	hbWrite(t, filepath.Join(stagedDir, "a.exe"), "NEW_A")
	// b.exe staged file deliberately absent

	if err := backupAndSwap([]target{t1, t2}, stagedDir, backupDir, nil); err == nil {
		t.Fatal("expected failure when a staged file is missing")
	}
	if got := hbRead(t, t1.live); got != "OLD_A" {
		t.Errorf("target 1 not restored after mid-swap failure: %q", got)
	}
	if got := hbRead(t, t2.live); got != "OLD_B" {
		t.Errorf("target 2 corrupted by failed swap: %q", got)
	}
	noTemp(t, t1.live)
	noTemp(t, t2.live)
}

func TestBackupAndSwapSuccess(t *testing.T) {
	liveDir, stagedDir, backupDir := t.TempDir(), t.TempDir(), t.TempDir()
	tg := target{asset: "a.exe", live: filepath.Join(liveDir, "a.exe")}
	hbWrite(t, tg.live, "OLD")
	hbWrite(t, filepath.Join(stagedDir, "a.exe"), "NEW")
	if err := backupAndSwap([]target{tg}, stagedDir, backupDir, nil); err != nil {
		t.Fatal(err)
	}
	if got := hbRead(t, tg.live); got != "NEW" {
		t.Errorf("not swapped: %q", got)
	}
	if got := hbRead(t, filepath.Join(backupDir, "a.exe")); got != "OLD" {
		t.Errorf("backup not written: %q", got)
	}
	noTemp(t, tg.live)
}

func TestAtomicSwapInto_FinalRenameFailsRestores(t *testing.T) {
	dir := t.TempDir()
	live := filepath.Join(dir, "app.exe")
	src := filepath.Join(dir, "src")
	hbWrite(t, live, "OLD")
	hbWrite(t, src, "NEW")

	orig := renameFn
	defer func() { renameFn = orig }()
	// Fail the .new->live rename; let live->old and the old->live restore work.
	renameFn = func(from, to string) error {
		if strings.HasSuffix(from, ".new") {
			return errors.New("injected rename failure")
		}
		return orig(from, to)
	}
	if err := atomicSwapInto(src, live); err == nil {
		t.Fatal("expected the swap to fail")
	}
	if got := hbRead(t, live); got != "OLD" {
		t.Errorf("live not restored to the original: %q", got)
	}
	noTemp(t, live)
}

func TestAtomicSwapInto_RestoreAlsoFails(t *testing.T) {
	dir := t.TempDir()
	live := filepath.Join(dir, "app.exe")
	src := filepath.Join(dir, "src")
	hbWrite(t, live, "OLD")
	hbWrite(t, src, "NEW")

	orig := renameFn
	defer func() { renameFn = orig }()
	// Fail BOTH the .new->live rename and the .old->live restore.
	renameFn = func(from, to string) error {
		if strings.HasSuffix(from, ".new") || strings.HasSuffix(from, ".old") {
			return errors.New("injected rename failure")
		}
		return orig(from, to)
	}
	err := atomicSwapInto(src, live)
	if err == nil {
		t.Fatal("expected the swap to fail")
	}
	if !strings.Contains(err.Error(), "recover by hand") {
		t.Errorf("error should point to manual recovery, got: %v", err)
	}
	if !errors.Is(err, errRollbackFailed) {
		t.Errorf("a missing live file IS a failed rollback -- must wrap errRollbackFailed, got: %v", err)
	}
	// .old must survive for recovery (live was moved there and never restored).
	if _, e := os.Stat(live + ".old"); e != nil {
		t.Errorf(".old should be preserved for recovery: %v", e)
	}
}

func TestRecoverTarget(t *testing.T) {
	// live present -> no-op
	d1 := t.TempDir()
	live1 := filepath.Join(d1, "app.exe")
	hbWrite(t, live1, "LIVE")
	hbWrite(t, live1+".old", "OLDLEFT")
	if err := recoverTarget(live1); err != nil {
		t.Fatal(err)
	}
	if hbRead(t, live1) != "LIVE" {
		t.Error("live changed when it should not")
	}

	// live missing + .old present -> restore from .old, .new removed
	d2 := t.TempDir()
	live2 := filepath.Join(d2, "app.exe")
	hbWrite(t, live2+".old", "ORIG")
	hbWrite(t, live2+".new", "INTERRUPTED")
	if err := recoverTarget(live2); err != nil {
		t.Fatal(err)
	}
	if hbRead(t, live2) != "ORIG" {
		t.Errorf("live not restored from .old: %q", hbRead(t, live2))
	}
	if _, e := os.Stat(live2 + ".new"); !os.IsNotExist(e) {
		t.Error(".new should be removed after recovery")
	}

	// live missing + only .new -> fail closed, delete nothing
	d3 := t.TempDir()
	live3 := filepath.Join(d3, "app.exe")
	hbWrite(t, live3+".new", "ONLYNEW")
	if err := recoverTarget(live3); err == nil {
		t.Error("only-.new should fail closed")
	}
	if _, e := os.Stat(live3 + ".new"); e != nil {
		t.Error(".new must not be deleted on fail-closed")
	}

	// live missing + nothing -> error
	d4 := t.TempDir()
	if err := recoverTarget(filepath.Join(d4, "app.exe")); err == nil {
		t.Error("missing live with no recovery files should error")
	}
}

func TestAtomicSwapInto_RefusesMissingLive(t *testing.T) {
	// The data-loss scenario: live is gone but .old (recovery copy) is present.
	// atomicSwapInto must refuse WITHOUT deleting .old.
	dir := t.TempDir()
	live := filepath.Join(dir, "app.exe")
	src := filepath.Join(dir, "src")
	hbWrite(t, live+".old", "RECOVERY")
	hbWrite(t, src, "NEW")
	if err := atomicSwapInto(src, live); err == nil {
		t.Fatal("expected refusal when live is missing")
	}
	if _, e := os.Stat(live + ".old"); e != nil {
		t.Error(".old (recovery copy) must be preserved, not deleted")
	}
}

func TestJournalLifecycle(t *testing.T) {
	dir := t.TempDir()
	jp := filepath.Join(dir, "update-transaction.json")
	j, err := newJournal(jp, "1.0.0", "1.0.1", filepath.Join(dir, "bak"))
	if err != nil {
		t.Fatal(err)
	}
	if d, _ := readJournal(jp); d == nil || d.State != "prepared" {
		t.Fatalf("journal should exist as prepared, got %+v", d)
	}
	// a second transaction must be refused while one is recorded
	if _, err := newJournal(jp, "1.0.0", "1.0.1", "x"); err == nil {
		t.Error("a second journal over an existing one should be refused")
	}
	j.setState("backed_up")
	j.addSwapped("a.exe")
	d, _ := readJournal(jp)
	if d.State != "swapping" || len(d.Swapped) != 1 || d.Swapped[0] != "a.exe" {
		t.Fatalf("state/swapped not persisted: %+v", d)
	}
	if err := j.archive("committed"); err != nil {
		t.Fatal(err)
	}
	if d, _ := readJournal(jp); d != nil {
		t.Error("archived journal should read as no pending transaction")
	}
	if !fileExists(jp + ".last") {
		t.Error(".last forensic copy should exist after archive")
	}
	// nil journal is a no-op everywhere (tests + optional use)
	var nilJ *txJournal
	if nilJ.setState("x") != nil || nilJ.addSwapped("y") != nil || nilJ.archive("z") != nil {
		t.Error("nil journal methods should no-op")
	}
}

func TestRecoverFromJournal_WholeSet(t *testing.T) {
	// Crash mid-transaction: A was swapped to NEW, B's swap was interrupted
	// (live missing, .new left). The whole-set recovery must put BOTH back to
	// their pre-transaction versions and archive the journal.
	root := t.TempDir()
	bakDir := filepath.Join(root, "bak")
	os.MkdirAll(bakDir, 0o755)
	tA := target{asset: "a.exe", live: filepath.Join(root, "a.exe")}
	tB := target{asset: "b.exe", live: filepath.Join(root, "b.exe")}
	hbWrite(t, filepath.Join(bakDir, "a.exe"), "OLD_A")
	hbWrite(t, filepath.Join(bakDir, "b.exe"), "OLD_B")
	hbWrite(t, tA.live, "NEW_A")          // swapped before the crash
	hbWrite(t, tB.live+".new", "NEW_B")   // interrupted: live missing, .new left

	jp := filepath.Join(root, "update-transaction.json")
	j, err := newJournal(jp, "1.0.0", "1.0.1", bakDir)
	if err != nil {
		t.Fatal(err)
	}
	j.setState("backed_up")
	j.addSwapped("a.exe")

	if err := recoverFromJournal(jp, []target{tA, tB}); err != nil {
		t.Fatal(err)
	}
	if got := hbRead(t, tA.live); got != "OLD_A" {
		t.Errorf("A not rolled back: %q", got)
	}
	if got := hbRead(t, tB.live); got != "OLD_B" {
		t.Errorf("B not restored: %q", got)
	}
	if d, _ := readJournal(jp); d != nil {
		t.Error("journal should be archived after whole-set rollback")
	}
	noTemp(t, tA.live)
	noTemp(t, tB.live)
	// no journal -> no-op
	if err := recoverFromJournal(jp, []target{tA, tB}); err != nil {
		t.Errorf("recovery with no journal should be a no-op: %v", err)
	}
}

func TestAcquireLockExclusive(t *testing.T) {
	p := filepath.Join(t.TempDir(), "updater.lock")
	if err := acquireLock(p); err != nil {
		t.Fatal(err)
	}
	if err := acquireLock(p); err == nil {
		t.Error("second acquire should fail while the lock exists")
	}
	releaseLock(p)
	if err := acquireLock(p); err != nil {
		t.Errorf("acquire after release should succeed: %v", err)
	}
}

func TestBackupAndSwap_AllBackupsBeforeFirstSwap(t *testing.T) {
	// Phase 1 must capture EVERY target before any swap: with target 2's staged
	// file missing, its swap fails -- but its backup must already exist.
	liveDir, stagedDir, backupDir := t.TempDir(), t.TempDir(), t.TempDir()
	t1 := target{asset: "a.exe", live: filepath.Join(liveDir, "a.exe")}
	t2 := target{asset: "b.exe", live: filepath.Join(liveDir, "b.exe")}
	hbWrite(t, t1.live, "OLD_A")
	hbWrite(t, t2.live, "OLD_B")
	hbWrite(t, filepath.Join(stagedDir, "a.exe"), "NEW_A")
	// b.exe staged deliberately absent
	if err := backupAndSwap([]target{t1, t2}, stagedDir, backupDir, nil); err == nil {
		t.Fatal("expected failure")
	}
	if got := hbRead(t, filepath.Join(backupDir, "b.exe")); got != "OLD_B" {
		t.Errorf("b.exe must be backed up BEFORE the first swap, got %q", got)
	}
	if got := hbRead(t, t1.live); got != "OLD_A" {
		t.Errorf("a.exe not restored: %q", got)
	}
}

func TestBackupAndSwap_InnerRestoreFailureIsRollbackFailed(t *testing.T) {
	// P1-1 end to end: A swaps fine; B's final rename fails AND its .old
	// restore fails (live missing). A's rollback succeeds -- but the combined
	// error must STILL be errRollbackFailed, so main goes to manual_recovery
	// and never starts the supervisor on a set with a missing exe.
	liveDir, stagedDir, backupDir := t.TempDir(), t.TempDir(), t.TempDir()
	t1 := target{asset: "a.exe", live: filepath.Join(liveDir, "a.exe")}
	t2 := target{asset: "b.exe", live: filepath.Join(liveDir, "b.exe")}
	hbWrite(t, t1.live, "OLD_A")
	hbWrite(t, t2.live, "OLD_B")
	hbWrite(t, filepath.Join(stagedDir, "a.exe"), "NEW_A")
	hbWrite(t, filepath.Join(stagedDir, "b.exe"), "NEW_B")

	orig := renameFn
	defer func() { renameFn = orig }()
	renameFn = func(from, to string) error {
		if strings.HasSuffix(from, "b.exe.new") || strings.HasSuffix(from, "b.exe.old") {
			return errors.New("injected rename failure")
		}
		return orig(from, to)
	}
	err := backupAndSwap([]target{t1, t2}, stagedDir, backupDir, nil)
	if err == nil {
		t.Fatal("expected failure")
	}
	if !errors.Is(err, errRollbackFailed) {
		t.Errorf("missing live exe must classify as rollback failure, got: %v", err)
	}
	if got := hbRead(t, t1.live); got != "OLD_A" {
		t.Errorf("A should be rolled back: %q", got)
	}
}

func TestRecoverFromJournal_CommittedNeverRollsBack(t *testing.T) {
	// P1-3: a committed journal whose .last rename failed must NOT undo a
	// verified healthy update at the next run -- only finish the archive.
	root := t.TempDir()
	bakDir := filepath.Join(root, "bak")
	os.MkdirAll(bakDir, 0o755)
	tg := target{asset: "a.exe", live: filepath.Join(root, "a.exe")}
	hbWrite(t, filepath.Join(bakDir, "a.exe"), "OLD")
	hbWrite(t, tg.live, "NEW") // the committed, healthy version

	jp := filepath.Join(root, "update-transaction.json")
	j, err := newJournal(jp, "1.0.0", "1.0.1", bakDir)
	if err != nil {
		t.Fatal(err)
	}
	j.data.State = "committed" // as if archive's rename failed after commit
	if err := j.write(); err != nil {
		t.Fatal(err)
	}
	if err := recoverFromJournal(jp, []target{tg}); err != nil {
		t.Fatal(err)
	}
	if got := hbRead(t, tg.live); got != "NEW" {
		t.Errorf("committed update was rolled back: %q", got)
	}
	if d, _ := readJournal(jp); d != nil {
		t.Error("journal should be archived")
	}
	if !fileExists(jp + ".last") {
		t.Error(".last should exist")
	}
}

func TestRecoverFromJournal_MissingBackupFailsClosed(t *testing.T) {
	// P1-2: past backed_up, EVERY target must have a backup. One missing ->
	// no file is touched, the journal is kept as manual_recovery, error out.
	root := t.TempDir()
	bakDir := filepath.Join(root, "bak")
	os.MkdirAll(bakDir, 0o755)
	tA := target{asset: "a.exe", live: filepath.Join(root, "a.exe")}
	tB := target{asset: "b.exe", live: filepath.Join(root, "b.exe")}
	hbWrite(t, filepath.Join(bakDir, "a.exe"), "OLD_A")
	// b.exe backup deliberately missing
	hbWrite(t, tA.live, "NEW_A")
	hbWrite(t, tB.live, "NEW_B")

	jp := filepath.Join(root, "update-transaction.json")
	j, err := newJournal(jp, "1.0.0", "1.0.1", bakDir)
	if err != nil {
		t.Fatal(err)
	}
	j.setState("backed_up")
	if err := recoverFromJournal(jp, []target{tA, tB}); err == nil {
		t.Fatal("missing backup must fail closed")
	}
	if got := hbRead(t, tA.live); got != "NEW_A" {
		t.Errorf("no file may be touched on fail-closed, a.exe: %q", got)
	}
	d, _ := readJournal(jp)
	if d == nil || d.State != "manual_recovery" {
		t.Fatalf("journal must be kept as manual_recovery, got %+v", d)
	}
}

func TestRecoverFromJournal_PreparedArchivesOnly(t *testing.T) {
	// prepared = zero live mutations happened; recovery must archive and
	// restore nothing, even if some backups exist.
	root := t.TempDir()
	bakDir := filepath.Join(root, "bak")
	os.MkdirAll(bakDir, 0o755)
	tg := target{asset: "a.exe", live: filepath.Join(root, "a.exe")}
	hbWrite(t, filepath.Join(bakDir, "a.exe"), "OLD")
	hbWrite(t, tg.live, "CURRENT")

	jp := filepath.Join(root, "update-transaction.json")
	if _, err := newJournal(jp, "1.0.0", "1.0.1", bakDir); err != nil {
		t.Fatal(err)
	}
	if err := recoverFromJournal(jp, []target{tg}); err != nil {
		t.Fatal(err)
	}
	if got := hbRead(t, tg.live); got != "CURRENT" {
		t.Errorf("prepared recovery must not touch live files: %q", got)
	}
	if d, _ := readJournal(jp); d != nil {
		t.Error("journal should be archived")
	}
}

func writeJournalFile(t *testing.T, path string, d txData) {
	t.Helper()
	b, err := json.Marshal(d)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, b, 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestReadJournal_PicksNewerTmpRevision(t *testing.T) {
	// The P1-2 crash: archive("committed") wrote the tmp (newer revision) and
	// crashed before the rename -- main still says verifying. Preferring main
	// would roll back a verified healthy update; the higher revision must win.
	root := t.TempDir()
	jp := filepath.Join(root, "update-transaction.json")
	writeJournalFile(t, jp, txData{ID: "tx1", State: "verifying", Revision: 3})
	writeJournalFile(t, jp+".tmp", txData{ID: "tx1", State: "committed", Revision: 4})
	d, err := readJournal(jp)
	if err != nil {
		t.Fatal(err)
	}
	if d.State != "committed" {
		t.Errorf("newer tmp revision must win, got state %q", d.State)
	}
	// and an OLDER tmp must lose to main
	writeJournalFile(t, jp+".tmp", txData{ID: "tx1", State: "backed_up", Revision: 2})
	if d, err := readJournal(jp); err != nil || d.State != "verifying" {
		t.Errorf("older tmp must lose to main, got %+v err %v", d, err)
	}

	// End to end: with the committed tmp present, recovery must archive and
	// never restore the old binary.
	bakDir := filepath.Join(root, "bak")
	os.MkdirAll(bakDir, 0o755)
	tg := target{asset: "a.exe", live: filepath.Join(root, "a.exe")}
	hbWrite(t, filepath.Join(bakDir, "a.exe"), "OLD")
	hbWrite(t, tg.live, "NEW")
	writeJournalFile(t, jp, txData{ID: "tx1", State: "verifying", Revision: 3, BackupDir: bakDir})
	writeJournalFile(t, jp+".tmp", txData{ID: "tx1", State: "committed", Revision: 4, BackupDir: bakDir})
	if err := recoverFromJournal(jp, []target{tg}); err != nil {
		t.Fatal(err)
	}
	if got := hbRead(t, tg.live); got != "NEW" {
		t.Errorf("committed tmp must prevent rollback of the healthy update: %q", got)
	}
	if d, _ := readJournal(jp); d != nil {
		t.Error("journal should be archived")
	}
}

func TestReadJournal_UnreadableFailsClosed(t *testing.T) {
	// Unreadable transaction evidence must never pass as "no journal".
	root := t.TempDir()
	jp := filepath.Join(root, "update-transaction.json")
	hbWrite(t, jp, "{not json")
	if _, err := readJournal(jp); err == nil {
		t.Error("corrupt main journal must fail closed")
	}
	os.Remove(jp)
	hbWrite(t, jp+".tmp", "{not json")
	if _, err := readJournal(jp); err == nil {
		t.Error("corrupt tmp journal must fail closed")
	}
	writeJournalFile(t, jp, txData{ID: "tx1", State: "verifying", Revision: 3})
	if _, err := readJournal(jp); err == nil {
		t.Error("valid main + corrupt tmp is ambiguity and must fail closed")
	}
}

func TestReadJournal_ConflictFailsClosed(t *testing.T) {
	root := t.TempDir()
	jp := filepath.Join(root, "update-transaction.json")
	writeJournalFile(t, jp, txData{ID: "tx1", State: "verifying", Revision: 3})
	writeJournalFile(t, jp+".tmp", txData{ID: "tx2", State: "committed", Revision: 4})
	if _, err := readJournal(jp); err == nil {
		t.Error("different transaction IDs must fail closed")
	}
	writeJournalFile(t, jp+".tmp", txData{ID: "tx1", State: "committed", Revision: 3})
	if _, err := readJournal(jp); err == nil {
		t.Error("equal revisions with different states must fail closed")
	}
	writeJournalFile(t, jp+".tmp", txData{ID: "tx1", State: "verifying", Revision: 3})
	if d, err := readJournal(jp); err != nil || d == nil || d.State != "verifying" {
		t.Errorf("identical duplicates should read fine, got %+v err %v", d, err)
	}
}

func TestJournalNeedsProcessStop(t *testing.T) {
	for state, want := range map[string]bool{
		"committed": false, "rolled_back": false, "prepared": false,
		"backed_up": true, "swapping": true, "verifying": true,
		"rolling_back": true, "manual_recovery": true, "unknown-state": true,
	} {
		if got := journalNeedsProcessStop(state); got != want {
			t.Errorf("journalNeedsProcessStop(%q) = %v, want %v", state, got, want)
		}
	}
}
