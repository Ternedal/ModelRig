package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"
)

// The supervisor starts the server and worker directly, so IT -- not a launcher
// script -- must supply the environment they need. The one that actually matters
// is MODELRIG_HOST=0.0.0.0: the server defaults to loopback (a deliberate secure
// default), which the phone cannot reach, so an appliance that never sets it is
// broken for remote access even though it "runs". Rather than bake policy into
// the binary, the supervisor reads a small KEY=VALUE file (deploy/modelrig.env)
// and passes those vars to its children.

// stripInlineComment removes a trailing " # comment" and one layer of surrounding
// quotes. A quoted value is taken as the quoted span (a '#' inside quotes is
// kept); an unquoted value is cut at the first whitespace-preceded '#'. This
// matters because the shipped env example carries an inline comment on almost
// every line -- a parser that kept them would feed "0.0.0.0   # bind..." to the
// server as its bind host, and the appliance would restart-loop.
func stripInlineComment(v string) string {
	if len(v) >= 2 && (v[0] == '"' || v[0] == '\'') {
		if end := strings.IndexByte(v[1:], v[0]); end >= 0 {
			return v[1 : 1+end]
		}
	}
	for i := 1; i < len(v); i++ {
		if v[i] == '#' && (v[i-1] == ' ' || v[i-1] == '\t') {
			return strings.TrimRight(v[:i], " \t")
		}
	}
	return v
}

// loadEnvFile parses a KEY=VALUE file (# comments and blank lines ignored,
// surrounding whitespace and a single layer of quotes trimmed from the value).
// A missing file is not an error -- returns an empty slice -- so the flag can
// default to a path that may or may not exist.
func loadEnvFile(path string) ([]string, error) {
	if path == "" {
		return nil, nil
	}
	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	defer f.Close()

	var out []string
	sc := bufio.NewScanner(f)
	line := 0
	for sc.Scan() {
		line++
		t := strings.TrimSpace(sc.Text())
		if t == "" || strings.HasPrefix(t, "#") {
			continue
		}
		k, v, ok := strings.Cut(t, "=")
		if !ok {
			return nil, fmt.Errorf("%s:%d: not KEY=VALUE: %q", path, line, t)
		}
		k = strings.TrimSpace(k)
		if k == "" {
			return nil, fmt.Errorf("%s:%d: empty key", path, line)
		}
		out = append(out, k+"="+stripInlineComment(strings.TrimSpace(v)))
	}
	return out, sc.Err()
}
