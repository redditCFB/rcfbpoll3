# PostgreSQL 18 production cutover

`docker-compose.staging.yml` currently runs the live site. Its existing
`postgres_data17` volume must remain untouched. Both deployment Compose files
now mount a **new** `postgres_data18` volume at `/var/lib/postgresql`, the
PostgreSQL 18 image's volume root. The legacy `docker-compose.prod.yml` path
also keeps its old `postgres_data` volume. Neither old volume is an in-place
upgrade target.

The person running this procedure needs the old and proposed deployment
checkouts, access to the existing Compose project, enough private durable disk
space for a fresh dump, and a maintenance window. Replace the project name
below with the value shown by `docker compose ls` for the current deployment.
Keep the same name throughout
the cutover so Compose finds the existing volumes. Run commands from the
repository root. Restrict the backup directory to operators; it contains live
credentials and user data. Do not put dumps or snapshots in Git.

```sh
export POLL_PROJECT=rcfbpoll3
export POLL_COMPOSE=docker-compose.staging.yml
export POLL_BACKUP_DIR=/path/to/private-durable-backup/rcfbpoll-pg18-2026-09-28
install -d -m 700 "$POLL_BACKUP_DIR"
cp /path/to/proposed-checkout/docs/postgres18-snapshot.sql "$POLL_BACKUP_DIR/snapshot.sql"
```

## Rehearse with a fresh copy of production data

Before scheduling the live cutover, briefly freeze all writers and take a
current PG17 dump and source snapshot from the running deployment using the
**old** checkout and existing Compose file. Resume writes after both are
captured. An earlier sanitized local fixture does not establish compatibility
with production data. This rehearsal dump does not replace the fresh
post-freeze dump required below. Transfer it securely if rehearsal runs on a
different host.

```sh
docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" exec -T db sh -c \
  'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "$POLL_BACKUP_DIR/rehearsal.dump"
docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" exec -T db sh -c \
  'psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "$POLL_BACKUP_DIR/snapshot.sql" > "$POLL_BACKUP_DIR/rehearsal-source.csv"
pg_restore -l "$POLL_BACKUP_DIR/rehearsal.dump" > /dev/null
sha256sum "$POLL_BACKUP_DIR/rehearsal.dump" > "$POLL_BACKUP_DIR/rehearsal.sha256"
```

With the proposed checkout, use a separate Compose project so the rehearsal
has its own PG18 and static volumes. Restore the dump, compare its migration
set and core table counts with the source, and run *only* Django migrations.
The normal `migrate` service also runs application commands that can contact
Reddit, so do not run that service on a production-data rehearsal.

```sh
export POLL_REHEARSAL_PROJECT="${POLL_PROJECT}-pg18-rehearsal"
docker compose -p "$POLL_REHEARSAL_PROJECT" -f "$POLL_COMPOSE" build migrate
docker compose -p "$POLL_REHEARSAL_PROJECT" -f "$POLL_COMPOSE" up -d db
docker compose -p "$POLL_REHEARSAL_PROJECT" -f "$POLL_COMPOSE" exec -T db sh -c \
  'pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "$POLL_BACKUP_DIR/rehearsal.dump"
docker compose -p "$POLL_REHEARSAL_PROJECT" -f "$POLL_COMPOSE" exec -T db sh -c \
  'psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "$POLL_BACKUP_DIR/snapshot.sql" > "$POLL_BACKUP_DIR/rehearsal-restored.csv"
diff -u "$POLL_BACKUP_DIR/rehearsal-source.csv" "$POLL_BACKUP_DIR/rehearsal-restored.csv"
docker compose -p "$POLL_REHEARSAL_PROJECT" -f "$POLL_COMPOSE" run --rm --no-deps \
  --entrypoint python migrate manage.py migrate --noinput
docker compose -p "$POLL_REHEARSAL_PROJECT" -f "$POLL_COMPOSE" run --rm --no-deps \
  --entrypoint python migrate manage.py migrate --check
```

Investigate every snapshot mismatch, failed restore, or migration error before
proceeding. Record the rehearsal date,
source PostgreSQL version, row counts, migration output, and application image
revision in the deployment record. No production-data rehearsal has been
performed by this PR's local validation.

Before the live window, build the proposed `poll` and `migrate` images and
verify the full application test suite against the final revision. Keep those
images available for the cutover.

## Live cutover

1. Announce a maintenance window and stop all application writers, scheduled
   jobs, and inbound write traffic. Confirm the old application stays stopped
   until the new deployment is ready. Keep the PG17 `db` service running for
   the dump. Take the **fresh** dump and source snapshot from the old checkout:

   ```sh
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" exec -T db sh -c \
     'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' \
     > "$POLL_BACKUP_DIR/pg17-final.dump"
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" exec -T db sh -c \
     'psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
     < "$POLL_BACKUP_DIR/snapshot.sql" > "$POLL_BACKUP_DIR/source.csv"
   pg_restore -l "$POLL_BACKUP_DIR/pg17-final.dump" > /dev/null
   sha256sum "$POLL_BACKUP_DIR/pg17-final.dump" > "$POLL_BACKUP_DIR/pg17-final.sha256"
   ```

2. Deploy the reviewed application revision. Stop the old PG17 container
   **without** `down -v`, then start only the PG18 database service. Verify
   `docker compose ... ps db` shows the new image and that `pg_isready` passes.

   ```sh
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" stop db
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" up -d db
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" exec -T db sh -c \
     'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
   ```

3. Restore to the new, empty `postgres_data18` volume. Never restore onto a
   database that already contains the application schema. Compare the exact
   migration list and core row counts *before* running migrations:

   ```sh
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" exec -T db sh -c \
     'pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
     < "$POLL_BACKUP_DIR/pg17-final.dump"
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" exec -T db sh -c \
     'psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
     < "$POLL_BACKUP_DIR/snapshot.sql" > "$POLL_BACKUP_DIR/restored.csv"
   diff -u "$POLL_BACKUP_DIR/source.csv" "$POLL_BACKUP_DIR/restored.csv"
   ```

4. Run the deployment's migration service and check its exit status. It also
   updates logo handles, screens open provisional applications, and collects
   static files. Verify no migrations remain, then bring up the application:

   ```sh
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" up -d migrate
   POLL_MIGRATE_ID="$(docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" ps -a -q migrate)"
   test -n "$POLL_MIGRATE_ID"
   while [ "$(docker inspect -f '{{.State.Running}}' "$POLL_MIGRATE_ID")" = true ]; do sleep 2; done
   test "$(docker inspect -f '{{.State.ExitCode}}' "$POLL_MIGRATE_ID")" -eq 0
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" run --rm --no-deps \
     --entrypoint python migrate manage.py migrate --check
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" up -d poll nginx-proxy nginx-proxy-letsencrypt
   ```

5. Before reopening writes, smoke-test a normal login and logout, Reddit
   OAuth callback, existing ballots and a ballot write, administrator access,
   and normal public reads. Check application, migration, proxy, and database
   logs. Confirm the new writes persist and important row counts remain
   plausible. Record who performed each check. Reopen traffic only after all
   checks pass.

Retain `pg17-final.dump`, its checksum, the pre-cutover snapshot, and the old
PG17 volume until the new deployment is proven healthy and backups have been
verified. Do not run `docker compose down -v` or remove the old volume during
this period. If cutover fails before new writes begin, stop the new application,
restore the old checkout and old Compose definition, and start the old PG17
database and application against the preserved old volume. If new writes have
occurred, reconcile them before reverting traffic.

The unused `docker-compose.prod.yml` path follows the same dump, new-volume,
restore, snapshot, and smoke-test procedure, but its old database image is
PostgreSQL 13 and its preserved volume is `postgres_data`. Use a dump made
with that running source server rather than assuming it is PG17. It has no
`migrate` service. After comparing snapshots, run these commands before
starting `poll` and `nginx`:

```sh
docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" run --rm --no-deps poll python manage.py migrate --noinput
docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" run --rm --no-deps poll python manage.py collectstatic --noinput
docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" run --rm --no-deps poll python manage.py migrate --check
```
