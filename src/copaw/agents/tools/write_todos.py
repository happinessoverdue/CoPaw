# -*- coding: utf-8 -*-
"""
Plan management tool inspired by Claude Code's TodoWrite mechanism.

Provides a ``write_todos`` tool that agents can call to create or update
a structured plan (task list).  The plan is persisted as JSON under
``WORKING_DIR/todos/<user_id>/<session_id>/plan.json`` so that the
console front-end can read and display it in real time.
"""
import os
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...constant import WORKING_DIR

_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|]')


def _sanitize_filename(name: str) -> str:
    if not name:
        return "unknown"
    return _UNSAFE_FILENAME_RE.sub("--", name)


class Task(BaseModel):
    name: str = Field(description="任务名称,简短且有意义.")
    target: str = Field(description="任务目标,简要描述任务的目标.")
    status: Literal["pending", "in_progress", "complete"] = Field(
        description=(
            "任务状态: pending(未开始), in_progress(进行中), complete(完成)."
        ),
    )


class Plan(BaseModel):
    name: str = Field(
        description=(
            "计划名称，应简要但有意义, 最好包含版本号, "
            "例如 xxxxx_v1, xxxxx_v2。"
        ),
    )
    tasks: list[Task] = Field(
        description="任务清单,每个任务包含名称、目标、状态。",
    )


def _coerce_plan(plan: Any) -> Plan:
    if isinstance(plan, Plan):
        return plan
    if isinstance(plan, str):
        plan = json.loads(plan)
    if isinstance(plan, dict):
        return Plan.model_validate(plan)
    raise TypeError("`plan` must be Plan, dict, or valid JSON object string.")


def create_write_todos_tool(env_context_dict: dict[str, Any] | None):
    """Factory: build a ``write_todos`` async tool bound to a session."""
    context = env_context_dict or {}
    working_dir = str(context.get("working_dir") or WORKING_DIR)
    session_id = str(context.get("session_id") or "")
    user_id = str(context.get("user_id") or "")
    safe_sid = _sanitize_filename(session_id)
    safe_uid = _sanitize_filename(user_id)
    storage_dir = os.path.join(working_dir, "todos", safe_uid, safe_sid)

    current_plan: Plan | None = None

    async def write_todos(plan: Plan) -> ToolResponse:
        """Create or Update a Plan (Task List) / 创建或更新计划（任务清单）

        **重要要求**:
        - 必须使用这个 `write_todos` 工具来创建或更新计划和任务清单.
        - 计划的内容**必须使用中文**, 计划名称、任务名称、任务目标等内容都必须
          使用中文编写(对于特定和专业的术语名词,可以使用英文).

        **什么时候使用这个工具**:
        - 当你需要创建一个新的计划(任务清单)时, 调用此工具并且所有任务状态
          设置为 pending.
        - 在你开始一个任务前(更新该任务状态为 in_progress)
        - 在你完成一个任务时(更新该任务状态为 complete)

        **应该创建计划的情况**:
        - 多步骤任务：需要 3 个或以上步骤才能完成
        - 多数据源整合：需要从多个数据源查询或多次查询
        - 综合分析报告：需要多个分析维度
        - 探索性任务：需要多步骤探索、推理和验证
        - 依赖关系复杂：任务之间存在明确的先后顺序

        **不应该创建计划的情况**:
        - 直接回答：纯对话性或信息性问答
        - 简单需求：少于 3 个简单步骤
        - 单一查询：查询单个数据、读取单个文件等

        Args:
            plan: 需要被创建或更新的计划(任务清单)的内容.

        Returns:
            ToolResponse: 操作结果的提示信息.
        """
        nonlocal current_plan
        try:
            plan = _coerce_plan(plan)
        except Exception:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: `plan` must be Plan, dict, or a valid "
                            "JSON object string."
                        ),
                    ),
                ],
            )

        todo_file = ""
        if storage_dir:
            try:
                os.makedirs(storage_dir, exist_ok=True)
                todo_file = os.path.join(storage_dir, "plan.json")
                with open(todo_file, "w", encoding="utf-8") as f:
                    f.write(plan.model_dump_json(indent=4))
            except Exception as e:
                print("error when writing todo list to file: ", str(e))

        text = ""
        if not plan.name:
            text += "计划名称不能为空,请检查计划名称.\n"
        if not plan.tasks:
            text += "任务清单不能为空,请检查任务清单.\n"
        for task in plan.tasks:
            if not task.name:
                text += "任务名称不能为空,请检查任务名称.\n"
            if not task.target:
                text += "任务目标不能为空,请检查任务目标.\n"
            if not task.status:
                text += "任务状态不能为空,请检查任务状态.\n"

        if text:
            current_plan_content = ""
            if current_plan:
                current_plan_content = current_plan.model_dump_json()
            if current_plan_content:
                text += "**旧的计划内容**:\n" + current_plan_content
            return ToolResponse(
                content=[
                    TextBlock(type="text", text=text),
                ],
            )

        current_plan = plan
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        f"计划和任务清单已成功记录到文件:{todo_file}.\n"
                        "请你确保遵循任务清单并跟踪进度,"
                        "现在请按照任务清单继续工作."
                    ),
                ),
            ],
        )

    return write_todos
