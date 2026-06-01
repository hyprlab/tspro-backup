# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**TS Pro Backup** — a standalone, off-site backup server for
[Trusted Servants Pro](../tspro). Operators deploy this somewhere
separate from their portal; each TS Pro instance ("site") then pushes its
backup archives here over an authenticated HTTP API. The server stores
them (optionally AES-256 encrypted at rest), enforces a
grandfather-father-son retention policy per site and per scope, and
offers a web console — styled to match TS Pro — for managing sites and
browsing backups.

It is the *receiving* half of an off-site backup pair. TS Pro will gain a
new "TS Pro Backup" backup target (alongside its existing FTP / SFTP /
Dropbox backends in `tspro/app/backup_backends.py`) that speaks this
server's `/api/v1` protocol.

## Commands

**Run (Docker, preferred):** `docker compose up -d --build` — serves on
host port **8095** (container 8000). Data persisted in `./data`. Requires
`TSPB_SECRET_KEY` in `.env` (copy `.env.example`).

**Run (local):** `pip install -r requirements.txt && python run.py` —
serves on port 8000 with `TSPB_DEBUG=1` for plain-HTTP cookies.

**Seeded admin:** on first boot (empty DB), `TSPB_ADMIN_USERNAME` /
`TSPB_ADMIN_PASSWORD` (defaults `admin`/`admin`) is created.

No test suite or linter is configured.

## Architecture

Flask + SQLAlchemy + SQLite app factory (`app/__init__.py::create_app`).
Three blueprints:

- `auth` (`app/auth.py`) — console login/logout + Cloudflare Turnstile.
- `main` (`app/routes.py`) — the web console (dashboard, sites, backups,
  settings, account). Session-cookie auth via Flask-Login.
- `api`  (`app/api.py`, prefix `/api/v1`) — the wire protocol TS Pro
  talks to. Authenticated by a per-site API key (Bearer / `X-API-Key`),
  **CSRF-exempt** (stateless). Mirrors the `put/list/delete/fetch` shape
  of TS Pro's backup backends.

**Schema migrations:** no Alembic. `_migrate_sqlite()` in
`app/__init__.py` runs every boot and additively `ALTER TABLE ADD COLUMN`s
missing columns. **When you add a model column, add a matching entry
there too** or upgraded deployments break. `db.create_all()` handles
fresh installs.

**Models** (`app/models.py`): `AdminUser` (console operators), `Setting`
(singleton row id=1: Turnstile config, at-rest toggle, default
retention), `Site` (one connected TS Pro instance; API key stored as
SHA-256 hash + visible prefix; per-site retention / encryption
overrides; **`e2ee_public_key`** — the site's `tsppk_…` recipient public
key, the private half is shown once and never stored), `Backup` (one
stored archive; `scope` is `full` whole-site or `frontend` frontend-only;
records original size/sha256 and whether the on-disk bytes are wrapped at
rest).

**E2EE crypto** (`app/pubkey.py`): the real end-to-end layer. Per-site
X25519 keypair; hybrid `TSPEPK01` envelope (ephemeral X25519 + HKDF-SHA256
+ streaming AES-256-GCM, 1 MiB blocks). The client encrypts each backup to
the site's public key (`Site.issue_keypair()` mints the pair, `/ping`
hands out the public key); only the operator's private key decrypts, at
restore. The server never holds the private key, never decrypts. Must stay
byte-identical to TS Pro's `app/pubkey.py`. The upload gate
(`api.py`) requires this envelope when `require_e2ee` and the site has a
key.

**Storage** (`app/storage.py`): blobs live at
`<DATA_DIR>/storage/site-<id>/<uuid>.bin`. `ingest()` hashes the upload,
sniffs whether TS Pro already client-encrypted it, optionally wraps it
with `app/restenc.py`, writes it, creates the `Backup` row, then calls
retention. `open_for_download()` unwraps at-rest blobs to a temp file.

**At-rest crypto** (`app/restenc.py`): streaming AES-256-GCM,
PBKDF2-HMAC-SHA256 (600k iters), 1 MiB blocks. Shares the `TSPENC01`
envelope format with TS Pro's `app/bundle_crypto.py`. Passphrase from
`TSPB_REST_PASSPHRASE` or an auto-generated `<DATA_DIR>/rest.key`.

**Secret crypto** (`app/crypto.py`): Fernet for the Turnstile secret key,
mirroring TS Pro's `app/crypto.py`. Key from `TSPB_FERNET_KEY` or
`<DATA_DIR>/secret.key`.

**Retention** (`app/retention.py`): GFS. `survivors()` is pure — keeps the
newest backup in each of the last N distinct days/weeks/months/years per
tier; `prune_site_scope()` deletes the rest. Runs **per scope** so
frontend snapshots never evict whole-site backups. All-zero policy = keep
everything (never wipe a site to zero by accident).

## Configuration

`TSPB_SECRET_KEY` (Flask session secret — required), `TSPB_FERNET_KEY`
(optional explicit Fernet seed), `TSPB_REST_PASSPHRASE` (optional at-rest
passphrase), `TSPB_ADMIN_USERNAME`/`TSPB_ADMIN_PASSWORD` (seed only),
`TSPB_DATA_DIR` (default `/data`), `TSPB_MAX_UPLOAD_MB` (default `8192`),
`TSPB_DEBUG` (plain-HTTP dev cookies).

## API quick reference (`/api/v1`)

Auth: `Authorization: Bearer <key>` or `X-API-Key: <key>`.

- `GET  /ping` — auth check + capabilities (scopes, retention, encrypt-at-rest, `require_e2ee`, `e2ee_alg`, `e2ee_public_key`).
- `POST /backups` — multipart `file=<archive>`, `scope=full|frontend`, optional `note`. Returns the stored backup. (Single-shot; for archives larger than a fronting proxy's body cap use the chunked pair below.)
- `POST /backups/chunk` — one part of a chunked upload: `upload_id` (client UUID), `chunk_index`, `total_chunks`, `chunk=<bytes>`. Staged under `upload-chunks/site-<id>/<upload_id>/`.
- `POST /backups/finalize` — reassemble `upload_id`'s chunks, run the E2EE gate + ingest, return the stored backup. Fields: `upload_id`, `scope`, `filename`, `total_chunks`, optional `note`.
- `GET  /backups[?scope=]` — list this site's backups.
- `GET  /backups/<id>` — one backup's metadata.
- `GET  /backups/<id>/download` — download original bytes (at-rest layer removed).
- `DELETE /backups/<id>` — delete one.
