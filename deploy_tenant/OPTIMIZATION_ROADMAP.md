# CoPaw 多租户部署方案 — 优化迭代规划

> **状态：已实现** (2026-03-07)
> 本文档中描述的目标架构已全部实现。详见新版 README.md 和 CLAUDE.md。

本文档汇总了多租户部署方案的优化思路，用于指导下一步开发迭代。

---

## 一、目标架构概述

### 1.1 核心变化

| 现状 | 目标 |
|------|------|
| docker-compose 包含 nginx + auth + 所有 copaw-instance | docker-compose 仅包含 nginx + admin |
| CoPaw 实例由 compose 静态定义，启动时全部拉起 | CoPaw 实例由 admin 按需动态创建 |
| 租户配置在 config.json，需手动编辑 | 租户配置完全由 Web 管理页面维护 |
| manage.py 负责 generate、up、down 等 | 弃用 manage.py，全部由 Web 管理 |

### 1.2 目标架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│  初始部署：仅启动 nginx + admin                                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  nginx (:80)  ──┬── /auth/*        ──→ admin (:9000) 认证 + 管理        │
│                 │                                                       │
│                 └── 其他请求  ──→ auth_request ──→ admin /auth/check    │
│                                   ──→ 通过则 proxy 到 copaw-instance-xxx│
│                                                                          │
│  admin         ── 认证：login, logout, check, whoami                    │
│                 ── 管理：租户 CRUD、容器启停、日志、批量操作               │
│                 ── 挂载 Docker socket，通过 Docker API 动态创建容器      │
│                                                                          │
│  copaw-instance-xxx  ── 由 admin 按需创建，加入 copaw-net，不在 compose 中 │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 二、配置分离

### 2.1 两类配置

| 配置类型 | 用途 | 维护方式 | 存储位置 |
|----------|------|----------|----------|
| **Compose / 部署配置** | 启动 nginx、admin | 部署时一次性配置 | docker-compose.yml |
| **租户配置** | 定义每个用户的 CoPaw 实例 | **仅通过 Web 管理页面** | 独立存储（文件或数据库） |

### 2.2 Compose 配置

- **内容**：nginx、admin 两个服务，网络 copaw-net，项目名 `copaw-multi-tenant-service`
- **特点**：静态、极少变更，与租户无关
- **不再**：包含任何 copaw-instance 服务

### 2.3 租户配置

- **内容**：user_id、user_name、password、数据目录、环境变量、CoPaw 镜像等
- **特点**：完全由 Web 页面 CRUD，人工不直接编辑
- **存储**：独立于 compose，如 `tenants.json` 或 SQLite

---

## 三、租户配置管理原则

### 3.1 单一维护入口

- 租户配置 **不应** 由人工手动维护（不直接编辑 JSON 文件）
- 所有增删改查 **必须** 通过 Web 管理页面完成
- Web 页面是租户配置的 **唯一** 操作入口

### 3.2 配置与运行时分离

| 概念 | 含义 | 存储 |
|------|------|------|
| **配置** | 用户存在、其参数定义 | 租户配置存储 |
| **运行时** | 容器是否在运行 | Docker 状态 |

- 有配置 ≠ 有运行中的容器
- 导入配置 ≠ 启动容器
- 删除配置时，若容器在运行，需先停止并删除容器

### 3.3 JSON 导入的语义

- **作用**：从模板批量创建租户配置
- **行为**：在系统中新增多条配置记录
- **不触发**：不启动任何容器
- **结果**：页面上显示这些租户及其配置，用户可逐个或批量点击「启动」

---

## 四、Admin 容器设计

### 4.1 功能合并

将 **auth（认证）** 与 **admin（管理）** 合并为同一个容器：

| 功能模块 | 路由/职责 | 说明 |
|----------|-----------|------|
| 认证 | `/auth/login`, `/auth/logout`, `/auth/check`, `/auth/whoami` | 沿用现有 auth 逻辑，Cookie 签名验证 |
| 管理 | `/admin/*` 或独立管理路径 | 租户 CRUD、容器启停、日志、批量操作 |
| 前端 | 管理页面 SPA 或服务端渲染 | 列表、表单、导入、启停按钮 |

### 4.2 权限与访问控制

- 认证接口：面向所有访问 CoPaw 的用户
- 管理接口：需单独的管理员认证（与 CoPaw 用户登录分离），或通过路径/IP 限制

### 4.3 依赖

- 挂载 `/var/run/docker.sock` 以调用 Docker API
- 读写租户配置存储（文件或数据库）
- 读取 `cookie_secret` 等部署级配置（可从环境变量或独立 deploy 配置读取）

---

## 五、初始部署流程（内网服务器）

### 5.1 仅启动 nginx + admin

```bash
# 1. 导入镜像（或提前 build）
docker load -i nginx-alpine.tar
docker load -i copaw-admin.tar      # 合并后的 admin 镜像（含认证+管理）
docker load -i copaw-ampere.tar     # CoPaw 实例用

# 2. 准备最小部署配置（端口、cookie_secret 等，不含租户）
# 3. 启动
docker compose up -d
```

此时 **无任何** copaw-instance 容器运行。

### 5.2 后续操作

- 通过 Web 管理页面添加租户配置（或导入 JSON）
- 在页面上逐个或批量点击「启动」，admin 按配置创建并启动容器

---

## 六、Web 管理页面功能

### 6.1 租户配置管理

| 功能 | 说明 |
|------|------|
| 列表 | 展示所有租户配置及当前运行状态 |
| 新增 | 表单填写 user_id、user_name、password、数据目录、环境变量等 |
| 编辑 | 修改已有租户配置 |
| 删除 | 删除配置；若容器在运行，先停止并删除容器 |
| 导入 JSON | 从模板文件批量创建配置，不启动容器 |

### 6.2 容器操作

| 功能 | 说明 |
|------|------|
| 启动 | 根据配置创建容器并启动（单个或批量） |
| 停止 | 停止容器（单个或批量） |
| 重启 | 重启容器 |
| 查看日志 | 拉取容器日志并展示 |

### 6.3 快捷功能

- **批量导入**：上传 JSON 文件，解析后批量创建配置
- **批量启动**：勾选多个租户，一键启动
- **批量停止**：勾选多个租户，一键停止

---

## 七、技术实现要点

### 7.1 容器创建

admin 通过 Docker API（如 `docker` Python 库）创建容器：

```python
# 伪代码
client.containers.run(
    image=config["copaw_image"],
    name=f"copaw-instance-{user_id}",
    network="copaw-multi-tenant-service_copaw-net",
    volumes={f"{base_data_dir}/{user_id}": {"bind": "/app/working", "mode": "rw"}},
    environment={"COPAW_PORT": "8088", **config.get("env", {})},
    detach=True,
)
```

- 容器名：`copaw-instance-{user_id}`
- 网络：与 nginx、admin 同网，以便路由
- 数据目录：从租户配置读取

### 7.2 网络

- compose 创建 `copaw-net`
- admin 创建的容器需加入该网络
- 网络名通常为 `{project_name}_copaw-net`，如 `copaw-multi-tenant-service_copaw-net`

### 7.3 Nginx 配置

- `/auth/*` → admin
- 其他请求 → auth_request → admin `/auth/check` → 通过则 `proxy_pass http://$copaw_instance:8088`
- 重定向登录页时使用 `$scheme://$http_host/auth/login` 以保留端口

### 7.4 配置一致性

- 租户配置存储作为 **唯一数据源**
- 写操作加文件锁或使用数据库事务，避免并发冲突
- 可选：操作审计日志（谁在何时做了什么）

---

## 八、manage.py 的处置

### 8.1 弃用范围

- `generate`：不再根据 config.json 生成包含 copaw-instance 的 compose
- `up` / `down` / `start` / `stop` / `restart`：由 admin 通过 Docker API 实现

### 8.2 保留可能（可选）

- `build`：构建镜像（copaw-admin、copaw-ampere）
- `export` / `import`：镜像导出导入，用于离线部署

若保留，可简化为仅负责镜像构建与导入导出，与运行时管理解耦。

---

## 九、实施阶段建议

### 阶段一：Admin 合并与最小部署

1. 合并 auth 与 admin 为单一服务
2. 精简 docker-compose，仅 nginx + admin
3. 实现 admin 通过 Docker API 创建/启停容器
4. 验证：手动调用 API 能创建 copaw-instance 并正常访问

### 阶段二：租户配置存储与 API

1. 设计租户配置存储格式（JSON 或 SQLite）
2. 实现租户 CRUD API
3. 实现「启动/停止/重启」API，内部调用 Docker API

### 阶段三：Web 管理页面

1. 租户列表、新增、编辑、删除
2. 单个/批量启动、停止、重启
3. JSON 导入
4. 日志查看

### 阶段四：完善与收尾

1. 管理员认证与权限
2. 操作审计（可选）
3. 文档与部署脚本更新
4. 移除或简化 manage.py

---

## 十、参考：当前 config.json 结构（将拆分为部署配置 + 租户配置）

当前 `config.json` 混合了部署级与租户级配置，优化后建议拆分：

**部署配置**（用于 compose 或 admin 启动参数）：
- `nginx_http_port`
- `copaw_internal_port`
- `cookie_secret`
- `copaw_image`
- `base_data_dir`

**租户配置**（独立存储，仅 Web 维护）：
- `user_id`, `user_name`, `password`
- 可选：`enabled`、自定义 `env` 等

---

*文档版本：2025-03-07*
