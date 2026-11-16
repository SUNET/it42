# Common tasks for the it42 PoC. `just` (or `just --list`) shows them.

set positional-arguments
set shell := ["bash", "-euo", "pipefail", "-c"]

web_services := "core-web core-worker core-orcid o1-web o1-worker o1-review-web o2-web o2-worker o2-review-web o3-web o3-worker o3-review-web o4-web o4-worker o4-review-web o5-web o5-worker o5-review-web ro-web ro-worker"

default:
    @just --list --unsorted

# ---- Code -----------------------------------------------------------------------------

# Run every test in every zone (SQLite, no Docker needed)
test:
    ./scripts/test.sh

# ruff format --check, ruff check, ty check
lint:
    ./scripts/lint.sh

# Format and auto-fix with ruff
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# Install/sync dependencies through Socket Firewall
sync:
    sfw uv sync

# Make migrations for every zone and check nothing is missing
migrations:
    APP_ROLE=core uv run python manage.py makemigrations
    APP_ROLE=org uv run python manage.py makemigrations
    APP_ROLE=ro uv run python manage.py makemigrations
    APP_ROLE=core uv run python manage.py makemigrations --check --dry-run
    APP_ROLE=org uv run python manage.py makemigrations --check --dry-run
    APP_ROLE=ro uv run python manage.py makemigrations --check --dry-run

# ---- Stack ----------------------------------------------------------------------------

# One-time local setup: env files, mkcert certificate, SAML keys and metadata, RabbitMQ definitions
setup:
    ./scripts/setup.sh

# Build and start all services
up:
    docker compose up -d --build

# Rebuild only the Django containers after changing src/, templates/ or static/
rebuild:
    docker compose up -d --build {{ web_services }}

# Stop the stack, keep all data
down:
    docker compose down

# Service status
ps:
    docker compose ps

# Follow logs (optionally of one service: `just logs core-web`)
logs *services:
    docker compose logs -f --tail=200 {{ services }}

# Django shell in a zone's web container (`just shell o1-web`)
shell service="core-web":
    docker compose exec {{ service }} python manage.py shell

# Make a subject an org admin after their first login (`just org-admin o1-web staff1`)
org-admin service subject:
    docker compose exec {{ service }} python manage.py bootstrap_org_admin --subject {{ subject }}

# ---- IdP (run these from this checkout on the laptop or server) -------------------------

# Start the IdP using the configured image and persistent account database
idp-up:
    docker compose up -d --wait idp

# Recreate the IdP to use a rebuilt local image; keep accounts and keys
idp-restart:
    docker compose up -d --force-recreate --wait idp

# Pull the configured image, recreate the IdP, and refresh app trust metadata
idp-update:
    docker compose pull idp
    just idp-restart
    just idp-refresh-metadata

# Follow the IdP logs
idp-logs:
    docker compose logs -f --tail=200 idp

# Run a management command in the running IdP (supports piped stdin)
idp-manage +args:
    @./scripts/idp-manage.sh "$@"

# Run a one-off management command before starting the IdP (runs migrations first)
idp-run +args:
    @./scripts/idp-manage.sh --one-off "$@"

# Check the running IdP's Django configuration
idp-check:
    @./scripts/idp-manage.sh check

# Apply pending migrations (also automatic on container startup)
idp-migrate:
    @./scripts/idp-manage.sh migrate --noinput

# Open the IdP's Django shell
idp-shell:
    @./scripts/idp-manage.sh shell

# Create an account; optional --admin or --password-stdin; prints generated password once
idp-create-user username email *options:
    @./scripts/idp-manage.sh idp_user create "$1" --email "$2" "${@:3}"

# Set a password: `just idp-set-password staff1 hunter2`; omit it to generate one
idp-set-password username *options:
    @./scripts/set-idp-password.sh "$@"

# Grant/revoke IdP administration (separate from IT42 organisation roles)
idp-set-admin username action:
    @case "$2" in enable|disable) ;; *) echo 'Action must be enable or disable.' >&2; exit 2 ;; esac; ./scripts/idp-manage.sh idp_user set-admin "$1" "--$2"

# Import a host JSON file once; prints new passwords (redirect to a private file)
idp-import-users file="idp/users.json":
    @file=$(realpath -e -- "$1"); test -f "$file"; docker compose run --rm --no-deps -T -v "$file:/import/source.json:ro" idp python manage.py idp_import_users /import/source.json

# Print live IdP metadata without changing app configuration
idp-metadata:
    @./scripts/idp-metadata.sh show

# Save live IdP metadata and restart running app web services to reload it
idp-refresh-metadata:
    @./scripts/idp-metadata.sh refresh

# Trust a new SP metadata file and reload the IdP's resolver
idp-add-sp file:
    @file=$(realpath -e -- "$1"); test -f "$file"; install -m 644 -- "$file" "secrets/saml/sp-metadata/$(basename -- "$file")"
    docker compose restart idp

# ---- Data -----------------------------------------------------------------------------

# Remove ALL old data: stop the stack and delete the database, media, RabbitMQ and Caddy volumes (code, certs, env files and SAML keys are kept)
reset:
    docker compose down -v --remove-orphans
    @echo "All data volumes removed. 'just up' starts an empty stack."

# Reset and start again from empty databases
fresh: reset up

# Like reset, and also delete everything scripts/setup.sh generated (certs, env files, SAML keys, RabbitMQ definitions); run `just setup` afterwards
purge: reset
    rm -rf certs secrets env/*.env rabbitmq/definitions.json
    @echo "Generated files removed. Run 'just setup' before 'just up'."

# ---- Checks against the running stack -------------------------------------------------

# Network, credential, ACL, forged-event and review-note isolation checks
isolation:
    ./scripts/check-isolation.sh

# Every acceptance check end to end (re-runnable), then the isolation checks
acceptance:
    uv run python scripts/acceptance.py

# Tests, lint and the full acceptance run
all: test lint acceptance
