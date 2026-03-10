# CoPaw custom image for multi-user deployment.
# Based on official agentscope/copaw image — skips all apt/system-package steps.
# Build context: project root (REPO_ROOT). Paths like deploy/, console/, src/ are relative to context.
# Content mirrors deploy/Dockerfile; keep in sync when that file changes.

# -----------------------------------------------------------------------------
# Stage 1: build console frontend (dist not committed in repo).
# -----------------------------------------------------------------------------
FROM agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/node:slim AS console-builder
WORKDIR /app
COPY console /app/console
RUN cd /app/console && npm ci --include=dev && npm run build

# -----------------------------------------------------------------------------
# Stage 2: apply custom fork code on top of official CoPaw image.
# All system packages, Python venv, Chromium, supervisor, entrypoint are
# already present in the base image — no apt-get needed.
# -----------------------------------------------------------------------------
FROM agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/copaw:latest

ENV TZ=Asia/Shanghai

# Available channels for this image (imessage & discord excluded).
# Override at runtime with -e COPAW_ENABLED_CHANNELS=... if needed.
ARG COPAW_ENABLED_CHANNELS="discord,telegram,dingtalk,feishu,qq,console"
ENV COPAW_ENABLED_CHANNELS=${COPAW_ENABLED_CHANNELS}

WORKDIR ${WORKSPACE_DIR}

# Replace source code with our fork and reinstall into the existing venv.
COPY pyproject.toml setup.py README.md ./
COPY src ./src
# Inject console dist from build stage (repo does not commit dist).
COPY --from=console-builder /app/console/dist/ ./src/copaw/console/
# pip only downloads packages not already satisfied in the base venv.
RUN pip install --no-cache-dir .

# Re-init working dir to pick up any new default files from this version.
RUN copaw init --defaults --accept-security

# Custom entrypoint: init working dir on first run when bind-mounted empty.
COPY deploy_tenant/entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

EXPOSE 8088

CMD ["/entrypoint.sh"]
