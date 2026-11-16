"""Settings for the research organisation site (ro.it42.vr).

One site and one database serve every research organisation (RO) in the directory
(``config/research_orgs.toml``, ``it42.common.research_orgs``); each user belongs to one
RO and sees only its requests. The RO zone talks only to the orgs (``o1-to-ro``,
``ro-to-o1``, ...), never to the core.
"""

from it42.common.saml_config import IT42_DOMAIN, build_saml_config

from .base import *  # noqa: F403
from .base import BASE_INSTALLED_APPS, MIDDLEWARE, SITE_URL, env, templates

APP_ROLE = "ro"
ORG_SLUG = ""
SITE_NAME = env("SITE_NAME", "IT42 Research organisations")
THEME_COLOR = env("THEME_COLOR", "#ac7aef")
# The public IT42 site, linked from the logged-out page.
CORE_SITE_URL = env("CORE_SITE_URL", f"https://{IT42_DOMAIN}")

INSTALLED_APPS = [
    *BASE_INSTALLED_APPS,
    "it42.ro.accounts",
    "it42.ro.members",
    "it42.ro.signing",
]

AUTH_USER_MODEL = "ro_accounts.User"
ROOT_URLCONF = "it42.ro.urls"
MIDDLEWARE = [*MIDDLEWARE, "it42.ro.members.access.RoMemberGateMiddleware"]
TEMPLATES = templates(["it42.ro.members.access.member_context"])

# The orgs (funders) that send signature requests: slug -> display name. The RO site
# shows these names, never one an event claims.
KNOWN_ORGS = {"o1": "Org 1", "o2": "Org 2", "o3": "Formas", "o4": "Forte", "o5": "Vinnova"}

SAML_CONFIG = build_saml_config(
    site_url=SITE_URL,
    key_dir=env("SAML_KEY_DIR", "secrets/saml/ro"),
    idp_metadata=env("SAML_IDP_METADATA", "secrets/saml/idp/metadata.xml"),
    name=SITE_NAME,
)
