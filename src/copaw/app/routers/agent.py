# -*- coding: utf-8 -*-
"""Agent file management API."""

import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ...config import (
    load_config,
    save_config,
    AgentsRunningConfig,
)
from ...constant import WORKING_DIR
from ..channels.utils import file_url_to_local_path

from ...agents.memory.agent_md_manager import AgentMdManager
from ..agent_context import get_agent_for_request

_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|]')


def _sanitize_filename(name: str) -> str:
    if not name:
        return "unknown"
    return _UNSAFE_FILENAME_RE.sub("--", name)


router = APIRouter(prefix="/agent", tags=["agent"])


class PlanReadResponse(BaseModel):
    """Current plan content for a session/user."""

    exists: bool = Field(..., description="Whether plan file exists")
    file_path: str = Field(..., description="Resolved plan file path")
    plan: dict[str, Any] | None = Field(
        default=None,
        description="Parsed plan json content",
    )


class MdFileInfo(BaseModel):
    """Markdown file metadata."""

    filename: str = Field(..., description="File name")
    path: str = Field(..., description="File path")
    size: int = Field(..., description="Size in bytes")
    created_time: str = Field(..., description="Created time")
    modified_time: str = Field(..., description="Modified time")


class MdFileContent(BaseModel):
    """Markdown file content."""

    content: str = Field(..., description="File content")


@router.get(
    "/files",
    response_model=list[MdFileInfo],
    summary="List working files",
    description="List all working files (uses active agent)",
)
async def list_working_files(
    request: Request,
) -> list[MdFileInfo]:
    """List working directory markdown files."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_manager = AgentMdManager(
            str(workspace.workspace_dir),
        )
        files = [
            MdFileInfo.model_validate(file)
            for file in workspace_manager.list_working_mds()
        ]
        return files
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/files/{md_name}",
    response_model=MdFileContent,
    summary="Read a working file",
    description="Read a working markdown file (uses active agent)",
)
async def read_working_file(
    md_name: str,
    request: Request,
) -> MdFileContent:
    """Read a working directory markdown file."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_manager = AgentMdManager(
            str(workspace.workspace_dir),
        )
        content = workspace_manager.read_working_md(md_name)
        return MdFileContent(content=content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put(
    "/files/{md_name}",
    response_model=dict,
    summary="Write a working file",
    description="Create or update a working file (uses active agent)",
)
async def write_working_file(
    md_name: str,
    body: MdFileContent,
    request: Request,
) -> dict:
    """Write a working directory markdown file."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_manager = AgentMdManager(
            str(workspace.workspace_dir),
        )
        workspace_manager.write_working_md(md_name, body.content)
        return {"written": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/memory",
    response_model=list[MdFileInfo],
    summary="List memory files",
    description="List all memory files (uses active agent)",
)
async def list_memory_files(
    request: Request,
) -> list[MdFileInfo]:
    """List memory directory markdown files."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_manager = AgentMdManager(
            str(workspace.workspace_dir),
        )
        files = [
            MdFileInfo.model_validate(file)
            for file in workspace_manager.list_memory_mds()
        ]
        return files
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/memory/{md_name}",
    response_model=MdFileContent,
    summary="Read a memory file",
    description="Read a memory markdown file (uses active agent)",
)
async def read_memory_file(
    md_name: str,
    request: Request,
) -> MdFileContent:
    """Read a memory directory markdown file."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_manager = AgentMdManager(
            str(workspace.workspace_dir),
        )
        content = workspace_manager.read_memory_md(md_name)
        return MdFileContent(content=content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put(
    "/memory/{md_name}",
    response_model=dict,
    summary="Write a memory file",
    description="Create or update a memory file (uses active agent)",
)
async def write_memory_file(
    md_name: str,
    body: MdFileContent,
    request: Request,
) -> dict:
    """Write a memory directory markdown file."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_manager = AgentMdManager(
            str(workspace.workspace_dir),
        )
        workspace_manager.write_memory_md(md_name, body.content)
        return {"written": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/language",
    summary="Get agent language",
    description="Get the language setting for agent MD files (en/zh/ru)",
)
async def get_agent_language() -> dict:
    """Get agent language setting."""
    config = load_config()
    return {"language": config.agents.language}


@router.put(
    "/language",
    summary="Update agent language",
    description=(
        "Update the language for agent MD files (en/zh/ru). "
        "Optionally copies MD files for the new language."
    ),
)
async def put_agent_language(
    body: dict = Body(
        ...,
        description='Language setting, e.g. {"language": "zh"}',
    ),
) -> dict:
    """Update agent language and optionally re-copy MD files."""
    language = (body.get("language") or "").strip().lower()
    valid = {"zh", "en", "ru"}
    if language not in valid:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid language '{language}'. "
                f"Must be one of: {', '.join(sorted(valid))}"
            ),
        )
    config = load_config()
    old_language = config.agents.language
    config.agents.language = language
    save_config(config)

    copied_files: list[str] = []
    if old_language != language:
        from ...agents.utils import copy_md_files

        copied_files = copy_md_files(language) or []
        if copied_files:
            config = load_config()
            config.agents.installed_md_files_language = language
            save_config(config)

    return {
        "language": language,
        "copied_files": copied_files,
    }


@router.get(
    "/running-config",
    response_model=AgentsRunningConfig,
    summary="Get agent running config",
    description="Get running configuration for active agent",
)
async def get_agents_running_config(
    request: Request,
) -> AgentsRunningConfig:
    """Get agent running configuration."""
    workspace = await get_agent_for_request(request)
    from ...config.config import load_agent_config

    agent_config = load_agent_config(workspace.agent_id)
    return agent_config.running or AgentsRunningConfig()


@router.put(
    "/running-config",
    response_model=AgentsRunningConfig,
    summary="Update agent running config",
    description="Update running configuration for active agent",
)
async def put_agents_running_config(
    running_config: AgentsRunningConfig = Body(
        ...,
        description="Updated agent running configuration",
    ),
    request: Request = None,
) -> AgentsRunningConfig:
    """Update agent running configuration."""
    workspace = await get_agent_for_request(request)
    from ...config.config import load_agent_config, save_agent_config

    agent_config = load_agent_config(workspace.agent_id)
    agent_config.running = running_config
    save_agent_config(workspace.agent_id, agent_config)

    # Hot reload config (async, non-blocking)
    import asyncio

    async def reload_in_background():
        try:
            manager = request.app.state.multi_agent_manager
            await manager.reload_agent(workspace.agent_id)
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(
                f"Background reload failed: {e}",
            )

    asyncio.create_task(reload_in_background())

    return running_config


@router.get(
    "/system-prompt-files",
    response_model=list[str],
    summary="Get system prompt files",
    description="Get system prompt files for active agent",
)
async def get_system_prompt_files(
    request: Request,
) -> list[str]:
    """Get list of enabled system prompt files."""
    workspace = await get_agent_for_request(request)
    from ...config.config import load_agent_config

    agent_config = load_agent_config(workspace.agent_id)
    return agent_config.system_prompt_files or []


@router.put(
    "/system-prompt-files",
    response_model=list[str],
    summary="Update system prompt files",
    description="Update system prompt files for active agent",
)
async def put_system_prompt_files(
    files: list[str] = Body(
        ...,
        description="Markdown filenames to load into system prompt",
    ),
    request: Request = None,
) -> list[str]:
    """Update list of enabled system prompt files."""
    workspace = await get_agent_for_request(request)
    from ...config.config import load_agent_config, save_agent_config

    agent_config = load_agent_config(workspace.agent_id)
    agent_config.system_prompt_files = files
    save_agent_config(workspace.agent_id, agent_config)

    # Hot reload config (async, non-blocking)
    import asyncio

    async def reload_in_background():
        try:
            manager = request.app.state.multi_agent_manager
            await manager.reload_agent(workspace.agent_id)
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(
                f"Background reload failed: {e}",
            )

    asyncio.create_task(reload_in_background())

    return files


@router.get(
    "/current-plan",
    response_model=PlanReadResponse,
    summary="Get current plan",
    description=(
        "Read current session plan from "
        "WORKING_DIR/todos/<user_id>/<session_id>/plan.json"
    ),
)
async def get_current_plan(
    session_id: str = Query(..., description="Session ID"),
    user_id: str = Query("default", description="User ID"),
) -> PlanReadResponse:
    """Return current plan content for a session/user."""
    safe_sid = _sanitize_filename(session_id)
    safe_uid = _sanitize_filename(user_id)
    plan_path = (
        Path(WORKING_DIR) / "todos" / safe_uid / safe_sid / "plan.json"
    )

    if not plan_path.exists():
        return PlanReadResponse(
            exists=False,
            file_path=str(plan_path),
            plan=None,
        )

    try:
        text = plan_path.read_text(encoding="utf-8")
        plan_json = json.loads(text) if text else None
        return PlanReadResponse(
            exists=True,
            file_path=str(plan_path),
            plan=plan_json,
        )
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid plan.json format: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/download-file",
    summary="Download file by local path or file URL",
    description=(
        "Download a local file by absolute path, plain path, "
        "or file:// URL."
    ),
)
async def download_file(
    file_path: str = Query(..., description="Local path or file:// URL"),
):
    """Stream a local file to browser download."""
    local_path = file_url_to_local_path(file_path)
    if not local_path:
        raise HTTPException(
            status_code=400,
            detail="Invalid local file path. "
            "Expect plain path or file:// URL.",
        )

    p = Path(local_path).expanduser()
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {p}")
    if not p.is_file():
        raise HTTPException(status_code=400, detail=f"Not a file: {p}")

    media_type, _ = mimetypes.guess_type(str(p))
    return FileResponse(
        path=str(p),
        filename=os.path.basename(str(p)),
        media_type=media_type or "application/octet-stream",
    )
