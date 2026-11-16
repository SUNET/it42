#!/bin/sh
# Create SAML signing key pairs and the metadata files that the SPs and the IdP
# exchange. TLS certificates are separate (scripts/make-certs.sh).
#
#   secrets/saml/<site>/sp.key, sp.pem    one RSA-3072 pair per SP (core, o1, o2, o1-review, o2-review, ro)
#   secrets/saml/sp-metadata/<site>.xml   SP metadata, registered at the IdP on start
#   secrets/saml/idp/idp.key, idp.pem     IdP signing pair (PKCS#8 key)
#   secrets/saml/idp/metadata.xml         IdP metadata, loaded by every SP
#
# Existing keys are kept; metadata is always regenerated from them.
set -eu
cd "$(dirname "$0")/.."
. scripts/lib/domain.sh  # the host names in the metadata

umask 077
mkdir -p secrets/saml/sp-metadata secrets/saml/idp
# Extra IdP profiles for explicit imports; may stay empty.
mkdir -p secrets/idp-users

cert_body() {
    grep -v -- '-----' "$1" | tr -d '\n'
}

new_pair() {  # dir common-name
    if [ ! -s "$1/sp.key" ] && [ ! -s "$1/idp.key" ]; then
        mkdir -p "$1"
        openssl req -x509 -newkey rsa:3072 -days 825 -nodes -sha256 \
            -subj "/CN=$2" -keyout "$1/$3.key" -out "$1/$3.pem" 2>/dev/null
        echo "create  $1/$3.key"
    else
        echo "keep    $1/$3.key"
    fi
}

for site in core o1 o2 o3 o4 o5 o1-review o2-review o3-review o4-review o5-review ro; do
    case "$site" in
        core) host="$IT42_DOMAIN" ;;
        ro) host="ro.$IT42_DOMAIN" ;;
        *) host="f$site.$IT42_DOMAIN" ;;  # org slugs stay o1/o2; the sites are fo1/fo2(-review)
    esac
    new_pair "secrets/saml/$site" "$host" sp
    cert="$(cert_body "secrets/saml/$site/sp.pem")"
    cat > "secrets/saml/sp-metadata/$site.xml" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" xmlns:ds="http://www.w3.org/2000/09/xmldsig#" entityID="https://$host/saml2/metadata/">
  <md:SPSSODescriptor AuthnRequestsSigned="true" WantAssertionsSigned="true" protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:KeyDescriptor use="signing">
      <ds:KeyInfo><ds:X509Data><ds:X509Certificate>$cert</ds:X509Certificate></ds:X509Data></ds:KeyInfo>
    </md:KeyDescriptor>
    <md:SingleLogoutService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" Location="https://$host/saml2/ls/post/"/>
    <md:NameIDFormat>urn:oasis:names:tc:SAML:2.0:nameid-format:transient</md:NameIDFormat>
    <md:AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" Location="https://$host/saml2/acs/" index="1" isDefault="true"/>
  </md:SPSSODescriptor>
</md:EntityDescriptor>
XML
done

new_pair secrets/saml/idp "idp.$IT42_DOMAIN" idp
cert="$(cert_body secrets/saml/idp/idp.pem)"
# Local metadata for the Django IdP (assertion signing and browser SAML logout).
cat > secrets/saml/idp/metadata.xml <<XML
<?xml version="1.0" encoding="UTF-8"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" xmlns:ds="http://www.w3.org/2000/09/xmldsig#" entityID="https://idp.$IT42_DOMAIN/idp/metadata">
  <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:KeyDescriptor use="signing">
      <ds:KeyInfo><ds:X509Data><ds:X509Certificate>$cert</ds:X509Certificate></ds:X509Data></ds:KeyInfo>
    </md:KeyDescriptor>
    <md:SingleLogoutService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" Location="https://idp.$IT42_DOMAIN/idp/slo/"/>
    <md:SingleLogoutService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" Location="https://idp.$IT42_DOMAIN/idp/slo/"/>
    <md:NameIDFormat>urn:oasis:names:tc:SAML:2.0:nameid-format:transient</md:NameIDFormat>
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" Location="https://idp.$IT42_DOMAIN/idp/sso/"/>
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" Location="https://idp.$IT42_DOMAIN/idp/sso/"/>
  </md:IDPSSODescriptor>
</md:EntityDescriptor>
XML

# The containers run as non-root users that differ from the host user; the
# files are bind-mounted read-only, so make them readable.
chmod 700 secrets
chmod 755 secrets/saml secrets/saml/*
chmod 644 secrets/saml/*/*
echo "SAML keys and metadata are in secrets/saml/."
