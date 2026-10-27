FROM node:20-alpine AS dependencies
WORKDIR /app

COPY package*.json ./
RUN npm ci --no-audit --no-fund

FROM dependencies AS lint
COPY . .
RUN npm run lint

FROM lint AS test
RUN npm run verify
CMD ["npm", "run", "verify"]

FROM dependencies AS build
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
USER root
COPY security-headers.conf /etc/nginx/security-headers.conf
COPY 30-security-headers.sh /docker-entrypoint.d/30-security-headers.sh
COPY 40-runtime-config.sh /docker-entrypoint.d/40-runtime-config.sh
# The baked snippet is rewritten in place at container start by the entrypoint
# running as UID 101, so ownership is granted explicitly instead of relying on
# the base image directory permissions. `nginx -t` validates the static
# configuration plus the baked snippet; it also leaves a root-owned pid file
# behind, which would make the container fail to start as UID 101.
RUN chmod +x /docker-entrypoint.d/30-security-headers.sh \
  && chmod +x /docker-entrypoint.d/40-runtime-config.sh \
  && chown 101:0 /etc/nginx/security-headers.conf \
  && chmod 664 /etc/nginx/security-headers.conf \
  && chown -R 101:101 /usr/share/nginx/html \
  && nginx -t \
  && rm -f /tmp/nginx.pid
USER 101

EXPOSE 5173
CMD ["nginx", "-g", "daemon off;"]
