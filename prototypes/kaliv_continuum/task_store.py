"""SQLite-backed isolated Continuum prototype; no production runtime wiring."""
import hashlib
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from continuum_state import Task, State, transition

class TaskStore:
    def __init__(self, path):
        self.path = str(Path(path))
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY, state TEXT NOT NULL,
                revision INTEGER NOT NULL, approved INTEGER NOT NULL,
                requires_approval INTEGER NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS task_events (
                task_id TEXT NOT NULL, revision INTEGER NOT NULL,
                state TEXT NOT NULL, PRIMARY KEY(task_id, revision))""")
            db.execute("""CREATE TABLE IF NOT EXISTS continuum_approvals (
                digest TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                actor_id TEXT NOT NULL, capability TEXT NOT NULL,
                revision INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                consumed_at INTEGER)""")
            db.execute("""CREATE TABLE IF NOT EXISTS command_outbox (
                operation_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                revision INTEGER NOT NULL, capability TEXT NOT NULL,
                actor_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'reserved')""")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA busy_timeout=5000")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, task_id, requires_approval=True):
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task_id required")
        task = Task(task_id=task_id, requires_approval=requires_approval)
        with self._db() as db:
            db.execute("INSERT INTO tasks VALUES (?,?,?,?,?)",
                       (task.task_id, task.state.value, 0, 0, int(requires_approval)))
            db.execute("INSERT INTO task_events VALUES (?,?,?)", (task_id, 0, task.state.value))
        return task

    def _read(self, db, task_id):
        row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return Task(row[0], State(row[1]), row[2], bool(row[3]), bool(row[4]))

    def get(self, task_id):
        with self._db() as db:
            return self._read(db, task_id)

    def move(self, task_id, target, expected_revision, approval_token=None):
        """Non-executing transitions only; executing always requires reserve_execution."""
        if target == State.EXECUTING or approval_token is not None:
            raise PermissionError("use reserve_execution for authorized execution")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = transition(self._read(db, task_id), target,
                                 expected_revision=expected_revision)
            self._save(db, updated)
        return updated

    def _save(self, db, task):
        db.execute("UPDATE tasks SET state=?,revision=?,approved=? WHERE task_id=?",
                   (task.state.value, task.revision, int(task.approved), task.task_id))
        db.execute("INSERT INTO task_events VALUES (?,?,?)",
                   (task.task_id, task.revision, task.state.value))

    def reserve_execution(self, *, task_id, expected_revision, actor_id,
                          capability, token, operation_id):
        """Atomically consume an existing grant, move task and reserve command.

        Grant issuance must be authorized by a separate trusted UI and policy.
        No command executor is connected in this prototype.
        """
        if not all(isinstance(x, str) and x for x in (actor_id, capability, token, operation_id)):
            raise ValueError("missing execution scope")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self._read(db, task_id)
            if task.state != State.AWAITING_APPROVAL or task.revision != expected_revision:
                raise PermissionError("task not at approved checkpoint")
            now = int(time.time())
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            row = db.execute("""UPDATE continuum_approvals SET consumed_at=?
                WHERE digest=? AND task_id=? AND actor_id=? AND capability=?
                  AND revision=? AND expires_at>? AND consumed_at IS NULL""",
                (now, digest, task_id, actor_id, capability, expected_revision, now))
            if row.rowcount != 1:
                raise PermissionError("valid scoped approval required")
            updated = transition(task, State.EXECUTING,
                                 expected_revision=expected_revision, verified_approval=True)
            db.execute("INSERT INTO command_outbox(operation_id,task_id,revision,capability,actor_id) VALUES (?,?,?,?,?)",
                       (operation_id, task_id, updated.revision, capability, actor_id))
            self._save(db, updated)
        return updated

    def events(self, task_id):
        with self._db() as db:
            return db.execute("SELECT revision,state FROM task_events WHERE task_id=? ORDER BY revision",
                              (task_id,)).fetchall()
