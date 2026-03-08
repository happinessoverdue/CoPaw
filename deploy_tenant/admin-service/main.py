"""CoPaw multi-tenant admin service.

Combines authentication gateway (for CoPaw users) and management API
(for administrators). Tenant data is stored in SQLite; CoPaw containers
are managed dynamically via the Docker API.
"""

import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import db
import docker_manager as dm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("copaw-admin")

app = FastAPI(title="CoPaw Admin Service")

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

LOGIN_HTML = Path(os.environ.get("LOGIN_HTML", "/app/login.html"))
ADMIN_HTML = Path(os.environ.get("ADMIN_HTML", "/app/admin.html"))
COOKIE_SECRET = os.environ.get("COOKIE_SECRET", "CHANGE_ME_TO_A_RANDOM_STRING")
COOKIE_NAME = "copaw_instance"
COOKIE_MAX_AGE = int(os.environ.get("COOKIE_MAX_AGE", "86400"))

ADMIN_COOKIE_NAME = "copaw_admin_session"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")

COPAW_IMAGE = os.environ.get("COPAW_IMAGE", "copaw-ampere:latest")
BASE_DATA_DIR = os.environ.get("BASE_DATA_DIR", "/data/copaw")
COPAW_INTERNAL_PORT = int(os.environ.get("COPAW_INTERNAL_PORT", "8088"))
DOCKER_NETWORK = os.environ.get("DOCKER_NETWORK", "copaw-multi-tenant-service_copaw-net")

INSTANCE_PREFIX = "copaw-instance-"


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

@app.on_event("startup")
async def startup():
    db.init_db()
    dm.init_client()
    logger.info("Admin service started. DB: %s", db.DB_PATH)


# ===================================================================
# PART 1: User Authentication (consumed by nginx auth_request)
# ===================================================================

def _load_users() -> dict:
    """Build user lookup from SQLite."""
    tenants = db.get_all_tenants()
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
        response.headers["X-CoPaw-Instance"] = instance
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
<title>CoPaw 管理后台 - 登录</title>
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
<div class="login-header"><h1>CoPaw 管理后台</h1><p>请输入管理员账号登录</p></div>
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
<title>CoPaw 管理后台 - 登录</title>
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
<div class="login-header"><h1>CoPaw 管理后台</h1><p>请输入管理员账号登录</p></div>
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

    tenants = db.get_all_tenants()
    statuses = dm.get_all_instance_statuses()

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

    return {"tenants": result}


@app.post("/admin/api/tenants")
async def api_add_tenant(request: Request):
    denied = _require_admin(request)
    if denied:
        return denied

    body = await request.json()
    uid = body.get("user_id", "")
    uname = body.get("user_name", "")
    pw = body.get("password", "")
    env = body.get("env")

    ok, msg = db.add_tenant(uid, uname, pw, env)
    if ok:
        return {"ok": True, "message": f"租户 '{uid}' 创建成功"}
    return JSONResponse({"ok": False, "message": msg}, status_code=400)


@app.put("/admin/api/tenants/{user_id}")
async def api_update_tenant(user_id: str, request: Request):
    denied = _require_admin(request)
    if denied:
        return denied

    body = await request.json()
    ok, msg = db.update_tenant(
        user_id,
        user_name=body.get("user_name"),
        password=body.get("password"),
        env=body.get("env"),
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

    ok, msg = db.delete_tenant(user_id)
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

    count, errors = db.import_tenants(tenant_list)
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

    tenant = db.get_tenant(user_id)
    if not tenant:
        return JSONResponse({"ok": False, "message": f"租户 '{user_id}' 不存在"}, status_code=404)

    container_name = f"{INSTANCE_PREFIX}{user_id}"
    env = {"COPAW_PORT": str(COPAW_INTERNAL_PORT)}
    if tenant.get("env"):
        env.update(tenant["env"])

    ok, msg = dm.create_and_start_container(
        container_name=container_name,
        image=COPAW_IMAGE,
        data_dir=f"{BASE_DATA_DIR}/{user_id}",
        port=COPAW_INTERNAL_PORT,
        network=DOCKER_NETWORK,
        env=env,
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
    denied = _require_admin(request)
    if denied:
        return denied

    container_name = f"{INSTANCE_PREFIX}{user_id}"
    ok, msg = dm.restart_container(container_name)
    if ok:
        return {"ok": True, "message": f"容器 '{container_name}' 已重启"}
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

    if action not in ("start", "stop"):
        return JSONResponse({"ok": False, "message": "action 必须是 start 或 stop"}, status_code=400)
    if not user_ids:
        return JSONResponse({"ok": False, "message": "user_ids 不能为空"}, status_code=400)

    results = []
    for uid in user_ids:
        container_name = f"{INSTANCE_PREFIX}{uid}"
        if action == "start":
            tenant = db.get_tenant(uid)
            if not tenant:
                results.append({"user_id": uid, "ok": False, "message": f"租户 '{uid}' 不存在"})
                continue
            env = {"COPAW_PORT": str(COPAW_INTERNAL_PORT)}
            if tenant.get("env"):
                env.update(tenant["env"])
            ok, msg = dm.create_and_start_container(
                container_name=container_name, image=COPAW_IMAGE,
                data_dir=f"{BASE_DATA_DIR}/{uid}", port=COPAW_INTERNAL_PORT,
                network=DOCKER_NETWORK, env=env,
            )
        else:
            ok, msg = dm.stop_container(container_name)
        results.append({"user_id": uid, "ok": ok, "message": msg})

    return {"ok": True, "results": results}
