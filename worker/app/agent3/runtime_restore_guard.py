from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_GUARD_TABLE = "agent3_runtime_restore_guard"
_GUARD_SQL = (
    "CREATE TABLE agent3_runtime_restore_guard ("
    "id INTEGER PRIMARY KEY CHECK(id=1), "
    "restore_in_progress INTEGER NOT NULL CHECK(restore_in_progress IN (0,1)))"
)


def _guard_path(run_db_path: str) -> str:
    return f"{run_db_path}.runtime-restore-guard.db"


def _open_guard(run_db_path: str) -> sqlite3.Connection:
    path = _guard_path(run_db_path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=0.0, isolation_level=None, check_same_thread=False)
    try:
        try:
            row = con.execute(
                f"SELECT restore_in_progress FROM {_GUARD_TABLE} WHERE id=1"
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            con.execute(_GUARD_SQL)
            con.execute(
                f"INSERT INTO {_GUARD_TABLE}(id,restore_in_progress) VALUES(1,0)"
            )
            row = (0,)
        if row is None or int(row[0]) not in (0, 1):
            raise RuntimeError("Agent3 runtime/restore guard is corrupt")
        con.execute("PRAGMA busy_timeout=0")
        return con
    except Exception:
        con.close()
        raise


class Agent3RuntimeLease:
    """A long-lived shared SQLite read transaction owned by one runtime store."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._connection.in_transaction:
                self._connection.rollback()
        finally:
            self._connection.close()


class Agent3RestoreLease:
    """Exclusive restore lease plus a durable fail-closed incomplete marker."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        self._closed = False

    def complete(self) -> None:
        if self._closed:
            return
        try:
            self._connection.execute(
                f"UPDATE {_GUARD_TABLE} SET restore_in_progress=0 WHERE id=1"
            )
            self._connection.commit()
        finally:
            self._closed = True
            self._connection.close()

    def abort(self) -> None:
        if self._closed:
            return
        # restore_in_progress=1 was committed before the exclusive restore
        # transaction began. Rolling this transaction back therefore leaves the
        # durable marker set so a partial restore cannot boot Agent3.
        try:
            if self._connection.in_transaction:
                self._connection.rollback()
        finally:
            self._closed = True
            self._connection.close()


def acquire_agent3_runtime_lease(run_db_path: str) -> Agent3RuntimeLease:
    """Acquire shared runtime authority, refusing incomplete/active restore."""
    try:
        con = _open_guard(run_db_path)
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            raise RuntimeError(
                "Agent3 restore or maintenance is in progress; runtime startup is blocked"
            ) from exc
        raise
    try:
        con.execute("BEGIN")
        row = con.execute(
            f"SELECT restore_in_progress FROM {_GUARD_TABLE} WHERE id=1"
        ).fetchone()
        if row != (0,):
            con.rollback()
            raise RuntimeError(
                "Agent3 restore is incomplete; rerun a verified restore before starting Agent3"
            )
        # Keep this read transaction open for the lifetime of AgentRunStore. In
        # rollback-journal mode it owns a SHARED lock, so exclusive restore or
        # maintenance cannot succeed while this runtime is alive.
        return Agent3RuntimeLease(con)
    except sqlite3.OperationalError as exc:
        try:
            if con.in_transaction:
                con.rollback()
        finally:
            con.close()
        if "locked" in str(exc).lower():
            raise RuntimeError(
                "Agent3 restore or maintenance is in progress; runtime startup is blocked"
            ) from exc
        raise
    except Exception:
        try:
            if con.in_transaction:
                con.rollback()
        finally:
            con.close()
        raise


def acquire_agent3_restore_lease(run_db_path: str) -> Agent3RestoreLease:
    """Acquire exclusive restore authority or fail immediately if runtime is live."""
    try:
        con = _open_guard(run_db_path)
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            raise RuntimeError(
                "Agent3 restore is already in progress; concurrent restore is refused"
            ) from exc
        raise
    try:
        # First exclusive transaction is deliberately non-blocking. Any live
        # AgentRunStore owns a shared transaction and makes this fail before a
        # single live restore destination is touched.
        con.execute("PRAGMA busy_timeout=0")
        con.execute("BEGIN EXCLUSIVE")
    except sqlite3.OperationalError as exc:
        con.close()
        if "locked" in str(exc).lower():
            raise RuntimeError(
                "Agent3 runtime or maintenance is active; stop it before restoring persistent state"
            ) from exc
        raise

    try:
        # Make restore intent durable BEFORE publishing anything. If the process
        # crashes later, fresh Agent3 startup sees this marker and fails closed.
        con.execute(
            f"UPDATE {_GUARD_TABLE} SET restore_in_progress=1 WHERE id=1"
        )
        con.commit()

        # New runtime attempts now read marker=1 and immediately retire. Give
        # those brief probes room to release their read lock, then hold EXCLUSIVE
        # for the entire restore so no runtime can enter mid-publication.
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("BEGIN EXCLUSIVE")
        row = con.execute(
            f"SELECT restore_in_progress FROM {_GUARD_TABLE} WHERE id=1"
        ).fetchone()
        if row != (1,):
            raise RuntimeError("Agent3 restore guard lost its durable marker")
        return Agent3RestoreLease(con)
    except Exception:
        try:
            if con.in_transaction:
                con.rollback()
        finally:
            con.close()
        # The committed marker intentionally remains 1 on every failure after
        # restore authority was acquired.
        raise


@contextmanager
def agent3_maintenance_guard(run_db_path: str) -> Iterator[None]:
    """Hold exclusive runtime authority for an atomic non-restore transition.

    Unlike restore, maintenance does not publish multiple files and therefore
    needs no durable incomplete marker. A crash rolls the maintenance operation
    back and releases this SQLite lock. Existing restore-incomplete authority is
    never bypassed or cleared by maintenance.
    """
    try:
        con = _open_guard(run_db_path)
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            raise RuntimeError(
                "Agent3 restore or maintenance is active; maintenance is refused"
            ) from exc
        raise
    try:
        con.execute("PRAGMA busy_timeout=0")
        con.execute("BEGIN EXCLUSIVE")
        row = con.execute(
            f"SELECT restore_in_progress FROM {_GUARD_TABLE} WHERE id=1"
        ).fetchone()
        if row != (0,):
            raise RuntimeError(
                "Agent3 restore is incomplete; maintenance is refused until verified restore recovery"
            )
    except sqlite3.OperationalError as exc:
        con.close()
        if "locked" in str(exc).lower():
            raise RuntimeError(
                "Agent3 runtime is active; stop it before maintenance"
            ) from exc
        raise
    except Exception:
        if con.in_transaction:
            con.rollback()
        con.close()
        raise

    try:
        yield
    except BaseException:
        if con.in_transaction:
            con.rollback()
        raise
    else:
        con.commit()
    finally:
        con.close()


@contextmanager
def agent3_restore_guard(run_db_path: str) -> Iterator[None]:
    lease = acquire_agent3_restore_lease(run_db_path)
    try:
        yield
    except BaseException:
        lease.abort()
        raise
    else:
        lease.complete()
