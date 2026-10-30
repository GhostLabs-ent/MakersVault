FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS dependencies
ARG SOURCE_DATE_EPOCH=0
ENV SOURCE_DATE_EPOCH="$SOURCE_DATE_EPOCH"
WORKDIR /app

COPY package*.json ./
RUN npm ci --no-audit --no-fund

FROM dependencies AS test
COPY . .
RUN npm run verify
CMD ["npm", "run", "verify"]

FROM dependencies AS build
COPY . .
RUN npm run build

# HTTP/static proxy only; image-processing/mail modules are not used by MakersVault.
FROM nginxinc/nginx-unprivileged:1.31-alpine-slim@sha256:a8cb0f33d51fa107c96fd2bd3a71aaf564ec131e9d2bdf8700944f0ed8b170d7
ARG SOURCE_DATE_EPOCH=0
ENV SOURCE_DATE_EPOCH="$SOURCE_DATE_EPOCH"
ARG MAKERSVAULT_VERSION=development
ARG MAKERSVAULT_REVISION=unknown
ARG MAKERSVAULT_CREATED=unknown
LABEL org.opencontainers.image.title="MakersVault Web" \
  org.opencontainers.image.version="$MAKERSVAULT_VERSION" \
  org.opencontainers.image.revision="$MAKERSVAULT_REVISION" \
  org.opencontainers.image.created="$MAKERSVAULT_CREATED" \
  org.opencontainers.image.source="https://github.com/VincentCinque/MakersVault"
COPY nginx.conf /etc/nginx/conf.d/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
USER root
COPY 40-runtime-config.sh /docker-entrypoint.d/40-runtime-config.sh
RUN chmod +x /docker-entrypoint.d/40-runtime-config.sh \
  && rm -f /etc/nginx/conf.d/default.conf \
  && touch /etc/nginx/conf.d/default.conf \
  && chown 101:101 /etc/nginx/conf.d/default.conf \
  && chown -R 101:101 /usr/share/nginx/html
USER 101

EXPOSE 5173
CMD ["nginx", "-g", "daemon off;"]
