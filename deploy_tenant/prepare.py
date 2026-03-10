#!/usr/bin/env python3
"""CoPaw Multi-Tenant Deployment Preparation Tool.

Handles image building, export/import for offline deployment, and initial
compose startup. Runtime tenant management is handled by the admin Web UI.

推荐优先使用 prepare.sh（Bash 版本，无需 Python）。本脚本适用于无 Bash 环境。

Usage:
    python prepare.py build       Build all Docker images
    python prepare.py export      Export images to tar files (for offline transfer)
    python prepare.py import [dir] Import images from tar files
    python prepare.py up          Start nginx + admin services
    python prepare.py down        Stop all services
    python prepare.py restart [nginx|admin]  Restart services (default: all)
    python prepare.py status      Show container status
    python prepare.py logs [svc]  Show logs (optionally for a specific service)
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Union

SCRIPT_DIR = Path(__file__).resolve().parent
COMPOSE_FILE = SCRIPT_DIR / "docker-compose.yml"
IMAGES_DIR = SCRIPT_DIR / "images"
REPO_ROOT = SCRIPT_DIR.parent

COPAW_IMAGE = os.environ.get("COPAW_IMAGE", "gridpaw-tenant:latest")


def _color(text: str, code: str) -> str:
    if sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text


def green(text: str) -> str:
    return _color(text, "32")


def red(text: str) -> str:
    return _color(text, "31")


def run(args: List[str], check: bool = True) -> int:
    result = subprocess.run(args)
    if check and result.returncode != 0:
        print(red(f"ERROR: Command failed (exit {result.returncode}): {' '.join(str(a) for a in args)}"))
        sys.exit(result.returncode)
    return result.returncode


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

BUILD_TARGETS = ("nginx", "admin", "copaw")


def _build_nginx() -> None:
    print("==> Building nginx image: gridpaw-nginx:latest")
    run([
        "docker", "build",
        "-f", str(SCRIPT_DIR / "nginx" / "Dockerfile"),
        "-t", "gridpaw-nginx:latest",
        str(SCRIPT_DIR / "nginx"),
    ])


def _build_admin() -> None:
    print("==> Building admin image: gridpaw-admin:latest")
    run([
        "docker", "build",
        "-f", str(SCRIPT_DIR / "admin-service" / "Dockerfile"),
        "-t", "gridpaw-admin:latest",
        str(SCRIPT_DIR),
    ])


def _build_copaw() -> None:
    copaw_dockerfile = SCRIPT_DIR / "copaw.Dockerfile"
    print(f"==> Building CoPaw image: {COPAW_IMAGE}")
    print(f"    Dockerfile: {copaw_dockerfile}")
    print(f"    Context: {REPO_ROOT}")
    run([
        "docker", "build", "-f", str(copaw_dockerfile),
        "-t", COPAW_IMAGE, str(REPO_ROOT),
    ])


def cmd_build(targets: Optional[List[str]] = None) -> None:
    """Build Docker images. If targets given, build only those; else build all.

    Targets: nginx (build), admin, copaw
    Example: python prepare.py build admin    # rebuild admin only
    """
    if targets:
        invalid = [t for t in targets if t not in BUILD_TARGETS]
        if invalid:
            print(red(f"ERROR: 未知构建目标: {', '.join(invalid)}"))
            print(red(f"  可选: {', '.join(BUILD_TARGETS)}"))
            sys.exit(1)
        to_build = targets
    else:
        to_build = list(BUILD_TARGETS)

    if "nginx" in to_build:
        _build_nginx()
    if "admin" in to_build:
        _build_admin()
    if "copaw" in to_build:
        _build_copaw()

    print(green("==> Build complete."))
    if to_build:
        built = []
        if "nginx" in to_build:
            built.append("gridpaw-nginx:latest")
        if "admin" in to_build:
            built.append("gridpaw-admin:latest")
        if "copaw" in to_build:
            built.append(COPAW_IMAGE)
        print(green(f"    Built: {', '.join(built)}"))


# ---------------------------------------------------------------------------
# export / import
# ---------------------------------------------------------------------------

def cmd_export() -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"==> Exporting images to {IMAGES_DIR}/ ...")

    for name, filename in [
        ("gridpaw-nginx:latest", "gridpaw-nginx.tar"),
        ("gridpaw-admin:latest", "gridpaw-admin.tar"),
        (COPAW_IMAGE, "gridpaw-tenant.tar"),
    ]:
        print(f"  -> {name}")
        run(["docker", "save", name, "-o", str(IMAGES_DIR / filename)])

    print(green("==> Export complete. Files:"))
    for f in sorted(IMAGES_DIR.glob("*.tar")):
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"    {f.name}  ({size_mb:.1f} MB)")
    print()
    print("Transfer these files to the intranet server, then run:")
    print("  python prepare.py import")


def cmd_import(images_dir: Optional[Union[str, Path]] = None) -> None:
    dir_path = Path(images_dir).resolve() if images_dir else IMAGES_DIR

    if not dir_path.exists():
        print(red(f"ERROR: 目录不存在: {dir_path}"))
        sys.exit(1)
    if not dir_path.is_dir():
        print(red(f"ERROR: 不是有效目录: {dir_path}"))
        sys.exit(1)

    print(f"==> Importing images from {dir_path}/ ...")

    tar_files = sorted(dir_path.glob("*.tar"))
    if not tar_files:
        print(red(f"ERROR: 目录下没有找到 .tar 文件: {dir_path}"))
        sys.exit(1)

    for tarfile in tar_files:
        print(f"  -> {tarfile.name}")
        run(["docker", "load", "-i", str(tarfile)])

    print(green("==> Import complete."))
    result = subprocess.run(["docker", "images"], capture_output=True, text=True, check=False)
    for line in (result.stdout or "").splitlines():
        if "nginx" in line or "gridpaw" in line:
            print(line)


# ---------------------------------------------------------------------------
# Docker Compose wrappers
# ---------------------------------------------------------------------------

def cmd_up() -> None:
    print("==> Starting services (nginx + admin) ...")
    run(["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"])
    print(green("==> Services started."))
    print(green("    Admin panel: http://localhost:<NGINX_PORT>/admin/"))
    print(green("    (Check .env for the actual NGINX_PORT value)"))


def cmd_down() -> None:
    print("==> Stopping all services ...")
    run(["docker", "compose", "-f", str(COMPOSE_FILE), "down"])
    print(green("==> All services stopped."))


def cmd_restart(services: Optional[List[str]] = None) -> None:
    """Restart services. If services given, restart only those; else restart all."""
    valid = {"nginx", "admin"}
    if services:
        invalid = [s for s in services if s not in valid]
        if invalid:
            print(red(f"ERROR: 未知服务: {', '.join(invalid)}"))
            print(red(f"  可选: nginx, admin"))
            sys.exit(1)
        svc = services
        print(f"==> Restarting: {', '.join(svc)} ...")
    else:
        svc = []
        print("==> Restarting all services ...")
    run(["docker", "compose", "-f", str(COMPOSE_FILE), "restart", *svc])
    print(green("==> Restart complete."))


def cmd_status() -> None:
    run(["docker", "compose", "-f", str(COMPOSE_FILE), "ps"])


def cmd_logs(service: str = "") -> None:
    if service:
        run(["docker", "compose", "-f", str(COMPOSE_FILE), "logs", "-f", service])
    else:
        run(["docker", "compose", "-f", str(COMPOSE_FILE), "logs", "-f"])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

COMMANDS = {
    "build":   (cmd_build,   "Build images [nginx|admin|copaw] (default: all)"),
    "export":  (cmd_export,  "Export images to tar files (for offline transfer)"),
    "import":  (cmd_import,  "Import images from tar files [images_dir]"),
    "up":      (cmd_up,      "Start nginx + admin services"),
    "down":    (cmd_down,    "Stop all services"),
    "restart": (cmd_restart, "Restart services [nginx|admin] (default: all)"),
    "status":  (cmd_status,  "Show container status"),
    "logs":    (cmd_logs,    "Show logs (optionally for a specific service)"),
}


def print_help() -> None:
    print("CoPaw 多租户部署准备工具")
    print("用法: python prepare.py <命令> [参数]")
    print()
    print("命令:")
    for name, (_, desc) in COMMANDS.items():
        print(f"  {name:<12} {desc}")
    print()
    print("典型操作流程:")
    print("  build 可指定目标，避免全量重建:")
    print("    python prepare.py build admin   # 仅重建 admin（如改了 login.html）")
    print("    python prepare.py build copaw   # 仅重建 CoPaw 镜像")
    print()
    print("  【首次部署（有网络）】")
    print("    1. 编辑 .env（端口、密钥、镜像名等）")
    print("    2. python prepare.py build      # 构建所有镜像")
    print("    3. python prepare.py up         # 启动 nginx + admin")
    print("    4. 浏览器访问管理页面，添加租户并启动实例")
    print()
    print("  【离线服务器部署】")
    print("  在有网机器上:")
    print("    1. python prepare.py build      # 构建镜像")
    print("    2. python prepare.py export     # 导出到 images/*.tar")
    print("    3. 将整个 deploy_tenant 目录拷贝到离线服务器")
    print()
    print("  在离线服务器上:")
    print("    4. python prepare.py import     # 导入镜像")
    print("    5. 编辑 .env（按环境调整端口等）")
    print("    6. python prepare.py up         # 启动服务")
    print("    7. 浏览器访问管理页面，添加租户并启动实例")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "-h", "--help"):
        print_help()
        return

    cmd_name = sys.argv[1]
    if cmd_name not in COMMANDS:
        print(red(f"Unknown command: {cmd_name}"))
        print()
        print_help()
        sys.exit(1)

    cmd_func = COMMANDS[cmd_name][0]

    if cmd_name == "logs" and len(sys.argv) > 2:
        cmd_func(sys.argv[2])
    elif cmd_name == "import" and len(sys.argv) > 2:
        cmd_func(sys.argv[2])
    elif cmd_name in ("build", "restart"):
        cmd_func(sys.argv[2:] if len(sys.argv) > 2 else None)
    else:
        cmd_func()


if __name__ == "__main__":
    main()
