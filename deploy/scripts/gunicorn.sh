#!/usr/bin/env bash
set -Eeuo pipefail
workers="${GUNICORN_WORKERS:-2}"
threads="${GUNICORN_THREADS:-4}"
timeout="${GUNICORN_TIMEOUT:-120}"
max_requests="${GUNICORN_MAX_REQUESTS:-0}"
for value in "$workers" "$threads" "$timeout"; do
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || { echo 'Invalid positive Gunicorn setting' >&2; exit 1; }
done
[[ "$max_requests" =~ ^[0-9]+$ ]] || { echo 'Invalid GUNICORN_MAX_REQUESTS' >&2; exit 1; }
exec gunicorn --chdir=/home/frappe/frappe-bench/sites --bind=0.0.0.0:8000 \
  --threads="$threads" --workers="$workers" --worker-class=gthread --worker-tmp-dir=/dev/shm \
  --timeout="$timeout" --max-requests="$max_requests" --preload frappe.app:application "$@"
