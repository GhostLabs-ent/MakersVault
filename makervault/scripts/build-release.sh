#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
repo_dir=$(CDPATH= cd -- "$app_dir/.." && pwd)
version="v5.1.0"
output_dir="$app_dir/release/$version"
allow_dirty=false

usage() {
  cat <<'EOF'
Usage: ./scripts/build-release.sh [options]

Options:
  --version VERSION  Release identity (default: v5.1.0)
  --output-dir PATH  New empty artifact directory
  --allow-dirty      Development only; output is not release evidence

Builds local versioned API/web images and six bridge binaries, generates SPDX
SBOMs, validates OCI/source identity, and writes SHA256SUMS. It never pushes.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) version=${2:-}; shift 2 ;;
    --output-dir) output_dir=${2:-}; shift 2 ;;
    --allow-dirty) allow_dirty=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$version" in
  v[0-9]*.[0-9]*.[0-9]*) ;;
  *) echo "Version must use the vMAJOR.MINOR.PATCH form" >&2; exit 2 ;;
esac
numeric_version=${version#v}
revision=$(git -C "$repo_dir" rev-parse HEAD)
tree=$(git -C "$repo_dir" rev-parse HEAD^{tree})
created=$(git -C "$repo_dir" show -s --format=%cI HEAD)
short_revision=$(git -C "$repo_dir" rev-parse --short=12 HEAD)

if [ "$allow_dirty" != true ]; then
  if ! git -C "$repo_dir" diff --quiet || ! git -C "$repo_dir" diff --cached --quiet ||
     [ -n "$(git -C "$repo_dir" ls-files --others --exclude-standard)" ]; then
    echo "Release assembly requires a clean source revision" >&2
    exit 2
  fi
fi
if [ -e "$output_dir" ] && [ -n "$(ls -A "$output_dir" 2>/dev/null)" ]; then
  echo "Release output must be empty: $output_dir" >&2
  exit 2
fi
mkdir -p "$output_dir"
output_dir=$(CDPATH= cd -- "$output_dir" && pwd)

python3 -c \
  'import json,sys; value=json.load(open(sys.argv[1], encoding="utf-8")); assert value["version"] == sys.argv[2]' \
  "$app_dir/web/package.json" "$numeric_version"

api_image="makersvault-api:${version}-${short_revision}"
web_image="makersvault-web:${version}-${short_revision}"
build_args="--build-arg MAKERSVAULT_VERSION=$version --build-arg MAKERSVAULT_REVISION=$revision --build-arg MAKERSVAULT_CREATED=$created"

echo "Building $api_image"
# shellcheck disable=SC2086
docker build --target runtime $build_args -t "$api_image" "$app_dir/api"
echo "Building $web_image"
# shellcheck disable=SC2086
docker build $build_args -t "$web_image" "$app_dir/web"

docker image inspect "$api_image" > "$output_dir/api-image-inspect.json"
docker image inspect "$web_image" > "$output_dir/web-image-inspect.json"

golang_image="golang@sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6"
bridge_dir="$app_dir/slicer-bridge"
uid=$(id -u)
gid=$(id -g)
ldflags="-s -w -buildid= -X main.version=$version -X main.revision=$revision"

docker run --rm \
  --user "$uid:$gid" \
  -e HOME=/tmp -e GOCACHE=/tmp/go-cache -e GOMODCACHE=/tmp/go-mod \
  -v "$bridge_dir:/src:ro" -w /src \
  "$golang_image" \
  sh -c 'go test ./...'

for target in \
  linux-amd64 linux-arm64 \
  windows-amd64 windows-arm64 \
  darwin-amd64 darwin-arm64
do
  target_os=${target%-*}
  target_arch=${target#*-}
  filename="makersvault-bridge-$target"
  if [ "$target_os" = windows ]; then
    filename="$filename.exe"
  fi
  echo "Building $filename"
  docker run --rm \
    --user "$uid:$gid" \
    -e HOME=/tmp -e GOCACHE=/tmp/go-cache -e GOMODCACHE=/tmp/go-mod \
    -e CGO_ENABLED=0 -e GOOS="$target_os" -e GOARCH="$target_arch" \
    -e RELEASE_LDFLAGS="$ldflags" \
    -v "$bridge_dir:/src:ro" -v "$output_dir:/release" -w /src \
    "$golang_image" \
    sh -c 'go build -trimpath -buildvcs=false -ldflags "$RELEASE_LDFLAGS" -o "/release/$1" ./cmd/slicer-bridge' sh "$filename"
done

"$output_dir/makersvault-bridge-linux-amd64" --version | \
  grep -F "MakersVault Bridge $version ($revision)" >/dev/null

syft_image="anchore/syft@sha256:1288ea4c8b38767b4e620c1e312c8cb26b6e887a99b4f07ab6cd19fc6f225026"
echo "Generating SPDX SBOMs with Syft v1.50.0"
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  "$syft_image" "$api_image" -o spdx-json > "$output_dir/makersvault-api.spdx.json"
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  "$syft_image" "$web_image" -o spdx-json > "$output_dir/makersvault-web.spdx.json"
for binary in "$output_dir"/makersvault-bridge-*; do
  filename=$(basename "$binary")
  docker run --rm -v "$output_dir:/scan:ro" \
    "$syft_image" "file:/scan/$filename" -o spdx-json > "$output_dir/$filename.spdx.json"
done

python3 "$script_dir/release-metadata.py" \
  --output-dir "$output_dir" \
  --version "$version" \
  --revision "$revision" \
  --tree "$tree" \
  --created "$created" \
  >/dev/null

(cd "$output_dir" && sha256sum --check SHA256SUMS)
echo "Local release assembly complete: $output_dir"
echo "No image or artifact was pushed."
