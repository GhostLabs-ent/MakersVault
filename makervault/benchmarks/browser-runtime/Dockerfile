# Verification tooling only. Never used as an application runtime image.
FROM mcr.microsoft.com/playwright:v1.62.1-noble@sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libnss3-tools && apt-get clean
COPY firefox-policies.json /opt/makersvault-fixture-policies.json
RUN for browser_dir in /ms-playwright/firefox-*/firefox; do \
      test -d "$browser_dir" && mkdir -p "$browser_dir/distribution" && \
      install -m 644 /opt/makersvault-fixture-policies.json "$browser_dir/distribution/policies.json"; \
    done
COPY trust-fixture.sh /opt/makersvault-trust-fixture.sh
ENTRYPOINT ["sh", "/opt/makersvault-trust-fixture.sh"]
