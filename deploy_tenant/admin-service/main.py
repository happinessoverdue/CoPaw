"""GridPaw multi-tenant admin service.

Combines authentication gateway (for GridPaw users) and management API
(for administrators). Tenant data is stored in SQLite; GridPaw containers
are managed dynamically via the Docker API.
"""

import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
import secrets as _secrets
from datetime import datetime
from urllib.parse import quote, urlparse

import aiofiles
from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import db
import docker_manager as dm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gridpaw-admin")

app = FastAPI(title="GridPaw Admin Service")

STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/admin/static", StaticFiles(directory=str(STATIC_DIR)), name="admin-static")

# ---------------------------------------------------------------------------
# Configuration — 由 .env 经 docker-compose 注入的可配置项
# ---------------------------------------------------------------------------

# 租户容器使用的 Docker 镜像名，须与 prepare.sh build 构建的镜像名一致（两者均从 .env 读取）。
# Nginx 对外端口，用于补充共享文件下载 URL 的端口部分。
_NGINX_PORT     = os.environ.get("NGINX_PORT", "")
# 租户容器使用的 Docker 镜像名，须与 prepare.sh build 构建的镜像名一致（两者均从 .env 读取）。
TENANT_IMAGE    = os.environ.get("TENANT_IMAGE", "gridpaw-tenant:latest")
# 宿主机上租户数据根目录，每台机器路径不同，用于构造容器 volume 挂载路径。
TENANTS_DATA_BASE_DIR = os.environ.get("TENANTS_DATA_BASE_DIR", "/var/gridpaw/tenants_data")
# 租户容器名前缀，容器名为 {INSTANCE_PREFIX}{user_id}（如 gridpaw-instance-zhangsan）。
INSTANCE_PREFIX = os.environ.get("INSTANCE_PREFIX", "gridpaw-instance-")
# 租户容器加入的 Docker 网络名，由 compose 直接注入（值由 compose 项目名 + 网络别名决定）。
# 若修改 docker-compose.yml 的 name: 或 networks: 字段，需同步更新此处默认值。
DOCKER_NETWORK  = os.environ.get("DOCKER_NETWORK", "gridpaw-multi-tenant-service_gridpaw-net")
# 共享文件服务对外访问的 scheme+host（如 http://192.168.1.10），用于拼接下载 URL。
_FILE_SERVICE_BASE_RAW = os.environ.get("FILE_SERVICE_BASE_URL", "").rstrip("/")
# 宿主机上 Admin 数据目录，用于错误提示中的路径说明（如模板目录位置）。
GRIDPAW_ADMIN_DATA_DIR = os.environ.get("GRIDPAW_ADMIN_DATA_DIR", "/root/var/gridpaw/admin_data")


# ---------------------------------------------------------------------------
# Configuration — 写死的固定值（容器内部结构决定，无需外部配置）
# ---------------------------------------------------------------------------

# 容器内文件路径（由镜像目录结构和 docker-compose volume 挂载决定，不随部署变化）
# 租户容器内部监听端口,与 nginx.conf proxy_pass 目标端口耦合，两者须始终保持一致。只在docker网络里可见，并未映射到宿主机端口，外部只能通过nginx的统一代理访问，无法直接访问。
TENANT_INTERNAL_PORT = 8088

TENANTS_ROOT     = Path("/app/tenants")                  # 租户数据挂载点（TENANTS_DATA_BASE_DIR 挂载到此）
SHARED_FILES_DATA_DIR = Path("/app/shared_files")             # 共享文件存放目录的挂载点,用于共享文件服务读写共享文件

DB_PATH        = Path("/app/data/db/admin.db")               # SQLite 数据库(GRIDPAW_ADMIN_DATA_DIR/db/)
TEMPLATES_ROOT = Path("/app/data/tenant_working_templates")  # 模板根目录，对标租户容器内 /app（智能体工作目录 /app/working 与 /app/working.secret 的父目录）
LOGIN_HTML     = Path("/app/admin-service/login.html")    # 用户登录页
ADMIN_HTML     = Path("/app/admin-service/admin.html")    # 管理面板页

# 管理员账号（内网部署，固定值）
ADMIN_USERNAME    = "admin"
ADMIN_PASSWORD    = "admin"
ADMIN_COOKIE_NAME = "gridpaw_admin_session"  # 管理员会话 Cookie 名

# 用户会话 Cookie 配置
# 登录成功后由 POST /auth/login 通过 response.set_cookie 写入浏览器，存签名后的 instance 名（如 gridpaw-instance-user1）。
# /auth/check 读取此 Cookie、校验后设置响应头 X-GridPaw-Instance，nginx auth_request 据此将请求转发到对应租户容器。
# 修改 COOKIE_NAME 或 /auth/check 的响应头名时，须同步修改 nginx.conf 中 auth_request_set 的 $upstream_http_x_gridpaw_instance。
COOKIE_NAME    = "gridpaw_instance"
COOKIE_SECRET  = _secrets.token_hex(32) # Cookie 签名密钥，每次启动随机生成。内网部署可接受；代价是重启后所有会话失效。
COOKIE_MAX_AGE = 86400                  # 用户会话 Cookie 有效期，24 小时

# ---------------------------------------------------------------------------
# Cookie helpers (shared between user auth and admin auth)
# ---------------------------------------------------------------------------

def _sign_cookie(value: str) -> str:
    ts = str(int(time.time()))
    payload = f"{value}.{ts}"
    sig = hmac.new(COOKIE_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}.{sig}"


def _verify_cookie(signed: str, max_age: int = COOKIE_MAX_AGE) -> str | None:
    parts = signed.split(".")
    if len(parts) != 3:
        return None
    value, ts, sig = parts
    payload = f"{value}.{ts}"
    expected = hmac.new(COOKIE_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        if time.time() - int(ts) > max_age:
            return None
    except ValueError:
        return None
    return value


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

# 租户数据库实例，在 startup 中初始化，之后在所有请求处理中复用。
tenant_db: db.TenantDB

@app.on_event("startup")
async def startup():
    global tenant_db
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)  # 确保 db 目录存在（SQLite 不创建父目录）
    TEMPLATES_ROOT.mkdir(parents=True, exist_ok=True)  # 确保模板根目录存在，便于首次部署
    tenant_db = db.TenantDB(db_path=DB_PATH, instance_prefix=INSTANCE_PREFIX, tenants_data_base_dir=TENANTS_DATA_BASE_DIR)
    dm.init_client()
    logger.info("Admin service started. DB: %s", DB_PATH)


# ===================================================================
# PART 1: User Authentication (consumed by nginx auth_request)
# ===================================================================

def _load_users() -> dict:
    """Build user lookup from SQLite."""
    tenants = tenant_db.get_all_tenants()
    users = {}
    for t in tenants:
        uid = t["user_id"]
        users[uid] = {
            "password": t["password"],
            "user_name": t["user_name"],
            "instance": f"{INSTANCE_PREFIX}{uid}",
        }
    return users


@app.get("/auth/login", response_class=HTMLResponse)
async def login_page():
    if LOGIN_HTML.exists():
        return HTMLResponse(LOGIN_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Login page not found</h1>", status_code=500)


@app.post("/auth/login")
async def login(username: str = Form(...), password: str = Form(...)):
    users = _load_users()
    user = users.get(username)
    if not user or user.get("password") != password:
        logger.warning("Failed login attempt for: %s", username)
        if LOGIN_HTML.exists():
            html = LOGIN_HTML.read_text(encoding="utf-8")
            html = html.replace(
                "<!-- ERROR_PLACEHOLDER -->",
                '<p class="error">用户名或密码错误</p>',
            )
            return HTMLResponse(html, status_code=401)
        return HTMLResponse("<h1>用户名或密码错误</h1>", status_code=401)

    instance = user["instance"]
    logger.info("User %s logged in -> %s", username, instance)
    signed = _sign_cookie(instance)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        key=COOKIE_NAME, value=signed, max_age=COOKIE_MAX_AGE,
        httponly=True, samesite="lax", path="/",
    )
    return response


@app.get("/auth/logout")
async def logout():
    response = RedirectResponse("/auth/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@app.get("/auth/check")
async def check(request: Request):
    """Nginx auth_request subrequest endpoint."""
    cookie = request.cookies.get(COOKIE_NAME, "")
    instance = _verify_cookie(cookie) if cookie else None
    if instance:
        response = Response(status_code=200)
        response.headers["X-GridPaw-Instance"] = instance
        return response
    return Response(status_code=401)


@app.get("/auth/whoami")
async def whoami(request: Request):
    cookie = request.cookies.get(COOKIE_NAME, "")
    instance = _verify_cookie(cookie) if cookie else None
    if not instance:
        return {"logged_in": False}
    users = _load_users()
    for uid, uinfo in users.items():
        if uinfo.get("instance") == instance:
            return {
                "logged_in": True,
                "user_id": uid,
                "user_name": uinfo.get("user_name", uid),
                "instance": instance,
            }
    return {"logged_in": True, "instance": instance}


# ===================================================================
# PART 2: Admin Authentication
# ===================================================================

def _verify_admin(request: Request) -> bool:
    cookie = request.cookies.get(ADMIN_COOKIE_NAME, "")
    if not cookie:
        return False
    value = _verify_cookie(cookie)
    return value == "admin_authenticated"


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    if _verify_admin(request):
        return RedirectResponse("/admin/", status_code=303)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>GridPaw 管理后台 - 登录</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{min-height:100vh;display:flex;align-items:center;justify-content:center;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
background:linear-gradient(135deg,#0f172a 0%,#1e293b 50%,#0f172a 100%);color:#e2e8f0}}
.login-container{{width:100%;max-width:400px;padding:2.5rem;
background:rgba(30,41,59,0.8);border:1px solid rgba(100,116,139,0.3);
border-radius:12px;backdrop-filter:blur(20px);box-shadow:0 25px 50px -12px rgba(0,0,0,0.5)}}
.login-header{{text-align:center;margin-bottom:2rem}}
.login-header h1{{font-size:1.5rem;font-weight:600;color:#f1f5f9;margin-bottom:0.5rem}}
.login-header p{{font-size:0.875rem;color:#94a3b8}}
.form-group{{margin-bottom:1.25rem}}
.form-group label{{display:block;font-size:0.875rem;font-weight:500;color:#cbd5e1;margin-bottom:0.5rem}}
.form-group input{{width:100%;padding:0.75rem 1rem;font-size:0.9375rem;color:#f1f5f9;
background:rgba(15,23,42,0.6);border:1px solid rgba(100,116,139,0.4);border-radius:8px;outline:none;
transition:border-color 0.2s}}
.form-group input:focus{{border-color:#3b82f6;box-shadow:0 0 0 3px rgba(59,130,246,0.15)}}
.login-btn{{width:100%;padding:0.75rem;font-size:0.9375rem;font-weight:600;color:#fff;
background:#3b82f6;border:none;border-radius:8px;cursor:pointer;transition:background 0.2s;margin-top:0.5rem}}
.login-btn:hover{{background:#2563eb}}
.error{{text-align:center;color:#f87171;font-size:0.875rem;margin-bottom:1rem;padding:0.5rem;
background:rgba(248,113,113,0.1);border-radius:6px}}
</style>
</head>
<body>
<div class="login-container">
<div class="login-header"><h1>GridPaw 管理后台</h1><p>请输入管理员账号登录</p></div>
<!-- ERROR_PLACEHOLDER -->
<form action="/admin/login" method="POST">
<div class="form-group"><label for="username">用户名</label>
<input type="text" id="username" name="username" placeholder="admin" required autofocus></div>
<div class="form-group"><label for="password">密码</label>
<input type="password" id="password" name="password" placeholder="请输入密码" required></div>
<button type="submit" class="login-btn">登 录</button>
</form>
</div>
</body>
</html>"""
    return HTMLResponse(html)


@app.post("/admin/login")
async def admin_login(username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        logger.info("Admin logged in")
        signed = _sign_cookie("admin_authenticated")
        response = RedirectResponse("/admin/", status_code=303)
        response.set_cookie(
            key=ADMIN_COOKIE_NAME, value=signed, max_age=COOKIE_MAX_AGE,
            httponly=True, samesite="lax", path="/admin",
        )
        return response

    logger.warning("Failed admin login: %s", username)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>GridPaw 管理后台 - 登录</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{min-height:100vh;display:flex;align-items:center;justify-content:center;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
background:linear-gradient(135deg,#0f172a 0%,#1e293b 50%,#0f172a 100%);color:#e2e8f0}}
.login-container{{width:100%;max-width:400px;padding:2.5rem;
background:rgba(30,41,59,0.8);border:1px solid rgba(100,116,139,0.3);
border-radius:12px;backdrop-filter:blur(20px);box-shadow:0 25px 50px -12px rgba(0,0,0,0.5)}}
.login-header{{text-align:center;margin-bottom:2rem}}
.login-header h1{{font-size:1.5rem;font-weight:600;color:#f1f5f9;margin-bottom:0.5rem}}
.login-header p{{font-size:0.875rem;color:#94a3b8}}
.form-group{{margin-bottom:1.25rem}}
.form-group label{{display:block;font-size:0.875rem;font-weight:500;color:#cbd5e1;margin-bottom:0.5rem}}
.form-group input{{width:100%;padding:0.75rem 1rem;font-size:0.9375rem;color:#f1f5f9;
background:rgba(15,23,42,0.6);border:1px solid rgba(100,116,139,0.4);border-radius:8px;outline:none;
transition:border-color 0.2s}}
.form-group input:focus{{border-color:#3b82f6;box-shadow:0 0 0 3px rgba(59,130,246,0.15)}}
.login-btn{{width:100%;padding:0.75rem;font-size:0.9375rem;font-weight:600;color:#fff;
background:#3b82f6;border:none;border-radius:8px;cursor:pointer;transition:background 0.2s;margin-top:0.5rem}}
.login-btn:hover{{background:#2563eb}}
.error{{text-align:center;color:#f87171;font-size:0.875rem;margin-bottom:1rem;padding:0.5rem;
background:rgba(248,113,113,0.1);border-radius:6px}}
</style></head><body>
<div class="login-container">
<div class="login-header"><h1>GridPaw 管理后台</h1><p>请输入管理员账号登录</p></div>
<p class="error">用户名或密码错误</p>
<form action="/admin/login" method="POST">
<div class="form-group"><label for="username">用户名</label>
<input type="text" id="username" name="username" placeholder="admin" required autofocus></div>
<div class="form-group"><label for="password">密码</label>
<input type="password" id="password" name="password" placeholder="请输入密码" required></div>
<button type="submit" class="login-btn">登 录</button>
</form>
</div></body></html>"""
    return HTMLResponse(html, status_code=401)


@app.get("/admin/logout")
async def admin_logout():
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(ADMIN_COOKIE_NAME, path="/admin")
    return response


@app.get("/admin/impersonate/{user_id}")
async def admin_impersonate(user_id: str, request: Request):
    """管理员代为登录：在新标签页以指定租户身份打开 GridPaw 页面。"""
    if not _verify_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    tenant = tenant_db.get_tenant(user_id)
    if not tenant:
        return HTMLResponse(
            f"<h1>租户不存在</h1><p>user_id: {user_id}</p><a href='/admin/'>返回管理</a>",
            status_code=404,
        )
    instance = f"{INSTANCE_PREFIX}{user_id}"
    signed = _sign_cookie(instance)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        key=COOKIE_NAME, value=signed, max_age=COOKIE_MAX_AGE,
        httponly=True, samesite="lax", path="/",
    )
    logger.info("Admin impersonating tenant: %s -> %s", user_id, instance)
    return response


# ===================================================================
# PART 3: Admin Management Page
# ===================================================================

@app.get("/admin/", response_class=HTMLResponse)
async def admin_page(request: Request):
    if not _verify_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    if ADMIN_HTML.exists():
        return HTMLResponse(ADMIN_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Admin page not found</h1>", status_code=500)


# ===================================================================
# PART 4: Admin API — Tenant CRUD
# ===================================================================

def _require_admin(request: Request) -> JSONResponse | None:
    """Return a 401 JSONResponse if not admin, else None."""
    if not _verify_admin(request):
        return JSONResponse({"error": "未登录管理后台"}, status_code=401)
    return None


@app.get("/admin/api/tenants")
async def api_list_tenants(request: Request):
    denied = _require_admin(request)
    if denied:
        return denied

    tenants = tenant_db.get_all_tenants()
    statuses = dm.get_all_instance_statuses(prefix=INSTANCE_PREFIX)

    result = []
    for t in tenants:
        uid = t["user_id"]
        container_name = f"{INSTANCE_PREFIX}{uid}"
        container_info = statuses.get(container_name, {"status": "not_found", "running_for": ""})
        result.append({
            "user_id": uid,
            "user_name": t["user_name"],
            "env": t.get("env", {}),
            "created_at": t.get("created_at", ""),
            "updated_at": t.get("updated_at", ""),
            "container": container_info,
        })

    return {"tenants": result, "config": {"instance_prefix": INSTANCE_PREFIX}}


@app.get("/admin/api/tenants/{user_id}")
async def api_get_tenant(user_id: str, request: Request):
    """Get full tenant details for edit form.
    Returns instance_info (actual running container) and instance_config (DB record).
    """
    denied = _require_admin(request)
    if denied:
        return denied

    tenant = tenant_db.get_tenant(user_id)
    if not tenant:
        return JSONResponse({"error": f"租户 '{user_id}' 不存在"}, status_code=404)

    # 优先使用数据库中的值，否则按约定计算
    container_name = tenant.get("container_name") or f"{INSTANCE_PREFIX}{user_id}"
    default_mounts = tenant.get("default_mounts") or [
        {"host": f"{TENANTS_DATA_BASE_DIR}/{user_id}/working", "bind": "/app/working", "mode": "rw"},
        {"host": f"{TENANTS_DATA_BASE_DIR}/{user_id}/working.secret", "bind": "/app/working.secret", "mode": "rw"},
    ]
    default_mount_host = default_mounts[0].get("host", "") if default_mounts else ""
    extra_mounts = tenant.get("extra_mounts", [])

    # 实例信息：从实际运行的容器获取
    runtime = dm.get_container_runtime_config(container_name)
    instance_info = {"running": runtime is not None}
    if runtime:
        instance_info["container_name"] = runtime["container_name"]
        instance_info["mounts"] = runtime["mounts"]
    else:
        instance_info["container_name"] = None
        instance_info["mounts"] = []

    # 实例配置：数据库记录
    instance_config = {
        "container_name": container_name,
        "default_mounts": default_mounts,
        "extra_mounts": extra_mounts,
    }

    return {
        "user_id": tenant["user_id"],
        "user_name": tenant["user_name"],
        "password": tenant.get("password", ""),
        "env": tenant.get("env", {}),
        "instance_info": instance_info,
        "instance_config": instance_config,
        "extra_mounts": extra_mounts,
        "default_mount_host": default_mount_host,
    }


@app.post("/admin/api/tenants")
async def api_add_tenant(request: Request):
    denied = _require_admin(request)
    if denied:
        return denied

    body = await request.json()
    uid = body.get("user_id", "").strip()
    uname = body.get("user_name", "")
    pw = body.get("password", "")
    env = body.get("env")
    extra_mounts = body.get("extra_mounts")

    ok, msg = tenant_db.add_tenant(uid, uname, pw, env, extra_mounts)
    if ok:
        return {"ok": True, "message": f"租户 '{uid}' 创建成功"}
    return JSONResponse({"ok": False, "message": msg}, status_code=400)


@app.put("/admin/api/tenants/{user_id}")
async def api_update_tenant(user_id: str, request: Request):
    denied = _require_admin(request)
    if denied:
        return denied

    body = await request.json()
    ok, msg = tenant_db.update_tenant(
        user_id,
        user_name=body.get("user_name"),
        password=body.get("password"),
        env=body.get("env"),
        extra_mounts=body.get("extra_mounts") if "extra_mounts" in body else None,
    )
    if ok:
        return {"ok": True, "message": f"租户 '{user_id}' 更新成功"}
    return JSONResponse({"ok": False, "message": msg}, status_code=400)


@app.delete("/admin/api/tenants/{user_id}")
async def api_delete_tenant(user_id: str, request: Request):
    denied = _require_admin(request)
    if denied:
        return denied

    container_name = f"{INSTANCE_PREFIX}{user_id}"
    dm.stop_container(container_name)
    dm.remove_container(container_name)

    ok, msg = tenant_db.delete_tenant(user_id)
    if ok:
        return {"ok": True, "message": f"租户 '{user_id}' 已删除（容器已清理）"}
    return JSONResponse({"ok": False, "message": msg}, status_code=400)


@app.post("/admin/api/tenants/import")
async def api_import_tenants(request: Request):
    denied = _require_admin(request)
    if denied:
        return denied

    body = await request.json()
    tenant_list = body.get("tenants", [])
    if not isinstance(tenant_list, list):
        return JSONResponse({"ok": False, "message": "tenants 必须是数组"}, status_code=400)

    count, errors = tenant_db.import_tenants(tenant_list)
    return {
        "ok": True,
        "imported": count,
        "errors": errors,
        "message": f"成功导入 {count} 个租户" + (f"，{len(errors)} 个失败" if errors else ""),
    }


# ===================================================================
# PART 5: Admin API — Container Operations
# ===================================================================

@app.post("/admin/api/containers/{user_id}/start")
async def api_start_container(user_id: str, request: Request):
    denied = _require_admin(request)
    if denied:
        return denied

    tenant = tenant_db.get_tenant(user_id)
    if not tenant:
        return JSONResponse({"ok": False, "message": f"租户 '{user_id}' 不存在"}, status_code=404)

    container_name = f"{INSTANCE_PREFIX}{user_id}"
    env = {"COPAW_PORT": str(TENANT_INTERNAL_PORT)}
    if tenant.get("env"):
        env.update(tenant["env"])
    extra_mounts = tenant.get("extra_mounts") or []

    ok, msg = dm.create_and_start_container(
        container_name=container_name,
        image=TENANT_IMAGE,
        data_dir=f"{TENANTS_DATA_BASE_DIR}/{user_id}/working",
        port=TENANT_INTERNAL_PORT,
        network=DOCKER_NETWORK,
        env=env,
        extra_volumes=extra_mounts,
        force_recreate=True,
        secret_dir=f"{TENANTS_DATA_BASE_DIR}/{user_id}/working.secret",
    )
    if ok:
        return {"ok": True, "message": f"容器 '{container_name}' 已启动"}
    return JSONResponse({"ok": False, "message": msg}, status_code=400)


@app.post("/admin/api/containers/{user_id}/stop")
async def api_stop_container(user_id: str, request: Request):
    denied = _require_admin(request)
    if denied:
        return denied

    container_name = f"{INSTANCE_PREFIX}{user_id}"
    ok, msg = dm.stop_container(container_name)
    if ok:
        return {"ok": True, "message": f"容器 '{container_name}' 已停止"}
    return JSONResponse({"ok": False, "message": msg}, status_code=400)


@app.post("/admin/api/containers/{user_id}/restart")
async def api_restart_container(user_id: str, request: Request):
    """Restart container. Recreates container to apply latest config (env, extra_mounts)."""
    denied = _require_admin(request)
    if denied:
        return denied

    tenant = tenant_db.get_tenant(user_id)
    if not tenant:
        return JSONResponse({"ok": False, "message": f"租户 '{user_id}' 不存在"}, status_code=404)

    container_name = f"{INSTANCE_PREFIX}{user_id}"
    env = {"COPAW_PORT": str(TENANT_INTERNAL_PORT)}
    if tenant.get("env"):
        env.update(tenant["env"])
    extra_mounts = tenant.get("extra_mounts") or []

    ok, msg = dm.create_and_start_container(
        container_name=container_name,
        image=TENANT_IMAGE,
        data_dir=f"{TENANTS_DATA_BASE_DIR}/{user_id}/working",
        port=TENANT_INTERNAL_PORT,
        network=DOCKER_NETWORK,
        env=env,
        extra_volumes=extra_mounts,
        force_recreate=True,
        secret_dir=f"{TENANTS_DATA_BASE_DIR}/{user_id}/working.secret",
    )
    if ok:
        return {"ok": True, "message": f"容器 '{container_name}' 已重建"}
    return JSONResponse({"ok": False, "message": msg}, status_code=400)


@app.post("/admin/api/containers/{user_id}/remove")
async def api_remove_container(user_id: str, request: Request):
    """Remove container only (does not delete tenant). Container must be stopped first."""
    denied = _require_admin(request)
    if denied:
        return denied

    container_name = f"{INSTANCE_PREFIX}{user_id}"
    ok, msg = dm.stop_container(container_name)
    if not ok:
        return JSONResponse({"ok": False, "message": msg}, status_code=400)
    ok, msg = dm.remove_container(container_name)
    if ok:
        return {"ok": True, "message": f"容器 '{container_name}' 已删除"}
    return JSONResponse({"ok": False, "message": msg}, status_code=400)


@app.get("/admin/api/containers/{user_id}/logs")
async def api_container_logs(user_id: str, request: Request):
    denied = _require_admin(request)
    if denied:
        return denied

    container_name = f"{INSTANCE_PREFIX}{user_id}"
    tail = int(request.query_params.get("tail", "200"))
    ok, logs = dm.get_container_logs(container_name, tail=tail)
    if ok:
        return {"ok": True, "logs": logs}
    return JSONResponse({"ok": False, "message": logs}, status_code=400)


@app.post("/admin/api/containers/batch")
async def api_batch_containers(request: Request):
    denied = _require_admin(request)
    if denied:
        return denied

    body = await request.json()
    action = body.get("action", "")
    user_ids = body.get("user_ids", [])

    if action not in ("start", "stop", "restart"):
        return JSONResponse({"ok": False, "message": "action 必须是 start、stop 或 restart"}, status_code=400)
    if not user_ids:
        return JSONResponse({"ok": False, "message": "user_ids 不能为空"}, status_code=400)

    results = []
    for uid in user_ids:
        container_name = f"{INSTANCE_PREFIX}{uid}"
        if action == "start":
            tenant = tenant_db.get_tenant(uid)
            if not tenant:
                results.append({"user_id": uid, "ok": False, "message": f"租户 '{uid}' 不存在"})
                continue
            env = {"COPAW_PORT": str(TENANT_INTERNAL_PORT)}
            if tenant.get("env"):
                env.update(tenant["env"])
            extra_mounts = tenant.get("extra_mounts") or []
            ok, msg = dm.create_and_start_container(
                container_name=container_name, image=TENANT_IMAGE,
                data_dir=f"{TENANTS_DATA_BASE_DIR}/{uid}/working", port=TENANT_INTERNAL_PORT,
                network=DOCKER_NETWORK, env=env, extra_volumes=extra_mounts,
                secret_dir=f"{TENANTS_DATA_BASE_DIR}/{uid}/working.secret",
            )
        elif action == "restart":
            tenant = tenant_db.get_tenant(uid)
            if not tenant:
                results.append({"user_id": uid, "ok": False, "message": f"租户 '{uid}' 不存在"})
                continue
            env = {"COPAW_PORT": str(TENANT_INTERNAL_PORT)}
            if tenant.get("env"):
                env.update(tenant["env"])
            extra_mounts = tenant.get("extra_mounts") or []
            ok, msg = dm.create_and_start_container(
                container_name=container_name, image=TENANT_IMAGE,
                data_dir=f"{TENANTS_DATA_BASE_DIR}/{uid}/working", port=TENANT_INTERNAL_PORT,
                network=DOCKER_NETWORK, env=env, extra_volumes=extra_mounts,
                force_recreate=True,
                secret_dir=f"{TENANTS_DATA_BASE_DIR}/{uid}/working.secret",
            )
        else:
            ok, msg = dm.stop_container(container_name)
        results.append({"user_id": uid, "ok": ok, "message": msg})

    return {"ok": True, "results": results}


# ===================================================================
# PART 6: Admin API — Template Distribution
# ===================================================================

# 快捷分发预设：每个预设对应模板内要分发的相对路径。目标为各租户 working.secret。
PRESET_PATHS = {
    "llm_config": ["working.secret/providers.json"],
    "env_vars": ["working.secret/envs.json"],
}


def _get_template_secret_dir_hint() -> str:
    """返回模板 working.secret 的宿主机路径提示，用于错误信息。"""
    return f"{GRIDPAW_ADMIN_DATA_DIR.rstrip('/')}/tenant_working_templates/working.secret/"


def _validate_preset_files(preset_paths: list[str]) -> tuple[bool, str]:
    """
    校验预设路径对应的源文件均存在。
    返回 (ok, error_message)。ok 为 True 时 error_message 为空。
    """
    missing = []
    for rel in preset_paths:
        full = TEMPLATES_ROOT / rel
        if not full.exists() or not full.is_file():
            missing.append(rel.split("/")[-1])
    if not missing:
        return True, ""
    hint = _get_template_secret_dir_hint()
    files_str = "、".join(sorted(set(missing)))
    return False, (
        f"模板目录下缺少以下文件: {files_str}。"
        f"请在目录 {hint} 下创建并填写这些文件。"
    )


def _build_tree_node(p: Path, rel_path: str) -> dict:
    """递归构建目录树节点，path 为相对于 TEMPLATES_ROOT 的路径。"""
    name = p.name or TEMPLATES_ROOT.name
    is_dir = p.is_dir()
    node = {"name": name, "path": rel_path, "is_dir": is_dir}
    if is_dir:
        node["children"] = []
        for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            child_rel = f"{rel_path}/{child.name}" if rel_path else child.name
            node["children"].append(_build_tree_node(child, child_rel))
    return node


def _is_path_safe(rel_path: str) -> bool:
    """校验相对路径在模板根内，禁止 .. 等穿越。"""
    if not rel_path:
        return True
    parts = Path(rel_path).parts
    if ".." in parts or rel_path.startswith("/"):
        return False
    resolved = (TEMPLATES_ROOT / rel_path).resolve()
    return str(resolved).startswith(str(TEMPLATES_ROOT.resolve()))


def _expand_paths(paths: list[str]) -> list[str]:
    """将选中的路径展开为所有要复制的项（勾选目录则递归包含其下所有内容）。"""
    seen = set()
    result = []
    for rel in paths:
        if not rel or rel in seen:
            continue
        full = TEMPLATES_ROOT / rel
        if not full.exists():
            continue
        if full.is_file():
            if rel not in seen:
                seen.add(rel)
                result.append(rel)
        else:
            for f in full.rglob("*"):
                if f.is_file():
                    r = str(f.relative_to(TEMPLATES_ROOT)).replace("\\", "/")
                    if r not in seen:
                        seen.add(r)
                        result.append(r)
    return result


@app.get("/admin/api/templates/tree")
async def api_templates_tree(request: Request):
    """获取模板目录完整树结构，一次性返回。"""
    denied = _require_admin(request)
    if denied:
        return denied

    if not TEMPLATES_ROOT.is_dir():
        return {"ok": False, "error": f"模板目录不存在: {TEMPLATES_ROOT}", "tree": None}

    root_node = _build_tree_node(TEMPLATES_ROOT, "")
    return {"ok": True, "tree": root_node}


@app.post("/admin/api/distribute")
async def api_distribute(request: Request):
    """将选中的模板文件/目录分发到各租户。勾选目录即递归包含其下所有内容，覆盖已存在文件。
    支持 presets 快捷分发：llm_config（envs.json+providers.json）、env_vars（envs.json）。
    """
    denied = _require_admin(request)
    if denied:
        return denied

    body = await request.json()
    tenant_ids = body.get("tenant_ids", [])
    paths = list(body.get("paths", []))
    presets = body.get("presets", [])

    # 将预设路径合并到 paths（去重）
    preset_paths = []
    for preset_id in presets:
        if preset_id in PRESET_PATHS:
            for rel in PRESET_PATHS[preset_id]:
                if rel not in paths:
                    paths.append(rel)
                if rel not in preset_paths:
                    preset_paths.append(rel)

    if not tenant_ids:
        return JSONResponse({"ok": False, "message": "tenant_ids 不能为空"}, status_code=400)
    if not paths:
        return JSONResponse({"ok": False, "message": "请至少选择一个文件或目录（含快捷分发）"}, status_code=400)

    # 校验路径安全
    for p in paths:
        if not _is_path_safe(p):
            return JSONResponse({"ok": False, "message": f"非法路径: {p}"}, status_code=400)

    # 校验预设文件存在（快捷分发选中的文件必须在模板中存在）
    if preset_paths:
        ok_val, err_msg = _validate_preset_files(preset_paths)
        if not ok_val:
            return JSONResponse({"ok": False, "message": err_msg}, status_code=400)

    # 校验租户存在
    all_tenants = {t["user_id"]: t for t in tenant_db.get_all_tenants()}
    for uid in tenant_ids:
        if uid not in all_tenants:
            return JSONResponse({"ok": False, "message": f"租户 '{uid}' 不存在"}, status_code=400)

    # 展开路径（目录 → 其下所有文件）
    expanded = _expand_paths(paths)
    if not expanded:
        return JSONResponse({"ok": False, "message": "选中的路径中无有效文件"}, status_code=400)

    results = []
    for uid in tenant_ids:
        tenant_dir = TENANTS_ROOT / uid
        tenant_dir.mkdir(parents=True, exist_ok=True)
        ok_count, fail_count = 0, 0
        err_msg = ""
        for rel in expanded:
            src = TEMPLATES_ROOT / rel
            dst = tenant_dir / rel
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_file():
                    shutil.copy(src, dst)  # 不保留原时间戳，使用分发时时间
                    ok_count += 1
                else:
                    shutil.copytree(src, dst, dirs_exist_ok=True, copy_function=shutil.copy)  # 同上
                    ok_count += 1
            except Exception as e:
                fail_count += 1
                err_msg = str(e)
                logger.warning("Distribute failed %s -> %s: %s", src, dst, e)
        results.append({
            "user_id": uid,
            "ok": fail_count == 0,
            "ok_count": ok_count,
            "fail_count": fail_count,
            "message": err_msg or f"已分发 {ok_count} 项",
        })

    return {"ok": True, "results": results}


# ===================================================================
# PART 7: Shared File Service
# ===================================================================
#
# 供 GridPaw 工具、外部服务（如潮流计算）写入大文件，前端可读取用于展示。
# 文件按日期存储：{SHARED_FILES_DATA_DIR}/YYYYMMDD/{path}，日期由服务自动添加。
# 支持 JSON 写入（文本）和 multipart 写入（任意文件含二进制）。
# 以下代码块可整体定位为「共享文件服务」。
# ===================================================================


def _is_shared_file_path_safe(path: str) -> bool:
    """校验工具提供的 path：禁止 .. 与绝对路径，仅允许安全字符。"""
    if not path or len(path) > 512:
        return False
    if ".." in path or path.startswith("/") or path.startswith("\\"):
        return False
    if re.search(r"[^\w\-. /]", path):
        return False
    return True


def _build_shared_file_full_path(path: str) -> Path:
    """构建完整存储路径：{root}/YYYYMMDD/{path}"""
    date_dir = datetime.now().strftime("%Y%m%d")
    # 规范化 path，移除首尾空格和多余斜杠
    clean_path = path.strip().strip("/").replace("\\", "/")
    rel = f"{date_dir}/{clean_path}" if clean_path else date_dir
    return (SHARED_FILES_DATA_DIR / rel).resolve()


def _ensure_resolved_under_root(resolved: Path) -> bool:
    """确保解析后路径在 SHARED_FILES_DATA_DIR 之下。"""
    root = SHARED_FILES_DATA_DIR.resolve()
    return str(resolved).startswith(str(root))


def _get_file_service_base_url() -> str:
    """
    构建共享文件服务的 Base URL，端口自动从 NGINX_PORT 补充。
    FILE_SERVICE_BASE_URL 只需填 scheme+host，如 http://127.0.0.1，无需写端口。
    """
    base = _FILE_SERVICE_BASE_RAW
    if not base:
        return ""
    try:
        port_num = int(_NGINX_PORT)
    except (ValueError, TypeError):
        return base
    p = urlparse(base)
    if not p.scheme or not p.hostname:
        return base
    default_port = 443 if p.scheme == "https" else 80
    if port_num != default_port:
        return f"{p.scheme}://{p.hostname}:{port_num}"
    return base


# -----------------------------------------------------------------------
# Shared File Service - Write (JSON or multipart)
# -----------------------------------------------------------------------

@app.post("/share_files/write")
async def shared_files_write(request: Request):
    """
    写入文件到共享存储。
    - JSON: {"path": "query_load_data_tool/abc.json", "content": "..."}
    - Multipart: path (form) + file (form)
    返回完整 URL。
    """
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception as e:
            return JSONResponse(
                {"success": False, "error": f"JSON 解析失败: {e}"},
                status_code=400,
            )
        path = body.get("path")
        content = body.get("content")
        if not path:
            return JSONResponse(
                {"success": False, "error": "缺少 path"},
                status_code=400,
            )
        if content is None:
            return JSONResponse(
                {"success": False, "error": "缺少 content"},
                status_code=400,
            )
        if not _is_shared_file_path_safe(path):
            return JSONResponse(
                {"success": False, "error": "path 非法"},
                status_code=400,
            )

        full_path = _build_shared_file_full_path(path)
        if not _ensure_resolved_under_root(full_path):
            return JSONResponse(
                {"success": False, "error": "path 非法"},
                status_code=400,
            )

        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                await f.write(content if isinstance(content, str) else str(content))
        except Exception as e:
            logger.exception("Shared file write failed: %s", e)
            return JSONResponse(
                {"success": False, "error": f"写入失败: {e}"},
                status_code=500,
            )

    elif "multipart/form-data" in content_type:
        form = await request.form()
        path = form.get("path")
        file = form.get("file")
        if not path:
            return JSONResponse(
                {"success": False, "error": "缺少 path"},
                status_code=400,
            )
        if not file or not hasattr(file, "read"):
            return JSONResponse(
                {"success": False, "error": "缺少 file 字段"},
                status_code=400,
            )
        path_str = path if isinstance(path, str) else str(path)
        if not _is_shared_file_path_safe(path_str):
            return JSONResponse(
                {"success": False, "error": "path 非法"},
                status_code=400,
            )

        full_path = _build_shared_file_full_path(path_str)
        if not _ensure_resolved_under_root(full_path):
            return JSONResponse(
                {"success": False, "error": "path 非法"},
                status_code=400,
            )

        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(full_path, "wb") as f:
                while chunk := await file.read(65536):
                    await f.write(chunk)
        except Exception as e:
            logger.exception("Shared file write (multipart) failed: %s", e)
            return JSONResponse(
                {"success": False, "error": f"写入失败: {e}"},
                status_code=500,
            )

    else:
        return JSONResponse(
            {"success": False, "error": "Content-Type 需为 application/json 或 multipart/form-data"},
            status_code=400,
        )

    # 构建相对 path（用于 URL 路径）与完整 URL（端口自动从 NGINX_PORT 补充）
    rel_path = str(full_path.relative_to(SHARED_FILES_DATA_DIR)).replace("\\", "/")
    encoded = quote(rel_path, safe="/")
    base = _get_file_service_base_url()
    full_url = f"{base}/share_files/{encoded}" if base else f"/share_files/{encoded}"
    return {
        "success": True,
        "url": full_url,
        "path": rel_path,
    }


# -----------------------------------------------------------------------
# Shared File Service - Read (stream file)
# -----------------------------------------------------------------------

@app.get("/share_files/{file_path:path}")
async def shared_files_read(file_path: str):
    """
    读取共享文件。path 格式：YYYYMMDD/xxx/yyy.ext
    """
    if not file_path:
        return JSONResponse({"error": "缺少路径"}, status_code=400)
    if ".." in file_path or file_path.startswith("/") or file_path.startswith("\\"):
        return JSONResponse({"error": "path 非法"}, status_code=400)

    full_path = (SHARED_FILES_DATA_DIR / file_path).resolve()
    if not _ensure_resolved_under_root(full_path):
        return JSONResponse({"error": "path 非法"}, status_code=400)
    if not full_path.is_file():
        return JSONResponse({"error": "文件不存在"}, status_code=404)

    return FileResponse(str(full_path))
