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
the existing project name from `docker compose ls` and the live checkout path;
the examples use `rcfbpoll3`. If the live project name differs, substitute it
for `rcfbpoll3` throughout. Keep the live checkout and its configuration
untouched. Stage the reviewed checkout in a separate directory and pass the
same explicit project name to every Compose command. Compose prefixes named
volumes with that project name, not the checkout directory.

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
matching checkout (including this Compose file) to a new directory on the VM
before the window, for example
`/private/staging/rcfbpoll3-${POLL_REVISION}`. Do not transfer over the live
checkout. First create `/private/staging` on the VM with mode `700`, owned by
the deployment operator. Preserve the staged checkout's Git metadata so its
commit can be checked. Use a private staging directory on a disk included in
capacity calculations.

Before transferring the checkout or image, create the staging directory on the
VM:

```sh
install -d -m 700 /private/staging
```

On the VM, start in the existing live checkout. Set `POLL_NEW_DIR` to the
separate reviewed checkout that was transferred above. Copy the live Compose
environment files into that staged checkout with their original permissions;
keep the source files in the live checkout unchanged. Set `POLL_REVISION` to
the recorded build revision and verify the staged checkout matches it. Inspect
free space before transferring the image tar and again before loading it:

```sh
export POLL_OLD_DIR="$(pwd -P)"
export POLL_OLD_REVISION="$(git -C "$POLL_OLD_DIR" rev-parse HEAD)"
docker compose ls
git -C "$POLL_OLD_DIR" status --short
sha256sum \
  "$POLL_OLD_DIR/.env.staging" "$POLL_OLD_DIR/.env.staging.db" \
  "$POLL_OLD_DIR/.env.staging.proxy-companion"
export POLL_NEW_DIR="/private/staging/rcfbpoll3-REVIEWED_SHA"
export POLL_REVISION=REVIEWED_SHA
test "$(git -C "$POLL_NEW_DIR" rev-parse HEAD)" = "$POLL_REVISION"
export POLL_IMAGE="rcfbpoll:${POLL_REVISION}"
export POLL_PROJECT=rcfbpoll3
export POLL_OLD_COMPOSE="$POLL_OLD_DIR/docker-compose.staging.yml"
export POLL_NEW_COMPOSE="$POLL_NEW_DIR/docker-compose.staging.yml"
export POLL_COMPOSE="$POLL_OLD_COMPOSE"
cp -p "$POLL_OLD_DIR/.env.staging" "$POLL_NEW_DIR/.env.staging"
cp -p "$POLL_OLD_DIR/.env.staging.db" "$POLL_NEW_DIR/.env.staging.db"
cp -p "$POLL_OLD_DIR/.env.staging.proxy-companion" "$POLL_NEW_DIR/.env.staging.proxy-companion"
test "$POLL_OLD_DIR" != "$POLL_NEW_DIR"
```

Check that both Compose files declare the same named volumes and that the
existing project volumes are present. These commands only render Compose
configuration and inspect volumes; they do not create or switch containers.

```sh
docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" config --volumes
docker compose -p "$POLL_PROJECT" -f "$POLL_NEW_COMPOSE" config --volumes
docker volume inspect --format '{{.Name}} {{.Mountpoint}}' \
  "${POLL_PROJECT}_postgres_data17" "${POLL_PROJECT}_static_volume"
```

Both files must list `postgres_data17` and `static_volume`. With
`POLL_PROJECT=rcfbpoll3`, the corresponding Docker volumes are
`rcfbpoll3_postgres_data17` and `rcfbpoll3_static_volume`. Stop if either
inspection fails or the names do not match the volumes used by the live
containers.

```sh
POLL_DOCKER_ROOT="$(docker info --format '{{.DockerRootDir}}')"
POLL_DB_MOUNT="$(docker volume inspect --format '{{.Mountpoint}}' "${POLL_PROJECT}_postgres_data17")"
POLL_STATIC_MOUNT="$(docker volume inspect --format '{{.Mountpoint}}' "${POLL_PROJECT}_static_volume")"
POLL_VHOST_MOUNT="$(docker volume inspect --format '{{.Mountpoint}}' "${POLL_PROJECT}_vhost")"
df -h /private/staging "$POLL_DOCKER_ROOT" "$POLL_DB_MOUNT" "$POLL_STATIC_MOUNT" "$POLL_VHOST_MOUNT" "$POLL_OLD_DIR"
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
on the Docker data disk and the tar's size on its staging disk. If these do not
fit with operational headroom, add disk capacity before the window. Do not
prune Docker volumes or remove the active/rollback images to make space. After
checksum and image ID verification, the transferred tar may be deleted; this
frees only its staging space. Recheck `df -h` after loading.

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

### Enable operator-only maintenance access

The live Compose file binds `nginx-proxy` to VM ports 80 and 443; `poll` only
exposes port 8000 inside Docker. `nginx/Dockerfile` uses `jwilder/nginx-proxy`
0.9, and its per-host file `/etc/nginx/vhost.d/<VIRTUAL_HOST>` is included in
the HTTPS server block at server scope. The existing `vhost.d/default` file
contains the static-file location. The procedure below saves the current
per-host file, or copies `default` when no per-host file exists, then adds a
server-level source-IP allowlist followed by `deny all`. Nginx allows these
directives at server scope and inherits them into locations unless a location
defines its own access rules; the generated app and static locations do not.
This restricts app, admin, ballot, OAuth callback, and static-file URLs while
preserving the existing TLS certificate and hostname. HTTP continues to
redirect to HTTPS; the HTTP endpoint does not proxy requests to the application.
The per-host include is visible in the [nginx-proxy 0.9 template](https://github.com/nginx-proxy/nginx-proxy/blob/0.9.3/nginx.tmpl), and the inheritance behavior is documented by [Nginx](https://nginx.org/en/docs/http/ngx_http_access_module.html).

Use the app's configured hostname, currently
`poll-staging.redditcfb.com`, and the VM's public origin IPv4 address. Set
`OPERATOR_CIDR` to the operator workstation's public egress address as seen
when it connects directly to the VM, with `/32` for one IPv4 address. Since
the Compose proxy publishes 443 on the VM, this works without Cloudflare
access. If public DNS is proxied through Cloudflare or another CDN, temporarily
map the hostname to the VM origin on the operator workstation so Nginx sees
the operator's address instead of a shared CDN address. Use the HTTPS hostname
for all browser tests; do not browse to the IP. That preserves the certificate,
secure cookies, and the registered Reddit OAuth redirect URI.

On the operator workstation, set the hostname and origin address to the same
values used on the VM. Determine the workstation's public IPv4 egress address
there and use it with `/32` for `OPERATOR_CIDR` on the VM. If the workstation
uses a VPN or proxy, make sure its direct route to the VM uses this same source
address. This is an IP allowlist: any other device sharing that same public
egress address can also reach the site during maintenance.

```sh
export POLL_HOST=poll-staging.redditcfb.com
export VM_ORIGIN_IPV4=VM_PUBLIC_IPV4
export OPERATOR_CIDR="$(curl -4fsS https://api.ipify.org)/32"
printf '%s %s\n' "$VM_ORIGIN_IPV4" "$POLL_HOST" | sudo tee -a /etc/hosts
```

On Windows, add the same `VM_ORIGIN_IPV4 poll-staging.redditcfb.com` line to
`C:\Windows\System32\drivers\etc\hosts` as Administrator. Remove this
entry after the maintenance window. A command-line request that bypasses DNS
can use:

```sh
curl --resolve "${POLL_HOST}:443:${VM_ORIGIN_IPV4}" \
  --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  "https://${POLL_HOST}/"
```

The request from the allowlisted workstation must not return 403. The same
request from a non-allowlisted network must return 403.

These checks use the HTTPS hostname and connect directly to the VM origin.

Set the following on the VM, replacing the origin and operator placeholders:

```sh
export POLL_HOST=poll-staging.redditcfb.com
export VM_ORIGIN_IPV4=VM_PUBLIC_IPV4
export OPERATOR_CIDR=OPERATOR_PUBLIC_IPV4/32
```

Install the gate into the existing `nginx-proxy` container. The original file
and the allowlisted address are backed up in the existing `vhost` volume so
the same commands can remove the restriction exactly. The script validates
the hostname and address characters, tests the resulting Nginx configuration,
and reloads only after the test succeeds. If the test fails, it restores the
original file and exits; do not continue to the snapshot until the reload and
access checks succeed.

```sh
docker exec -i nginx-proxy sh -s -- "$POLL_HOST" "$OPERATOR_CIDR" <<'SH'
set -eu
host=$1
cidr=$2
dir=/etc/nginx/vhost.d
case "$host" in *[!A-Za-z0-9.-]*|'') echo "invalid host" >&2; exit 2;; esac
case "$cidr" in *[!0-9./:]*|'') echo "invalid CIDR" >&2; exit 2;; esac
file="$dir/$host"
backup="$dir/.${host}.maintenance-original"
absent="$dir/.${host}.maintenance-was-absent"
allowfile="$dir/.${host}.maintenance-allow"
test ! -e "$backup" && test ! -e "$absent" && test ! -e "$allowfile"
if [ -e "$file" ]; then
  cp -p "$file" "$backup"
else
  test -s "$dir/default"
  cp -p "$dir/default" "$backup"
  : > "$absent"
fi
printf '%s\n' "$cidr" > "$allowfile"
{
  cat "$backup"
  printf '\nallow %s;\ndeny all;\n' "$cidr"
} > "$file.tmp"
mv "$file.tmp" "$file"
if nginx -t; then
  nginx -s reload
else
  if [ -e "$absent" ]; then rm -f "$file" "$absent"; else cp -p "$backup" "$file"; fi
  rm -f "$backup" "$allowfile" "$file.tmp"
  exit 1
fi
SH
```

Confirm the gate is active before stopping writers: from the operator
workstation, request the direct origin over HTTPS and confirm it is not a
403; from a separate non-allowlisted network, the same request must return
403. Also confirm `docker exec nginx-proxy nginx -t` succeeds. If the direct
origin route, certificate hostname, or observed client address differs from
these assumptions, stop and correct the network/allowlist values before the
snapshot. Do not substitute the CDN's address in `OPERATOR_CIDR`; doing so
would allow other public users sharing that address.

### Freeze writers and snapshot the original state

1. Keep the traffic gate active. Record the stopped scheduled jobs and how to
   restart them, including Reddit automation and any non-Compose workers. From
   the **old** checkout, record and pin its running app image. Then stop the old
   `poll` and `migrate` services and verify they are stopped. Do not rely on
   stopping `poll` as the traffic gate; the upgraded app will be started while
   the Nginx restriction remains active.

   ```sh
   export POLL_OLD_CONTAINER_ID="$(docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" ps -a -q poll)"
   test -n "$POLL_OLD_CONTAINER_ID"
   export POLL_OLD_IMAGE_ID="$(docker inspect --format '{{.Image}}' "$POLL_OLD_CONTAINER_ID")"
   export POLL_OLD_IMAGE="rcfbpoll:preupgrade-${POLL_REVISION}"
   docker image tag "$POLL_OLD_IMAGE_ID" "$POLL_OLD_IMAGE"
   test "$(docker image inspect --format '{{.Id}}' "$POLL_OLD_IMAGE")" = "$POLL_OLD_IMAGE_ID"
   docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" config --images
   docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" stop --timeout 60 poll migrate
   docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" ps -a poll migrate
   ```

   Record `POLL_OLD_REVISION`, `POLL_OLD_IMAGE_ID`, and `POLL_OLD_IMAGE` in
   the deployment record, along with the `git status --short` output and the
   `.env.staging*` checksums printed during setup. Stop every other writer
   before proceeding.

2. Verify the running database is PostgreSQL 17 on the existing named volume.
   Record the mountpoints for Docker storage, PostgreSQL, static files, and the
   proxy's `vhost` volume. The snapshot must include the disk containing Docker
   metadata/images and **every disk containing these volume mountpoints**, plus
   the live checkout and its configuration. A boot-disk-only snapshot is not
   sufficient when Docker or the checkout is on another disk. Stop PostgreSQL
   cleanly, confirm it exited, take the VM snapshot, and record its ID. Do not
   proceed if the snapshot fails or omits any of those disks. The old checkout,
   environment files, Docker image, and containers remain intact at this point.

   ```sh
   export POLL_DB_CONTAINER="$(docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" ps -q db)"
   docker inspect --format '{{.Config.Image}} {{range .Mounts}}{{.Name}}:{{.Destination}} {{end}}' "$POLL_DB_CONTAINER"
   docker volume inspect \
     "${POLL_PROJECT}_postgres_data17" "${POLL_PROJECT}_static_volume" \
     "${POLL_PROJECT}_certs" "${POLL_PROJECT}_html" \
     "${POLL_PROJECT}_vhost" "${POLL_PROJECT}_acme"
   docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" ps db
   docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" stop --timeout 120 db
   docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" ps -a db
   test "$(docker inspect --format '{{.State.Status}} {{.State.ExitCode}}' "$POLL_DB_CONTAINER")" = 'exited 0'
   # Take and verify the VM snapshot here; record its ID and included disks.
   docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" start db
   docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" exec -T db sh -c \
     'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
   ```

3. **Only after the snapshot succeeds**, switch the operator shell to the new
   staged Compose file. The project name and logical volume names must match
   the old checkout. Compare the actual volume names and mountpoints before
   deployment; `-p "$POLL_PROJECT"` prevents the staged directory name from
   creating a new project namespace.

   ```sh
   export POLL_COMPOSE="$POLL_NEW_COMPOSE"
   test "$POLL_COMPOSE" != "$POLL_OLD_COMPOSE"
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" config --images
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" config --volumes
   umask 077
   export POLL_VOLUME_RECORD=/private/staging/volumes.before
   docker volume inspect --format '{{.Name}} {{.Mountpoint}}' \
     "${POLL_PROJECT}_postgres_data17" "${POLL_PROJECT}_static_volume" \
     "${POLL_PROJECT}_certs" "${POLL_PROJECT}_html" \
     "${POLL_PROJECT}_vhost" "${POLL_PROJECT}_acme" > "$POLL_VOLUME_RECORD"
   docker image inspect "$POLL_IMAGE"
   ```

   Confirm both `poll` and `migrate` resolve to `POLL_IMAGE`, `db` remains
   `postgres:17.0-alpine`, and both named volumes remain
   `postgres_data17`/`static_volume`. The `docker-compose.staging.yml` file
   names the same project-scoped volumes in both checkouts. Do not use `down`
   or `down -v` during the switch.

4. Run migrations, checks, and static collection as explicit one-shot commands.
   `--no-deps` prevents Compose from starting the normal `migrate` service
   command, which also screens provisional applicants.

   ```sh
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
   `migrate` service also runs `screen_open_provisional_applications`, which
   can accept users and send Reddit messages. Inspect the open applicant count
   and automation credentials before deliberately running it after core smoke
   tests. Keep scheduled jobs stopped until then.

5. Start only the upgraded app. Leave `nginx-proxy` running with the IP gate
   active. Confirm the new `poll` container uses the recorded build-host image
   ID, compare volume names and mountpoints with the saved record, and inspect
   application/database/proxy logs.

   ```sh
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" up -d --no-deps --no-build --pull never poll
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" ps poll db
   test "$(docker inspect --format '{{.Image}}' "$(docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" ps -q poll)")" = 'IMAGE_ID_RECORDED_ON_BUILD_HOST'
   docker volume inspect --format '{{.Name}} {{.Mountpoint}}' \
     "${POLL_PROJECT}_postgres_data17" "${POLL_PROJECT}_static_volume" \
     "${POLL_PROJECT}_certs" "${POLL_PROJECT}_html" \
     "${POLL_PROJECT}_vhost" "${POLL_PROJECT}_acme" > "$POLL_VOLUME_RECORD.after"
   diff -u "$POLL_VOLUME_RECORD" "$POLL_VOLUME_RECORD.after"
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" logs --tail=100 poll db
   ```

   A successful comparison confirms Compose reused the existing PostgreSQL,
   static, certificate, and proxy volumes instead of creating volumes under a
   checkout-derived project name.

6. From the operator workstation, use
   `https://poll-staging.redditcfb.com` with its temporary origin hosts entry.
   While the allowlist is active, verify login **and logout**, Reddit OAuth
   sign-in and callback, existing ballot viewing, a test ballot submission and
   persisted readback, admin access and provisional-voter management, and
   public results pages. Confirm static files load and inspect logs for errors.
   Keep test writes confined to a test account/poll and clean them up through
   the application if appropriate. The OAuth callback uses the normal HTTPS
   hostname, and its request reaches the same operator-allowlisted origin.

   Explicitly review the effect of any migration or startup command that could
   interact with Reddit. When core checks pass, deliberately run the normal
   applicant-screen command while the traffic gate is still active:

   ```sh
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" run --rm --no-deps --pull never \
     --entrypoint python migrate manage.py screen_open_provisional_applications
   ```

   Verify its accepted/error/notification counts and any Reddit messages, then
   repeat relevant admin and public checks. Reconcile any external Reddit
   messages if rollback is later needed.

7. Disable the gate only after every smoke test passes and the operator accepts
   the logs. This restores the exact host-specific file (or returns to the
   saved default file), tests the resulting Nginx config, and reloads the proxy.
   If `nginx -t` or reload fails, the script puts the allowlist back on disk;
   leave scheduled jobs stopped and resolve the proxy issue before continuing.

   ```sh
   docker exec -i nginx-proxy sh -s -- "$POLL_HOST" <<'SH'
   set -eu
   host=$1
   dir=/etc/nginx/vhost.d
   file="$dir/$host"
   backup="$dir/.${host}.maintenance-original"
   absent="$dir/.${host}.maintenance-was-absent"
   allowfile="$dir/.${host}.maintenance-allow"
   test -f "$backup" && test -f "$allowfile"
   if [ -e "$absent" ]; then rm -f "$file"; else cp -p "$backup" "$file"; fi
   if nginx -t && nginx -s reload; then
     rm -f "$backup" "$absent" "$allowfile" "$file.tmp"
   else
     cidr=$(cat "$allowfile")
     {
       cat "$backup"
       printf '\nallow %s;\ndeny all;\n' "$cidr"
     } > "$file.tmp"
     mv "$file.tmp" "$file"
     exit 1
   fi
   SH
   ```

   From a non-allowlisted network, confirm the public HTTPS hostname now
   reaches the validated app. Then restart the recorded scheduled jobs and
   remove the temporary hosts-file entry from the operator workstation.

## Rollback and cleanup

If a check fails, leave the Nginx gate enabled and scheduled jobs stopped.
Using the recorded snapshot ID, restore the **entire pre-upgrade VM state**
with all disks captured in that snapshot: Docker's data root and metadata,
`postgres_data17`, the `vhost` volume, the original live checkout, and its
configuration. Do not restore only the database disk or only the boot disk.
The snapshot was taken with the old app stopped, PostgreSQL cleanly stopped,
and the Nginx gate active, so it restores the original application revision,
old image/container metadata, configuration, and database together while
keeping public traffic blocked.

After the VM restore, set the recorded values again in the operator shell and
verify the snapshot contents before starting services. Compare the working-tree
status and environment-file checksums below with the values recorded before
the snapshot:

```sh
export POLL_PROJECT=rcfbpoll3
export POLL_OLD_DIR=/path/to/original/live/checkout
export POLL_OLD_COMPOSE="$POLL_OLD_DIR/docker-compose.staging.yml"
export POLL_OLD_REVISION=RECORDED_OLD_REVISION
export POLL_OLD_IMAGE=rcfbpoll:preupgrade-REVIEWED_SHA
export POLL_OLD_IMAGE_ID=RECORDED_OLD_IMAGE_ID
export POLL_HOST=poll-staging.redditcfb.com
test "$(git -C "$POLL_OLD_DIR" rev-parse HEAD)" = "$POLL_OLD_REVISION"
git -C "$POLL_OLD_DIR" status --short
sha256sum \
  "$POLL_OLD_DIR/.env.staging" "$POLL_OLD_DIR/.env.staging.db" \
  "$POLL_OLD_DIR/.env.staging.proxy-companion"
test "$(docker image inspect --format '{{.Id}}' "$POLL_OLD_IMAGE")" = "$POLL_OLD_IMAGE_ID"
docker volume inspect \
  "${POLL_PROJECT}_postgres_data17" "${POLL_PROJECT}_static_volume" \
  "${POLL_PROJECT}_vhost"
docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" ps -a db poll migrate
docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" start nginx-proxy
docker exec nginx-proxy nginx -t
docker exec nginx-proxy nginx -s reload
```

If the recorded checkout, image ID, volume names, or containers are missing or
different, stop. Recheck the VM restore scope; do not start the upgraded
checkout against a partially restored database. Once the old state is
confirmed, start the original database and original app containers without
running migrations:

```sh
docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" start db
docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" exec -T db sh -c \
  'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" start poll
test "$(docker inspect --format '{{.Image}}' "$(docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" ps -q poll)")" = "$POLL_OLD_IMAGE_ID"
docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" logs --tail=100 poll db
```

Use the temporary workstation hosts entry and operator allowlist to smoke-test
the restored app. Only after those checks pass should you run the gate-disable
commands above and restart the recorded scheduled jobs. Writes made during
private smoke tests are absent from the restored snapshot. Reddit messages
sent after the snapshot cannot be rolled back; reconcile them manually before
resuming automation.

Never run `docker compose down -v` during deployment or rollback. Do not
recreate or delete `postgres_data17`, `static_volume`, or the proxy's named
volumes. Keep the original checkout, its configuration, and the tagged
pre-upgrade image until the rollback snapshot retention decision is made.
After the upgraded site is accepted, delete only the verified transferred
`rcfbpoll-${POLL_REVISION}.tar` and its checksum from the VM's private staging
directory. Identify any other old image by exact ID and verify that no running
container or rollback plan needs it before deleting it. Do not run `docker
system prune`, `docker volume prune`, or broad cleanup commands.
