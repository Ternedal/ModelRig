//go:build !windows

package main

import "os"

// The supervisor ships only for Windows, but `go build ./...` and the test
// suite run on Linux in CI. These no-ops keep the shared code single-branch:
// the caller adopts children unconditionally and never asks which platform it
// is on. See processtree_windows.go for what this actually does and why.

type processTree struct{}

func newProcessTree() (*processTree, error) { return &processTree{}, nil }

func (t *processTree) adopt(p *os.Process) error { return nil }

func (t *processTree) Close() error { return nil }
