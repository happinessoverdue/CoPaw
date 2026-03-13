"""Docker API wrapper for managing GridPaw tenant containers.

Uses the docker Python SDK to create, start, stop, remove containers and
fetch logs. Expects /var/run/docker.sock to be mounted into the admin
container.
"""

import logging
from datetime import datetime, timezone

import docker
from docker.errors import APIError, NotFound

logger = logging.getLogger("gridpaw-admin.docker")

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
    extra_volumes: list | None = None,
    force_recreate: bool = False,
    secret_dir: str | None = None,
) -> tuple[bool, str]:
    """Create and start a container, or start it if it already exists (stopped).

    port: 容器内 CoPaw 监听端口（通常 8088），与 env 中的 COPAW_PORT 同源（main.py 用
         TENANT_INTERNAL_PORT 构造 env）。**当前未用于宿主机端口映射**：生产环境通过 Docker
         网络 + nginx 按容器名代理，无需映射到宿主机。保留此参数供将来「无 admin/nginx 时
         直连调试点」实现时使用。注意：若启用 host 映射，多租户默认同为 8088 会互相冲突，
         且易与宿主机既有服务抢端口。
    extra_volumes: list of {"host": "/host/path", "bind": "/container/path", "mode": "rw"}
    force_recreate: if True, remove existing container and create fresh (to apply new mounts)
    secret_dir: host path for GridPaw SECRET_DIR ({data_dir}.secret), mounted to /app/working.secret
    """
    client = _get_client()

    volumes = {data_dir: {"bind": "/app/working", "mode": "rw"}}
    if secret_dir:
        volumes[secret_dir] = {"bind": "/app/working.secret", "mode": "rw"}
    for m in extra_volumes or []:
        host = m.get("host", "").strip()
        bind = m.get("bind", "").strip()
        if host and bind:
            mode = m.get("mode", "rw")
            volumes[host] = {"bind": bind, "mode": mode}

    try:
        existing = client.containers.get(container_name)
        if existing.status == "running":
            if force_recreate:
                existing.stop(timeout=10)
                existing.remove(force=True)
            else:
                return True, "容器已在运行中"
        elif force_recreate:
            existing.remove(force=True)
        else:
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
            volumes=volumes,
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


def get_container_runtime_config(container_name: str) -> dict | None:
    """Get actual runtime config (name, mounts) from a running container.
    Returns None if container does not exist or is not running.
    Returns {"container_name": str, "mounts": [{"host": str, "bind": str, "mode": str}, ...]}
    """
    client = _get_client()
    try:
        container = client.containers.get(container_name)
        if container.status != "running":
            return None
        attrs = container.attrs or {}
        mounts_raw = attrs.get("Mounts") or []
        mounts = []
        for m in mounts_raw:
            mtype = m.get("Type", "")
            if mtype == "bind":
                host = m.get("Source", "")
                bind = m.get("Destination", "")
                mode_val = m.get("Mode", "")
                rw = m.get("RW", True)
                mode = "ro" if (mode_val == "ro" or not rw) else "rw"
                if host and bind:
                    mounts.append({"host": host, "bind": bind, "mode": mode})
        return {
            "container_name": container.name,
            "mounts": mounts,
        }
    except NotFound:
        return None
    except APIError:
        return None


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


def get_all_instance_statuses(prefix: str = "gridpaw-instance-") -> dict:
    """Return status for all containers whose name starts with prefix, as {name: status_dict}."""
    client = _get_client()
    result = {}
    try:
        containers = client.containers.list(all=True, filters={"name": prefix})
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
