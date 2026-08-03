//go:build windows

// Tiny native fixture used only by the Windows restricted-token CI gate.
package main

import (
	"encoding/json"
	"os"
	"syscall"
	"unsafe"
)

const tokenQuery = 0x0008

type result struct {
	Restricted   bool   `json:"restricted"`
	InsideRead   bool   `json:"inside_read"`
	OutsideRead  bool   `json:"outside_read"`
	InsideWrite  bool   `json:"inside_write"`
	OutsideWrite bool   `json:"outside_write"`
	Error        string `json:"error,omitempty"`
}

func tokenRestricted() (bool, error) {
	kernel32 := syscall.NewLazyDLL("kernel32.dll")
	advapi32 := syscall.NewLazyDLL("advapi32.dll")
	getCurrentProcess := kernel32.NewProc("GetCurrentProcess")
	openProcessToken := advapi32.NewProc("OpenProcessToken")
	isTokenRestricted := advapi32.NewProc("IsTokenRestricted")
	closeHandle := kernel32.NewProc("CloseHandle")

	process, _, _ := getCurrentProcess.Call()
	var token syscall.Handle
	ok, _, err := openProcessToken.Call(
		process,
		tokenQuery,
		uintptr(unsafe.Pointer(&token)),
	)
	if ok == 0 {
		return false, err
	}
	defer closeHandle.Call(uintptr(token))
	restricted, _, _ := isTokenRestricted.Call(uintptr(token))
	return restricted != 0, nil
}

func canRead(path string) bool {
	_, err := os.ReadFile(path)
	return err == nil
}

func canWrite(path string) bool {
	return os.WriteFile(path, []byte("restricted-write-ok"), 0o600) == nil
}

func main() {
	if len(os.Args) != 6 {
		os.Exit(2)
	}
	restricted, err := tokenRestricted()
	out := result{
		Restricted:   restricted,
		InsideRead:   canRead(os.Args[1]),
		OutsideRead:  canRead(os.Args[2]),
		InsideWrite:  canWrite(os.Args[3]),
		OutsideWrite: canWrite(os.Args[4]),
	}
	if err != nil {
		out.Error = err.Error()
	}
	payload, marshalErr := json.Marshal(out)
	if marshalErr != nil || os.WriteFile(os.Args[5], payload, 0o600) != nil {
		os.Exit(3)
	}
}
