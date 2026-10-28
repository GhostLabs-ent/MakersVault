.PHONY: verify verify-fast verify-lint lint-api lint-web verify-api verify-web verify-bridge verify-compose verify-smoke

# Host toolchains. A repo-local .venv wins if present; otherwise PATH.
VENV ?= $(CURDIR)/.venv
PYTHON ?= $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)
RUFF ?= $(if $(wildcard $(VENV)/bin/ruff),$(VENV)/bin/ruff,ruff)
NPM ?= npm
GO ?= go

# Full gate. Run once per wave (or per ticket when it touches migrations,
# Dockerfiles, nginx.conf, compose manifests or dependency locks).
verify: verify-lint verify-api verify-web verify-bridge verify-compose verify-smoke

# Fast gate (~20s, no image builds, no container smoke). Run per ticket while
# iterating; the wave still ends on `make verify`.
verify-fast: verify-fast-api verify-fast-web verify-fast-bridge

verify-fast-api:
	cd makervault/api && $(RUFF) check . && $(PYTHON) -m pytest -q

verify-fast-web:
	cd makervault/web && $(NPM) run lint && $(NPM) run typecheck && $(NPM) run test:run

verify-fast-bridge:
	cd makervault/slicer-bridge && $(GO) test ./...

verify-lint: lint-api lint-web

lint-api:
	docker build --target lint -t makersvault-api-lint makervault/api

lint-web:
	docker build --target lint -t makersvault-web-lint makervault/web

verify-api:
	docker build --target test -t makersvault-api-gate0-test makervault/api
	docker run --rm makersvault-api-gate0-test

verify-web:
	docker build --target test -t makersvault-web-gate0-test makervault/web

verify-bridge:
	docker run --rm \
		-v "$(CURDIR)/makervault/slicer-bridge:/src" \
		-w /src golang:1.21.13 \
		sh -c 'go test ./... && go build -o /tmp/makersvault-bridge ./cmd/slicer-bridge'

verify-compose:
	cd makervault && docker compose -f docker-compose.yml config -q
	cd makervault && docker compose -f docker-compose.deploy.yml config -q
	cd makervault && docker compose -f docker-deploy.yml config -q
	cd makervault && docker compose -f docker-compose.yml -f docker-compose.smoke.yml config -q

verify-smoke:
	./makervault/scripts/container-smoke.sh
