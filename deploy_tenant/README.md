# CoPaw 多租户部署方案

基于 Docker Compose 的多租户部署方案。每个用户运行独立的 CoPaw 容器实例，通过 Nginx 网关统一认证和路由，通过 Web 管理面板动态管理租户和容器。

## 架构

```
用户浏览器 → http://服务器IP
                │
    ┌───────────┴───────────────────────────────────────┐
    │               Docker Network                       │
    │                                                    │
    │  ┌────────┐  ┌────────────────┐                   │
    │  │ nginx  │  │     admin      │                   │
    │  │ :80→外 │  │ :9000          │                   │
    │  └───┬────┘  │ ・认证网关     │                   │
    │      │       │ ・管理 API     │   copaw-instance- │
    │      │       │ ・Web 管理面板 │   {user_id}       │
    │      │       │ ・Docker API   │   (按需动态创建)   │
    │      │       └────────────────┘                   │
    │      │  唯一对外端口                                │
    └──────┼────────────────────────────────────────────┘
           │
      宿主机 :80
```

- **nginx**: 唯一对外端口，认证代理 + 动态路由
- **admin**: 认证网关 + 租户管理 API + Web 管理面板 + 共享文件服务
- **copaw-instance-{user_id}**: 由 admin 通过 Docker API 按需创建，不在 compose 中
- CoPaw 容器不暴露端口，只能通过 Nginx 访问
- 每个用户的数据目录独立挂载，容器重启不丢数据

## 前提条件

- Docker（含 Docker Compose）
- Bash（推荐 `prepare.sh`，本地和服务器均可直接使用；亦可使用 Python 3 运行 `prepare.py`）

## 快速开始

### 1. 编辑部署配置

修改 `.env` 文件：

```env
NGINX_PORT=80                          # Nginx 对外端口
COOKIE_SECRET=改成随机字符串             # Cookie 签名密钥
COPAW_IMAGE=copaw-ampere:latest        # CoPaw 镜像名
BASE_DATA_DIR=/data/copaw              # 用户数据根目录（需挂载到 admin 容器以便分发）
COPAW_INTERNAL_PORT=8088               # CoPaw 容器内部监听端口（默认 8088，与 Nginx 代理目标一致，一般无需修改）
TEMPLATES_DIR=templates                # 模板目录名（data/ 下，默认 templates）
ADMIN_PASSWORD=admin                   # 管理后台密码
SHARED_FILES_DIR=./shared_files        # 共享文件服务存储目录（可选，默认 ./shared_files）
FILE_SERVICE_BASE_URL=http://127.0.0.1  # 共享文件服务 scheme+host，端口自动从 NGINX_PORT 补充
```

### 2. 构建镜像 & 启动

```bash
./prepare.sh build    # 构建全部镜像（nginx + admin + copaw）
./prepare.sh up       # 启动 nginx + admin
```

### 3. 管理租户

浏览器访问 `http://服务器IP/admin/`，用管理员账号（admin/admin）登录管理后台。

在管理面板中：
- **新增租户**: 填写用户 ID、姓名、密码
- **批量导入**: 上传 JSON 文件批量创建租户
- **批量分发**: 勾选租户后点击「分发」，从模板目录选择文件/目录批量同步到各租户数据目录
- **启动实例**: 点击「启动」按钮，admin 自动创建 Docker 容器
- **停止/重启**: 在管理面板上操作
- **查看日志**: 点击「日志」查看容器输出

### 4. 用户登录

浏览器访问 `http://服务器IP`，使用管理员分配的账号登录，自动路由到对应的 CoPaw 实例。

## 内网部署（无法联网的服务器）

```bash
# --- 在有网的机器上 ---
./prepare.sh build      # 构建全部镜像
./prepare.sh export     # 导出为 tar 文件到 images/

# 将整个 deploy_tenant 目录（含 images/*.tar）拷贝到内网服务器

# --- 在内网服务器上 ---
./prepare.sh import     # 导入镜像
vim .env                 # 编辑配置
./prepare.sh up          # 启动
# 浏览器访问管理面板，添加租户并启动
```

需要导出的 3 个镜像：

| 镜像 | 来源 | 用途 |
|------|------|------|
| `copaw-nginx:latest` | nginx/Dockerfile | 网关路由（基于 nginx:alpine + tzdata） |
| `copaw-admin:latest` | admin-service/Dockerfile | 认证 + 管理 |
| `copaw-ampere:latest` | copaw.Dockerfile | CoPaw 智能助手 |

## 日常管理

```bash
./prepare.sh status     # 查看 nginx + admin 容器状态
./prepare.sh logs       # 查看全部日志
./prepare.sh logs admin # 查看 admin 服务日志
./prepare.sh restart    # 重启 nginx + admin
./prepare.sh down        # 停止所有服务
```

租户和 CoPaw 实例的管理全部在 Web 管理面板上完成。

## 命令参考

| 命令 | 说明 |
|------|------|
| `build` | 构建全部镜像（nginx + copaw-admin + copaw-ampere） |
| `up` | 启动 nginx + admin 服务 |
| `down` | 停止所有服务 |
| `restart` | 重启所有服务 |
| `status` | 查看容器运行状态 |
| `logs [service]` | 查看日志（可指定某个服务） |
| `export` | 导出镜像为 tar 文件（用于内网部署，需先 build） |
| `import [dir]` | 从 tar 文件导入镜像 |

## 定制某个用户的提示词

**方式一**：直接编辑该用户的数据目录：

```bash
vim /data/copaw/zhangsan/working/AGENTS.md
vim /data/copaw/zhangsan/working/SOUL.md
```

**方式二**：使用管理面板「分发」功能，从 `data/templates/` 选择文件/目录批量同步到选中租户，修改模板后一次分发即可更新多个租户。

在管理面板上重启对应用户的容器即可生效。

## 模板与分发

- **模板目录**：`data/templates/`（可通过 `TEMPLATES_DIR` 环境变量配置）
- 模板结构对标每个租户目录，例如 `templates/working/AGENTS.md` → `{user_id}/working/AGENTS.md`
- 分发时勾选租户，选择要分发的文件或目录，确认后批量复制到各租户对应路径，覆盖已存在文件

### data 目录说明

`data/` 目录存放 admin 服务的运行时数据及 CoPaw 工作目录模板。

**data 目录结构：**

- **admin.db**：SQLite 数据库，存储租户配置
- **templates/**：CoPaw 工作目录模板（目录名可通过环境变量 TEMPLATES_DIR 配置，默认 templates）
  - **working/**：CoPaw 工作目录模板，用于分发同步到各租户 `{user_id}/working/`
    - 提示词：AGENTS.md、SOUL.md、PROFILE.md、MEMORY.md、HEARTBEAT.md、BOOTSTRAP.md
    - **config.json**：应用配置（频道、MCP、agents 等）
    - **active_skills/**：默认技能（pdf、news、cron 等）
    - **customized_skills/**：用户定义创建的技能
  - **working.secret/**：敏感配置模板，用于分发同步到各租户 `{user_id}/working.secret/`
    - **providers.json**：LLM 提供商配置（含 API Key）
    - **envs.json**：环境变量（如 DASHSCOPE_API_KEY）

**租户数据目录结构：**

每个租户在 `{BASE_DATA_DIR}` 下拥有一个独立目录：

```
{BASE_DATA_DIR}/
├── zhangsan/
│   ├── working/           → 容器内 /app/working (CoPaw 工作目录)
│   └── working.secret/    → 容器内 /app/working.secret (敏感配置)
├── lisi/
│   ├── working/
│   └── working.secret/
└── ...
```

**同步模板到租户时的目标路径：**

- `templates/working/` 内容 → `{BASE_DATA_DIR}/{user_id}/working/`
- `templates/working.secret/` 内容 → `{BASE_DATA_DIR}/{user_id}/working.secret/`
- `templates/` 下的根级文件 → `{BASE_DATA_DIR}/{user_id}/` 下同名文件

### 共享文件服务

供 CoPaw 工具、外部服务（如潮流计算）写入大文件，前端可读取展示。

- **路径前缀**：`/share_files/`
- **写入**：`POST /share_files/write`
  - JSON：`{"path": "query_load_data_tool/abc.json", "content": "..."}`（文本）
  - Multipart：`path` + `file`（任意文件，含 docx、图片等）
- **读取**：`GET /share_files/YYYYMMDD/...`，无需登录
- **存储**：按日期分目录 `{SHARED_FILES_DIR}/YYYYMMDD/{path}`
- `FILE_SERVICE_BASE_URL` 只需填 scheme+host（如 `http://127.0.0.1`），端口会自动从 `NGINX_PORT` 补充

**使用前请修改：**

1. **working.secret/providers.json**：将 `api_key` 占位符替换为真实 Key，或依赖租户 env 注入
2. **working.secret/envs.json**：将 `DASHSCOPE_API_KEY` 等替换为真实值，或依赖租户 env 注入

## 文件说明

```
deploy_tenant/
├── .env                        # 部署配置（端口、密钥、镜像名等）
├── prepare.sh                  # 镜像构建/导出/导入 + 首次启停（推荐，Bash 脚本）
├── prepare.py                  # 同上，Python 版本（无 Bash 时可用）
├── docker-compose.yml          # 静态编排：仅 nginx + admin
├── admin-service/              # 认证 + 管理服务
│   ├── Dockerfile
│   ├── main.py                 # FastAPI: 认证 API + 管理 API + 分发 API
│   ├── db.py                   # SQLite 租户数据层
│   ├── docker_manager.py       # Docker API 封装
│   ├── requirements.txt
│   ├── login.html              # 用户登录页
│   ├── admin.html              # 管理面板页面
│   └── static/                 # 静态资源（jQuery、jsTree，用于分发目录树）
├── nginx/
│   ├── Dockerfile              # Nginx 镜像（含 tzdata 时区）
│   └── nginx.conf              # Nginx 静态配置
├── copaw.Dockerfile            # CoPaw 镜像构建文件
├── data/                       # 挂载到宿主机的持久化目录（说明见上文「data 目录说明」）
│   ├── admin.db                # SQLite 数据库（运行时自动创建）
│   └── templates/              # 模板目录（working、working.secret 等，用于分发给各租户docker里copaw的 {工作目录} 和 {工作目录.secret}
└── images/                     # (export 时生成)
    ├── copaw-nginx.tar
    ├── copaw-admin.tar
    └── copaw-ampere.tar
```

## 故障排查

| 问题 | 排查方向 |
|------|---------|
| 管理面板无法访问 | `./prepare.sh status` 确认 nginx + admin 容器运行 |
| 用户登录后白屏 | 管理面板查看对应用户容器日志 |
| "用户名或密码错误" | 管理面板确认租户配置 |
| 大模型调用失败 | 检查 .env 或租户环境变量中的 API Key |
| 容器启动失败 | 管理面板查看容器日志，确认镜像已导入 |
