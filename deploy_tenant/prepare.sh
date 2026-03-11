#!/usr/bin/env bash
# GridPaw 多租户部署准备工具（Shell 版本）
# 推荐使用：本地和服务器均可直接运行，无需 Python。
# prepare.py 为 Python 版本，功能等价，可在无 Bash 环境下使用。

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
IMAGES_DIR="${SCRIPT_DIR}/images"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# 从 .env 文件读取配置（与 docker compose 保持一致，不依赖系统环境变量）
_read_env() {
    grep "^${1}=" "${SCRIPT_DIR}/.env" 2>/dev/null | head -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d ' '
}
TENANT_IMAGE="$(_read_env TENANT_IMAGE)"
TENANT_IMAGE="${TENANT_IMAGE:-gridpaw-tenant:latest}"
NGINX_PORT="$(_read_env NGINX_PORT)"
NGINX_PORT="${NGINX_PORT:-8087}"

BUILD_TARGETS="nginx admin gridpaw"

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
    echo "==> Building nginx image: gridpaw-nginx:latest"
    run docker build -f "${SCRIPT_DIR}/nginx/Dockerfile" -t gridpaw-nginx:latest "${SCRIPT_DIR}/nginx"
}

cmd_build_admin() {
    echo "==> Building admin image: gridpaw-admin:latest"
    run docker build -f "${SCRIPT_DIR}/admin-service/Dockerfile" -t gridpaw-admin:latest "${SCRIPT_DIR}"
}

cmd_build_gridpaw() {
    echo "==> Building GridPaw tenant image: ${TENANT_IMAGE}"
    echo "    Dockerfile: ${SCRIPT_DIR}/gridpaw.Dockerfile"
    echo "    Context: ${REPO_ROOT}"
    run docker build -f "${SCRIPT_DIR}/gridpaw.Dockerfile" -t "${TENANT_IMAGE}" "${REPO_ROOT}"
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
        targets=(nginx admin gridpaw)
    fi

    for t in "${targets[@]}"; do
        case "$t" in
            nginx) cmd_build_nginx ;;
            admin) cmd_build_admin ;;
            gridpaw) cmd_build_gridpaw ;;
        esac
    done

    echo_green "==> Build complete."
    local built=""
    for t in "${targets[@]}"; do
        case "$t" in
            nginx) built="${built:+${built}, }gridpaw-nginx:latest" ;;
            admin) built="${built:+${built}, }gridpaw-admin:latest" ;;
            gridpaw) built="${built:+${built}, }${TENANT_IMAGE}" ;;
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

    echo "  -> gridpaw-nginx:latest"
    run docker save gridpaw-nginx:latest -o "${IMAGES_DIR}/gridpaw-nginx.tar"
    echo "  -> gridpaw-admin:latest"
    run docker save gridpaw-admin:latest -o "${IMAGES_DIR}/gridpaw-admin.tar"
    echo "  -> ${TENANT_IMAGE}"
    run docker save "${TENANT_IMAGE}" -o "${IMAGES_DIR}/gridpaw-tenant.tar"

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
    docker images | grep -E "nginx|gridpaw" || true
}

# ---------------------------------------------------------------------------
# Docker Compose wrappers
# ---------------------------------------------------------------------------

_COMPOSE_SVC="nginx admin"

_validate_services() {
    local svc=("$@")
    if [ ${#svc[@]} -gt 0 ]; then
        for s in "${svc[@]}"; do
            case " ${_COMPOSE_SVC} " in
                *" ${s} "*) ;;
                *)
                    echo_red "ERROR: 未知服务: ${s}"
                    echo_red "  可选: ${_COMPOSE_SVC}"
                    exit 1
                    ;;
            esac
        done
    fi
}

cmd_up() {
    local svc=("$@")
    _validate_services "${svc[@]}"
    if [ ${#svc[@]} -gt 0 ]; then
        echo "==> Starting: ${svc[*]} ..."
    else
        echo "==> Starting services (nginx + admin) ..."
    fi
    run docker compose -f "${COMPOSE_FILE}" up -d "${svc[@]}"
    echo_green "==> Services started."
    echo_green "    Admin panel: http://localhost:${NGINX_PORT}/admin/"
}

cmd_down() {
    local svc=("$@")
    _validate_services "${svc[@]}"
    if [ ${#svc[@]} -gt 0 ]; then
        echo "==> Stopping and removing: ${svc[*]} ..."
        run docker compose -f "${COMPOSE_FILE}" rm -f -s "${svc[@]}"
    else
        echo "==> Stopping all services ..."
        run docker compose -f "${COMPOSE_FILE}" down
    fi
    echo_green "==> Done."
}

cmd_start() {
    local svc=("$@")
    _validate_services "${svc[@]}"
    if [ ${#svc[@]} -gt 0 ]; then
        echo "==> Starting: ${svc[*]} ..."
    else
        echo "==> Starting all services ..."
    fi
    run docker compose -f "${COMPOSE_FILE}" start "${svc[@]}"
    echo_green "==> Done."
}

cmd_stop() {
    local svc=("$@")
    _validate_services "${svc[@]}"
    if [ ${#svc[@]} -gt 0 ]; then
        echo "==> Stopping: ${svc[*]} ..."
    else
        echo "==> Stopping all services ..."
    fi
    run docker compose -f "${COMPOSE_FILE}" stop "${svc[@]}"
    echo_green "==> Done."
}

cmd_restart() {
    local svc=("$@")
    _validate_services "${svc[@]}"
    if [ ${#svc[@]} -gt 0 ]; then
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
# Prune dangling images
# ---------------------------------------------------------------------------
# 悬空镜像（<none>:<none>）通常由 rebuild gridpaw-nginx / gridpaw-admin / gridpaw-tenant 时产生。
# Docker 无法按原 tag 过滤悬空镜像，此处删除所有悬空镜像以释放空间。

cmd_prune() {
    echo "==> Pruning dangling images (from previous gridpaw-nginx/admin/tenant builds) ..."
    run docker image prune -f
    echo_green "==> Prune complete."
}

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

print_help() {
    echo "GridPaw 多租户部署准备工具"
    echo "用法: ./prepare.sh <命令> [参数]"
    echo
    echo "命令:"
    echo "  build         构建镜像 [nginx|admin|gridpaw]（默认全部）"
    echo "  export        导出镜像为 tar 文件（用于离线传输）"
    echo "  import        从 tar 文件导入镜像 [images_dir]"
    echo "  up            创建并启动 [nginx|admin]（默认全部）"
    echo "  down          停止并移除 [nginx|admin]（默认全部）"
    echo "  start         启动已有服务 [nginx|admin]（默认全部）"
    echo "  stop          停止 [nginx|admin]（默认全部）"
    echo "  restart       重启 [nginx|admin]（默认全部）"
    echo "  status        显示容器状态"
    echo "  logs          查看日志（可指定服务）"
    echo "  prune         删除悬空镜像（来自 gridpaw-nginx/admin/tenant 重建）"
    echo
    echo "典型操作流程:"
    echo "  build 可指定目标，避免全量重建:"
    echo "    ./prepare.sh build admin   # 仅重建 admin（如改了 login.html）"
    echo "    ./prepare.sh build gridpaw   # 仅重建 GridPaw 租户镜像"
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
            cmd_up "$@"
            ;;
        down)
            cmd_down "$@"
            ;;
        start)
            cmd_start "$@"
            ;;
        stop)
            cmd_stop "$@"
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
        prune)
            cmd_prune
            ;;
        *)
            echo_red "未知命令: ${cmd}"
            echo
            print_help
            exit 1
            ;;
    esac
}

# Disable set -e for cmd_import's docker images grep (may match nothing)
main "$@"
