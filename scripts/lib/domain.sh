# Sourced by the setup scripts: sets IT42_DOMAIN from the environment, else from .env,
# else the laptop default it42.vr. Run from the repository root.
if [ -z "${IT42_DOMAIN:-}" ] && [ -f .env ]; then
    IT42_DOMAIN="$(sed -n 's/^IT42_DOMAIN=//p' .env | tail -n 1)"
fi
IT42_DOMAIN="${IT42_DOMAIN:-it42.vr}"
