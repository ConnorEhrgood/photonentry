# The PhotonEntry API (also the one-shot migration and the worker: the same image, other commands). Built from the REPOSITORY ROOT:
#   docker build -f api/Dockerfile --build-arg BUILD_SHA=$(git rev-parse HEAD) .
# The base is the one PhotonGuard pins on the same host (by digest). Packages are pinned by version (api/requirements.txt); a hash-locked file is
# OPERATIONS.md §2.9's next step (pip-compile --generate-hashes), as PhotonGuard has.
FROM python:3.12.15-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY api/requirements.txt .
RUN pip install --no-compile -r requirements.txt
COPY api/alembic.ini ./
COPY api/alembic ./alembic
COPY api/app ./app
COPY api/photonid_directory_client ./photonid_directory_client
# Unprivileged: a bug in the app must not hand out root in the container.
RUN echo 'entry:x:10001:10001:entry:/nonexistent:/usr/sbin/nologin' >> /etc/passwd && echo 'entry:x:10001:' >> /etc/group
USER 10001:10001
ARG BUILD_SHA=""
ENV BUILD_SHA=${BUILD_SHA}
LABEL org.opencontainers.image.revision=${BUILD_SHA} org.opencontainers.image.title="photonentry-api"
EXPOSE 8000
# The proxy in front is believed for X-Forwarded-For (FORWARDED_ALLOW_IPS), so per-address limits see the real client.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\" --timeout-keep-alive 75"]
