package main

import (
	"os"
	"path/filepath"
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

	if err := backupAndSwap(targets, staged, backup); err != nil {
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
