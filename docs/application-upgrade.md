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

The live Compose file binds nginx-proxy to VM ports 80 and 443; poll only
exposes port 8000 inside Docker. The expected production hostname is
poll.redditcfb.com. The checked-in .env.staging may not represent the live
environment: verify the running poll container's VIRTUAL_HOST and stop if it is
not exactly poll.redditcfb.com. Also verify that the Nginx TLS virtual host
uses that hostname before proceeding.

nginx/Dockerfile uses jwilder/nginx-proxy 0.9. Its [0.9.0 template](https://github.com/nginx-proxy/nginx-proxy/blob/0.9.0/nginx.tmpl)
chooses /etc/nginx/vhost.d/<VIRTUAL_HOST> or, if absent,
/etc/nginx/vhost.d/default when docker-gen renders the generated server
configuration. Its [Procfile](https://github.com/nginx-proxy/nginx-proxy/blob/0.9.0/Procfile)
runs docker-gen as a container watcher and reloads Nginx on container changes.
The Compose file mounts vhost at /etc/nginx/vhost.d; the repository's
nginx/vhost.d/default contains the static-file location and is shared by
virtual hosts. Never add the allowlist to that shared file. Use nginx -T to
identify the include in the TLS server block for poll.redditcfb.com. If that
block already includes the host-specific file, back up and edit that file. If
it includes default, copy its current contents to the host-specific file and
explicitly render the generated configuration once. The Nginx access rules are
inherited by locations without their own allow or deny rules; inspect nginx -T
and stop if a location-specific rule could bypass the server-level gate. The
repository's static-file location has no such rule. See [Nginx access-module
inheritance](https://nginx.org/en/docs/http/ngx_http_access_module.html).

The host-specific override persists in the existing vhost volume. Explicitly
render with the image's docker-gen /app/nginx.tmpl /etc/nginx/conf.d/default.conf
command without -watch or -notify, then run nginx -t and reload only if the
syntax test passes. This avoids relying on file creation to trigger the
watcher. When the upgraded poll container starts, the existing watcher will
render again; the template selects the still-present host-specific override.
After that start, inspect nginx -T and repeat the access checks before any
smoke tests. If a gate activation or validation step fails, stop the poll
service and leave the gate backup files in place; do not take the snapshot or
start the upgraded application until the gate is proven active.

On the VM, before stopping the old app, verify its runtime host and inspect the
effective configuration. These checks deliberately compare the live container,
not the hostname in a checked-in sample file:

```sh
set -eu
export POLL_HOST=poll.redditcfb.com
export VM_ORIGIN_IPV4=VM_PUBLIC_IPV4
export OPERATOR_CIDR=OPERATOR_PUBLIC_IPV4/32
export POLL_OLD_CONTAINER_ID="$(docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" ps -q poll)"
test -n "$POLL_OLD_CONTAINER_ID"
POLL_RUNNING_HOST="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$POLL_OLD_CONTAINER_ID" | sed -n 's/^VIRTUAL_HOST=//p')"
test "$POLL_RUNNING_HOST" = "$POLL_HOST" || { echo "VIRTUAL_HOST is '$POLL_RUNNING_HOST', expected '$POLL_HOST'; stop" >&2; exit 1; }
POLL_RUNNING_ALLOWED_HOSTS="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$POLL_OLD_CONTAINER_ID" | sed -n 's/^DJANGO_ALLOWED_HOSTS=//p')"
case ",$POLL_RUNNING_ALLOWED_HOSTS," in *,"$POLL_HOST",*) ;; *) echo "DJANGO_ALLOWED_HOSTS does not include $POLL_HOST; stop" >&2; exit 1;; esac
POLL_STAGED_HOST="$(sed -n 's/^VIRTUAL_HOST=//p' "$POLL_NEW_DIR/.env.staging")"
test "$POLL_STAGED_HOST" = "$POLL_HOST" || { echo "staged VIRTUAL_HOST is '$POLL_STAGED_HOST', expected '$POLL_HOST'; stop" >&2; exit 1; }
```

Capture nginx -T output with restrictive permissions. Inspect the
server_name poll.redditcfb.com TLS server (the block listening on 443), its
include /etc/nginx/vhost.d/... line, its certificate, and any location-level
allow or deny rules. Set POLL_ACTIVE_INCLUDE to exactly the included file
shown there. The only supported values below are default and the
hostname-specific file; stop if the active TLS block uses a different include,
the TLS server name differs, or a host-specific file exists but is not the
active include. Also inspect the port-80 server: under the configured redirect
mode it must redirect application paths to HTTPS; if it is in noredirect mode,
the same host-specific file must gate HTTP as well. Stop if any HTTP path can
reach the application without this restriction.

```sh
set -eu
umask 077
export POLL_NGINX_DUMP=/private/staging/nginx.before-maintenance.txt
docker exec nginx-proxy nginx -T > "$POLL_NGINX_DUMP" 2>&1
grep -Fq "server_name $POLL_HOST;" "$POLL_NGINX_DUMP" || { echo "Nginx does not contain the expected virtual host $POLL_HOST; stop" >&2; exit 1; }
grep -n -B 3 -A 35 -F "server_name $POLL_HOST;" "$POLL_NGINX_DUMP"
docker exec nginx-proxy test -x /usr/local/bin/docker-gen
docker exec nginx-proxy test -r /app/nginx.tmpl
docker exec nginx-proxy grep -F 'docker-gen -watch -notify "nginx -s reload" /app/nginx.tmpl /etc/nginx/conf.d/default.conf' /app/Procfile
export POLL_ACTIVE_INCLUDE=/etc/nginx/vhost.d/default
# If nginx -T shows the host-specific include in that TLS server instead, use:
# export POLL_ACTIVE_INCLUDE="/etc/nginx/vhost.d/$POLL_HOST"
```

On the operator workstation, use the same hostname and origin address. Obtain
the workstation's public IPv4 egress address as seen by the VM and use it with
/32 for OPERATOR_CIDR. If the workstation uses a VPN or proxy, verify that the
direct route to the VM uses that address. This allowlist also permits any
other device sharing that public egress address during maintenance. Since the
Compose proxy publishes port 443 on the VM, no Cloudflare access is needed.
If public DNS is proxied through Cloudflare or another CDN, map the hostname
temporarily to the VM origin on the operator workstation so Nginx sees the
operator's source address. Keep the HTTPS hostname in the browser and OAuth
flow; do not browse to the IP. This preserves TLS verification, secure-cookie
host handling, and the registered Reddit OAuth redirect hostname.

```sh
export POLL_HOST=poll.redditcfb.com
export VM_ORIGIN_IPV4=VM_PUBLIC_IPV4
export OPERATOR_CIDR="$(curl -4fsS https://api.ipify.org)/32"
printf '%s %s\n' "$VM_ORIGIN_IPV4" "$POLL_HOST" | sudo tee -a /etc/hosts
```

Copy the reported CIDR to the VM shell with the same origin and hostname:

```sh
export POLL_HOST=poll.redditcfb.com
export VM_ORIGIN_IPV4=VM_PUBLIC_IPV4
export OPERATOR_CIDR=OPERATOR_PUBLIC_IPV4/32
```

On Windows, add VM_ORIGIN_IPV4 poll.redditcfb.com to
C:\Windows\System32\drivers\etc\hosts as Administrator. Remove the entry
after the maintenance window. A direct-origin HTTPS request from the operator
workstation is:

```sh
curl --resolve "${POLL_HOST}:443:${VM_ORIGIN_IPV4}" \
  --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  "https://${POLL_HOST}/"
```

Create a host-specific override, preserving the effective original contents
and recording whether the host-specific file existed. The shared default file
is only read, never modified. This script refuses an unexpected active include
or stale backup markers. It writes allow and deny before the saved contents so
the operator rule is evaluated first.

```sh
if ! docker exec -i nginx-proxy sh -s -- "$POLL_HOST" "$OPERATOR_CIDR" "$POLL_ACTIVE_INCLUDE" <<'SH'
set -eu
host=$1
cidr=$2
active=$3
dir=/etc/nginx/vhost.d
case "$host" in *[!A-Za-z0-9.-]*|'') echo "invalid host" >&2; exit 2;; esac
case "$cidr" in *[!0-9./]*|'') echo "invalid IPv4 CIDR" >&2; exit 2;; esac
file="$dir/$host"
default="$dir/default"
backup="$dir/.${host}.maintenance-original"
absent="$dir/.${host}.maintenance-was-absent"
allowfile="$dir/.${host}.maintenance-allow"
test "$active" = "$default" || test "$active" = "$file"
test ! -e "$backup" && test ! -e "$absent" && test ! -e "$allowfile"
if [ -e "$file" ]; then
  test ! -L "$file"
  test "$active" = "$file"
  cp -p "$file" "$backup"
else
  test "$active" = "$default" && test -s "$default"
  cp -p "$default" "$backup"
  : > "$absent"
fi
printf '%s\n' "$cidr" > "$allowfile"
{
  printf 'allow %s;\ndeny all;\n\n' "$cidr"
  cat "$backup"
} > "$file.tmp"
chmod "$(stat -c '%a' "$backup")" "$file.tmp"
mv "$file.tmp" "$file"
resolvers=$(awk '$1 == "nameserver" {print ($2 ~ ":")? "["$2"]": $2}' ORS=' ' /etc/resolv.conf | sed 's/ *$//g')
test -n "$resolvers"
RESOLVERS="$resolvers" docker-gen /app/nginx.tmpl /etc/nginx/conf.d/default.conf
nginx -t
nginx -s reload
SH
then
  docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" stop --timeout 60 poll
  echo "Gate activation failed; poll is stopped. Keep the backups and do not continue." >&2
  exit 1
fi
```

The upstream nginx-proxy 0.9.0 image pins docker-gen 0.7.6. Its [CLI usage](https://github.com/nginx-proxy/docker-gen/blob/0.7.6/README.md#usage)
accepts a template and destination without watch mode; it renders once and exits
when -watch and -notify are omitted. This is the template-render step from the
0.9 watcher, with automatic reload omitted so this procedure can test syntax first. After the reload, dump the effective
configuration again and confirm the TLS server for this hostname includes
/etc/nginx/vhost.d/poll.redditcfb.com, and that the same server contains
allow OPERATOR_CIDR; followed by deny all;. Also verify no location-level
access rule overrides it. nginx -t and a successful reload alone do not prove
the intended server uses the gate.

```bash
set -eu
trap 'docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" stop --timeout 60 poll' ERR
export POLL_NGINX_DUMP=/private/staging/nginx.maintenance.txt
docker exec nginx-proxy nginx -T > "$POLL_NGINX_DUMP" 2>&1
grep -n -B 3 -A 40 -F "server_name $POLL_HOST;" "$POLL_NGINX_DUMP"
grep -Fq "include /etc/nginx/vhost.d/$POLL_HOST;" "$POLL_NGINX_DUMP"
grep -Fq "allow $OPERATOR_CIDR;" "$POLL_NGINX_DUMP"
grep -Fq 'deny all;' "$POLL_NGINX_DUMP"
   docker exec nginx-proxy grep -Fqx "allow $OPERATOR_CIDR;" "/etc/nginx/vhost.d/$POLL_HOST"
   docker exec nginx-proxy grep -Fqx 'deny all;' "/etc/nginx/vhost.d/$POLL_HOST"
```

Now verify actual access, using the workstation's hosts mapping or curl
--resolve above. The allowlisted operator request must reach the app without
HTTP 403 (normally 200 or a login redirect):

```sh
set -eu
POLL_OPERATOR_STATUS="$(curl --resolve "${POLL_HOST}:443:${VM_ORIGIN_IPV4}" -sS -o /dev/null -w '%{http_code}' "https://${POLL_HOST}/")"
test "$POLL_OPERATOR_STATUS" != 403
```

From a separate, non-allowlisted network, run the direct-origin request and
require exactly HTTP 403:

```sh
set -eu
POLL_NONOPERATOR_STATUS="$(curl --resolve "${POLL_HOST}:443:${VM_ORIGIN_IPV4}" -sS -o /dev/null -w '%{http_code}' "https://${POLL_HOST}/")"
test "$POLL_NONOPERATOR_STATUS" = 403
```

Do not continue to the snapshot unless the operator gets a non-403 response and the
non-allowlisted request gets 403. If either access check or the effective-config check fails, immediately run `docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" stop --timeout 60 poll` on the VM and keep scheduled writers stopped. Do not use a CDN IP in OPERATOR_CIDR.


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
   the deployment record, along with the verified hostname, VM origin,
   operator CIDR, active Nginx include path, checkout status, and staged env
   file checksums. Stop every other writer before proceeding.

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

   ```bash
   set -eu
   trap 'docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" stop --timeout 60 poll' ERR
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" up -d --no-deps --no-build --pull never poll
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" ps poll db
   test "$(docker inspect --format '{{.Image}}' "$(docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" ps -q poll)")" = 'IMAGE_ID_RECORDED_ON_BUILD_HOST'
   docker volume inspect --format '{{.Name}} {{.Mountpoint}}' \
     "${POLL_PROJECT}_postgres_data17" "${POLL_PROJECT}_static_volume" \
     "${POLL_PROJECT}_certs" "${POLL_PROJECT}_html" \
     "${POLL_PROJECT}_vhost" "${POLL_PROJECT}_acme" > "$POLL_VOLUME_RECORD.after"
   diff -u "$POLL_VOLUME_RECORD" "$POLL_VOLUME_RECORD.after"
   docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" logs --tail=100 poll db
   POLL_NEW_CONTAINER_ID="$(docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" ps -q poll)"
   POLL_NEW_HOST="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$POLL_NEW_CONTAINER_ID" | sed -n 's/^VIRTUAL_HOST=//p')"
   test "$POLL_NEW_HOST" = "$POLL_HOST" || { echo "new VIRTUAL_HOST is '$POLL_NEW_HOST', expected '$POLL_HOST'; stop" >&2; exit 1; }
   docker exec nginx-proxy nginx -t
   export POLL_NGINX_DUMP=/private/staging/nginx.after-app-start.txt
   docker exec nginx-proxy nginx -T > "$POLL_NGINX_DUMP" 2>&1
   grep -n -B 3 -A 40 -F "server_name $POLL_HOST;" "$POLL_NGINX_DUMP"
   grep -Fq "include /etc/nginx/vhost.d/$POLL_HOST;" "$POLL_NGINX_DUMP"
   grep -Fq "allow $OPERATOR_CIDR;" "$POLL_NGINX_DUMP"
   grep -Fq 'deny all;' "$POLL_NGINX_DUMP"
   docker exec nginx-proxy grep -Fqx "allow $OPERATOR_CIDR;" "/etc/nginx/vhost.d/$POLL_HOST"
   docker exec nginx-proxy grep -Fqx 'deny all;' "/etc/nginx/vhost.d/$POLL_HOST"
   ```

   A successful comparison confirms Compose reused the existing PostgreSQL,
   static, certificate, and proxy volumes instead of creating volumes under a
   checkout-derived project name. The poll start generates an Nginx-proxy
   container event; confirm that its generated TLS server still uses the
   per-host gate, then repeat the operator non-403 and external 403 checks
   before any smoke test. If any check fails, stop poll and do not proceed.

6. From the operator workstation, use
   `https://poll.redditcfb.com` with its temporary origin hosts entry.
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
   the logs. Restore the original host-specific file, or remove the temporary
   host-specific override if it did not exist before maintenance. Render the
   generated configuration without the watch/notify flags, syntax-test it, and
   reload only after the test succeeds. The saved files remain until the external
   access check succeeds.

   ```sh
   if ! docker exec -i nginx-proxy sh -s -- "$POLL_HOST" <<'SH'
   set -eu
   host=$1
   dir=/etc/nginx/vhost.d
   file="$dir/$host"
   backup="$dir/.${host}.maintenance-original"
   absent="$dir/.${host}.maintenance-was-absent"
   allowfile="$dir/.${host}.maintenance-allow"
   test -f "$backup" && test -f "$allowfile"
   if [ -e "$absent" ]; then
     rm -f "$file"
   else
     cp -p "$backup" "$file"
   fi
   resolvers=$(awk '$1 == "nameserver" {print ($2 ~ ":")? "["$2"]": $2}' ORS=' ' /etc/resolv.conf | sed 's/ *$//g')
   test -n "$resolvers"
   RESOLVERS="$resolvers" docker-gen /app/nginx.tmpl /etc/nginx/conf.d/default.conf
   nginx -t
   nginx -s reload
   SH
   then
     docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" stop --timeout 60 poll
     echo "Gate restoration failed; poll is stopped. Keep backups and do not restart writers." >&2
     exit 1
   fi
   ```

   Verify the actual included file and compare it with the pre-maintenance copy.
   If it was absent originally, the generated TLS server should include default
   again and the host-specific file must be absent. If it existed, the file must
   match the saved bytes. Inspect nginx -T for the poll.redditcfb.com TLS server
   and confirm its access rules match the captured pre-maintenance configuration.

   ```bash
   set -eu
   trap 'docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" stop --timeout 60 poll' ERR
   docker exec nginx-proxy nginx -T > "$POLL_NGINX_DUMP" 2>&1
   grep -n -B 3 -A 40 -F "server_name $POLL_HOST;" "$POLL_NGINX_DUMP"
   docker exec -i nginx-proxy sh -s -- "$POLL_HOST" <<'SH'
   set -eu
   host=$1
   dir=/etc/nginx/vhost.d
   file="$dir/$host"
   backup="$dir/.${host}.maintenance-original"
   absent="$dir/.${host}.maintenance-was-absent"
   if [ -e "$absent" ]; then
     test ! -e "$file"
     grep -Fq 'include /etc/nginx/vhost.d/default;' /etc/nginx/conf.d/default.conf
   else
     cmp -s "$file" "$backup"
     grep -Fq "include /etc/nginx/vhost.d/$host;" /etc/nginx/conf.d/default.conf
   fi
   SH
   ```

   From a non-allowlisted network, use the direct-origin HTTPS hostname and
   require a response other than 403 (normally 200 or a login redirect). If this
   check or any restoration check fails, immediately run `docker compose -p "$POLL_PROJECT" -f "$POLL_COMPOSE" stop --timeout 60 poll` on the VM, keep scheduled writers stopped, and leave the backup markers in place while repairing the gate. Do not restart the scheduled jobs until public access reaches the
   validated app. Once the effective configuration and external check pass,
   remove the maintenance backups and marker files, then restart the recorded
   scheduled jobs and remove the temporary hosts-file entry from the operator
   workstation:

   ```sh
   docker exec -i nginx-proxy sh -s -- "$POLL_HOST" <<'SH'
   set -eu
   host=$1
   dir=/etc/nginx/vhost.d
   rm -f "$dir/.${host}.maintenance-original" \
     "$dir/.${host}.maintenance-was-absent" \
     "$dir/.${host}.maintenance-allow" "$dir/$host.tmp"
   SH
   ```



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
export POLL_COMPOSE="$POLL_OLD_COMPOSE"
export POLL_OLD_REVISION=RECORDED_OLD_REVISION
export POLL_OLD_IMAGE=rcfbpoll:preupgrade-REVIEWED_SHA
export POLL_OLD_IMAGE_ID=RECORDED_OLD_IMAGE_ID
export POLL_HOST=poll.redditcfb.com
export OPERATOR_CIDR=RECORDED_OPERATOR_PUBLIC_IPV4/32
export POLL_NGINX_DUMP=/private/staging/nginx.rollback.txt
set -eu
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
docker exec nginx-proxy sh -c 'nginx -t && nginx -s reload'
```

If the recorded checkout, image ID, volume names, or containers are missing or
different, stop. Recheck the VM restore scope; do not start the upgraded
checkout against a partially restored database. Once the old state is
confirmed, start the original database and original app containers without
running migrations:

```bash
set -eu
trap 'docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" stop --timeout 60 poll' ERR
docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" start db
docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" exec -T db sh -c \
  'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" start poll
POLL_RESTORED_CONTAINER_ID="$(docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" ps -q poll)"
POLL_RESTORED_HOST="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$POLL_RESTORED_CONTAINER_ID" | sed -n 's/^VIRTUAL_HOST=//p')"
test "$POLL_RESTORED_HOST" = "$POLL_HOST"
test "$(docker inspect --format '{{.Image}}' "$POLL_RESTORED_CONTAINER_ID")" = "$POLL_OLD_IMAGE_ID"
docker exec nginx-proxy nginx -t
docker exec nginx-proxy nginx -T > "$POLL_NGINX_DUMP" 2>&1
grep -n -B 3 -A 40 -F "server_name $POLL_HOST;" "$POLL_NGINX_DUMP"
grep -Fq "include /etc/nginx/vhost.d/$POLL_HOST;" "$POLL_NGINX_DUMP"
grep -Fq 'deny all;' "$POLL_NGINX_DUMP"
docker exec nginx-proxy grep -Fqx "allow $OPERATOR_CIDR;" "/etc/nginx/vhost.d/$POLL_HOST"
docker exec nginx-proxy grep -Fqx 'deny all;' "/etc/nginx/vhost.d/$POLL_HOST"
docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" logs --tail=100 poll db
```

Use the temporary workstation hosts entry and operator allowlist to smoke-test
the restored app. Repeat the access checks: the operator must not receive 403,
and a non-allowlisted network must receive 403. If either check fails, stop the
restored poll service with `docker compose -p "$POLL_PROJECT" -f "$POLL_OLD_COMPOSE" stop --timeout 60 poll`. Only after those checks pass
should you run the gate-disable commands above and restart the recorded
scheduled jobs. Writes made during
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
