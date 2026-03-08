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
BASE_DATA_DIR = os.environ.get("BASE_DATA_DIR", "/data/copaw")
INSTANCE_PREFIX = os.environ.get("INSTANCE_PREFIX", "copaw-instance-")

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
            user_id       TEXT PRIMARY KEY,
            user_name     TEXT NOT NULL,
            password      TEXT NOT NULL,
            env           TEXT DEFAULT '{}',
            extra_mounts  TEXT DEFAULT '[]',
            container_name TEXT,
            default_mounts TEXT DEFAULT '[]',
            created_at    TEXT DEFAULT (datetime('now')),
            updated_at    TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    # 迁移：为已存在表添加新列
    for col_def in [
        ("extra_mounts", "TEXT DEFAULT '[]'"),
        ("container_name", "TEXT"),
        ("default_mounts", "TEXT DEFAULT '[]'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE tenants ADD COLUMN {col_def[0]} {col_def[1]}")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    _backfill_container_and_default_mounts(conn)
    # 迁移：删除已废弃的 default_mount 列（SQLite 3.35+ 支持 DROP COLUMN）
    try:
        conn.execute("ALTER TABLE tenants DROP COLUMN default_mount")
        conn.commit()
    except sqlite3.OperationalError:
        pass


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


def _parse_extra_mounts(raw: str | None) -> list:
    try:
        return json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_default_mounts(raw: str | None) -> list:
    """Parse default_mounts as list of {host, bind, mode}."""
    try:
        o = json.loads(raw or "[]")
        return o if isinstance(o, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _backfill_container_and_default_mounts(conn: sqlite3.Connection) -> None:
    """Backfill container_name and default_mounts for existing rows where they are null."""
    try:
        rows = conn.execute(
            "SELECT user_id FROM tenants WHERE container_name IS NULL OR default_mounts IS NULL"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = conn.execute(
            "SELECT user_id FROM tenants WHERE container_name IS NULL"
        ).fetchall()
    for row in rows:
        uid = row["user_id"]
        cnt = INSTANCE_PREFIX + uid
        dm_list = [
            {"host": f"{BASE_DATA_DIR}/{uid}/working", "bind": "/app/working", "mode": "rw"},
            {"host": f"{BASE_DATA_DIR}/{uid}/working.secret", "bind": "/app/working.secret", "mode": "rw"},
        ]
        try:
            conn.execute(
                "UPDATE tenants SET container_name = ?, default_mounts = ? WHERE user_id = ?",
                (cnt, json.dumps(dm_list), uid),
            )
        except sqlite3.OperationalError:
            conn.execute(
                "UPDATE tenants SET container_name = ? WHERE user_id = ?",
                (cnt, uid),
            )
    if rows:
        conn.commit()


def get_all_tenants() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT user_id, user_name, password, env, extra_mounts, container_name, default_mounts, created_at, updated_at FROM tenants ORDER BY created_at"
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["env"] = json.loads(d.get("env") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["env"] = {}
        d["extra_mounts"] = _parse_extra_mounts(d.get("extra_mounts"))
        d["default_mounts"] = _parse_default_mounts(d.get("default_mounts"))
        result.append(d)
    return result


def get_tenant(user_id: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT user_id, user_name, password, env, extra_mounts, container_name, default_mounts, created_at, updated_at FROM tenants WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    try:
        d["env"] = json.loads(d.get("env") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["env"] = {}
    d["extra_mounts"] = _parse_extra_mounts(d.get("extra_mounts"))
    d["default_mounts"] = _parse_default_mounts(d.get("default_mounts"))
    return d


def add_tenant(user_id: str, user_name: str, password: str, env: Optional[dict] = None,
               extra_mounts: Optional[list] = None,
               container_name: Optional[str] = None,
               default_mounts: Optional[list] = None) -> tuple[bool, str]:
    """Add a tenant. Returns (success, message).

    container_name and default_mounts can be provided; if not, they are computed from user_id.
    """
    err = _validate_user_id(user_id)
    if err:
        return False, err
    if not user_name or not user_name.strip():
        return False, "user_name 不能为空"
    if not password:
        return False, "password 不能为空"

    uid = user_id.strip()
    cnt = container_name if container_name else (INSTANCE_PREFIX + uid)
    dm_list = default_mounts if default_mounts else [
        {"host": f"{BASE_DATA_DIR}/{uid}/working", "bind": "/app/working", "mode": "rw"},
        {"host": f"{BASE_DATA_DIR}/{uid}/working.secret", "bind": "/app/working.secret", "mode": "rw"},
    ]

    conn = _get_conn()
    try:
        now = _now_iso()
        mounts = extra_mounts if extra_mounts is not None else []
        conn.execute(
            "INSERT INTO tenants (user_id, user_name, password, env, extra_mounts, container_name, default_mounts, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, user_name.strip(), password, json.dumps(env or {}), json.dumps(mounts), cnt, json.dumps(dm_list), now, now),
        )
        conn.commit()
        return True, "ok"
    except sqlite3.IntegrityError:
        return False, f"user_id '{user_id}' 已存在"


def update_tenant(user_id: str, user_name: Optional[str] = None,
                  password: Optional[str] = None, env: Optional[dict] = None,
                  extra_mounts: Optional[list] = None) -> tuple[bool, str]:
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
    if extra_mounts is not None:
        sets.append("extra_mounts = ?")
        params.append(json.dumps(extra_mounts))

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
        extra_mounts = t.get("extra_mounts")

        if not uid:
            errors.append(f"第 {i+1} 条: 缺少 user_id")
            continue

        ok, msg = add_tenant(uid, uname, pw, env, extra_mounts)
        if ok:
            success += 1
        else:
            errors.append(f"{uid}: {msg}")

    return success, errors
