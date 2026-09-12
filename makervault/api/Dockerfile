FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534 AS base
ARG SOURCE_DATE_EPOCH=0
ENV SOURCE_DATE_EPOCH="$SOURCE_DATE_EPOCH"
WORKDIR /app

COPY native-packages.lock ./
# Gate 13 stable security refresh: exact existing packages, shared by tests/runtime.
# Signed repository verification stays enabled; never remove packages or run a broad upgrade.
RUN test -s native-packages.lock \
  && apt-get -o APT::Update::Error-Mode=any -o Acquire::AllowInsecureRepositories=false update \
  && DEBIAN_FRONTEND=noninteractive xargs -r apt-get \
       -o APT::Get::AllowUnauthenticated=false install --yes \
       --no-install-recommends --only-upgrade --no-remove < native-packages.lock \
  && rm -rf /var/lib/apt/lists/*

COPY requirements-build.lock ./
# The base image's installer/vendor packages are outside the application lock.
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-build.lock
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

FROM base AS test
COPY requirements-dev.txt requirements-dev.lock ./
RUN pip install --no-cache-dir -r requirements-dev.lock
COPY . .
ENV DB_URL=sqlite:////tmp/makersvault-test.db \
    FILE_STORAGE=/tmp/makersvault-storage \
    IMPORT_MOUNT_ON_STARTUP=false
CMD ["python", "-m", "pytest", "-q"]

FROM base AS runtime
ARG MAKERSVAULT_VERSION=development
ARG MAKERSVAULT_REVISION=unknown
ARG MAKERSVAULT_CREATED=unknown
LABEL org.opencontainers.image.title="MakersVault API" \
  org.opencontainers.image.version="$MAKERSVAULT_VERSION" \
  org.opencontainers.image.revision="$MAKERSVAULT_REVISION" \
  org.opencontainers.image.created="$MAKERSVAULT_CREATED" \
  org.opencontainers.image.source="https://github.com/VincentCinque/MakersVault"
ENV MAKERSVAULT_VERSION="$MAKERSVAULT_VERSION" \
  MAKERSVAULT_REVISION="$MAKERSVAULT_REVISION"
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

COPY . .
RUN mkdir -p /app/storage /app/data

EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
