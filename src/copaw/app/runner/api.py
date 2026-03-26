# -*- coding: utf-8 -*-
"""Chat management API."""
from __future__ import annotations
import json
from typing import Optional
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from agentscope.memory import InMemoryMemory

from ...config.config import load_agent_config
from ...agents.utils import get_copaw_token_counter
from .session import SafeJSONSession
from .manager import ChatManager
from .models import (
    ChatSpec,
    ChatHistory,
)
from .utils import agentscope_msg_to_message


router = APIRouter(prefix="/chats", tags=["chats"])


def _clamp_ratio(value: float) -> float:
    return max(0.0, min(value, 1.0))


async def _build_context_usage_meta(
    workspace,
    chat_spec: ChatSpec,
    state: dict,
) -> dict:
    agent_config = load_agent_config(workspace.agent_id)
    running = agent_config.running
    token_counter = get_copaw_token_counter(agent_config)

    max_input_tokens = max(int(running.max_input_length or 0), 0)
    compact_threshold_tokens = max(
        int(running.memory_compact_threshold or 0),
        0,
    )
    reserve_threshold_tokens = max(
        int(running.memory_compact_reserve or 0),
        0,
    )

    memories = state.get("agent", {}).get("memory", [])
    memory = InMemoryMemory()
    if memories:
        memory.load_state_dict(memories)
    messages = await memory.get_memory()
    compressed_summary = (
        memory.get_compressed_summary()
        if hasattr(memory, "get_compressed_summary")
        else ""
    )
    serialized_messages = json.dumps(
        [
            msg.to_dict() if hasattr(msg, "to_dict") else str(msg)
            for msg in messages
        ],
        ensure_ascii=False,
    )
    system_prompt = ""
    agent_state = state.get("agent", {})
    if isinstance(agent_state, dict):
        for key in ("_sys_prompt", "sys_prompt"):
            value = agent_state.get(key)
            if isinstance(value, str) and value.strip():
                system_prompt = value
                break

    system_prompt_tokens = await token_counter.count(messages=[], text=system_prompt or "")
    summary_tokens = await token_counter.count(messages=[], text=compressed_summary or "")
    messages_tokens = await token_counter.count(messages=[], text=serialized_messages)
    used_tokens = system_prompt_tokens + summary_tokens + messages_tokens

    context_usage = {
        "session_id": chat_spec.session_id,
        "user_id": chat_spec.user_id,
        "used_tokens": used_tokens,
        "max_input_tokens": max_input_tokens,
        "compact_threshold_tokens": compact_threshold_tokens,
        "reserve_threshold_tokens": reserve_threshold_tokens,
        "system_prompt_tokens": system_prompt_tokens,
        "summary_tokens": summary_tokens,
        "messages_tokens": messages_tokens,
        "message_count": len(messages),
        "usage_ratio": (
            _clamp_ratio(used_tokens / max_input_tokens)
            if max_input_tokens > 0
            else 0
        ),
        "compact_ratio": (
            _clamp_ratio(used_tokens / compact_threshold_tokens)
            if compact_threshold_tokens > 0
            else 0
        ),
        "compact_threshold_ratio": (
            compact_threshold_tokens / max_input_tokens
            if max_input_tokens > 0
            else 0
        ),
        "has_compressed_summary": bool(compressed_summary),
    }
    latest_usage = {
        "input_tokens": used_tokens,
        "output_tokens": 0,
        "source": "estimated_history",
    }

    return {
        **(chat_spec.meta or {}),
        "latest_usage": latest_usage,
        "context_usage": context_usage,
    }


async def get_workspace(request: Request):
    """Get the workspace for the active agent."""
    from ..agent_context import get_agent_for_request

    return await get_agent_for_request(request)


async def get_chat_manager(
    request: Request,
) -> ChatManager:
    """Get the chat manager for the active agent.

    Args:
        request: FastAPI request object

    Returns:
        ChatManager instance for the specified agent

    Raises:
        HTTPException: If manager is not initialized
    """
    workspace = await get_workspace(request)
    return workspace.chat_manager


async def get_session(
    request: Request,
) -> SafeJSONSession:
    """Get the session for the active agent.

    Args:
        request: FastAPI request object

    Returns:
        SafeJSONSession instance for the specified agent

    Raises:
        HTTPException: If session is not initialized
    """
    workspace = await get_workspace(request)
    return workspace.runner.session


@router.get("", response_model=list[ChatSpec])
async def list_chats(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    channel: Optional[str] = Query(None, description="Filter by channel"),
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """List all chats with optional filters.

    Args:
        user_id: Optional user ID to filter chats
        channel: Optional channel name to filter chats
        mgr: Chat manager dependency
    """
    chats = await mgr.list_chats(user_id=user_id, channel=channel)
    tracker = workspace.task_tracker
    result = []
    for spec in chats:
        status = await tracker.get_status(spec.id)
        result.append(spec.model_copy(update={"status": status}))
    return result


@router.post("", response_model=ChatSpec)
async def create_chat(
    request: ChatSpec,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Create a new chat.

    Server generates chat_id (UUID) automatically.

    Args:
        request: Chat creation request
        mgr: Chat manager dependency

    Returns:
        Created chat spec with UUID
    """
    chat_id = str(uuid4())
    spec = ChatSpec(
        id=chat_id,
        name=request.name,
        session_id=request.session_id,
        user_id=request.user_id,
        channel=request.channel,
        meta=request.meta,
    )
    return await mgr.create_chat(spec)


@router.post("/batch-delete", response_model=dict)
async def batch_delete_chats(
    chat_ids: list[str],
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Delete chats by chat IDs.

    Args:
        chat_ids: List of chat IDs
        mgr: Chat manager dependency
    Returns:
        True if deleted, False if failed

    """
    deleted = await mgr.delete_chats(chat_ids=chat_ids)
    return {"deleted": deleted}


@router.get("/{chat_id}", response_model=ChatHistory)
async def get_chat(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    session: SafeJSONSession = Depends(get_session),
    workspace=Depends(get_workspace),
):
    """Get detailed information about a specific chat by UUID.

    Args:
        request: FastAPI request (for agent context)
        chat_id: Chat UUID
        mgr: Chat manager dependency
        session: SafeJSONSession dependency

    Returns:
        ChatHistory with messages and status (idle/running)

    Raises:
        HTTPException: If chat not found (404)
    """
    chat_spec = await mgr.get_chat(chat_id)
    if not chat_spec:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )

    state = await session.get_session_state_dict(
        chat_spec.session_id,
        chat_spec.user_id,
    )
    status = await workspace.task_tracker.get_status(chat_id)
    # --- GridPaw: start --- Include ChatSpec fields for frontend reconnect (logical session_id)
    _spec_kwargs = {
        "session_id": chat_spec.session_id,
        "user_id": chat_spec.user_id,
        "channel": chat_spec.channel,
        "meta": chat_spec.meta or {},
    }
    # --- GridPaw: end ---
    if not state:
        return ChatHistory(messages=[], status=status, **_spec_kwargs)
    _spec_kwargs["meta"] = await _build_context_usage_meta(
        workspace,
        chat_spec,
        state,
    )
    memories = state.get("agent", {}).get("memory", [])
    memory = InMemoryMemory()
    memory.load_state_dict(memories)

    memories = await memory.get_memory()
    messages = agentscope_msg_to_message(memories)
    return ChatHistory(messages=messages, status=status, **_spec_kwargs)


@router.put("/{chat_id}", response_model=ChatSpec)
async def update_chat(
    chat_id: str,
    spec: ChatSpec,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Update an existing chat.

    Args:
        chat_id: Chat UUID
        spec: Updated chat specification
        mgr: Chat manager dependency

    Returns:
        Updated chat spec

    Raises:
        HTTPException: If chat_id mismatch (400) or not found (404)
    """
    if spec.id != chat_id:
        raise HTTPException(
            status_code=400,
            detail="chat_id mismatch",
        )

    # Check if exists
    existing = await mgr.get_chat(chat_id)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )

    updated = await mgr.update_chat(spec)
    return updated


@router.delete("/{chat_id}", response_model=dict)
async def delete_chat(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Delete a chat by UUID.

    Note: This only deletes the chat spec (UUID mapping).
    JSONSession state is NOT deleted.

    Args:
        chat_id: Chat UUID
        mgr: Chat manager dependency

    Returns:
        True if deleted, False if failed

    Raises:
        HTTPException: If chat not found (404)
    """
    deleted = await mgr.delete_chats(chat_ids=[chat_id])
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    return {"deleted": True}
