#!/bin/sh
# Substitute COPAW_PORT in supervisord template and start supervisord.
# Default port 8088; override at runtime with -e COPAW_PORT=3000.
set -e

WORKING_DIR="${COPAW_WORKING_DIR:-/app/working}"
if [ ! -f "${WORKING_DIR}/AGENTS.md" ]; then
    echo "[entrypoint] Working dir not initialized (AGENTS.md missing), running copaw init..."
    copaw init --defaults --accept-security
    echo "[entrypoint] Init done."
fi

# Substitute COPAW_PORT in supervisord template and start supervisord.
export COPAW_PORT="${COPAW_PORT:-8088}"
envsubst '${COPAW_PORT}' \
  < /etc/supervisor/conf.d/supervisord.conf.template \
  > /etc/supervisor/conf.d/supervisord.conf
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
