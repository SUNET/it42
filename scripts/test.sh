#!/bin/sh
# Run the test suite for every zone type (core, org, research organisation). Each has
# its own settings module and app set, so they run as separate pytest sessions.
set -eu
cd "$(dirname "$0")/.."
uv run pytest --ds=it42.settings.core tests/core tests/common "$@"
SITE_NAME="Org 1" THEME_COLOR="#198754" ORG_SLUG=o1 \
    uv run pytest --ds=it42.settings.org tests/org "$@"
uv run pytest --ds=it42.settings.ro tests/ro "$@"
