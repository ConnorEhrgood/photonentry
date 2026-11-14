# The demo's simulators (docs/DEMO.md): six simulated Axis controllers, the real entry-link on each, two simulated Akuvox intercoms and the
# driver. It runs on the demo simulator host only (never a production host), and reaches PhotonEntry over its public names, as a site does.
# Built from the REPOSITORY ROOT:   docker build -f deploy/demo/Dockerfile --build-arg BUILD_SHA=$(git rev-parse HEAD) .
FROM python:3.12.15-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS build
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev make libcurl4-openssl-dev libssl-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY acap/vendor ./acap/vendor
COPY acap/entry-link ./acap/entry-link
RUN make -C acap/entry-link clean && make -C acap/entry-link

FROM python:3.12.15-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONPATH=/app
RUN apt-get update && apt-get install -y --no-install-recommends libcurl4 ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# The simulator's own needs, at the API's pinned versions.
RUN pip install --no-compile fastapi==0.143.0 starlette==1.7.0 "uvicorn[standard]==0.39.0" httpx==0.28.1
COPY sim/axis_sim ./axis_sim
COPY sim/demo_sim ./demo_sim
COPY --from=build /src/acap/entry-link/build/entry-link /usr/local/bin/entry-link
RUN echo 'demo:x:10001:10001:demo:/nonexistent:/usr/sbin/nologin' >> /etc/passwd && echo 'demo:x:10001:' >> /etc/group \
    && mkdir /state && chown 10001:10001 /state
USER 10001:10001
ARG BUILD_SHA=""
ENV BUILD_SHA=${BUILD_SHA}
LABEL org.opencontainers.image.revision=${BUILD_SHA} org.opencontainers.image.title="photonentry-demo" com.photonind.demo="true"
VOLUME /state
CMD ["python", "-m", "demo_sim", "run"]
