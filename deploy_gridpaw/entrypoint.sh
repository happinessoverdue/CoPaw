#!/bin/sh
# Substitute COPAW_PORT in supervisord template and start supervisord.
# Default port 8088; override at runtime with -e COPAW_PORT=3000.
set -e

# CoPaw 多 agent 结构：init 仅针对 workspaces/default，以该工作区 AGENTS.md 为锚点判断是否需初始化
WORKING_DIR="${COPAW_WORKING_DIR:-/root/.copaw}"
DEFAULT_AGENTS="${WORKING_DIR}/workspaces/default/AGENTS.md"
if [ ! -f "$DEFAULT_AGENTS" ]; then
    echo "[entrypoint] Default workspace not initialized ($DEFAULT_AGENTS missing), running copaw init..."
    copaw init --defaults --accept-security
    echo "[entrypoint] Init done."
fi

# Substitute COPAW_PORT in supervisord template and start supervisord.
export COPAW_PORT="${COPAW_PORT:-8088}"
envsubst '${COPAW_PORT}' \
  < /etc/supervisor/conf.d/supervisord.conf.template \
  > /etc/supervisor/conf.d/supervisord.conf
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
