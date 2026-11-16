#!/usr/bin/env bash
# Keep arguments intact and disable the Compose TTY when piping passwords/output.
set -euo pipefail
cd "$(dirname "$0")/.."
mode=exec
if [[ ${1:-} == --one-off ]]; then
    mode=run
    shift
fi
if [[ $# == 0 ]]; then
    echo 'Usage: idp-manage.sh [--one-off] COMMAND [ARGUMENTS...]' >&2
    exit 2
fi
options=()
if [[ ! -t 0 || ! -t 1 ]]; then options+=(-T); fi
if [[ $mode == run ]]; then
    exec docker compose run --rm --no-deps "${options[@]}" idp python manage.py "$@"
fi
exec docker compose exec "${options[@]}" idp python manage.py "$@"
