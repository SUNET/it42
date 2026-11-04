#!/bin/sh
# Create a local CA (mkcert) and one TLS certificate for IT42_DOMAIN (default it42.vr)
# and its subdomains. A server in public DNS uses IT42_TLS=public_tls instead (Caddyfile).
#
# `mkcert -install` is run as the current user on purpose: it asks sudo for the
# system trust store itself and also updates the user's browser (NSS) stores.
# Running it as `sudo mkcert -install` would create a second CA under /root.
set -eu
cd "$(dirname "$0")/.."
. scripts/lib/domain.sh

mkdir -p certs
mkcert -install
mkcert -cert-file certs/it42.pem -key-file certs/it42-key.pem \
    "$IT42_DOMAIN" "*.$IT42_DOMAIN"
cp "$(mkcert -CAROOT)/rootCA.pem" certs/rootCA.pem
# Caddy runs as root in its container, but keep the key private on the host.
chmod 600 certs/it42-key.pem
echo "Certificates written to certs/. Never copy rootCA-key.pem."
