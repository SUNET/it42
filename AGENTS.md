# Repository Guidelines

## Project Structure & Module Organization

IT42 is a Django grant application proof of concept using Python 3.13+. Source lives in `src/it42/`: `core/` handles applicant-facing functionality, `org/` handles funding organisations and reviews, `ro/` handles research organisations and signing, and `common/` contains shared infrastructure. Each zone has a settings module in `settings/`. Keep migrations within their Django apps.

Tests mirror these zones under `tests/`. Django templates live in `templates/`, browser assets in `static/it42/`, and operational scripts in `scripts/`. `compose.yaml` and `docker/` define the local service stack.

## Build, Test, and Development Commands

- `just sync`: install dependencies with `sfw uv sync` (requires Socket Firewall).
- `just setup`: generate local environment files, certificates, SAML keys, and RabbitMQ definitions; follow its hostname setup instructions.
- `just up`: build and start the Docker Compose stack.
- `just rebuild`: rebuild Django services after source, template, or asset changes.
- `just test`: run all three zone test suites using SQLite, without Docker.
- `just lint`: check Ruff formatting, Ruff lint rules, and types with `ty`.
- `just fmt`: format and apply Ruff fixes.
- `just migrations`: generate migrations and check all three zones for missing migrations.
- `just acceptance`: run end-to-end acceptance and isolation checks against the running stack.

## Coding Style & Naming Conventions

Use four-space Python indentation, a 100-character line limit, and Ruff-managed formatting and imports. Use `snake_case` for functions and modules and `PascalCase` for classes. Follow existing type annotations and Django app conventions; place business operations in existing `services.py` modules where appropriate. Add docstrings and code comments explaining properly for all code and update/add while editing any new code.

## Testing Guidelines

Use pytest and pytest-django. Name files `test_*.py` and functions `test_*`; place fixtures in the relevant `conftest.py`. Add regression tests for changed behaviour, especially permissions and cross-zone messaging. `uv run pytest` covers only core/common; use `just test` for all zones or `./scripts/test.sh -k pattern` to filter them. No numeric coverage threshold is configured.

## Commit & Pull Request Guidelines

Recent history uses short subjects such as `add: one liner for README`; follow that concise style. PRs should describe the behaviour change, affected zones, validation performed, and related issues. Include screenshots for UI changes and explain migrations or configuration changes.

## Agent & Configuration Rules

Codex must not create commits unless explicitly asked by the user. Keep generated secrets, certificates, and local environment files untracked; update `.example` files for configuration changes. `just reset`, `just fresh`, and `just purge` delete local data.
