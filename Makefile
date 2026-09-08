.PHONY: verify verify-api verify-web verify-bridge verify-compose verify-smoke verify-passkeys verify-release verify-harness verify-lifecycle

verify: verify-api verify-web verify-bridge verify-compose verify-smoke verify-passkeys verify-release verify-harness verify-lifecycle

verify-api:
	docker build --target test -t makersvault-api-gate0-test makervault/api
	docker run --rm makersvault-api-gate0-test

verify-web:
	docker build --target test -t makersvault-web-gate0-test makervault/web

verify-bridge:
	docker run --rm \
		-v "$(CURDIR)/makervault/slicer-bridge:/src" \
		-w /src golang:1.26.6 \
		sh -c 'go test ./... && go build -o /tmp/makersvault-bridge ./cmd/slicer-bridge'

verify-compose:
	cd makervault && docker compose -f docker-compose.yml config -q
	cd makervault && AUTH_PASSWORD=compose-verification-password AUTH_SECRET=compose-verification-signing-secret-32-bytes docker compose --env-file /dev/null -f docker-compose.deploy.yml config -q
	cd makervault && AUTH_PASSWORD=compose-verification-password AUTH_SECRET=compose-verification-signing-secret-32-bytes docker compose --env-file /dev/null -f docker-deploy.yml config -q
	cd makervault && ./scripts/verify-compose-security.sh
	cd makervault && docker compose -f docker-compose.yml -f docker-compose.smoke.yml config -q
	cd makervault && docker compose -f docker-compose.yml -f docker-compose.preview-benchmark.yml config -q
	cd makervault && docker compose -f docker-compose.yml -f docker-compose.organization-benchmark.yml config -q
	cd makervault && docker compose -f docker-compose.yml -f docker-compose.mount-scan-verification.yml config -q

verify-smoke:
	./makervault/scripts/container-smoke.sh

verify-release:
	python3 makervault/scripts/verify-release-contract.py

verify-passkeys:
	./makervault/scripts/passkey-browser-smoke.sh

verify-harness:
	python3 -m unittest discover -s makervault/scripts/tests -v
	docker run --rm -v "$(CURDIR)/makervault/benchmarks:/bench:ro" \
		node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 \
		sh -c 'node --check /bench/preview/preview-baseline.mjs && node --check /bench/organization/organization-baseline.mjs && node --check /bench/organization/mount-scan-verification.mjs && node --check /bench/organization/tls-probe.mjs && node --check /bench/organization/request-order-regression.mjs && node --test /bench/session-client.test.mjs /bench/first-visible-card.test.mjs /bench/organization/chromium-profile.test.mjs'

verify-lifecycle:
	python3 makervault/scripts/gate13-lifecycle-drill.py --allow-dirty
