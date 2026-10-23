"""Read-only command outbox inspection; no token issuance or execution."""
import sqlite3
from dataclasses import dataclass

@dataclass(frozen=True)
class CommandStatus:
    operation_id: str
    task_id: str
    revision: int
    capability: str
    actor_id: str
    status: str

class OutboxInspector:
    def __init__(self, database):
        self.database = str(database)

    def get(self, operation_id):
        with sqlite3.connect(self.database) as db:
            row = db.execute("""SELECT operation_id,task_id,revision,capability,actor_id,status
                FROM command_outbox WHERE operation_id=?""", (operation_id,)).fetchone()
        if row is None:
            raise KeyError(operation_id)
        return CommandStatus(*row)

    def list_for_task(self, task_id):
        with sqlite3.connect(self.database) as db:
            rows = db.execute("""SELECT operation_id,task_id,revision,capability,actor_id,status
                FROM command_outbox WHERE task_id=? ORDER BY revision,operation_id""",
                (task_id,)).fetchall()
        return tuple(CommandStatus(*row) for row in rows)
