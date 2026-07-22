#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:180]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


MEMORY = "worker/app/agent3/memory.py"
replace_once(
    MEMORY,
    '''from typing import Any, Iterable\n\n\nKINDS =''',
    '''from typing import Any, Iterable\n\nfrom .memory_dpapi import WindowsDpapiMemoryProtector\nfrom .memory_protection import (\n    MemoryProtectionError,\n    MemoryProtector,\n    is_protected,\n    open_text,\n    seal_text,\n)\n\n\nKINDS =''',
)
replace_once(
    MEMORY,
    '''    def __init__(self, path: str):\n        if path != ":memory:":\n            Path(path).parent.mkdir(parents=True, exist_ok=True)\n        self._lock = threading.RLock()\n        self._conn = sqlite3.connect(path, check_same_thread=False)\n''',
    '''    def __init__(\n        self,\n        path: str,\n        *,\n        protector: MemoryProtector | None = None,\n    ):\n        if path != ":memory:":\n            Path(path).parent.mkdir(parents=True, exist_ok=True)\n        self._lock = threading.RLock()\n        self._protector = protector or WindowsDpapiMemoryProtector()\n        self._conn = sqlite3.connect(path, check_same_thread=False)\n''',
)
replace_once(
    MEMORY,
    '''        self._conn.execute(\n            "CREATE INDEX IF NOT EXISTS idx_agent_memories_lookup "\n            "ON agent_memories(subject,predicate,lifecycle_status,review_status)"\n        )\n''',
    '''        self._conn.execute(\n            "CREATE TABLE IF NOT EXISTS agent_memory_meta ("\n            "key TEXT PRIMARY KEY,value TEXT NOT NULL)"\n        )\n        self._conn.execute(\n            "INSERT OR IGNORE INTO agent_memory_meta(key,value) VALUES('store_scope',?)",\n            (uuid.uuid4().hex,),\n        )\n        scope_row = self._conn.execute(\n            "SELECT value FROM agent_memory_meta WHERE key='store_scope'"\n        ).fetchone()\n        if scope_row is None or not isinstance(scope_row[0], str) or not scope_row[0]:\n            raise MemoryStoreError("memory store protection scope is missing")\n        self._store_scope = scope_row[0]\n        self._conn.execute(\n            "CREATE INDEX IF NOT EXISTS idx_agent_memories_lookup "\n            "ON agent_memories(subject,predicate,lifecycle_status,review_status)"\n        )\n''',
)
old_search = '''    def search(\n        self,\n        query: str,\n        *,\n        confirmed_only: bool = True,\n        include_secret: bool = False,\n        limit: int = 50,\n    ) -> list[MemoryRecord]:\n        q = self._clean_text("query", query, 300)\n        escaped = q.replace("\\\\", "\\\\\\\\").replace("%", "\\\\%").replace("_", "\\\\_")\n        pattern = f"%{escaped.lower()}%"\n        clauses = [\n            "lifecycle_status='active'",\n            "(expires_at IS NULL OR expires_at>?)",\n            "(lower(subject) LIKE ? ESCAPE '\\\\' OR lower(predicate) LIKE ? ESCAPE '\\\\' "\n            "OR lower(value) LIKE ? ESCAPE '\\\\')",\n        ]\n        params: list[Any] = [time.time(), pattern, pattern, pattern]\n        if confirmed_only:\n            clauses.append("review_status='confirmed'")\n        if not include_secret:\n            clauses.append("sensitivity!='secret'")\n        params.append(max(1, min(int(limit), 200)))\n        with self._lock:\n            rows = self._conn.execute(\n                "SELECT * FROM agent_memories WHERE " + " AND ".join(clauses)\n                + " ORDER BY updated_at DESC LIMIT ?",\n                tuple(params),\n            ).fetchall()\n        return [self._record(row) for row in rows]\n'''
new_search = '''    def search(\n        self,\n        query: str,\n        *,\n        confirmed_only: bool = True,\n        include_secret: bool = False,\n        limit: int = 50,\n    ) -> list[MemoryRecord]:\n        # Sensitive values are ciphertext in SQLite and must never be indexed or\n        # matched as storage syntax. Select a bounded recent candidate set using\n        # non-sensitive metadata, then open/filter inside the authorized store.\n        needle = self._clean_text("query", query, 300).casefold()\n        result_limit = max(1, min(int(limit), 200))\n        candidate_limit = max(200, min(result_limit * 20, 2_000))\n        clauses = [\n            "lifecycle_status='active'",\n            "(expires_at IS NULL OR expires_at>?)",\n        ]\n        params: list[Any] = [time.time()]\n        if confirmed_only:\n            clauses.append("review_status='confirmed'")\n        if not include_secret:\n            clauses.append("sensitivity!='secret'")\n        params.append(candidate_limit)\n        with self._lock:\n            rows = self._conn.execute(\n                "SELECT * FROM agent_memories WHERE " + " AND ".join(clauses)\n                + " ORDER BY updated_at DESC LIMIT ?",\n                tuple(params),\n            ).fetchall()\n        matches: list[MemoryRecord] = []\n        for row in rows:\n            record = self._record(row)\n            if any(\n                needle in value.casefold()\n                for value in (record.subject, record.predicate, record.value)\n            ):\n                matches.append(record)\n                if len(matches) >= result_limit:\n                    break\n        return matches\n'''
replace_once(MEMORY, old_search, new_search)
replace_once(
    MEMORY,
    '''    def _insert_locked(\n        self,\n''',
    '''    @staticmethod\n    def _is_sensitive(sensitivity: str) -> bool:\n        return sensitivity in {"private", "secret"}\n\n    def _seal_field(self, value: str, *, memory_id: str, field: str) -> str:\n        try:\n            return seal_text(\n                self._protector,\n                value,\n                store_scope=self._store_scope,\n                record_id=memory_id,\n                field=field,\n            )\n        except MemoryProtectionError as exc:\n            raise MemoryStoreError(\n                f"sensitive memory {field} could not be protected"\n            ) from exc\n\n    def _open_field(self, value: str, *, memory_id: str, field: str) -> str:\n        if not is_protected(value):\n            raise MemoryStoreError(\n                "legacy sensitive memory requires protected migration"\n            )\n        try:\n            return open_text(\n                self._protector,\n                value,\n                store_scope=self._store_scope,\n                record_id=memory_id,\n                field=field,\n            )\n        except MemoryProtectionError as exc:\n            raise MemoryStoreError(\n                f"sensitive memory {field} could not be opened"\n            ) from exc\n\n    def _insert_locked(\n        self,\n''',
)
old_insert = '''        memory_id = str(uuid.uuid4())\n        now = time.time()\n        self._conn.execute(\n            "INSERT INTO agent_memories("\n            "id,subject,predicate,value,kind,sensitivity,source_type,source_ref,confidence,"\n            "review_status,lifecycle_status,supersedes_id,created_at,updated_at,expires_at,"\n            "deleted_at,schema_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",\n            (\n                memory_id,\n                subject,\n                predicate,\n                value,\n                kind,\n                sensitivity,\n                source_type,\n                source_ref,\n                confidence,\n                review_status,\n                "active",\n                supersedes_id,\n                now,\n                now,\n                expires_at,\n                None,\n            ),\n        )\n'''
new_insert = '''        memory_id = str(uuid.uuid4())\n        now = time.time()\n        schema_version = 1\n        stored_value = value\n        stored_source_ref = source_ref\n        if self._is_sensitive(sensitivity):\n            stored_value = self._seal_field(\n                value, memory_id=memory_id, field="value"\n            )\n            if source_ref is not None:\n                stored_source_ref = self._seal_field(\n                    source_ref, memory_id=memory_id, field="source_ref"\n                )\n            schema_version = 2\n        self._conn.execute(\n            "INSERT INTO agent_memories("\n            "id,subject,predicate,value,kind,sensitivity,source_type,source_ref,confidence,"\n            "review_status,lifecycle_status,supersedes_id,created_at,updated_at,expires_at,"\n            "deleted_at,schema_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",\n            (\n                memory_id,\n                subject,\n                predicate,\n                stored_value,\n                kind,\n                sensitivity,\n                source_type,\n                stored_source_ref,\n                confidence,\n                review_status,\n                "active",\n                supersedes_id,\n                now,\n                now,\n                expires_at,\n                None,\n                schema_version,\n            ),\n        )\n'''
replace_once(MEMORY, old_insert, new_insert)
replace_once(
    MEMORY,
    '''    @staticmethod\n    def _record(row: sqlite3.Row | None) -> MemoryRecord:\n        if row is None:\n            raise MemoryNotFound("memory not found")\n        return MemoryRecord(**dict(row))\n''',
    '''    def _record(self, row: sqlite3.Row | None) -> MemoryRecord:\n        if row is None:\n            raise MemoryNotFound("memory not found")\n        data = dict(row)\n        if (\n            self._is_sensitive(data["sensitivity"])\n            and data["lifecycle_status"] != "deleted"\n        ):\n            data["value"] = self._open_field(\n                data["value"], memory_id=data["id"], field="value"\n            )\n            if data["source_ref"] is not None:\n                data["source_ref"] = self._open_field(\n                    data["source_ref"],\n                    memory_id=data["id"],\n                    field="source_ref",\n                )\n        return MemoryRecord(**data)\n''',
)

replace_once(
    "tests/worker_agent3_memory.py",
    "from app.agent3.memory import MemoryNotFound, MemoryStore, MemoryStoreError\n",
    "from app.agent3.memory import MemoryNotFound, MemoryStore, MemoryStoreError\n"
    "from support_memory_protector import TestMemoryProtector\n",
)
replace_once(
    "tests/worker_agent3_memory.py",
    "store = MemoryStore(path)",
    "protector = TestMemoryProtector()\nstore = MemoryStore(path, protector=protector)",
)
replace_once(
    "tests/worker_agent3_memory.py",
    "reopened = MemoryStore(path)",
    "reopened = MemoryStore(path, protector=protector)",
)

replace_once(
    "tests/worker_agent3_memory_context.py",
    "from app.agent3.memory import MemoryStore\n",
    "from app.agent3.memory import MemoryStore\n"
    "from support_memory_protector import TestMemoryProtector\n",
)
replace_once(
    "tests/worker_agent3_memory_context.py",
    'store = MemoryStore(os.path.join(tempfile.mkdtemp(prefix="agent3-memory-context-"), "memory.db"))',
    'store = MemoryStore(\n    os.path.join(tempfile.mkdtemp(prefix="agent3-memory-context-"), "memory.db"),\n    protector=TestMemoryProtector(),\n)',
)

replace_once(
    "tests/worker_agent3_memory_api.py",
    "from app.agent3.memory import MemoryStore\n",
    "from app.agent3.memory import MemoryStore\n"
    "from support_memory_protector import TestMemoryProtector\n",
)
replace_once(
    "tests/worker_agent3_memory_api.py",
    'store = MemoryStore(os.path.join(tempfile.mkdtemp(prefix="agent3-memory-api-"), "memory.db"))',
    'store = MemoryStore(\n    os.path.join(tempfile.mkdtemp(prefix="agent3-memory-api-"), "memory.db"),\n    protector=TestMemoryProtector(),\n)',
)

replace_once(
    "tests/worker_agent3_planner_memory.py",
    "from app.agent3.memory import MemoryStore\n",
    "from app.agent3.memory import MemoryStore\n"
    "from support_memory_protector import TestMemoryProtector\n",
)
replace_once(
    "tests/worker_agent3_planner_memory.py",
    'memory_store = MemoryStore(os.path.join(root, "memory.db"))',
    'memory_store = MemoryStore(\n    os.path.join(root, "memory.db"),\n    protector=TestMemoryProtector(),\n)',
)

print("T-033 protected MemoryStore stage applied")
