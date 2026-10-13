# ai-running-coach — chat avec le coach en conteneur (backend OpenCode).
#
# L'image n'apporte que l'outillage : Python, OpenCode, garmin-mcp. Le moteur
# (ce dépôt) et le workspace sont montés depuis l'hôte AUX MÊMES CHEMINS, parce que
# le workspace pointe vers le moteur par liens symboliques absolus (skills/, agents/).
# Même raison pour HOME : les scripts cherchent garmin-mcp sous
# ~/.local/share/uv/tools et les jetons Garmin sous ~/.garminconnect.
# Voir deploy/dashboard/compose.chat.yaml et docs/dashboard/chat.md.
FROM python:3.12-slim-trixie

LABEL org.opencontainers.image.title="ai-running-coach-chat" \
      org.opencontainers.image.description="Chat avec le coach ai-running-coach (OpenCode)" \
      org.opencontainers.image.source="https://github.com/mmornati/ai-running-coach" \
      org.opencontainers.image.licenses="MIT"

# Gardés alignés sur install.sh (GARMIN_MCP_REF) et scripts/arc_chat_opencode.py
# (OPENCODE_TESTED_VERSION) — vérifié par tests/install/test_chat_container.py.
ARG OPENCODE_VERSION=1.18.35
ARG GARMIN_MCP_REF=git+https://github.com/Taxuspt/garmin_mcp@cfc5d799ab0f165e837f1188a1d093c65838aaf7
ARG ARC_HOME=/home/coach
ARG ARC_UID=1000
ARG ARC_GID=1000

# git : garmin-mcp s'installe depuis un dépôt ; tzdata : sans lui TZ est ignoré.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv

RUN groupadd -g "$ARC_GID" coach \
    && useradd -u "$ARC_UID" -g "$ARC_GID" -d "$ARC_HOME" -m -s /bin/bash coach

USER $ARC_UID:$ARC_GID
ENV HOME=$ARC_HOME \
    PATH=$ARC_HOME/.opencode/bin:$ARC_HOME/.local/bin:/usr/local/bin:/usr/bin:/bin \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPENCODE_DISABLE_AUTOUPDATE=1

RUN mkdir -p "$HOME/.opencode/bin" "$HOME/.local/share/opencode" "$HOME/.garminconnect" \
    && chmod 700 "$HOME/.garminconnect" \
    && arch="$(uname -m)" && case "$arch" in x86_64) arch=x64 ;; aarch64) arch=arm64 ;; esac \
    && curl -fsSL "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/opencode-linux-${arch}.tar.gz" \
       | tar -xz -C "$HOME/.opencode/bin" opencode \
    && opencode --version \
    && uv tool install --python 3.12 --with fitparse "$GARMIN_MCP_REF" \
    && uv cache clean

EXPOSE 8766

# /healthz n'est accepté que depuis la boucle locale ; 503 si OpenCode ou la clé manquent.
HEALTHCHECK --interval=60s --timeout=20s --start-period=30s --retries=3 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8766/api/chat/healthz', timeout=15)"]
