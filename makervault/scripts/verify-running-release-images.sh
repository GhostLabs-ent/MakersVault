#!/bin/sh
set -eu

if [ "$#" -ne 4 ]; then
  echo "Usage: $0 API_IMAGE WEB_IMAGE API_CONTAINER WEB_CONTAINER" >&2
  exit 2
fi

api_image=$1
web_image=$2
api_container=$3
web_container=$4

expected_api_id=$(docker image inspect --format '{{.Id}}' "$api_image")
expected_web_id=$(docker image inspect --format '{{.Id}}' "$web_image")
actual_api_id=$(docker container inspect --format '{{.Image}}' "$api_container")
actual_web_id=$(docker container inspect --format '{{.Image}}' "$web_container")

if [ "$actual_api_id" != "$expected_api_id" ]; then
  echo "API container does not use the requested release image" >&2
  exit 1
fi
if [ "$actual_web_id" != "$expected_web_id" ]; then
  echo "Web container does not use the requested release image" >&2
  exit 1
fi

api_version=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}' "$api_image")
web_version=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}' "$web_image")
api_revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$api_image")
web_revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$web_image")

if [ -z "$api_version" ] || [ "$api_version" != "$web_version" ]; then
  echo "Release image version labels are missing or mismatched" >&2
  exit 1
fi
if [ -z "$api_revision" ] || [ "$api_revision" != "$web_revision" ]; then
  echo "Release image revision labels are missing or mismatched" >&2
  exit 1
fi

echo "Verified release images: $api_version revision $api_revision"
