# ai-running-coach — tableau de bord en conteneur (lecture seule).
#
# Le workspace est monté en lecture seule sur /workspace ; l'index vit en mémoire
# (--memory) et se reconstruit au démarrage. Aucune authentification propre :
# le conteneur se place derrière un reverse proxy qui en a une.
# Voir docs/dashboard/docker.md et deploy/dashboard/.
FROM python:3.12-alpine

LABEL org.opencontainers.image.title="ai-running-coach-dashboard" \
      org.opencontainers.image.description="Tableau de bord ai-running-coach (lecture seule)" \
      org.opencontainers.image.source="https://github.com/mmornati/ai-running-coach" \
      org.opencontainers.image.licenses="MIT"

# tzdata : sans lui, TZ est ignoré et « aujourd'hui » bascule à minuit UTC.
RUN apk add --no-cache tzdata

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    ARC_DASHBOARD_LISTEN=0.0.0.0

WORKDIR /app
COPY scripts/ scripts/
COPY web/ web/
COPY config/ config/

# Utilisateur non root ; remplacé par `user:` dans compose pour lire le
# workspace de l'hôte avec son propriétaire.
USER 1000:1000
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=4)"]

ENTRYPOINT ["python3", "/app/scripts/arc_serve.py", "--workspace", "/workspace", "--memory", "--port", "8765"]
