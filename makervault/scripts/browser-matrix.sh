#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
api_image=${MAKERSVAULT_BENCHMARK_API_IMAGE:-}
web_image=${MAKERSVAULT_BENCHMARK_WEB_IMAGE:-}
playwright_image=${MAKERSVAULT_BENCHMARK_PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright:v1.62.1-noble@sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e}

if [ -z "$api_image" ] || [ -z "$web_image" ]; then
  echo "MAKERSVAULT_BENCHMARK_API_IMAGE and MAKERSVAULT_BENCHMARK_WEB_IMAGE are required" >&2
  exit 2
fi

for browser in chromium firefox webkit; do
  echo "Running $browser release-image organization smoke"
  MAKERSVAULT_BENCHMARK_API_IMAGE="$api_image" \
  MAKERSVAULT_BENCHMARK_WEB_IMAGE="$web_image" \
  MAKERSVAULT_BENCHMARK_PLAYWRIGHT_IMAGE="$playwright_image" \
  MAKERSVAULT_BENCHMARK_BROWSER="$browser" \
    sh "$script_dir/organization-benchmark.sh"
done
