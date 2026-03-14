#!/usr/bin/env python3
"""GridPaw 多租户部署准备工具.

Handles image building, export/import for offline deployment, and initial
compose startup. Runtime tenant management is handled by the admin Web UI.

推荐优先使用 prepare.sh（Bash 版本，无需 Python）。本脚本适用于无 Bash 环境。

Usage:
    python prepare.py build [targets] [-p|--platform amd64|arm64]  Build images; -p for cross-platform (output to images/<arch>/)
    python prepare.py export      Export images to tar files (for offline transfer)
    python prepare.py import [dir] Import images from tar files
    python prepare.py up [nginx|admin]     Create and start (default: all)
    python prepare.py down [nginx|admin]    Stop and remove (default: all)
    python prepare.py start [nginx|admin]  Start existing (default: all)
    python prepare.py stop [nginx|admin]   Stop (default: all)
    python prepare.py restart [nginx|admin]  Restart (default: all)
    python prepare.py status      Show container status
    python prepare.py logs [svc]  Show logs (optionally for a specific service)
    python prepare.py prune       Remove dangling images (from rebuild)
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


def _read_env(key: str, default: str = "") -> str:
    """从 .env 文件读取指定 key 的值（与 docker compose 保持一致，不依赖系统环境变量）。"""
    env_file = SCRIPT_DIR / ".env"
    try:
        for line in env_file.read_text().splitlines():
            line = line.split("#")[0].strip()
            if line.startswith(f"{key}="):
                return line[len(key) + 1:].strip()
    except FileNotFoundError:
        pass
    return default


TENANT_IMAGE = _read_env("TENANT_IMAGE") or "gridpaw-tenant:latest"
NGINX_PORT = _read_env("NGINX_PORT") or "8087"


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

BUILD_TARGETS = ("nginx", "admin", "gridpaw")
EXPORT_TARGETS = ("nginx", "admin", "gridpaw")
BUILDX_BUILDER = "gridpaw-multiarch"


def _normalize_platform(raw: str) -> str:
    """解析平台简写，返回 linux/amd64 或 linux/arm64."""
    m = {
        "linux/amd64": "linux/amd64", "amd64": "linux/amd64", "amd": "linux/amd64",
        "linux/arm64": "linux/arm64", "arm64": "linux/arm64", "arm": "linux/arm64",
    }
    if raw.lower() in m:
        return m[raw.lower()]
    print(red(f"ERROR: 不支持的平台: {raw}"))
    print(red("  可选: linux/amd64, amd64, amd | linux/arm64, arm64, arm"))
    sys.exit(1)
    return ""  # unreachable


def _platform_short_name(platform: str) -> str:
    if platform == "linux/amd64":
        return "amd64"
    if platform == "linux/arm64":
        return "arm64"
    return platform.replace("/", "_")


def _detect_arch() -> str:
    """检测当前平台架构，返回 amd64 或 arm64（用于 export 目录）."""
    try:
        import platform as pl
        m = (pl.machine() or "").lower()
    except Exception:
        result = subprocess.run(["uname", "-m"], capture_output=True, text=True, check=False)
        m = (result.stdout or "").strip().lower()
    if m in ("x86_64", "amd64"):
        return "amd64"
    if m in ("aarch64", "arm64", "armv8", "armv8l", "armv8b"):
        return "arm64"
    return "amd64"  # 未知时默认


def _ensure_buildx_builder() -> None:
    """确保存在支持 type=docker,dest= 的 buildx builder（需 docker-container 驱动）."""
    result = subprocess.run(
        ["docker", "buildx", "inspect", BUILDX_BUILDER],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"==> 创建 buildx builder '{BUILDX_BUILDER}'（首次跨平台构建需此步骤）...")
        run(["docker", "buildx", "create", "--name", BUILDX_BUILDER, "--driver", "docker-container", "--use"])
    else:
        subprocess.run(["docker", "buildx", "use", BUILDX_BUILDER], capture_output=True)


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


def _build_gridpaw() -> None:
    gridpaw_dockerfile = SCRIPT_DIR / "gridpaw.Dockerfile"
    print(f"==> Building GridPaw tenant image: {TENANT_IMAGE}")
    print(f"    Dockerfile: {gridpaw_dockerfile}")
    print(f"    Context: {REPO_ROOT}")
    run([
        "docker", "build", "-f", str(gridpaw_dockerfile),
        "-t", TENANT_IMAGE, str(REPO_ROOT),
    ])


def _build_nginx_cross(platform: str, out_dir: Path) -> None:
    tar_file = out_dir / "gridpaw-nginx.tar"
    print(f"==> Building nginx ({platform}) -> {tar_file}")
    run([
        "docker", "buildx", "build",
        "--platform", platform,
        "-f", str(SCRIPT_DIR / "nginx" / "Dockerfile"),
        "-t", "gridpaw-nginx:latest",
        f"--output=type=docker,dest={tar_file}",
        str(SCRIPT_DIR / "nginx"),
    ])


def _build_admin_cross(platform: str, out_dir: Path) -> None:
    tar_file = out_dir / "gridpaw-admin.tar"
    print(f"==> Building admin ({platform}) -> {tar_file}")
    run([
        "docker", "buildx", "build",
        "--platform", platform,
        "-f", str(SCRIPT_DIR / "admin-service" / "Dockerfile"),
        "-t", "gridpaw-admin:latest",
        f"--output=type=docker,dest={tar_file}",
        str(SCRIPT_DIR),
    ])


def _build_gridpaw_cross(platform: str, out_dir: Path) -> None:
    tar_file = out_dir / "gridpaw-tenant.tar"
    print(f"==> Building GridPaw tenant ({platform}) -> {tar_file}")
    print(f"    Image tag in tar: {TENANT_IMAGE}")
    run([
        "docker", "buildx", "build",
        "--platform", platform,
        "-f", str(SCRIPT_DIR / "gridpaw.Dockerfile"),
        "-t", TENANT_IMAGE,
        f"--output=type=docker,dest={tar_file}",
        str(REPO_ROOT),
    ])


def _parse_build_args(args: Optional[List[str]]) -> tuple[List[str], Optional[str]]:
    """从 build 参数中解析 targets 和 platform。返回 (targets, platform)."""
    if not args:
        return (list(BUILD_TARGETS), None)
    targets: List[str] = []
    platform: Optional[str] = None
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-p", "--platform"):
            if i + 1 >= len(args):
                print(red("ERROR: --platform 需要指定值，如 amd64 或 arm64"))
                sys.exit(1)
            platform = _normalize_platform(args[i + 1])
            i += 2
            continue
        if a.startswith("-"):
            print(red(f"ERROR: 未知选项: {a}"))
            sys.exit(1)
        if a in BUILD_TARGETS:
            targets.append(a)
        else:
            print(red(f"ERROR: 未知构建目标: {a}"))
            print(red(f"  可选: {', '.join(BUILD_TARGETS)}"))
            sys.exit(1)
        i += 1
    if not targets:
        targets = list(BUILD_TARGETS)
    return (targets, platform)


def cmd_build(args: Optional[List[str]] = None) -> None:
    """Build Docker images. If targets given, build only those; else build all.

    支持 -p/--platform <平台> 跨平台构建，输出到 images/<arch>/（不加载到本地）。
    平台: linux/amd64, amd64, amd | linux/arm64, arm64, arm

    Example:
        python prepare.py build admin
        python prepare.py build -p amd64
    """
    to_build, platform = _parse_build_args(args)

    if platform:
        # 跨平台构建：输出到 images/<arch>/
        short_name = _platform_short_name(platform)
        out_dir = IMAGES_DIR / short_name
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"==> 跨平台构建: {platform} -> {out_dir}/")
        _ensure_buildx_builder()
        if "nginx" in to_build:
            _build_nginx_cross(platform, out_dir)
        if "admin" in to_build:
            _build_admin_cross(platform, out_dir)
        if "gridpaw" in to_build:
            _build_gridpaw_cross(platform, out_dir)
        print(green(f"==> Build complete. 镜像已保存到: {out_dir}/"))
        for f in sorted(out_dir.glob("*.tar")):
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"    {f.name}  ({size_mb:.1f} MB)")
        print()
        print(f"  传输到目标服务器后执行: python prepare.py import {out_dir}")
    else:
        # 本机构建：加载到 Docker
        if "nginx" in to_build:
            _build_nginx()
        if "admin" in to_build:
            _build_admin()
        if "gridpaw" in to_build:
            _build_gridpaw()
        print(green("==> Build complete."))
        if to_build:
            built = []
            if "nginx" in to_build:
                built.append("gridpaw-nginx:latest")
            if "admin" in to_build:
                built.append("gridpaw-admin:latest")
            if "gridpaw" in to_build:
                built.append(TENANT_IMAGE)
            print(green(f"    Built: {', '.join(built)}"))


# ---------------------------------------------------------------------------
# export / import
# ---------------------------------------------------------------------------

def cmd_export(targets: Optional[List[str]] = None) -> None:
    """Export Docker images to tar files. If targets given, export only those; else export all."""
    if targets:
        invalid = [t for t in targets if t not in EXPORT_TARGETS]
        if invalid:
            print(red(f"ERROR: 未知导出目标: {', '.join(invalid)}"))
            print(red(f"  可选: {', '.join(EXPORT_TARGETS)}"))
            sys.exit(1)
        to_export = targets
    else:
        to_export = list(EXPORT_TARGETS)

    arch = _detect_arch()
    out_dir = IMAGES_DIR / arch
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"==> Exporting images to {out_dir}/ (platform: {arch}) ...")

    export_map = [
        ("nginx", "gridpaw-nginx:latest", "gridpaw-nginx.tar"),
        ("admin", "gridpaw-admin:latest", "gridpaw-admin.tar"),
        ("gridpaw", TENANT_IMAGE, "gridpaw-tenant.tar"),
    ]
    exported = []
    for key, name, filename in export_map:
        if key in to_export:
            print(f"  -> {name}")
            run(["docker", "save", name, "-o", str(out_dir / filename)])
            exported.append(out_dir / filename)

    print(green("==> Export complete. Files:"))
    for f in exported:
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"    {f.name}  ({size_mb:.1f} MB)")
    print()
    print("Transfer to target server, then run:")
    print(f"  python prepare.py import {out_dir}")


def cmd_import(images_dir: Optional[Union[str, Path]] = None) -> None:
    arch = _detect_arch()
    default_dir = IMAGES_DIR / arch
    dir_path = Path(images_dir).resolve() if images_dir else default_dir

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

COMPOSE_SERVICES = ("nginx", "admin")


def _validate_services(services: Optional[List[str]]) -> List[str]:
    if not services:
        return []
    invalid = [s for s in services if s not in COMPOSE_SERVICES]
    if invalid:
        print(red(f"ERROR: 未知服务: {', '.join(invalid)}"))
        print(red(f"  可选: {', '.join(COMPOSE_SERVICES)}"))
        sys.exit(1)
    return services


def cmd_up(services: Optional[List[str]] = None) -> None:
    svc = _validate_services(services) if services else []
    # 若启动 admin（未指定服务时启动全部，或明确指定 admin），则先确保宿主机数据目录存在
    need_admin = not svc or "admin" in svc
    if need_admin:
        gridpaw_data = _read_env("GRIDPAW_DATA") or "/var/gridpaw"
        print(f"==> Ensuring host data dirs exist under {gridpaw_data} ...")
        for sub in ("admin_data", "tenants_data", "shared_files"):
            Path(gridpaw_data, sub).mkdir(parents=True, exist_ok=True)
    if svc:
        print(f"==> Starting: {', '.join(svc)} ...")
    else:
        print("==> Starting services (nginx + admin) ...")
    run(["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", *svc])
    print(green("==> Services started."))
    print(green(f"    Admin panel: http://localhost:{NGINX_PORT}/admin/"))


def cmd_down(services: Optional[List[str]] = None) -> None:
    svc = _validate_services(services) if services else []
    if svc:
        print(f"==> Stopping and removing: {', '.join(svc)} ...")
        run(["docker", "compose", "-f", str(COMPOSE_FILE), "rm", "-f", "-s", *svc])
    else:
        print("==> Stopping all services ...")
        run(["docker", "compose", "-f", str(COMPOSE_FILE), "down"])
    print(green("==> Done."))


def cmd_start(services: Optional[List[str]] = None) -> None:
    svc = _validate_services(services) if services else []
    if svc:
        print(f"==> Starting: {', '.join(svc)} ...")
    else:
        print("==> Starting all services ...")
    run(["docker", "compose", "-f", str(COMPOSE_FILE), "start", *svc])
    print(green("==> Done."))


def cmd_stop(services: Optional[List[str]] = None) -> None:
    svc = _validate_services(services) if services else []
    if svc:
        print(f"==> Stopping: {', '.join(svc)} ...")
    else:
        print("==> Stopping all services ...")
    run(["docker", "compose", "-f", str(COMPOSE_FILE), "stop", *svc])
    print(green("==> Done."))


def cmd_restart(services: Optional[List[str]] = None) -> None:
    """Restart services. If services given, restart only those; else restart all."""
    svc = _validate_services(services) if services else []
    if svc:
        print(f"==> Restarting: {', '.join(svc)} ...")
    else:
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
# Prune dangling images
# ---------------------------------------------------------------------------
# 悬空镜像（<none>:<none>）通常由 rebuild gridpaw-nginx/admin/tenant 时产生。
# Docker 无法按原 tag 过滤悬空镜像，此处删除所有悬空镜像以释放空间。


def cmd_prune() -> None:
    print("==> Pruning dangling images (from previous gridpaw-nginx/admin/tenant builds) ...")
    run(["docker", "image", "prune", "-f"])
    print(green("==> Prune complete."))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

COMMANDS = {
    "build":   (cmd_build,   "构建镜像 [nginx|admin|gridpaw]；可加 -p/--platform amd64|arm64 跨平台构建"),
    "export":  (cmd_export,  "导出镜像到 images/<架构>/ [nginx|admin|gridpaw]（可指定目标，默认全部）"),
    "import":  (cmd_import,  "从 tar 文件导入镜像 [images_dir]"),
    "up":      (cmd_up,      "创建并启动 [nginx|admin]（默认全部）"),
    "down":    (cmd_down,    "停止并移除 [nginx|admin]（默认全部）"),
    "start":   (cmd_start,   "启动已有服务 [nginx|admin]（默认全部）"),
    "stop":    (cmd_stop,    "停止 [nginx|admin]（默认全部）"),
    "restart": (cmd_restart, "重启 [nginx|admin]（默认全部）"),
    "status":  (cmd_status,  "显示容器状态"),
    "logs":    (cmd_logs,    "查看日志（可指定服务）"),
    "prune":   (cmd_prune,   "删除悬空镜像（来自 gridpaw-nginx/admin/tenant 重建）"),
}


def print_help() -> None:
    print("GridPaw 多租户部署准备工具")
    print("用法: python prepare.py <命令> [参数]")
    print()
    print("命令:")
    for name, (_, desc) in COMMANDS.items():
        print(f"  {name:<12} {desc}")
    print()
    print("典型操作流程:")
    print("  build 可指定目标，避免全量重建:")
    print("    python prepare.py build admin   # 仅重建 admin（如改了 login.html）")
    print("    python prepare.py build -p amd64  # 跨平台构建 linux/amd64，输出到 images/amd64/（不加载到本地）")
    print("    python prepare.py build gridpaw   # 仅重建 GridPaw 租户镜像")
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
    print("    3. 将整个 deploy_gridpaw 目录拷贝到离线服务器")
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
        print(red(f"未知命令: {cmd_name}"))
        print()
        print_help()
        sys.exit(1)

    cmd_func = COMMANDS[cmd_name][0]

    if cmd_name == "logs" and len(sys.argv) > 2:
        cmd_func(sys.argv[2])
    elif cmd_name == "import" and len(sys.argv) > 2:
        cmd_func(sys.argv[2])
    elif cmd_name in ("build", "export", "restart", "up", "down", "start", "stop"):
        cmd_func(sys.argv[2:] if len(sys.argv) > 2 else None)
    else:
        cmd_func()


if __name__ == "__main__":
    main()
