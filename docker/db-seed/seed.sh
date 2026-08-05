#!/bin/sh

set -eu

: "${POSTGRES_HOST:?POSTGRES_HOST is required}"
: "${POSTGRES_PORT:?POSTGRES_PORT is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${FIXTURE_URL:?FIXTURE_URL is required}"
: "${FIXTURE_SHA256:?FIXTURE_SHA256 is required}"

export PGPASSWORD="$POSTGRES_PASSWORD"

psql_args="-h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DB"

# A volume with Django's migration table already contains a usable local
# database. Never replace it implicitly; use `docker compose down -v` to seed
# a fresh copy deliberately.
if psql $psql_args -tAc "SELECT to_regclass('public.django_migrations') IS NOT NULL" | grep -qx "t"; then
    echo "Existing local database detected; skipping fixture restore."
    exit 0
fi

archive="$(mktemp)"
trap 'rm -f "$archive"' EXIT

echo "Downloading local poll fixture..."
curl --fail --location --retry 3 --retry-delay 1 --output "$archive" "$FIXTURE_URL"

printf '%s  %s\n' "$FIXTURE_SHA256" "$archive" | sha256sum -c -s -
echo "Fixture checksum verified."

pg_restore \
    --exit-on-error \
    --no-owner \
    --no-privileges \
    -h "$POSTGRES_HOST" \
    -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    "$archive"

echo "Local poll fixture restored."
