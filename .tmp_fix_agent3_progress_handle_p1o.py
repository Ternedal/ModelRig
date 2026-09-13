from pathlib import Path

path = Path("worker/app/agent3/core.py")
text = path.read_text(encoding="utf-8")

old = '''        # Execution-start evidence deliberately lives in a separate SQLite file.\n        # A stale/partially-restored agent_runs payload must never be able to roll\n        # this watermark backwards and make a side effect look PENDING again.\n        progress_path = ":memory:" if path == ":memory:" else f"{path}.execution-progress"\n        self._progress_conn = sqlite3.connect(progress_path, check_same_thread=False)\n        self._progress_conn.execute(\n            "CREATE TABLE IF NOT EXISTS agent_execution_starts ("\n            "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "\n            "started_at REAL NOT NULL, "\n            "PRIMARY KEY(run_id,step_index,step_sha256))"\n        )\n        self._progress_conn.commit()\n'''
new = '''        # Execution-start evidence deliberately lives in a separate SQLite file.\n        # A stale/partially-restored agent_runs payload must never be able to roll\n        # this watermark backwards and make a side effect look PENDING again.\n        # File-backed stores use short-lived sidecar connections so Windows never\n        # retains a handle that prevents normal temp-dir/backup lifecycle cleanup.\n        self._progress_path = None if path == ":memory:" else f"{path}.execution-progress"\n        progress_conn = self._conn if self._progress_path is None else sqlite3.connect(self._progress_path)\n        try:\n            progress_conn.execute(\n                "CREATE TABLE IF NOT EXISTS agent_execution_starts ("\n                "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "\n                "started_at REAL NOT NULL, "\n                "PRIMARY KEY(run_id,step_index,step_sha256))"\n            )\n            progress_conn.commit()\n        finally:\n            if progress_conn is not self._conn:\n                progress_conn.close()\n'''
if old not in text:
    raise SystemExit("missing progress init anchor")
text = text.replace(old, new, 1)

old = '''        with self._lock:\n            try:\n                self._progress_conn.execute(\n                    "INSERT OR IGNORE INTO agent_execution_starts("\n                    "run_id,step_index,step_sha256,started_at) VALUES(?,?,?,?)",\n                    (run.id, run.current_step, digest, time.time()),\n                )\n                self._progress_conn.commit()\n            except Exception:\n                self._progress_conn.rollback()\n                raise\n'''
new = '''        with self._lock:\n            progress_conn = self._conn if self._progress_path is None else sqlite3.connect(self._progress_path)\n            try:\n                progress_conn.execute(\n                    "INSERT OR IGNORE INTO agent_execution_starts("\n                    "run_id,step_index,step_sha256,started_at) VALUES(?,?,?,?)",\n                    (run.id, run.current_step, digest, time.time()),\n                )\n                progress_conn.commit()\n            except Exception:\n                progress_conn.rollback()\n                raise\n            finally:\n                if progress_conn is not self._conn:\n                    progress_conn.close()\n'''
if old not in text:
    raise SystemExit("missing progress write anchor")
text = text.replace(old, new, 1)

old = '''        with self._lock:\n            rows = self._progress_conn.execute(\n                "SELECT step_index,step_sha256 FROM agent_execution_starts "\n                "WHERE run_id=? ORDER BY step_index ASC",\n                (run.id,),\n            ).fetchall()\n'''
new = '''        with self._lock:\n            progress_conn = self._conn if self._progress_path is None else sqlite3.connect(self._progress_path)\n            try:\n                rows = progress_conn.execute(\n                    "SELECT step_index,step_sha256 FROM agent_execution_starts "\n                    "WHERE run_id=? ORDER BY step_index ASC",\n                    (run.id,),\n                ).fetchall()\n            finally:\n                if progress_conn is not self._conn:\n                    progress_conn.close()\n'''
if old not in text:
    raise SystemExit("missing progress read anchor")
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("applied short-lived execution-progress sidecar connections")
