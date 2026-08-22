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

FROM nginxinc/nginx-unprivileged:1.27-alpine@sha256:65e3e85dbaed8ba248841d9d58a899b6197106c23cb0ff1a132b7bfe0547e4c0
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
