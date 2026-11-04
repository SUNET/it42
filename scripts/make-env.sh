#!/bin/sh
# Create env/*.env from env/*.env.example, replacing every __RANDOM__ with a fresh
# random secret, and config/research_orgs.toml (the research organisation directory)
# from its example. Existing files are left untouched.
set -eu
cd "$(dirname "$0")/.."
. scripts/lib/domain.sh

for example in env/*.env.example; do
    target="${example%.example}"
    if [ -e "$target" ]; then
        echo "keep    $target"
        continue
    fi
    : > "$target"
    chmod 600 "$target"
    while IFS= read -r line || [ -n "$line" ]; do
        while case "$line" in *__RANDOM__*) true ;; *) false ;; esac; do
            secret="$(openssl rand -hex 24)"
            line="$(printf '%s' "$line" | sed "s/__RANDOM__/$secret/")"
        done
        # The examples name the laptop domain; a server's .env may set another.
        printf '%s\n' "$line" | sed "s/it42\.vr/$IT42_DOMAIN/g" >> "$target"
    done < "$example"
    echo "create  $target"
done

if [ -e config/research_orgs.toml ]; then
    echo "keep    config/research_orgs.toml"
else
    cp config/research_orgs.toml.example config/research_orgs.toml
    echo "create  config/research_orgs.toml"
fi
