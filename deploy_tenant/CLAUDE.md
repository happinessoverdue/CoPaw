# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 一、项目概述

这是 CoPaw 的多租户部署方案，基于 Docker Compose 实现每个用户独立容器实例，通过 Nginx 网关统一认证和路由，通过 Web 管理面板动态管理租户和容器。

### 架构

```
用户浏览器 → Nginx(:80)
    ├── /auth/*   → admin:9000 (用户登录/登出/验证)
    ├── /admin/*  → admin:9000 (管理面板 + 管理 API)
    └── /*        → auth_request 验证 → 路由到 copaw-instance-{user_id}:8088
```

**核心组件**：
- **nginx**: 网关，唯一对外端口，auth_request 集成，注入退出登录按钮
- **admin**: FastAPI 服务，包含认证网关 + 租户管理 API + Web 管理面板
- **copaw-instance-{user_id}**: 由 admin 通过 Docker API 动态创建的用户容器

**数据隔离**：每个用户的数据目录独立挂载
```
{BASE_DATA_DIR}/{user_id}/ → 容器内 /app/working/
```

**租户配置**：SQLite 数据库（挂载到宿主机，容器重启不丢失）

---

## 二、常用命令

```bash
# 构建全部镜像（nginx + copaw-admin + copaw-ampere）
python prepare.py build

# 启动 nginx + admin 服务
python prepare.py up

# 停止所有服务
python prepare.py down

# 查看容器状态
python prepare.py status

# 查看日志（可指定服务）
python prepare.py logs
python prepare.py logs admin

# 离线部署：导出/导入镜像
python prepare.py export
python prepare.py import
python prepare.py import /path/to/tar/dir
```

租户和容器管理全部在 Web 管理面板（`/admin/`）上完成。

---

## 三、关键文件

| 文件 | 用途 |
|------|------|
| `.env` | **部署配置**（端口、密钥、镜像名、数据目录等） |
| `prepare.py` | 镜像构建/导出/导入 + 首次 compose 启停 |
| `docker-compose.yml` | 静态编排，仅 nginx + admin |
| `nginx/nginx.conf` | Nginx 静态配置 |
| `admin-service/main.py` | FastAPI: 认证 API + 管理 API |
| `admin-service/db.py` | SQLite 租户数据层 |
| `admin-service/docker_manager.py` | Docker API 容器管理封装 |
| `admin-service/login.html` | 用户登录页面 |
| `admin-service/admin.html` | 管理面板页面 |
| `copaw.Dockerfile` | CoPaw 镜像构建文件 |
| `data/admin.db` | SQLite 数据库（运行时自动创建） |

---

## 四、认证机制

### 用户认证流程
1. 用户访问 → Nginx `auth_request` 调用 `/_auth_check`
2. admin 服务验证签名 Cookie → 返回 `X-CoPaw-Instance` 头
3. Nginx 根据 header 动态 `proxy_pass` 到对应容器
4. 未认证返回 401 → 重定向到 `/auth/login`

### Cookie 签名格式
```
{instance_name}.{timestamp}.{hmac_sha256签名前16位}
```
- 密钥：`COOKIE_SECRET` 环境变量
- 有效期：默认 24 小时

### 管理员认证
- 固定账号：admin / `ADMIN_PASSWORD`
- 独立 cookie（`copaw_admin_session`）
- 仅用于 `/admin/*` 路径

---

## 五、管理 API

| 路由 | 方法 | 功能 |
|------|------|------|
| `/admin/api/tenants` | GET | 获取所有租户（配置 + 容器状态） |
| `/admin/api/tenants` | POST | 新增租户 |
| `/admin/api/tenants/{user_id}` | PUT | 编辑租户 |
| `/admin/api/tenants/{user_id}` | DELETE | 删除租户 + 删除容器 |
| `/admin/api/tenants/import` | POST | JSON 批量导入 |
| `/admin/api/containers/{user_id}/start` | POST | 启动容器 |
| `/admin/api/containers/{user_id}/stop` | POST | 停止容器 |
| `/admin/api/containers/{user_id}/restart` | POST | 重启容器 |
| `/admin/api/containers/{user_id}/logs` | GET | 获取容器日志 |
| `/admin/api/containers/batch` | POST | 批量启动/停止 |

---

## 六、租户管理

所有租户管理通过 Web 管理面板（`/admin/`）完成：

- **新增**：填写 user_id、user_name、password，可选环境变量
- **编辑**：修改姓名、密码、环境变量
- **删除**：同时清理容器
- **批量导入**：上传 JSON 文件
- **启动/停止/重启**：单个或批量操作容器
- **日志查看**：实时查看容器日志

---

## 七、离线部署流程

```bash
# 有网机器上
python prepare.py build
python prepare.py export

# 拷贝整个 deploy_tenant 目录（含 images/）到离线服务器

# 离线服务器上
python prepare.py import
vim .env                      # 编辑配置
python prepare.py up
# 浏览器访问 /admin/ 管理面板，添加租户并启动
```

三个镜像：`nginx:alpine`、`copaw-admin:latest`、`copaw-ampere:latest`

---

## 八、定制化

### 修改登录页样式
编辑 `admin-service/login.html`，错误信息通过 `<!-- ERROR_PLACEHOLDER -->` 占位符注入。

### 修改某个用户的提示词
直接编辑该用户的数据目录：
```bash
vim /data/copaw/zhangsan/AGENTS.md
vim /data/copaw/zhangsan/SOUL.md
```
在管理面板上重启对应容器。

---

## 九、.env 配置说明

```env
NGINX_PORT=80                          # Nginx 对外端口
COOKIE_SECRET=随机字符串                # Cookie 签名密钥（务必修改）
COPAW_IMAGE=copaw-ampere:latest        # CoPaw 镜像名
BASE_DATA_DIR=/data/copaw              # 用户数据根目录（宿主机路径）
COPAW_INTERNAL_PORT=8088               # CoPaw 容器内部端口
ADMIN_PASSWORD=admin                   # 管理后台密码
```

---

## 十、技术要点

- **动态容器管理**：admin 挂载 docker.sock，通过 Docker Python SDK 创建/管理容器
- **网络**：动态创建的容器加入 `copaw-multi-tenant-service_copaw-net`，与 nginx 同网络
- **SQLite**：WAL 模式，线程安全，文件挂载到宿主机持久化
- **容器命名**：`copaw-instance-{user_id}`
- **重启策略**：动态容器设置 `unless-stopped`，宿主机重启后自动恢复
