.PHONY: verify verify-api verify-web verify-bridge verify-compose verify-smoke

verify: verify-api verify-web verify-bridge verify-compose verify-smoke

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

verify-smoke:
	./makervault/scripts/container-smoke.sh
