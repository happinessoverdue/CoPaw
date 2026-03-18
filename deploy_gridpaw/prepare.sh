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
EXPORT_TARGETS="nginx admin gridpaw"

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

# 检测当前平台架构，输出 amd64 或 arm64（用于 export 目录）
_detect_arch() {
    local m
    m=$(uname -m 2>/dev/null || true)
    case "${m}" in
        x86_64|amd64) echo "amd64" ;;
        aarch64|arm64|armv8*) echo "arm64" ;;
        *) echo "amd64" ;;  # 未知时默认 amd64
    esac
}

# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

# 解析 --platform / -p 的简写，输出 linux/amd64 或 linux/arm64
_normalize_platform() {
    case "$1" in
        linux/amd64|amd64|amd) echo "linux/amd64" ;;
        linux/arm64|arm64|arm) echo "linux/arm64" ;;
        *)
            echo_red "ERROR: 不支持的平台: $1"
            echo_red "  可选: linux/amd64, amd64, amd | linux/arm64, arm64, arm"
            exit 1
            ;;
    esac
}

# 平台简称，用于输出目录名
_platform_short_name() {
    case "$1" in
        linux/amd64) echo "amd64" ;;
        linux/arm64) echo "arm64" ;;
        *) echo "$1" ;;
    esac
}

# 确保存在支持 type=docker,dest= 的 buildx builder（需 docker-container 驱动）
_ensure_buildx_builder() {
    local name="gridpaw-multiarch"
    if ! docker buildx inspect "${name}" &>/dev/null; then
        echo "==> 创建 buildx builder '${name}'（首次跨平台构建需此步骤）..."
        run docker buildx create --name "${name}" --driver docker-container --use
    else
        docker buildx use "${name}" &>/dev/null || true
    fi
}

cmd_build_nginx() {
    echo "==> Building nginx image: gridpaw-nginx:latest"
    run docker build -f "${SCRIPT_DIR}/nginx/Dockerfile" -t gridpaw-nginx:latest "${SCRIPT_DIR}/nginx"
    echo_green "✓ gridpaw-nginx:latest 构建成功"
}

cmd_build_admin() {
    echo "==> Building admin image: gridpaw-admin:latest"
    run docker build -f "${SCRIPT_DIR}/admin-service/Dockerfile" -t gridpaw-admin:latest "${SCRIPT_DIR}"
    echo_green "✓ gridpaw-admin:latest 构建成功"
}

cmd_build_gridpaw() {
    echo "==> Building GridPaw tenant image: ${TENANT_IMAGE}"
    echo "    Dockerfile: ${SCRIPT_DIR}/gridpaw.Dockerfile"
    echo "    Context: ${REPO_ROOT}"
    run docker build -f "${SCRIPT_DIR}/gridpaw.Dockerfile" -t "${TENANT_IMAGE}" "${REPO_ROOT}"
    echo_green "✓ ${TENANT_IMAGE} 构建成功"
}

# 跨平台构建：直接输出到 tar，不加载到本地 Docker
cmd_build_nginx_cross() {
    local platform="$1"
    local out_dir="$2"
    local tar_file="${out_dir}/gridpaw-nginx.tar"
    echo "==> Building nginx (${platform}) -> ${tar_file}"
    run docker buildx build \
        --platform "${platform}" \
        -f "${SCRIPT_DIR}/nginx/Dockerfile" \
        -t gridpaw-nginx:latest \
        --output "type=docker,dest=${tar_file}" \
        "${SCRIPT_DIR}/nginx"
    echo_green "✓ gridpaw-nginx:latest (${platform}) 构建成功 -> ${tar_file}"
}

cmd_build_admin_cross() {
    local platform="$1"
    local out_dir="$2"
    local tar_file="${out_dir}/gridpaw-admin.tar"
    echo "==> Building admin (${platform}) -> ${tar_file}"
    run docker buildx build \
        --platform "${platform}" \
        -f "${SCRIPT_DIR}/admin-service/Dockerfile" \
        -t gridpaw-admin:latest \
        --output "type=docker,dest=${tar_file}" \
        "${SCRIPT_DIR}"
    echo_green "✓ gridpaw-admin:latest (${platform}) 构建成功 -> ${tar_file}"
}

cmd_build_gridpaw_cross() {
    local platform="$1"
    local out_dir="$2"
    local tar_file="${out_dir}/gridpaw-tenant.tar"
    echo "==> Building GridPaw tenant (${platform}) -> ${tar_file}"
    echo "    Image tag in tar: ${TENANT_IMAGE}"
    run docker buildx build \
        --platform "${platform}" \
        -f "${SCRIPT_DIR}/gridpaw.Dockerfile" \
        -t "${TENANT_IMAGE}" \
        --output "type=docker,dest=${tar_file}" \
        "${REPO_ROOT}"
    echo_green "✓ ${TENANT_IMAGE} (${platform}) 构建成功 -> ${tar_file}"
}

cmd_build() {
    local platform=""
    local targets=()
    # 解析参数：支持 --platform / -p
    while [ $# -gt 0 ]; do
        case "$1" in
            -p|--platform)
                if [ -z "${2:-}" ]; then
                    echo_red "ERROR: --platform 需要指定值，如 amd64 或 arm64"
                    exit 1
                fi
                platform="$(_normalize_platform "$2")"
                shift 2
                ;;
            -*)
                echo_red "ERROR: 未知选项: $1"
                exit 1
                ;;
            *)
                case " ${BUILD_TARGETS} " in
                    *" ${1} "*) targets+=("$1") ;;
                    *)
                        echo_red "ERROR: 未知构建目标: ${1}"
                        echo_red "  可选: ${BUILD_TARGETS}"
                        exit 1
                        ;;
                esac
                shift
                ;;
        esac
    done
    [ ${#targets[@]} -eq 0 ] && targets=(nginx admin gridpaw)

    if [ -n "$platform" ]; then
        # 跨平台构建：输出到 images/<arch>/
        local short_name
        short_name="$(_platform_short_name "$platform")"
        local out_dir="${IMAGES_DIR}/${short_name}"
        mkdir -p "${out_dir}"
        echo "==> 跨平台构建: ${platform} -> ${out_dir}/"
        _ensure_buildx_builder
        for t in "${targets[@]}"; do
            case "$t" in
                nginx) cmd_build_nginx_cross "$platform" "$out_dir" ;;
                admin) cmd_build_admin_cross "$platform" "$out_dir" ;;
                gridpaw) cmd_build_gridpaw_cross "$platform" "$out_dir" ;;
            esac
        done
        echo_green "==> Build complete. 镜像已保存到: ${out_dir}/"
        for f in "${out_dir}"/*.tar; do
            [ -f "$f" ] || continue
            local size_b
            size_b=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null)
            size_b="${size_b:-0}"
            echo "    $(basename "$f")  ($(awk -v s="$size_b" 'BEGIN {printf "%.1f", s/1048576}') MB)"
        done
        echo
        echo "  传输到目标服务器后执行: ./prepare.sh import ${out_dir}"
    else
        # 本机构建：加载到 Docker
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
    fi
}

# ---------------------------------------------------------------------------
# export / import
# ---------------------------------------------------------------------------

cmd_export() {
    local targets=()
    if [ $# -gt 0 ]; then
        for t in "$@"; do
            case " ${EXPORT_TARGETS} " in
                *" ${t} "*) targets+=("$t") ;;
                *)
                    echo_red "ERROR: 未知导出目标: ${t}"
                    echo_red "  可选: ${EXPORT_TARGETS}"
                    exit 1
                    ;;
            esac
        done
    else
        targets=(nginx admin gridpaw)
    fi

    local arch
    arch="$(_detect_arch)"
    local out_dir="${IMAGES_DIR}/${arch}"
    mkdir -p "${out_dir}"
    echo "==> Exporting images to ${out_dir}/ (platform: ${arch}) ..."

    local exported=()
    for t in "${targets[@]}"; do
        case "$t" in
            nginx)
                echo "  -> gridpaw-nginx:latest"
                run docker save gridpaw-nginx:latest -o "${out_dir}/gridpaw-nginx.tar"
                exported+=("${out_dir}/gridpaw-nginx.tar")
                ;;
            admin)
                echo "  -> gridpaw-admin:latest"
                run docker save gridpaw-admin:latest -o "${out_dir}/gridpaw-admin.tar"
                exported+=("${out_dir}/gridpaw-admin.tar")
                ;;
            gridpaw)
                echo "  -> ${TENANT_IMAGE}"
                run docker save "${TENANT_IMAGE}" -o "${out_dir}/gridpaw-tenant.tar"
                exported+=("${out_dir}/gridpaw-tenant.tar")
                ;;
        esac
    done

    echo_green "==> Export complete. Files:"
    for f in "${exported[@]}"; do
        [ -f "$f" ] || continue
        local size_b
        size_b=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null)
        size_b="${size_b:-0}"
        echo "    $(basename "$f")  ($(awk -v s="$size_b" 'BEGIN {printf "%.1f", s/1048576}') MB)"
    done
    echo
    echo "Transfer to target server, then run:"
    echo "  ./prepare.sh import ${out_dir}"
}

cmd_import() {
    local arch raw
    arch="$(_detect_arch)"
    raw="${1:-${IMAGES_DIR}/${arch}}"
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
    # 若启动 admin（未指定服务时启动全部，或明确指定 admin），则先确保宿主机数据目录存在
    local need_admin=0
    if [ ${#svc[@]} -eq 0 ]; then
        need_admin=1
    else
        for s in "${svc[@]}"; do
            [ "$s" = "admin" ] && need_admin=1 && break
        done
    fi
    if [ "$need_admin" -eq 1 ]; then
        local gridpaw_data
        gridpaw_data="$(_read_env GRIDPAW_DATA)"
        gridpaw_data="${gridpaw_data:-/var/gridpaw}"
        echo "==> Ensuring host data dirs exist under ${gridpaw_data} ..."
        mkdir -p "${gridpaw_data}/admin_data" "${gridpaw_data}/tenants_data" "${gridpaw_data}/shared_files"
    fi
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
    echo "                 可加 -p/--platform <平台> 跨平台构建并直接保存到 images/<arch>/"
    echo "                 平台: linux/amd64|amd64|amd | linux/arm64|arm64|arm"
    echo "  export [nginx|admin|gridpaw]  导出镜像到 images/<架构>/（可指定目标，默认全部）"
    echo "  import [dir]  从 tar 导入镜像（默认 images/<架构>/）"
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
    echo "    ./prepare.sh build -p amd64  # 跨平台构建 linux/amd64，输出到 images/amd64/（不加载到本地）"
    echo "  export 可指定目标:"
    echo "    ./prepare.sh export gridpaw # 仅导出租户镜像（体积最大）"
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
    echo "    2. ./prepare.sh export     # 导出到 images/<架构>/*.tar"
    echo "    3. 将整个 deploy_gridpaw 目录拷贝到离线服务器"
    echo
    echo "  在离线服务器上（需与本机同架构）:"
    echo "    4. ./prepare.sh import     # 导入镜像（默认 images/<架构>/）"
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
            cmd_export "$@"
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
