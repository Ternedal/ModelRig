"""SQLite-backed prototype task store. Not wired into production services."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from continuum_state import Task, State, transition

class TaskStore:
    def __init__(self, path):
        self.path = str(Path(path))
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                revision INTEGER NOT NULL,
                approved INTEGER NOT NULL,
                requires_approval INTEGER NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS task_events (
                task_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                state TEXT NOT NULL,
                PRIMARY KEY(task_id, revision)
            )""")

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
        if not task_id or not isinstance(task_id, str):
            raise ValueError("task_id required")
        task = Task(task_id=task_id, requires_approval=requires_approval)
        with self._db() as db:
            db.execute("INSERT INTO tasks VALUES (?,?,?,?,?)",
                       (task.task_id, task.state.value, 0, 0, int(requires_approval)))
            db.execute("INSERT INTO task_events VALUES (?,?,?)",
                       (task_id, 0, task.state.value))
        return task

    def get(self, task_id):
        with self._db() as db:
            row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return Task(row[0], State(row[1]), row[2], bool(row[3]), bool(row[4]))

    def move(self, task_id, target, expected_revision, approval_token=None):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            current = Task(row[0], State(row[1]), row[2], bool(row[3]), bool(row[4]))
            updated = transition(current, target, expected_revision=expected_revision,
                                 approval_token=approval_token)
            db.execute("UPDATE tasks SET state=?,revision=?,approved=? WHERE task_id=?",
                       (updated.state.value, updated.revision, int(updated.approved), task_id))
            db.execute("INSERT INTO task_events VALUES (?,?,?)",
                       (task_id, updated.revision, updated.state.value))
        return updated

    def events(self, task_id):
        with self._db() as db:
            return db.execute("SELECT revision,state FROM task_events WHERE task_id=? ORDER BY revision",
                              (task_id,)).fetchall()
