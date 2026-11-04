#!/bin/sh
set -eu

case "${1:-web}" in
web)
    python manage.py migrate --noinput
    python manage.py createcachetable
    exec gunicorn it42.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers "${GUNICORN_WORKERS:-3}" \
        --forwarded-allow-ips '*' \
        --no-control-socket \
        --access-logfile - \
        --error-logfile -
    ;;
worker)
    exec /usr/local/bin/worker.sh
    ;;
*)
    exec "$@"
    ;;
esac
