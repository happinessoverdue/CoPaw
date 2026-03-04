---
description: "CoPaw 定制开发工作流上下文"
globs: "**/*"
alwaysApply: true
---

## 项目背景

这是 CoPaw（个人 AI 助手框架）的**定制开发仓库**，基于官方 Fork 进行本地改造。

## 仓库结构

- **origin**: `https://github.com/happinessoverdue/CoPaw`（Fork，可推送）
- **upstream**: `https://github.com/agentscope-ai/CoPaw`（官方，只拉取）
- **开发分支**: `ampere` — 所有改动都在这个分支上
- **main 分支**: 纯官方代码，**禁止修改**，只用于同步官方更新
- **改造日志**: `CUSTOM_CHANGES.md` — 记录了所有定制功能的概要
- **工作流指南**: `docs/custom/开发工作流指南.md` — 完整的 Git 工作流说明、概念解释和命令速查，遇到分支/同步/rebase 等问题时可参考

## 开发规则

1. **只在 `ampere` 分支上修改代码**，永远不要在 `main` 上改
2. 每个独立功能**单独 commit**，便于后续 rebase 时精准处理冲突
3. commit 消息使用英文，格式：`feat:` / `fix:` / `docs:` + 简要描述
4. 新增或修改定制功能后，同步更新 `CUSTOM_CHANGES.md`
5. 提交三步骤：`git add` → `git commit` → `git push origin ampere`

## 当前定制功能

- **write_todos 工具**: 智能体计划/任务清单管理，JSON 持久化到 `WORKING_DIR/todos/`
- **计划面板**: 前端 Chat 页面右侧浮层，展示当前计划进度
- **文件下载**: 后端下载接口 + 前端下载卡片渲染
- **SPA fallback 修复**: 防止 API 路由被前端 fallback 吞掉
