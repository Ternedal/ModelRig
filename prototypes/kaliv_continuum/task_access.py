"""Local prototype task ACL with transactional audit records.

Administrative caller identity is not authenticated here; caller-supplied
administrator IDs are audit labels only. No HTTP mutation endpoint exists.
"""
import sqlite3
import time

class TaskAccess:
    def __init__(self, database):
        self.database = str(database)
        with sqlite3.connect(self.database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS task_acl (
                task_id TEXT NOT NULL, actor_id TEXT NOT NULL,
                permission TEXT NOT NULL CHECK(permission IN ('read','approve')),
                PRIMARY KEY(task_id,actor_id,permission))""")
            db.execute("""CREATE TABLE IF NOT EXISTS task_acl_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL, actor_id TEXT NOT NULL,
                permission TEXT NOT NULL, action TEXT NOT NULL,
                administrator_id TEXT NOT NULL, occurred_at INTEGER NOT NULL)""")

    def grant(self, task_id, actor_id, permission, *, administrator_id="local-prototype"):
        if not all(isinstance(x, str) and x for x in (task_id, actor_id, administrator_id)):
            raise ValueError("missing scope")
        if permission not in ("read", "approve"):
            raise ValueError("unsupported permission")
        with sqlite3.connect(self.database) as db:
            exists = db.execute("SELECT 1 FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if exists is None:
                raise KeyError(task_id)
            changed = db.execute("INSERT OR IGNORE INTO task_acl VALUES (?,?,?)",
                                 (task_id, actor_id, permission))
            if changed.rowcount:
                db.execute("INSERT INTO task_acl_audit(task_id,actor_id,permission,action,administrator_id,occurred_at) VALUES (?,?,?,?,?,?)",
                           (task_id, actor_id, permission, "grant", administrator_id, int(time.time())))

    def revoke(self, task_id, actor_id, permission, *, administrator_id="local-prototype"):
        if not all(isinstance(x, str) and x for x in (task_id, actor_id, administrator_id)):
            raise ValueError("missing scope")
        if permission not in ("read", "approve"):
            raise ValueError("unsupported permission")
        with sqlite3.connect(self.database) as db:
            changed = db.execute("DELETE FROM task_acl WHERE task_id=? AND actor_id=? AND permission=?",
                                 (task_id, actor_id, permission))
            if changed.rowcount:
                db.execute("INSERT INTO task_acl_audit(task_id,actor_id,permission,action,administrator_id,occurred_at) VALUES (?,?,?,?,?,?)",
                           (task_id, actor_id, permission, "revoke", administrator_id, int(time.time())))

    def require(self, task_id, actor_id, permission):
        if not all(isinstance(x, str) and x for x in (task_id, actor_id)):
            raise PermissionError("task access denied")
        if permission not in ("read", "approve"):
            raise PermissionError("unsupported permission")
        with sqlite3.connect(self.database) as db:
            row = db.execute("""SELECT 1 FROM task_acl WHERE task_id=?
                AND actor_id=? AND permission=?""",
                (task_id, actor_id, permission)).fetchone()
        if row is None:
            raise PermissionError("task access denied")

    def audit(self, task_id):
        with sqlite3.connect(self.database) as db:
            return db.execute("""SELECT actor_id,permission,action,administrator_id,occurred_at
                FROM task_acl_audit WHERE task_id=? ORDER BY id""", (task_id,)).fetchall()
