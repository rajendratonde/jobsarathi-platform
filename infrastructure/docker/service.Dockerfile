# One image definition for all eight services.
#   docker build -f infrastructure/docker/service.Dockerfile --build-arg SERVICE=identity --build-arg PACKAGE=identity_service .
# Build context is the repo root so the shared libs can be installed.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY libs/ /srv/libs/
RUN pip install /srv/libs/js_core /srv/libs/js_audit /srv/libs/js_outbox /srv/libs/js_integration

ARG SERVICE
ARG PACKAGE
COPY services/${SERVICE}/ /srv/service/
RUN pip install --no-deps /srv/service

COPY infrastructure/docker/entrypoint.sh /srv/entrypoint.sh
RUN chmod 0755 /srv/entrypoint.sh \
    && useradd --create-home --uid 10001 app \
    && chown -R app /srv/service
USER app
WORKDIR /srv/service

ENV SERVICE_PACKAGE=${PACKAGE} \
    PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health/live' % os.environ.get('PORT','8000'), timeout=2)"

ENTRYPOINT ["/srv/entrypoint.sh"]
CMD ["serve"]
