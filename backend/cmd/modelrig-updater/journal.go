package main

// The transaction journal makes an update a recoverable whole-set operation
// instead of three independent file swaps. It is a small JSON file in the
// ModelRig root, written BEFORE the first mutation and updated at each state
// change; its PRESENCE means an update did not commit. The recovery pass at
// startup reads it and restores every target from that attempt's backup dir --
// closing the gap where a crash between targets left the rig on mixed versions
// (server new, worker old) with nothing at next start knowing what to undo.
//
// States: prepared -> backed_up -> swapping -> verifying -> (committed:
// journal archived) | rolling_back -> rolled_back (archived) | manual_recovery
// (journal KEPT so the operator and the next run can see what happened).
//
// Writes go via tmp + rename (Windows-safe: old file removed first). The brief
// window where only the tmp exists is covered by readJournal falling back to
// the .tmp -- the journal can never silently vanish mid-transaction.

import (
	"encoding/json"
	"fmt"
	"os"
	"time"
)

type txData struct {
	ID        string   `json:"id"`
	From      string   `json:"from"`
	To        string   `json:"to"`
	BackupDir string   `json:"backup_dir"` // absolute
	State     string   `json:"state"`
	Swapped   []string `json:"swapped"` // asset names already swapped in
	UpdatedAt string   `json:"updated_at"`
	// Revision increments on every write. After a crash both the main file and
	// the .tmp can exist with DIFFERENT states (the tmp is written first); the
	// higher revision is the truth. UpdatedAt can't decide this -- RFC3339 has
	// second resolution and several writes can share a second.
	Revision int `json:"revision"`
}

type txJournal struct {
	path string
	data txData
}

// newJournal claims the journal file and records state "prepared". Fails if a
// journal already exists -- an incomplete prior transaction must be recovered
// (or explicitly resolved) before a new one may start.
func newJournal(path, from, to, backupDir string) (*txJournal, error) {
	if fileExists(path) || fileExists(path+".tmp") {
		return nil, fmt.Errorf("an update transaction is already recorded at %s -- recover it first", path)
	}
	j := &txJournal{path: path, data: txData{
		ID: time.Now().UTC().Format("20060102T150405Z"), From: from, To: to,
		BackupDir: backupDir, State: "prepared",
	}}
	return j, j.write()
}

func (j *txJournal) setState(s string) error {
	if j == nil {
		return nil
	}
	j.data.State = s
	return j.write()
}

func (j *txJournal) addSwapped(asset string) error {
	if j == nil {
		return nil
	}
	j.data.Swapped = append(j.data.Swapped, asset)
	if j.data.State != "swapping" {
		j.data.State = "swapping"
	}
	return j.write()
}

// archive marks the transaction finished (committed / rolled_back) and renames
// the journal to .last, so no journal file = no pending transaction, while the
// evidence of the last one is kept for forensics.
func (j *txJournal) archive(finalState string) error {
	if j == nil {
		return nil
	}
	j.data.State = finalState
	if err := j.write(); err != nil {
		return err
	}
	_ = os.Remove(j.path + ".last")
	return os.Rename(j.path, j.path+".last")
}

func (j *txJournal) write() error {
	j.data.Revision++
	j.data.UpdatedAt = time.Now().UTC().Format(time.RFC3339)
	b, err := json.MarshalIndent(j.data, "", "  ")
	if err != nil {
		return err
	}
	// The journal is the safety evidence after a crash, so the tmp is fsynced
	// before the rename -- a power loss right after write() must still find the
	// content on disk. (Directory-metadata flush isn't portable; the .tmp
	// read-fallback covers the rename window.)
	tmp := j.path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	if _, err := f.Write(b); err != nil {
		f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	_ = os.Remove(j.path) // Windows rename won't overwrite
	return os.Rename(tmp, j.path)
}

// readOne parses a single journal file. (nil, nil) ONLY when the file does not
// exist; an existing-but-unreadable file is an error -- unreadable transaction
// evidence must never be treated as "no journal".
func readOne(p string) (*txData, error) {
	b, err := os.ReadFile(p)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("journal %s cannot be read: %w", p, err)
	}
	var d txData
	if err := json.Unmarshal(b, &d); err != nil {
		return nil, fmt.Errorf("journal %s is unreadable: %w", p, err)
	}
	return &d, nil
}

// readJournal returns the current transaction, or nil if none exists. BOTH the
// main file and the .tmp are considered: write() goes tmp -> fsync -> remove
// main -> rename, so a crash can leave only the tmp, or BOTH -- and then the
// tmp carries the NEWER state (e.g. main=verifying, tmp=committed; preferring
// main there would roll back a verified healthy update). The monotonic
// Revision decides. Any ambiguity -- an unreadable file, a transaction-ID
// mismatch, equal revisions with different states -- fails closed.
func readJournal(path string) (*txData, error) {
	mainD, err := readOne(path)
	if err != nil {
		return nil, err
	}
	tmpD, err := readOne(path + ".tmp")
	if err != nil {
		return nil, err
	}
	switch {
	case mainD == nil && tmpD == nil:
		return nil, nil
	case mainD == nil:
		return tmpD, nil
	case tmpD == nil:
		return mainD, nil
	}
	if mainD.ID != tmpD.ID {
		return nil, fmt.Errorf("journal conflict at %s: main and .tmp describe different transactions (%s vs %s) -- resolve by hand", path, mainD.ID, tmpD.ID)
	}
	if tmpD.Revision > mainD.Revision {
		return tmpD, nil
	}
	if tmpD.Revision < mainD.Revision {
		return mainD, nil
	}
	if tmpD.State != mainD.State {
		return nil, fmt.Errorf("journal conflict at %s: equal revisions with different states (%s vs %s) -- resolve by hand", path, mainD.State, tmpD.State)
	}
	return mainD, nil
}

// recoverFromJournal undoes an uncommitted transaction as a WHOLE SET: every
// target with a backup in the journal's backup dir is restored to its
// pre-transaction binary, regardless of how far the swap got. Live-missing
// targets are handled (a .old is used first; otherwise the backup is copied in
// fresh), and stray .old/.new are cleaned only after a successful restore. On
// success the journal is archived as rolled_back. Any failure marks the journal
// manual_recovery and returns an error -- the caller must fail closed.
func recoverFromJournal(jPath string, targets []target) error {
	d, err := readJournal(jPath)
	if err != nil {
		return err
	}
	if d == nil {
		return nil
	}
	j := &txJournal{path: jPath, data: *d}

	// State-aware: what a leftover journal means depends on how far it got.
	switch d.State {
	case "committed", "rolled_back":
		// The transaction FINISHED; only the forensic rename to .last failed.
		// Never touch binaries here -- rolling back a healthy committed update
		// because an archive rename failed would undo a verified release.
		fmt.Printf("updater: journal %s is terminal (%s) -- finishing the archive, binaries untouched\n", d.ID, d.State)
		if err := j.archive(d.State); err != nil {
			return fmt.Errorf("could not archive terminal journal %s: %w -- remove it by hand", jPath, err)
		}
		_ = os.Remove(jPath + ".tmp")
		return nil
	case "prepared":
		// Swaps begin only AFTER the journal records backed_up, so prepared
		// means zero live mutations happened. Archive; restore nothing.
		fmt.Printf("updater: journal %s crashed in prepared (nothing was swapped) -- archiving, binaries untouched\n", d.ID)
		if err := j.archive("rolled_back"); err != nil {
			return fmt.Errorf("could not archive journal %s: %w", jPath, err)
		}
		_ = os.Remove(jPath + ".tmp")
		return nil
	}

	// backed_up / swapping / verifying / rolling_back / manual_recovery: phase 1
	// completed, so EVERY target must have a backup. Validate before touching
	// anything -- restoring only some targets and archiving would bless a
	// mixed-version set as rolled_back. Fail closed instead.
	for _, t := range targets {
		if !fileExists(fmt.Sprintf("%s%c%s", d.BackupDir, os.PathSeparator, t.asset)) {
			_ = j.setState("manual_recovery")
			return fmt.Errorf("whole-set rollback impossible: backup for %s is missing from %s -- journal kept (manual_recovery); restore by hand", t.asset, d.BackupDir)
		}
	}
	fmt.Printf("updater: found uncommitted update %s (%s -> %s, state %s) -- rolling the whole set back\n",
		d.ID, d.From, d.To, d.State)

	restored := 0
	for _, t := range targets {
		bak := fmt.Sprintf("%s%c%s", d.BackupDir, os.PathSeparator, t.asset)
		if !fileExists(t.live) {
			_ = recoverTarget(t.live) // may bring a .old back
		}
		if fileExists(t.live) {
			err = atomicSwapInto(bak, t.live)
		} else {
			err = copyFile(bak, t.live) // nothing to preserve; create fresh
		}
		if err != nil {
			_ = j.setState("manual_recovery")
			return fmt.Errorf("whole-set rollback of %s failed (%v) -- journal kept at %s, backups at %s; restore by hand", t.asset, err, jPath, d.BackupDir)
		}
		_ = os.Remove(t.live + ".old")
		_ = os.Remove(t.live + ".new")
		restored++
	}
	if err := j.archive("rolled_back"); err != nil {
		return fmt.Errorf("restored %d target(s) but could not archive the journal: %w", restored, err)
	}
	_ = os.Remove(jPath + ".tmp")
	fmt.Printf("updater: whole-set rollback complete (%d target(s) restored to %s)\n", restored, d.From)
	return nil
}
