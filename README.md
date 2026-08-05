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

### Resetting local data

To discard local changes and restore a fresh fixture:

```sh
docker compose down -v
docker compose up --build
```

`down -v` deletes the local PostgreSQL volume. It does not affect production
or any remote database.
