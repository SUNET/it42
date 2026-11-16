#!/usr/bin/env bash
# Accept a simple password argument, generated password, or native CLI options.
set -euo pipefail
cd "$(dirname "$0")/.."
username=${1:?usage: scripts/set-idp-password.sh USERNAME [PASSWORD | --password-stdin]}
shift
if [[ $# -gt 0 && $1 != --* ]]; then
    if [[ $# != 1 || $1 == *$'\n'* || $1 == *$'\r'* ]]; then
        echo 'Supply one quoted password without line breaks.' >&2
        exit 2
    fi
    # The local demo shortcut permits short passwords. Pass the value to Django
    # over stdin so Docker/management command arguments do not contain it.
    printf '%s\n' "$1" | ./scripts/idp-manage.sh idp_user set-password "$username" \
        --password-stdin --allow-weak-password
else
    exec ./scripts/idp-manage.sh idp_user set-password "$username" "$@"
fi
