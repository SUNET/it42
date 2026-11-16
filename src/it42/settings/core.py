"""Settings for the core site (it42.vr): public listings and applicants."""

from it42.common.saml_config import build_saml_config

from .base import *  # noqa: F403
from .base import BASE_INSTALLED_APPS, SITE_URL, env

APP_ROLE = "core"
SITE_NAME = env("SITE_NAME", "IT42 Grants")
THEME_COLOR = env("THEME_COLOR", "#020344")
ORG_SLUG = ""

INSTALLED_APPS = [
    *BASE_INSTALLED_APPS,
    "it42.core.accounts",
    "it42.core.profiles",
    "it42.core.catalog",
    "it42.core.applications",
]

AUTH_USER_MODEL = "core_accounts.User"
ROOT_URLCONF = "it42.core.urls"

# Every org the core exchanges events with: slug -> display name and colour. The core
# shows these names, never the org_name an event claims.
KNOWN_ORGS = {"o1": "Org 1", "o2": "Org 2", "o3": "Formas", "o4": "Forte", "o5": "Vinnova"}
ORG_COLORS = {"o1": "#198754", "o2": "#6f42c1", "o3": "#198754", "o4": "#6f42c1", "o5": "#6f42c1"}

SAML_CONFIG = build_saml_config(
    site_url=SITE_URL,
    key_dir=env("SAML_KEY_DIR", "secrets/saml/core"),
    idp_metadata=env("SAML_IDP_METADATA", "secrets/saml/idp/metadata.xml"),
    name="IT42 Grants",
)

# ORCID Public API, used by the researcher profile import (core only; mocked in tests).
ORCID_API_URL = env("ORCID_API_URL", "https://pub.orcid.org/v3.0")
ORCID_TIMEOUT = 15
ORCID_MAX_WORKS = 300
