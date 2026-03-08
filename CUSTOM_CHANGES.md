# CoPaw 定制改造日志

> 记录 `ampere` 分支相对于官方 `main` 的功能级改造。
> 只记功能和目的，不记代码细节（代码差异用 `git diff main..ampere` 查看）。

---

## 2026-03-08 ~ 2026-03-09：多租户部署与管理面板

- **目的**：基于 Docker Compose 实现多租户隔离部署，Web 管理面板动态管理租户，支持自定义挂载、批量分发、完整实例信息展示
- **范围**：
  - **基础部署**：新增 `deploy_tenant/` 目录，nginx 网关统一认证与路由，admin 认证/管理服务，prepare.py CLI（build/up/down/status/logs）；每租户独立容器与数据目录挂载
  - **目录结构**：宿主机 `admin-service/`、`data/` 平级 → 容器内 `/app/admin-service/`、`/app/data/` 对应；Dockerfile 以 deploy_tenant 为 context；main.py 中 HTML 路径为 /app/admin-service/...
  - **数据库**：新增 `container_name`、`default_mounts`、`extra_mounts` 列（JSON 数组格式）；迁移并为旧数据回填；租户详情含密码、容器名、挂载路径
  - **自定义挂载**：`extra_mounts` 支持宿主机路径:容器路径[:rw|ro]，每行一个；启动/重启时重建容器以应用最新配置
  - **管理面板**：`GET /admin/api/tenants/{user_id}` 租户详情；`POST /admin/api/containers/{user_id}/remove` 删除容器（不删租户）；编辑弹窗区分「实例信息」（Docker inspect 实时）与「实例配置(数据库记录)」；密码留空则保持不变；停止后「删除容器」与「删除租户」区分
  - **批量分发**：模板目录 `data/templates/`（TEMPLATES_DIR 可配置），jsTree 目录树选择文件/目录，勾选目录递归包含，确认后批量复制到选中租户对应路径
  - **API**：`GET /admin/api/templates/tree`、`POST /admin/api/distribute`；挂载 BASE_DATA_DIR 到 admin 的 `/app/tenants`
  - **UI**：按钮暗色系（蓝/绿/红/紫），租户行启动/停止/重启/编辑/日志/删除；jsTree 本地 static/ 无 CDN；自动刷新保留选中状态
- **涉及文件**：`deploy_tenant/` 全目录（nginx、admin-service、prepare、docker-compose、data/README、admin-service/static/ 等），见 `deploy_tenant/README.md`

## 2026-03-03：计划管理（write_todos 工具）

- **目的**：让智能体能创建和跟踪结构化的任务计划，类似 Claude Code 的 TodoWrite 机制
- **范围**：
  - 后端：新增 `write_todos` 工具，计划以 JSON 保存到 `WORKING_DIR/todos/<user_id>/<session_id>/plan.json`
  - 后端：新增 `GET /agent/current-plan` API 端点，供前端读取计划
  - 前端：Chat 页面右侧新增浮动"当前计划"按钮和面板，展示计划名、进度条、任务列表（含状态标签），每 10 秒自动刷新
- **涉及文件**：`write_todos.py`、`react_agent.py`、`runner.py`、`routers/agent.py`、`agent.ts`、`Chat/index.tsx`

## 2026-03-03：文件下载

- **目的**：智能体生成文件后，用户可在前端聊天界面直接下载
- **范围**：
  - 后端：新增 `GET /agent/download-file` API 端点，支持本地路径和 `file://` URL
  - 前端：新增 `SendFile` 组件，在聊天消息中渲染文件下载卡片（含去重、错误处理、下载状态）
- **涉及文件**：`routers/agent.py`、`SendFile/index.tsx`、`Chat/index.tsx`

## 2026-03-03：SPA fallback 修复

- **目的**：防止前端 SPA fallback 路由吞掉后端 API 请求，导致 API 404 被当成页面返回
- **范围**：`_app.py` 中对 `api/` 开头的路径直接返回 404
- **涉及文件**：`_app.py`

---

_每次新增改造时，在上方追加一条，格式：日期 + 功能名 → 目的 → 范围 → 涉及文件。_
