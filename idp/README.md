# Django IdP operations

Run these commands from the IT42 checkout on the laptop or server. They use the
checkout's Compose configuration and `.env`, including `IDP_IMAGE` and
`IT42_DOMAIN`; no separate IdP source checkout is required. To operate on the
server, SSH there first and change to `/home/debian/it42-poc`.

## Service and account commands

| Command | Purpose |
| --- | --- |
| `just idp-up` | Start the configured image and wait for health |
| `just idp-restart` | Recreate using a rebuilt local image, retaining accounts |
| `just idp-update` | Pull the configured tag, recreate, refresh metadata in apps |
| `just idp-logs` | Follow IdP logs |
| `just idp-check` | Run Django configuration checks |
| `just idp-create-user alice alice@example.org` | Create an account; print its generated password once |
| `just idp-create-user operator operator@example.org --admin` | Create an IdP administrator |
| `just idp-set-password staff1 hunter2` | Set the supplied password (short demo passwords allowed) |
| `just idp-set-password alice` | Generate a replacement password |
| `just idp-set-admin alice enable` | Grant IdP administration; use `disable` to revoke |
| `just idp-import-users /path/to/users.json` | Import a host JSON file; default is `idp/users.json` |
| `just idp-manage showmigrations` | Run any command in the running IdP |
| `just idp-run check` | Run a one-off container, including before HTTP startup |
| `just idp-migrate` / `just idp-shell` | Apply migrations / open a Django shell |
| `just idp-metadata` | Print live, validated metadata |
| `just idp-refresh-metadata` | Save live metadata and restart app web services |
| `just idp-add-sp /path/to/partner.xml` | Trust SP metadata and restart the IdP |

Quote passwords containing spaces, for example `just idp-set-password staff1 "my demo password"`.

Management commands preserve argument boundaries and support redirected stdin.
To supply a password without putting it in command history:

```bash
read -rs -p 'New password: ' idp_password; printf '\n'
printf '%s\n' "$idp_password" | just idp-set-password alice --password-stdin
unset idp_password
```

IdP administrators are separate from IT42 organisation administrators; use
`just org-admin` for the latter. Password changes take effect immediately.

## Persistent data and initial setup

The image is `docker.io/kushaldas/django-idp:0.2.0`. Startup applies migrations
and collects static files. Accounts and sessions persist in `idp_data`; signing
keys stay in `secrets/saml/idp/`, and application secrets in `env/idp.env`.
`just reset` and `just purge` delete the IdP database along with other volumes.

For a new checkout, run `just setup` and `just up`. When migrating from idp2,
run `./scripts/make-env.sh` and `./scripts/make-saml-keys.sh`, update any old
`IDP_IMAGE` override in `.env`, then run `just up`. Existing signing keys stay.
Import profiles once and capture the generated passwords privately:

```sh
(umask 077; set -C; just idp-import-users > secrets/idp-import-passwords.txt)
```

Imports are atomic and reject existing accounts; they do not preserve old
passwords or grant administrator rights. There is no default password. Import
extra profiles explicitly with `just idp-import-users secrets/idp-users/FILE.json`
and save their output in a different private file. Do not overwrite an existing
credentials file when re-running an import. The acceptance browser reads the
local import credentials or an explicit `IDP_PASSWORD` test override.

## SAML metadata

The proxy uses port 8000. Metadata, SSO, and SLO live at `/idp/metadata`,
`/idp/sso/`, and `/idp/slo/`. SPs require signed assertions. After installing an
image with new endpoints, run `just idp-refresh-metadata`; it checks the entity
ID and signing certificate before replacing metadata, preserving the file's
bind mount, then restarts the app web services. `just idp-update` includes this
step. `just idp-restart` alone only recreates the IdP.
