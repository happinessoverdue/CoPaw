#!/usr/bin/env bash
# CoPaw Multi-Tenant Deployment Preparation Tool (Shell version).
# 推荐使用：本地和服务器均可直接运行，无需 Python。
# prepare.py 为 Python 版本，功能等价，可在无 Bash 环境下使用。

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
IMAGES_DIR="${SCRIPT_DIR}/images"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
COPAW_IMAGE="${COPAW_IMAGE:-copaw-tenant-ampere:latest}"

BUILD_TARGETS="nginx admin copaw"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_color() {
    if [ -t 1 ]; then
        printf "\033[%sm%s\033[0m" "$1" "$2"
    else
        printf "%s" "$2"
    fi
}

green()  { _color "32" "$1"; }
red()    { _color "31" "$1"; }
echo_green() { green "$1"; echo; }
echo_red()   { red "$1"; echo; }

run() {
    if ! "$@"; then
        echo_red "ERROR: Command failed (exit $?): $*"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

cmd_build_nginx() {
    echo "==> Building nginx image: copaw-nginx:latest"
    run docker build -f "${SCRIPT_DIR}/nginx/Dockerfile" -t copaw-nginx:latest "${SCRIPT_DIR}/nginx"
}

cmd_build_admin() {
    echo "==> Building admin image: copaw-admin:latest"
    run docker build -f "${SCRIPT_DIR}/admin-service/Dockerfile" -t copaw-admin:latest "${SCRIPT_DIR}"
}

cmd_build_copaw() {
    echo "==> Building CoPaw image: ${COPAW_IMAGE}"
    echo "    Dockerfile: ${SCRIPT_DIR}/copaw.Dockerfile"
    echo "    Context: ${REPO_ROOT}"
    run docker build -f "${SCRIPT_DIR}/copaw.Dockerfile" -t "${COPAW_IMAGE}" "${REPO_ROOT}"
}

cmd_build() {
    local targets=()
    if [ $# -gt 0 ]; then
        for t in "$@"; do
            case " ${BUILD_TARGETS} " in
                *" ${t} "*) targets+=("$t") ;;
                *)
                    echo_red "ERROR: 未知构建目标: ${t}"
                    echo_red "  可选: ${BUILD_TARGETS}"
                    exit 1
                    ;;
            esac
        done
    else
        targets=(nginx admin copaw)
    fi

    for t in "${targets[@]}"; do
        case "$t" in
            nginx) cmd_build_nginx ;;
            admin) cmd_build_admin ;;
            copaw) cmd_build_copaw ;;
        esac
    done

    echo_green "==> Build complete."
    local built=""
    for t in "${targets[@]}"; do
        case "$t" in
            nginx) built="${built:+${built}, }copaw-nginx:latest" ;;
            admin) built="${built:+${built}, }copaw-admin:latest" ;;
            copaw) built="${built:+${built}, }${COPAW_IMAGE}" ;;
        esac
    done
    [ -n "$built" ] && echo_green "    Built: ${built}"
}

# ---------------------------------------------------------------------------
# export / import
# ---------------------------------------------------------------------------

cmd_export() {
    mkdir -p "${IMAGES_DIR}"
    echo "==> Exporting images to ${IMAGES_DIR}/ ..."

    echo "  -> copaw-nginx:latest"
    run docker save copaw-nginx:latest -o "${IMAGES_DIR}/copaw-nginx.tar"
    echo "  -> copaw-admin:latest"
    run docker save copaw-admin:latest -o "${IMAGES_DIR}/copaw-admin.tar"
    echo "  -> ${COPAW_IMAGE}"
    run docker save "${COPAW_IMAGE}" -o "${IMAGES_DIR}/copaw-tenant-ampere.tar"

    echo_green "==> Export complete. Files:"
    for f in $(ls -1 "${IMAGES_DIR}"/*.tar 2>/dev/null | sort); do
        [ -f "$f" ] || continue
        local size_b
        size_b=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null)
        echo "    $(basename "$f")  ($(awk "BEGIN {printf \"%.1f\", ${size_b:-0} / 1048576}") MB)"
    done
    echo
    echo "Transfer these files to the intranet server, then run:"
    echo "  ./prepare.sh import"
}

cmd_import() {
    local raw="${1:-${IMAGES_DIR}}"
    if [ ! -d "$raw" ]; then
        echo_red "ERROR: 目录不存在: ${raw}"
        exit 1
    fi
    local dir_path
    dir_path="$(cd "$raw" && pwd)"

    echo "==> Importing images from ${dir_path}/ ..."

    local found=0
    for tarfile in "${dir_path}"/*.tar; do
        [ -f "$tarfile" ] || continue
        found=1
        echo "  -> $(basename "$tarfile")"
        run docker load -i "$tarfile"
    done

    if [ "$found" -eq 0 ]; then
        echo_red "ERROR: 目录下没有找到 .tar 文件: ${dir_path}"
        exit 1
    fi

    echo_green "==> Import complete."
    docker images | grep -E "nginx|copaw" || true
}

# ---------------------------------------------------------------------------
# Docker Compose wrappers
# ---------------------------------------------------------------------------

cmd_up() {
    echo "==> Starting services (nginx + admin) ..."
    run docker compose -f "${COMPOSE_FILE}" up -d
    echo_green "==> Services started."
    echo_green "    Admin panel: http://localhost:<NGINX_PORT>/admin/"
    echo_green "    (Check .env for the actual NGINX_PORT value)"
}

cmd_down() {
    echo "==> Stopping all services ..."
    run docker compose -f "${COMPOSE_FILE}" down
    echo_green "==> All services stopped."
}

cmd_restart() {
    local svc=("$@")
    if [ ${#svc[@]} -gt 0 ]; then
        for s in "${svc[@]}"; do
            case "$s" in nginx|admin) ;; *)
                echo_red "ERROR: 未知服务: ${s}"
                echo_red "  可选: nginx, admin"
                exit 1
                ;;
            esac
        done
        echo "==> Restarting: ${svc[*]} ..."
    else
        echo "==> Restarting all services ..."
    fi
    run docker compose -f "${COMPOSE_FILE}" restart "${svc[@]}"
    echo_green "==> Restart complete."
}

cmd_status() {
    docker compose -f "${COMPOSE_FILE}" ps
}

cmd_logs() {
    if [ -n "$1" ]; then
        docker compose -f "${COMPOSE_FILE}" logs -f "$1"
    else
        docker compose -f "${COMPOSE_FILE}" logs -f
    fi
}

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

print_help() {
    echo "CoPaw 多租户部署准备工具"
    echo "用法: ./prepare.sh <命令> [参数]"
    echo
    echo "命令:"
    echo "  build         Build images [nginx|admin|copaw] (default: all)"
    echo "  export        Export images to tar files (for offline transfer)"
    echo "  import        Import images from tar files [images_dir]"
    echo "  up            Start nginx + admin services"
    echo "  down          Stop all services"
    echo "  restart       Restart services [nginx|admin] (default: all)"
    echo "  status        Show container status"
    echo "  logs          Show logs (optionally for a specific service)"
    echo
    echo "典型操作流程:"
    echo "  build 可指定目标，避免全量重建:"
    echo "    ./prepare.sh build admin   # 仅重建 admin（如改了 login.html）"
    echo "    ./prepare.sh build copaw   # 仅重建 CoPaw 镜像"
    echo
    echo "  【首次部署（有网络）】"
    echo "    1. 编辑 .env（端口、密钥、镜像名等）"
    echo "    2. ./prepare.sh build      # 构建所有镜像"
    echo "    3. ./prepare.sh up         # 启动 nginx + admin"
    echo "    4. 浏览器访问管理页面，添加租户并启动实例"
    echo
    echo "  【离线服务器部署】"
    echo "  在有网机器上:"
    echo "    1. ./prepare.sh build      # 构建镜像"
    echo "    2. ./prepare.sh export     # 导出到 images/*.tar"
    echo "    3. 将整个 deploy_tenant 目录拷贝到离线服务器"
    echo
    echo "  在离线服务器上:"
    echo "    4. ./prepare.sh import     # 导入镜像"
    echo "    5. 编辑 .env（按环境调整端口等）"
    echo "    6. ./prepare.sh up         # 启动服务"
    echo "    7. 浏览器访问管理页面，添加租户并启动实例"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    if [ $# -lt 1 ] || [ "$1" = "help" ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
        print_help
        return 0
    fi

    local cmd="$1"
    shift

    case "$cmd" in
        build)
            cmd_build "$@"
            ;;
        export)
            cmd_export
            ;;
        import)
            cmd_import "$@"
            ;;
        up)
            cmd_up
            ;;
        down)
            cmd_down
            ;;
        restart)
            cmd_restart "$@"
            ;;
        status)
            cmd_status
            ;;
        logs)
            cmd_logs "$@"
            ;;
        *)
            echo_red "Unknown command: ${cmd}"
            echo
            print_help
            exit 1
            ;;
    esac
}

# Disable set -e for cmd_import's docker images grep (may match nothing)
main "$@"
