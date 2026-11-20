#!/usr/bin/env bash
# Automated isolation checks against the running stack (docker compose up -d).
#
#   1. Network: org and RO containers cannot reach any other zone's database; web
#      containers cannot reach AMQP.
#   2. Credentials: no container holds another zone's secrets; web containers hold
#      no broker credentials; each web container (staff, reviewer, RO) mounts only
#      its own SAML key.
#   3. RabbitMQ: an org's or the RO zone's credentials can only publish to its own
#      exchanges and read its own inbound queues (everything else is ACCESS_REFUSED).
#   4. A forged application.status_changed from o1 naming a2's g2 application (an
#      Org 2 application) is dead-lettered and changes nothing.
#   5. The core database contains no review-note text.
#   6. A signature.granted the RO zone sends to Org 2 about an Org 1 application is
#      dead-lettered and changes nothing; signers' comments reach only core's relay
#      outbox, not its applicant-domain state.
#
# Checks 4-6 need demo data (a2's applications, review notes, a signed application);
# run `uv run python scripts/acceptance.py` first, or they are reported as SKIP.
set -uo pipefail
cd "$(dirname "$0")/.."
. scripts/lib/domain.sh

pass=0 fail=0 skip=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$*"; pass=$((pass + 1)); }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; fail=$((fail + 1)); }
skp()  { printf '  \033[33mSKIP\033[0m %s\n' "$*"; skip=$((skip + 1)); }
section() { printf '\n\033[1m%s\033[0m\n' "$*"; }

dc() { docker compose "$@"; }
in_container() {  # service script [args...]: run a probe script with the service's python
    local service=$1 script=$2
    shift 2
    dc exec -T "$service" python -c "$(cat "$script")" "$@"
}
env_value() { grep -E "^$2=" "env/$1.env" | head -1 | cut -d= -f2-; }
container_env() { docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$(dc ps -q "$1")"; }
django_shell() {  # service python-code
    dc exec -T "$1" python manage.py shell --no-imports -v 0 -c "$2"
}

section "1. Network isolation"
check_tcp() {  # service expectation targets...
    local service=$1 expect=$2
    shift 2
    while read -r target state rest; do
        if [ "$state" = "$expect" ]; then
            ok "$service -> $target: $state ${rest}"
        else
            bad "$service -> $target: $state ${rest} (expected $expect)"
        fi
    done < <(in_container "$service" scripts/probes/tcp.py "$@")
}
for org in o1 o2; do
    other=$([ "$org" = o1 ] && echo o2 || echo o1)
    for service in "$org-web" "$org-worker"; do
        check_tcp "$service" blocked core-db:5432 "$other-db:5432" ro-db:5432
        check_tcp "$service" open "$org-db:5432"
    done
    check_tcp "$org-web" blocked rabbitmq:5672
    check_tcp "$org-review-web" blocked core-db:5432 "$other-db:5432" ro-db:5432 rabbitmq:5672
    check_tcp "$org-review-web" open "$org-db:5432"
    check_tcp "$org-worker" blocked core-web:8000 "$other-web:8000" "$other-worker:8000" ro-web:8000
done
check_tcp core-web blocked o1-db:5432 o2-db:5432 ro-db:5432 rabbitmq:5672
check_tcp core-worker blocked o1-db:5432 o2-db:5432 ro-db:5432
check_tcp core-orcid blocked o1-db:5432 o2-db:5432 ro-db:5432 rabbitmq:5672
check_tcp core-orcid open core-db:5432
for service in ro-web ro-worker; do
    check_tcp "$service" blocked core-db:5432 o1-db:5432 o2-db:5432
    check_tcp "$service" open ro-db:5432
done
check_tcp ro-web blocked rabbitmq:5672
check_tcp ro-worker blocked core-web:8000 o1-web:8000 o2-web:8000

section "2. Credentials"
secrets_of() {  # zone files... -> one secret value per line
    for file in "$@"; do
        grep -E '^(DJANGO_SECRET_KEY|POSTGRES_PASSWORD|RABBITMQ_PASSWORD|RABBITMQ_ADMIN_PASSWORD)=' \
            "env/$file.env" | cut -d= -f2-
    done
}
check_no_secrets() {  # service label files...
    local service=$1 label=$2 found=0
    shift 2
    local env
    env=$(container_env "$service")
    while read -r secret; do
        [ -n "$secret" ] && grep -qF -- "$secret" <<<"$env" && found=1
    done < <(secrets_of "$@")
    if [ "$found" = 0 ]; then ok "$service holds no $label"; else bad "$service holds $label"; fi
}
for org in o1 o2; do
    other=$([ "$org" = o1 ] && echo o2 || echo o1)
    for service in "$org-web" "$org-review-web" "$org-worker" "$org-db"; do
        check_no_secrets "$service" "core, $other or RO credentials" core core-mq "$other" "$other-mq" ro ro-mq rabbitmq
    done
    check_no_secrets "$org-web" "broker credentials" "$org-mq"
    check_no_secrets "$org-review-web" "broker credentials" "$org-mq"
    check_no_secrets "$org-db" "broker credentials" "$org-mq"
done
for service in core-web core-worker core-orcid core-db; do
    check_no_secrets "$service" "org or RO credentials" o1 o2 o1-mq o2-mq ro ro-mq rabbitmq
done
check_no_secrets core-web "broker credentials" core-mq
check_no_secrets core-orcid "broker credentials" core-mq
for service in ro-web ro-worker ro-db; do
    check_no_secrets "$service" "core or org credentials" core core-mq o1 o2 o1-mq o2-mq rabbitmq
done
check_no_secrets ro-web "broker credentials" ro-mq
check_no_secrets ro-db "broker credentials" ro-mq
for zone in core o1 o2 o1-review o2-review ro; do
    mounts=$(docker inspect --format '{{range .Mounts}}{{.Source}} {{end}}' "$(dc ps -q "$zone-web")")
    others=$(tr ' ' '\n' <<<"$mounts" | grep -E 'secrets/saml/' | grep -vE "secrets/saml/($zone|idp/metadata.xml)$" || true)
    if [ -z "$others" ]; then ok "$zone-web mounts only its own SAML key"; else bad "$zone-web mounts $others"; fi
done

section "3. RabbitMQ permissions"
for org in o1 o2 o3; do
    while read -r name result; do
        case "$name" in
            *) if [[ "$result" == 403\ ACCESS_REFUSED* ]]; then
                   ok "$org: $name refused ($result)"
               else
                   bad "$org: $name -> $result (expected 403 ACCESS_REFUSED)"
               fi ;;
        esac
    done < <(in_container "$org-worker" scripts/probes/rabbit_acl.py)
done
while read -r name result; do
    if [[ "$result" == 403\ ACCESS_REFUSED* ]]; then
        ok "ro: $name refused ($result)"
    else
        bad "ro: $name -> $result (expected 403 ACCESS_REFUSED)"
    fi
done < <(in_container ro-worker scripts/probes/rabbit_acl_ro.py)

section "4. Forged event from Org 1 about an Org 2 application"
target=$(django_shell core-web "
from it42.core.applications.models import ApplicationCopy
a = ApplicationCopy.objects.filter(user__sso_subject='a2', org_slug='o2').first()
print(f'{a.public_id} {a.status} {a.last_seq}' if a else '')")
if [ -z "$target" ]; then
    skp "a2 has no Org 2 application yet (run scripts/acceptance.py first)"
else
    read -r app_id status_before seq_before <<<"$target"
    event_id=$(python3 -c 'import uuid; print(uuid.uuid4())')
    envelope=$(python3 - "$event_id" "$app_id" <<'PY'
import json, sys
from datetime import datetime, timezone
event_id, app_id = sys.argv[1:]
print(json.dumps({
    "id": event_id, "type": "application.status_changed", "version": 1,
    "occurred_at": datetime.now(timezone.utc).isoformat(),
    "application_id": app_id, "grant_id": None, "seq": 999,
    "payload": {"application_id": app_id, "status": "approved", "seq": 999},
}))
PY
)
    published=$(dc exec -T o1-worker python -c "$(cat scripts/probes/forge.py)" o1-to-core <<<"$envelope")
    [ "$published" = "$event_id" ] && ok "o1 published forged event $event_id on o1-to-core" \
        || bad "could not publish the forged event: $published"
    sleep 4
    admin_user=$(env_value rabbitmq RABBITMQ_ADMIN_USER)
    admin_pass=$(env_value rabbitmq RABBITMQ_ADMIN_PASSWORD)
    dlq=$(curl -sS --resolve "mq.$IT42_DOMAIN:443:127.0.0.1" -u "$admin_user:$admin_pass" \
        -H 'content-type: application/json' \
        -d '{"count": 1000, "ackmode": "ack_requeue_true", "encoding": "auto"}' \
        "https://mq.$IT42_DOMAIN/api/queues/%2Fit42/o1-to-core.dlq/get")
    if grep -q "\"message_id\":\"$event_id\"" <<<"$dlq"; then
        ok "the forged event is in o1-to-core.dlq"
    else
        bad "the forged event is not in o1-to-core.dlq"
    fi
    after=$(django_shell core-web "
from it42.core.applications.models import ApplicationCopy
a = ApplicationCopy.objects.get(public_id='$app_id')
print(f'{a.status} {a.last_seq}')")
    if [ "$after" = "$status_before $seq_before" ]; then
        ok "a2's g2 application is unchanged ($after)"
    else
        bad "a2's g2 application changed: '$status_before $seq_before' -> '$after'"
    fi
    if dc logs core-worker --since 1m 2>&1 | grep -q "rejecting message $event_id"; then
        ok "core-worker logged the rejection"
    else
        bad "no rejection logged for $event_id"
    fi
fi

section "5. Review notes stay in the org databases"
notes=""
for org in o1 o2; do
    notes+=$(dc exec -T "$org-db" psql -U "$org" -d "$org" -At -c \
        "select replace(text, E'\n', ' ') from org_applications_reviewnote" 2>/dev/null)$'\n'
done
if [ -z "${notes//[[:space:]]/}" ]; then
    skp "no review notes exist yet (run scripts/acceptance.py first)"
else
    dump=$(dc exec -T core-db pg_dump -U core core)
    count=0 leaked=0
    while IFS= read -r note; do
        [ -z "$note" ] && continue
        count=$((count + 1))
        grep -qF -- "$note" <<<"$dump" && leaked=$((leaked + 1))
    done <<<"$notes"
    if [ "$leaked" = 0 ]; then
        ok "none of $count review note(s) appear in a dump of the core database"
    else
        bad "$leaked of $count review note(s) found in the core database"
    fi
fi

section "6. Signatures reach only the asking org"
target=$(django_shell o1-web "
from it42.org.applications.models import Application
a = Application.objects.exclude(research_org='').exclude(signed_by='').order_by('-signed_at').first()
print(f'{a.public_id} {a.status} {a.seq}' if a else '')")
if [ -z "$target" ]; then
    skp "Org 1 has no signed application yet (run scripts/acceptance.py first)"
else
    read -r app_id status_before seq_before <<<"$target"
    event_id=$(python3 -c 'import uuid; print(uuid.uuid4())')
    envelope=$(python3 - "$event_id" "$app_id" <<'PY'
import json, sys
from datetime import datetime, timezone
event_id, app_id = sys.argv[1:]
print(json.dumps({
    "id": event_id, "type": "signature.granted", "version": 1,
    "occurred_at": datetime.now(timezone.utc).isoformat(),
    "application_id": app_id, "grant_id": None, "seq": None,
    "payload": {"application_id": app_id, "signer": {"name": "Forger"}, "method": "click"},
}))
PY
)
    published=$(dc exec -T ro-worker python -c "$(cat scripts/probes/forge.py)" ro-to-o2 <<<"$envelope")
    [ "$published" = "$event_id" ] && ok "ro published a signature for an Org 1 application on ro-to-o2" \
        || bad "could not publish the forged signature: $published"
    sleep 4
    admin_user=$(env_value rabbitmq RABBITMQ_ADMIN_USER)
    admin_pass=$(env_value rabbitmq RABBITMQ_ADMIN_PASSWORD)
    dlq=$(curl -sS --resolve "mq.$IT42_DOMAIN:443:127.0.0.1" -u "$admin_user:$admin_pass" \
        -H 'content-type: application/json' \
        -d '{"count": 1000, "ackmode": "ack_requeue_true", "encoding": "auto"}' \
        "https://mq.$IT42_DOMAIN/api/queues/%2Fit42/ro-to-o2.dlq/get")
    if grep -q "\"message_id\":\"$event_id\"" <<<"$dlq"; then
        ok "the forged signature is in ro-to-o2.dlq"
    else
        bad "the forged signature is not in ro-to-o2.dlq"
    fi
    after=$(django_shell o1-web "
from it42.org.applications.models import Application
a = Application.objects.get(public_id='$app_id')
print(f'{a.status} {a.seq}')")
    if [ "$after" = "$status_before $seq_before" ]; then
        ok "the Org 1 application is unchanged ($after)"
    else
        bad "the Org 1 application changed: '$status_before $seq_before' -> '$after'"
    fi
    comments=$(dc exec -T ro-db psql -U ro -d ro -At -c \
        "select replace(comment, E'\n', ' ') from ro_signing_signaturerequest where status = 'signed' and comment <> ''" 2>/dev/null)
    if [ -z "${comments//[[:space:]]/}" ]; then
        skp "no signer comments exist yet"
    else
        # Core relays the RO event to the funding organisation through its transactional
        # outbox. The comment is expected there until delivery, but must not be copied to
        # applicant-domain tables. Exclude only outbox row data from this isolation check.
        dump=$(dc exec -T core-db pg_dump -U core \
            --exclude-table-data=public.common_outboxevent core)
        leaked=0
        while IFS= read -r comment; do
            [ -n "$comment" ] && grep -qF -- "$comment" <<<"$dump" && leaked=$((leaked + 1))
        done <<<"$comments"
        if [ "$leaked" = 0 ]; then
            ok "no signer comment appears in core applicant-domain data"
        else
            bad "$leaked signer comment(s) found in core applicant-domain data"
        fi
    fi
fi

printf '\n%d passed, %d failed, %d skipped\n' "$pass" "$fail" "$skip"
[ "$fail" = 0 ]
