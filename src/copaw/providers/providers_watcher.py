# -*- coding: utf-8 -*-
"""Watcher for providers and envs config hot-reload (GridPaw custom).

Monitors providers.json, providers/*.json, and envs.json. Uses mtime + hash
(like MCPConfigWatcher) to avoid false triggers. When files change, reloads
ProviderManager and envs into os.environ so distributed config takes effect
without restart. Self-contained to minimize merge conflicts with upstream.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from .provider_manager import ProviderManager
from ..constant import SECRET_DIR
from ..envs.store import get_envs_json_path, load_envs, reload_envs_from_disk

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 10.0


def _get_providers_max_mtime() -> float:
    """Max mtime of providers.json and all JSON under providers/."""
    mtimes: list[float] = []
    legacy = SECRET_DIR / "providers.json"
    if legacy.exists() and legacy.is_file():
        mtimes.append(legacy.stat().st_mtime)
    providers_dir = SECRET_DIR / "providers"
    if providers_dir.exists() and providers_dir.is_dir():
        for p in providers_dir.rglob("*.json"):
            if p.is_file():
                mtimes.append(p.stat().st_mtime)
    return max(mtimes) if mtimes else 0.0


def _get_providers_content_hash() -> int:
    """Hash of providers config files content for change detection."""
    parts: list[tuple[str, str]] = []
    legacy = SECRET_DIR / "providers.json"
    if legacy.exists() and legacy.is_file():
        try:
            with open(legacy, "r", encoding="utf-8") as f:
                parts.append((str(legacy), json.dumps(json.load(f), sort_keys=True)))
        except Exception:
            parts.append((str(legacy), ""))
    providers_dir = SECRET_DIR / "providers"
    if providers_dir.exists() and providers_dir.is_dir():
        for p in sorted(providers_dir.rglob("*.json")):
            if p.is_file():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        parts.append((str(p), json.dumps(json.load(f), sort_keys=True)))
                except Exception:
                    parts.append((str(p), ""))
    return hash("|".join(f"{path}:{cnt}" for path, cnt in sorted(parts)))


def _get_envs_json_mtime() -> float:
    """mtime of envs.json."""
    path = get_envs_json_path()
    if path.exists() and path.is_file():
        return path.stat().st_mtime
    return 0.0


def _get_envs_content_hash() -> int:
    """Hash of envs.json content for change detection."""
    envs = load_envs()
    return hash(json.dumps(envs, sort_keys=True))


class ProvidersConfigWatcher:
    """Watch providers and envs config files; hot-reload on change (mtime + hash)."""

    def __init__(
        self,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ):
        self._poll_interval = poll_interval
        self._last_providers_mtime: float = 0.0
        self._last_providers_hash: Optional[int] = None
        self._last_envs_mtime: float = 0.0
        self._last_envs_hash: Optional[int] = None
        self._task: Optional[asyncio.Task] = None
        self._reload_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Take initial snapshot and start polling."""
        self._last_providers_mtime = _get_providers_max_mtime()
        self._last_envs_mtime = _get_envs_json_mtime()
        try:
            self._last_providers_hash = _get_providers_content_hash()
        except Exception:
            self._last_providers_hash = None
        try:
            self._last_envs_hash = _get_envs_content_hash()
        except Exception:
            self._last_envs_hash = None
        self._task = asyncio.create_task(
            self._poll_loop(),
            name="providers_config_watcher",
        )
        logger.debug(
            "ProvidersConfigWatcher started (poll=%.1fs, providers+envs)",
            self._poll_interval,
        )

    async def stop(self) -> None:
        """Stop the polling task and wait for any ongoing reload."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._reload_task and not self._reload_task.done():
            try:
                await asyncio.wait_for(self._reload_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._reload_task.cancel()
            self._reload_task = None
        logger.debug("ProvidersConfigWatcher stopped")

    async def _poll_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._poll_interval)
                await self._check()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "ProvidersConfigWatcher: poll iteration failed",
                )

    async def _check(self) -> None:
        """Check mtime + hash for providers and envs; reload if changed."""
        providers_reload = False
        envs_reload = False

        # Providers: mtime changed -> hash -> if hash changed, reload
        prov_mtime = _get_providers_max_mtime()
        if prov_mtime != self._last_providers_mtime:
            self._last_providers_mtime = prov_mtime
            try:
                new_hash = _get_providers_content_hash()
                if new_hash != self._last_providers_hash:
                    self._last_providers_hash = new_hash
                    providers_reload = True
            except Exception:
                self._last_providers_hash = None

        # Envs: mtime changed -> hash -> if hash changed, reload
        envs_mtime = _get_envs_json_mtime()
        if envs_mtime != self._last_envs_mtime:
            self._last_envs_mtime = envs_mtime
            try:
                new_hash = _get_envs_content_hash()
                if new_hash != self._last_envs_hash:
                    self._last_envs_hash = new_hash
                    envs_reload = True
            except Exception:
                self._last_envs_hash = None

        if not providers_reload and not envs_reload:
            return

        if self._reload_task and not self._reload_task.done():
            logger.debug(
                "ProvidersConfigWatcher: skipping reload, previous still in progress",
            )
            return

        logger.debug(
            "ProvidersConfigWatcher: detected config change (providers=%s envs=%s), reloading",
            providers_reload,
            envs_reload,
        )
        self._reload_task = asyncio.create_task(
            self._do_reload(providers_reload, envs_reload),
            name="providers_reload_task",
        )
        try:
            await self._reload_task
        except Exception:
            pass
        self._reload_task = None

    async def _do_reload(
        self,
        providers: bool,
        envs: bool,
    ) -> None:
        """Run reload in thread to avoid blocking event loop."""
        def _sync_reload() -> None:
            if providers:
                ProviderManager.get_instance().reload_from_disk()
            if envs:
                reload_envs_from_disk()

        try:
            await asyncio.to_thread(_sync_reload)
            msg_parts = []
            if providers:
                msg_parts.append("providers")
            if envs:
                msg_parts.append("envs")
            logger.info(
                "ProvidersConfigWatcher: reload completed (%s)",
                ", ".join(msg_parts),
            )
        except Exception:
            logger.warning(
                "ProvidersConfigWatcher: reload failed",
                exc_info=True,
            )
