#!/bin/sh
# Give every IdP user one password instead of idp2's hard-coded hunter2.
#
#   scripts/set-idp-password.sh 'the password'
#
# Writes two lines to .env: IDP_PASSWORD (plaintext, read only by scripts/lib/browser.py
# for the acceptance run) and IDP_PASSWORD_HASH (base64 of its bcrypt hash, cost 10,
# made with the stack's Caddy image), which compose passes to idp/entrypoint.sh. Then
# recreate the IdP: docker compose up -d --force-recreate idp
set -eu
cd "$(dirname "$0")/.."

password=${1:?usage: scripts/set-idp-password.sh PASSWORD}
caddy_image=$(sed -n 's/^ *image: *\(caddy:[^ ]*\).*/\1/p' compose.yaml | head -n 1)
hash=$(docker run --rm "$caddy_image" caddy hash-password --algorithm bcrypt \
    --bcrypt-cost 10 --plaintext "$password" | tr -d '\n' | base64 -w0)

touch .env
sed -i '/^IDP_PASSWORD=/d; /^IDP_PASSWORD_HASH=/d' .env
printf 'IDP_PASSWORD=%s\nIDP_PASSWORD_HASH=%s\n' "$password" "$hash" >> .env
chmod 600 .env
echo "IDP_PASSWORD and IDP_PASSWORD_HASH written to .env."
echo "Next: docker compose up -d --force-recreate idp"
