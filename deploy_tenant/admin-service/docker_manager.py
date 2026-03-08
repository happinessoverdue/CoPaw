"""Docker API wrapper for managing CoPaw tenant containers.

Uses the docker Python SDK to create, start, stop, remove containers and
fetch logs. Expects /var/run/docker.sock to be mounted into the admin
container.
"""

import logging
from datetime import datetime, timezone

import docker
from docker.errors import APIError, NotFound

logger = logging.getLogger("copaw-admin.docker")

_client: docker.DockerClient | None = None


def init_client() -> None:
    global _client
    try:
        _client = docker.from_env()
        _client.ping()
        logger.info("Docker client connected")
    except Exception as e:
        logger.error("Failed to connect to Docker: %s", e)
        _client = None


def _get_client() -> docker.DockerClient:
    if _client is None:
        raise RuntimeError("Docker client not initialized")
    return _client


# ---------------------------------------------------------------------------
# Container lifecycle
# ---------------------------------------------------------------------------

def create_and_start_container(
    container_name: str,
    image: str,
    data_dir: str,
    port: int,
    network: str,
    env: dict | None = None,
) -> tuple[bool, str]:
    """Create and start a container, or start it if it already exists (stopped)."""
    client = _get_client()

    try:
        existing = client.containers.get(container_name)
        if existing.status == "running":
            return True, "容器已在运行中"
        existing.start()
        logger.info("Started existing container: %s", container_name)
        return True, "容器已启动（从已停止状态恢复）"
    except NotFound:
        pass
    except APIError as e:
        return False, f"启动已有容器失败: {e}"

    try:
        env_list = {k: str(v) for k, v in (env or {}).items()}
        container = client.containers.run(
            image=image,
            name=container_name,
            detach=True,
            network=network,
            volumes={data_dir: {"bind": "/app/working", "mode": "rw"}},
            environment=env_list,
            restart_policy={"Name": "unless-stopped"},
        )
        logger.info("Created and started container: %s (id=%s)", container_name, container.short_id)
        return True, "容器创建并启动成功"
    except APIError as e:
        logger.error("Failed to create container %s: %s", container_name, e)
        return False, f"创建容器失败: {e}"


def stop_container(container_name: str, timeout: int = 10) -> tuple[bool, str]:
    client = _get_client()
    try:
        container = client.containers.get(container_name)
        if container.status != "running":
            return True, "容器未在运行"
        container.stop(timeout=timeout)
        logger.info("Stopped container: %s", container_name)
        return True, "容器已停止"
    except NotFound:
        return True, "容器不存在"
    except APIError as e:
        logger.error("Failed to stop %s: %s", container_name, e)
        return False, f"停止容器失败: {e}"


def remove_container(container_name: str) -> tuple[bool, str]:
    client = _get_client()
    try:
        container = client.containers.get(container_name)
        container.remove(force=True)
        logger.info("Removed container: %s", container_name)
        return True, "容器已删除"
    except NotFound:
        return True, "容器不存在"
    except APIError as e:
        logger.error("Failed to remove %s: %s", container_name, e)
        return False, f"删除容器失败: {e}"


def restart_container(container_name: str, timeout: int = 10) -> tuple[bool, str]:
    client = _get_client()
    try:
        container = client.containers.get(container_name)
        container.restart(timeout=timeout)
        logger.info("Restarted container: %s", container_name)
        return True, "容器已重启"
    except NotFound:
        return False, "容器不存在，请先启动"
    except APIError as e:
        logger.error("Failed to restart %s: %s", container_name, e)
        return False, f"重启容器失败: {e}"


# ---------------------------------------------------------------------------
# Status queries
# ---------------------------------------------------------------------------

def _format_running_for(started_at_str: str) -> str:
    """Convert a Docker started_at timestamp to a human-readable duration."""
    try:
        started = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - started
        total_seconds = int(delta.total_seconds())
        if total_seconds < 60:
            return f"{total_seconds}s"
        minutes = total_seconds // 60
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        remaining_minutes = minutes % 60
        if hours < 24:
            return f"{hours}h {remaining_minutes}m"
        days = hours // 24
        remaining_hours = hours % 24
        return f"{days}d {remaining_hours}h"
    except Exception:
        return ""


def get_container_status(container_name: str) -> dict:
    client = _get_client()
    try:
        container = client.containers.get(container_name)
        attrs = container.attrs or {}
        state = attrs.get("State", {})
        status = container.status
        running_for = ""
        if status == "running":
            running_for = _format_running_for(state.get("StartedAt", ""))
        return {
            "status": status,
            "running_for": running_for,
            "container_id": container.short_id,
        }
    except NotFound:
        return {"status": "not_found", "running_for": "", "container_id": ""}
    except APIError:
        return {"status": "error", "running_for": "", "container_id": ""}


def get_all_instance_statuses() -> dict:
    """Return status for all copaw-instance-* containers as {name: status_dict}."""
    client = _get_client()
    result = {}
    try:
        containers = client.containers.list(all=True, filters={"name": "copaw-instance-"})
        for c in containers:
            attrs = c.attrs or {}
            state = attrs.get("State", {})
            running_for = ""
            if c.status == "running":
                running_for = _format_running_for(state.get("StartedAt", ""))
            result[c.name] = {
                "status": c.status,
                "running_for": running_for,
                "container_id": c.short_id,
            }
    except APIError as e:
        logger.error("Failed to list containers: %s", e)
    return result


def get_container_logs(container_name: str, tail: int = 200) -> tuple[bool, str]:
    client = _get_client()
    try:
        container = client.containers.get(container_name)
        logs = container.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
        return True, logs
    except NotFound:
        return False, "容器不存在"
    except APIError as e:
        return False, f"获取日志失败: {e}"
