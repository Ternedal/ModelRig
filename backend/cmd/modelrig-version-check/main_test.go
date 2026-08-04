package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func writeFixture(t *testing.T, root, relative, content string) {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(relative))
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func completeFixture(t *testing.T, version string) string {
	t.Helper()
	root := t.TempDir()
	writeFixture(t, root, "VERSION", version+"\n")
	writeFixture(t, root, "worker/app/main.py", `VERSION = "`+version+`"`)
	writeFixture(t, root, "backend/internal/config/config.go", `const Version = "`+version+`"`)
	writeFixture(t, root, "android/app/build.gradle.kts", `versionName = "`+version+`"`)
	writeFixture(t, root, "desktop/composeApp/build.gradle.kts", `packageVersion = "`+version+`"`)
	return root
}

func TestRunAcceptsMatchingVersions(t *testing.T) {
	root := completeFixture(t, "1.2.3")
	var output bytes.Buffer
	if code := run(&output, nil, root); code != 0 {
		t.Fatalf("code=%d output=%s", code, output.String())
	}
	if !strings.Contains(output.String(), "all sites match VERSION 1.2.3") {
		t.Fatalf("unexpected output: %s", output.String())
	}
}

func TestRunRejectsDrift(t *testing.T) {
	root := completeFixture(t, "1.2.3")
	writeFixture(t, root, "worker/app/main.py", `VERSION = "1.2.4"`)
	var output bytes.Buffer
	if code := run(&output, nil, root); code != 1 {
		t.Fatalf("code=%d output=%s", code, output.String())
	}
	if !strings.Contains(output.String(), "1.2.4 != VERSION 1.2.3") {
		t.Fatalf("unexpected output: %s", output.String())
	}
}

func TestRunRejectsInvalidVersionAndArguments(t *testing.T) {
	root := completeFixture(t, "not-semver")
	var output bytes.Buffer
	if code := run(&output, nil, root); code != 1 {
		t.Fatalf("invalid version code=%d output=%s", code, output.String())
	}
	output.Reset()
	if code := run(&output, []string{"check"}, root); code != 2 {
		t.Fatalf("argument code=%d output=%s", code, output.String())
	}
}
