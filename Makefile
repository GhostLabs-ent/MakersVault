.PHONY: verify verify-fast verify-lint lint-api lint-web verify-version verify-api verify-web verify-bridge verify-compose verify-smoke

# Host toolchains. A repo-local .venv wins if present; otherwise PATH.
VENV ?= $(CURDIR)/.venv
PYTHON ?= $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)
RUFF ?= $(if $(wildcard $(VENV)/bin/ruff),$(VENV)/bin/ruff,ruff)
NPM ?= npm
GO ?= go

# Verification isolation (Mf-ly4o). Everything mutable a verification run
# creates - test DB, test storage, image tags, compose project name, host
# ports - is namespaced by MV_RUN_ID so two runs can share one host and one
# Docker daemon. Default: this make process's pid plus the worktree directory,
# which keeps concurrent runs apart with no setup. Set MV_RUN_ID to join a lane
# (see makervault/docs/DEVELOPMENT.md).
ifeq ($(strip $(MV_RUN_ID)),)
MV_RUN_ID := $(shell echo "$$PPID-$$(basename "$(CURDIR)")")
endif
# Image tags and compose project names allow only [a-z0-9_.-] (project names
# also must start with an alphanumeric), so normalise whatever MV_RUN_ID holds.
# Dots become dashes too: the smoke script and the API tests allow only
# [a-z0-9_-], and one normalisation for all three keeps a lane's tag, project
# name and test path spelled the same way.
RUN_ID := $(shell printf '%s' '$(MV_RUN_ID)' | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9_-]/-/g')
export MV_RUN_ID

API_TEST_IMAGE ?= makersvault-api-gate0-test:$(RUN_ID)
WEB_TEST_IMAGE ?= makersvault-web-gate0-test:$(RUN_ID)
API_LINT_IMAGE ?= makersvault-api-lint:$(RUN_ID)
WEB_LINT_IMAGE ?= makersvault-web-lint:$(RUN_ID)

# Full gate. Run once per wave (or per ticket when it touches migrations,
# Dockerfiles, nginx.conf, compose manifests or dependency locks).
verify: verify-lint verify-api verify-web verify-bridge verify-compose verify-smoke

# Fast gate (~20s, no image builds, no container smoke). Run per ticket while
# iterating; the wave still ends on `make verify`.
verify-fast: verify-version verify-fast-api verify-fast-web verify-fast-bridge

verify-fast-api:
	cd makervault/api && $(RUFF) check . && $(PYTHON) -m pytest -q

verify-fast-web:
	cd makervault/web && $(NPM) run lint && $(NPM) run typecheck && $(NPM) run test:run

verify-fast-bridge:
	cd makervault/slicer-bridge && $(GO) test ./...

verify-lint: lint-api lint-web

lint-api:
	docker build --target lint -t $(API_LINT_IMAGE) makervault/api
	docker image rm $(API_LINT_IMAGE) >/dev/null 2>&1 || true

lint-web:
	docker build --target lint -t $(WEB_LINT_IMAGE) makervault/web
	docker image rm $(WEB_LINT_IMAGE) >/dev/null 2>&1 || true

# Version drift guard (Mf-cvoo). `python3` on CI runners, repo .venv locally.
verify-version:
	$(PYTHON) makervault/scripts/check_version.py

verify-api: verify-version
	docker build --target test -t $(API_TEST_IMAGE) makervault/api
	status=0; docker run --rm $(API_TEST_IMAGE) || status=$$?; \
		docker image rm $(API_TEST_IMAGE) >/dev/null 2>&1 || true; exit $$status

verify-web: verify-version
	status=0; docker build --target test -t $(WEB_TEST_IMAGE) makervault/web || status=$$?; \
		docker image rm $(WEB_TEST_IMAGE) >/dev/null 2>&1 || true; exit $$status

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
