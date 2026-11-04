"""Build the djangosaml2 / pygamlastan SP configuration for one site.

This module must stay free of Django imports because settings modules import it.
"""

import os
from pathlib import Path
from typing import Any

BINDING_HTTP_POST = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
BINDING_HTTP_REDIRECT = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
NAMEID_FORMAT_TRANSIENT = "urn:oasis:names:tc:SAML:2.0:nameid-format:transient"
SIG_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
DIGEST_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"

# The test IdP lives at idp.<IT42_DOMAIN> (compose passes the domain to every container).
IT42_DOMAIN = os.environ.get("IT42_DOMAIN") or "it42.vr"
IDP_ENTITY_ID = f"https://idp.{IT42_DOMAIN}/metadata"

# SAML attribute (friendly name) -> User fields. The IdP only issues transient
# NameIDs, so the stable subject is the ``uid`` attribute.
SAML_ATTRIBUTE_MAPPING: dict[str, tuple[str, ...]] = {
    "uid": ("sso_subject",),
    "mail": ("email",),
    "email": ("email",),
    "givenName": ("first_name",),
    "sn": ("last_name",),
}


def build_saml_config(
    *, site_url: str, key_dir: str, idp_metadata: str, name: str
) -> dict[str, Any]:
    keys = Path(key_dir)
    return {
        "entityid": f"{site_url}/saml2/metadata/",
        "allow_unknown_attributes": True,
        "service": {
            "sp": {
                "name": name,
                "name_id_policy_format": NAMEID_FORMAT_TRANSIENT,
                "endpoints": {
                    "assertion_consumer_service": [
                        (f"{site_url}/saml2/acs/", BINDING_HTTP_POST),
                    ],
                    # idp2 answers LogoutRequests with a signed LogoutResponse,
                    # POSTed here.
                    "single_logout_service": [
                        (f"{site_url}/saml2/ls/post/", BINDING_HTTP_POST),
                    ],
                },
                "signing_algorithm": SIG_RSA_SHA256,
                "digest_algorithm": DIGEST_SHA256,
                "authn_requests_signed": True,
                "logout_requests_signed": True,
                "want_logout_response_signed": True,
                "want_response_signed": True,
                "want_assertions_signed": True,
                "allow_unsolicited": False,
                "required_attributes": ["uid"],
                "optional_attributes": ["mail", "givenName", "sn", "cn"],
                "idp": {IDP_ENTITY_ID: {}},
            },
        },
        "metadata": {"local": [idp_metadata]},
        "key_file": str(keys / "sp.key"),
        "cert_file": str(keys / "sp.pem"),
        "accepted_time_diff": 30,
    }
