"""Settings for an org's sites: the staff site (fo1.it42.vr) and the reviewer site
(fo1-review.it42.vr).

One module serves every org; ORG_SLUG and the env file select which one. ``SITE_ROLE``
picks which of the org's two sites a container serves: both share the org's database,
apps and media, and differ in URLconf, access gate, hostname, SAML service provider and
theme.
"""

from django.core.exceptions import ImproperlyConfigured

from it42.common.saml_config import IT42_DOMAIN, build_saml_config

from .base import *  # noqa: F403
from .base import BASE_INSTALLED_APPS, MIDDLEWARE, SITE_URL, env, templates

APP_ROLE = "org"
ORG_SLUG = env("ORG_SLUG", "o1")
SITE_ROLE = env("SITE_ROLE", "staff")
if SITE_ROLE not in {"staff", "review"}:
    raise ImproperlyConfigured("SITE_ROLE must be 'staff' or 'review'")
SITE_NAME = env("SITE_NAME", f"Org {ORG_SLUG.removeprefix('o')}")
# The org's own name, shown where the site name would mislead ("not on any review
# panel of Org 1" on the reviewer site, whose SITE_NAME is "Org 1 review panels").
ORG_NAME = env("ORG_NAME", SITE_NAME)
# The public IT42 site, linked from the logged-out page (the org sites have no public page).
CORE_SITE_URL = env("CORE_SITE_URL", f"https://{IT42_DOMAIN}")
# IdP subjects that become admins of this org automatically when they log in
# (comma-separated; env/<org>.env lists staff1 for o1 and staff2 for o2).
ORG_BOOTSTRAP_ADMINS = [s.strip() for s in env("ORG_BOOTSTRAP_ADMINS", "").split(",") if s.strip()]

INSTALLED_APPS = [
    *BASE_INSTALLED_APPS,
    "it42.org.accounts",
    "it42.org.members",
    "it42.org.grants",
    "it42.org.applications",
    "it42.org.review",
]

AUTH_USER_MODEL = "org_accounts.User"

TEMPLATES = templates(
    [
        "it42.org.members.access.membership_context",
        "it42.org.review.access.reviewer_context",
    ]
)
if SITE_ROLE == "review":
    MIDDLEWARE = [*MIDDLEWARE, "it42.org.review.access.ReviewerGateMiddleware"]
    ROOT_URLCONF = "it42.org.review.site_urls"
    _saml_key_dir = f"secrets/saml/{ORG_SLUG}-review"
else:
    MIDDLEWARE = [*MIDDLEWARE, "it42.org.members.access.MembershipGateMiddleware"]
    ROOT_URLCONF = "it42.org.urls"
    _saml_key_dir = f"secrets/saml/{ORG_SLUG}"

SAML_CONFIG = build_saml_config(
    site_url=SITE_URL,
    key_dir=env("SAML_KEY_DIR", _saml_key_dir),
    idp_metadata=env("SAML_IDP_METADATA", "secrets/saml/idp/metadata.xml"),
    name=SITE_NAME,
)
