"""SQLite data layer for tenant configuration storage.

纯数据访问层，通过 TenantDB 类封装所有状态（数据库路径、容器命名规则等）。
调用方（main.py）实例化一次 TenantDB 后复用，无模块级可变状态、无环境变量读取。
"""

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# 模块级纯工具函数（无状态）
# ---------------------------------------------------------------------------

_BAD_ID_PATTERN = re.compile(r"[/\\: ]")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _validate_user_id(user_id: str) -> Optional[str]:
    if not user_id or not user_id.strip():
        return "user_id 不能为空"
    if user_id.strip().lower() == "admin":
        return "user_id 不能使用 admin（系统保留）"
    if _BAD_ID_PATTERN.search(user_id):
        return "user_id 不能包含 / \\ : 或空格"
    if len(user_id) > 64:
        return "user_id 长度不能超过 64 字符"
    return None


def _parse_json_list(raw: str | None) -> list:
    """将 JSON 字符串解析为 list，解析失败返回空列表。"""
    try:
        o = json.loads(raw or "[]")
        return o if isinstance(o, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# ---------------------------------------------------------------------------
# TenantDB
# ---------------------------------------------------------------------------

class TenantDB:
    """线程安全的租户数据存储，基于 SQLite。

    参数由调用方(main.py)在实例化时传入，类自身不读取任何环境变量：
    - db_path: 数据库文件绝对路径
    - instance_prefix: 租户容器名前缀（如 gridpaw-instance-）
    - tenants_data_base_dir: 宿主机上租户数据根目录

    构造时自动完成建表与迁移。
    """

    # ------------------------------------------------------------------
    # SQL 类变量
    # ------------------------------------------------------------------

    _SQL_CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS tenants (
            user_id        TEXT PRIMARY KEY,
            user_name      TEXT NOT NULL,
            password       TEXT NOT NULL,
            container_name TEXT NOT NULL,
            default_mounts TEXT NOT NULL DEFAULT '[]',
            env            TEXT NOT NULL DEFAULT '{}',
            extra_mounts   TEXT NOT NULL DEFAULT '[]',
            is_meta        INTEGER NOT NULL DEFAULT 0,
            tenant_group   TEXT NOT NULL DEFAULT '通用',
            created_at     TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """

    _SQL_FIELDS = (
        "user_id, user_name, password, container_name, default_mounts, "
        "env, extra_mounts, is_meta, tenant_group, created_at, updated_at"
    )

    _SQL_SELECT_ALL = f"SELECT {_SQL_FIELDS} FROM tenants ORDER BY is_meta DESC, created_at"
    _SQL_SELECT_ONE = f"SELECT {_SQL_FIELDS} FROM tenants WHERE user_id = ?"
    _SQL_SELECT_META = f"SELECT {_SQL_FIELDS} FROM tenants WHERE is_meta = 1 ORDER BY tenant_group, created_at"

    _SQL_INSERT = (
        "INSERT INTO tenants "
        "(user_id, user_name, password, container_name, default_mounts, "
        "env, extra_mounts, is_meta, tenant_group, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )

    _SQL_DELETE = "DELETE FROM tenants WHERE user_id = ?"

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def __init__(
        self, db_path: str | Path, instance_prefix: str, tenants_data_base_dir: str
    ) -> None:
        self._db_path = db_path
        self._instance_prefix = instance_prefix
        self._tenants_data_base_dir = tenants_data_base_dir
        self._local = threading.local()
        self._setup()

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local SQLite connection with WAL mode."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _setup(self) -> None:
        """建表，由 __init__ 自动调用。"""
        conn = self._get_conn()
        conn.execute(self._SQL_CREATE_TABLE)
        conn.commit()

    # ------------------------------------------------------------------
    # 公开 CRUD 接口
    # ------------------------------------------------------------------

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """将数据库行转换为 dict，并反序列化 JSON 字段。"""
        d = dict(row)
        try:
            d["env"] = json.loads(d.get("env") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["env"] = {}
        d["default_mounts"] = _parse_json_list(d.get("default_mounts"))
        d["extra_mounts"] = _parse_json_list(d.get("extra_mounts"))
        d["is_meta"] = bool(d.get("is_meta", 0))
        d["tenant_group"] = d.get("tenant_group") or "通用"
        return d

    def get_all_tenants(self) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(self._SQL_SELECT_ALL).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_tenant(self, user_id: str) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute(self._SQL_SELECT_ONE, (user_id,)).fetchone()
        return self._row_to_dict(row) if row is not None else None

    def get_meta_tenants(self) -> list[dict]:
        """返回所有元租户，按 tenant_group 和 created_at 排序。"""
        conn = self._get_conn()
        rows = conn.execute(self._SQL_SELECT_META).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_groups(self) -> list[str]:
        """返回去重的租户组名列表。"""
        conn = self._get_conn()
        rows = conn.execute("SELECT DISTINCT tenant_group FROM tenants ORDER BY tenant_group").fetchall()
        return [r["tenant_group"] for r in rows]

    def add_tenant(self, user_id: str, user_name: str, password: str,
                   env: Optional[dict] = None,
                   extra_mounts: Optional[list] = None,
                   container_name: Optional[str] = None,
                   default_mounts: Optional[list] = None,
                   is_meta: bool = False,
                   tenant_group: Optional[str] = None) -> tuple[bool, str]:
        """Add a tenant. Returns (success, message).

        container_name 和 default_mounts 若不传入，由实例根据 instance_prefix 和
        tenants_data_base_dir 自动计算。
        """
        err = _validate_user_id(user_id)
        if err:
            return False, err
        if not user_name or not user_name.strip():
            return False, "user_name 不能为空"
        if not password:
            return False, "password 不能为空"

        uid = user_id.strip()
        cnt = container_name or (self._instance_prefix + uid)
        dm_list = default_mounts or [
            {"host": f"{self._tenants_data_base_dir}/{uid}/working", "bind": "/root/.copaw", "mode": "rw"},
            {"host": f"{self._tenants_data_base_dir}/{uid}/working.secret", "bind": "/root/.copaw.secret", "mode": "rw"},
        ]

        conn = self._get_conn()
        try:
            now = _now_iso()
            conn.execute(
                self._SQL_INSERT,
                (uid, user_name.strip(), password, cnt,
                 json.dumps(dm_list), json.dumps(env or {}),
                 json.dumps(extra_mounts or []),
                 1 if is_meta else 0,
                 (tenant_group or "通用").strip(),
                 now, now),
            )
            conn.commit()
            return True, "ok"
        except sqlite3.IntegrityError:
            return False, f"user_id '{user_id}' 已存在"

    def update_tenant(self, user_id: str, user_name: Optional[str] = None,
                      password: Optional[str] = None, env: Optional[dict] = None,
                      extra_mounts: Optional[list] = None,
                      is_meta: Optional[bool] = None,
                      tenant_group: Optional[str] = None) -> tuple[bool, str]:
        """Update a tenant. Only non-None fields are updated. Returns (success, message)."""
        if self.get_tenant(user_id) is None:
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
        if is_meta is not None:
            sets.append("is_meta = ?")
            params.append(1 if is_meta else 0)
        if tenant_group is not None:
            sets.append("tenant_group = ?")
            params.append(tenant_group.strip())

        if not sets:
            return True, "无变更"

        sets.append("updated_at = ?")
        params.append(_now_iso())
        params.append(user_id)

        conn = self._get_conn()
        conn.execute(f"UPDATE tenants SET {', '.join(sets)} WHERE user_id = ?", params)
        conn.commit()
        return True, "ok"

    def delete_tenant(self, user_id: str) -> tuple[bool, str]:
        """Delete a tenant. Meta tenants must be demoted first."""
        tenant = self.get_tenant(user_id)
        if tenant is None:
            return False, f"租户 '{user_id}' 不存在"
        if tenant.get("is_meta"):
            return False, f"元租户 '{user_id}' 不可直接删除，请先取消元租户身份"

        conn = self._get_conn()
        cursor = conn.execute(self._SQL_DELETE, (user_id,))
        conn.commit()
        if cursor.rowcount == 0:
            return False, f"租户 '{user_id}' 不存在"
        return True, "ok"

    def import_tenants(self, tenant_list: list[dict]) -> tuple[int, list[str], list[str]]:
        """Bulk import tenants. Returns (success_count, error_messages, imported_user_ids).

        Each item should have: user_id, user_name, password, and optionally env,
        extra_mounts, is_meta, tenant_group.
        Existing user_ids are skipped with an error message.
        container_name 和 default_mounts 由实例自动计算，无需在数据中提供。
        """
        success = 0
        errors = []
        imported_ids: list[str] = []
        for i, t in enumerate(tenant_list):
            uid = t.get("user_id", "")
            if not uid:
                errors.append(f"第 {i+1} 条: 缺少 user_id")
                continue
            ok, msg = self.add_tenant(
                uid, t.get("user_name", ""), t.get("password", ""),
                env=t.get("env"),
                extra_mounts=t.get("extra_mounts"),
                is_meta=bool(t.get("is_meta", False)),
                tenant_group=t.get("tenant_group"),
            )
            if ok:
                success += 1
                imported_ids.append(uid)
            else:
                errors.append(f"{uid}: {msg}")
        return success, errors, imported_ids
