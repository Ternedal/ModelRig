"""Read-only per-task authorization policy prototype.

This is a local policy model, not an authenticated identity provider.
Callers must derive actor identity from a trusted gateway, never from
untrusted request parameters.
"""
import sqlite3

class TaskAccess:
    def __init__(self, database):
        self.database = str(database)
        with sqlite3.connect(self.database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS task_acl (
                task_id TEXT NOT NULL, actor_id TEXT NOT NULL,
                permission TEXT NOT NULL CHECK(permission IN ('read','approve')),
                PRIMARY KEY(task_id,actor_id,permission))""")

    def grant(self, task_id, actor_id, permission):
        if not all(isinstance(x, str) and x for x in (task_id, actor_id)):
            raise ValueError("missing scope")
        if permission not in ("read", "approve"):
            raise ValueError("unsupported permission")
        with sqlite3.connect(self.database) as db:
            exists = db.execute("SELECT 1 FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if exists is None:
                raise KeyError(task_id)
            db.execute("INSERT OR IGNORE INTO task_acl VALUES (?,?,?)",
                       (task_id, actor_id, permission))

    def revoke(self, task_id, actor_id, permission):
        with sqlite3.connect(self.database) as db:
            db.execute("DELETE FROM task_acl WHERE task_id=? AND actor_id=? AND permission=?",
                       (task_id, actor_id, permission))

    def require(self, task_id, actor_id, permission):
        if permission not in ("read", "approve"):
            raise PermissionError("unsupported permission")
        with sqlite3.connect(self.database) as db:
            row = db.execute("""SELECT 1 FROM task_acl WHERE task_id=?
                AND actor_id=? AND permission=?""",
                (task_id, actor_id, permission)).fetchone()
        if row is None:
            raise PermissionError("task access denied")
