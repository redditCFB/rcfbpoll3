#!/bin/sh
set -eu

if [ "${DATABASE:-}" = "postgres" ]; then
    python - <<'PY'
import os
import time

import psycopg

for attempt in range(60):
    try:
        with psycopg.connect(
            host=os.environ['SQL_HOST'],
            port=os.environ.get('SQL_PORT', '5432'),
            dbname=os.environ['SQL_DATABASE'],
            user=os.environ['SQL_USER'],
            password=os.environ['SQL_PASSWORD'],
            connect_timeout=2,
        ) as connection:
            connection.execute('SELECT 1')
        print('PostgreSQL is ready for queries.', flush=True)
        break
    except psycopg.OperationalError as error:
        if attempt == 59:
            raise SystemExit(f'PostgreSQL did not become ready: {error}')
        time.sleep(1)
PY
fi

exec "$@"
