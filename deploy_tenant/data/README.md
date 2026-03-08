# data 目录说明

本目录存放 admin 服务的运行时数据及 CoPaw 工作目录模板。

## 目录结构

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

## 租户数据目录结构

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

## 同步模板到租户时的目标路径

模板目录下每个子目录/文件与租户目录一一对应：

- `templates/working/` 内容 → `{BASE_DATA_DIR}/{user_id}/working/`
- `templates/working.secret/` 内容 → `{BASE_DATA_DIR}/{user_id}/working.secret/`
- `templates/` 下的根级文件 → `{BASE_DATA_DIR}/{user_id}/` 下同名文件

## 使用前请修改

1. **working.secret/providers.json**：将 `api_key` 占位符替换为真实 Key，或依赖租户 env 注入
2. **working.secret/envs.json**：将 `DASHSCOPE_API_KEY` 等替换为真实值，或依赖租户 env 注入
