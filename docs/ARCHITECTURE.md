# Architecture

How the pieces fit together, and why. TS Pro Backup is the receiving half of
an off-site backup pair: each Trusted Servants Pro portal has a "TS Pro
Backup" backup target that speaks this server's [API](API.md).

## The app

A Flask app factory (`app/__init__.py`, `create_app`) with SQLAlchemy on
SQLite, served by gunicorn in one container. Three blueprints:

| Blueprint | File | What it does |
|---|---|---|
| `auth` | `app/auth.py` | Console sign-in and sign-out, the forced password change, Cloudflare Turnstile |
| `main` | `app/routes.py` | The web console: dashboard, sites, backups, remote restore, settings, accounts. Session cookies through Flask-Login |
| `api` | `app/api.py` | `/api/v1`, the protocol TS Pro speaks. Authenticated by a per-site API key and CSRF-exempt, because it is stateless |

## Models

In `app/models.py`:

- `AdminUser`: a console account, `admin` or `user`.
- `Setting`: one row (id 1) with the Turnstile configuration, the
  encryption-at-rest switch and the default retention.
- `Site`: one connected TS Pro portal. The API key is stored as a SHA-256
  hash plus a visible prefix. Per-site retention and encryption overrides,
  the site's `e2ee_public_key` (`tsppk_...`), and the remote-restore
  pairing (callback URL, an encrypted restore token, the host an admin
  pinned or confirmed).
- `Backup`: one stored archive. `scope` is `full` (the whole portal) or
  `frontend` (the public frontend only). Records the original size and
  SHA-256, and whether the bytes on disk are wrapped at rest.

## Schema migrations

There is no Alembic. `_migrate_sqlite()` in `app/__init__.py` runs at every
boot and adds any missing column with `ALTER TABLE ADD COLUMN`;
`db.create_all()` handles fresh installs. A new model column needs a matching
entry there, or upgraded installs break. A migration an older version can't
read back is a MAJOR release ([RELEASING.md](RELEASING.md)).

## Storage

Archives live at `<DATA_DIR>/storage/site-<id>/<uuid>.bin`.
`storage.ingest()` hashes the upload, detects whether TS Pro already
encrypted it, optionally wraps it at rest, writes it under a `.part` name and
renames it when complete, creates the `Backup` row, then applies retention.
`open_for_download()` removes the at-rest layer into a temporary file.

Chunked uploads are staged under `upload-chunks/site-<id>/<upload_id>/` and
reassembled at finalize. A background reaper removes abandoned chunks.

## Encryption

Three separate layers, each with its own key:

| Layer | Code | Key held by | Protects against |
|---|---|---|---|
| End-to-end | `app/pubkey.py` | The operator only | Anyone with the server or its storage |
| At rest | `app/restenc.py` | The server | Someone with the storage volume but not the key |
| Stored secrets | `app/crypto.py` | The server | Reading the Turnstile secret or restore tokens straight from the database |

**End-to-end** is the real protection. Each site has an X25519 keypair,
minted by `Site.issue_keypair()`; the private half is shown once and never
stored. `/ping` hands out the public key, and TS Pro encrypts every backup to
it in a hybrid `TSPEPK01` envelope: ephemeral X25519, HKDF-SHA256, then
streaming AES-256-GCM in 1 MiB blocks. The server never holds the private key
and never decrypts. The upload gate in `app/api.py` refuses anything that is
not a well-formed envelope when the site requires end-to-end encryption.
`app/pubkey.py` must stay byte-identical to TS Pro's copy.

**At rest** is streaming AES-256-GCM with PBKDF2-HMAC-SHA256 (600,000
iterations) in 1 MiB blocks, in the `TSPENC01` format shared with TS Pro's
`app/bundle_crypto.py`. The passphrase comes from `TSPB_REST_PASSPHRASE` or a
generated `<DATA_DIR>/rest.key`.

**Stored secrets** use Fernet, as in TS Pro's `app/crypto.py`, keyed from
`TSPB_FERNET_KEY` or a generated `<DATA_DIR>/secret.key`.

## Retention

Grandfather-father-son, in `app/retention.py`. `survivors()` is a pure
function: it keeps the newest backup in each of the last N distinct days,
weeks, months and years. `prune_site_scope()` deletes the rest. It runs per
scope, so frontend snapshots never evict whole-site backups. A policy of all
zeros keeps everything, so a misconfiguration can never empty a site.

## Remote restore

The console can push a stored full backup back into the live TS Pro portal,
for a corrupted database or a locked-out admin. The portal registers its
public URL and a shared restore token through `POST /api/v1/register`;
`app/restore_push.py` then streams the stored ciphertext to the portal's
inbound restore endpoints, together with the operator's private key, which
passes through in memory and is never stored or logged.

The portal accepts a restore only with both the token and a private key
matching the site's public key, so a stolen token alone can't push an
archive. Pushes refuse plain HTTP and never follow redirects. When the
registered endpoint changes, the operator must confirm it by typing its
hostname, and an admin can pin the expected host per site. Decryption
happens only on the portal; this server stays unable to read the backups.
