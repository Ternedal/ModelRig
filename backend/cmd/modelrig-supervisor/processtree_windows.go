//go:build windows

package main

import (
	"fmt"
	"os"
	"syscall"
	"unsafe"
)

// A supervised child is a process TREE, not a process.
//
// The worker ships as a PyInstaller bundle: the exe the supervisor starts is a
// bootstrapper that spawns the real Python process, and it is the CHILD that
// binds port 8099. Killing only the parent -- which is all os.Process.Kill can
// do -- leaves that child holding the port. The supervisor then starts a
// replacement, which dies instantly on
//
//	[Errno 10048] error while attempting to bind on address ('127.0.0.1', 8099)
//
// and the loop repeats every 10 seconds forever. Observed on the rig.
//
// The same shape bit the updater, which matched process names without wildcards
// and stopped nothing at all. Parent is not tree.
//
// A Job Object fixes both halves properly. Every child is assigned to one job,
// created with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, so:
//
//   - killing a child kills its whole tree;
//   - and when the supervisor itself exits -- gracefully, crashing, or killed
//     from outside with Stop-Process -Force -- Windows closes its handles, the
//     job closes, and every remaining descendant dies with it.
//
// The second half is the one a taskkill /T /F in restart() could never cover,
// and it is exactly what stranded two orphaned workers on the rig.
//
// This uses kernel32 directly through syscall rather than golang.org/x/sys:
// the module has no external dependencies, and adding one for four calls would
// be a poor trade.

const (
	_JobObjectExtendedLimitInformation  = 9
	_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
)

type _IO_COUNTERS struct {
	ReadOperationCount  uint64
	WriteOperationCount uint64
	OtherOperationCount uint64
	ReadTransferCount   uint64
	WriteTransferCount  uint64
	OtherTransferCount  uint64
}

type _JOBOBJECT_BASIC_LIMIT_INFORMATION struct {
	PerProcessUserTimeLimit int64
	PerJobUserTimeLimit     int64
	LimitFlags              uint32
	MinimumWorkingSetSize   uintptr
	MaximumWorkingSetSize   uintptr
	ActiveProcessLimit      uint32
	Affinity                uintptr
	PriorityClass           uint32
	SchedulingClass         uint32
}

type _JOBOBJECT_EXTENDED_LIMIT_INFORMATION struct {
	BasicLimitInformation _JOBOBJECT_BASIC_LIMIT_INFORMATION
	IoInfo                _IO_COUNTERS
	ProcessMemoryLimit    uintptr
	JobMemoryLimit        uintptr
	PeakProcessMemoryUsed uintptr
	PeakJobMemoryUsed     uintptr
}

var (
	kernel32                 = syscall.NewLazyDLL("kernel32.dll")
	procCreateJobObjectW     = kernel32.NewProc("CreateJobObjectW")
	procSetInformationJobObj = kernel32.NewProc("SetInformationJobObject")
	procAssignProcessToJobOb = kernel32.NewProc("AssignProcessToJobObject")
	procOpenProcess          = kernel32.NewProc("OpenProcess")
)

// processTree owns every supervised child, so none can outlive the supervisor.
type processTree struct {
	handle syscall.Handle
}

// newProcessTree creates the job children are assigned to.
//
// A nil tree is not an error: the supervisor must keep working on a machine
// where the job cannot be created (an outer job that forbids nesting, a locked
// down policy). Callers treat adoption as best-effort and log the miss, because
// a supervisor that refuses to start is worse than one whose cleanup is weaker.
func newProcessTree() (*processTree, error) {
	h, _, err := procCreateJobObjectW.Call(0, 0)
	if h == 0 {
		return nil, fmt.Errorf("CreateJobObject: %w", err)
	}
	info := _JOBOBJECT_EXTENDED_LIMIT_INFORMATION{}
	info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
	ok, _, err := procSetInformationJobObj.Call(
		h,
		uintptr(_JobObjectExtendedLimitInformation),
		uintptr(unsafe.Pointer(&info)),
		unsafe.Sizeof(info),
	)
	if ok == 0 {
		syscall.CloseHandle(syscall.Handle(h))
		return nil, fmt.Errorf("SetInformationJobObject: %w", err)
	}
	return &processTree{handle: syscall.Handle(h)}, nil
}

// adopt puts a started child, and everything it spawns, into the job.
func (t *processTree) adopt(p *os.Process) error {
	if t == nil || p == nil {
		return nil
	}
	// PROCESS_SET_QUOTA | PROCESS_TERMINATE, which is what assignment needs.
	const access = 0x0100 | 0x0001
	h, _, err := procOpenProcess.Call(access, 0, uintptr(p.Pid))
	if h == 0 {
		return fmt.Errorf("OpenProcess(%d): %w", p.Pid, err)
	}
	defer syscall.CloseHandle(syscall.Handle(h))
	ok, _, err := procAssignProcessToJobOb.Call(uintptr(t.handle), h)
	if ok == 0 {
		return fmt.Errorf("AssignProcessToJobObject(%d): %w", p.Pid, err)
	}
	return nil
}

// Close drops the job, which terminates every process still inside it.
func (t *processTree) Close() error {
	if t == nil || t.handle == 0 {
		return nil
	}
	err := syscall.CloseHandle(t.handle)
	t.handle = 0
	return err
}
