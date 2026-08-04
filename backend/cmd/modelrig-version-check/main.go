package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

var semverPattern = regexp.MustCompile(`^\d+\.\d+\.\d+$`)

type versionSite struct {
	path    string
	pattern *regexp.Regexp
}

var versionSites = []versionSite{
	{"worker/app/main.py", regexp.MustCompile(`VERSION = "(\d+\.\d+\.\d+)"`)},
	{"backend/internal/config/config.go", regexp.MustCompile(`const Version = "(\d+\.\d+\.\d+)"`)},
	{"android/app/build.gradle.kts", regexp.MustCompile(`versionName = "(\d+\.\d+\.\d+)"`)},
	{"desktop/composeApp/build.gradle.kts", regexp.MustCompile(`packageVersion = "(\d+\.\d+\.\d+)"`)},
}

func readText(root, relative string) (string, error) {
	payload, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(relative)))
	if err != nil {
		return "", err
	}
	return string(payload), nil
}

func run(output io.Writer, args []string, root string) int {
	if len(args) != 0 {
		fmt.Fprintln(output, "usage: modelrig-version-check")
		return 2
	}

	versionText, err := readText(root, "VERSION")
	if err != nil {
		fmt.Fprintf(output, "FAIL  VERSION: %v\n", err)
		return 1
	}
	want := strings.TrimSpace(versionText)
	if !semverPattern.MatchString(want) {
		fmt.Fprintf(output, "FAIL  VERSION: not semver: %q\n", want)
		return 1
	}

	ok := true
	for _, site := range versionSites {
		text, readErr := readText(root, site.path)
		if readErr != nil {
			fmt.Fprintf(output, "FAIL  %s: %v\n", site.path, readErr)
			ok = false
			continue
		}
		match := site.pattern.FindStringSubmatch(text)
		if len(match) != 2 {
			fmt.Fprintf(output, "FAIL  %s: version pattern not found\n", site.path)
			ok = false
			continue
		}
		if match[1] != want {
			fmt.Fprintf(output, "FAIL  %s: %s != VERSION %s\n", site.path, match[1], want)
			ok = false
			continue
		}
		fmt.Fprintf(output, "ok    %s: %s\n", site.path, match[1])
	}
	if !ok {
		fmt.Fprintf(output, "\nVERSION drift (source of truth: VERSION = %s). Fix: python scripts/version_tool.py sync\n", want)
		return 1
	}
	fmt.Fprintf(output, "\nall sites match VERSION %s\n", want)
	return 0
}

func main() {
	os.Exit(run(os.Stdout, os.Args[1:], "."))
}
