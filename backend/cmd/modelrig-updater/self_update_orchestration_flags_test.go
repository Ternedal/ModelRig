package main

import (
	"path/filepath"
	"strings"
	"testing"
)

func TestParseAutomaticSelfUpdateArgsAcceptsGoFlagSpellings(t *testing.T) {
	root := t.TempDir()
	wantRoot, err := filepath.Abs(root)
	if err != nil {
		t.Fatal(err)
	}

	cases := []struct {
		name           string
		args           []string
		wantSkipVerify bool
		wantSkipAttest bool
	}{
		{
			name: "double dash and equals",
			args: []string{
				"--dir=" + root,
				"--repo=Example/Repo",
				"--insecure-skip-verify",
				"--skip-attestation=true",
			},
			wantSkipVerify: true,
			wantSkipAttest: true,
		},
		{
			name: "single dash mixed values",
			args: []string{
				"-dir", root,
				"-repo=Example/Repo",
				"-insecure-skip-verify=1",
				"-skip-attestation=t",
			},
			wantSkipVerify: true,
			wantSkipAttest: true,
		},
		{
			name: "explicit false does not become true",
			args: []string{
				"--dir", root,
				"--repo", "Example/Repo",
				"--insecure-skip-verify=false",
				"--skip-attestation=0",
				"--check=false",
				"--recover=f",
			},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cfg, mode, err := parseAutomaticSelfUpdateArgs(tc.args, ".")
			if err != nil {
				t.Fatal(err)
			}
			if mode != automaticSelfUpdateWatch {
				t.Fatalf("mode = %v, want watch", mode)
			}
			if cfg.root != wantRoot || cfg.repo != "Example/Repo" {
				t.Fatalf("config = %+v", cfg)
			}
			if cfg.skipVerify != tc.wantSkipVerify || cfg.skipAttestation != tc.wantSkipAttest {
				t.Fatalf("verification flags = (%v, %v), want (%v, %v)",
					cfg.skipVerify, cfg.skipAttestation, tc.wantSkipVerify, tc.wantSkipAttest)
			}
		})
	}
}

func TestParseAutomaticSelfUpdateArgsConsumesAllMainStringFlagValues(t *testing.T) {
	root := t.TempDir()
	cfg, mode, err := parseAutomaticSelfUpdateArgs([]string{
		"--current", "1.2.3",
		"--server-health=http://127.0.0.1:8080/healthz",
		"--worker-health", "http://127.0.0.1:8099/healthz",
		"--heartbeat", `C:\Rig\logs\heartbeat`,
		"--supervisor-interval=10s",
		"--supervisor-task", "KalivSupervisor",
		"--dir", root,
		"--repo", "Example/Repo",
	}, ".")
	if err != nil {
		t.Fatal(err)
	}
	if mode != automaticSelfUpdateWatch {
		t.Fatalf("mode = %v, want watch", mode)
	}
	wantRoot, _ := filepath.Abs(root)
	if cfg.root != wantRoot || cfg.repo != "Example/Repo" {
		t.Fatalf("observer lost alignment with main flags: %+v", cfg)
	}
}

func TestParseAutomaticSelfUpdateArgsDisablesTrueCommandFlagsInAllSpellings(t *testing.T) {
	for _, arg := range []string{"--check", "-check=true", "--recover=1", "-recover=t"} {
		t.Run(arg, func(t *testing.T) {
			_, mode, err := parseAutomaticSelfUpdateArgs([]string{arg}, t.TempDir())
			if err != nil {
				t.Fatal(err)
			}
			if mode != automaticSelfUpdateDisabled {
				t.Fatalf("mode = %v, want disabled", mode)
			}
		})
	}
}

func TestParseAutomaticSelfUpdateArgsRejectsInvalidBoolValues(t *testing.T) {
	for _, arg := range []string{"--skip-attestation=maybe", "-insecure-skip-verify=", "--check=nope"} {
		t.Run(arg, func(t *testing.T) {
			if _, _, err := parseAutomaticSelfUpdateArgs([]string{arg}, t.TempDir()); err == nil {
				t.Fatal("expected invalid boolean value to fail")
			}
		})
	}
}

func TestParseAutomaticSelfUpdateArgsStopsWhereFlagPackageStops(t *testing.T) {
	defaultRoot := t.TempDir()
	ignoredRoot := t.TempDir()
	cfg, mode, err := parseAutomaticSelfUpdateArgs([]string{
		"--current", "1.2.3",
		"positional",
		"--dir", ignoredRoot,
	}, defaultRoot)
	if err != nil {
		t.Fatal(err)
	}
	if mode != automaticSelfUpdateWatch {
		t.Fatalf("mode = %v, want watch", mode)
	}
	wantRoot, _ := filepath.Abs(defaultRoot)
	if cfg.root != wantRoot {
		t.Fatalf("root = %q, want %q; flags after positional argument must be ignored", cfg.root, wantRoot)
	}

	cfg, _, err = parseAutomaticSelfUpdateArgs([]string{"--", "--dir", ignoredRoot}, defaultRoot)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.root != wantRoot {
		t.Fatalf("root = %q, want %q; flags after -- must be ignored", cfg.root, wantRoot)
	}
}

func TestParseAutomaticSelfUpdateArgsUsesFinalCommandBooleanValues(t *testing.T) {
	for _, args := range [][]string{
		{"-check=true", "--check=false"},
		{"--recover", "-recover=0"},
		{"-check", "-check=false", "-recover=true", "-recover=false"},
	} {
		cfg, mode, err := parseAutomaticSelfUpdateArgs(args, t.TempDir())
		if err != nil {
			t.Fatalf("%v: %v", args, err)
		}
		if mode != automaticSelfUpdateWatch {
			t.Fatalf("%v mode = %v, want watch; final false must win", args, mode)
		}
		if cfg.root == "" {
			t.Fatalf("%v returned empty root", args)
		}
	}

	for _, args := range [][]string{
		{"-check=false", "--check=true"},
		{"-recover=0", "--recover"},
	} {
		_, mode, err := parseAutomaticSelfUpdateArgs(args, t.TempDir())
		if err != nil {
			t.Fatalf("%v: %v", args, err)
		}
		if mode != automaticSelfUpdateDisabled {
			t.Fatalf("%v mode = %v, want disabled; final true must win", args, mode)
		}
	}
}

func TestParseAutomaticSelfUpdateArgsRespectsSelectorParsingBoundaries(t *testing.T) {
	defaultRoot := t.TempDir()
	cases := [][]string{
		{"--", "--post-commit-self-update"},
		{"positional", "--post-commit-self-update"},
		{"-current", "--post-commit-self-update"},
	}
	for _, args := range cases {
		_, mode, err := parseAutomaticSelfUpdateArgs(args, defaultRoot)
		if err != nil {
			t.Fatalf("%v: %v", args, err)
		}
		if mode != automaticSelfUpdateWatch {
			t.Fatalf("%v mode = %v, want watch; selector is data outside flag parsing", args, mode)
		}
	}
}

func TestParseAutomaticSelfUpdateArgsUsesFinalSelectorValue(t *testing.T) {
	fingerprint := "-baseline-commit=" + strings.Repeat("ab", 32)
	_, mode, err := parseAutomaticSelfUpdateArgs([]string{
		"--post-commit-self-update=true",
		"-post-commit-self-update=false",
		fingerprint,
	}, t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if mode != automaticSelfUpdateDisabled {
		t.Fatalf("mode = %v, want disabled; final selector false must win", mode)
	}

	_, mode, err = parseAutomaticSelfUpdateArgs([]string{
		"--post-commit-self-update=false",
		"-post-commit-self-update=true",
		fingerprint,
	}, t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if mode != automaticSelfUpdatePostCommit {
		t.Fatalf("mode = %v, want post-commit; final selector true must win", mode)
	}
}
