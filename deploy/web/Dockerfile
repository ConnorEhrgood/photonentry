# The web app: built here (the photon-ui pieces are vendored into web/src), then served as static files by a pinned Caddy with its settings at
# /config.js from the container's environment, so one image runs in every environment. Built from the REPOSITORY ROOT:
#   docker build -f deploy/web/Dockerfile --build-arg BUILD_SHA=$(git rev-parse HEAD) .
FROM node:22.23.3-alpine AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build && ! grep -rqs "VITE_DEV_TOKEN" dist      # the developer sign-in shortcut must never reach a production bundle

FROM caddy:2.11.7-alpine@sha256:e70b164da81ef698b3ad19af799ea6086ce6d9e48ed4079eb9fe26f6fbf14ee5
COPY --from=build /web/dist /srv
COPY deploy/web/Caddyfile /etc/caddy/Caddyfile
ARG BUILD_SHA=""
LABEL org.opencontainers.image.revision=${BUILD_SHA} org.opencontainers.image.title="photonentry-web"
