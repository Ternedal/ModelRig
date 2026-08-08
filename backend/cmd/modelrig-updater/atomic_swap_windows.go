//go:build windows

package main

import (
	"fmt"
	"os"
	"strings"
	"syscall"
	"unsafe"
)

var (
	kernel32ReplaceFile = syscall.NewLazyDLL("kernel32.dll").NewProc("ReplaceFileW")
	replaceFileFn       = replaceFileWindows
)

// Install the Windows adapter behind the existing renameFn seam. The portable
// atomicSwapInto transaction remains the single caller and its fault-injection
// tests keep working, but the production live-file transition is now one
// ReplaceFileW call rather than a live->old rename followed by new->live.
func init() {
	renameFn = windowsAtomicRename
}

// windowsAtomicRename implements the three rename shapes atomicSwapInto uses:
//
//   live -> live.old   make a durable rollback copy while live stays present
//   live.new -> live   atomically replace the live name with ReplaceFileW
//   live.old -> live   atomically restore the rollback copy after a failure
//
// Other rename operations retain ordinary os.Rename semantics.
func windowsAtomicRename(from, to string) error {
	switch {
	case to == from+".old":
		// atomicSwapInto has already removed a stale .old. Copy instead of
		// renaming so there is never a point where the live name is absent.
		return copyFile(from, to)
	case strings.HasSuffix(from, ".new") && from == to+".new":
		return replaceFileFn(to, from)
	case strings.HasSuffix(from, ".old") && from == to+".old":
		if fileExists(to) {
			// ReplaceFileW can fail before it mutates either path (for example
			// because another process still has a sharing-incompatible handle).
			// In that state the live file is already the original we are trying
			// to restore. Prove byte identity against .old and accept the rollback
			// instead of repeating the same failing native replacement and falsely
			// escalating to manual_recovery.
			if sameFileContents(to, from) {
				_ = os.Remove(from)
				return nil
			}
			return replaceFileFn(to, from)
		}
		// A prior failure may genuinely have left live absent. The old copy
		// is then the only safe recovery source and a simple rename restores it.
		return os.Rename(from, to)
	default:
		return os.Rename(from, to)
	}
}

func sameFileContents(a, b string) bool {
	aDigest, err := fileSHA256(a)
	if err != nil {
		return false
	}
	bDigest, err := fileSHA256(b)
	if err != nil {
		return false
	}
	return strings.EqualFold(aDigest, bDigest)
}

// replaceFileWindows calls ReplaceFileW with no backup path. atomicSwapInto has
// already made live.old before this point, and the staged replacement is on the
// same volume beside live. ReplaceFileW preserves the live file's metadata and
// changes the live name in one OS operation.
func replaceFileWindows(replaced, replacement string) error {
	replacedPtr, err := syscall.UTF16PtrFromString(replaced)
	if err != nil {
		return fmt.Errorf("encode replaced path %q: %w", replaced, err)
	}
	replacementPtr, err := syscall.UTF16PtrFromString(replacement)
	if err != nil {
		return fmt.Errorf("encode replacement path %q: %w", replacement, err)
	}

	result, _, callErr := kernel32ReplaceFile.Call(
		uintptr(unsafe.Pointer(replacedPtr)),
		uintptr(unsafe.Pointer(replacementPtr)),
		0, // backup path: atomicSwapInto owns the explicit .old copy
		0, // flags: REPLACEFILE_WRITE_THROUGH is documented as unsupported
		0,
		0,
	)
	if result != 0 {
		return nil
	}
	if callErr != syscall.Errno(0) {
		return callErr
	}
	return syscall.EINVAL
}
