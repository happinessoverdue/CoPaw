---
description: "CoPaw 定制开发项目上下文"
globs: "**/*"
alwaysApply: true
---

## 项目背景

这是官方 CoPaw（个人 AI 助手框架，阿里通义 AgentScope 团队开发）的 **Fork 定制化仓库**，正在适配**电力调度自动化系统**场景。

- **官方仓库**: https://github.com/agentscope-ai/CoPaw
- **Fork 仓库**: https://github.com/happinessoverdue/CoPaw
- **技术栈**: Python 3.10+, FastAPI, AgentScope, React

## 分支与仓库

| 分支 | 用途 | 规则 |
|---|---|---|
| `main` | 纯官方代码 | **禁止修改**，只用于同步官方更新 |
| `ampere` | 定制开发主线 | **所有改动都在这里** |

- **origin**: Fork 仓库（可推送）
- **upstream**: 官方仓库（只拉取）
- 同步官方更新流程：`fetch upstream` → `merge upstream/main 到 main` → `rebase main 到 ampere`

## 代码与配置分离（重要）

| 改动类型 | 在哪里改 | 说明 |
|---|---|---|
| **代码级改造**（新增工具、API、前端组件） | 源码目录 `src/copaw/`、`console/` | 需要 commit |
| **配置级调整**（提示词优化、技能增删） | `~/.copaw/` 运行时工作目录 | 不要改源码里的模板文件 |

**禁止执行** `copaw init --defaults`，会用默认模板覆盖 `~/.copaw/` 里的配置。

## 源码结构

| 路径 | 说明 |
|---|---|
| `src/copaw/agents/react_agent.py` | **CoPawAgent 主类**（继承 ReActAgent） |
| `src/copaw/agents/tools/` | 内置工具（shell, file_io, browser, write_todos 等） |
| `src/copaw/agents/skills/` | 内置技能（pdf, docx, xlsx 等） |
| `src/copaw/agents/hooks/` | 推理前钩子 |
| `src/copaw/agents/md_files/` | 智能体提示词默认模板 |
| `src/copaw/app/routers/` | API 端点定义 |
| `src/copaw/app/channels/` | 频道实现（钉钉, 飞书, QQ 等） |
| `src/copaw/app/runner/` | AgentRunner 和会话管理 |
| `src/copaw/app/_app.py` | FastAPI 应用主文件 |
| `console/` | React 前端 |

## 扩展开发模式

**添加新工具**: `src/copaw/agents/tools/` 创建函数 → `__init__.py` 导出 → `CoPawAgent._create_toolkit()` 注册

**添加新技能**: `src/copaw/agents/skills/` 或 `~/.copaw/active_skills/` 创建目录 + `SKILL.md`

**添加新 API**: `src/copaw/app/routers/` 创建路由 → `_app.py` 注册 → `console/src/api/modules/` 添加前端 API

## 开发-测试循环

| 改动类型 | 生效方式 |
|---|---|
| Python 代码 (`src/copaw/`) | 重启 `copaw app`（可编辑模式安装，无需重装） |
| 前端代码 (`console/src/`) | `cd console && npm run build` → 刷新浏览器 |
| `~/.copaw/` 配置文件 | 重启 `copaw app` |
| `pyproject.toml` | `pip install -e ".[dev]"` → 重启服务 |

## 开发规则

1. **只在 `ampere` 分支上修改代码**，永远不要在 `main` 上改
2. 每个独立功能**单独 commit**，便于 rebase 时精准处理冲突
3. commit 消息格式：`feat:` / `fix:` / `docs:` / `refactor:` + 简要描述
4. 新增或修改定制功能后，同步更新 `CUSTOM_CHANGES.md`

## 当前定制功能

- **write_todos 工具**: 智能体计划/任务清单管理，JSON 持久化到 `WORKING_DIR/todos/`
- **计划面板**: 前端 Chat 页面右侧浮层，展示当前计划进度
- **文件下载**: 后端下载接口 + 前端下载卡片渲染
- **SPA fallback 修复**: 防止 API 路由被前端 fallback 吞掉

## 关键文件

| 文件 | 用途 |
|---|---|
| `CUSTOM_CHANGES.md` | **定制改造日志**（每次改造后更新） |
| `docs/custom/开发工作流指南.md` | Git 工作流详细说明 |
| `docs/custom/调研笔记.md` | 项目调研、架构分析、电力调度适配方案 |

## 环境变量

| 变量 | 说明 |
|---|---|
| `COPAW_WORKING_DIR` | 工作目录路径（默认 `~/.copaw`） |
| `COPAW_CONSOLE_STATIC_DIR` | 前端静态文件目录（本地开发用） |
| `COPAW_LOG_LEVEL` | 日志级别（默认 `info`） |
| `DASHSCOPE_API_KEY` | 通义千问 API Key |
