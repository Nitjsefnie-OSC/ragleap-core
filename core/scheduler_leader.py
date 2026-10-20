"""
One scheduler per database.

The background jobs (data-source sync, proactive triggers) run inside the web process. With several
web workers or replicas, every process would run them and each proactive trigger would fire more than
once. A Postgres advisory lock picks one leader: only the process that holds it runs the jobs. If the
leader dies, the database drops its connection and with it the lock, and another process takes over
on its next tick (within about a minute).

SCHEDULER_ENABLED=false (default: true) turns the jobs off in one process for good, for a replica that
must never lead. Never raises.

Limit: the lock belongs to a database connection, so it needs a direct Postgres connection. A
connection pooler in transaction mode (for example pgbouncer) would drop it.
"""
import logging
import threading

import os

logger = logging.getLogger(__name__)

LOCK_KEY = 7421905501
_lock = threading.Lock()
_leader_conn = None


def enabled() -> bool:
    return os.environ.get("SCHEDULER_ENABLED", "true").strip().lower() not in ("false", "0", "no", "off")


def _connect():
    from core.employees._db import get_connection
    conn = get_connection()
    conn.autocommit = True
    return conn


def _alive(conn) -> bool:
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        return True
    except Exception:
        return False


def _close(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass


def is_leader() -> bool:
    """True if this process holds (or has just won) the scheduler lock."""
    global _leader_conn
    if not enabled():
        return False
    with _lock:
        if _leader_conn is not None:
            if _alive(_leader_conn):
                return True
            _close(_leader_conn)
            _leader_conn = None
            logger.warning("Scheduler leader connection was lost; trying to take the lock again.")
        conn = None
        try:
            conn = _connect()
            cur = conn.cursor()
            cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
            got = bool(cur.fetchone()[0])
            cur.close()
        except Exception as e:
            logger.warning("Scheduler leader check failed: %s", type(e).__name__)
            if conn is not None:
                _close(conn)
            return False
        if got:
            _leader_conn = conn
            logger.info("This process is now the scheduler leader.")
            return True
        _close(conn)
        return False


def release() -> None:
    """Give the lock up (closing the connection drops it). Safe to call when not leader."""
    global _leader_conn
    with _lock:
        if _leader_conn is not None:
            _close(_leader_conn)
            _leader_conn = None


def leader_only(job):
    """Wrap an async job so it runs only in the leader process."""
    import asyncio

    async def run():
        if await asyncio.to_thread(is_leader):
            await job()
    return run
