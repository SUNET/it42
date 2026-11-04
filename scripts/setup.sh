#!/bin/sh
# One-time setup from a clean clone: env files, the research organisation directory,
# TLS certificate, SAML keys and RabbitMQ definitions. Safe to re-run; existing secrets and keys are kept.
set -eu
cd "$(dirname "$0")/.."
. scripts/lib/domain.sh
./scripts/make-env.sh
./scripts/make-certs.sh
./scripts/make-saml-keys.sh
python3 scripts/gen-rabbit-defs.py
if ! grep -q "ro.$IT42_DOMAIN" /etc/hosts; then
    d=$IT42_DOMAIN
    echo
    echo "Add the hostnames to /etc/hosts (needed by your browser):"
    echo "  echo \"127.0.0.1 $d fo1.$d fo2.$d fo1-review.$d fo2-review.$d ro.$d idp.$d mq.$d\" | sudo tee -a /etc/hosts"
fi
echo
echo "Next: docker compose up -d --build"
