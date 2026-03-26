#!/usr/bin/env bash
# Pack CoPaw-dev into a .zip for sharing/backup, excluding heavy or regeneratable paths
# (node_modules, venvs, build outputs, disk/VM images, common archives, etc.).
#
# Usage (from repo root):
#   bash scripts/pack_copaw_dev_zip.sh
#   bash scripts/pack_copaw_dev_zip.sh -o ~/Desktop/my-copaw.zip
#   bash scripts/pack_copaw_dev_zip.sh --with-git
#   bash scripts/pack_copaw_dev_zip.sh --with-env
#
# Default output: <parent-of-repo>/CoPaw-dev-YYYYMMDD-HHMMSS.zip (never inside the repo tree).
# Archive paths are <repo-basename>/... so unzip creates one top-level folder (your real folder name).
set -euo pipefail

WITH_GIT=false
WITH_ENV=false
OUT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--output)
            OUT="$2"
            shift 2 ;;
        --with-git)
            WITH_GIT=true
            shift ;;
        --with-env)
            WITH_ENV=true
            shift ;;
        -h|--help)
            head -n 22 "$0"
            exit 0 ;;
        *)
            echo "Unknown option: $1 (use --help)" >&2
            exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_PARENT="$(dirname "$REPO_ROOT")"
TOP="$(basename "$REPO_ROOT")"

TS="$(date +%Y%m%d-%H%M%S)"
if [[ -z "$OUT" ]]; then
    OUT="$(dirname "$REPO_ROOT")/CoPaw-dev-${TS}.zip"
else
    OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
fi

case "$OUT" in
    "$REPO_ROOT"/*)
        echo "Refusing to write zip inside repo: $OUT" >&2
        echo "Use -o path outside $REPO_ROOT" >&2
        exit 1 ;;
esac

TMP_LIST="$(mktemp)"
cleanup() { rm -f "$TMP_LIST"; }
trap cleanup EXIT

# Optional: skip typical secret env files (keep .env.example / .env.template).
ENV_EXCLUDE=()
if [[ "$WITH_ENV" != true ]]; then
    ENV_EXCLUDE=(
        '!'
        '('
        '(' -name '.env' -o -name '.env.*' ')'
        -a '!' -name '.env.example'
        -a '!' -name '.env.template'
        -a '!' -name '.env.sample'
        ')'
    )
fi

GIT_EXCLUDE=()
if [[ "$WITH_GIT" != true ]]; then
    GIT_EXCLUDE=( '!' -path "$TOP/.git/*" )
fi

cd "$REPO_PARENT"

find "$TOP" '(' -type f -o -type l ')' \
    "${GIT_EXCLUDE[@]}" \
    ! -path '*/.cursor/*' \
    ! -path '*/.claude/*' \
    ! -path '*/.agents/*' \
    ! -path '*/openspec/*' \
    ! -path '*/deploy_gridpaw/gridpaw_data/tenants_data/*' \
    ! -path '*/deploy_gridpaw/gridpaw_data/admin_data/tenant_template/*' \
    ! -path '*/node_modules/*' \
    ! -path "$TOP/node_modules" \
    ! -path '*/__pycache__/*' \
    ! -path '*/.pytest_cache/*' \
    ! -path '*/.mypy_cache/*' \
    ! -path '*/.ruff_cache/*' \
    ! -path '*/.tox/*' \
    ! -path '*/htmlcov/*' \
    ! -path '*/coverage/*' \
    ! -path '*/.cache/*' \
    ! -path '*/.venv/*' \
    ! -path '*/venv/*' \
    ! -path '*/env/*' \
    ! -path '*/.pnpm-store/*' \
    ! -path '*/.yarn/*' \
    ! -path '*/sessions_mount_dir/*' \
    ! -path '*/cookbook/_build/*' \
    ! -path '*/website/.vite/*' \
    ! -path '*/website/dist/*' \
    ! -path '*/console/dist/*' \
    ! -path '*/src/copaw/console/*' \
    ! -path '*/dist/*' \
    ! -path '*/build/*' \
    ! -path '*/.wheelshim/*' \
    ! -path '*/.egg-info/*' \
    ! -path '*/.*egg-info/*' \
    ! -name '.DS_Store' \
    ! -name 'Thumbs.db' \
    ! -name '*.pyc' \
    ! -name '*.pyo' \
    ! -name '*.rdb' \
    ! -name '*.iso' \
    ! -name '*.qcow2' \
    ! -name '*.vmdk' \
    ! -name '*.ova' \
    ! -name '*.dmg' \
    ! -name '*.img' \
    ! -name '*.tar' \
    ! -name '*.tgz' \
    ! -name '*.zip' \
    ! -name '*.whl' \
    "${ENV_EXCLUDE[@]}" \
    -print > "$TMP_LIST"

if [[ ! -s "$TMP_LIST" ]]; then
    echo "No files matched (check exclusions)." >&2
    exit 1
fi

# zip -@: paths are relative to REPO_PARENT (e.g. CoPaw-dev/README.md).
zip -q -X "$OUT" -@ < "$TMP_LIST"

echo "Created: $OUT"
if command -v du &>/dev/null; then
    du -h "$OUT" | awk '{print "Size:    " $1}'
fi
