"""Read-only approval audit inspection without exposing grant digests or tokens."""
import sqlite3

class ApprovalAuditInspector:
    def __init__(self, database):
        self.database = str(database)

    def list_for_task(self, task_id):
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task_id required")
        with sqlite3.connect(self.database) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("""SELECT a.id,a.approver_id,a.executor_id,
                a.capability,a.revision,a.issued_at,g.expires_at,g.consumed_at
                FROM approval_issue_audit a
                JOIN continuum_approvals g ON g.digest=a.grant_digest
                WHERE a.task_id=? ORDER BY a.id""", (task_id,)).fetchall()
        return [{"audit_id": row["id"], "approver_id": row["approver_id"],
                 "executor_id": row["executor_id"], "capability": row["capability"],
                 "revision": row["revision"], "issued_at": row["issued_at"],
                 "expires_at": row["expires_at"], "consumed_at": row["consumed_at"]}
                for row in rows]
