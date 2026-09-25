# Documentation

Installing, configuring and running TS Pro Backup. The
[README](../README.md) has the short version.

## Installing with Docker Compose

You need [Docker](https://docs.docker.com/get-docker/) with the Compose
plugin, and nothing else.

### 1. Get the compose file

Either clone the repository:

```bash
git clone https://github.com/hyprlab/tspro-backup.git
cd tspro-backup
```

or create a `docker-compose.yml` next to a `data/` directory with this
content. It pulls the published image, so no source checkout is needed:

```yaml
services:
  tspro-backup:
    image: hyprlab/tspro-backup:latest
    container_name: tspro-backup
    ports:
      - "${TSPB_PORT:-8095}:8000"
    volumes:
      - ./data:/data
    environment:
      - TSPB_SECRET_KEY=${TSPB_SECRET_KEY:?TSPB_SECRET_KEY must be set in .env}
      - TSPB_ADMIN_USERNAME=${TSPB_ADMIN_USERNAME:-admin}
      - TSPB_ADMIN_PASSWORD=${TSPB_ADMIN_PASSWORD:-admin}
      - TSPB_REST_PASSPHRASE=${TSPB_REST_PASSPHRASE:-}
      - TSPB_MAX_UPLOAD_MB=${TSPB_MAX_UPLOAD_MB:-8192}
      - TSPB_DEBUG=${TSPB_DEBUG:-0}
    restart: unless-stopped
```

The repository's own `docker-compose.yml` adds container hardening
(`no-new-privileges`, dropped capabilities, a memory limit) and explains each
line; it is worth copying instead if you can.

### 2. Configure the environment

```bash
cp .env.example .env
```

The full sample `.env`:

```ini
# Copy to .env and fill in. Generate a strong secret:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
TSPB_SECRET_KEY=change-me-to-a-long-random-string

# Seed admin (used only on first boot, when the DB is empty).
TSPB_ADMIN_USERNAME=admin
TSPB_ADMIN_PASSWORD=admin

# Host port to expose the console on (the container always listens on
# 8000 internally).
TSPB_PORT=8095

# Optional at-rest encryption passphrase. If set, reproducible across
# rebuilds; if blank, a random key is generated in ./data/rest.key.
TSPB_REST_PASSPHRASE=

# Max single upload in MiB (whole-site bundles can be large).
TSPB_MAX_UPLOAD_MB=8192

# Console sign-in lockout. After this many failed attempts for one username
# OR one client IP within the window (minutes), sign-ins are refused until
# the oldest failures age out. Set FAILURES to 0 to disable.
TSPB_LOGIN_MAX_FAILURES=5
TSPB_LOGIN_WINDOW_MINUTES=15

# Set to 1 only for local HTTP dev (disables Secure cookie flag).
TSPB_DEBUG=0

# Trust X-Forwarded-* from the proxy in front. Leave at 1 ONLY when a trusted
# reverse proxy is the sole ingress and overwrites X-Forwarded-For. If the
# container port is reachable directly, set to 0 (uses the real socket peer)
# so the login lockout can't be defeated by a spoofed X-Forwarded-For.
TSPB_TRUST_PROXY=1
```

At a minimum, set a strong session secret and change the admin password:

```ini
TSPB_SECRET_KEY=<paste the generated secret>
TSPB_ADMIN_PASSWORD=<a strong password>
```

### 3. Start it

```bash
docker compose up -d
```

The first boot creates the seed admin and the database in `./data`. Open the
console at **<http://localhost:8095>** and sign in with
`TSPB_ADMIN_USERNAME` / `TSPB_ADMIN_PASSWORD`.

```bash
docker compose logs -f
docker compose ps
```

### 4. First-run setup in the console

1. **Sign in** with the seed credentials. If the admin password is still the
   default `admin`, the console asks for a new one before anything else is
   reachable.
2. **Settings**: end-to-end encryption is required by default. Optionally
   turn on Turnstile and encryption at rest, and set the default retention.
3. **Sites > Add site**: name it. Copy the **API key** and the **private
   key**, both shown once, and store the private key somewhere safe.
4. In your TS Pro portal, add a **TS Pro Backup** target pointing at
   `https://<this-host>/api/v1` with that API key. It fetches the site's
   public key and encrypts every backup to it.

> The **private key** is the only thing that can decrypt your backups, and
> this server never keeps a copy. If it is lost, the stored archives can't be
> recovered. That is what keeps the server unable to read them. Keep it in a
> password manager.

### 5. Put TLS in front of it

The console sets `Secure` session cookies, so in production it must be served
over HTTPS. Terminate TLS at a reverse proxy (Caddy, nginx, Traefik,
Cloudflare Tunnel) in front of the container, for example
`https://backup.example.org` to `http://127.0.0.1:8095`. Make sure the
proxy's maximum request body is large enough for your whole-site bundles, or
rely on the chunked upload endpoints. Leave `TSPB_DEBUG=0` behind TLS; set it
to `1` **only** for local plain-HTTP development.

The app trusts `X-Forwarded-*` from the proxy by default
(`TSPB_TRUST_PROXY=1`), which is right when a trusted proxy is the **only**
way in. If the container port is also reachable directly, either bind it to
loopback (`127.0.0.1:8095:8000`) or set `TSPB_TRUST_PROXY=0`, so a spoofed
`X-Forwarded-For` can't defeat the per-IP sign-in lockout.

## Upgrading

```bash
docker compose pull          # fetch the new image
docker compose up -d         # recreate the container
```

Your data lives in the `./data` volume and is kept across upgrades. Schema
changes are applied at boot (additive SQLite migrations), so there is no
manual migration step.

`latest` is always the newest stable release. To pin a version, change the
image tag in `docker-compose.yml` to one such as `1.3.2`; once betas are
published, `beta` follows them. See
[RELEASING.md](RELEASING.md#channels-and-cadence).

> **Upgrading to 1.1.0** has three one-time effects: existing console
> sessions are signed out; an admin still on the `admin` password is sent
> through a forced password change; and a site with end-to-end encryption
> required but no key must have its keypair rotated before it can upload.

## Building from source

To build the image locally instead of pulling it, uncomment `build: .` in
`docker-compose.yml` and run `docker compose up -d --build`.

## Running locally without Docker

For development:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
TSPB_SECRET_KEY=dev-secret TSPB_DEBUG=1 .venv/bin/python run.py
.venv/bin/python -m pytest
```

It serves on <http://localhost:8000> with plain-HTTP development cookies.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `TSPB_SECRET_KEY` | none, required | Flask session secret. |
| `TSPB_PORT` | `8095` | Host port for the console (compose only). |
| `TSPB_FERNET_KEY` | generated (`data/secret.key`) | Seed for encrypting stored secrets such as the Turnstile secret and restore tokens. |
| `TSPB_REST_PASSPHRASE` | generated (`data/rest.key`) | Encryption-at-rest passphrase. |
| `TSPB_ADMIN_USERNAME` / `TSPB_ADMIN_PASSWORD` | `admin` / `admin` | Seed admin, first boot only. The default password forces a change at first sign-in. |
| `TSPB_DATA_DIR` | `/data` | Where the database and archives live. |
| `TSPB_MAX_UPLOAD_MB` | `8192` | Largest backup, single-shot or reassembled. |
| `TSPB_SITE_QUOTA_MB` | `0` (off) | Optional storage quota per site. |
| `TSPB_TRUST_PROXY` | `1` | Trust `X-Forwarded-*`. Set `0` if the port is reachable without a trusted proxy. |
| `TSPB_LOGIN_MAX_FAILURES` | `5` | Failed sign-ins (per username or IP) before lockout; `0` turns it off. |
| `TSPB_LOGIN_WINDOW_MINUTES` | `15` | The lockout's sliding window. |
| `TSPB_MEM_LIMIT` | `2g` | Container memory limit (compose only). |
| `TSPB_DEBUG` | `0` | `1` for plain-HTTP development cookies. |
| `TSPB_FLASK_DEBUG` | `0` | `1` for the Werkzeug debugger (loopback development only). |

> If you use encryption at rest, **back up `TSPB_REST_PASSPHRASE` (or
> `data/rest.key`)**. Without it the stored archives can't be read.

## Backing up the backup server

Everything stateful lives under `./data`:

- `tspro_backup.db`: sites, settings and backup metadata.
- `storage/site-<id>/`: the stored archives.
- `rest.key` and `secret.key`: generated keys, unless you supplied your own
  through the environment. **These are secrets.** Protect the volume; a copy
  of `data/` carries the keys with it.

To move to another host, stop the container and copy the whole `data/`
directory.
