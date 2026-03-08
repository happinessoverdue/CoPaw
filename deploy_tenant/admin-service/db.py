"""SQLite data layer for tenant configuration storage.

All tenant CRUD operations go through this module. The database file is stored
at DB_PATH (default /app/data/admin.db), which should be on a host-mounted
volume so data survives container restarts.
"""

import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = os.environ.get("DB_PATH", "/app/data/admin.db")

_local = threading.local()

_BAD_ID_PATTERN = re.compile(r"[/\\: ]")


def _get_conn() -> sqlite3.Connection:
    """Return a thread-local SQLite connection with WAL mode."""
    if not hasattr(_local, "conn") or _local.conn is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return _local.conn


def init_db() -> None:
    """Create the tenants table if it does not exist."""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            user_id    TEXT PRIMARY KEY,
            user_name  TEXT NOT NULL,
            password   TEXT NOT NULL,
            env        TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _validate_user_id(user_id: str) -> Optional[str]:
    """Return an error message if user_id is invalid, else None."""
    if not user_id or not user_id.strip():
        return "user_id 不能为空"
    if _BAD_ID_PATTERN.search(user_id):
        return "user_id 不能包含 / \\ : 或空格"
    if len(user_id) > 64:
        return "user_id 长度不能超过 64 字符"
    return None


def get_all_tenants() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT user_id, user_name, password, env, created_at, updated_at FROM tenants ORDER BY created_at"
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["env"] = json.loads(d.get("env") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["env"] = {}
        result.append(d)
    return result


def get_tenant(user_id: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT user_id, user_name, password, env, created_at, updated_at FROM tenants WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    try:
        d["env"] = json.loads(d.get("env") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["env"] = {}
    return d


def add_tenant(user_id: str, user_name: str, password: str, env: Optional[dict] = None) -> tuple[bool, str]:
    """Add a tenant. Returns (success, message)."""
    err = _validate_user_id(user_id)
    if err:
        return False, err
    if not user_name or not user_name.strip():
        return False, "user_name 不能为空"
    if not password:
        return False, "password 不能为空"

    conn = _get_conn()
    try:
        now = _now_iso()
        conn.execute(
            "INSERT INTO tenants (user_id, user_name, password, env, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id.strip(), user_name.strip(), password, json.dumps(env or {}), now, now),
        )
        conn.commit()
        return True, "ok"
    except sqlite3.IntegrityError:
        return False, f"user_id '{user_id}' 已存在"


def update_tenant(user_id: str, user_name: Optional[str] = None,
                  password: Optional[str] = None, env: Optional[dict] = None) -> tuple[bool, str]:
    """Update a tenant. Only non-None fields are updated. Returns (success, message)."""
    existing = get_tenant(user_id)
    if existing is None:
        return False, f"租户 '{user_id}' 不存在"

    sets = []
    params = []
    if user_name is not None:
        if not user_name.strip():
            return False, "user_name 不能为空"
        sets.append("user_name = ?")
        params.append(user_name.strip())
    if password is not None:
        if not password:
            return False, "password 不能为空"
        sets.append("password = ?")
        params.append(password)
    if env is not None:
        sets.append("env = ?")
        params.append(json.dumps(env))

    if not sets:
        return True, "无变更"

    sets.append("updated_at = ?")
    params.append(_now_iso())
    params.append(user_id)

    conn = _get_conn()
    conn.execute(f"UPDATE tenants SET {', '.join(sets)} WHERE user_id = ?", params)
    conn.commit()
    return True, "ok"


def delete_tenant(user_id: str) -> tuple[bool, str]:
    """Delete a tenant. Returns (success, message)."""
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM tenants WHERE user_id = ?", (user_id,))
    conn.commit()
    if cursor.rowcount == 0:
        return False, f"租户 '{user_id}' 不存在"
    return True, "ok"


def import_tenants(tenant_list: list[dict]) -> tuple[int, list[str]]:
    """Bulk import tenants. Returns (success_count, error_messages).

    Each item should have: user_id, user_name, password, and optionally env.
    Existing user_ids are skipped with an error message.
    """
    success = 0
    errors = []

    for i, t in enumerate(tenant_list):
        uid = t.get("user_id", "")
        uname = t.get("user_name", "")
        pw = t.get("password", "")
        env = t.get("env")

        if not uid:
            errors.append(f"第 {i+1} 条: 缺少 user_id")
            continue

        ok, msg = add_tenant(uid, uname, pw, env)
        if ok:
            success += 1
        else:
            errors.append(f"{uid}: {msg}")

    return success, errors
