# CoPaw 定制改造日志

> 记录 `copaw-linxin` 分支相对于官方 `main` 的功能级改造。
> 只记功能和目的，不记代码细节（代码差异用 `git diff main..copaw-linxin` 查看）。

---

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
