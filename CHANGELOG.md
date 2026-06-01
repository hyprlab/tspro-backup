# Changelog

All notable changes to **TS Pro Backup** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-06-01

First public release. An off-site, zero-knowledge backup server for
[Trusted Servants Pro](https://github.com/viibeware): TS Pro portals push
their backup archives here over an authenticated HTTP API, and this server
stores them under a grandfather-father-son retention policy with a web
console to manage it all.

### Added

- **End-to-end encryption (default on).** Each site gets its own X25519
  keypair. TS Pro encrypts every archive to the site's **public** key
  before upload using a hybrid `TSPEPK01` envelope (ephemeral X25519 +
  HKDF-SHA256 + streaming AES-256-GCM in 1 MiB blocks). The matching
  **private** key is shown once at site creation and never stored on the
  server, so stored archives are unreadable to the server even if it is
  fully compromised. When `require_e2ee` is on, the upload gate rejects any
  archive that isn't already wrapped in this envelope.
- **Encryption at rest.** Optional defense-in-depth layer over the storage
  volume: streaming AES-256-GCM with PBKDF2-HMAC-SHA256 (600k iterations),
  1 MiB blocks, `TSPENC01` envelope. Server-wide or per-site. Passphrase
  from `TSPB_REST_PASSPHRASE`, or an auto-generated `data/rest.key`.
- **Grandfather-father-son retention.** Keep the newest backup in each of
  the last N distinct days / weeks / months / years, per tier. Runs
  independently **per scope**, so frontend snapshots never evict whole-site
  backups. An all-zero policy keeps everything (no accidental wipe to zero).
- **HTTP API (`/api/v1`).** Per-site API key auth (Bearer / `X-API-Key`),
  CSRF-exempt and stateless. Endpoints: `ping`, single-shot and chunked
  uploads (`backups`, `backups/chunk`, `backups/finalize`), `list`,
  `metadata`, `download`, and `delete` — mirroring TS Pro's existing
  backup-backend interface.
- **Chunked uploads** for archives larger than a fronting proxy's body cap:
  stage chunks by `upload_id`, then reassemble and ingest on finalize.
- **Two backup scopes:** `full` (whole-site export) and `frontend`
  (frontend-only snapshot), retained separately.
- **Web console**, styled to match Trusted Servants Pro: dashboard,
  per-site management with one-time API-key + private-key reveal, and a
  backup browser with download / delete.
- **Cloudflare Turnstile** support on the console login (optional). The
  Turnstile secret is stored encrypted with Fernet (`app/crypto.py`).
- **Additive SQLite migrations** at boot (`_migrate_sqlite()`): missing
  columns are added with `ALTER TABLE ADD COLUMN`, so upgrades are safe
  without Alembic. Fresh installs use `db.create_all()`.
- **Docker deployment.** `python:3.12-slim` image served by gunicorn
  (2 workers, 600s timeout for multi-GB bundles). Data persisted to a
  mounted `/data` volume. Published as
  [`viibeware/tspro-backup`](https://hub.docker.com/r/viibeware/tspro-backup).

[1.0.0]: https://github.com/viibeware/tspro-backup/releases/tag/v1.0.0
