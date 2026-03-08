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
- **admin**: 认证网关 + 租户管理 API + Web 管理面板
- **copaw-instance-{user_id}**: 由 admin 通过 Docker API 按需创建，不在 compose 中
- CoPaw 容器不暴露端口，只能通过 Nginx 访问
- 每个用户的数据目录独立挂载，容器重启不丢数据

## 前提条件

- Docker（含 Docker Compose）
- Python 3（仅用于 `prepare.py` 构建/导入镜像）

## 快速开始

### 1. 编辑部署配置

修改 `.env` 文件：

```env
NGINX_PORT=80                          # Nginx 对外端口
COOKIE_SECRET=改成随机字符串             # Cookie 签名密钥
COPAW_IMAGE=copaw-ampere:latest        # CoPaw 镜像名
BASE_DATA_DIR=/data/copaw              # 用户数据根目录（需挂载到 admin 容器以便分发）
TEMPLATES_DIR=templates                # 模板目录名（data/ 下，默认 templates）
ADMIN_PASSWORD=admin                   # 管理后台密码
```

### 2. 构建镜像 & 启动

```bash
python prepare.py build    # 构建全部镜像（nginx + admin + copaw）
python prepare.py up       # 启动 nginx + admin
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
python prepare.py build      # 构建全部镜像
python prepare.py export     # 导出为 tar 文件到 images/

# 将整个 deploy_tenant 目录（含 images/*.tar）拷贝到内网服务器

# --- 在内网服务器上 ---
python prepare.py import     # 导入镜像
vim .env                     # 编辑配置
python prepare.py up         # 启动
# 浏览器访问管理面板，添加租户并启动
```

需要导出的 3 个镜像：

| 镜像 | 来源 | 用途 |
|------|------|------|
| `nginx:alpine` | Docker Hub 官方 | 网关路由 |
| `copaw-admin:latest` | admin-service/Dockerfile | 认证 + 管理 |
| `copaw-ampere:latest` | copaw.Dockerfile | CoPaw 智能助手 |

## 日常管理

```bash
python prepare.py status     # 查看 nginx + admin 容器状态
python prepare.py logs       # 查看全部日志
python prepare.py logs admin # 查看 admin 服务日志
python prepare.py restart    # 重启 nginx + admin
python prepare.py down       # 停止所有服务
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

## 文件说明

```
deploy_tenant/
├── .env                        # 部署配置（端口、密钥、镜像名等）
├── prepare.py                  # 镜像构建/导出/导入 + 首次启停
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
│   └── nginx.conf              # Nginx 静态配置
├── copaw.Dockerfile            # CoPaw 镜像构建文件
├── data/                       # 挂载到宿主机的持久化目录
│   ├── admin.db                # SQLite 数据库（运行时自动创建）
│   ├── templates/              # 模板目录（working、working.secret 等，用于分发）
│   └── README.md               # data 目录说明
└── images/                     # (export 时生成)
    ├── nginx-alpine.tar
    ├── copaw-admin.tar
    └── copaw-ampere.tar
```

## 故障排查

| 问题 | 排查方向 |
|------|---------|
| 管理面板无法访问 | `python prepare.py status` 确认 nginx + admin 容器运行 |
| 用户登录后白屏 | 管理面板查看对应用户容器日志 |
| "用户名或密码错误" | 管理面板确认租户配置 |
| 大模型调用失败 | 检查 .env 或租户环境变量中的 API Key |
| 容器启动失败 | 管理面板查看容器日志，确认镜像已导入 |
