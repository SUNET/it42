#!/bin/bash
# Run the outbox relay and the event consumer side by side; org workers also run the
# signature expiry job (requests past their grant's signature deadline). If any of them
# exits, stop the others and exit non-zero so Docker restarts the container.
set -u

python manage.py relay_outbox &
pids="$!"
python manage.py consume_events &
pids="$pids $!"
if [ "${APP_ROLE:-}" = org ]; then
    python manage.py expire_signatures --every 60 &
    pids="$pids $!"
fi

# shellcheck disable=SC2086  # word splitting of the pid list is intended
trap 'kill -TERM $pids 2>/dev/null' TERM INT
# shellcheck disable=SC2086
wait -n $pids
status=$?
# shellcheck disable=SC2086
kill -TERM $pids 2>/dev/null
wait
exit "$status"
