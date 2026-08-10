# rcfbpoll3

r/CFB Poll Top 25 Site Re-Rebuild

## Provisional application screening

The deployment environment should provide RCFB_MODERATOR_USERNAMES as a
comma-separated list of the current r/CFB moderator usernames, for example
sample_mod_one,sample_mod_two. Auto-accept fails closed when this setting is
missing or malformed. The environment-backed provider is intentionally a seam
for a future dynamic moderator lookup.

After migrations, the production deployment's migrate service runs
screen_open_provisional_applications to reconsider existing OPEN applications.
The file docker-compose.staging.yml is currently the real production
deployment despite its name.


## Local development

A fresh clone can start a usable local copy, populated with a sanitized poll
fixture, with Docker Compose:

```sh
docker compose up --build
```

Open <http://localhost:8000>. On first start, Compose downloads the versioned
fixture from this repository's GitHub Releases, verifies its SHA-256 checksum,
restores it to the local PostgreSQL volume, and applies any outstanding Django
migrations. Later starts reuse the volume and do not download or overwrite
data.

The fixture contains public poll content, usernames, and rationales. It omits
authentication accounts, sessions, social-login data, admin logs, provisional
applications, and derived result caches. It is a release asset rather than a
regular Git object so clones and Git history remain small.

### Local admin

The fixture includes a local-only Django administrator:

```text
Username: localadmin
Password: RcfbPollLocal2026!
```

This password is intentionally public and predictable because the fixture is
public. Use the account only in a local development container; never reuse
these credentials or expose that container as a real deployment.

### Resetting local data

To discard local changes and restore a fresh fixture:

```sh
docker compose down -v
docker compose up --build
```

`down -v` deletes the local PostgreSQL volume. It does not affect production
or any remote database.

## Reddit automation accounts

Normal site login and server-side automation use separate Reddit OAuth
applications. Django Allauth continues to use the existing `REDDIT_KEY` and
`REDDIT_SECRET` application and its existing login scopes. Automation uses a
different Reddit application and never changes the normal login flow.

Configure these deployment variables for automation:

```text
REDDIT_AUTOMATION_CLIENT_ID
REDDIT_AUTOMATION_CLIENT_SECRET
REDDIT_AUTOMATION_USER_AGENT
REDDIT_AUTOMATION_REDIRECT_URI
REDDIT_AUTOMATION_TOKEN_ENCRYPTION_KEY
```

`REDDIT_AUTOMATION_REDIRECT_URI` must exactly match the callback registered in
the automation Reddit application. The callback path used by this project is:

```text
/admin/poll/redditaccount/oauth/callback/
```

Generate the Fernet encryption key during deployment, for example with:

```sh
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep the key outside the database and back it up as a deployment secret. It is
needed to decrypt connected-account refresh tokens.

Superusers connect accounts from **Admin → Poll → Reddit accounts → Connect
Reddit account**. The OAuth callback obtains the Reddit username and granted
scopes directly from Reddit; administrators never paste usernames or refresh
tokens into the site. Roles are configured separately and may share one
connected account:

- `NOTIFICATIONS` requires `identity` and `privatemessages`.
- `APPLICATION_REVIEW` requires `identity` and `read`.
- `RESULTS_PUBLISHER` requires `identity` and `submit`.

The expected initial production assignments are configuration only:
`CFB_Referee` for `NOTIFICATIONS`, and `sirgippy` for both review and results.
No usernames are hard-coded in the application.

## Poll migration deployment

The poll migration baseline represents the legacy poll tables already present
in the production database. Before deployment, back up the database and verify
that schema against `poll/migrations/0001_initial.py`. On that existing
database, adopt only the baseline with:

```sh
python manage.py migrate poll 0001_initial --fake-initial
python manage.py migrate --noinput
```

Do not fake `0002_poll_required` or `0003_reddit_accounts`; those migrations
must run normally. Verify that `poll_poll.required` was added and backfilled,
the Reddit account tables were created, and a subsequent `migrate` is
idempotent. Never run this procedure against a shared database without a
current backup and schema verification.
