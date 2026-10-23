"""Fail-closed, no-side-effect outbox worker prototype.

The caller supplies an explicit capability allowlist. Empty by default.
No external tools are dispatched; no production runtime wiring.
"""
import sqlite3
import time
from dataclasses import dataclass

@dataclass(frozen=True)
class DryRunReceipt:
    operation_id: str
    task_id: str
    capability: str
    status: str

class DryRunWorker:
    def __init__(self, database, *, allowed_capabilities=()):
        self.database = str(database)
        self.allowed_capabilities = frozenset(allowed_capabilities)
        if any(not isinstance(x, str) or not x for x in self.allowed_capabilities):
            raise ValueError("invalid capability allowlist")
        with sqlite3.connect(self.database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS dry_run_receipts (
                operation_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                capability TEXT NOT NULL,
                created_at INTEGER NOT NULL)""")

    def run_once(self):
        """Only simulate a reserved command with an explicitly allowed capability."""
        with sqlite3.connect(self.database, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT operation_id,task_id,capability
                FROM command_outbox WHERE status='reserved'
                ORDER BY rowid LIMIT 1""").fetchone()
            if row is None:
                return None
            operation_id, task_id, capability = row
            if capability not in self.allowed_capabilities:
                raise PermissionError("worker capability not allowed")
            db.execute("""INSERT INTO dry_run_receipts VALUES (?,?,?,?)""",
                       (operation_id, task_id, capability, int(time.time())))
            changed = db.execute("""UPDATE command_outbox SET status='simulated'
                WHERE operation_id=? AND status='reserved'""", (operation_id,))
            if changed.rowcount != 1:
                raise RuntimeError("lost reservation")
        return DryRunReceipt(operation_id, task_id, capability, "simulated")
