<p align="center">
  <img src="app/static/img/logo_tspro_white.svg" alt="TS Pro Backup" width="320">
</p>

<h1 align="center">TS Pro Backup</h1>

<p align="center">Off-site, encrypted backup storage for Trusted Servants Pro.</p>

<p align="center">
  <a href="https://hub.docker.com/r/hyprlab/tspro-backup"><img alt="Docker Image" src="https://img.shields.io/docker/v/hyprlab/tspro-backup?label=docker&sort=semver"></a>
  <a href="https://hub.docker.com/r/hyprlab/tspro-backup"><img alt="Docker Pulls" src="https://img.shields.io/docker/pulls/hyprlab/tspro-backup"></a>
  <a href="LICENSE"><img alt="License: AGPL-3.0" src="https://img.shields.io/badge/license-AGPL--3.0-blue"></a>
</p>

---

TS Pro Backup is a small, self-hostable server you deploy **off-site** from
your [Trusted Servants Pro](https://github.com/hyprlab/trusted-servants-pro)
portal. Each portal ("site") connects to this server's API with its own key
and pushes backup archives here. The server stores them, optionally
**AES-256 encrypted at rest**, enforces a **grandfather-father-son retention
policy**, and has a web console, styled like TS Pro, for managing sites and
browsing backups.

It receives two kinds of archive from TS Pro:

- **Whole-site backups** (`full`): the complete portal export, meaning the
  SQLite database, uploads and the encryption key seed.
- **Frontend-only backups** (`frontend`): just the public web frontend.

Retention runs separately per scope, so a burst of frontend snapshots never
evicts your whole-site backups.

## Features

- **End-to-end encrypted** (on by default): every site gets its own X25519
  keypair. TS Pro encrypts each backup to the site's **public** key before
  upload; only the **private** key, shown once when the site is created and
  never stored here, can decrypt it. The server holds only ciphertext, and
  the API rejects any upload that isn't already encrypted.
- **Remote restore**: push a stored full backup back into the live TS Pro
  site from the console, for a corrupted database or a locked-out admin.
  Gated by a restore token and the operator's private key; off by default.
- **Hardened console sign-in**: lockout per username and per IP, a forced
  password change on first sign-in, optional Cloudflare Turnstile, and
  sessions invalidated on a password change.
- **Admin and user roles**: `user` accounts manage sites and backups but
  can't rotate keys, delete sites or change a site's encryption policy.
- **Hardened by default**: a non-root container, secure response headers
  (CSP, HSTS, `X-Frame-Options`), `0600` data files, upload size and quota
  caps, and an envelope check on every end-to-end encrypted upload.
- **Encryption at rest**: streaming AES-256-GCM, server-wide or per site.
  The server holds this key, so it protects the storage volume, not the
  data from the server; it is separate from the end-to-end layer.
- **GFS retention**: keep the newest backup for each of the last N days,
  weeks, months and years.
- **An HTTP API** shaped like TS Pro's other backup targets
  (`put / list / delete / fetch`), with single-shot and chunked uploads for
  multi-GB bundles behind a proxy's body-size cap.

## Quick start

You need [Docker](https://docs.docker.com/get-docker/) with the Compose
plugin.

```bash
git clone https://github.com/hyprlab/tspro-backup.git
cd tspro-backup
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste as TSPB_SECRET_KEY in .env
docker compose up -d
```

Open **<http://localhost:8095>** and sign in with `TSPB_ADMIN_USERNAME` /
`TSPB_ADMIN_PASSWORD` from `.env` (`admin` / `admin` unless changed). A
default password has to be changed before anything else is reachable.

Then:

1. **Settings**: end-to-end encryption is required by default. Optionally
   turn on Turnstile and encryption at rest, and set the default retention.
2. **Sites > Add site**: name it, then copy the **API key** and the
   **private key**. Both are shown once.
3. In your TS Pro portal, add a **TS Pro Backup** target pointing at
   `https://<this-host>/api/v1` with that API key. It fetches the site's
   public key and encrypts every backup to it.

> **The private key is the only thing that can decrypt your backups**, and
> this server never keeps a copy. If it is lost, the stored archives can't
> be recovered. Keep it in a password manager.

In production, serve the console over HTTPS behind a reverse proxy. The
[documentation](docs/DOCUMENTATION.md) covers TLS, every setting, upgrading
and backing up the server itself.

### Upgrading

```bash
docker compose pull && docker compose up -d
```

Data in `./data` is kept, and schema changes are applied at boot.

## Documentation

| | |
| --- | --- |
| [Documentation](docs/DOCUMENTATION.md) | Installing, configuration, TLS, upgrading, backing up the server |
| [API](docs/API.md) | The `/api/v1` protocol TS Pro speaks |
| [Architecture](docs/ARCHITECTURE.md) | How the pieces fit, and the encryption layers |
| [Security](docs/SECURITY.md) | The security model, and reporting a problem |
| [Contributing](docs/CONTRIBUTING.md) | Commits, prose style, credit, issue replies |
| [Releasing](docs/RELEASING.md) | SemVer, the beta and stable channels, shipping |
| [Changelog](CHANGELOG.md) | What changed in each release |

## AI notice

TS Pro Backup is built by a human maintainer who uses generative AI as a
development tool. Most of the code was written by Anthropic's Claude, through
Claude Code, following the maintainer's direction; documentation and release
notes are largely AI-drafted and human-edited. The maintainer decides what
gets built, reviews the results, tests every release and signs off on
everything that ships. Commits are made under the maintainer's name; the tool
is declared here once, for the whole repository, instead of in a trailer on
every commit.

The app itself contains no AI. It has no AI features and makes no requests to
AI services: your backups are stored and served from your own host only.

Bug reports and pull requests are welcome from people and their AI tools
alike; everything merged gets the same human review.

## License

TS Pro Backup is free software, licensed under the **GNU Affero General
Public License v3.0 or later** ([AGPL-3.0-or-later](LICENSE)).

© 2026 Hyprlab
