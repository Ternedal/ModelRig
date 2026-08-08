package main

import (
	"encoding/base64"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"modelrig/internal/config"
)

func TestParseSelfUpdateArgs(t *testing.T) {
	root := t.TempDir()
	cfg, err := parseSelfUpdateArgs([]string{
		"-self-update",
		"-repo", "Example/Repo",
		"-dir", root,
		"-skip-attestation",
	})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.repo != "Example/Repo" {
		t.Fatalf("repo = %q", cfg.repo)
	}
	wantRoot, _ := filepath.Abs(root)
	if cfg.root != wantRoot {
		t.Fatalf("root = %q, want %q", cfg.root, wantRoot)
	}
	if !cfg.skipAttestation || cfg.skipVerify {
		t.Fatalf("flags parsed incorrectly: %+v", cfg)
	}
}

func TestParseSelfUpdateArgsRejectsUnknownArgument(t *testing.T) {
	if _, err := parseSelfUpdateArgs([]string{"-self-update", "-current", "1.2.3"}); err == nil {
		t.Fatal("unknown normal-update flags must not silently change self-update behaviour")
	}
}

func TestUpdaterVersionUsesCompiledBackendIdentity(t *testing.T) {
	if updaterVersion != config.Version {
		t.Fatalf("updater version %q differs from compiled backend version %q", updaterVersion, config.Version)
	}
	if got := resolveUpdaterVersion(); got != config.Version {
		t.Fatalf("resolved version = %q, want %q", got, config.Version)
	}
}

func TestResolveUpdaterVersionNormalizesEmbeddedVersion(t *testing.T) {
	old := updaterVersion
	defer func() { updaterVersion = old }()
	updaterVersion = "v9.8.7"
	if got := resolveUpdaterVersion(); got != "9.8.7" {
		t.Fatalf("version = %q", got)
	}
}

func TestResolveUpdaterVersionFailsClosedToDev(t *testing.T) {
	old := updaterVersion
	defer func() { updaterVersion = old }()
	updaterVersion = "not-semver"
	if got := resolveUpdaterVersion(); got != "dev" {
		t.Fatalf("version = %q, want dev", got)
	}
}

func TestCopyFileExclusive(t *testing.T) {
	root := t.TempDir()
	src := filepath.Join(root, "new.exe")
	dst := filepath.Join(root, "live.exe.pending")
	if err := os.WriteFile(src, []byte("NEW"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := copyFileExclusive(src, dst); err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(dst)
	if err != nil {
		t.Fatal(err)
	}
	if string(b) != "NEW" {
		t.Fatalf("pending = %q", b)
	}
	if err := copyFileExclusive(src, dst); err == nil {
		t.Fatal("existing pending file must fail closed instead of being overwritten")
	}
	b, err = os.ReadFile(dst)
	if err != nil || string(b) != "NEW" {
		t.Fatalf("existing pending changed after refused overwrite: %q, %v", b, err)
	}
}

func TestPowerShellLiteralEscapesSingleQuote(t *testing.T) {
	if got, want := powershellLiteral(`C:\Anders's Rig\updater.exe`), `'C:\Anders''s Rig\updater.exe'`; got != want {
		t.Fatalf("literal = %q, want %q", got, want)
	}
}

func TestReplacementHelperWaitsMovesThenReleasesLock(t *testing.T) {
	script := replacementHelperScript(
		1234,
		`C:\Rig\updater.exe.pending`,
		`C:\Rig\updater.exe`,
		`C:\Rig\updater.lock`,
	)
	for _, required := range []string{
		"Wait-Process -Id 1234",
		"Move-Item -LiteralPath 'C:\\Rig\\updater.exe.pending'",
		"-Destination 'C:\\Rig\\updater.exe' -Force",
		"finally { Remove-Item -LiteralPath 'C:\\Rig\\updater.lock'",
	} {
		if !strings.Contains(script, required) {
			t.Fatalf("helper script missing %q: %s", required, script)
		}
	}
	waitAt := strings.Index(script, "Wait-Process")
	moveAt := strings.Index(script, "Move-Item")
	unlockAt := strings.Index(script, "Remove-Item")
	if waitAt < 0 || moveAt < 0 || unlockAt < 0 || !(waitAt < moveAt && moveAt < unlockAt) {
		t.Fatalf("helper order must be wait -> move -> unlock: %s", script)
	}
}

func TestCountReleaseAttestationsBindsRepoTagWorkflowAndDigest(t *testing.T) {
	digest := strings.Repeat("a", 64)
	body := releaseAttestationBody(t, "https://github.com/Ternedal/ModelRig", "refs/tags/v1.58.151", releaseWorkflowPath, digest)

	got, err := countReleaseAttestations(body, "Ternedal/ModelRig", digest, "v1.58.151")
	if err != nil {
		t.Fatal(err)
	}
	if got != 1 {
		t.Fatalf("matching attestations = %d, want 1", got)
	}
}

func TestCountReleaseAttestationsRejectsPreviouslyAttestedOlderRelease(t *testing.T) {
	digest := strings.Repeat("b", 64)
	body := releaseAttestationBody(t, "https://github.com/Ternedal/ModelRig", "refs/tags/v1.58.140", releaseWorkflowPath, digest)

	got, err := countReleaseAttestations(body, "Ternedal/ModelRig", digest, "v1.58.151")
	if err != nil {
		t.Fatal(err)
	}
	if got != 0 {
		t.Fatalf("older release attestation matched newer tag: %d", got)
	}
}

func TestCountReleaseAttestationsRejectsOtherWorkflowOrDigest(t *testing.T) {
	digest := strings.Repeat("c", 64)
	body := releaseAttestationBody(t, "https://github.com/Ternedal/ModelRig", "refs/tags/v1.58.151", ".github/workflows/ci.yml", digest)
	got, err := countReleaseAttestations(body, "Ternedal/ModelRig", digest, "v1.58.151")
	if err != nil {
		t.Fatal(err)
	}
	if got != 0 {
		t.Fatalf("non-release workflow attestation matched: %d", got)
	}

	body = releaseAttestationBody(t, "https://github.com/Ternedal/ModelRig", "refs/tags/v1.58.151", releaseWorkflowPath, strings.Repeat("d", 64))
	got, err = countReleaseAttestations(body, "Ternedal/ModelRig", digest, "v1.58.151")
	if err != nil {
		t.Fatal(err)
	}
	if got != 0 {
		t.Fatalf("wrong digest attestation matched: %d", got)
	}
}

func releaseAttestationBody(t *testing.T, repo, ref, workflowPath, digest string) []byte {
	t.Helper()
	statement := map[string]any{
		"_type":         "https://in-toto.io/Statement/v1",
		"predicateType": "https://slsa.dev/provenance/v1",
		"subject": []any{map[string]any{
			"name": updaterAssetName,
			"digest": map[string]string{"sha256": digest},
		}},
		"predicate": map[string]any{
			"buildDefinition": map[string]any{
				"externalParameters": map[string]any{
					"workflow": map[string]string{
						"ref":        ref,
						"repository": repo,
						"path":       workflowPath,
					},
				},
			},
		},
	}
	statementJSON, err := json.Marshal(statement)
	if err != nil {
		t.Fatal(err)
	}
	payload := map[string]any{
		"attestations": []any{map[string]any{
			"bundle": map[string]any{
				"dsseEnvelope": map[string]string{
					"payload": base64.StdEncoding.EncodeToString(statementJSON),
				},
			},
		}},
	}
	body, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	return body
}
