"""Read-only, single-transaction snapshot of a Continuum task.

A single SQLite read transaction ensures task, events and command records
describe one database point in time, even while another worker writes.
"""
import sqlite3

def snapshot(database, task_id):
    with sqlite3.connect(str(database), timeout=5) as db:
        db.execute("BEGIN")
        task = db.execute("""SELECT task_id,state,revision,requires_approval
            FROM tasks WHERE task_id=?""", (task_id,)).fetchone()
        if task is None:
            raise KeyError(task_id)
        events = db.execute("""SELECT revision,state FROM task_events
            WHERE task_id=? ORDER BY revision""", (task_id,)).fetchall()
        commands = db.execute("""SELECT operation_id,revision,capability,status
            FROM command_outbox WHERE task_id=? ORDER BY revision,operation_id""",
            (task_id,)).fetchall()
    return {
        "task_id": task[0],
        "state": task[1],
        "revision": task[2],
        "requires_approval": bool(task[3]),
        "events": [{"revision": revision, "state": state}
                   for revision, state in events],
        "commands": [{"operation_id": operation_id, "revision": revision,
                      "capability": capability, "status": status}
                     for operation_id, revision, capability, status in commands],
    }
