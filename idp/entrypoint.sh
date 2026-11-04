#!/bin/bash
# Wrapper entrypoint for kushaldas/idp2.
#
# idp2 keeps registered service providers in memory only, and the image has no
# curl or wget. Start idp2, then PUT every SP metadata file from /sp-metadata to
# /services/<name> using bash's /dev/tcp. A marker file tells the health check
# that registration finished.
#
# Users: idp2 loads /data/users.json with the hard-coded password hunter2. Users in
# /data/extra-users/*.json (server-only, from secrets/idp-users/) are added through
# PUT /users/<name>, and when IDP_PASSWORD_HASH is set every user, from both places,
# gets that password instead (scripts/set-idp-password.sh). The hash goes in as
# "hashed_password": idp2 never reads a plaintext "password" field, because its User
# struct has two fields with that JSON name and encoding/json then ignores both.
set -euo pipefail

rm -f /tmp/sps-registered
/usr/bin/idp2 -idp "${IDP_BASE_URL:?}" -bind :8080 &
idp_pid=$!
trap 'kill -TERM "$idp_pid" 2>/dev/null; wait "$idp_pid"' TERM INT

urlencode() {  # text -> percent-encoded path segment (byte by byte, so å works)
    local LC_ALL=C text=$1 out="" c i
    for ((i = 0; i < ${#text}; i++)); do
        c=${text:i:1}
        case "$c" in
            [A-Za-z0-9._~-]) out+=$c ;;
            *) out+=$(printf '%%%02X' "'$c") ;;
        esac
    done
    printf '%s' "$out"
}

# base64 of the bcrypt hash of hunter2 (cost 10), for extra users on a laptop.
HUNTER2_HASH=JDJhJDEwJFJGUUJETFEucFByV29qZG83ZFJwLy5KWU9FT1ovelFxaXdhM282TXdCZEc1aW5LM1ozQXRt

put_users() {  # users-file hash: PUT every user object of a JSON list with that password
    local file=$1 hash=$2 part name status
    rm -f /tmp/user.*
    # One object per file: the user lists hold flat objects (only "groups" is a list).
    awk 'BEGIN { depth = 0; n = 0 }
        {
            for (i = 1; i <= length($0); i++) {
                c = substr($0, i, 1)
                if (c == "{" && depth++ == 0) { n++; f = "/tmp/user." n; printf "" > f }
                if (depth > 0) printf "%s", c >> f
                if (c == "}" && --depth == 0) close(f)
            }
            if (depth > 0) printf "\n" >> f
        }' "$file"
    for part in /tmp/user.*; do
        [ -e "$part" ] || continue
        name=$(grep -o '"name"[[:space:]]*:[[:space:]]*"[^"]*"' "$part" | head -n 1 | sed 's/.*"\([^"]*\)"$/\1/')
        body=$(cat "$part")
        # hash is base64 (JSON's encoding of idp2's []byte), so it needs no escaping.
        printf '{"hashed_password": "%s", %s' "$hash" "${body#*\{}" > /tmp/body.json
        # A PUT keeps an existing user's stored hash, so drop the user first.
        http DELETE "/users/$(urlencode "$name")" > /dev/null
        status=$(http PUT "/users/$(urlencode "$name")" /tmp/body.json)
        if [ "$status" != 204 ]; then
            echo "setting user $name failed with HTTP $status" >&2
            return 1
        fi
        echo "user $name"
    done
    rm -f /tmp/user.* /tmp/body.json
}

http() {  # method path [body-file] -> prints the status code
    local method=$1 path=$2 body=${3:-} length=0 status
    [ -n "$body" ] && length=$(wc -c < "$body")
    exec 3<>/dev/tcp/127.0.0.1/8080
    {
        printf '%s %s HTTP/1.0\r\nHost: localhost\r\nContent-Length: %s\r\n' "$method" "$path" "$length"
        printf 'Content-Type: application/xml\r\n\r\n'
        [ -n "$body" ] && cat "$body"
    } >&3
    read -r _ status _ <&3
    exec 3<&-
    echo "$status"
}

for _ in $(seq 1 50); do
    if (exec 3<>/dev/tcp/127.0.0.1/8080) 2>/dev/null; then break; fi
    sleep 0.2
done

for file in /sp-metadata/*.xml; do
    name=$(basename "$file" .xml)
    status=$(http PUT "/services/$name" "$file")
    if [ "$status" != 204 ]; then
        echo "registering SP $name failed with HTTP $status" >&2
        kill -TERM "$idp_pid"
        exit 1
    fi
    echo "registered SP $name"
done
hash=${IDP_PASSWORD_HASH:-$HUNTER2_HASH}
if [ -n "${IDP_PASSWORD_HASH:-}" ]; then
    put_users /data/users.json "$hash" || { kill -TERM "$idp_pid"; exit 1; }
fi
for file in /data/extra-users/*.json; do
    [ -e "$file" ] || continue
    put_users "$file" "$hash" || { kill -TERM "$idp_pid"; exit 1; }
done
touch /tmp/sps-registered

wait "$idp_pid"
