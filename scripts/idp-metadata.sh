#!/usr/bin/env bash
# Trust only metadata using this stack's configured entity ID and signing key.
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/lib/domain.sh
mode=${1:-show}
case "$mode" in show|refresh) ;; *) echo 'Usage: idp-metadata.sh show|refresh' >&2; exit 2 ;; esac
metadata=$(mktemp)
trap 'rm -f "$metadata"' EXIT
docker compose exec -T idp python -c 'import sys, urllib.request; sys.stdout.buffer.write(urllib.request.urlopen("http://localhost:8000/idp/metadata", timeout=10).read())' > "$metadata"
python3 - "$metadata" "https://idp.$IT42_DOMAIN/idp/metadata" <<'CHECK'
import base64
import ssl
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

root = ET.parse(sys.argv[1]).getroot()
ns = {"md": "urn:oasis:names:tc:SAML:2.0:metadata", "ds": "http://www.w3.org/2000/09/xmldsig#"}
if root.tag != "{urn:oasis:names:tc:SAML:2.0:metadata}EntityDescriptor" or root.get("entityID") != sys.argv[2]:
    raise SystemExit("Unexpected IdP entity ID; existing metadata was kept")
cert = ssl.PEM_cert_to_DER_cert(Path("secrets/saml/idp/idp.pem").read_text())
certs = root.findall("md:IDPSSODescriptor/md:KeyDescriptor[@use='signing']/ds:KeyInfo/ds:X509Data/ds:X509Certificate", ns)
if not any(base64.b64decode(node.text or "") == cert for node in certs):
    raise SystemExit("IdP signing certificate mismatch; existing metadata was kept")
if not root.findall("md:IDPSSODescriptor/md:SingleSignOnService", ns):
    raise SystemExit("Missing SSO endpoints; existing metadata was kept")
CHECK
if [[ $mode == show ]]; then
    cat "$metadata"
    exit
fi
# Preserve the inode: app containers bind-mount this individual file.
cat "$metadata" > secrets/saml/idp/metadata.xml
chmod 644 secrets/saml/idp/metadata.xml
docker compose restart core-web o1-web o2-web o1-review-web o2-review-web o3-web o3-review-web o4-web o4-review-web o5-web o5-review-web ro-web
echo 'IdP metadata refreshed; running web services restarted.'
