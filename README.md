# rcfbpoll3

r/CFB Poll Top 25 Site Re-Rebuild

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

### Provisional-application notifications

When a staff member accepts or rejects an open provisional-voter application in
Django admin, the site sends the applicant a Reddit private message from
`CFB_Referee`. Create a **web app** at Reddit while logged in as that account,
then complete Reddit's permanent OAuth code flow as `CFB_Referee` with the
`privatemessages` scope to obtain a refresh token. Messaging is disabled until
these deployment environment variables are set:

```text
REDDIT_MESSAGE_CLIENT_ID
REDDIT_MESSAGE_CLIENT_SECRET
REDDIT_MESSAGE_REFRESH_TOKEN
```

Use the client ID and secret from that Reddit application and store the resulting
refresh token as a deployment secret. The notifier supplies a default Reddit
user agent, which can be overridden with `REDDIT_MESSAGE_USER_AGENT` if
necessary. The refresh token authenticates as the account that completed the
OAuth flow; no Reddit password is stored by the site. Failed deliveries are
logged and shown as an admin warning, but never reverse the application decision.
