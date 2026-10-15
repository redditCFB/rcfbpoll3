# Application-only production upgrade on PostgreSQL 17

`docker-compose.staging.yml` is the live deployment despite its name. This
procedure keeps its `postgres:17.0-alpine` service, `postgres_data17` volume,
`/var/lib/postgresql/data/` mount, credentials, and Compose project name. Use
an off-host build and a VM snapshot that includes the existing database volume.
Do not run this procedure against `docker-compose.prod.yml`: that unused file
still defines PostgreSQL 13, which Django 6.1 does not support.

The operator needs the reviewed revision, a host with Docker and enough space
to build and export the image, SSH access to the VM, permission to snapshot the
VM and every disk containing Docker volumes, and a maintenance window. Record
the existing project name from `docker compose ls`; the examples use
`rcfbpoll3`. Run Compose commands from the deployment checkout. Keep the same
project name throughout so Compose uses the existing volumes.

## Build and deliver the exact image

On the build host, from the reviewed commit, build and validate the production
image. Use the commit SHA as its immutable deployment tag. The image is shared
by the `poll` and `migrate` services.

```sh
export POLL_REVISION="$(git rev-parse HEAD)"
export POLL_IMAGE="rcfbpoll:${POLL_REVISION}"
docker build -f app/Dockerfile.prod -t "$POLL_IMAGE" app
docker run --rm --entrypoint python "$POLL_IMAGE" -m pip check
docker image inspect --format '{{.Id}} {{.Size}}' "$POLL_IMAGE"
docker save "$POLL_IMAGE" -o "rcfbpoll-${POLL_REVISION}.tar"
sha256sum "rcfbpoll-${POLL_REVISION}.tar" > "rcfbpoll-${POLL_REVISION}.tar.sha256"
```

Record the image ID and tar SHA-256 in the deployment record. Transfer the
matching checkout (including this Compose file) to the VM before the window;
verify its `git rev-parse HEAD` equals `POLL_REVISION`. Use a private staging
directory on a disk included in capacity calculations.

On the VM, create `/private/staging` with operator-only access. In the
reviewed checkout, set the same revision and image tag as the build host.
Inspect free space before transfer and again before loading:

```sh
export POLL_REVISION="$(git rev-parse HEAD)"
export POLL_IMAGE="rcfbpoll:${POLL_REVISION}"
export POLL_PROJECT=rcfbpoll3
install -d -m 700 /private/staging
```

```sh
POLL_DOCKER_ROOT="$(docker info --format '{{.DockerRootDir}}')"
POLL_DB_MOUNT="$(docker volume inspect --format '{{.Mountpoint}}' "${POLL_PROJECT}_postgres_data17")"
df -h /private/staging "$POLL_DOCKER_ROOT" "$POLL_DB_MOUNT"
docker system df
du -sh "$POLL_DB_MOUNT"
```

The VM needs room for the complete tar **plus** the loaded image's uncompressed
layers while both exist, the old image for rollback until the snapshot is
proven, Docker's temporary load overhead, database growth during migrations,
and normal PostgreSQL free space. The validation build produced a 308,745,728
byte tar and a 291,092,562 byte image, so roughly 600 MB of additional space
was needed while both coexisted, before Docker load overhead or database
growth. Recalculate these values for the final artifact. `docker image inspect`
reports the image's uncompressed size; compare that with actual free space
on the Docker data disk and the tar's size on its staging disk. If these do not fit with operational
headroom, add disk capacity before the window. Do not prune Docker volumes or
remove the active/rollback images to make space. After checksum and image ID
verification, the transferred tar may be deleted; this frees only its staging
space. Recheck `df -h` after loading.

After confirming capacity, transfer the archive from the build host:

```sh
scp "rcfbpoll-${POLL_REVISION}.tar" "rcfbpoll-${POLL_REVISION}.tar.sha256" VM:/private/staging/
```

On the VM, check space again, verify the tar, and load the image:

```sh
df -h /private/staging "$POLL_DOCKER_ROOT" "$POLL_DB_MOUNT"
cd /private/staging
sha256sum -c "rcfbpoll-${POLL_REVISION}.tar.sha256"
docker load -i "rcfbpoll-${POLL_REVISION}.tar"
test "$(docker image inspect --format '{{.Id}}' "$POLL_IMAGE")" = 'IMAGE_ID_RECORDED_ON_BUILD_HOST'
```

This verifies the transferred archive and the loaded image identity. Set
`POLL_IMAGE` in the operator shell for every Compose invocation below. The
staging Compose file names this image for both application services. `up` uses
`--no-build` and `--pull never`; `run` uses the already loaded image with
`--pull never`. Verify the image exists before every deployment command. Keep
the source tar on the build host.

## Freeze, snapshot, and deploy

1. Put the public site into maintenance mode **upstream of the app**, blocking
   all public writes. Stop scheduled jobs and any other writers or workers,
   including Reddit automation. Record the list of stopped jobs and how to
   restart them. Keep maintenance mode active through all smoke tests. Stop the
   old app and migration service, then verify no application process can write.
   Keep the database running until the writers are stopped.

   ```sh
   export POLL_REVISION="$(git rev-parse HEAD)"
   export POLL_PROJECT=rcfbpoll3
   export POLL_COMPOSE=docker-compose.staging.yml
   export POLL_IMAGE="rcfbpoll:${POLL_REVISION}"
   docker image inspect "$POLL_IMAGE"
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" config --images
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" stop poll migrate
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" ps
   ```

2. Confirm the `db` container is the existing PostgreSQL 17 container and its
   mounted volume is the existing `postgres_data17` volume. Record the volume
   mountpoint from `docker volume inspect`. Confirm the VM snapshot includes
   **the disk containing that mountpoint**, the Docker metadata, and the
   application checkout/configuration; snapshots of only the boot disk are
   insufficient when Docker data lives elsewhere. Stop PostgreSQL cleanly,
   confirm it has exited, take the VM snapshot, and record its ID. If the
   snapshot fails, do not proceed. Start the same database container and check
   readiness before migrations.

   ```sh
   docker volume inspect "${POLL_PROJECT}_postgres_data17"
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" ps db
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" stop db
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" ps db
   # Take and verify the VM snapshot here, including the database volume disk.
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" start db
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" exec -T db sh -c \
     'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
   ```

3. In the reviewed checkout, verify that Compose resolves **both** `poll` and
   `migrate` to the loaded `POLL_IMAGE` and still resolves `db` to PostgreSQL
   17 with `postgres_data17`. Run migrations, checks, and static collection as
   explicit one-shot commands. `--no-deps` prevents Compose from starting the
   normal `migrate` service command, which also screens provisional applicants.

   ```sh
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" config # Inspect privately: includes environment values.
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" run --rm --no-deps --pull never \
     --entrypoint python migrate manage.py migrate --noinput
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" run --rm --no-deps --pull never \
     --entrypoint python migrate manage.py migrate --check
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" run --rm --no-deps --pull never \
     --entrypoint python migrate manage.py check
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" run --rm --no-deps --pull never \
     --entrypoint python migrate manage.py update_team_logo_handles --dry-run
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" run --rm --no-deps --pull never \
     --entrypoint python migrate manage.py update_team_logo_handles
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" run --rm --no-deps --pull never \
     --entrypoint python migrate manage.py collectstatic --noinput
   ```

   Migrations and logo updates modify the existing database and can have
   application side effects; review their output before proceeding. The normal
   `migrate` service additionally runs `screen_open_provisional_applications`,
   which can accept users and send Reddit messages. Inspect the open applicant
   count and automation credentials before deliberately running that command
   after core smoke tests. Keep scheduled jobs stopped until then. Future
   ordinary `docker compose up` calls can invoke the full `migrate` service;
   operators should account for this behavior.

4. Start only the app, bypassing automatic service dependencies, then restore
   the public proxy as appropriate for the site's maintenance mode. Keep the
   upstream write block active. Confirm the running `poll` container image ID
   equals the recorded build-host ID, and inspect app/database/proxy logs.

   ```sh
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" up -d --no-deps --no-build --pull never poll
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" ps poll db
   test "$(docker inspect --format '{{.Image}}' "$(docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" ps -q poll)")" = 'IMAGE_ID_RECORDED_ON_BUILD_HOST'
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" logs --tail=100 poll db
   ```

5. Through operator-only access that bypasses the public write block, verify
   login **and logout**, Reddit OAuth sign-in and callback, existing ballot
   viewing, a new/updated ballot submission and persisted readback, admin
   access and provisional-voter management, and public results pages. Confirm
   static files load and inspect logs for errors. Check the ballot write is
   confined to a test account/poll and clean it up through the application if
   appropriate. Explicitly review the effect of any migration or startup
   command that could interact with Reddit. When ready, deliberately run:

   ```sh
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" run --rm --no-deps --pull never \
     --entrypoint python migrate manage.py screen_open_provisional_applications
   ```

   Verify its accepted/error/notification counts and any Reddit messages.
   Repeat relevant admin and public checks. Reopen public writes and scheduled
   activity only after every check passes and the operator accepts the logs.

## Rollback and cleanup

If a check fails, leave public writes blocked and scheduled jobs stopped.
Restore the **pre-deployment VM snapshot, including the disk with
`postgres_data17`**, then verify the old checkout, image, PostgreSQL 17
container, volume, and application are back. Smoke-test the restored site
before reopening writes. The snapshot restores database and application state
together; writes made during private smoke tests will be lost. If external
Reddit messages were sent after the snapshot, they cannot be rolled back;
reconcile them manually before resuming automation.

Never run `docker compose down -v` during deployment or rollback. Do not
recreate or delete `postgres_data17`. After the upgraded site is accepted and
the rollback snapshot retention decision is made, delete only the verified
transferred `rcfbpoll-${POLL_REVISION}.tar` and its checksum from the VM's
private staging directory. Identify any other old image by exact ID and verify
that no running container or rollback plan needs it before deleting it. Do not
run `docker system prune`, `docker volume prune`, or broad cleanup commands.
